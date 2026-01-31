# GPU 推論管線

## 概述

GPU 推論管線是 general_stt_server 的效能核心，負責將 VAD 偵測到的語音片段轉換為文字。本文檔詳細說明推論管線的設計、實作與優化策略。

## 架構設計

### 管線流程圖

```
VADProcessor → inference_queue → Dispatcher → ThreadPool → InferenceEngine
     (1)              (2)            (3)          (4)            (5)
                                                                  ↓
                                                          WhisperModel (GPU)
                                                                  ↓
                                                          Transcription
                                                                  ↓
                                                            event_bus
                                                                  ↓
                                                            Broadcaster
```

### 各階段說明

#### (1) 音訊打包 - VADProcessor

```python
def perform_final_transcription(self, audio_bytes=None, use_prompt=True) -> str:
    # 轉換格式
    audio_data = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    # 建立任務
    job = {
        "session_id": self.session_id,
        "channel_id": self.channel_id,
        "audio_data": audio_data,
        "timestamp": time.time(),
        "language": self.language or "zh"
    }
    
    # 放入佇列
    inference_queue.put(job)
```

**關鍵操作**:
- 音訊格式轉換 (int16 → float32)
- 標準化 (除以 32768.0)
- 附加元資料

#### (2) 任務佇列 - inference_queue

```python
inference_queue = queue.Queue()  # 無界佇列
```

**特性**:
- **Thread-safe**: 內建執行緒鎖
- **阻塞式**: `put()` 和 `get()` 可阻塞
- **FIFO**: 先進先出

**為何使用 Queue？**
- 解耦 VAD 與推論
- 緩衝突發流量
- 自動負載平衡

#### (3) 任務分發 - Dispatcher

```python
def worker_dispatcher():
    logger.info("Worker Dispatcher Started.")
    while True:
        try:
            job = inference_queue.get()  # 阻塞等待
            inference_executor.submit(engine.transcribe, job)
        except Exception as e:
            logger.error(f"Dispatcher Error: {e}")
```

**責任**:
- 從佇列取出任務
- 提交給執行緒池
- 錯誤處理

**為何需要 Dispatcher？**
- 統一任務分發邏輯
- 避免多執行緒競爭
- 簡化錯誤處理

#### (4) 執行緒池 - ThreadPoolExecutor

```python
MAX_INFERENCE_WORKERS = 2
inference_executor = ThreadPoolExecutor(max_workers=MAX_INFERENCE_WORKERS)
```

**優勢**:
- 限制並行數量（避免 OOM）
- 自動管理執行緒生命週期
- 支援 Future 模式（可擴展）

**Worker 數量選擇**:

| GPU VRAM | 模型大小 | 建議 Workers |
|----------|---------|-------------|
| 4GB      | tiny/small | 2-4 |
| 8GB      | medium | 2-4 |
| 12GB     | medium/large | 4-6 |
| 16GB+    | large | 6-8 |

#### (5) 推論引擎 - InferenceEngine

```python
class InferenceEngine:
    def __init__(self):
        self.model = None
        self.lock = threading.Lock()

    def load_model(self):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(
            WHISPER_MODEL_PATH, 
            device="cuda", 
            compute_type="float16",
            local_files_only=True
        )

    def transcribe(self, job: dict):
        segments, info = self.model.transcribe(
            job["audio_data"], 
            beam_size=5, 
            language="zh"
        )
        text = " ".join([s.text for s in segments]).strip()
        # 發送結果...
```

## Whisper 模型詳解

### faster-whisper 簡介

**faster-whisper** 是 OpenAI Whisper 的 C++ 實作，基於 CTranslate2。

**優勢**:
- **4x 更快**: 相比原版 Whisper
- **更低 VRAM**: 透過量化
- **釋放 GIL**: 真正的 Python 並行

### 模型大小與效能

| 模型 | 參數量 | VRAM (FP16) | 速度 (RTF*) | WER** |
|------|--------|-------------|------------|-------|
| tiny | 39M | ~1GB | 0.05 | ~10% |
| small | 244M | ~2GB | 0.15 | ~5% |
| medium | 769M | ~5GB | 0.30 | ~3% |
| large-v2 | 1550M | ~10GB | 0.50 | ~2% |

