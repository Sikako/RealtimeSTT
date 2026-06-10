import copy
import gc
import logging
import queue
import threading
import time
import numpy as np
from RealtimeSTT import AudioToTextRecorder


def start_thread_patch(self, target=None, args=()):
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()
    return thread


AudioToTextRecorder._start_thread = start_thread_patch


def dummy_worker(*args, **kwargs):
    conn = args[0]

    try:
        ready_event = args[7]
        if ready_event:
            ready_event.set()
    except IndexError:
        pass

    while True:
        try:
            if conn.poll(0.5):
                conn.recv()
        except Exception:
            break


patch_lock = threading.Lock()


class VADProcessor(AudioToTextRecorder):
    def __init__(
        self,
        session_id: str,
        channel_id: str,
        model_path: str,
        models_dir: str,
        inference_queue: queue.Queue,
        logger: logging.Logger | None = None,
        **kwargs,
    ):
        self.session_id = session_id
        self.channel_id = channel_id
        self.inference_queue = inference_queue
        self.logger = logger or logging.getLogger(__name__)

        kwargs.pop("input_queue", None)

        with patch_lock:
            self._original_worker = AudioToTextRecorder._transcription_worker
            AudioToTextRecorder._transcription_worker = dummy_worker

            try:
                super().__init__(
                    model=model_path,
                    download_root=models_dir,
                    enable_realtime_transcription=False,
                    use_microphone=False,
                    spinner=False,
                    debug_mode=False,
                    level=logging.INFO,
                    silero_sensitivity=0.4,
                    min_length_of_recording=0.5,
                    post_speech_silence_duration=0.6,
                    on_vad_detect_start=lambda: self.logger.info(
                        "[%s][%s] VAD: Listening...",
                        self.session_id,
                        self.channel_id,
                    ),
                    on_vad_start=lambda: self.logger.info(
                        "[%s][%s] VAD: Speech Detected (Start)",
                        self.session_id,
                        self.channel_id,
                    ),
                    on_vad_stop=lambda: self.logger.info(
                        "[%s][%s] VAD: Speech Ended (Stop)",
                        self.session_id,
                        self.channel_id,
                    ),
                    on_recording_start=self._handle_recording_start,
                    on_recording_stop=self._handle_recording_stop,
                    **kwargs,
                )
            finally:
                AudioToTextRecorder._transcription_worker = self._original_worker

            self.start_recording_on_voice_activity = True
            self.is_recording = False

            lib_logger = logging.getLogger("realtimestt")
            lib_logger.handlers = []
            lib_logger.propagate = True

    def _handle_recording_start(self):
        self.logger.info("[%s][%s] Recording Started", self.session_id, self.channel_id)
        self.stop_recording_on_voice_deactivity = True

    def _handle_recording_stop(self):
        self.logger.info(
            "[%s][%s] Recording Stopped, processing %s frames...",
            self.session_id,
            self.channel_id,
            len(self.frames),
        )

        if self.frames:
            self.perform_final_transcription(b"".join(self.frames))

        self.start_recording_on_voice_activity = True

    def perform_final_transcription(self, audio_bytes=None, use_prompt=True) -> str:
        with self.transcription_lock:
            if not audio_bytes:
                if hasattr(self, "audio") and self.audio is not None:
                    audio_bytes = copy.deepcopy(self.audio)
                else:
                    return ""

            if not audio_bytes:
                return ""

            audio_data = (
                np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            )
            job = {
                "session_id": self.session_id,
                "channel_id": self.channel_id,
                "audio_data": audio_data,
                "timestamp": time.time(),
                "language": self.language or "zh",
            }

            self.logger.info(
                "[%s][%s] Sentence detected (%.2fs), queuing...",
                self.session_id,
                self.channel_id,
                len(audio_data) / 16000,
            )
            try:
                self.inference_queue.put(job, timeout=1)
            except queue.Full:
                self.logger.warning(
                    "[%s][%s] Inference queue is full; dropping audio segment.",
                    self.session_id,
                    self.channel_id,
                )

            self.allowed_to_early_transcribe = True
            self._set_state("inactive")
            return ""

    def _realtime_worker(self):
        pass

    def shutdown(self):
        with self.shutdown_lock:
            if self.is_shut_down:
                return

            self.is_shut_down = True
            self.start_recording_event.set()
            self.stop_recording_event.set()
            self.shutdown_event.set()
            self.is_recording = False
            self.is_running = False

            if self.recording_thread:
                self.recording_thread.join(timeout=1)

            if (
                self.use_microphone.value
                and hasattr(self, "reader_process")
                and self.reader_process
            ):
                self.reader_process.join(timeout=1)

            if self.transcript_process:
                self.transcript_process.join(timeout=1)
                if self.transcript_process.is_alive():
                    self.logger.warning("Transcription thread did not join in time.")

            try:
                self.parent_transcription_pipe.close()
            except Exception:
                pass

            if self.enable_realtime_transcription and self.realtime_thread:
                self.realtime_thread.join(timeout=1)

            gc.collect()
