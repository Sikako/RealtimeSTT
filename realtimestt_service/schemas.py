from typing import Optional

from pydantic import BaseModel


class StreamConfig(BaseModel):
    sample_rate: int = 16000
    encoding: str = "pcm_16"
    language: Optional[str] = "zh"
