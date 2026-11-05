"""VR7-T17 run_voice 启动顺序单元测试（语音真机修复专项）。

验证 :func:`run_voice.prewarm_asr` 与 ``run_voice.main`` 的启动契约：
  - 配置启用（asr_provider=whisper 且 asr_config.prewarm）时，模型在 serve_voice 之前预热；
  - 禁用/未启用时完全不加载（no-op）；
  - 预热失败直接阻止启动（serve_voice 不会被调用）。
通过 monkeypatch 拦截 provider 的 prewarm 与 serve_voice，不加载真实模型、不监听真实端口。
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
import sys
from typing import Any

import httpx
import pytest

from voice.errors import VoiceASRError

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import run_voice  # noqa: E402
import voice.qwen_asr as qwen_asr  # noqa: E402
import voice.whisper_asr as whisper_asr  # noqa: E402
from voice.settings import VoiceSettings  # noqa: E402


class _FakeSocket:
    def getsockname(self) -> tuple[str, int]:
        return ("127.0.0.1", 12345)


class _FakeServer:
    def __init__(self) -> None:
        self.sockets = [_FakeSocket()]

    async def wait_closed(self) -> None:
        return None

    def close(self) -> None:
        return None


def _recording_prewarm(order: list[str]) -> Any:
    async def _prewarm(self: object) -> None:  # noqa: ARG001
        order.append("prewarm")

    return _prewarm


def _recording_serve(order: list[str]) -> Any:
    async def _serve(*args: object, **kwargs: object) -> _FakeServer:
        order.append("serve")
        return _FakeServer()

    return _serve


def test_prewarm_disabled_does_not_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """asr_config 未启用 prewarm 时 prewarm_asr 必须是 no-op（不构造 provider、不加载）。"""

    def boom_prewarm(self: object) -> Any:
        raise AssertionError("prewarm must not run when disabled")

    monkeypatch.setattr(whisper_asr.WhisperASRProvider, "prewarm", boom_prewarm)

    # asr_provider=whisper 但 asr_config 无 prewarm —— 应从 prewarm_asr 直接返回。
    provider_ctor_calls: list[object] = []

    class SpyProvider(whisper_asr.WhisperASRProvider):
        def __init__(self, *args: object, **kwargs: object) -> None:
            provider_ctor_calls.append(1)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(whisper_asr, "WhisperASRProvider", SpyProvider)

    settings = _make_settings()
    asyncio.run(run_voice.prewarm_asr(settings))

    assert provider_ctor_calls == [], "disabled prewarm must not even construct the provider"


def test_prewarm_happens_before_serve_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    """监听顺序：prewarm 完成于 serve_voice 之前（真实仓库配置 prewarm: true）。"""
    order: list[str] = []
    monkeypatch.setattr(whisper_asr.WhisperASRProvider, "prewarm", _recording_prewarm(order))
    monkeypatch.setattr(qwen_asr.QwenASRProvider, "prewarm", _recording_prewarm(order))
    monkeypatch.setattr(run_voice, "serve_voice", _recording_serve(order))
    monkeypatch.setattr(sys, "argv", ["run_voice.py", "--port", "0"])

    asyncio.run(run_voice.main())

    assert order == ["prewarm", "serve"], "prewarm must complete before the server opens"


def test_prewarm_failure_blocks_startup_serve_never_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """配置启用时预热失败 -> 直接阻止启动：serve_voice 不会被调用。"""
    order: list[str] = []

    async def failing_prewarm(self: object) -> None:  # noqa: ARG001
        raise VoiceASRError(
            "whisper model could not be loaded",
            field="asr",
            details={"provider": "whisper", "reason": "model_load_failed"},
        )

    monkeypatch.setattr(whisper_asr.WhisperASRProvider, "prewarm", failing_prewarm)
    monkeypatch.setattr(qwen_asr.QwenASRProvider, "prewarm", failing_prewarm)
    monkeypatch.setattr(run_voice, "serve_voice", _recording_serve(order))
    monkeypatch.setattr(sys, "argv", ["run_voice.py", "--port", "0"])

    with pytest.raises(VoiceASRError):
        asyncio.run(run_voice.main())

    assert order == [], "serve_voice must never run when prewarm fails"


def _capturing_serve(captured: dict[str, object]) -> Any:
    async def _serve(*args: object, **kwargs: object) -> _FakeServer:
        captured.update(kwargs)
        return _FakeServer()

    return _serve


def test_idle_timeout_default_covers_inference_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-4：生产入口默认 idle 预算须覆盖最长单步推理（whisper/bge_m3/DeepSeek 60s）。"""
    captured: dict[str, object] = {}
    monkeypatch.setattr(whisper_asr.WhisperASRProvider, "prewarm", _recording_prewarm([]))
    monkeypatch.setattr(qwen_asr.QwenASRProvider, "prewarm", _recording_prewarm([]))
    monkeypatch.setattr(run_voice, "serve_voice", _capturing_serve(captured))
    monkeypatch.setattr(sys, "argv", ["run_voice.py", "--port", "0"])

    asyncio.run(run_voice.main())

    assert captured["idle_timeout_seconds"] == run_voice.DEFAULT_IDLE_TIMEOUT_SECONDS
    assert run_voice.DEFAULT_IDLE_TIMEOUT_SECONDS >= 90.0, (
        "idle 预算必须大于 DeepSeek 60s 提供方超时加 whisper 推理余量"
    )


