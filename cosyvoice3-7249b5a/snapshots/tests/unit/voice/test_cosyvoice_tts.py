from __future__ import annotations

import asyncio
from urllib.parse import parse_qs

import httpx
import pytest

from voice.contracts import PlaybackHandleState, SpokenAnswer
from voice.cosyvoice_tts import CosyVoiceTTSProvider
from voice.errors import VoiceTTSError
from voice.settings import VoiceSettings
from voice.tts import PlaybackHandle


KNOWN_PROVIDERS = {
    "transport": {"websocket", "in_memory"},
    "vad": {"mock"},
    "asr": {"mock", "whisper", "qwen3_asr"},
    "tts": {"mock", "cosyvoice"},
}


def _provider(transport: httpx.AsyncBaseTransport | None = None) -> CosyVoiceTTSProvider:
    settings = VoiceSettings.from_file(
        "configs/voice.yaml",
        known_providers=KNOWN_PROVIDERS,
    )
    return CosyVoiceTTSProvider(settings=settings, transport=transport)


def _spoken() -> SpokenAnswer:
    return SpokenAnswer(
        answer_brief="C919 采用双发布局。",
        spoken_steps=("RAG 只用已审核证据。", "AG600 是水陆两栖飞机。"),
        follow_up_prompt="还要了解 C919 吗？",
        source_answer_id="answer_1",
        source_evidence_package_id="evidence_pkg_1",
    )


def test_cosyvoice_tts_provider_name_and_constructs() -> None:
    assert CosyVoiceTTSProvider.name == "cosyvoice"
    provider = _provider()
    assert isinstance(provider.pronunciation_lexicon, dict)
    assert provider.pronunciation_lexicon


def test_streaming_tts_emits_one_complete_mp3_chunk_per_segment() -> None:
    recorded_texts: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/inference_zero_shot"
        form = parse_qs(request.content.decode("utf-8"))
        tts_text = form["tts_text"][0]
        recorded_texts.append(tts_text)
        return httpx.Response(200, content=b"MP3:" + tts_text.encode("utf-8"))

    transport = httpx.MockTransport(handler)

    async def exercise():
        provider = _provider(transport=transport)
        answer = _spoken()
        handle = await provider.synthesize_stream(answer, {"chunk_delay_seconds": 0})
        chunks = []
        async for chunk in handle.chunks():
            chunks.append(chunk)
            handle.mark_played(chunk)
        return provider, handle, chunks

    provider, handle, chunks = asyncio.run(exercise())

    assert [chunk.sequence_no for chunk in chunks] == [0, 1, 2, 3]
    assert [chunk.is_final for chunk in chunks] == [False, False, False, True]
    assert isinstance(handle, PlaybackHandle)
    assert handle.provider == "cosyvoice"
    assert handle.state is PlaybackHandleState.COMPLETED
    assert handle.raw_audio_persisted is False

    expected_texts = [
        "C 九一九 采用双发布局。",
        "R A G 只用已审核证据。",
        "A G 六百 是水陆两栖飞机。",
        "还要了解 C 九一九 吗？",
    ]
    assert recorded_texts == expected_texts
    for chunk, expected in zip(chunks, expected_texts):
        assert chunk.payload == b"MP3:" + expected.encode("utf-8")
        assert chunk.codec == "mp3"
        assert chunk.duration_ms > 0


def test_cosyvoice_encoder_returns_none_when_cancel_event_is_set() -> None:
    async def exercise():
        provider = _provider()
        cancel_event = asyncio.Event()
        cancel_event.set()
        return await provider._encode_segment("APU 正常", 0, cancel_event)

    assert asyncio.run(exercise()) is None


def test_cosyvoice_encoder_times_out_when_service_hangs() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5.0)
        return httpx.Response(200, content=b"MP3")

    async def exercise():
        provider = _provider(transport=httpx.MockTransport(handler))
        provider._timeout_seconds = 0.05
        with pytest.raises(VoiceTTSError) as exc_info:
            await provider._encode_segment("hang", 0, asyncio.Event())
        return exc_info.value

    err = asyncio.run(exercise())
    assert err.details.get("field") == "stream_timeout" or err.field == "stream_timeout"


def test_cosyvoice_http_failure_marks_playback_failed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"busy")

    async def exercise():
        provider = _provider(transport=httpx.MockTransport(handler))
        handle = await provider.synthesize_stream(_spoken(), {"chunk_delay_seconds": 0})
        with pytest.raises(VoiceTTSError):
            async for _ in handle.chunks():
                pass
        return handle

    handle = asyncio.run(exercise())
    assert handle.state is PlaybackHandleState.FAILED
    assert handle.error_code == "VOICE_TTS_ERROR"


def test_cosyvoice_rejects_answer_without_evidence_provenance() -> None:
    provider = _provider()
    bad = _spoken()
    object.__setattr__(bad, "source_evidence_package_id", None)
    with pytest.raises(VoiceTTSError) as caught:
        asyncio.run(provider.synthesize_stream(bad, {}))
    assert caught.value.code == "VOICE_TTS_ERROR"
    assert caught.value.field == "source_evidence_package_id"


def test_cosyvoice_rejects_unknown_config_key() -> None:
    provider = _provider()
    with pytest.raises(VoiceTTSError):
        asyncio.run(provider.synthesize_stream(_spoken(), {"bad_key": 1}))


def test_cosyvoice_rejects_answer_over_duration_budget() -> None:
    provider = _provider()
    with pytest.raises(VoiceTTSError):
        asyncio.run(provider.synthesize_stream(_spoken(), {"max_seconds": 1}))


def test_cancel_during_active_request_cleans_up_before_cancel_returns() -> None:
    cleaned = []
    entered = asyncio.Event()
    request_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            cleaned.append(request_count)
        return httpx.Response(200, content=b"MP3")

    async def exercise():
        provider = _provider(transport=httpx.MockTransport(handler))
        handle = await provider.synthesize_stream(_spoken(), {"chunk_delay_seconds": 0})

        async def consume():
            async for _ in handle.chunks():
                pass

        consumer = asyncio.create_task(consume())
        await asyncio.wait_for(entered.wait(), timeout=2.0)
        result = await handle.cancel("interrupted")
        assert result is True
        # Cleanup in the HTTP handler finished before cancel() returned.
        assert cleaned == [1]
        # No further segments were requested after cancellation.
        assert request_count == 1
        await asyncio.wait_for(consumer, timeout=2.0)
        assert handle.state is PlaybackHandleState.CANCELLED
        # No leftover request/event tasks for this handle.
        current = asyncio.current_task()
        leftovers = [
            t for t in asyncio.all_tasks()
            if t is not current and t is not consumer and not t.done()
        ]
        assert leftovers == []

    asyncio.run(exercise())
