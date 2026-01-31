# 系統架構設計

## 概述

general_stt_server 採用分層架構設計，將語音轉錄流程分為四個主要層次，每層負責特定的功能模組。

## 整體架構圖

```
┌─────────────────────────────────────────────────────────────────┐
│                          應用服務層                              │
│  ┌──────────────────┐  ┌──────────────────┐                    │
│  │  FastAPI Router  │  │ ConnectionManager │                   │
│  │  - /v1/audio/*   │  │  - Session 管理   │                   │
│  │  - /v1/events/*  │  │  - 連線追蹤       │                   │
│  └──────────────────┘  └──────────────────┘                    │
└────────────────┬────────────────────┬────────────────────────────┘
                 │                    │
                 ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                          核心邏輯層                              │
│  ┌──────────────────┐  ┌──────────────────┐                    │
│  │  VADProcessor    │  │ InferenceEngine  │                    │
│  │  - 語音偵測      │  │  - 模型載入       │                   │
│  │  - 自動斷句      │  │  - 並行推論       │                   │
│  │  - 音訊預處理    │  │  - 結果輸出       │                   │
│  └──────────────────┘  └──────────────────┘                    │
└────────────────┬────────────────────┬────────────────────────────┘
                 │                    │
                 ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                          基礎設施層                              │
│  ┌──────────────────┐  ┌──────────────────┐                    │
│  │  Queue Manager   │  │  Thread Pool     │                    │
│  │  - 任務佇列       │  │  - Worker 管理    │                   │
│  │  - Event Bus     │  │  - 執行緒池       │                   │
│  └──────────────────┘  └──────────────────┘                    │
└────────────────────────────────────────────────────────────────┘
```

## 層次說明

### 1. 應用服務層 (API Layer)

**責任**: 處理 HTTP/WebSocket 請求，管理客戶端連線

**主要組件**:

#### FastAPI Application
```python
app = FastAPI(title="STT SIP Server", version="2.0.0")
app.add_middleware(CORSMiddleware, ...)
```

**功能**:
- RESTful API 路由
- WebSocket 連線管理
- CORS 中介軟體
- 請求驗證

#### ConnectionManager
```python
class ConnectionManager:
    def __init__(self):
        # session_id -> Set[WebSocket]
        self.rooms: Dict[str, Set[WebSocket]] = {}
```

**功能**:
- 管理 Session 與 WebSocket 的映射關係
- 實現 Room 概念（一對多廣播）
- 追蹤連線狀態
- 處理連線失效

**關鍵方法**:
- `connect(session_id, ws)`: 新增連線到 Session
- `disconnect(session_id, ws)`: 移除連線
- `broadcast(event)`: 廣播訊息到 Session 內所有連線

### 2. 核心邏輯層 (Business Logic Layer)

**責任**: 實現語音轉錄的核心功能

#### VADProcessor

**繼承關係**: 
```python
class VADProcessor(AudioToTextRecorder):
    """
    繼承自 RealtimeSTT.AudioToTextRecorder
    但剝離了推論邏輯，僅保留 VAD 功能
    """
```

**工作流程**:
```
音訊輸入 → VAD 偵測 → 語音開始 → 持續錄音 → VAD 偵測靜音 → 語音結束 → 打包音訊
```

**狀態機**:
```
inactive → listening → recording → processing → inactive
```

**關鍵回調**:
- `on_vad_start()`: 偵測到語音開始
- `on_recording_start()`: 開始錄音
- `on_recording_stop()`: 停止錄音，觸發推論
- `perform_final_transcription()`: 將音訊打包送入佇列

**Monkey Patching**:
```python
# 替換 RealtimeSTT 的內部 Worker
AudioToTextRecorder._transcription_worker = dummy_worker
```

目的：
- 避免 RealtimeSTT 啟動內部推論執行緒
- 將推論邏輯移到外部統一管理
- 提升資源利用率

#### InferenceEngine

**責任**: GPU 模型載入與推論

**架構**:
```python
class InferenceEngine:
    def __init__(self):
        self.model = None  # WhisperModel 實例
        self.lock = threading.Lock()
```

