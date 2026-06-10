import asyncio
import logging

from realtimestt_service import app as app_module
from realtimestt_service.app import (
    SttServerContext,
    broadcaster,
    create_app,
)


class FakeExecutor:
    def __init__(self):
        self.submissions = []
        self.shutdown_called = False

    def submit(self, fn, job):
        self.submissions.append((fn, job))

    def shutdown(self, wait=True):
        self.shutdown_called = wait


def make_context(tmp_path):
    return SttServerContext(
        models_dir=str(tmp_path),
        inference_executor=FakeExecutor(),
    )


def test_context_uses_bounded_inference_queue(tmp_path):
    context = make_context(tmp_path)

    assert app_module.INFERENCE_QUEUE_MAX_SIZE == 100
    assert context.inference_queue.maxsize == app_module.INFERENCE_QUEUE_MAX_SIZE


def test_dispatcher_marks_jobs_and_shutdown_signal_done(tmp_path):
    context = make_context(tmp_path)
    job = {"session_id": "s1", "channel_id": "c1", "audio_data": [], "timestamp": 1}

    context.inference_queue.put(job)
    context.inference_queue.put(None)

    context.worker_dispatcher()

    assert context.inference_executor.submissions == [
        (context.engine.transcribe, job)
    ]
    assert context.inference_queue.unfinished_tasks == 0


def test_shutdown_joins_dispatcher_before_executor_shutdown(tmp_path):
    context = make_context(tmp_path)
    calls = []

    class DispatcherThread:
        def join(self):
            calls.append("join")

    context.dispatcher_thread = DispatcherThread()
    context.inference_executor.shutdown = lambda wait=True: calls.append("shutdown")

    asyncio.run(context.shutdown())

    assert calls == ["join", "shutdown"]


def test_publish_from_worker_logs_when_loop_rejects_event(
    tmp_path, monkeypatch, caplog
):
    context = make_context(tmp_path)
    context.main_loop = object()
    context.event_bus = asyncio.Queue()

    def reject_submission(coro, loop):
        coro.close()
        raise RuntimeError("event loop closed")

    monkeypatch.setattr(
        app_module.asyncio,
        "run_coroutine_threadsafe",
        reject_submission,
    )

    with caplog.at_level(logging.WARNING):
        context.publish_from_worker({"type": "transcription", "session_id": "s1"})

    assert "Failed to publish transcription event" in caplog.text


def test_broadcaster_continues_after_single_broadcast_failure():
    async def run_broadcaster():
        event_bus = asyncio.Queue()
        done = asyncio.Event()

        class Manager:
            def __init__(self):
                self.calls = 0

            async def broadcast(self, event):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("send failed")
                done.set()

        manager = Manager()
        await event_bus.put({"session_id": "s1"})
        await event_bus.put({"session_id": "s2"})
        task = asyncio.create_task(broadcaster(event_bus, manager))

        try:
            await asyncio.wait_for(done.wait(), timeout=1)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        return manager.calls

    assert asyncio.run(run_broadcaster()) == 2


def test_startup_loads_model_without_blocking_event_loop(tmp_path, monkeypatch):
    context = make_context(tmp_path)
    calls = []

    async def fake_to_thread(fn, *args, **kwargs):
        calls.append("to_thread")
        return fn(*args, **kwargs)

    def load_model():
        calls.append("load_model")
        return True

    monkeypatch.setattr(app_module.asyncio, "to_thread", fake_to_thread)
    context.engine.load_model = load_model
    service_app = create_app(context)

    async def run_lifecycle():
        async with service_app.router.lifespan_context(service_app):
            pass

    asyncio.run(run_lifecycle())

    assert calls[:2] == ["to_thread", "load_model"]


def test_create_app_uses_lifespan_instead_of_deprecated_event_hooks(tmp_path):
    service_app = create_app(make_context(tmp_path))

    assert service_app.router.on_startup == []
    assert service_app.router.on_shutdown == []
