from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx
import pytest

from app.api.schemas import TextQueryRequest, TextQueryResponse
from tests.fixtures.canonical_answer import canonical_answer, canonical_claim
from voice.asr import MockASRProvider
from voice.contracts import ASRResult, AudioFrame, VoiceMetricRecord
from voice.cosyvoice_tts import CosyVoiceTTSProvider
from voice.metrics import VoiceMetricsRecorder
from voice.mock_client import MockVoiceClient, MockVoiceScenario
from voice.orchestrator import VoiceSessionOrchestrator
from voice.providers import ProviderRegistry
from voice.session_state import VoiceState
from voice.settings import VoiceSettings
from voice.transport import WebSocketAudioTransport
from voice.vad import MockVADService
from voice.websocket_server import serve_voice


class _Pipeline:
    def __init__(self) -> None:
        self.requests: list[TextQueryRequest] = []

    def run_text_query(self, request: TextQueryRequest) -> TextQueryResponse:
        self.requests.append(request)
        return TextQueryResponse(
            run_id="tts-degradation-run",
            status="ok",
            answer=canonical_answer(
                answer_id="answer-degradation",
                short_answer="机翼通过改变气流产生升力。",
                main_answer=(
                    "机翼通过改变气流产生升力。"
                    "上下表面压强差形成向上的合力。"
                    "气流向下偏转也会带来向上的反作用力。"
                    "这两种作用共同解释了机翼产生升力的过程。"
                ),
                claim_candidates=(
                    canonical_claim(
                        "claim-degradation",
                        (
                            "机翼通过改变气流产生升力。"
                            "上下表面压强差形成向上的合力。"
                            "气流向下偏转也会带来向上的反作用力。"
                            "这两种作用共同解释了机翼产生升力的过程。"
                        ),
                        evidence_ids=("evidence-degradation",),
                    ),
                ),
                evidence_refs=("evidence-degradation",),
                follow_up_questions=(),
            ).to_public_dict(),
            action_decision="PASS",
            final_answer_id="answer-degradation",
            evidence_package_id="evidence-package-degradation",
            check_report_id="check-degradation",
            self_check_completed=True,
        )


def _frames(session_id: str, turn_id: str) -> tuple[AudioFrame, ...]:
    stream_id = f"stream-{turn_id}"
    return (
        AudioFrame(
            session_id,
            turn_id,
            stream_id,
            0,
            b"\xff\x7f" * 160,
            energy=0.8,
        ),
        *tuple(
            AudioFrame(
                session_id,
                turn_id,
                stream_id,
                sequence,
                b"\x00\x00" * 160,
                client_timestamp_ms=sequence * 20,
                energy=0.0,
            )
            for sequence in range(1, 31)
        ),
    )


@pytest.mark.parametrize("failure_mode", ["http_503", "connect_error"])
def test_tts_failure_degrades_to_display_answer_and_clarify(failure_mode: str) -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if failure_mode == "http_503":
            return httpx.Response(503, content=b"busy")
        raise httpx.ConnectError("simulated TTS network outage")

    async def exercise():
        settings = replace(
            VoiceSettings.from_file("configs/voice.yaml"),
            asr_provider="mock",
            tts_provider="cosyvoice",
        )
        pipeline = _Pipeline()
        metrics: list[VoiceMetricRecord] = []
        registry = ProviderRegistry()
        registry.register_transport("websocket", WebSocketAudioTransport)
        registry.register_vad("mock", MockVADService)
        registry.register_asr(
            "mock",
            lambda **_kwargs: MockASRProvider(
                events=(
                    ASRResult("机翼升力", 0.95, False),
                    ASRResult("机翼升力", 0.95, True),
                )
            ),
        )
        registry.register_tts(
            "cosyvoice",
            lambda **_kwargs: CosyVoiceTTSProvider(
                settings=settings, transport=httpx.MockTransport(handler)
            ),
        )
        orchestrator = VoiceSessionOrchestrator(
            pipeline=pipeline,
            settings=settings,
            provider_registry=registry,
            metrics_recorder=VoiceMetricsRecorder(writer=metrics.append),
        )
        server = await serve_voice("127.0.0.1", 0, orchestrator)
        port = int(server.sockets[0].getsockname()[1])
        session_id = "session-tts-fail"
        turn_id = "turn-tts-fail"
        client = MockVoiceClient(f"ws://127.0.0.1:{port}")
        try:
            events = await client.run_scenario(
                MockVoiceScenario(
                    session_id=session_id,
                    turn_id=turn_id,
                    audio_stream_id=f"stream-{turn_id}",
                    frames=_frames(session_id, turn_id),
                )
            )
        finally:
            server.close()
            await server.wait_closed()
            await orchestrator.drain_metrics()
        return events, pipeline, metrics

    events, pipeline, metrics = asyncio.run(exercise())
    event_types = [event["type"] for event in events]

    # The trusted answer was produced and displayed before TTS playback.
    assert "answer.display" in event_types
    display = next(event for event in events if event["type"] == "answer.display")
    assert display["answer_id"] == "answer-degradation"
    assert len(pipeline.requests) == 1
    assert request_count == 1

    # No audio chunk was ever delivered because synthesis failed.
    assert "tts.chunk" not in event_types

    # The websocket adapter reported the TTS failure and the failed playback.
    error = next(event for event in events if event["type"] == "voice.error")
    assert error["code"] == "VOICE_TTS_ERROR"
    assert error["field"] == "tts"
    failed = next(
        event
        for event in events
        if event["type"] == "voice.state" and event["status"] == "playback.failed"
    )
    assert failed["session_id"] == "session-tts-fail"

    # The orchestrator recorded the display-only degradation on a metric
    # record whose state was captured while the state machine was in CLARIFY.
    degraded = next(
        record for record in metrics if record.degradation_action == "display_answer_only"
    )
    assert degraded.state is VoiceState.CLARIFY
    assert degraded.error_code == "VOICE_TTS_ERROR"
    assert degraded.clarification_reason == "spoken_playback_failed"
    assert degraded.clarification_count == 1
    assert any(
        transition.get("to_state") == "CLARIFY" for transition in degraded.transitions
    )
    assert degraded.raw_audio_persisted is False
    assert degraded.private_payload_logged is False