**模型載入**:
```python
def load_model(self):
    from faster_whisper import WhisperModel
    self.model = WhisperModel(
        WHISPER_MODEL_PATH, 
        device="cuda", 
        compute_type="float16",
        local_files_only=True
    )
```

**推論流程**:
```python
def transcribe(self, job: dict):
    segments, info = self.model.transcribe(
        job["audio_data"], 
        beam_size=5, 
        language="zh"
    )
    text = " ".join([s.text for s in segments])
    # 發送結果到 Event Bus
    asyncio.run_coroutine_threadsafe(event_bus.put(result), main_loop)
```

### 3. 基礎設施層 (Infrastructure Layer)

**責任**: 提供並發處理、訊息傳遞等基礎設施

#### 任務佇列系統

**組件**:
```python
inference_queue = queue.Queue()        # VAD → GPU Worker
event_bus = asyncio.Queue()            # GPU → WebSocket Broadcaster
```

**資料流**:
```
VADProcessor → inference_queue → Dispatcher → ThreadPool → InferenceEngine
                                                                 ↓
WebSocket Clients ← Broadcaster ← event_bus ← InferenceEngine
```

#### Worker Dispatcher

```python
def worker_dispatcher():
    """從 Queue 取出並分發給 ThreadPool"""
    while True:
        job = inference_queue.get()
        inference_executor.submit(engine.transcribe, job)
```

**特點**:
- 單一 Dispatcher 執行緒
- 使用 `ThreadPoolExecutor` 管理 Worker
- 非阻塞式任務分發

#### ThreadPoolExecutor

```python
MAX_INFERENCE_WORKERS = 2
inference_executor = ThreadPoolExecutor(max_workers=MAX_INFERENCE_WORKERS)
```

**優點**:
- 限制並行推論數量，避免 OOM
- 自動管理執行緒生命週期
- 支援 Future 模式（目前未使用）

#### Event Broadcaster

```python
async def broadcaster():
    """負責將 event_bus 的資料推給 manager 進行廣播"""
    while True:
        event = await event_bus.get()
        await manager.broadcast(event)
```

**特點**:
- 在 asyncio Event Loop 中運行
- 非阻塞式廣播
- 自動處理失效連線

## 資料結構

### Job (推論任務)

```python
job = {
    "session_id": str,        # Session 識別碼
    "channel_id": str,        # 聲道識別碼
    "audio_data": np.ndarray, # 音訊資料 (float32, 16kHz)
    "timestamp": float,       # 任務建立時間
    "language": str          # 語言代碼
}
```

### Event (廣播事件)

```python
event = {
    "type": "transcription",  # 事件類型
    "session_id": str,        # Session 識別碼
    "channel_id": str,        # 聲道識別碼
    "text": str,              # 轉錄文字
    "timestamp": float,       # 轉錄時間
    "duration": float        # 音訊時長
}
```

## 並發模型

### Threading vs Multiprocessing

**選擇 Threading 的原因**:

1. **Windows 兼容性**: 避免 Multiprocessing 的 pickle 限制
2. **資源共享**: 模型載入一次，多執行緒共用
3. **GIL 釋放**: faster-whisper 底層是 C++，會釋放 GIL
4. **高併發連線**: 輕量級執行緒適合處理大量 WebSocket

**架構對比**:

```
原始 RealtimeSTT (Multiprocessing):
每個客戶端 → 獨立 Process → 獨立模型載入 → 高記憶體消耗

general_stt_server (Threading):
多個客戶端 → 共用 VAD Thread Pool → 共用 GPU 推論 Pool → 低記憶體消耗
```

### 執行緒分類

| 執行緒類型 | 數量 | 功能 |
|-----------|------|------|
| WebSocket Handler | N (動態) | 接收客戶端音訊 |
| VAD Thread | N (動態) | 每個 WebSocket 一個 VAD 處理器 |
| Dispatcher Thread | 1 | 分發推論任務 |
| Inference Worker | 2-8 (可配置) | 執行 GPU 推論 |
| Broadcaster Task | 1 (asyncio) | 廣播轉錄結果 |

