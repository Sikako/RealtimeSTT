import os
import queue
import time
import json
import logging
import threading
import asyncio
import copy
import multiprocessing as mp
import platform
import numpy as np
import scipy.signal
from typing import Dict, List, Optional, Set
from pydantic import BaseModel, ValidationError
from concurrent.futures import ThreadPoolExecutor
import torch

# =========================================================================
# Monkey Patch: torch.hub.load for Offline Silero VAD
# =========================================================================
_original_torch_hub_load = torch.hub.load

def offline_torch_hub_load(repo_or_dir, model, *args, **kwargs):
    """
    攔截 torch.hub.load，若目標是 silero-vad，強制導向本地 Cache 目錄。
    並將 source 設為 'local'，避免聯網檢查。
    """
    if "silero-vad" in repo_or_dir:
        # 建構本地路徑: <MODELS_DIR>/hub/snakers4_silero-vad_master
        # 注意: 目錄名稱可能因版本不同而異 (master/master.zip_extracted 等)
        # 這裡根據 list_dir 結果，假設是用戶手動解壓或之前下載好的 'snakers4_silero-vad_master'
        local_repo_path = os.path.join(MODELS_DIR, "hub", "snakers4_silero-vad_master")
        
        if os.path.exists(local_repo_path):
            logger.info(f"Redirecting Silero VAD load to local path: {local_repo_path}")
            # 強制改為 local 模式
            # 注意: torch.hub.load(source='local', repo_or_dir=path, ...)
            kwargs["source"] = "local"
            return _original_torch_hub_load(local_repo_path, model, *args, **kwargs)
        else:
            logger.warning(f"Silero VAD local path not found: {local_repo_path}, falling back to default.")
            
    return _original_torch_hub_load(repo_or_dir, model, *args, **kwargs)

torch.hub.load = offline_torch_hub_load

# FastAPI 核心
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

# RealtimeSTT (VAD 核心)
from RealtimeSTT import AudioToTextRecorder

# =========================================================================
# Monkey Patch: 強制使用 Threading 避免 Windows 上開啟過多 Process
# =========================================================================
def start_thread_patch(self, target=None, args=()):
    """
    覆寫 RealtimeSTT 的 _start_thread 方法。
    強制在所有平台上使用 threading.Thread，以支援高併發連線。
    """
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()
    return thread

# 應用 Patch
AudioToTextRecorder._start_thread = start_thread_patch

# =========================================================================
# 設定 Log
# =========================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("STT-Service")

# =========================================================================
# 環境 configuration (離線模型支援)
# =========================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
# 自動偵測可用模型 (優先順序: Medium -> Large -> Small -> Tiny)
def find_available_model():
    priorities = ["medium", "large-v2", "small", "tiny"]
    for size in priorities:
        for d in os.listdir(MODELS_DIR):
            if f"faster-whisper-{size}" in d and os.path.isdir(os.path.join(MODELS_DIR, d)):
                path = os.path.join(MODELS_DIR, d)
                logger.info(f"Found local model: {size} at {path}")
                return path
    logger.warning("No local model found in priority list, defaulting to 'tiny'")
    return "tiny"

WHISPER_MODEL_PATH = find_available_model()

# 設置環境變數確保 RealtimeSTT 和 faster_whisper 使用離線資源
os.environ["TORCH_HOME"] = MODELS_DIR
os.environ["HF_HUB_OFFLINE"] = "1"

# 佇列與執行緒池
inference_queue = queue.Queue()       # VAD -> GPU Worker
event_bus: Optional[asyncio.Queue] = None # GPU -> WebSocket Broadcaster

# GPU Worker 設定
MAX_INFERENCE_WORKERS = 2  # 根據顯卡 VRAM 大小調整並行數量
inference_executor = ThreadPoolExecutor(max_workers=MAX_INFERENCE_WORKERS)

# =========================================================================
# 核心邏輯層 - VAD 處理器
# =========================================================================
def dummy_worker(*args, **kwargs):
    """虛擬 Worker，用於替換 RealtimeSTT 的 Internal Processing"""
    # args[0] -> conn
    # args[7] -> ready_event (需通知主程序 initialization 完成)
    
    conn = args[0]
    
    try:
        ready_event = args[7]
        if ready_event:
            ready_event.set()
    except IndexError:
        pass

    while True:
        try:
            if conn.poll(0.5): conn.recv() # 清空 pipe 防止阻塞
        except: break

