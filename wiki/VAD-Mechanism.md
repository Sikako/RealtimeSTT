# VAD 機制詳解

## 概述

VAD (Voice Activity Detection，語音活動偵測) 是 general_stt_server 的核心組件之一，負責從連續音訊流中識別語音區段，實現自動斷句。

## Silero VAD 簡介

### 什麼是 Silero VAD？

Silero VAD 是一個基於深度學習的語音活動偵測模型，具有以下特點：

- **高準確度**: 使用 RNN 架構，準確識別語音與非語音
- **低延遲**: 輕量級模型，即時處理
- **多語言支援**: 不受語言限制
- **ONNX 加速**: 支援 ONNX Runtime，CPU 友善

### 模型結構

```
Input Audio (16kHz) → Feature Extraction → RNN → Sigmoid → Probability (0-1)
                                                                    ↓
                                                        > threshold → Voice
                                                        < threshold → Silence
```

## VADProcessor 實作

### 類別定義

```python
class VADProcessor(AudioToTextRecorder):
    """
    僅負責 VAD (語音活動偵測) 與斷句的處理器。
    繼承自 RealtimeSTT.AudioToTextRecorder 但剝離推論邏輯。
    """
    def __init__(self, session_id: str, channel_id: str, **kwargs):
        # 初始化 RealtimeSTT，但禁用推論
        super().__init__(
            enable_realtime_transcription=False,
            use_microphone=False,
            ...
        )
```

### 繼承與修改

**繼承自**: `RealtimeSTT.AudioToTextRecorder`

**保留功能**:
- VAD 偵測
- 音訊緩衝
- 自動斷句

**移除功能**:
- 即時轉錄
- 內部推論 Worker
- 麥克風輸入

**修改方式**: Monkey Patching

```python
# 替換內部 Worker
AudioToTextRecorder._transcription_worker = dummy_worker

# 覆寫 shutdown 方法以支援 Threading
def shutdown(self):
    # 等待 Thread 而非 Process
    self.recording_thread.join(timeout=1)
```

## VAD 狀態機

### 狀態定義

```
┌──────────┐
│ inactive │ ← 初始狀態 / 處理完成
└─────┬────┘
      │ feed_audio()
      ▼
┌──────────┐
│listening │ ← 監聽中，等待語音
└─────┬────┘
      │ VAD 偵測到語音
      ▼
┌──────────┐
│recording │ ← 錄音中
└─────┬────┘
      │ VAD 偵測到靜音 (持續 > post_speech_silence_duration)
      ▼
┌──────────┐
│processing│ ← 打包音訊，送入推論佇列
└─────┬────┘
      │ 完成
      ▼
┌──────────┐
│ inactive │
└──────────┘
```

### 狀態轉換觸發

| 事件 | 當前狀態 | 下一狀態 | 動作 |
|------|---------|---------|------|
| VAD 偵測到語音 | listening | recording | 觸發 `on_vad_start()` |
| VAD 偵測到靜音 | recording | processing | 觸發 `on_recording_stop()` |
| 推論任務建立 | processing | inactive | 重置 VAD |

## 關鍵參數

### silero_sensitivity

**定義**: VAD 觸發的靈敏度閾值

**範圍**: 0.0 - 1.0

**效果**:
- **低值 (0.1-0.3)**: 更靈敏，容易觸發，適合安靜環境
- **中值 (0.4-0.6)**: 平衡，適合一般環境（預設）
- **高值 (0.7-0.9)**: 不靈敏，僅強烈語音觸發，適合嘈雜環境

**範例**:
```python
VADProcessor(
    silero_sensitivity=0.4  # 預設值
)
```

**調整建議**:
```python
# 安靜辦公室
silero_sensitivity=0.3

# 會議室（多人）
silero_sensitivity=0.4

# 嘈雜環境（街頭、工廠）
silero_sensitivity=0.6
```

### min_length_of_recording

**定義**: 最小錄音長度（秒）

**範圍**: 0.1 - 5.0

**效果**:
- 過濾掉過短的語音片段（如咳嗽、口語癖）
- 避免無意義的推論請求

**範例**:
```python
VADProcessor(
    min_length_of_recording=0.5  # 預設值
)
```

**調整建議**:
```python
# 快速對話（客服）
min_length_of_recording=0.3

# 正式演講
min_length_of_recording=0.5

# 過濾雜音
min_length_of_recording=1.0
```

### post_speech_silence_duration

