from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import sys

import numpy as np
import pytest

from voice.qwen_asr import QwenASRProvider
from voice.settings import VoiceSettings
from voice.terminology import AviationTermCorrector


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({"context": "涵道比、歼-20、主旋翼"}, "涵道比、歼-20、主旋翼"),
        ({"initial_prompt": "C919、副翼"}, "C919、副翼"),
        ({"context": "迎角", "initial_prompt": "不应使用"}, "迎角"),
        ({}, QwenASRProvider.default_context),
    ],
)
def test_qwen_hotwords_reach_processor_prompt(monkeypatch, config, expected):
    """Exercise the inference call without importing torch or loading weights."""
    provider = QwenASRProvider(settings=SimpleNamespace(asr_config=config))

    class Inputs(dict):
        def to(self, *args):
            return self

    inputs = Inputs(input_ids=np.array([[1, 2]]))
    processor = SimpleNamespace(
        apply_transcription_request=Mock(return_value=inputs),
        decode=Mock(return_value=["歼-20采用鸭翼布局"]),
    )
    model = SimpleNamespace(
        device="cpu", dtype="float32",
        generate=Mock(return_value=SimpleNamespace(
            sequences=np.array([[1, 2, 3]]), scores=(),
        )),
    )
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(no_grad=nullcontext))
    monkeypatch.setattr(provider, "_get_model_and_processor", lambda: (model, processor))

    result = provider._transcribe_sync(np.zeros(160, dtype=np.int16).tobytes())

    call = processor.apply_transcription_request.call_args
    assert call.kwargs == {"language": "Chinese", "prompt": expected}
    assert call.args[0].dtype == np.float32
    assert len(call.args[0]) == 160
    assert result[0].raw_transcript == "歼-20采用鸭翼布局"
    assert result[0].provider == "qwen3_asr"
    assert result[0].end_ms == 10
    assert model.generate.call_count == 1


def test_repository_qwen_config_preserves_model_and_supplies_hotwords():
    root = Path(__file__).resolve().parents[3]
    settings = VoiceSettings.from_file(root / "configs/voice.yaml")
    assert settings.asr_provider == "qwen3_asr"
    assert settings.asr_config["model_id"] == "./models/Qwen3-ASR-0.6B-hf"
    assert settings.asr_config["device"] == "cuda:0"
    assert settings.asr_config["dtype"] == "bfloat16"
    provider = QwenASRProvider(settings=settings)
    assert provider.context == settings.asr_config["context"]
    for term in ("C919", "歼-20", "运-20", "直-20", "涵道比", "主旋翼"):
        assert term in provider.context


@pytest.mark.parametrize(
    ("source", "expected"),
    [("歼 二十和运20", "歼-20和运-20"),
     ("直二十的主旋翼", "直-20的主旋翼"),
     ("C919客机的全动尾翼", "C919客机的全动尾翼"),
     ("T形尾翼与蚌壳进气道", "T形尾翼与蚌壳进气道"),
     ("利普发动机与神雕直升机", "利普发动机与神雕直升机")],
)
def test_hotword_normalization_preserves_meaning(source, expected):
    root = Path(__file__).resolve().parents[3]
    corrector = AviationTermCorrector(lexicon_path=root / "configs/voice_terminology.yaml")
    corrected = corrector.correct(source).corrected_transcript
    assert corrected == expected
    assert corrector.correct(corrected).corrected_transcript == expected
