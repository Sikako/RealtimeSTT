import asyncio
import logging
import os
import queue
import threading
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Mapping

import torch
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from .audio import TARGET_SAMPLE_RATE, resample_pcm16
from .config import SttModelConfig, build_stt_model_config
from .connection_manager import ConnectionManager
from .inference import InferenceEngine, TranscriptionJob, TranscriptionRuntimeConfig
from .offline import configure_offline_environment, patch_torch_hub_for_offline_silero
from .schemas import StreamConfig, TranscriptionEvent


logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BASE_DIR, "models")


def _int_from_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        logger.warning("Invalid %s value; using default %s.", name, default)
        return default


MAX_INFERENCE_WORKERS = _int_from_env("STT_MAX_INFERENCE_WORKERS", 1)
INFERENCE_QUEUE_MAX_SIZE = _int_from_env("STT_INFERENCE_QUEUE_MAX_SIZE", 100)
MAX_AUDIO_FRAME_BYTES = _int_from_env("STT_MAX_AUDIO_FRAME_BYTES", 1024 * 1024)
QUERY_ID_MAX_LENGTH = 128

InferenceJob = TranscriptionJob | Mapping[str, Any]

configure_offline_environment(MODELS_DIR)
patch_torch_hub_for_offline_silero(torch, MODELS_DIR, logger)

from .vad import VADProcessor  # noqa: E402


@dataclass
class SttServerContext:
    models_dir: str
    model_config: SttModelConfig = field(init=False)
    inference_queue: queue.Queue[InferenceJob | None] = field(
        default_factory=lambda: queue.Queue(maxsize=INFERENCE_QUEUE_MAX_SIZE)
    )
    manager: ConnectionManager = field(
        default_factory=lambda: ConnectionManager(logger)
    )
    inference_executor: ThreadPoolExecutor = field(
        default_factory=lambda: ThreadPoolExecutor(max_workers=MAX_INFERENCE_WORKERS)
    )
    event_bus: asyncio.Queue[TranscriptionEvent] | None = None
    main_loop: asyncio.AbstractEventLoop | None = None
    broadcaster_task: asyncio.Task[None] | None = None
    dispatcher_thread: threading.Thread | None = None
    engine: InferenceEngine = field(init=False)
    model_loaded: bool = False

    def __post_init__(self) -> None:
        self.model_config = build_stt_model_config(self.models_dir)
        logger.info(
            "Selected STT model: %s (device=%s, compute_type=%s)",
            self.model_config.model_path,
            self.model_config.device,
            self.model_config.compute_type,
        )
        self.engine = InferenceEngine(
            config=TranscriptionRuntimeConfig.from_stt_config(self.model_config),
            event_publisher=self.publish_from_worker,
            logger=logger,
        )

    def publish_from_worker(self, event: TranscriptionEvent) -> None:
        if not self.main_loop or not self.event_bus:
            return

        publish_coro = self.event_bus.put(event)
        try:
            future = asyncio.run_coroutine_threadsafe(publish_coro, self.main_loop)
        except RuntimeError:
            publish_coro.close()
            logger.warning("Failed to publish transcription event.", exc_info=True)
            return

        def log_publish_error(done_future) -> None:
            try:
                done_future.result()
            except Exception:
                logger.warning("Failed to publish transcription event.", exc_info=True)

        future.add_done_callback(log_publish_error)

    def start_dispatcher(self) -> None:
        if self.dispatcher_thread and self.dispatcher_thread.is_alive():
            return
        self.dispatcher_thread = threading.Thread(
            target=self.worker_dispatcher, daemon=True
        )
        self.dispatcher_thread.start()

    def worker_dispatcher(self) -> None:
        logger.info("Worker Dispatcher Started.")
        while True:
            job = self.inference_queue.get()
            try:
                if job is None:
                    logger.info("Dispatcher received shutdown signal.")
                    break
                self.inference_executor.submit(self.engine.transcribe, job)
            except Exception:
                logger.exception("Dispatcher Error")
            finally:
                self.inference_queue.task_done()

    async def shutdown(self) -> None:
        if self.dispatcher_thread:
            is_alive = getattr(self.dispatcher_thread, "is_alive", lambda: True)
            if is_alive():
                await asyncio.to_thread(self.inference_queue.put, None)
            await asyncio.to_thread(self.dispatcher_thread.join)

        self.inference_executor.shutdown(wait=True)
        logger.info("Inference Executor stopped.")


async def broadcaster(
    event_bus: asyncio.Queue[TranscriptionEvent],
    manager: ConnectionManager,
) -> None:
    while True:
        event = await event_bus.get()
        try:
            await manager.broadcast(event)
        except Exception:
            logger.exception("Broadcast Error")
        finally:
            event_bus.task_done()


