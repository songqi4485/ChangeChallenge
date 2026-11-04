from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from voice.errors import VoiceConfigError
from voice.settings import VoiceSettings, load_string_mapping, load_terminology_mapping
from voice.terminology import AviationTermCorrector
from voice.tts import MockTTSProvider
from voice.vad import MockVADService
from input.voice_query_normalizer import VoiceQueryNormalizer
from voice.asr import ASRResult


KNOWN_PROVIDERS = {
    "transport": {"websocket", "in_memory"},
    "vad": {"mock"},
    "asr": {"mock"},
    "tts": {"mock"},
}


VALID_VOICE = {
    "transport": "websocket",
    "sample_rate": 16000,
    "channel_count": 1,
    "frame_duration_ms": 20,
    "vad_provider": "mock",
    "vad_threshold": 0.2,
    "endpoint_silence_ms": 600,
    "asr_provider": "mock",
    "asr_low_confidence_threshold": 0.65,
    "tts_provider": "mock",
    "max_utterance_ms": 15000,
    "max_frames": 750,
    "max_audio_bytes": 480000,
    "max_spoken_answer_seconds": 20,
    "max_spoken_answer_chars": 180,
    "spoken_chars_per_second": 6.0,
    "min_spoken_explanation_steps": 2,
    "max_spoken_explanation_steps": 3,
    "barge_in_enabled": True,
    "barge_in_priority": 100,
    "raw_audio_persist_enabled": False,
    "raw_transcript_logging_enabled": False,
    "raw_transcript_retention_seconds": 0,
    "raw_transcript_redaction_mode": "full",
    "terminology_lexicon_path": "terminology.yaml",
    "pronunciation_lexicon_path": "pronunciation.yaml",
}


def _yaml_scalar(value: object) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _render_value(key: str, value: object, indent: int) -> list[str]:
    """Render a scalar, nested mapping, or flow list under ``key``."""
    prefix = " " * indent
    if isinstance(value, dict):
        lines = [f"{prefix}{key}:"]
        for sub_key, sub_value in value.items():
            lines.extend(_render_value(str(sub_key), sub_value, indent + 2))
        return lines
    if isinstance(value, (list, tuple)):
        return [f"{prefix}{key}: [{', '.join(_yaml_scalar(item) for item in value)}]"]
    return [f"{prefix}{key}: {_yaml_scalar(value)}"]


def write_voice_config(tmp_path: Path, **overrides: object) -> Path:
    values = {**VALID_VOICE, **overrides}
    (tmp_path / "terminology.yaml").write_text(
        "terms:\n  航道比: 涵道比\nsimplifications:\n  气流压力分布: 压力差\n",
        encoding="utf-8",
    )
    (tmp_path / "pronunciation.yaml").write_text("terms:\n  C919: C 九一九\n", encoding="utf-8")
    config = tmp_path / "voice.yaml"
    lines = ["voice:"]
    for key, value in values.items():
        lines.extend(_render_value(key, value, indent=2))
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config


def test_voice_settings_loads_typed_frozen_config_and_safe_snapshot(tmp_path: Path) -> None:
    config = write_voice_config(tmp_path, vad_threshold=0.4, max_spoken_answer_chars=99)

    settings = VoiceSettings.from_file(config, known_providers=KNOWN_PROVIDERS)

    assert settings.vad_threshold == 0.4
    assert settings.max_spoken_answer_chars == 99
    assert settings.terminology_lexicon_path == tmp_path / "terminology.yaml"
    assert settings.pronunciation_lexicon_path == tmp_path / "pronunciation.yaml"
    assert settings.safe_summary()["snapshot_id"] == settings.snapshot_id
    assert len(settings.snapshot_id) == 64
    assert str(tmp_path) not in repr(settings.safe_summary())
    assert "航道比" not in repr(settings.safe_summary())
    assert "terminology_lexicon_path" not in settings.safe_summary()
    assert "pronunciation_lexicon_path" not in settings.safe_summary()
    assert len(settings.safe_summary()["terminology_lexicon_digest"]) == 64
    assert len(settings.safe_summary()["simplification_lexicon_digest"]) == 64
    assert len(settings.safe_summary()["pronunciation_lexicon_digest"]) == 64
    assert "asr_config" in settings.safe_summary()
    assert "tts_config" in settings.safe_summary()
    with pytest.raises(FrozenInstanceError):
        settings.sample_rate = 8000  # type: ignore[misc]


