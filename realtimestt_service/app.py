import asyncio
import logging
import os
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional

import torch
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .audio import TARGET_SAMPLE_RATE, resample_pcm16
from .config import build_stt_model_config
from .connection_manager import ConnectionManager
from .inference import InferenceEngine, TranscriptionRuntimeConfig
from .offline import configure_offline_environment, patch_torch_hub_for_offline_silero
from .schemas import StreamConfig


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("STT-Service")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BASE_DIR, "models")
MAX_INFERENCE_WORKERS = 2

configure_offline_environment(MODELS_DIR)
patch_torch_hub_for_offline_silero(torch, MODELS_DIR, logger)

from .vad import VADProcessor  # noqa: E402


@dataclass
class SttServerContext:
    models_dir: str
    inference_queue: queue.Queue = field(default_factory=queue.Queue)
    manager: ConnectionManager = field(
        default_factory=lambda: ConnectionManager(logger)
    )
    inference_executor: ThreadPoolExecutor = field(
        default_factory=lambda: ThreadPoolExecutor(max_workers=MAX_INFERENCE_WORKERS)
    )
    event_bus: Optional[asyncio.Queue] = None
    main_loop: Optional[asyncio.AbstractEventLoop] = None
    broadcaster_task: Optional[asyncio.Task] = None
    dispatcher_thread: Optional[threading.Thread] = None
    engine: InferenceEngine = field(init=False)

    def __post_init__(self):
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

    def publish_from_worker(self, event: dict):
        if self.main_loop and self.event_bus:
            asyncio.run_coroutine_threadsafe(self.event_bus.put(event), self.main_loop)

    def start_dispatcher(self):
        if self.dispatcher_thread and self.dispatcher_thread.is_alive():
            return
        self.dispatcher_thread = threading.Thread(
            target=self.worker_dispatcher, daemon=True
        )
        self.dispatcher_thread.start()

    def worker_dispatcher(self):
        logger.info("Worker Dispatcher Started.")
        while True:
            try:
                job = self.inference_queue.get()
                if job is None:
                    logger.info("Dispatcher received shutdown signal.")
                    break
                self.inference_executor.submit(self.engine.transcribe, job)
            except Exception as exc:
                logger.error("Dispatcher Error: %s", exc)

    async def shutdown(self):
        self.inference_queue.put(None)
        self.inference_executor.shutdown(wait=True)
        logger.info("Inference Executor stopped.")


context = SttServerContext(models_dir=MODELS_DIR)


async def broadcaster(app_context: SttServerContext = context):
    while True:
        if app_context.event_bus:
            event = await app_context.event_bus.get()
            await app_context.manager.broadcast(event)
        else:
            await asyncio.sleep(0.1)


def create_app(app_context: SttServerContext = context) -> FastAPI:
    service_app = FastAPI(title="STT SIP Server", version="2.0.0")
    service_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @service_app.on_event("startup")
    async def startup():
        app_context.main_loop = asyncio.get_running_loop()
        app_context.event_bus = asyncio.Queue()
        app_context.engine.load_model()
        app_context.start_dispatcher()
        app_context.broadcaster_task = asyncio.create_task(broadcaster(app_context))
        logger.info("System Startup Correctly.")

    @service_app.on_event("shutdown")
    async def shutdown():
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

    @service_app.websocket("/v1/audio/stream")
    async def audio_stream(
        websocket: WebSocket,
        session_id: str = Query(..., description="Unique Session ID"),
        channel_id: str = Query(..., description="Speaker/Channel ID"),
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

            if first_msg["type"] == "websocket.receive" and "text" in first_msg:
                try:
                    config = StreamConfig.model_validate_json(first_msg["text"])
                    logger.info("Stream config: %s", config)
                except Exception:
                    logger.warning(
                        "First message was text but not valid config, using defaults."
                    )
            elif first_msg["type"] == "websocket.receive" and "bytes" in first_msg:
                pass

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

            if "bytes" in first_msg and first_msg["bytes"]:
                vad_processor.feed_audio(first_msg["bytes"])

            while True:
                data = await websocket.receive_bytes()
                if config.sample_rate != TARGET_SAMPLE_RATE:
                    data = resample_pcm16(data, config.sample_rate)
                vad_processor.feed_audio(data)

        except WebSocketDisconnect:
            logger.info("Stream disconnected: %s/%s", session_id, channel_id)
        except Exception as exc:
            if "ConnectionClosed" in str(type(exc).__name__):
                logger.info(
                    "Stream disconnected (ConnectionClosed): %s/%s",
                    session_id,
                    channel_id,
                )
            else:
                logger.error("Stream error: %s", exc)
        finally:
            if vad_processor:
                vad_processor.shutdown()
            if receive_text:
                await app_context.manager.disconnect(session_id, websocket)

    @service_app.websocket("/v1/events/sub")
    async def event_subscription(
        websocket: WebSocket,
        session_id: str = Query(..., description="Session ID to subscribe"),
    ):
        await websocket.accept()
        await app_context.manager.connect(session_id, websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            await app_context.manager.disconnect(session_id, websocket)

    return service_app


app = create_app()


def run():
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
