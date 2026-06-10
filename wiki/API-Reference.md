# API 參考手冊

## 概述

本文檔提供 general_stt_server 的完整 API 規格說明，包含健康檢查、readiness、WebSocket 端點、訊息格式、錯誤代碼等。

## HTTP 端點

### 1. 健康檢查

- **URL**: `GET http://{host}:{port}/health`
- **用途**: 確認 process 是否存活。

**回應**:
```json
{
  "status": "ok"
}
```

### 2. Readiness

- **URL**: `GET http://{host}:{port}/ready`
- **用途**: 確認模型與背景任務是否已完成啟動。

**回應**:
```json
{
  "model_loaded": true,
  "dispatcher_started": true,
  "broadcaster_started": true
}
```

## WebSocket 端點

### 1. 音訊串流端點

#### 基本資訊

- **URL**: `ws://{host}:{port}/v1/audio/stream`
- **協議**: WebSocket
- **用途**: 發送音訊並接收轉錄結果

#### Query 參數

| 參數 | 類型 | 必填 | 預設值 | 說明 |
|------|------|------|--------|------|
| `session_id` | string | ✅ | - | Session 識別碼，用於區分不同的轉錄任務，長度 `1-128` |
| `channel_id` | string | ✅ | - | 聲道識別碼，標識音訊來源（如使用者名稱），長度 `1-128` |
| `receive_text` | boolean | ❌ | `true` | 是否接收轉錄結果廣播 |

#### 連線範例

**JavaScript**:
```javascript
const ws = new WebSocket(
  'ws://localhost:8000/v1/audio/stream?session_id=room1&channel_id=user1&receive_text=true'
);

ws.onopen = () => {
  console.log('Connected');
  
  // 1. 發送配置（可選）
  ws.send(JSON.stringify({
    sample_rate: 16000,
    encoding: "pcm_16",
    language: "zh"
  }));
  
  // 2. 發送音訊
  // ws.send(audioBytes);
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(`[${data.channel_id}]: ${data.text}`);
};
```

**Python**:
```python
import asyncio
import websockets
import json

async def audio_stream():
    uri = "ws://localhost:8000/v1/audio/stream?session_id=room1&channel_id=user1"
    
    async with websockets.connect(uri) as websocket:
        # 1. 發送配置
        config = {
            "sample_rate": 16000,
            "encoding": "pcm_16",
            "language": "zh"
        }
        await websocket.send(json.dumps(config))
        
        # 2. 發送音訊
        while True:
            audio_chunk = get_audio_data()  # 取得 PCM bytes
            await websocket.send(audio_chunk)
            
        # 3. 接收轉錄
        async for message in websocket:
            data = json.loads(message)
            print(f"[{data['channel_id']}]: {data['text']}")

asyncio.run(audio_stream())
```

#### 訊息流程

##### 1. 配置訊息（可選）

**方向**: Client → Server

**格式**: JSON (Text Message)

**Schema**:
```json
{
  "sample_rate": 16000,      // int, 取樣率 (Hz)，允許 8000-48000
  "encoding": "pcm_16",      // string, 目前只支援 pcm_16
  "language": "zh"           // string, 語言代碼 (可選)
}
```

**範例**:
```json
{
  "sample_rate": 16000,
  "encoding": "pcm_16",
  "language": "zh"
}
```