def test_repository_voice_settings_consumes_declared_config_and_lexicons() -> None:
    settings = VoiceSettings.from_file("configs/voice.yaml")

    assert settings.transport == "websocket"
    assert settings.asr_provider in {"whisper", "qwen3_asr"}
    assert settings.tts_provider == "edge"
    assert settings.asr_low_confidence_threshold == 0.40
    assert settings.raw_audio_persist_enabled is False
    assert settings.raw_transcript_logging_enabled is False
    assert settings.raw_transcript_retention_seconds == 0
    assert settings.raw_transcript_redaction_mode == "full"
    assert settings.spoken_chars_per_second == 6.0
    assert settings.min_spoken_explanation_steps == 2
    assert settings.max_spoken_explanation_steps == 3
    if settings.asr_provider == "whisper":
        assert settings.asr_config == {
            "model_size": "small",
            "device": "cpu",
            "compute_type": "int8",
            "language": "zh",
            "initial_prompt": "航空、飞机、发动机、APU、副翼、襟翼、起落架、尾翼、机翼、C919、歼-20、运-20、直-20、涡扇发动机、涵道比、LEAP-1C、WS-10C、WS-15、WS-20、超临界机翼、展弦比、翼梢小翼、鸭翼、边条翼、T形尾翼、主旋翼、尾桨、缝翼、DSI进气道、电传飞控、航电系统、升力、阻力、迎角、失速、马赫数、雷达散射截面、地面效应",
            "prewarm": True,
        }
    else:
        assert settings.asr_config == {
            "model_id": "./models/Qwen3-ASR-0.6B-hf",
            "device": "cuda:0",
            "dtype": "bfloat16",
            "language": "Chinese",
            "context": "航空、飞机、发动机、APU、副翼、襟翼、起落架、尾翼、机翼、C919、歼-20、运-20、直-20、涡扇发动机、涵道比、LEAP-1C、WS-10C、WS-15、WS-20、超临界机翼、展弦比、翼梢小翼、鸭翼、边条翼、T形尾翼、主旋翼、尾桨、缝翼、DSI进气道、电传飞控、航电系统、升力、阻力、迎角、失速、马赫数、雷达散射截面、地面效应",
            "prewarm": True,
        }
    assert settings.tts_config == {
        "voice": "zh-CN-XiaoxiaoNeural",
        "rate": "+0%",
        "volume": "+0%",
    }
    assert load_terminology_mapping(
        settings.terminology_lexicon_path,
        root_key="terms",
    )["A G 六百"] == "AG600"
    assert load_string_mapping(settings.pronunciation_lexicon_path)["RAG"] == "R A G"


def test_voice_settings_parses_asr_tts_config_and_snapshots_new_fields(tmp_path: Path) -> None:
    config = write_voice_config(
        tmp_path,
        asr_config={
            "model_size": "small",
            "device": "cpu",
            "compute_type": "int8",
            "language": "zh",
            "initial_prompt": "航空、飞机、发动机",
        },
        tts_config={"voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "volume": "+0%"},
    )

    settings = VoiceSettings.from_file(config, known_providers=KNOWN_PROVIDERS)

    assert settings.asr_config == {
        "model_size": "small",
        "device": "cpu",
        "compute_type": "int8",
        "language": "zh",
        "initial_prompt": "航空、飞机、发动机",
    }
    assert settings.tts_config == {
        "voice": "zh-CN-XiaoxiaoNeural",
        "rate": "+0%",
        "volume": "+0%",
    }
    summary = settings.safe_summary()
    assert summary["asr_config"] == settings.asr_config
    assert summary["tts_config"] == settings.tts_config
    assert settings.snapshot_id != VoiceSettings.from_file(
        write_voice_config(tmp_path), known_providers=KNOWN_PROVIDERS
    ).snapshot_id


@pytest.mark.parametrize("prewarm", [True, False])
def test_voice_settings_accepts_strict_bool_prewarm_in_asr_config(
    tmp_path: Path, prewarm: bool
) -> None:
    """VR7-T17: asr_config.prewarm is the ONLY boolean key; true/false both parse."""
    config = write_voice_config(
        tmp_path,
        asr_config={
            "model_size": "small",
            "device": "cpu",
            "compute_type": "int8",
            "prewarm": prewarm,
        },
    )

    settings = VoiceSettings.from_file(config, known_providers=KNOWN_PROVIDERS)

    assert settings.asr_config["prewarm"] is prewarm
    assert isinstance(settings.asr_config["prewarm"], bool)


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"raw_audio_persist_enabled": True}, "raw_audio_persist_enabled"),
        ({"raw_transcript_logging_enabled": True}, "raw_transcript_logging_enabled"),
        ({"raw_transcript_retention_seconds": 1}, "raw_transcript_retention_seconds"),
        ({"raw_transcript_redaction_mode": "partial"}, "raw_transcript_redaction_mode"),
    ],
)
def test_voice_settings_constructor_invariants_cannot_be_bypassed_with_replace(
    changes: dict[str, object],
    field: str,
) -> None:
    settings = VoiceSettings.from_file("configs/voice.yaml")

    with pytest.raises(VoiceConfigError) as caught:
        replace(settings, **changes)

    assert caught.value.field == field