patch_lock = threading.Lock()

class VADProcessor(AudioToTextRecorder):
    """
    僅負責 VAD (語音活動偵測) 與斷句的處理器。
    繼承自 RealtimeSTT.AudioToTextRecorder 但剝離推論邏輯。
    """
    def __init__(self, session_id: str, channel_id: str, **kwargs):
        self.session_id = session_id
        self.channel_id = channel_id
        
        if 'input_queue' in kwargs: kwargs.pop('input_queue')
        
        # 攔截 RealtimeSTT 內部 Worker
        with patch_lock:
            self._original_worker = AudioToTextRecorder._transcription_worker
            AudioToTextRecorder._transcription_worker = dummy_worker
            
            try:
                # 參數優化以適應 Server 場景
                super().__init__(
                    model=WHISPER_MODEL_PATH, 
                    download_root=MODELS_DIR,
                    enable_realtime_transcription=False, # 禁用即時轉錄
                    use_microphone=False, 
                    spinner=False, 
                    debug_mode=False,
                    level=logging.INFO, # 開啟 INFO 以檢視 VAD 狀態
                    # VAD 參數微調
                    silero_sensitivity=0.4,
                    min_length_of_recording=0.5,
                    post_speech_silence_duration=0.6,
                    # Callbacks for debugging
                    on_vad_detect_start=lambda: logger.info(f"[{self.session_id}][{self.channel_id}] VAD: Listening..."),
                    on_vad_start=lambda: logger.info(f"[{self.session_id}][{self.channel_id}] VAD: Speech Detected (Start)"),
                    on_vad_stop=lambda: logger.info(f"[{self.session_id}][{self.channel_id}] VAD: Speech Ended (Stop)"),
                    on_recording_start=self._handle_recording_start,
                    on_recording_stop=self._handle_recording_stop, # Hook to trigger transcription
                    # 避免在 Server 端列印過多 log (但為了 Debug 先註解掉或設為 False)
                    # no_log_file=True, 
                    **kwargs
                )
            finally:
                AudioToTextRecorder._transcription_worker = self._original_worker
            
            # 手動初始化狀態
            self.start_recording_on_voice_activity = True
            
            # 確保狀態正確
            self.is_recording = False 

            # Fix: 清除 RealtimeSTT 可能重複添加的 Logger Handlers
            # 避免每個連線都多一組 Console Output
            # Library 內部 logger 名稱為 "realtimestt" (見 audio_recorder.py line 62)
            lib_logger = logging.getLogger("realtimestt")
            lib_logger.handlers = []
            lib_logger.propagate = True # 讓 Log 向上傳遞給 Server Root Logger 統一列印 

    def _handle_recording_start(self):
        """開始錄音時，啟用靜音自動停止"""
        logger.info(f"[{self.session_id}][{self.channel_id}] Recording Started")
        self.stop_recording_on_voice_deactivity = True

    def _handle_recording_stop(self):
        """
        當 VAD 偵測到說話結束並停止錄音時，觸發此回調。
        將收集到的 Frames 組合後進行推論，並重置 VAD 等待下一句。
        """
        logger.info(f"[{self.session_id}][{self.channel_id}] Recording Stopped, processing {len(self.frames)} frames...")
        
        if self.frames:
            # 組合音訊 (frames 是 list of bytes)
            audio_bytes = b"".join(self.frames)
            self.perform_final_transcription(audio_bytes)
        
        # 重置旗標以允許下一句偵測
        self.start_recording_on_voice_activity = True
    
    def perform_final_transcription(self, audio_bytes=None, use_prompt=True) -> str:
        """當偵測到完整句子時觸發，將音訊打包放入全域推論佇列"""
        with self.transcription_lock:
            if not audio_bytes: 
                # RealtimeSTT 有時會傳 None，需檢查
                if hasattr(self, 'audio') and self.audio is not None:
                    audio_bytes = copy.deepcopy(self.audio)
                else:
                    return ""
            
            if not audio_bytes: return ""

            # 轉換 int16 -> float32 (faster-whisper 需要 float32)
            # RealtimeSTT 內部使用 int16
            audio_data = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

            job = {
                "session_id": self.session_id,
                "channel_id": self.channel_id,
                "audio_data": audio_data,
                "timestamp": time.time(),
                "language": self.language or "zh"
            }
            
            logger.info(f"[{self.session_id}][{self.channel_id}] Sentence detected ({len(audio_data)/16000:.2f}s), queuing...")
            inference_queue.put(job)
            
            # 重置狀態
            self.allowed_to_early_transcribe = True
            self._set_state("inactive")
            return ""

    def _realtime_worker(self): 
        # 禁用 realtime worker
        pass

    def shutdown(self):
        """
        覆寫 shutdown 以支援 Threading 模式 (Thread 沒有 terminate 方法)
        """
        import gc
        
        with self.shutdown_lock:
            if self.is_shut_down:
                return

            self.is_shut_down = True
            self.start_recording_event.set()
            self.stop_recording_event.set()

            self.shutdown_event.set()
            self.is_recording = False
            self.is_running = False

            # 等待 Recording Thread
            if self.recording_thread:
                self.recording_thread.join(timeout=1)

            # 等待 Reader Thread (我們 Patch 後也是 Thread)
            if self.use_microphone.value:
                # Reader process in our patched version is also a thread if use_microphone is True
                # But here we set use_microphone=False in __init__, so this block might skip.
                # Just in case:
                if hasattr(self, 'reader_process') and self.reader_process:
                     self.reader_process.join(timeout=1)

            # 等待 Transcription Worker (Dummy Worker)
            # 在 Patch 後它是 Thread
            if self.transcript_process:
                self.transcript_process.join(timeout=1)
                if self.transcript_process.is_alive():
                    logger.warning("Transcription thread did not join in time.")

            # 關閉 Pipe
            try:
                self.parent_transcription_pipe.close()
            except:
                pass

            if self.enable_realtime_transcription:
                if self.realtime_thread:
                    self.realtime_thread.join(timeout=1)
            
            gc.collect()