\* RTF (Real-Time Factor): 處理 1 秒音訊所需的時間  
** WER (Word Error Rate): 詞錯誤率（越低越好）

### 計算型別 (Compute Type)

```python
# FP32 (最高精度，最慢)
compute_type="float32"

# FP16 (平衡，建議) ✅
compute_type="float16"

# INT8 (最快，但精度下降)
compute_type="int8"
```

**建議**:
- GPU 推論: `float16`
- CPU 推論: `int8`

## 推論參數調整

### beam_size

**定義**: Beam Search 的寬度

**效果**:
- 1: Greedy Search (最快，可能不準確)
- 5: 標準 (平衡) ✅
- 10+: 更準確，但更慢

```python
segments, info = self.model.transcribe(
    audio_data,
    beam_size=5  # 建議值
)
```

### language

**指定語言**:
```python
language="zh"  # 中文
language="en"  # 英文
language=None  # 自動偵測（較慢）
```

**建議**: 明確指定語言以提升速度與準確度

### initial_prompt

**用途**: 提供上下文以改善轉錄品質

```python
segments, info = self.model.transcribe(
    audio_data,
    initial_prompt="繁體中文會議記錄，對話清晰。"
)
```

**範例**:
```python
# 醫療領域
initial_prompt="醫療病歷記錄，包含專業術語。"

# 技術會議
initial_prompt="技術討論會議，包含程式碼與專有名詞。"
```

### temperature

**定義**: 採樣溫度（控制隨機性）

```python
# 確定性輸出 (預設)
temperature=0.0

# 增加多樣性
temperature=0.8
```

**建議**: 保持 0.0 以獲得穩定結果

## 並發處理機制

### 為何 Threading 可行？

**關鍵**: faster-whisper 底層是 C++，會釋放 Python GIL

```python
# Python 偽代碼
def transcribe(audio):
    with nogil:  # 釋放 GIL
        result = cpp_transcribe(audio)  # C++ 實作
    return result
```

**結果**: 多執行緒可真正並行執行

### Thread-Safety

**faster-whisper 的 Thread-Safety**:

```python
# 單一模型實例，多執行緒呼叫
model = WhisperModel(...)

# Thread 1
model.transcribe(audio1)  # ✅ Safe

# Thread 2 (同時)
model.transcribe(audio2)  # ✅ Safe
```

**為何安全？**
- CTranslate2 內部有執行緒鎖
- 每次推論建立獨立的 CUDA Stream

### 負載平衡

**自動負載平衡**:

```
Job 1 → Worker 1 (忙碌 2 秒)
Job 2 → Worker 2 (忙碌 1 秒)
Job 3 → Worker 2 (Worker 1 還在忙) ← 自動分配
```

**實現方式**: `ThreadPoolExecutor` 內建佇列管理

## 結果傳遞

### Event Bus 機制

```python
# 推論完成後
result = {
    "type": "transcription",
    "session_id": session_id,
    "channel_id": channel_id,
    "text": text,
    "timestamp": job["timestamp"],
    "duration": info.duration
}

# 跨執行緒傳遞到 asyncio Event Loop
asyncio.run_coroutine_threadsafe(event_bus.put(result), main_loop)
```

**為何需要 `run_coroutine_threadsafe`？**
- InferenceEngine 在 Worker Thread
- event_bus 在 asyncio Event Loop (Main Thread)
- 需要執行緒安全的橋接

### 廣播流程

```python
async def broadcaster():
    while True:
        event = await event_bus.get()  # 從 Event Bus 取出
        await manager.broadcast(event)  # 廣播給所有 WebSocket
```

## 效能優化

### 1. 批次處理 (未來擴展)

**當前實作**: 單一音訊片段推論

**優化方案**: 動態批次

```python
# 收集多個任務
batch = []
while len(batch) < BATCH_SIZE and not queue.empty():
    batch.append(inference_queue.get())

# 批次推論
results = model.transcribe_batch([job["audio_data"] for job in batch])
```

**優勢**:
- 更高 GPU 利用率
- 降低推論延遲

