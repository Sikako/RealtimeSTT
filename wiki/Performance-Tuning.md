# 效能調校指南

## 概述

本文檔提供 general_stt_server 的完整效能調校策略，涵蓋 GPU、VAD、網路、並發等各方面的優化技巧。

## 效能指標

### 關鍵指標定義

#### 1. RTF (Real-Time Factor)

**定義**: 處理 1 秒音訊所需的時間

**計算**:
```
RTF = 處理時間 / 音訊時長
```

**目標**:
- RTF < 0.5: 優秀（2 倍實時）
- RTF < 1.0: 良好（實時）
- RTF > 1.0: 需優化（慢於實時）

**範例**:
```python
start = time.time()
result = model.transcribe(audio)  # audio 時長 3 秒
elapsed = time.time() - start     # 處理花費 1.2 秒

rtf = elapsed / 3.0  # 1.2 / 3.0 = 0.4 (優秀)
```

#### 2. 延遲 (Latency)

**定義**: 從語音結束到收到轉錄結果的時間

**組成**:
```
總延遲 = VAD 斷句時間 + 佇列等待時間 + 推論時間 + 廣播時間
```

**目標**:
- < 1 秒: 即時互動場景
- < 3 秒: 一般場景
- < 5 秒: 可接受

#### 3. 吞吐量 (Throughput)

**定義**: 每秒可處理的音訊秒數

**計算**:
```
吞吐量 = 並行數 / RTF
```

**範例**:
```
並行數 = 4 Workers
RTF = 0.5
吞吐量 = 4 / 0.5 = 8 (每秒處理 8 秒音訊)
```

#### 4. GPU 利用率

**定義**: GPU 計算單元的使用百分比

**查看**:
```bash
nvidia-smi
```

**目標**: 70-95%（過高可能導致過熱）

---

## GPU 優化

### 1. 選擇適當的模型大小

| 模型 | VRAM | RTF | 準確度 | 建議場景 |
|------|------|-----|--------|---------|
| tiny | 1GB | 0.05 | 85% | 快速測試、低資源環境 |
| small | 2GB | 0.15 | 92% | 平衡場景 |
| medium | 5GB | 0.30 | 95% | **生產環境（建議）** |
| large-v2 | 10GB | 0.50 | 97% | 高準確度需求 |

**決策樹**:
```
VRAM < 4GB → tiny/small
VRAM 4-8GB → small/medium
VRAM 8-16GB → medium/large
VRAM > 16GB → large + 增加並行數
```

### 2. 調整並行 Worker 數量

**公式**:
```
MAX_INFERENCE_WORKERS = floor(GPU_VRAM / MODEL_VRAM) - 1
```

**範例**:
```python
# 8GB GPU + medium 模型 (5GB)
MAX_INFERENCE_WORKERS = floor(8 / 5) - 1 = 1 - 1 = 1
# 實際可設為 2（有一定餘裕）

# 16GB GPU + medium 模型
MAX_INFERENCE_WORKERS = floor(16 / 5) - 1 = 3 - 1 = 2
# 實際可設為 4
```

**實際配置**:
```python
# general_stt_server.py

# 保守（穩定優先）
MAX_INFERENCE_WORKERS = 2

# 積極（效能優先）
MAX_INFERENCE_WORKERS = 4

# 超頻（需監控溫度）
MAX_INFERENCE_WORKERS = 6
```

### 3. 計算型別優化

**選項對比**:

```python
# FP32 (基準)
compute_type="float32"
# 速度: 1x
# VRAM: 100%
# 準確度: 100%

# FP16 (建議) ✅
compute_type="float16"
# 速度: 1.5-2x
# VRAM: 50%
# 準確度: 99.5%

# INT8 (極限)
compute_type="int8"
# 速度: 2-3x
# VRAM: 25%
# 準確度: 97-98%
```

**建議配置**:
```python
# GPU 推論
model = WhisperModel(
    model_path,
    device="cuda",
    compute_type="float16"  # ✅ 最佳平衡
)

# CPU 推論
model = WhisperModel(
    model_path,
    device="cpu",
    compute_type="int8"  # CPU 上 INT8 更快
)
```

### 4. Beam Size 調整

**效果**:

| Beam Size | 速度 | 準確度 | 建議場景 |
|-----------|------|--------|---------|
| 1 | 最快 | 90% | 快速草稿 |
| 3 | 快 | 93% | 低延遲需求 |
| 5 | 平衡 | 95% | **生產環境（預設）** |
| 10 | 慢 | 97% | 高準確度需求 |

**配置**:
```python
# 快速模式
segments, info = model.transcribe(audio, beam_size=3)

# 標準模式 ✅
segments, info = model.transcribe(audio, beam_size=5)

# 高精度模式
segments, info = model.transcribe(audio, beam_size=10)
```

### 5. GPU 記憶體管理

