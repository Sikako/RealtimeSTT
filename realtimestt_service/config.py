import os
from dataclasses import dataclass
from typing import Mapping


BREEZE_ASR_25_DIRNAME = "faster-whisper-Breeze-ASR-25"
DEFAULT_MODEL_PROFILE = "breeze-asr-25"
DEFAULT_DEVICE = "cuda"
DEFAULT_COMPUTE_TYPE = "float16"
DEFAULT_INITIAL_PROMPT = "繁體中文會議記錄，台灣華語，中英混用，對話清晰。"
FALLBACK_MODEL_PRIORITIES = ("medium", "large-v2", "small", "tiny")


@dataclass(frozen=True)
class SttModelConfig:
    model_path: str
    device: str
    compute_type: str
    initial_prompt: str


def _env(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def _existing_dir(path: str) -> str | None:
    return path if path and os.path.isdir(path) else None


def _find_breeze_asr_25_model(models_dir: str) -> str | None:
    exact_path = os.path.join(models_dir, BREEZE_ASR_25_DIRNAME)
    if os.path.isdir(exact_path):
        return exact_path

    if not os.path.isdir(models_dir):
        return None

    for dirname in os.listdir(models_dir):
        path = os.path.join(models_dir, dirname)
        if BREEZE_ASR_25_DIRNAME.lower() in dirname.lower() and os.path.isdir(path):
            return path
    return None


def _find_fallback_whisper_model(models_dir: str) -> str | None:
    if not os.path.isdir(models_dir):
        return None

    for size in FALLBACK_MODEL_PRIORITIES:
        for dirname in os.listdir(models_dir):
            path = os.path.join(models_dir, dirname)
            if f"faster-whisper-{size}" in dirname and os.path.isdir(path):
                return path
    return None


def resolve_model_path(
    models_dir: str, environ: Mapping[str, str] | None = None
) -> str:
    values = _env(environ)
    explicit_path = _existing_dir(values.get("STT_MODEL_PATH", ""))
    if explicit_path:
        return explicit_path

    profile = values.get("STT_MODEL_PROFILE", DEFAULT_MODEL_PROFILE).strip().lower()
    if profile == "breeze-asr-25":
        breeze_model = _find_breeze_asr_25_model(models_dir)
        if breeze_model:
            return breeze_model

    fallback_model = _find_fallback_whisper_model(models_dir)
    if fallback_model:
        return fallback_model

    return "tiny"


def build_stt_model_config(
    models_dir: str,
    environ: Mapping[str, str] | None = None,
) -> SttModelConfig:
    values = _env(environ)
    return SttModelConfig(
        model_path=resolve_model_path(models_dir, values),
        device=values.get("STT_DEVICE", DEFAULT_DEVICE),
        compute_type=values.get("STT_COMPUTE_TYPE", DEFAULT_COMPUTE_TYPE),
        initial_prompt=values.get("STT_INITIAL_PROMPT", DEFAULT_INITIAL_PROMPT),
    )


def load_faster_whisper_model(model_cls, config: SttModelConfig):
    return model_cls(
        config.model_path,
        device=config.device,
        compute_type=config.compute_type,
        local_files_only=True,
    )