**定義**: 語音結束後需要多少秒的靜音才觸發斷句

**範圍**: 0.1 - 3.0

**效果**:
- **短 (0.3-0.5s)**: 快速斷句，適合短句對話
- **中 (0.6-1.0s)**: 平衡，適合一般場景（預設）
- **長 (1.5-3.0s)**: 緩慢斷句，適合長句演講

**範例**:
```python
VADProcessor(
    post_speech_silence_duration=0.6  # 預設值
)
```

**調整建議**:
```python
# 快節奏對話
post_speech_silence_duration=0.4

# 演講、報告
post_speech_silence_duration=1.0

# 思考時間較長的場景
post_speech_silence_duration=2.0
```

## 回調函式

### on_vad_start

```python
def on_vad_start():
    logger.info("VAD: Speech Detected (Start)")
```

**觸發時機**: VAD 偵測到語音開始

**用途**: 
- 日誌記錄
- 前端狀態更新（如顯示「正在聆聽」）

### on_recording_start

```python
def _handle_recording_start(self):
    logger.info("Recording Started")
    self.stop_recording_on_voice_deactivity = True
```

**觸發時機**: 開始錄音（語音持續足夠長）

**用途**:
- 啟用自動停止機制
- 重置緩衝區

### on_recording_stop

```python
def _handle_recording_stop(self):
    logger.info(f"Recording Stopped, processing {len(self.frames)} frames...")
    
    if self.frames:
        audio_bytes = b"".join(self.frames)
        self.perform_final_transcription(audio_bytes)
    
    # 重置旗標以允許下一句偵測
    self.start_recording_on_voice_activity = True
```

**觸發時機**: 偵測到靜音並停止錄音

**用途**:
- 打包音訊資料
- 送入推論佇列
- 重置狀態機

### perform_final_transcription

```python
def perform_final_transcription(self, audio_bytes=None, use_prompt=True) -> str:
    # 轉換 int16 -> float32
    audio_data = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    job = {
        "session_id": self.session_id,
        "channel_id": self.channel_id,
        "audio_data": audio_data,
        "timestamp": time.time(),
        "language": self.language or "zh"
    }
    
    inference_queue.put(job)
```

**功能**:
- 音訊格式轉換
- 建立推論任務
- 放入全域佇列

## 音訊處理流程

### 1. 音訊輸入

```python
# WebSocket 接收
data = await websocket.receive_bytes()

# 餵給 VAD
vad_processor.feed_audio(data)
```

**格式**: PCM 16-bit, 16kHz, Mono

### 2. VAD 分析

```python
# RealtimeSTT 內部處理
def feed_audio(self, audio_chunk: bytes):
    # 1. 寫入緩衝區
    self.frames.append(audio_chunk)
    
    # 2. VAD 分析
    speech_prob = silero_vad.detect(audio_chunk)
    
    # 3. 狀態更新
    if speech_prob > self.silero_sensitivity:
        self._set_state("recording")
    else:
        self._check_silence_duration()
```

### 3. 緩衝區管理

```python
# 音訊片段儲存
self.frames = []  # List of bytes

# 錄音時追加
self.frames.append(audio_chunk)

# 停止錄音時組合
audio_bytes = b"".join(self.frames)
```

### 4. 格式轉換

```python
# int16 → float32 (faster-whisper 需要)
audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
audio_float32 = audio_int16.astype(np.float32) / 32768.0
```

**為何需要轉換？**
- RealtimeSTT 內部使用 int16 (節省記憶體)
- faster-whisper 需要 float32 (模型輸入格式)

## 離線 VAD 配置

### Monkey Patch: 強制本地載入

```python
def offline_torch_hub_load(repo_or_dir, model, *args, **kwargs):
    if "silero-vad" in repo_or_dir:
        local_repo_path = os.path.join(MODELS_DIR, "hub", "snakers4_silero-vad_master")
        
        if os.path.exists(local_repo_path):
            kwargs["source"] = "local"
            return _original_torch_hub_load(local_repo_path, model, *args, **kwargs)
    
    return _original_torch_hub_load(repo_or_dir, model, *args, **kwargs)

torch.hub.load = offline_torch_hub_load
```

**目的**:
- 攔截 `torch.hub.load` 呼叫
- 強制使用本地模型
- 避免連網檢查

### 模型目錄結構

```
models/hub/snakers4_silero-vad_master/
├── hubconf.py
├── silero_vad.onnx
├── silero_vad.jit
└── utils_vad.py
```