**定期清理**:
```python
import gc
import torch

def cleanup_gpu():
    gc.collect()
    torch.cuda.empty_cache()

# 在客戶端斷線後呼叫
vad_processor.shutdown()
cleanup_gpu()
```

**監控記憶體**:
```python
def log_gpu_memory():
    allocated = torch.cuda.memory_allocated() / 1024**3
    reserved = torch.cuda.memory_reserved() / 1024**3
    logger.info(f"GPU Memory: {allocated:.2f}GB allocated, {reserved:.2f}GB reserved")
```

---

## VAD 優化

### 1. 靈敏度調整

**根據環境調整**:

```python
# 安靜環境（辦公室、錄音室）
silero_sensitivity=0.3  # 更靈敏

# 一般環境（會議室）
silero_sensitivity=0.4  # 預設 ✅

# 嘈雜環境（街道、工廠）
silero_sensitivity=0.6  # 降低誤觸發
```

### 2. 斷句參數優化

**根據場景調整**:

```python
# 快節奏對話（客服、訪談）
post_speech_silence_duration=0.4
min_length_of_recording=0.3

# 標準場景 ✅
post_speech_silence_duration=0.6
min_length_of_recording=0.5

# 演講、報告
post_speech_silence_duration=1.0
min_length_of_recording=0.8
```

### 3. 使用 ONNX VAD

**啟用**:
```python
VADProcessor(
    silero_use_onnx=True  # ✅ CPU 上快 2-3 倍
)
```

**前提**: 安裝 `onnxruntime`
```bash
pip install onnxruntime
# 或 GPU 版本
pip install onnxruntime-gpu
```

---

## 網路優化

### 1. 音訊區塊大小

**權衡**:

| Chunk Size | 延遲 | CPU 開銷 | 網路開銷 |
|------------|------|---------|---------|
| 512 | 32ms | 高 | 高 |
| 1024 | 64ms | 中 | 中 ✅ |
| 2048 | 128ms | 低 | 低 |

**建議**:
```python
CHUNK_SIZE = 1024  # samples
# 延遲: 1024 / 16000 = 64ms (可接受)
```

### 2. WebSocket 壓縮

**啟用 permessage-deflate**:
```python
# 客戶端 (JavaScript)
const ws = new WebSocket(url, {
    perMessageDeflate: false  // 音訊資料不建議壓縮
});

# 伺服器端 (uvicorn)
uvicorn.run(
    app,
    ws_per_message_deflate=False  # 禁用壓縮以降低 CPU
)
```

**為何禁用壓縮？**
- PCM 音訊壓縮率低
- 壓縮/解壓會增加 CPU 與延遲
- 得不償失

### 3. 批次發送

**客戶端優化**:
```python
# ❌ 差：每個 sample 發送一次
for sample in audio_data:
    await ws.send(bytes([sample]))

# ✅ 好：批次發送
chunk_size = 1024
for i in range(0, len(audio_data), chunk_size):
    chunk = audio_data[i:i+chunk_size]
    await ws.send(chunk)
```

---

## 並發優化

### 1. ThreadPool 配置

**基本公式**:
```
MAX_INFERENCE_WORKERS = min(
    CPU_CORES,
    GPU_VRAM / MODEL_VRAM,
    MAX_CONCURRENT_USERS / AVG_SPEECH_RATE
)
```

**範例計算**:
```
CPU: 16 核心
GPU: 16GB VRAM
模型: medium (5GB)
並發使用者: 50
平均說話頻率: 每 10 秒說一句

Workers = min(
    16,
    16 / 5 = 3,
    50 / (1/10) = 5
) = 3

實際配置: 4 Workers (稍微超配)
```

### 2. 佇列深度限制

**避免記憶體溢出**:
```python
# 當前: 無界佇列
inference_queue = queue.Queue()

# 優化: 限制深度
inference_queue = queue.Queue(maxsize=100)

# VADProcessor 中處理滿佇列
try:
    inference_queue.put_nowait(job)
except queue.Full:
    logger.warning("Queue full, dropping job")
    # 或實作重試邏輯
```

### 3. 批次推論（進階）

**概念**: 累積多個音訊後一起推論

```python
async def batch_dispatcher():
    batch = []
    batch_timeout = 0.1  # 100ms
    
    while True:
        try:
            # 收集任務
            while len(batch) < BATCH_SIZE:
                job = await asyncio.wait_for(
                    inference_queue.get(),
                    timeout=batch_timeout
                )
                batch.append(job)
        except asyncio.TimeoutError:
            pass
        
        if batch:
            # 批次推論
            inference_executor.submit(engine.transcribe_batch, batch)
            batch = []
```

**優勢**:
- 提升 GPU 利用率
- 降低平均延遲

**劣勢**:
- 實作複雜
- 增加最大延遲

---

## 系統層級優化

### 1. Linux Kernel 參數