def test_term_corrector_preserves_explicit_empty_lexicon() -> None:
    corrector = AviationTermCorrector(corrections={})

    assert corrector.corrections == {}


def test_voice_components_consume_settings_and_allow_explicit_overrides(tmp_path: Path) -> None:
    config = write_voice_config(
        tmp_path,
        vad_threshold=0.4,
        endpoint_silence_ms=740,
        asr_low_confidence_threshold=0.8,
        max_spoken_answer_seconds=2,
    )
    settings = VoiceSettings.from_file(config, known_providers=KNOWN_PROVIDERS)

    configured_vad = MockVADService(settings=settings)
    overridden_vad = MockVADService(
        threshold=0.7,
        end_silence_ms=900,
        settings=settings,
    )
    assert configured_vad.threshold == 0.4
    assert configured_vad.end_silence_ms == 740
    assert overridden_vad.threshold == 0.7
    assert overridden_vad.end_silence_ms == 900

    configured_normalizer = VoiceQueryNormalizer(settings=settings, corrector=AviationTermCorrector({}))
    overridden_normalizer = VoiceQueryNormalizer(
        asr_low_confidence_threshold=0.3,
        settings=settings,
        corrector=AviationTermCorrector({}),
    )
    result = ASRResult("解释机翼", confidence=0.5, is_final=True)
    assert configured_normalizer.normalize(result).needs_clarification is True
    assert overridden_normalizer.normalize(result).needs_clarification is False

    configured_tts = MockTTSProvider(settings=settings).synthesize("机翼" * 300)
    overridden_tts = MockTTSProvider(settings=settings).synthesize("机翼" * 300, max_seconds=1)
    assert configured_tts.duration_seconds == 2.0
    assert overridden_tts.duration_seconds == 1.0


def test_voice_settings_vad_debounce_keys_reach_vad_and_default_to_legacy(
    tmp_path: Path,
) -> None:
    """P1-3: vad_start_frames/vad_min_voice_frames are optional and plumb into the VAD."""
    config = write_voice_config(tmp_path, vad_start_frames=3, vad_min_voice_frames=10)
    settings = VoiceSettings.from_file(config, known_providers=KNOWN_PROVIDERS)

    configured_vad = MockVADService(settings=settings)
    assert configured_vad.start_frames == 3
    assert configured_vad.min_voice_frames == 10

    # Explicit constructor arguments still override the settings values.
    overridden_vad = MockVADService(
        settings=settings,
        start_frames=2,
        min_voice_frames=4,
    )
    assert overridden_vad.start_frames == 2
    assert overridden_vad.min_voice_frames == 4

    # Absent keys keep the legacy single-frame semantics.
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    legacy_settings = VoiceSettings.from_file(
        write_voice_config(legacy_dir), known_providers=KNOWN_PROVIDERS
    )
    legacy_vad = MockVADService(settings=legacy_settings)
    assert legacy_vad.start_frames == 1
    assert legacy_vad.min_voice_frames == 1


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("vad_start_frames", 0),
        ("vad_start_frames", -3),
        ("vad_start_frames", True),
        ("vad_min_voice_frames", 0),
        ("vad_min_voice_frames", -1),
        ("vad_min_voice_frames", '"3"'),
    ],
)
def test_voice_settings_rejects_invalid_vad_debounce_values(
    tmp_path: Path,
    field_name: str,
    value: object,
) -> None:
    config = write_voice_config(tmp_path, **{field_name: value})

    with pytest.raises(VoiceConfigError) as caught:
        VoiceSettings.from_file(config, known_providers=KNOWN_PROVIDERS)

    assert caught.value.field == field_name


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ("unknown_root:\n  x: 1\n", "unknown_root"),
        ("voice:\n  unknown_voice_key: 1\n", "unknown_voice_key"),
        ("app: value\n", "app"),
    ],
)
def test_voice_settings_rejects_unknown_or_missing_sections(
    tmp_path: Path,
    payload: str,
    field: str,
) -> None:
    path = tmp_path / "voice.yaml"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(VoiceConfigError) as caught:
        VoiceSettings.from_file(path, known_providers=KNOWN_PROVIDERS)

    assert caught.value.field == field


