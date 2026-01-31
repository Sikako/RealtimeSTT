# RealtimeSTT 離線語音轉錄伺服器

這是一個基於 `RealtimeSTT` 與 `faster-whisper` 的即時語音轉錄伺服器，專為離線環境與高併發場景設計。它支援多個客戶端同時連線（如 SIP 通話轉錄），並提供即時的語音活動偵測 (VAD) 與句子級別的轉錄廣播。

## 目錄

- [功能特色](#功能特色)
- [系統架構](#系統架構)
- [環境需求](#環境需求)
- [安裝說明](#安裝說明)
- [general_stt_server 功能與用法](#general_stt_server-功能與用法)
  - [伺服器端](#伺服器端-server)
  - [API 端點](#api-端點)
  - [客戶端](#客戶端-client)
- [離線環境配置](#離線環境配置)
- [性能優化](#性能優化)
- [故障排除](#故障排除)
- [技術文檔](#技術文檔)

## 功能特色

- **完全離線運行**: 模型與依賴皆本地化，無需網路連接
- **高併發支援**: 採用 WebSocket + Threading 架構，取代原生 Multiprocessing，適合 Windows/Linux 伺服器環境
- **即時廣播**: 支援 Room (Session) 概念，同一 Session 下的所有客戶端皆可接收轉錄結果
- **VAD 優化**: 內建 Silero VAD，並針對連續語音進行了狀態機優化
- **GPU 加速**: 使用 faster-whisper 配合 CUDA 進行高速推論
- **多語言支援**: 支援中文、英文等多種語言
- **靈活部署**: 支援單機或分散式部署

## 系統架構

general_stt_server 採用三層架構設計：

```
┌─────────────────────────────────────────────────────────┐
│                    WebSocket 客戶端                      │
│          (麥克風輸入 / 檔案播放 / SIP 通話)              │
└────────────────┬────────────────────────────────────────┘
                 │ PCM 音訊流
                 ▼
┌─────────────────────────────────────────────────────────┐
│              VAD 處理層 (Voice Activity Detection)       │
│  • 語音活動偵測 (Silero VAD)                            │
│  • 自動斷句                                              │
│  • 音訊預處理                                            │
└────────────────┬────────────────────────────────────────┘
                 │ 音訊片段
                 ▼
┌─────────────────────────────────────────────────────────┐
│               GPU 推論引擎 (Whisper Model)               │
│  • 並行推論 (ThreadPoolExecutor)                        │
│  • 佇列管理                                              │
│  • 批次處理                                              │
└────────────────┬────────────────────────────────────────┘
                 │ 轉錄結果
                 ▼
┌─────────────────────────────────────────────────────────┐
│              廣播系統 (Event Bus + Manager)              │
│  • Session 管理                                          │
│  • 多客戶端廣播                                          │
│  • 連線狀態追蹤                                          │
└─────────────────────────────────────────────────────────┘
```

## 環境需求

### 硬體需求
- **CPU**: 4 核心以上 (建議 8 核心)
- **記憶體**: 8GB 以上 (建議 16GB)
- **GPU**: NVIDIA GPU with 4GB+ VRAM (建議 8GB+ 以支援 large 模型)
- **儲存空間**: 至少 10GB (用於模型存儲)

### 軟體需求
- **作業系統**: Windows 10/11 或 Linux (Ubuntu 20.04+)
- **Python**: 3.10 或以上
- **CUDA**: 11.x / 12.x (建議使用 GPU 加速)
- **cuDNN**: 對應 CUDA 版本

## 安裝說明

### 1. 安裝 Python 依賴

```bash
pip install -r requirements.txt
```

主要依賴包括：
- `fastapi` - Web 框架
- `uvicorn` - ASGI 伺服器
- `websockets` - WebSocket 支援
- `RealtimeSTT` - VAD 核心
- `faster-whisper` - Whisper 推論引擎
- `torch` - PyTorch 深度學習框架
- `numpy`, `scipy` - 數值計算

### 2. 下載與配置離線模型

#### Whisper 模型
在 `models/` 目錄下放置 faster-whisper 格式的模型：

```bash
models/
├── faster-whisper-tiny/
├── faster-whisper-small/
├── faster-whisper-medium/
└── faster-whisper-large-v2/
```

模型下載方式：
```python
from faster_whisper import WhisperModel

# 下載並轉換模型
model = WhisperModel("medium", device="cpu", compute_type="int8")
# 模型會自動下載到 ~/.cache/huggingface/hub/
```

將下載的模型複製到專案的 `models/` 目錄。

#### Silero VAD 模型
```bash
models/hub/snakers4_silero-vad_master/
└── silero_vad.onnx
```

模型會在首次運行時自動下載，或從 [Silero VAD GitHub](https://github.com/snakers4/silero-vad) 手動下載。

### 3. 驗證安裝

```bash
python -c "import RealtimeSTT; import faster_whisper; print('安裝成功')"
```

---

## general_stt_server 功能與用法

### 伺服器端 (Server)

#### 啟動伺服器

```bash
python general_stt_server.py
```

伺服器啟動後會：
1. 載入 Whisper 模型到 GPU
2. 初始化 VAD 引擎
3. 啟動推論工作執行緒池
4. 監聽 WebSocket 連線 (預設 `0.0.0.0:8000`)

#### 啟動日誌範例
```
2024-01-31 [INFO] STT-Service: Found local model: medium at /path/to/models/faster-whisper-medium
2024-01-31 [INFO] STT-Service: Loading Whisper Model from /path/to/models/faster-whisper-medium ...
2024-01-31 [INFO] STT-Service: Model Loaded Successfully.
2024-01-31 [INFO] STT-Service: Worker Dispatcher Started.
2024-01-31 [INFO] STT-Service: System Startup Correctly.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

#### 配置選項

在 `general_stt_server.py` 中可調整的主要參數：

```python
# GPU 推論並行數量 (根據顯卡 VRAM 調整)
MAX_INFERENCE_WORKERS = 2

# VAD 靈敏度 (0.0-1.0, 越低越靈敏)
silero_sensitivity = 0.4

# 最小錄音長度 (秒)
min_length_of_recording = 0.5

# 語音結束後的靜音時長 (秒)
post_speech_silence_duration = 0.6
```

### API 端點

#### 1. 音訊串流與轉錄端點

**端點**: `ws://<server_ip>:8000/v1/audio/stream`

**Query 參數**:
- `session_id` (必填): 會議室/Session ID，用於區分不同的轉錄任務
- `channel_id` (必填): 使用者/聲道 ID，用於標識音訊來源
- `receive_text` (選填): 是否接收轉錄結果，預設 `true`

**功能**:
- 接收原始 PCM 音訊流 (16kHz, 16-bit, mono)
- 執行即時 VAD 與斷句
- (可選) 接收該 Session 的轉錄結果廣播

**連線流程**:

1. **建立 WebSocket 連線**
```javascript
const ws = new WebSocket('ws://localhost:8000/v1/audio/stream?session_id=room1&channel_id=user1');
```

2. **發送配置 (選填)**
```json
{
  "sample_rate": 16000,
  "encoding": "pcm_16",
  "language": "zh"
}
```

3. **發送音訊流**
```python
# 以 Python 為例
while True:
    audio_chunk = get_audio_data()  # 取得 PCM bytes
    await websocket.send(audio_chunk)
```

4. **接收轉錄結果**
```json
{
  "type": "transcription",
  "session_id": "room1",
  "channel_id": "user1",
  "text": "這是轉錄的文字內容",
  "timestamp": 1706659200.123,
  "duration": 2.5
}
```

**使用情境**:
- 會議記錄：多人同時說話，每人一個 `channel_id`
- SIP 通話轉錄：電話兩端各自建立連線
- 語音助手：單一使用者即時語音輸入

#### 2. 事件訂閱端點

**端點**: `ws://<server_ip>:8000/v1/events/sub`

**Query 參數**:
- `session_id` (必填): 要訂閱的 Session ID

**功能**:
- 僅訂閱特定 Session 的轉錄結果
- 不發送音訊資料
- 適用於監聽端或控制端

**連線範例**:
```python
import asyncio
import websockets
import json

async def subscribe_session(session_id):
    uri = f"ws://localhost:8000/v1/events/sub?session_id={session_id}"
    async with websockets.connect(uri) as websocket:
        async for message in websocket:
            data = json.loads(message)
            print(f"[{data['channel_id']}]: {data['text']}")

asyncio.run(subscribe_session("room1"))
```

**使用情境**:
- 會議監控面板：顯示所有參與者的發言
- SIP 伺服器控制端：記錄通話內容
- 即時字幕顯示

### 客戶端 (Client)

提供測試用的 Python 客戶端 `general_stt_client.py`。

#### 基本用法

```bash
python general_stt_client.py [options]
```

#### 參數說明

| 參數 | 預設值 | 說明 |
| :--- | :--- | :--- |
| `--mode` | `mic` | 音訊來源模式: `mic` (麥克風) 或 `file` (檔案) |
| `--path` | None | WAV 檔案路徑 (當 `mode=file` 時必填) |
| `--session` | `test_room` | Session ID，同一 Session 內的客戶端可互相接收轉錄結果 |
| `--user` | `User_A` | 使用者 ID，用於識別音訊來源 |

#### 使用範例

**範例 1: 使用麥克風即時轉錄**

```bash
python general_stt_client.py --mode mic --user Alice --session Meeting001
```

輸出範例：
```
--- Available Audio Devices ---
Input Device id 0 - 內建麥克風
Input Device id 1 - USB 麥克風
-------------------------------
[*] Recording from microphone... (Ctrl+C to stop)
[*] Connecting to ws://localhost:8000/v1/audio/stream?session_id=Meeting001&channel_id=Alice ...
[*] Connected.
[*] Config sent.

[Session Broadcast] Alice: 大家好，今天的會議開始
[Session Broadcast] Bob: 我們來討論一下專案進度
```

**範例 2: 播放 WAV 檔案**

```bash
python general_stt_client.py --mode file --path ./test_audio.wav --user FileBot --session Test
```

輸出範例：
```
[*] Reading from file: ./test_audio.wav
[*] Connecting to ws://localhost:8000/v1/audio/stream?session_id=Test&channel_id=FileBot ...
[*] Connected.
[*] Config sent.

[Session Broadcast] FileBot: 這是測試音訊檔案的內容
[*] File playback finished.
[*] Audio sending finished. Keeping connection open for results... (Ctrl+C to exit)
```

**範例 3: 多客戶端模擬會議**

開啟三個終端，分別執行：

```bash
# 終端 1
python general_stt_client.py --mode mic --user Alice --session Meeting

# 終端 2  
python general_stt_client.py --mode mic --user Bob --session Meeting

# 終端 3 (純監聽)
python -c "
import asyncio
import websockets
import json

async def monitor():
    async with websockets.connect('ws://localhost:8000/v1/events/sub?session_id=Meeting') as ws:
        async for msg in ws:
            data = json.loads(msg)
            print(f'[{data[\"channel_id\"]}]: {data[\"text\"]}')

asyncio.run(monitor())
"
```

#### 音訊格式要求

客戶端發送的音訊必須符合以下規格：
- **取樣率**: 16kHz (可在 Config 中設定其他值，Server 會自動重採樣)
- **位元深度**: 16-bit
- **聲道數**: 單聲道 (Mono)
- **編碼**: PCM (未壓縮)

**音訊格式轉換**:

如果您的音訊檔案不符合規格，可使用 `ffmpeg` 轉換：

```bash
ffmpeg -i input.mp3 -ar 16000 -ac 1 -sample_fmt s16 output.wav
```

---

## 離線環境配置

本專案已針對離線環境做特殊處理，確保在無網路環境下可正常運作。

### Monkey Patching 機制

#### 1. Silero VAD 離線載入

```python
# 覆寫 torch.hub.load，強制使用本地模型
def offline_torch_hub_load(repo_or_dir, model, *args, **kwargs):
    if "silero-vad" in repo_or_dir:
        local_repo_path = os.path.join(MODELS_DIR, "hub", "snakers4_silero-vad_master")
        if os.path.exists(local_repo_path):
            kwargs["source"] = "local"
            return _original_torch_hub_load(local_repo_path, model, *args, **kwargs)
    return _original_torch_hub_load(repo_or_dir, model, *args, **kwargs)

torch.hub.load = offline_torch_hub_load
```

#### 2. 強制使用 Threading 模式

```python
# 覆寫 RealtimeSTT 的 _start_thread 方法
def start_thread_patch(self, target=None, args=()):
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()
    return thread

AudioToTextRecorder._start_thread = start_thread_patch
```

這樣做的原因：
- 避免 Windows 上 Multiprocessing 的限制
- 提升高併發場景下的效能
- 簡化資源管理與清理流程

### 環境變數設定

```python
# 設置離線模式
os.environ["TORCH_HOME"] = MODELS_DIR
os.environ["HF_HUB_OFFLINE"] = "1"
```

### 模型自動偵測

伺服器啟動時會自動尋找可用的 Whisper 模型（優先順序：medium > large-v2 > small > tiny）：

```python
def find_available_model():
    priorities = ["medium", "large-v2", "small", "tiny"]
    for size in priorities:
        for d in os.listdir(MODELS_DIR):
            if f"faster-whisper-{size}" in d:
                return os.path.join(MODELS_DIR, d)
    return "tiny"  # 後備方案
```

---

## 性能優化

### GPU 記憶體優化

1. **調整並行推論數量**
   ```python
   # 根據 GPU VRAM 調整
   MAX_INFERENCE_WORKERS = 2  # 4GB VRAM
   # MAX_INFERENCE_WORKERS = 4  # 8GB VRAM
   # MAX_INFERENCE_WORKERS = 8  # 16GB+ VRAM
   ```

2. **選擇適當的模型大小**
   ```
   tiny    - 1GB VRAM, 快速但準確度較低
   small   - 2GB VRAM, 平衡
   medium  - 5GB VRAM, 高準確度 (建議)
   large-v2 - 10GB VRAM, 最高準確度
   ```

3. **使用 FP16 加速**
   ```python
   self.model = WhisperModel(
       WHISPER_MODEL_PATH, 
       device="cuda", 
       compute_type="float16",  # 使用 FP16
       local_files_only=True
   )
   ```

### VAD 參數調整

```python
VADProcessor(
    silero_sensitivity=0.4,           # 降低以減少誤觸發
    min_length_of_recording=0.5,      # 最小錄音長度
    post_speech_silence_duration=0.6, # 靜音判定時長
)
```

### 網路優化

1. **音訊區塊大小**: 建議 1024 samples (64ms @ 16kHz)
2. **WebSocket 緩衝**: 適當調整 `uvicorn` 的 `--ws-max-size` 參數
3. **並行連線數**: 使用 Nginx/HAProxy 做負載平衡

---

## 故障排除

### 常見問題

#### 1. 模型載入失敗

**問題**: `FileNotFoundError: Model not found`

**解決方案**:
- 確認 `models/` 目錄下有正確的模型檔案
- 檢查目錄權限
- 查看日誌中的模型路徑是否正確

#### 2. CUDA 記憶體不足

**問題**: `CUDA out of memory`

**解決方案**:
- 減少 `MAX_INFERENCE_WORKERS`
- 使用較小的模型 (如 `small` 或 `tiny`)
- 使用 `compute_type="int8"` 降低精度

#### 3. VAD 過於靈敏或遲鈍

**問題**: 不斷觸發 / 無法觸發

**解決方案**:
```python
# 調整靈敏度
silero_sensitivity=0.3  # 更靈敏
silero_sensitivity=0.6  # 更遲鈍

# 調整靜音時長
post_speech_silence_duration=0.3  # 更快斷句
post_speech_silence_duration=1.0  # 更慢斷句
```

#### 4. WebSocket 連線中斷

**問題**: 連線頻繁斷開

**解決方案**:
- 增加心跳包 (ping/pong)
- 檢查防火牆設定
- 使用 `wss://` (WebSocket over TLS) 提升穩定性

#### 5. 轉錄結果為空

**問題**: 收到音訊但無轉錄輸出

**解決方案**:
- 檢查音訊格式是否正確 (16kHz, 16-bit, mono)
- 確認 VAD 有正確觸發 (查看日誌)
- 檢查音訊音量是否過小

### 除錯技巧

**啟用詳細日誌**:
```python
logging.basicConfig(level=logging.DEBUG)
```

**監控 GPU 使用率**:
```bash
watch -n 1 nvidia-smi
```

**測試音訊流**:
```bash
# 使用 FFmpeg 生成測試音訊
ffmpeg -f lavfi -i "sine=frequency=1000:duration=5" -ar 16000 -ac 1 test.wav
python general_stt_client.py --mode file --path test.wav
```

---

## 技術文檔

更詳細的技術說明請參考 [Wiki 技術文檔](./wiki/README.md)，包含：

- [系統架構設計](./wiki/Architecture.md)
- [VAD 機制詳解](./wiki/VAD-Mechanism.md)
- [GPU 推論管線](./wiki/GPU-Inference-Pipeline.md)
- [WebSocket 廣播系統](./wiki/WebSocket-Broadcasting.md)
- [離線模型配置](./wiki/Offline-Model-Configuration.md)
- [效能調校指南](./wiki/Performance-Tuning.md)
- [API 參考手冊](./wiki/API-Reference.md)

### Wiki 遷移說明

> **注意**: 目前技術文檔位於倉庫的 `wiki/` 目錄中。如果您希望將這些內容遷移到 GitHub Wiki 頁面，請參考 [Wiki 遷移指南](./WIKI_MIGRATION_GUIDE.md)。
> 
> 快速遷移步驟：
> ```bash
> # 執行自動化遷移腳本
> ./migrate_wiki.sh
> ```
> 
> 遷移後可訪問：https://github.com/Sikako/RealtimeSTT/wiki

---

## 授權與貢獻

本專案基於 RealtimeSTT 與 faster-whisper 開發。

如有問題或建議，歡迎提交 Issue 或 Pull Request。