## 生命週期管理

### 啟動流程

```python
@app.on_event("startup")
async def startup():
    # 1. 載入模型
    engine.load_model()
    
    # 2. 啟動 Dispatcher
    threading.Thread(target=worker_dispatcher, daemon=True).start()
    
    # 3. 啟動 Broadcaster
    asyncio.create_task(broadcaster())
```

### 連線生命週期

```
Client Connect → WebSocket Accept → Config Handshake → VADProcessor Init
                                                              ↓
                                                         Start VAD Thread
                                                              ↓
                                            Audio Stream ← → VAD Processing
                                                              ↓
                                                    Disconnect / Exception
                                                              ↓
                                            VADProcessor Shutdown → Cleanup
```

### 關閉流程

```python
def shutdown(self):
    # 1. 設定關閉標誌
    self.is_shut_down = True
    
    # 2. 觸發所有 Event
    self.shutdown_event.set()
    
    # 3. 等待執行緒結束
    self.recording_thread.join(timeout=1)
    self.transcript_process.join(timeout=1)
    
    # 4. 清理資源
    self.parent_transcription_pipe.close()
    gc.collect()
```

## 錯誤處理

### 連線錯誤

```python
try:
    while True:
        data = await websocket.receive_bytes()
        vad_processor.feed_audio(data)
except WebSocketDisconnect:
    logger.info("Disconnected")
finally:
    vad_processor.shutdown()
    await manager.disconnect(session_id, websocket)
```

### 推論錯誤

```python
def transcribe(self, job: dict):
    try:
        segments, info = self.model.transcribe(...)
        # 處理結果
    except Exception as e:
        logger.error(f"Inference Error: {e}")
        # 不中斷服務，繼續處理下一個任務
```

### 廣播錯誤

```python
for ws in target_sockets:
    try:
        await ws.send_text(message)
    except Exception as e:
        dead_sockets.append(ws)  # 標記失效連線

# 清理失效連線
for ws in dead_sockets:
    self.rooms[session_id].remove(ws)
```

## 可擴展性

### 水平擴展

**方案**: 使用外部訊息佇列（如 Redis、RabbitMQ）

```
Client → Load Balancer → Server 1 (VAD) → Redis Queue → GPU Server 1
                       → Server 2 (VAD) →            → GPU Server 2
                       → Server 3 (VAD) →            → GPU Server 3
```

### 垂直擴展

**方案**: 增加 GPU 數量與 Worker 數量

```python
# 多 GPU 配置
MAX_INFERENCE_WORKERS = 16  # 每張 GPU 8 Workers
devices = [0, 1]  # 使用 GPU 0 和 1

# Worker 分配
workers = [
    WhisperModel(..., device=f"cuda:{i%len(devices)}")
    for i in range(MAX_INFERENCE_WORKERS)
]
```

## 效能考量

### 記憶體管理

1. **模型共享**: 所有 Worker 共用同一個模型實例
2. **音訊緩衝**: VAD 僅保留當前句子的音訊
3. **連線清理**: 及時清理斷開的 WebSocket

### CPU 優化

1. **VAD 使用 ONNX**: `silero_use_onnx=True`
2. **音訊重採樣**: 使用 `scipy.signal.resample` (NumPy 加速)
3. **非阻塞 I/O**: WebSocket 使用 asyncio

### GPU 優化

1. **FP16 推論**: `compute_type="float16"`
2. **批次處理**: 未來可實現動態批次
3. **模型量化**: 可使用 `int8` 進一步降低 VRAM

## 總結

general_stt_server 的架構設計充分考慮了：
- **模組化**: 清晰的層次劃分
- **可擴展**: 支援水平與垂直擴展
- **高效能**: Threading + GPU 並行
- **穩定性**: 完善的錯誤處理
- **離線支援**: Monkey Patching 確保離線運行

這種設計使系統能夠在資源受限的環境下支援大量並發連線，同時保持高轉錄品質。