def test_voice_settings_rejects_missing_key(tmp_path: Path) -> None:
    path = write_voice_config(tmp_path)
    path.write_text(path.read_text(encoding="utf-8").replace("  sample_rate: 16000\n", ""), encoding="utf-8")

    with pytest.raises(VoiceConfigError) as caught:
        VoiceSettings.from_file(path, known_providers=KNOWN_PROVIDERS)

    assert caught.value.field == "sample_rate"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sample_rate", True),
        ("sample_rate", 0),
        ("channel_count", 3),
        ("frame_duration_ms", 0),
        ("endpoint_silence_ms", -1),
        ("max_spoken_answer_seconds", 0),
        ("max_spoken_answer_chars", 0),
        ("spoken_chars_per_second", 0),
        ("spoken_chars_per_second", True),
        ("min_spoken_explanation_steps", 1),
        ("min_spoken_explanation_steps", 0),
        ("max_spoken_explanation_steps", 0),
        ("max_spoken_explanation_steps", 4),
        ("barge_in_priority", 0),
        ("vad_threshold", -0.1),
        ("vad_threshold", 1.1),
        ("asr_low_confidence_threshold", True),
        ("asr_low_confidence_threshold", 1.1),
        ("barge_in_enabled", 1),
        ("raw_audio_persist_enabled", True),
        ("raw_transcript_logging_enabled", True),
        ("raw_transcript_retention_seconds", 1),
        ("raw_transcript_redaction_mode", "partial"),
        ("asr_config", {"model_size": {"nested": 1}}),
        ("asr_config", ["small", "int8"]),
        ("asr_config", {"language": True}),
        ("asr_config", {"prewarm": "enabled"}),
        ("asr_config", {"prewarm": 1}),
        ("asr_config", {"prewarm": 1.5}),
        ("tts_config", {"voice": ["Xiaoxiao"]}),
        ("tts_config", {"rate": 1.5}),
    ],
)
def test_voice_settings_rejects_invalid_values(tmp_path: Path, field: str, value: object) -> None:
    path = write_voice_config(tmp_path, **{field: value})

    with pytest.raises(VoiceConfigError) as caught:
        VoiceSettings.from_file(path, known_providers=KNOWN_PROVIDERS)

    assert caught.value.field == field


def test_voice_settings_rejects_explanation_min_above_max(tmp_path: Path) -> None:
    path = write_voice_config(
        tmp_path,
        min_spoken_explanation_steps=3,
        max_spoken_explanation_steps=2,
    )

    with pytest.raises(VoiceConfigError) as caught:
        VoiceSettings.from_file(path, known_providers=KNOWN_PROVIDERS)

    assert caught.value.field == "min_spoken_explanation_steps"


@pytest.mark.parametrize(
    ("field", "provider", "known"),
    [
        ("transport", "missing", {"transport": {"websocket"}, "vad": {"mock"}, "asr": {"mock"}, "tts": {"mock"}}),
        ("vad_provider", "missing", {"transport": {"websocket"}, "vad": {"mock"}, "asr": {"mock"}, "tts": {"mock"}}),
        ("asr_provider", "missing", {"transport": {"websocket"}, "vad": {"mock"}, "asr": {"mock"}, "tts": {"mock"}}),
        ("tts_provider", "missing", {"transport": {"websocket"}, "vad": {"mock"}, "asr": {"mock"}, "tts": {"mock"}}),
    ],
)
def test_voice_settings_rejects_unknown_provider_by_category(
    tmp_path: Path,
    field: str,
    provider: str,
    known: dict[str, set[str]],
) -> None:
    path = write_voice_config(tmp_path, **{field: provider})

    with pytest.raises(VoiceConfigError) as caught:
        VoiceSettings.from_file(path, known_providers=known)

    assert caught.value.field == field


def test_voice_settings_rejects_missing_lexicon_without_leaking_path_contents(tmp_path: Path) -> None:
    path = write_voice_config(tmp_path, terminology_lexicon_path="secret-private-lexicon.yaml")

    with pytest.raises(VoiceConfigError) as caught:
        VoiceSettings.from_file(path, known_providers=KNOWN_PROVIDERS)

    assert caught.value.field == "terminology_lexicon_path"
    assert "secret-private-lexicon.yaml" not in str(caught.value)


