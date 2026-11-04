"""Real ASR provider backed by Qwen3-ASR-0.6B via Transformers native pipeline.

Transformers and torch are imported lazily inside `_get_model_and_processor` so
that importing this module never downloads or loads the Qwen3-ASR model.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from math import exp
from pathlib import Path
from typing import Any

import numpy as np

from voice.contracts import ASRResult, AudioFrame
from voice.errors import VoiceASRError
from voice.settings import VoiceSettings


_SAMPLE_WIDTH_BYTES = 2  # int16 little-endian PCM
_ASR_RESULT_LANGUAGE = "zh-CN"

# (model_id, revision, device, dtype) -> (model, processor) instance
_MODEL_CACHE: dict[tuple[str, str, str, str], tuple[object, object]] = {}
_MODEL_LOCKS: dict[tuple[str, str, str, str], asyncio.Lock] = {}


def _inference_lock(key: tuple[str, str, str, str]) -> asyncio.Lock:
    lock = _MODEL_LOCKS.get(key)
    if lock is None:
        lock = _MODEL_LOCKS.setdefault(key, asyncio.Lock())
    return lock


class QwenASRProvider:
    """Qwen3-ASR provider implementing the `ASRProvider` protocol."""

    name = "qwen3_asr"

    default_model_id = "./models/Qwen3-ASR-0.6B-hf"
    default_revision = "7f1569a48a89f3e3f4dc3a5c9d28bddd903bc76c"
    default_device = "cuda:0"
    default_dtype = "bfloat16"
    default_language = "Chinese"
    default_context = "航空、飞机、发动机、APU、副翼、襟翼、起落架、尾翼、机翼"
    default_max_new_tokens = 256

    def __init__(self, *, settings: VoiceSettings | None = None) -> None:
        asr_config = settings.asr_config if settings is not None else {}
        self.model_id = str(asr_config.get("model_id") or self.default_model_id)
        self.revision = str(asr_config.get("revision") or self.default_revision)
        self.device = str(asr_config.get("device") or self.default_device)
        self.dtype = str(asr_config.get("dtype") or self.default_dtype)
        self.language = str(asr_config.get("language") or self.default_language)
        self.context = str(asr_config.get("context") or asr_config.get("initial_prompt") or self.default_context)
        self.max_new_tokens = int(asr_config.get("max_new_tokens") or self.default_max_new_tokens)

    def _model_cache_key(self) -> tuple[str, str, str, str]:
        return (self.model_id, self.revision, self.device, self.dtype)

    def _get_model_and_processor(self) -> tuple[object, object]:
        key = self._model_cache_key()
        cached = _MODEL_CACHE.get(key)
        if cached is not None:
            return cached

        try:
            import torch
            from transformers import AutoModelForMultimodalLM, AutoProcessor

            torch_dtype = getattr(torch, self.dtype, torch.bfloat16)
            is_local = Path(self.model_id).exists()
            processor = AutoProcessor.from_pretrained(
                self.model_id,
                revision=self.revision if not is_local else None,
                local_files_only=is_local,
                trust_remote_code=False,
            )
            model = AutoModelForMultimodalLM.from_pretrained(
                self.model_id,
                revision=self.revision if not is_local else None,
                torch_dtype=torch_dtype,
                local_files_only=is_local,
                trust_remote_code=False,
            )
            model.to(self.device)
            model.eval()
        except Exception as exc:
            raise VoiceASRError(
                "qwen3_asr model could not be loaded",
                field="asr",
                details={"provider": self.name, "reason": "model_load_failed"},
            ) from exc

        cached = (model, processor)
        _MODEL_CACHE[key] = cached
        return cached

    async def prewarm(self) -> None:
        key = self._model_cache_key()
        async with _inference_lock(key):
            await asyncio.to_thread(self._get_model_and_processor)

    async def transcribe(
        self,
        frames: AsyncIterator[AudioFrame],
    ) -> AsyncIterator[ASRResult]:
        buffer = bytearray()
        async for frame in frames:
            if not isinstance(frame, AudioFrame):
                raise VoiceASRError(
                    "ASR frame stream contains a non-canonical frame",
                    field="frames",
                    details={"provider": self.name, "reason": "non_canonical_frame"},
                )
            buffer.extend(frame.payload)
        if not buffer:
            raise VoiceASRError(
                "ASR received an empty audio buffer",
                field="frames",
                details={"provider": self.name, "reason": "empty_audio"},
            )
        if len(buffer) % _SAMPLE_WIDTH_BYTES:
            raise VoiceASRError(
                "ASR received truncated int16 PCM",
                field="frames",
                details={"provider": self.name, "reason": "truncated_pcm"},
            )

        async with _inference_lock(self._model_cache_key()):
            results = await asyncio.to_thread(self._transcribe_sync, bytes(buffer))
        for result in results:
            yield result

    def _transcribe_sync(self, pcm_bytes: bytes) -> list[ASRResult]:
        try:
            import torch

            model, processor = self._get_model_and_processor()
            audio_array = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            duration_ms = int(len(audio_array) / 16000.0 * 1000)

            # Apply transcription request via official processor API
            inputs = processor.apply_transcription_request(
                audio_array,
                language=self.language,
                prompt=self.context,
            )
            inputs = inputs.to(model.device, model.dtype)

            with torch.no_grad():
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=self.max_new_tokens,
                    return_dict_in_generate=True,
                    output_scores=True,
                )

            sequences = outputs.sequences
            input_len = inputs["input_ids"].shape[1]
            generated_ids = sequences[:, input_len:]

            transcription = processor.decode(generated_ids, return_format="transcription_only")[0]
            text = transcription.strip() if isinstance(transcription, str) else ""
            if not text:
                return []

            # Compute transition confidence
            confidence = 0.90
            try:
                scores = model.compute_transition_scores(
                    sequences, outputs.scores, normalize_logits=True
                )
                if scores.shape[1] > 0:
                    mean_logprob = scores[0].mean().item()
                    confidence = float(max(0.0, min(1.0, exp(mean_logprob))))
            except Exception:
                pass

            return [
                ASRResult(
                    raw_transcript=text,
                    confidence=confidence,
                    is_final=True,
                    start_ms=0,
                    end_ms=duration_ms,
                    language=_ASR_RESULT_LANGUAGE,
                    provider=self.name,
                )
            ]
        except VoiceASRError:
            raise
        except Exception as exc:
            raise VoiceASRError(
                "qwen3_asr inference failed",
                field="asr",
                details={"provider": self.name, "reason": "inference_failed"},
            ) from exc
