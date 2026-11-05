from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx

from voice.contracts import SpokenAnswer
from voice.errors import VoiceTTSError
from voice.settings import VoiceSettings, load_default_settings, load_string_mapping
from voice.spoken_answer import estimate_spoken_seconds
from voice.tts import PlaybackHandle


_DEFAULT_ENDPOINT = "http://127.0.0.1:50000"
_DEFAULT_TIMEOUT_SECONDS = 20.0


class CosyVoiceTTSProvider:
    """Real TTS provider backed by the local CosyVoice 3 HTTP service."""

    name = "cosyvoice"

    def __init__(
        self,
        *,
        settings: VoiceSettings | None = None,
        pronunciation_lexicon: Mapping[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        resolved_settings = settings or load_default_settings()
        self.settings = resolved_settings
        self.pronunciation_lexicon = (
            dict(pronunciation_lexicon)
            if pronunciation_lexicon is not None
            else load_string_mapping(resolved_settings.pronunciation_lexicon_path)
        )
        tts_config = resolved_settings.tts_config
        endpoint = str(tts_config.get("endpoint") or _DEFAULT_ENDPOINT).rstrip("/")
        timeout_raw = tts_config.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
        self._endpoint = endpoint
        self._timeout_seconds = float(timeout_raw)
        self._transport = transport

    async def synthesize_stream(
        self,
        answer: SpokenAnswer,
        config: Mapping[str, Any],
    ) -> PlaybackHandle:
        if not isinstance(answer, SpokenAnswer):
            raise VoiceTTSError("answer must be a SpokenAnswer", field="answer")
        if (
            not isinstance(answer.source_evidence_package_id, str)
            or not answer.source_evidence_package_id.strip()
        ):
            raise VoiceTTSError(
                "spoken answer requires evidence provenance",
                field="source_evidence_package_id",
            )
        if not isinstance(config, Mapping):
            raise VoiceTTSError("TTS config must be a mapping", field="config")
        allowed = {"max_seconds", "chunk_delay_seconds"}
        unknown = sorted(set(config) - allowed)
        if unknown:
            raise VoiceTTSError("unknown TTS config key", field=str(unknown[0]))
        max_seconds = config.get("max_seconds", self.settings.max_spoken_answer_seconds)
        if (
            isinstance(max_seconds, bool) or not isinstance(max_seconds, int) or max_seconds <= 0
        ):
            raise VoiceTTSError("max_seconds must be a positive integer", field="max_seconds")
        if max_seconds > self.settings.max_spoken_answer_seconds:
            raise VoiceTTSError(
                "max_seconds must not exceed the configured maximum",
                field="max_seconds",
            )
        delay = config.get("chunk_delay_seconds", 0.0)
        if isinstance(delay, bool) or not isinstance(delay, (int, float)) or delay < 0:
            raise VoiceTTSError(
                "chunk_delay_seconds must be a non-negative number",
                field="chunk_delay_seconds",
            )
        display_segments = tuple(
            part
            for part in (
                answer.answer_brief,
                *answer.spoken_steps,
                answer.follow_up_prompt,
            )
            if part
        )
        segments = tuple(self._apply_pronunciation(part) for part in display_segments)
        text = "".join(segments)
        if estimate_spoken_seconds(
            text,
            characters_per_second=self.settings.spoken_chars_per_second,
        ) > max_seconds:
            raise VoiceTTSError("spoken answer exceeds TTS duration budget", field="max_seconds")
        return PlaybackHandle(
            provider=self.name,
            segments=segments,
            encoder=self._encode_segment,
            spoken_chars_per_second=self.settings.spoken_chars_per_second,
            chunk_delay_seconds=float(delay),
            audio_codec="mp3",
        )

    async def _encode_segment(
        self,
        segment: str,
        sequence_no: int,
        cancel_event: asyncio.Event,
    ) -> bytes | None:
        await asyncio.sleep(0)
        if cancel_event.is_set():
            return None

        try:
            async with asyncio.timeout(self._timeout_seconds):
                async with httpx.AsyncClient(
                    timeout=self._timeout_seconds,
                    transport=self._transport,
                ) as client:
                    response = await client.post(
                        f"{self._endpoint}/inference_zero_shot",
                        data={"tts_text": segment},
                    )
        except (TimeoutError, httpx.TimeoutException):
            raise VoiceTTSError(
                "TTS segment stream timed out",
                field="stream_timeout",
                details={"segment_sequence_no": sequence_no},
            ) from None
        if cancel_event.is_set():
            return None
        if response.status_code != 200:
            raise VoiceTTSError(
                "CosyVoice HTTP synthesis failed",
                field="tts",
                details={
                    "status_code": response.status_code,
                    "segment_sequence_no": sequence_no,
                },
            )
        if not response.content:
            raise VoiceTTSError(
                "CosyVoice returned empty audio payload",
                field="tts",
                details={"segment_sequence_no": sequence_no},
            )
        return response.content

    def _apply_pronunciation(self, segment: str) -> str:
        spoken = segment
        for written, pronunciation in self.pronunciation_lexicon.items():
            spoken = spoken.replace(written, pronunciation)
        return spoken
