import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence, Union

from .config import SttModelConfig, load_faster_whisper_model


KNOWN_ARTIFACTS = (
    "字幕由",
    "Subtitle by",
    "Amara.org",
    "MBC News",
    "不代表本台",
    "alugha",
    "Sous-titres",
    "點擊訂閱",
    "Subscribe",
    "視聴ありがとうございました",
)


@dataclass(frozen=True)
class TranscriptionRuntimeConfig(SttModelConfig):
    @classmethod
    def from_stt_config(cls, config: SttModelConfig) -> "TranscriptionRuntimeConfig":
        return cls(
            model_path=config.model_path,
            device=config.device,
            compute_type=config.compute_type,
            initial_prompt=config.initial_prompt,
        )


@dataclass(frozen=True)
class TranscriptionJob:
    session_id: str
    channel_id: str
    audio_data: Any
    timestamp: float
    language: str = "zh"

    @classmethod
    def from_mapping(cls, job: Mapping[str, Any]) -> "TranscriptionJob":
        return cls(
            session_id=str(job["session_id"]),
            channel_id=str(job["channel_id"]),
            audio_data=job["audio_data"],
            timestamp=float(job["timestamp"]),
            language=str(job.get("language") or "zh"),
        )


def clean_transcription_text(
    text: str, artifacts: Sequence[str] = KNOWN_ARTIFACTS
) -> str:
    cleaned = text.strip()
    for artifact in artifacts:
        cleaned = cleaned.replace(artifact, "")
    return cleaned.strip()


def default_model_loader(config: TranscriptionRuntimeConfig):
    from faster_whisper import WhisperModel

    return load_faster_whisper_model(WhisperModel, config)


class InferenceEngine:
    def __init__(
        self,
        config: TranscriptionRuntimeConfig,
        model_loader: Callable[
            [TranscriptionRuntimeConfig], Any
        ] = default_model_loader,
        event_publisher: Optional[Callable[[dict], None]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.config = config
        self.model_loader = model_loader
        self.event_publisher = event_publisher
        self.logger = logger or logging.getLogger(__name__)
        self.model = None

    def load_model(self) -> bool:
        if _looks_like_filesystem_path(self.config.model_path) and not os.path.exists(
            self.config.model_path
        ):
            self.logger.error("FATAL: Model not found at %s", self.config.model_path)
            return False

        self.logger.info(
            "Loading Whisper Model from %s (device=%s, compute_type=%s) ...",
            self.config.model_path,
            self.config.device,
            self.config.compute_type,
        )
        try:
            self.model = self.model_loader(self.config)
            self.logger.info("Model Loaded Successfully.")
            return True
        except Exception as exc:
            self.logger.error("Failed to load model: %s", exc)
            return False

    def transcribe(
        self, job: Union[TranscriptionJob, Mapping[str, Any]]
    ) -> Optional[dict]:
        if not self.model:
            self.logger.error("Model not initialized!")
            return None

        transcription_job = (
            TranscriptionJob.from_mapping(job) if isinstance(job, Mapping) else job
        )

        try:
            segments, info = self.model.transcribe(
                transcription_job.audio_data,
                beam_size=5,
                language=transcription_job.language,
                initial_prompt=self.config.initial_prompt,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                temperature=0.0,
                condition_on_previous_text=False,
                repetition_penalty=1.1,
            )

            raw_text = " ".join(segment.text for segment in segments)
            text = clean_transcription_text(raw_text)
            if not text:
                return None

            result = {
                "type": "transcription",
                "session_id": transcription_job.session_id,
                "channel_id": transcription_job.channel_id,
                "text": text,
                "timestamp": transcription_job.timestamp,
                "duration": info.duration,
            }
            self.logger.info(
                "TRANSCRIPTION [%s][%s]: %s",
                transcription_job.session_id,
                transcription_job.channel_id,
                text,
            )
            if self.event_publisher:
                self.event_publisher(result)
            return result
        except Exception as exc:
            self.logger.error(
                "Inference Error [%s]: %s", transcription_job.session_id, exc
            )
            return None


def _looks_like_filesystem_path(model_path: str) -> bool:
    return (
        os.path.isabs(model_path)
        or os.path.sep in model_path
        or (os.path.altsep is not None and os.path.altsep in model_path)
    )