**增加 Socket 緩衝區**:
```bash
# /etc/sysctl.conf
net.core.rmem_max=16777216
net.core.wmem_max=16777216
net.ipv4.tcp_rmem=4096 87380 16777216
net.ipv4.tcp_wmem=4096 65536 16777216

# 套用
sudo sysctl -p
```

### 2. ulimit 調整

**增加檔案描述符限制**:
```bash
# /etc/security/limits.conf
* soft nofile 65536
* hard nofile 65536

# 或臨時設定
ulimit -n 65536
```

### 3. CPU 親和性

**綁定執行緒到特定核心**:
```python
import os
import psutil

def set_cpu_affinity():
    # 綁定到前 8 個核心
    p = psutil.Process()
    p.cpu_affinity(list(range(8)))
```

---

## 監控與分析

### 1. 效能指標收集

**實作**:
```python
class PerformanceMonitor:
    def __init__(self):
        self.metrics = {
            "transcriptions": 0,
            "total_latency": 0,
            "total_audio_duration": 0
        }
    
    def record(self, latency, audio_duration):
        self.metrics["transcriptions"] += 1
        self.metrics["total_latency"] += latency
        self.metrics["total_audio_duration"] += audio_duration
    
    def get_stats(self):
        count = self.metrics["transcriptions"]
        if count == 0:
            return {}
        
        return {
            "avg_latency": self.metrics["total_latency"] / count,
            "avg_rtf": self.metrics["total_latency"] / self.metrics["total_audio_duration"],
            "throughput": self.metrics["total_audio_duration"] / self.metrics["total_latency"]
        }

monitor = PerformanceMonitor()

def transcribe(self, job):
    start = time.time()
    segments, info = self.model.transcribe(job["audio_data"])
    latency = time.time() - start
    
    monitor.record(latency, info.duration)
```

### 2. 佇列深度監控

```python
def monitor_queue_depth():
    while True:
        depth = inference_queue.qsize()
        if depth > 50:
            logger.warning(f"Queue depth high: {depth}")
        time.sleep(5)

threading.Thread(target=monitor_queue_depth, daemon=True).start()
```

### 3. GPU 監控

**使用 pynvml**:
```python
import pynvml

pynvml.nvmlInit()
handle = pynvml.nvmlDeviceGetHandleByIndex(0)

def log_gpu_stats():
    info = pynvml.nvmlDeviceGetMemoryInfo(handle)
    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
    temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
    
    logger.info(f"GPU: {util.gpu}% | VRAM: {info.used/1024**3:.1f}GB/{info.total/1024**3:.1f}GB | Temp: {temp}°C")
```

---

## 負載測試

### 1. 單連線壓測

**模擬持續音訊輸入**:
```python
import asyncio
import websockets
import numpy as np

async def stress_test_single():
    uri = "ws://localhost:8000/v1/audio/stream?session_id=test&channel_id=user1"
    
    async with websockets.connect(uri) as ws:
        # 生成 10 分鐘的測試音訊
        duration = 600  # 秒
        sample_rate = 16000
        
        for _ in range(duration * 16):  # 每 62.5ms 一個 chunk
            chunk = np.random.randint(-100, 100, 1000, dtype=np.int16)
            await ws.send(chunk.tobytes())
            await asyncio.sleep(0.0625)
```

### 2. 多連線壓測

**模擬多客戶端**:
```python
async def stress_test_multi(num_clients=50):
    tasks = []
    for i in range(num_clients):
        task = asyncio.create_task(
            stress_test_single_client(f"user_{i}")
        )
        tasks.append(task)
    
    await asyncio.gather(*tasks)

async def stress_test_single_client(user_id):
    # 類似 stress_test_single，但使用不同 channel_id
    ...
```

### 3. 分析結果

**觀察指標**:
- GPU 利用率應 > 70%
- 佇列深度應穩定
- 記憶體無洩漏
- 延遲無明顯增加

---

## 最佳化檢查清單

### GPU 層面
- [ ] 選擇適當模型大小
- [ ] 使用 FP16 推論
- [ ] 調整 Worker 數量
- [ ] 啟用 GPU 記憶體管理

### VAD 層面
- [ ] 根據環境調整靈敏度
- [ ] 優化斷句參數
- [ ] 啟用 ONNX VAD

### 網路層面
- [ ] 優化 Chunk Size
- [ ] 禁用不必要的壓縮
- [ ] 使用批次發送

### 系統層面
- [ ] 調整 Kernel 參數
- [ ] 增加 ulimit
- [ ] 設定 CPU 親和性

### 監控層面
- [ ] 收集效能指標
- [ ] 監控佇列深度
- [ ] 監控 GPU 狀態
- [ ] 定期負載測試

---

## 總結

效能調校是系統性工程，需要：

1. **基準測試**: 先測量再優化
2. **逐步調整**: 一次改一個參數
3. **持續監控**: 觀察長期趨勢
4. **負載測試**: 模擬生產環境

透過本指南的策略，可將系統效能提升 2-5 倍。