# =========================================================================
# 核心邏輯層 - GPU 推論引擎
# =========================================================================

# 訓練資料常見的幻覺/雜訊 (Safe Artifacts only)
KNOWN_ARTIFACTS = [
    "字幕由", "Subtitle by", "Amara.org", "MBC News", 
    "不代表本台", "alugha", "Sous-titres",
    "點擊訂閱", "Subscribe", "視聴ありがとうございました"
]

class InferenceEngine:
    def __init__(self):
        self.model = None
        self.lock = threading.Lock()

    def load_model(self):
        if not os.path.exists(WHISPER_MODEL_PATH):
            logger.error(f"FATAL: Model not found at {WHISPER_MODEL_PATH}")
            return
        
        logger.info(f"Loading Whisper Model from {WHISPER_MODEL_PATH} ...")
        try:
            from faster_whisper import WhisperModel
            # 載入模型 (確保在 Main Thread 或初始化時載入一次)
            # device_index=0 預設使用第一張顯卡
            self.model = WhisperModel(
                WHISPER_MODEL_PATH, 
                device="cuda", 
                compute_type="float16", 
                local_files_only=True
            )
            logger.info("Model Loaded Successfully.")
        except Exception as e:
            logger.error(f"Failed to load model: {e}")

    def transcribe(self, job: dict):
        if not self.model:
            logger.error("Model not initialized!")
            return

        session_id = job["session_id"]
        channel_id = job["channel_id"]
        
        try:
            # model.transcribe 是 Thread-safe 的 (CTranslate2 釋放 GIL)
            # 但為了保險起見，如果是大量併發，還是可以考慮是否需要 Lock
            # 這裡為了最大化吞吐量，不加 python level lock，依賴 C++ 內部處理
            
            segments, info = self.model.transcribe(
                job["audio_data"], 
                beam_size=5, 
                language="zh", 
                initial_prompt="繁體中文會議記錄，對話清晰。",
                # [Hallucination Fix 1] 啟用模型內建 VAD 過濾靜音
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
                # [Hallucination Fix 2] 參數調優
                temperature=0.0, # Greedy decoding 對抗幻覺
                condition_on_previous_text=False, # 避免上下文毒化
                repetition_penalty=1.1 # 抑制重複
            )
            
            text = " ".join([s.text for s in segments]).strip()
            
            # [Hallucination Fix 3] 移除已知的訓練雜訊 (Artifact Cleaning)
            for artifact in KNOWN_ARTIFACTS:
                if artifact in text:
                    logger.warning(f"Removed artifact '{artifact}' from: {text}")
                    text = text.replace(artifact, "")
            
            text = text.strip()

            if text:
                logger.info(f"TRANSCRIPTION [{session_id}][{channel_id}]: {text}")
                
                result = {
                    "type": "transcription",
                    "session_id": session_id,
                    "channel_id": channel_id,
                    "text": text,
                    "timestamp": job["timestamp"],
                    "duration": info.duration
                }
                
                # 發送到 Event Bus
                if main_loop and event_bus:
                    asyncio.run_coroutine_threadsafe(event_bus.put(result), main_loop)
                    
        except Exception as e:
            logger.error(f"Inference Error [{session_id}]: {e}")

