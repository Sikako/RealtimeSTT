# RealtimeSTT 離線語音轉錄伺服器

這是一個基於 `RealtimeSTT` 與 `faster-whisper` 的即時語音轉錄伺服器，專為離線環境與高併發場景設計。預設優先使用 Breeze-ASR-25 的 CTranslate2/faster-whisper 版本作為繁體中文、台灣華語與中英混用 ASR 後端；若本機未安裝該模型，會回退到既有 faster-whisper 模型。它支援多個客戶端同時連線（如 SIP 通話轉錄），並提供即時的語音活動偵測 (VAD) 與句子級別的轉錄廣播。

## 目錄

- [功能特色](#功能特色)
- [系統架構](#系統架構)
- [環境需求](#環境需求)
- [安裝說明](#安裝說明)
- [general_stt_server 功能與用法](#general_stt_server-功能與用法)
- [離線環境配置](#離線環境配置)
- [性能優化](#性能優化)
- [故障排除](#故障排除)
- [技術文檔](#技術文檔)

## 功能特色

- **完全離線運行**: 模型與依賴皆本地化，無需網路連接。
- **高併發支援**: 採用 WebSocket + Threading 架構，取代原生 Multiprocessing，適合 Windows/Linux 伺服器環境。
- **即時廣播**: 支援 Room (Session) 概念，同一 Session 下的所有客戶端皆可接收轉錄結果。
- **VAD 優化**: 內建 Silero VAD，並針對連續語音進行了狀態機優化。
- **GPU 加速**: 使用 faster-whisper 配合 CUDA 進行高速推論。
- **多語言支援**: 支援中文、英文等多種語言。
- **靈活部署**: 支援單機或分散式部署。

## 系統架構

伺服器已拆成 `realtimestt_service` 套件，根目錄腳本只保留相容入口：

| 模組 | 責任 |
| :--- | :--- |
| `general_stt_server.py` | 相容啟動入口，仍可使用 `python general_stt_server.py`。 |
| `realtimestt_service.app` | FastAPI app、生命週期、WebSocket routes 與背景 worker wiring。 |
| `realtimestt_service.config` | ASR 模型選擇、裝置、compute type 與 initial prompt 設定。 |
| `realtimestt_service.inference` | faster-whisper 推論、artifact 清理、轉錄事件輸出；可用 fake model 單元測試。 |
| `realtimestt_service.vad` | RealtimeSTT VAD 封裝、threading patch、句子音訊佇列化。 |
| `realtimestt_service.connection_manager` | Session/Room WebSocket 廣播管理。 |
| `realtimestt_service.audio` | PCM16 重採樣等音訊轉換工具。 |
| `realtimestt_service.offline` | 離線環境變數與 Silero VAD 本地載入 patch。 |

相容 shim：

- `stt_model_config.py` 仍可匯入原本的設定 API，但實作已移到 `realtimestt_service.config`。
- `general_stt_server:app` 仍保留，支援 `uvicorn general_stt_server:app` 類型的部署方式。

執行流程：

```text
WebSocket 客戶端
  -> FastAPI routes
  -> VADProcessor 語音活動偵測與斷句
  -> inference queue
  -> InferenceEngine / faster-whisper
  -> Event bus
  -> Session 廣播
```

## 環境需求

### 硬體需求

- **CPU**: 4 核心以上，建議 8 核心。
- **記憶體**: 8GB 以上，建議 16GB。
- **GPU**: NVIDIA GPU with 4GB+ VRAM，建議 8GB+ 以支援 large 模型。
- **儲存空間**: 至少 10GB，用於模型存儲。

### 軟體需求

- **作業系統**: Windows 10/11 或 Linux (Ubuntu 20.04+)。
- **Python**: 3.10 或以上。
- **CUDA**: 11.x / 12.x，建議使用 GPU 加速。
- **cuDNN**: 對應 CUDA 版本。

## 安裝說明

### 1. 安裝 Python 依賴

```bash
pip install -r requirements.txt
```

主要依賴包括：

- `fastapi`: Web framework。
- `uvicorn`: ASGI server。
- `websockets`: WebSocket client support。
- `RealtimeSTT`: VAD core。
- `faster-whisper`: Whisper inference engine。
- `torch`: PyTorch runtime。
- `numpy`, `scipy`: Numeric and audio processing.

### 2. 下載與配置離線模型

#### Breeze-ASR-25 模型

預設模型目錄：

```bash
models/faster-whisper-Breeze-ASR-25/
```

可使用 Hugging Face CLI 下載 CTranslate2/faster-whisper 版本：

```powershell
huggingface-cli download SoybeanMilk/faster-whisper-Breeze-ASR-25 `
  --local-dir "A:\文件\RealtimeSTT\models\faster-whisper-Breeze-ASR-25" `
  --local-dir-use-symlinks False
```

下載後目錄至少應包含：

- `model.bin`
- `config.json`
- `tokenizer.json`
- `preprocessor_config.json`
- `vocabulary.json`

#### faster-whisper fallback 模型

若未安裝 Breeze-ASR-25，可在 `models/` 目錄放置 faster-whisper 格式模型：

```text
models/
├── faster-whisper-tiny/
├── faster-whisper-small/
├── faster-whisper-medium/
└── faster-whisper-large-v2/
```

#### Silero VAD 模型

```text
models/hub/snakers4_silero-vad_master/
└── silero_vad.onnx
```

### 3. 驗證安裝

```bash
python -c "import RealtimeSTT; import faster_whisper; print('安裝成功')"
```

## general_stt_server 功能與用法

### 伺服器端 (Server)

啟動伺服器：

```bash
python general_stt_server.py
```

伺服器啟動後會：

1. 載入 Whisper 模型到設定的裝置。
2. 初始化 VAD 引擎。
3. 啟動推論工作執行緒池。
4. 監聽 WebSocket 連線，預設 `0.0.0.0:8000`。

### API 端點

#### 1. 音訊串流與轉錄端點

**端點**: `ws://<server_ip>:8000/v1/audio/stream`

**Query 參數**:

- `session_id` (必填): 會議室/Session ID，用於區分不同的轉錄任務。
- `channel_id` (必填): 使用者/聲道 ID，用於標識音訊來源。
- `receive_text` (選填): 是否接收轉錄結果，預設 `true`。

**連線流程**:

1. 建立 WebSocket 連線。

```javascript
const ws = new WebSocket("ws://localhost:8000/v1/audio/stream?session_id=room1&channel_id=user1");
```

2. 發送配置，可選。若第一包直接傳二進位音訊，server 會使用預設配置。

```json
{
  "sample_rate": 16000,
  "encoding": "pcm_16",
  "language": "zh"
}
```

3. 發送 PCM 音訊流。

```python
while True:
    audio_chunk = get_audio_data()
    await websocket.send(audio_chunk)
```

4. 接收轉錄結果。

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

#### 2. 事件訂閱端點

**端點**: `ws://<server_ip>:8000/v1/events/sub`

**Query 參數**:

- `session_id` (必填): 要訂閱的 Session ID。

**連線範例**:

```python
import asyncio
import json
import websockets


async def subscribe_session(session_id):
    uri = f"ws://localhost:8000/v1/events/sub?session_id={session_id}"
    async with websockets.connect(uri) as websocket:
        async for message in websocket:
            data = json.loads(message)
            print(f"[{data['channel_id']}]: {data['text']}")


asyncio.run(subscribe_session("room1"))
```

### 客戶端 (Client)

提供測試用的 Python 客戶端 `general_stt_client.py`。

```bash
python general_stt_client.py [options]
```

| 參數 | 預設值 | 說明 |
| :--- | :--- | :--- |
| `--mode` | `mic` | 音訊來源模式: `mic` 或 `file`。 |
| `--path` | None | WAV 檔案路徑，當 `mode=file` 時必填。 |
| `--session` | `test_room` | Session ID，同一 Session 內的客戶端可互相接收轉錄結果。 |
| `--user` | `User_A` | 使用者 ID，用於識別音訊來源。 |

範例：

```bash
python general_stt_client.py --mode mic --user Alice --session Meeting001
python general_stt_client.py --mode file --path ./test_audio.wav --user FileBot --session Test
```

音訊格式建議：

- **取樣率**: 16kHz。若在 config 中設定其他值，server 會自動重採樣。
- **位元深度**: 16-bit。
- **聲道數**: Mono。
- **編碼**: PCM。

若音訊檔案不符合規格，可使用 `ffmpeg` 轉換：

```bash
ffmpeg -i input.mp3 -ar 16000 -ac 1 -sample_fmt s16 output.wav
```

## 離線環境配置

本專案已針對離線環境做特殊處理，相關設定位於 `realtimestt_service.offline` 與 `realtimestt_service.config`。

### 環境變數

| 變數 | 預設值 | 說明 |
| :--- | :--- | :--- |
| `STT_MODEL_PROFILE` | `breeze-asr-25` | 模型選擇 profile。預設優先尋找 Breeze-ASR-25。 |
| `STT_MODEL_PATH` | None | 指定本機模型目錄；存在時優先使用。 |
| `STT_DEVICE` | `cuda` | faster-whisper 載入裝置。 |
| `STT_COMPUTE_TYPE` | `float16` | faster-whisper compute type。 |
| `STT_INITIAL_PROMPT` | `繁體中文會議記錄，台灣華語，中英混用，對話清晰。` | 轉錄 initial prompt。 |

### 離線與 threading patch

- `realtimestt_service.offline` 設定 `TORCH_HOME` 與 `HF_HUB_OFFLINE`，並將 Silero VAD 的 `torch.hub.load` 導向本地 `models/hub/snakers4_silero-vad_master`。
- `realtimestt_service.vad` 覆寫 RealtimeSTT 的 thread 啟動方式，避免 Windows 高併發場景下產生過多 process。
- VAD server 模式禁用 `enable_realtime_transcription`，只輸出完整句子。

## 性能優化

### GPU 記憶體優化

1. 調整並行推論數量。

```python
MAX_INFERENCE_WORKERS = 2
```

2. 選擇適當的模型大小。

```text
tiny      - 低 VRAM，速度快但準確度較低
small     - 平衡
medium    - 較高準確度
large-v2  - 最高準確度，VRAM 需求較高
```

3. 透過環境變數調整 compute type。

```powershell
$env:STT_COMPUTE_TYPE = "int8"
```

### VAD 參數調整

VAD 參數集中在 `realtimestt_service.vad.VADProcessor` 的初始化設定：

```python
silero_sensitivity = 0.4
min_length_of_recording = 0.5
post_speech_silence_duration = 0.6
```

### 網路優化

- 音訊區塊大小建議 1024 samples，約 64ms @ 16kHz。
- 大量連線時可用 Nginx/HAProxy 做負載平衡。
- 視需求調整 `uvicorn` 的 WebSocket buffer 參數。

## 故障排除

### 1. 模型載入失敗

確認：

- `models/` 目錄下有正確模型檔案。
- `STT_MODEL_PATH` 指向存在的本機模型目錄。
- 啟動日誌中的模型路徑是否符合預期。

### 2. CUDA 記憶體不足

可嘗試：

- 減少 `MAX_INFERENCE_WORKERS`。
- 使用較小模型，例如 `small` 或 `tiny`。
- 設定 `STT_COMPUTE_TYPE=int8`。

### 3. VAD 過於靈敏或遲鈍

可調整：

```python
silero_sensitivity = 0.3  # 更靈敏
silero_sensitivity = 0.6  # 更遲鈍
post_speech_silence_duration = 0.3  # 更快斷句
post_speech_silence_duration = 1.0  # 更慢斷句
```

### 4. WebSocket 連線中斷

確認：

- Client 端有 keep-alive / ping。
- 防火牆與反向代理設定允許 WebSocket。
- 生產環境可使用 `wss://`。

### 5. 轉錄結果為空

確認：

- 音訊格式是否正確。
- VAD 是否有觸發。
- 音訊音量是否過小。
- 模型是否成功載入。

## 技術文檔

更詳細的技術說明請參考 [Wiki 技術文檔](./wiki/README.md)，包含：

- [系統架構設計](./wiki/Architecture.md)
- [VAD 機制詳解](./wiki/VAD-Mechanism.md)
- [GPU 推論管線](./wiki/GPU-Inference-Pipeline.md)
- [WebSocket 廣播系統](./wiki/WebSocket-Broadcasting.md)
- [離線模型配置](./wiki/Offline-Model-Configuration.md)
- [效能調校指南](./wiki/Performance-Tuning.md)
- [API 參考手冊](./wiki/API-Reference.md)

## 授權與貢獻

本專案基於 RealtimeSTT 與 faster-whisper 開發。

如有問題或建議，歡迎提交 Issue 或 Pull Request。