### ONNX vs JIT

**ONNX 模式** (建議):
```python
VADProcessor(
    silero_use_onnx=True
)
```
- **優點**: CPU 推論更快
- **缺點**: 需額外安裝 `onnxruntime`

**JIT 模式**:
```python
VADProcessor(
    silero_use_onnx=False
)
```
- **優點**: 僅需 PyTorch
- **缺點**: CPU 推論較慢

## 效能優化

### 1. 減少 VAD 計算頻率

```python
# RealtimeSTT 內部實作
# 每 N 個 chunk 才做一次 VAD
vad_check_interval = 3  # 每 3 個 chunk 檢查一次
```

### 2. 音訊重採樣優化

```python
# 使用 scipy (NumPy 加速)
if config.sample_rate != 16000:
    audio_np = np.frombuffer(data, dtype=np.int16)
    num_samples = int(len(audio_np) * 16000 / config.sample_rate)
    resampled = scipy.signal.resample(audio_np, num_samples).astype(np.int16)
    data = resampled.tobytes()
```

**建議**: 客戶端直接傳送 16kHz 音訊，避免伺服器端重採樣

### 3. 緩衝區大小

```python
CHUNK_SIZE = 1024  # 建議值
# 計算延遲: 1024 / 16000 = 64ms
```

**權衡**:
- **小 chunk (512)**: 低延遲，但增加網路與 CPU 開銷
- **大 chunk (2048)**: 減少開銷，但增加延遲

## 常見問題

### Q1: VAD 過於靈敏，不斷觸發

**原因**:
- `silero_sensitivity` 過低
- 環境噪音過大

**解決**:
```python
# 提高靈敏度閾值
silero_sensitivity=0.6

# 增加最小錄音長度
min_length_of_recording=1.0
```

### Q2: VAD 無法觸發

**原因**:
- `silero_sensitivity` 過高
- 音訊音量過小

**解決**:
```python
# 降低靈敏度閾值
silero_sensitivity=0.2

# 檢查音訊音量
audio_rms = np.sqrt(np.mean(audio_data ** 2))
logger.info(f"Audio RMS: {audio_rms}")
```

### Q3: 斷句過快或過慢

**原因**:
- `post_speech_silence_duration` 設定不當

**解決**:
```python
# 快速斷句
post_speech_silence_duration=0.3

# 緩慢斷句
post_speech_silence_duration=1.5
```

### Q4: 離線環境無法載入 VAD 模型

**原因**:
- 模型路徑錯誤
- 未安裝 ONNX Runtime

**解決**:
```bash
# 確認模型存在
ls models/hub/snakers4_silero-vad_master/

# 安裝 ONNX Runtime
pip install onnxruntime
```

## 除錯技巧

### 啟用 VAD 日誌

```python
VADProcessor(
    on_vad_detect_start=lambda: logger.info("VAD: Listening..."),
    on_vad_start=lambda: logger.info("VAD: Speech Start"),
    on_vad_stop=lambda: logger.info("VAD: Speech Stop"),
    level=logging.DEBUG
)
```

### 視覺化 VAD 機率

```python
def visualize_vad(self, prob):
    bar = "█" * int(prob * 50)
    logger.info(f"VAD Prob: {prob:.2f} {bar}")
```

### 音訊儲存（除錯用）

```python
def _handle_recording_stop(self):
    # 儲存音訊片段
    audio_bytes = b"".join(self.frames)
    with open(f"/tmp/audio_{time.time()}.raw", "wb") as f:
        f.write(audio_bytes)
    
    # 繼續正常流程
    self.perform_final_transcription(audio_bytes)
```

## 最佳實踐

1. **環境評估**: 根據實際環境調整 `silero_sensitivity`
2. **場景適配**: 根據對話節奏調整 `post_speech_silence_duration`
3. **離線優先**: 使用本地模型避免網路依賴
4. **ONNX 加速**: 在 CPU 環境下啟用 ONNX
5. **日誌監控**: 啟用 VAD 回調以監控系統狀態

## 總結

VAD 是 general_stt_server 的核心組件，透過精心設計的狀態機與參數配置，實現了：

- ✅ 即時語音偵測
- ✅ 自動斷句
- ✅ 低延遲處理
- ✅ 離線運行
- ✅ 高度可配置

理解 VAD 機制是優化系統效能的關鍵。