**權衡**:
- 增加等待時間
- 複雜度提升

### 2. 模型量化

```python
# INT8 量化
model = WhisperModel(
    model_path,
    device="cuda",
    compute_type="int8"  # 從 float16 改為 int8
)
```

**效果**:
- VRAM 減少 50%
- 速度提升 30-50%
- 準確度下降 1-2%

### 3. VAD 過濾

**faster-whisper 內建 VAD**:

```python
segments, info = model.transcribe(
    audio_data,
    vad_filter=True,  # 啟用 VAD 過濾
    vad_parameters={
        "threshold": 0.5,
        "min_speech_duration_ms": 250
    }
)
```

**效果**: 過濾靜音部分，減少推論時間

**注意**: 我們已在 VADProcessor 做過濾，此選項可關閉

### 4. GPU 記憶體管理

```python
# 定期清理 CUDA 快取
import gc
import torch

def cleanup():
    gc.collect()
    torch.cuda.empty_cache()
```

**時機**: 客戶端斷線後

## 錯誤處理

### 推論錯誤

```python
def transcribe(self, job: dict):
    try:
        segments, info = self.model.transcribe(...)
    except Exception as e:
        logger.error(f"Inference Error [{session_id}]: {e}")
        # 不中斷服務，繼續處理下一個任務
        return
```

**常見錯誤**:
- CUDA OOM: 減少 `MAX_INFERENCE_WORKERS`
- 音訊格式錯誤: 檢查 VAD 輸出
- 模型損壞: 重新下載模型

### 佇列溢出

**當前**: 使用無界佇列（可能記憶體溢出）

**改進方案**:
```python
inference_queue = queue.Queue(maxsize=100)  # 限制大小

# VADProcessor
try:
    inference_queue.put_nowait(job)
except queue.Full:
    logger.warning("Inference queue full, dropping job")
```

## 監控與除錯

### 佇列深度監控

```python
def monitor_queue():
    while True:
        depth = inference_queue.qsize()
        logger.info(f"Queue depth: {depth}")
        time.sleep(5)

threading.Thread(target=monitor_queue, daemon=True).start()
```

### GPU 使用率監控

```bash
# 終端執行
watch -n 1 nvidia-smi
```

**關鍵指標**:
- GPU-Util: 應接近 100%
- Memory-Usage: 不應超過 90%
- Temperature: 不應超過 85°C

### 推論延遲統計

```python
def transcribe(self, job: dict):
    start_time = time.time()
    
    segments, info = self.model.transcribe(...)
    
    latency = time.time() - start_time
    audio_duration = info.duration
    rtf = latency / audio_duration
    
    logger.info(f"Latency: {latency:.2f}s, Audio: {audio_duration:.2f}s, RTF: {rtf:.2f}")
```

**目標 RTF**: < 0.5 (即處理 1 秒音訊需 < 0.5 秒)

## 多 GPU 支援 (進階)

### 方案一: 多模型實例

```python
# 載入多個模型到不同 GPU
models = [
    WhisperModel(model_path, device="cuda:0"),
    WhisperModel(model_path, device="cuda:1")
]

# Worker 輪流使用
def transcribe(self, job: dict):
    gpu_id = threading.get_ident() % len(models)
    model = models[gpu_id]
    segments, info = model.transcribe(...)
```

### 方案二: Data Parallel

```python
# 使用 torch.nn.DataParallel (需修改 faster-whisper)
# 目前 faster-whisper 不直接支援，需包裝
```

## 最佳實踐

1. **模型選擇**: 根據硬體選擇適當大小
2. **Worker 數量**: 根據 VRAM 調整
3. **離線模型**: 使用本地模型避免網路延遲
4. **監控佇列**: 避免任務堆積
5. **錯誤處理**: 不因單一錯誤中斷服務

## 總結

GPU 推論管線透過精心設計的多層架構，實現了：

- ✅ 高吞吐量 (並行處理)
- ✅ 低延遲 (快速推論)
- ✅ 穩定性 (錯誤隔離)
- ✅ 可擴展 (多 GPU 支援)

理解推論管線是優化系統效能的核心。