# 全域引擎實例
engine = InferenceEngine()

def worker_dispatcher():
    """從 Queue 取出並分發給 ThreadPool"""
    logger.info("Worker Dispatcher Started.")
    while True:
        try:
            job = inference_queue.get()
            if job is None: # Sentinel for shutdown
                logger.info("Dispatcher received shutdown signal.")
                break
                
            # 提交給 ThreadPool
            inference_executor.submit(engine.transcribe, job)
        except Exception as e:
            logger.error(f"Dispatcher Error: {e}")

# =========================================================================
# 應用服務層 - 連線管理 (支援 SIP Room 廣播)
# =========================================================================
class StreamConfig(BaseModel):
    sample_rate: int = 16000
    encoding: str = "pcm_16"
    language: Optional[str] = "zh"

class ConnectionManager:
    """
    管理 Session 與 WebSocket 的關聯。
    一個 Session 可以有多個 WebSocket (例如 User A, User B, SIP Server)。
    廣播時，該 Session 下的所有 Socket 都會收到訊息。
    """
    def __init__(self):
        # session_id -> Set[WebSocket]
        self.rooms: Dict[str, Set[WebSocket]] = {}
        self.lock = asyncio.Lock()

    async def connect(self, session_id: str, ws: WebSocket):
        await ws.accept()
        async with self.lock:
            if session_id not in self.rooms:
                self.rooms[session_id] = set()
            self.rooms[session_id].add(ws)
            logger.info(f"Client joined session {session_id}. Total: {len(self.rooms[session_id])}")

    async def disconnect(self, session_id: str, ws: WebSocket):
        async with self.lock:
            if session_id in self.rooms:
                if ws in self.rooms[session_id]:
                    self.rooms[session_id].remove(ws)
                if not self.rooms[session_id]:
                    del self.rooms[session_id]
        logger.info(f"Client left session {session_id}.")

    async def broadcast(self, event: dict):
        session_id = event.get("session_id")
        if not session_id: return
        
        # 取得該 Session 的所有連線 (快照避免迭代時修改)
        target_sockets = []
        async with self.lock:
            if session_id in self.rooms:
                target_sockets = list(self.rooms[session_id])
        
        if not target_sockets:
            return

        # 廣播
        message = json.dumps(event)
        dead_sockets = []
        for ws in target_sockets:
            try:
                await ws.send_text(message)
            except Exception as e:
                # logger.warning(f"Broadcast failed for socket in session {session_id}, removing. Error: {e}")
                dead_sockets.append(ws)
        
        # 清理失效連線
        if dead_sockets:
            async with self.lock:
                if session_id in self.rooms:
                    for ws in dead_sockets:
                        if ws in self.rooms[session_id]:
                            self.rooms[session_id].remove(ws)
                    if not self.rooms[session_id]:
                        del self.rooms[session_id]

manager = ConnectionManager()
main_loop = None 
broadcaster_task = None 

