# RealtimeSTT 離線語音轉錄伺服器

這是一個基於 `RealtimeSTT` 與 `faster-whisper` 的即時語音轉錄伺服器，專為離線環境與高併發場景設計。它支援多個客戶端同時連線（如 SIP 通話轉錄），並提供即時的語音活動偵測 (VAD) 與句子級別的轉錄廣播。

## 功能特色

- **完全離線運行**: 模型與依賴皆本地化，無需網路連接。
- **高併發支援**: 採用 WebSocket + Threading 架構，取代原生 Multiprocessing，適合 Windows/Linux 伺服器環境。
- **即時廣播**: 支援 Room (Session) 概念，同一 Session 下的所有客戶端皆可接收轉錄結果。
- **VAD 優化**: 內建 Silero VAD，並針對連續語音進行了狀態機優化。

## 環境需求

- Windows / Linux
- Python 3.10+
- CUDA 11.x / 12.x (建議使用 GPU 加速)

### 安裝依賴

```bash
pip install -r requirements.txt
```

*注意：需確保 `models/` 目錄下已包含必要的 Whisper 模型與 VAD 模型檔案。*

---

## 伺服器端 (Server)

啟動伺服器，預設監聽 `0.0.0.0:8000`。

### 啟動指令

```bash
python general_stt_server.py
```

### API 端點

1.  **音訊串流與轉錄 (Audio Stream)**
    -   URL: `ws://<server_ip>:8000/v1/audio/stream`
    -   Query Params:
        -   `session_id`: 會議室/Session ID (必填)
        -   `channel_id`: 使用者/聲道 ID (必填)
        -   `receive_text`: 是否接收轉錄結果 (預設: `True`)
    -   功能: 接收 PCM 16k 16bit 音訊，並回傳 JSON 轉錄結果。

2.  **事件訂閱 (Event Subscription)**
    -   URL: `ws://<server_ip>:8000/v1/events/sub`
    -   Query Params:
        -   `session_id`: 會議室/Session ID (必填)
    -   功能: 僅接收該 Session 的轉錄廣播，不傳送音訊 (適用於監聽端或 SIP Server 控制端)。

---

## 客戶端 (Client)

提供一個測試用的 Client 腳本 `general_stt_client.py`，可用於模擬麥克風輸入或傳送音檔。

### 使用指令

```bash
python general_stt_client.py [options]
```

### 參數說明

| 參數 | 預設值 | 說明 |
| :--- | :--- | :--- |
| `--mode` | `mic` | 模式選擇: `mic` (麥克風) 或 `file` (檔案) |
| `--path` | None | `.wav` 檔案路徑 (當 mode=file 時必填) |
| `--session` | `test_room` | Session ID (同一 ID 可互通) |
| `--user` | `User_A` | 使用者 ID |

### 使用範例

**1. 使用麥克風即時轉錄**

```bash
python general_stt_client.py --mode mic --user MyUser --session Room101
```

**2. 傳送 WAV 檔案進行測試**

```bash
python general_stt_client.py --mode file --path ./test_audio.wav --user FileBot
```

*注意：WAV 檔案需為 16kHz, 16-bit Mono 格式，否則可能會變快或變慢 (Server 端雖有基礎重採樣，但建議來源端先處理好)。*

---

## 離線環境配置

本專案已針對離線環境做以下處理，請勿更動 `general_stt_server.py` 中的相關設定：

1.  **Monkey Patching**: 強制 `torch.hub.load` 讀取本地 `models/hub/snakers4_silero-vad_master`，避免連網。
2.  **Model Path**: Whisper 模型路徑鎖定為本地 `models/` 目錄。
3.  **VAD參數**: 已禁用 `enable_realtime_transcription` 以節省資源，僅輸出完整句子。
