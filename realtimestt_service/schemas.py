from typing import Literal, TypedDict

from pydantic import BaseModel, Field


class TranscriptionEvent(TypedDict):
    type: str
    session_id: str
    channel_id: str
    text: str
    timestamp: float
    duration: float


class StreamConfig(BaseModel):
    sample_rate: int = Field(default=16000, ge=8000, le=48000)
    encoding: Literal["pcm_16"] = "pcm_16"
    language: str | None = "zh"