# =========================================================================
# API 路由層 (FastAPI)
# =========================================================================
app = FastAPI(title="STT SIP Server", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
async def startup():
    global main_loop, event_bus, broadcaster_task
    main_loop = asyncio.get_running_loop()
    event_bus = asyncio.Queue()
    
    # 1. 載入模型
    engine.load_model()
    
    # 2. 啟動 Dispatcher Thread
    threading.Thread(target=worker_dispatcher, daemon=True).start()
    
    # 3. 啟動廣播器 Loop Task
    broadcaster_task = asyncio.create_task(broadcaster())
    
    logger.info("System Startup Correctly.")
    
@app.on_event("shutdown")
async def shutdown():
    logger.info("Shutting down system...")
    
    # 1. 停止 Broadcaster
    if broadcaster_task:
        broadcaster_task.cancel()
        try:
            await broadcaster_task
        except asyncio.CancelledError:
            pass
    logger.info("Broadcaster stopped.")

    # 2. 停止 Dispatcher (送入 None 作為 Sentinel)
    inference_queue.put(None)
    
    # 3. 關閉 Thread Pool
    inference_executor.shutdown(wait=True)
    logger.info("Inference Executor stopped.")
    
    logger.info("System Shutdown Complete.")

async def broadcaster():
    """負責將 event_bus 的資料推給 manager 進行廣播"""
    while True:
        if event_bus:
            event = await event_bus.get()
            await manager.broadcast(event)
        else:
            await asyncio.sleep(0.1)

# --- Endpoint 1: 音訊輸入串流 (SIP Users) ---
@app.websocket("/v1/audio/stream")
async def audio_stream(
    websocket: WebSocket, 
    session_id: str = Query(..., description="Unique Session ID"), 
    channel_id: str = Query(..., description="Speaker/Channel ID"),
    receive_text: bool = Query(True, description="Whether to receive transcription on this socket")
):
    """
    主要音訊傳輸通道。
    - 接收原始 PCM 音訊
    - (可選) 接收該 Session 的轉錄結果
    """
    
    # 務必先 Accept 連線
    await websocket.accept()
    
    # 如果需要接收文字，我們將其加入 Manager
    if receive_text:
        await manager.connect(session_id, websocket)
    
    logger.info(f"Stream connected: {session_id}/{channel_id}")
    
    vad_processor = None
    
    try:
        # 1. Config Handshake (Optional but recommended)
        # 為了相容性，這裡做一個簡單的 check，如果第一包是 text 則是 config，否則直接當作 binary 16k handling
        # 但標準實作建議先傳 Config
        first_msg = await websocket.receive()
        
        config = StreamConfig() # Default
        
        if first_msg["type"] == "websocket.receive" and "text" in first_msg:
            try:
                config = StreamConfig.model_validate_json(first_msg["text"])
                logger.info(f"Stream config: {config}")
            except:
                logger.warning(f"First message was text but not invalid config, assuming default.")
        elif first_msg["type"] == "websocket.receive" and "bytes" in first_msg:
             # 第一包就是音訊，使用預設配置
             pass
        
        # 2. 初始化 VAD 處理器
        # 注意: 這裡會使用我們 Patch 過的 Threading 模式，非常輕量
        vad_processor = VADProcessor(
            session_id=session_id,
            channel_id=channel_id,
            language=config.language
        )
        vad_processor.start()

        # 如果第一包是 bytes，需先處理
        if "bytes" in first_msg and first_msg["bytes"]:
            vad_processor.feed_audio(first_msg["bytes"])

        # 3. 處理音訊串流 Loop
        while True:
            data = await websocket.receive_bytes()
            
            # 重採樣 (如果來源不是 16k)
            if config.sample_rate != 16000:
                # 簡單重採樣 (需優化效能，建議 Client 端做)
                audio_np = np.frombuffer(data, dtype=np.int16)
                num_samples = int(len(audio_np) * 16000 / config.sample_rate)
                if num_samples > 0:
                    resampled = scipy.signal.resample(audio_np, num_samples).astype(np.int16)
                    data = resampled.tobytes()
            
            vad_processor.feed_audio(data)

    except WebSocketDisconnect:
        logger.info(f"Stream disconnected: {session_id}/{channel_id}")
    except Exception as e:
        # 特別處理 ConnectionClosed，因為有時不會被 WebSocketDisconnect 捕獲
        if "ConnectionClosed" in str(type(e).__name__):
            logger.info(f"Stream disconnected (ConnectionClosed): {session_id}/{channel_id}")
        else:
            logger.error(f"Stream error: {e}")
    finally:
        if vad_processor:
            vad_processor.shutdown()
        if receive_text:
            await manager.disconnect(session_id, websocket)

# --- Endpoint 2: 純監聽/文字介面 (SIP Server Control) ---
@app.websocket("/v1/events/sub")
async def event_subscription(
    websocket: WebSocket, 
    session_id: str = Query(..., description="Session ID to subscribe")
):
    """
    僅訂閱特定 Session 的轉錄結果，不發送音訊。
    """
    await websocket.accept()
    await manager.connect(session_id, websocket)
    try:
        while True:
            await websocket.receive_text() # Keep alive / Ping
    except WebSocketDisconnect:
        await manager.disconnect(session_id, websocket)

if __name__ == "__main__":
    import uvicorn
    # 啟動 Server
    uvicorn.run(app, host="0.0.0.0", port=8000)