@pytest.mark.parametrize(
    "known_providers",
    [
        {"mock", "websocket"},
        {"transport": {"websocket"}, "vad": {"mock"}, "asr": {"mock"}},
        {"transport": {"websocket"}, "vad": {"mock"}, "asr": {"mock"}, "tts": "mock"},
        {"transport": {"websocket"}, "vad": {"mock"}, "asr": {"mock"}, "tts": {1}},
    ],
)
def test_voice_settings_requires_complete_typed_provider_mapping(
    tmp_path: Path,
    known_providers: object,
) -> None:
    path = write_voice_config(tmp_path)

    with pytest.raises(VoiceConfigError) as caught:
        VoiceSettings.from_file(path, known_providers=known_providers)  # type: ignore[arg-type]

    assert caught.value.field == "known_providers"


def test_voice_settings_resolves_project_config_paths_independently_of_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    config_dir = project / "configs"
    config_dir.mkdir(parents=True)
    config = write_voice_config(
        config_dir,
        terminology_lexicon_path="configs/terminology.yaml",
        pronunciation_lexicon_path="configs/pronunciation.yaml",
    )
    unrelated_cwd = tmp_path / "elsewhere"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)

    settings = VoiceSettings.from_file(config.resolve(), known_providers=KNOWN_PROVIDERS)

    assert settings.terminology_lexicon_path == (config_dir / "terminology.yaml").resolve()
    assert settings.pronunciation_lexicon_path == (config_dir / "pronunciation.yaml").resolve()


def test_voice_settings_snapshot_changes_when_lexicon_content_changes(tmp_path: Path) -> None:
    config = write_voice_config(tmp_path)
    first = VoiceSettings.from_file(config, known_providers=KNOWN_PROVIDERS)
    (tmp_path / "terminology.yaml").write_text(
        "terms:\n  航道比: 涵道比\n  鸡翼: 机翼\nsimplifications:\n  气流压力分布: 压力差\n",
        encoding="utf-8",
    )

    second = VoiceSettings.from_file(config, known_providers=KNOWN_PROVIDERS)

    assert second.terminology_lexicon_digest != first.terminology_lexicon_digest
    assert second.pronunciation_lexicon_digest == first.pronunciation_lexicon_digest
    assert second.snapshot_id != first.snapshot_id


def test_voice_settings_snapshot_changes_when_only_simplifications_change(tmp_path: Path) -> None:
    config = write_voice_config(tmp_path)
    first = VoiceSettings.from_file(config, known_providers=KNOWN_PROVIDERS)
    (tmp_path / "terminology.yaml").write_text(
        "terms:\n  航道比: 涵道比\nsimplifications:\n  气流压力分布: 空气压力差\n",
        encoding="utf-8",
    )

    second = VoiceSettings.from_file(config, known_providers=KNOWN_PROVIDERS)

    assert second.terminology_lexicon_digest == first.terminology_lexicon_digest
    assert second.simplification_lexicon_digest != first.simplification_lexicon_digest
    assert second.snapshot_id != first.snapshot_id


def test_voice_settings_rejects_invalid_simplification_mapping_at_startup(tmp_path: Path) -> None:
    config = write_voice_config(tmp_path)
    (tmp_path / "terminology.yaml").write_text(
        "terms:\n  航道比: 涵道比\nsimplifications:\n  气流压力分布:\n",
        encoding="utf-8",
    )

    with pytest.raises(VoiceConfigError) as caught:
        VoiceSettings.from_file(config, known_providers=KNOWN_PROVIDERS)

    assert caught.value.field == "terminology_lexicon_path"


@pytest.mark.parametrize(
    "payload",
    [
        "terms: value\n",
        "terms:\n  C919: \n",
        "terms:\n  C919:\n    nested: invalid\n",
    ],
)
def test_lexicon_loader_rejects_non_string_or_empty_entries(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "lexicon.yaml"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(VoiceConfigError):
        load_string_mapping(path)


def test_lexicon_loader_accepts_utf8_string_mapping(tmp_path: Path) -> None:
    path = tmp_path / "lexicon.yaml"
    path.write_text("terms:\n  航道比: 涵道比\n  C 九一九: C919\n", encoding="utf-8")

    assert load_string_mapping(path) == {"航道比": "涵道比", "C 九一九": "C919"}
