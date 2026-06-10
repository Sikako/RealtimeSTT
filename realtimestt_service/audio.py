import numpy as np
import scipy.signal


TARGET_SAMPLE_RATE = 16000


def resample_pcm16(
    data: bytes, source_rate: int, target_rate: int = TARGET_SAMPLE_RATE
) -> bytes:
    if source_rate == target_rate:
        return data

    audio_np = np.frombuffer(data, dtype=np.int16)
    num_samples = int(len(audio_np) * target_rate / source_rate)
    if num_samples <= 0:
        return b""

    resampled_audio = scipy.signal.resample(audio_np, num_samples)
    return np.asarray(resampled_audio, dtype=np.int16).tobytes()
