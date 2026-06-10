import os

from stt_model_config import (
    BREEZE_ASR_25_DIRNAME,
    DEFAULT_INITIAL_PROMPT,
    build_stt_model_config,
    load_faster_whisper_model,
    resolve_model_path,
)


def test_stt_model_path_env_takes_precedence(tmp_path, monkeypatch):
    explicit_model = tmp_path / "custom-model"
    explicit_model.mkdir()
    monkeypatch.setenv("STT_MODEL_PATH", str(explicit_model))

    assert resolve_model_path(str(tmp_path)) == str(explicit_model)


def test_breeze_asr_25_profile_prefers_local_breeze_model(tmp_path, monkeypatch):
    breeze_model = tmp_path / BREEZE_ASR_25_DIRNAME
    whisper_model = tmp_path / "models--Systran--faster-whisper-small"
    breeze_model.mkdir()
    whisper_model.mkdir()
    monkeypatch.delenv("STT_MODEL_PATH", raising=False)
    monkeypatch.setenv("STT_MODEL_PROFILE", "breeze-asr-25")

    assert resolve_model_path(str(tmp_path)) == str(breeze_model)


def test_missing_breeze_asr_25_falls_back_to_existing_whisper_model(
    tmp_path, monkeypatch
):
    medium_model = tmp_path / "models--Systran--faster-whisper-medium"
    small_model = tmp_path / "models--Systran--faster-whisper-small"
    medium_model.mkdir()
    small_model.mkdir()
    monkeypatch.delenv("STT_MODEL_PATH", raising=False)
    monkeypatch.setenv("STT_MODEL_PROFILE", "breeze-asr-25")

    assert resolve_model_path(str(tmp_path)) == str(medium_model)


def test_build_config_uses_device_compute_type_and_breeze_prompt(tmp_path, monkeypatch):
    breeze_model = tmp_path / BREEZE_ASR_25_DIRNAME
    breeze_model.mkdir()
    monkeypatch.delenv("STT_MODEL_PATH", raising=False)
    monkeypatch.setenv("STT_DEVICE", "cpu")
    monkeypatch.setenv("STT_COMPUTE_TYPE", "int8")

    config = build_stt_model_config(str(tmp_path))

    assert config.model_path == str(breeze_model)
    assert config.device == "cpu"
    assert config.compute_type == "int8"
    assert config.initial_prompt == DEFAULT_INITIAL_PROMPT


def test_load_faster_whisper_model_passes_runtime_options(tmp_path):
    calls = []

    class FakeWhisperModel:
        def __init__(self, model_path, **kwargs):
            calls.append((model_path, kwargs))

    model_path = tmp_path / "model"
    model_path.mkdir()
    config = build_stt_model_config(
        str(tmp_path),
        environ={
            **os.environ,
            "STT_MODEL_PATH": str(model_path),
            "STT_DEVICE": "cuda",
            "STT_COMPUTE_TYPE": "float16",
        },
    )

    load_faster_whisper_model(FakeWhisperModel, config)

    assert calls == [
        (
            str(model_path),
            {
                "device": "cuda",
                "compute_type": "float16",
                "local_files_only": True,
            },
        )
    ]
