import time

from realtimestt_service.inference import (
    InferenceEngine,
    TranscriptionJob,
    TranscriptionRuntimeConfig,
    clean_transcription_text,
)


class FakeSegment:
    def __init__(self, text):
        self.text = text


class FakeInfo:
    duration = 1.25


class FakeWhisperModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio_data, **kwargs):
        self.calls.append((audio_data, kwargs))
        return [FakeSegment("  你好 Subtitle by 測試  ")], FakeInfo()


def test_clean_transcription_text_removes_known_artifacts():
    assert clean_transcription_text("字幕由測試 Subscribe 完成") == "測試  完成"


def test_inference_engine_transcribes_and_publishes_result():
    published = []
    fake_model = FakeWhisperModel()
    config = TranscriptionRuntimeConfig(
        model_path="local-model",
        device="cpu",
        compute_type="int8",
        initial_prompt="繁體中文會議記錄",
    )
    engine = InferenceEngine(
        config=config,
        model_loader=lambda runtime_config: fake_model,
        event_publisher=published.append,
    )
    engine.load_model()

    job = TranscriptionJob(
        session_id="room-1",
        channel_id="user-a",
        audio_data=[0.0, 0.1],
        timestamp=time.time(),
        language="zh",
    )

    engine.transcribe(job)

    assert fake_model.calls == [
        (
            [0.0, 0.1],
            {
                "beam_size": 5,
                "language": "zh",
                "initial_prompt": "繁體中文會議記錄",
                "vad_filter": True,
                "vad_parameters": {"min_silence_duration_ms": 500},
                "temperature": 0.0,
                "condition_on_previous_text": False,
                "repetition_penalty": 1.1,
            },
        )
    ]
    assert published == [
        {
            "type": "transcription",
            "session_id": "room-1",
            "channel_id": "user-a",
            "text": "你好  測試",
            "timestamp": job.timestamp,
            "duration": 1.25,
        }
    ]