**支援的語言代碼**:
- `zh`: 中文
- `en`: 英文
- `ja`: 日文
- `ko`: 韓文
- 完整列表參考: [Whisper Language Codes](https://github.com/openai/whisper/blob/main/whisper/tokenizer.py)

若設定訊息不符合 schema，server 會送出錯誤並以 `1003` 關閉連線：

```json
{
  "type": "error",
  "code": "INVALID_STREAM_CONFIG",
  "message": "..."
}
```

##### 2. 音訊資料

**方向**: Client → Server

**格式**: Binary Message

**規格**:
- **編碼**: PCM (未壓縮)
- **取樣率**: 16kHz (可在配置中設定其他值，Server 會自動重採樣)
- **位元深度**: 16-bit signed integer
- **聲道數**: Mono (單聲道)
- **位元組序**: Little Endian
- **單一 frame 大小**: 預設上限 `1048576` bytes，可用 `STT_MAX_AUDIO_FRAME_BYTES` 調整

**區塊大小建議**: 1024 samples = 2048 bytes

若單一 binary frame 超過限制，server 會送出錯誤並以 `1009` 關閉連線：

```json
{
  "type": "error",
  "code": "AUDIO_FRAME_TOO_LARGE",
  "message": "Audio frame exceeds maximum size."
}
```

**範例 (Python)**:
```python
import numpy as np

# 生成測試音訊 (1 秒的 440Hz 正弦波)
sample_rate = 16000
frequency = 440
duration = 1.0

t = np.linspace(0, duration, int(sample_rate * duration))
audio = np.sin(2 * np.pi * frequency * t)
audio_int16 = (audio * 32767).astype(np.int16)
audio_bytes = audio_int16.tobytes()

# 分塊發送
chunk_size = 1024  # samples
bytes_per_chunk = chunk_size * 2  # 16-bit = 2 bytes

for i in range(0, len(audio_bytes), bytes_per_chunk):
    chunk = audio_bytes[i:i + bytes_per_chunk]
    await websocket.send(chunk)
```

##### 3. 轉錄結果

**方向**: Server → Client

**格式**: JSON (Text Message)

**Schema**:
```json
{
  "type": "transcription",   // string, 訊息類型
  "session_id": "room1",     // string, Session ID
  "channel_id": "user1",     // string, 聲道 ID
  "text": "轉錄文字",         // string, 轉錄結果
  "timestamp": 1706659200.123, // float, Unix 時間戳記
  "duration": 2.5            // float, 音訊時長（秒）
}
```

**範例**:
```json
{
  "type": "transcription",
  "session_id": "Meeting001",
  "channel_id": "Alice",
  "text": "大家好，今天的會議開始",
  "timestamp": 1706659200.123,
  "duration": 2.5
}
```

**欄位說明**:
- `type`: 固定為 `"transcription"`
- `session_id`: 與連線時的 Query 參數一致
- `channel_id`: 音訊來源的識別碼
- `text`: 轉錄的文字內容（可能為空字串）
- `timestamp`: 任務建立時間（Unix 時間戳記，秒）
- `duration`: 音訊片段的時長（秒）

---

### 2. 事件訂閱端點

#### 基本資訊

- **URL**: `ws://{host}:{port}/v1/events/sub`
- **協議**: WebSocket
- **用途**: 僅訂閱轉錄結果，不發送音訊

#### Query 參數

| 參數 | 類型 | 必填 | 預設值 | 說明 |
|------|------|------|--------|------|
| `session_id` | string | ✅ | - | 要訂閱的 Session ID，長度 `1-128` |

#### 連線範例

**JavaScript**:
```javascript
const ws = new WebSocket('ws://localhost:8000/v1/events/sub?session_id=room1');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(`[${data.channel_id}]: ${data.text}`);
};
```

**Python**:
```python
import asyncio
import websockets
import json

async def subscribe():
    uri = "ws://localhost:8000/v1/events/sub?session_id=room1"
    
    async with websockets.connect(uri) as websocket:
        async for message in websocket:
            data = json.loads(message)
            print(f"[{data['channel_id']}]: {data['text']}")

asyncio.run(subscribe())
```

#### 訊息流程

##### 1. Keep-Alive（可選）

**方向**: Client → Server

**格式**: Text Message (任意內容)

**用途**: 保持連線活躍

**範例**:
```python
# 每 30 秒發送 ping
async def keep_alive():
    while True:
        await websocket.send("ping")
        await asyncio.sleep(30)
```

##### 2. 轉錄結果

與「音訊串流端點」的轉錄結果相同。

---

## 錯誤處理

### WebSocket 斷線

**情況**: 連線異常中斷

**客戶端行為**:
```javascript
ws.onclose = (event) => {
  console.log(`Disconnected: ${event.code} - ${event.reason}`);
  
  // 重新連線
  setTimeout(() => {
    reconnect();
  }, 5000);
};

ws.onerror = (error) => {
  console.error('WebSocket error:', error);
};
```

**常見斷線代碼**:

| 代碼 | 說明 |
|------|------|
| 1000 | 正常關閉 |
| 1001 | 端點離開 |
| 1006 | 異常關閉（無法連線） |
| 1011 | 伺服器錯誤 |

### 伺服器端錯誤

目前會針對 client 可修正的 protocol 錯誤主動回覆 JSON error，例如：

```json
{
  "type": "error",
  "code": "INVALID_STREAM_CONFIG",
  "message": "..."
}
```

推論、VAD 或廣播期間的非預期錯誤會記錄在 server log；服務會盡量清理連線並繼續處理後續任務。

---

## 使用情境範例

### 情境 1: 單人語音輸入

```python
# 一個客戶端，既發送音訊又接收結果
async with websockets.connect(
    'ws://localhost:8000/v1/audio/stream?session_id=solo&channel_id=user1'
) as ws:
    # 發送音訊 + 接收轉錄
    ...
```

### 情境 2: 多人會議

```python
# Alice
async with websockets.connect(
    'ws://localhost:8000/v1/audio/stream?session_id=meeting&channel_id=Alice'
) as ws:
    # Alice 發送音訊，接收所有人的轉錄
    ...

# Bob
async with websockets.connect(
    'ws://localhost:8000/v1/audio/stream?session_id=meeting&channel_id=Bob'
) as ws:
    # Bob 發送音訊，接收所有人的轉錄
    ...
```

**廣播行為**:
- Alice 說話 → Server 轉錄 → 廣播給 Alice 和 Bob
- Bob 說話 → Server 轉錄 → 廣播給 Alice 和 Bob

### 情境 3: 會議 + 監控

```python
# Alice (參與者)
async with websockets.connect(
    'ws://localhost:8000/v1/audio/stream?session_id=meeting&channel_id=Alice'
) as ws:
    ...

# Bob (參與者)
async with websockets.connect(
    'ws://localhost:8000/v1/audio/stream?session_id=meeting&channel_id=Bob'
) as ws:
    ...

# Monitor (僅監聽)
async with websockets.connect(
    'ws://localhost:8000/v1/events/sub?session_id=meeting'
) as ws:
    # 僅接收轉錄，不發送音訊
    async for msg in ws:
        print(json.loads(msg))
```

### 情境 4: 僅發送不接收

```python
# 發送音訊但不接收轉錄結果（節省頻寬）
async with websockets.connect(
    'ws://localhost:8000/v1/audio/stream?session_id=room1&channel_id=user1&receive_text=false'
) as ws:
    # 僅發送音訊
    while True:
        await ws.send(audio_chunk)
```

---

## 效能考量

### 連線限制

**當前實作**: 無硬性限制

**建議**:
- 單一伺服器: < 100 並行連線
- 根據 GPU 效能調整

### 訊息頻率

**音訊區塊**:
- 建議大小: 1024 samples (64ms)
- 頻率: ~15 次/秒

**轉錄結果**:
- 頻率: 取決於語音活動（通常 0.5-3 秒一次）

### 頻寬需求

**上行（客戶端 → 伺服器）**:
- PCM 16kHz 16-bit: 32 KB/s
- 100 客戶端: ~3.2 MB/s

**下行（伺服器 → 客戶端）**:
- JSON 訊息: < 1 KB/次
- 頻率低，頻寬需求小

---

## 安全性

### 當前實作

- ❌ 無身份驗證
- ❌ 無加密（使用 `ws://`）
- ❌ 無存取控制

### 建議改進

#### 1. 使用 WSS (WebSocket over TLS)

```python
# 使用 SSL
uvicorn.run(
    app,
    host="0.0.0.0",
    port=8000,
    ssl_keyfile="key.pem",
    ssl_certfile="cert.pem"
)
```

#### 2. 加入 Token 驗證

```python
@app.websocket("/v1/audio/stream")
async def audio_stream(
    websocket: WebSocket,
    session_id: str,
    channel_id: str,
    token: str  # 新增 token 參數
):
    # 驗證 token
    if not verify_token(token):
        await websocket.close(code=1008, reason="Invalid token")
        return
    
    await websocket.accept()
    # ...
```

#### 3. 限制 Session 存取

```python
# 檢查使用者是否有權限加入 Session
if not can_join_session(user_id, session_id):
    await websocket.close(code=1008, reason="Permission denied")
    return
```

---

## 測試工具

### Postman

Postman 支援 WebSocket 測試（需 v10+）

**步驟**:
1. New → WebSocket Request
2. 輸入 URL: `ws://localhost:8000/v1/audio/stream?session_id=test&channel_id=user1`
3. Connect
4. 發送訊息

### websocat

命令列工具：

```bash
# 安裝
cargo install websocat

# 連線
websocat ws://localhost:8000/v1/events/sub?session_id=test

# 發送檔案
websocat ws://localhost:8000/v1/audio/stream?session_id=test&channel_id=user1 < audio.raw
```

### Python 測試腳本

參考專案中的 `general_stt_client.py`

---

## 總結

general_stt_server 提供簡潔但功能完整的 WebSocket API：

- ✅ 兩個端點（音訊 + 事件）
- ✅ 簡單的訊息格式（JSON + Binary）
- ✅ Room 廣播機制
- ✅ 彈性配置（語言、取樣率，並驗證 encoding 與 sample rate）
- ✅ 健康檢查與 readiness endpoint
- ✅ 易於整合（標準 WebSocket）

API 設計以簡單、直觀為原則，方便開發者快速整合。