def create_app(app_context: SttServerContext | None = None) -> FastAPI:
    if app_context is None:
        app_context = SttServerContext(models_dir=MODELS_DIR)

    async def startup() -> None:
        app_context.main_loop = asyncio.get_running_loop()
        app_context.event_bus = asyncio.Queue()
        app_context.model_loaded = await asyncio.to_thread(app_context.engine.load_model)
        app_context.start_dispatcher()
        app_context.broadcaster_task = asyncio.create_task(
            broadcaster(app_context.event_bus, app_context.manager)
        )
        logger.info("System Startup Correctly.")

    async def shutdown() -> None:
        logger.info("Shutting down system...")
        if app_context.broadcaster_task:
            app_context.broadcaster_task.cancel()
            try:
                await app_context.broadcaster_task
            except asyncio.CancelledError:
                pass
            logger.info("Broadcaster stopped.")
        await app_context.shutdown()
        logger.info("System Shutdown Complete.")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await startup()
        try:
            yield
        finally:
            await shutdown()

    service_app = FastAPI(
        title="STT SIP Server",
        version="2.0.0",
        lifespan=lifespan,
    )
    service_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @service_app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @service_app.get("/ready")
    async def ready() -> dict[str, bool]:
        return {
            "model_loaded": app_context.model_loaded,
            "dispatcher_started": bool(
                app_context.dispatcher_thread
                and app_context.dispatcher_thread.is_alive()
            ),
            "broadcaster_started": bool(
                app_context.broadcaster_task
                and not app_context.broadcaster_task.done()
            ),
        }

    @service_app.websocket("/v1/audio/stream")
    async def audio_stream(
        websocket: WebSocket,
        session_id: str = Query(
            ...,
            min_length=1,
            max_length=QUERY_ID_MAX_LENGTH,
            description="Unique Session ID",
        ),
        channel_id: str = Query(
            ...,
            min_length=1,
            max_length=QUERY_ID_MAX_LENGTH,
            description="Speaker/Channel ID",
        ),
        receive_text: bool = Query(
            True,
            description="Whether to receive transcription on this socket",
        ),
    ):
        await websocket.accept()
        if receive_text:
            await app_context.manager.connect(session_id, websocket)

        logger.info("Stream connected: %s/%s", session_id, channel_id)
        vad_processor = None

        try:
            first_msg = await websocket.receive()
            config = StreamConfig()
            first_audio = None

            if first_msg["type"] == "websocket.disconnect":
                logger.info(
                    "Stream disconnected before first frame: %s/%s",
                    session_id,
                    channel_id,
                )
                return

            if first_msg["type"] == "websocket.receive" and "text" in first_msg:
                try:
                    config = StreamConfig.model_validate_json(first_msg["text"])
                    logger.info("Stream config: %s", config)
                except ValidationError as exc:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "INVALID_STREAM_CONFIG",
                            "message": str(exc),
                        }
                    )
                    await websocket.close(code=1003)
                    return
            elif first_msg["type"] == "websocket.receive" and "bytes" in first_msg:
                first_audio = first_msg["bytes"]

            vad_processor = VADProcessor(
                session_id=session_id,
                channel_id=channel_id,
                model_path=app_context.model_config.model_path,
                models_dir=app_context.models_dir,
                inference_queue=app_context.inference_queue,
                logger=logger,
                language=config.language,
            )
            vad_processor.start()

            if first_audio:
                if len(first_audio) > MAX_AUDIO_FRAME_BYTES:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "AUDIO_FRAME_TOO_LARGE",
                            "message": "Audio frame exceeds maximum size.",
                        }
                    )
                    await websocket.close(code=1009)
                    return
                if config.sample_rate != TARGET_SAMPLE_RATE:
                    first_audio = resample_pcm16(first_audio, config.sample_rate)
                vad_processor.feed_audio(first_audio)

            while True:
                data = await websocket.receive_bytes()
                if len(data) > MAX_AUDIO_FRAME_BYTES:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "AUDIO_FRAME_TOO_LARGE",
                            "message": "Audio frame exceeds maximum size.",
                        }
                    )
                    await websocket.close(code=1009)
                    return
                if config.sample_rate != TARGET_SAMPLE_RATE:
                    data = resample_pcm16(data, config.sample_rate)
                vad_processor.feed_audio(data)

        except WebSocketDisconnect:
            logger.info("Stream disconnected: %s/%s", session_id, channel_id)
        except Exception:
            logger.exception("Stream error")
        finally:
            if vad_processor:
                vad_processor.shutdown()
            if receive_text:
                await app_context.manager.disconnect(session_id, websocket)

    @service_app.websocket("/v1/events/sub")
    async def event_subscription(
        websocket: WebSocket,
        session_id: str = Query(
            ...,
            min_length=1,
            max_length=QUERY_ID_MAX_LENGTH,
            description="Session ID to subscribe",
        ),
    ) -> None:
        await websocket.accept()
        await app_context.manager.connect(session_id, websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await app_context.manager.disconnect(session_id, websocket)

    return service_app


app = create_app()


def run() -> None:
    import uvicorn

    host = os.getenv("STT_HOST", "0.0.0.0")
    port = _int_from_env("STT_PORT", 8000)
    uvicorn.run(app, host=host, port=port)