def test_idle_timeout_cli_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """P1-4：--idle-timeout 显式传值必须原样传给 serve_voice。"""
    captured: dict[str, object] = {}
    monkeypatch.setattr(whisper_asr.WhisperASRProvider, "prewarm", _recording_prewarm([]))
    monkeypatch.setattr(qwen_asr.QwenASRProvider, "prewarm", _recording_prewarm([]))
    monkeypatch.setattr(run_voice, "serve_voice", _capturing_serve(captured))
    monkeypatch.setattr(
        sys, "argv", ["run_voice.py", "--port", "0", "--idle-timeout", "45"]
    )

    asyncio.run(run_voice.main())

    assert captured["idle_timeout_seconds"] == 45.0


def _make_settings() -> VoiceSettings:
    """Whisper + 无 prewarm 的 settings（用于禁用 no-op 验证）。"""
    return VoiceSettings(
        transport="websocket",
        sample_rate=16000,
        channel_count=1,
        frame_duration_ms=20,
        vad_provider="mock",
        vad_threshold=0.2,
        endpoint_silence_ms=600,
        asr_provider="whisper",
        asr_low_confidence_threshold=0.40,
        tts_provider="mock",
        max_utterance_ms=15000,
        max_frames=750,
        max_audio_bytes=480000,
        max_spoken_answer_seconds=20,
        max_spoken_answer_chars=180,
        spoken_chars_per_second=6.0,
        min_spoken_explanation_steps=2,
        max_spoken_explanation_steps=3,
        barge_in_enabled=True,
        barge_in_priority=100,
        raw_audio_persist_enabled=False,
        raw_transcript_logging_enabled=False,
        raw_transcript_retention_seconds=0,
        raw_transcript_redaction_mode="full",
        terminology_lexicon_path=ROOT / "configs" / "voice_terminology.yaml",
        pronunciation_lexicon_path=ROOT / "configs" / "voice_pronunciation.yaml",
        terminology_lexicon_digest="0" * 64,
        simplification_lexicon_digest="0" * 64,
        pronunciation_lexicon_digest="0" * 64,
        asr_config={"model_size": "small", "device": "cpu", "compute_type": "int8"},
        tts_config={},
    )

def _cosyvoice_settings() -> VoiceSettings:
    return replace(
        _make_settings(),
        tts_provider="cosyvoice",
        tts_config={"endpoint": "http://127.0.0.1:50000"},
    )


def _use_http_mock(
    monkeypatch: pytest.MonkeyPatch, handler: Any
) -> None:
    real_async_client = httpx.AsyncClient

    class _Client(real_async_client):
        def __init__(self, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


def test_check_tts_ready_unreachable_service_warns_and_returns(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("service not running")

    _use_http_mock(monkeypatch, handler)
    asyncio.run(run_voice.check_tts_ready(_cosyvoice_settings()))
    assert "尚未就绪" in capsys.readouterr().out


def test_check_tts_ready_healthy_service_is_silent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok", "ready": True, "busy": False})

    _use_http_mock(monkeypatch, handler)
    asyncio.run(run_voice.check_tts_ready(_cosyvoice_settings()))
    assert capsys.readouterr().out == ""


def test_check_tts_ready_noop_for_non_cosyvoice(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ready": True})

    _use_http_mock(monkeypatch, handler)
    asyncio.run(run_voice.check_tts_ready(_make_settings()))
    assert calls == []
