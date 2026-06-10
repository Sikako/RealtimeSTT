# WebSocket 廣播系統

## 概述

WebSocket 廣播系統負責將轉錄結果即時推送給所有相關客戶端，實現多人協作場景下的訊息同步。

## Room (Session) 概念

### 設計理念

**Room** 類似於聊天室，同一個 Room 內的所有客戶端可以互相接收訊息。

```
Room "Meeting001"
├── Alice (WebSocket 1) → 說話 → 轉錄 → 廣播給 Alice, Bob, Observer
├── Bob (WebSocket 2) → 說話 → 轉錄 → 廣播給 Alice, Bob, Observer  
└── Observer (WebSocket 3) → 僅接收，不發送音訊
```

### 資料結構

```python
class ConnectionManager:
    def __init__(self):
        # session_id -> Set[WebSocket]
        self.rooms: Dict[str, Set[WebSocket]] = {}
        self.lock = asyncio.Lock()
```

**範例**:
```python
self.rooms = {
    "Meeting001": {websocket_alice, websocket_bob, websocket_observer},
    "Meeting002": {websocket_charlie, websocket_david}
}
```

## 連線管理

### 建立連線

```python
async def connect(self, session_id: str, ws: WebSocket):
    await ws.accept()  # 接受 WebSocket 連線
    
    async with self.lock:
        if session_id not in self.rooms:
            self.rooms[session_id] = set()
        self.rooms[session_id].add(ws)
        
    logger.info(f"Client joined session {session_id}. Total: {len(self.rooms[session_id])}")
```

**流程**:
1. Accept WebSocket 連線
2. 取得鎖（避免競爭）
3. 建立或取得 Room
4. 加入 WebSocket 到 Room
5. 釋放鎖

### 斷開連線

```python
async def disconnect(self, session_id: str, ws: WebSocket):
    async with self.lock:
        if session_id in self.rooms:
            if ws in self.rooms[session_id]:
                self.rooms[session_id].remove(ws)
            
            # 清理空 Room
            if not self.rooms[session_id]:
                del self.rooms[session_id]
    
    logger.info(f"Client left session {session_id}.")
```

**流程**:
1. 取得鎖
2. 從 Room 移除 WebSocket
3. 如果 Room 為空，刪除 Room
4. 釋放鎖

## 廣播機制

### 廣播實作

```python
async def broadcast(self, event: dict):
    session_id = event.get("session_id")
    if not session_id:
        return
    
    # 1. 取得目標 WebSocket（快照）
    target_sockets = []
    async with self.lock:
        if session_id in self.rooms:
            target_sockets = list(self.rooms[session_id])
    
    if not target_sockets:
        return
    
    # 2. 廣播訊息
    message = json.dumps(event)
    dead_sockets = []
    
    for ws in target_sockets:
        try:
            await ws.send_text(message)
        except Exception as e:
            dead_sockets.append(ws)
    
    # 3. 清理失效連線
    if dead_sockets:
        async with self.lock:
            if session_id in self.rooms:
                for ws in dead_sockets:
                    if ws in self.rooms[session_id]:
                        self.rooms[session_id].remove(ws)
                
                if not self.rooms[session_id]:
                    del self.rooms[session_id]
```

### 關鍵設計

#### 快照機制

```python
# ✅ 正確: 先複製 List
target_sockets = list(self.rooms[session_id])
async with self.lock:
    # 釋放鎖後再廣播

for ws in target_sockets:
    await ws.send_text(message)
```

**為何需要快照？**
- 廣播過程中可能有新連線或斷線
- 避免在迭代時修改 Set（RuntimeError）
- 減少鎖持有時間

```python
# ❌ 錯誤: 在鎖內廣播
async with self.lock:
    for ws in self.rooms[session_id]:
        await ws.send_text(message)  # 阻塞！其他操作無法進行
```

#### 失效連線處理

```python
# 收集失效連線
dead_sockets = []
for ws in target_sockets:
    try:
        await ws.send_text(message)
    except Exception:
        dead_sockets.append(ws)

# 批次清理
for ws in dead_sockets:
    self.rooms[session_id].remove(ws)
```

**為何不立即清理？**
- 減少鎖操作次數
- 避免在迭代時修改 Set

## Event Bus 整合

### 跨執行緒通訊

```python
# InferenceEngine (Worker Thread)
result = {
    "type": "transcription",
    "session_id": session_id,
    "channel_id": channel_id,
    "text": text,
    ...
}

# 傳遞到 asyncio Event Loop
asyncio.run_coroutine_threadsafe(event_bus.put(result), main_loop)
```

### Broadcaster Task

```python
async def broadcaster():
    """負責將 event_bus 的資料推給 manager 進行廣播"""
    while True:
        if event_bus:
            event = await event_bus.get()  # 阻塞等待
            await manager.broadcast(event)  # 廣播
        else:
            await asyncio.sleep(0.1)
```

**流程**:
```
GPU Worker → event_bus.put() → broadcaster() → manager.broadcast() → WebSocket.send_text()
  (Thread)        (Queue)        (asyncio)         (asyncio)            (asyncio)
```

## 兩種端點設計

### 端點 1: /v1/audio/stream

**功能**: 發送音訊 + 接收轉錄

```python
@app.websocket("/v1/audio/stream")
async def audio_stream(
    websocket: WebSocket, 
    session_id: str,
    channel_id: str,
    receive_text: bool = True  # 是否接收轉錄
):
    await websocket.accept()
    
    # 加入 Room（如果需要接收）
    if receive_text:
        await manager.connect(session_id, websocket)
    
    # ... 處理音訊
    
    finally:
        if receive_text:
            await manager.disconnect(session_id, websocket)
```

**使用情境**:
- 使用者需要即時看到自己和他人的發言
- 會議記錄（多人協作）

### 端點 2: /v1/events/sub

**功能**: 僅接收轉錄（不發送音訊）

```python
@app.websocket("/v1/events/sub")
async def event_subscription(
    websocket: WebSocket, 
    session_id: str
):
    await websocket.accept()
    await manager.connect(session_id, websocket)
    
    try:
        while True:
            await websocket.receive_text()  # Keep alive
    except WebSocketDisconnect:
        await manager.disconnect(session_id, websocket)
```

**使用情境**:
- 監控面板（僅顯示）
- SIP 伺服器控制端（記錄對話）
- 字幕顯示器

## 訊息格式

### 轉錄結果

```json
{
  "type": "transcription",
  "session_id": "Meeting001",
  "channel_id": "Alice",
  "text": "大家好，我們開始今天的會議",
  "timestamp": 1706659200.123,
  "duration": 2.5
}
```

### 未來擴展

```json
{
  "type": "status",
  "session_id": "Meeting001",
  "channel_id": "Alice",
  "status": "speaking"  // "speaking", "idle", "disconnected"
}
```

```json
{
  "type": "error",
  "session_id": "Meeting001",
  "error": "VAD detection failed",
  "code": 500
}
```

## 並發安全

### asyncio.Lock

```python
self.lock = asyncio.Lock()

async def connect(...):
    async with self.lock:
        # 修改共享資料結構
        self.rooms[session_id].add(ws)
```

**為何需要鎖？**
- 多個 WebSocket 處理器並行執行
- 避免 Race Condition
- 確保資料一致性

### 競爭條件範例

**無鎖** (❌):
```python
# Thread 1
if session_id not in self.rooms:
    # [被中斷]
    self.rooms[session_id] = set()

# Thread 2
if session_id not in self.rooms:  # True (Thread 1 還沒執行完)
    self.rooms[session_id] = set()  # 覆蓋！

# Thread 1 繼續
self.rooms[session_id] = set()  # 再次覆蓋！
```

**有鎖** (✅):
```python
async with self.lock:
    if session_id not in self.rooms:
        self.rooms[session_id] = set()  # 原子操作
```

## 效能優化

### 1. 減少鎖持有時間

```python
# ✅ 好: 鎖外廣播
async with self.lock:
    target_sockets = list(self.rooms[session_id])

for ws in target_sockets:  # 鎖已釋放
    await ws.send_text(message)
```

```python
# ❌ 差: 鎖內廣播
async with self.lock:
    for ws in self.rooms[session_id]:
        await ws.send_text(message)  # 阻塞時鎖被持有
```

### 2. 批次清理

```python
# ✅ 批次清理失效連線
dead_sockets = []
for ws in target_sockets:
    try:
        await ws.send_text(message)
    except:
        dead_sockets.append(ws)

if dead_sockets:  # 一次性取鎖
    async with self.lock:
        for ws in dead_sockets:
            self.rooms[session_id].remove(ws)
```

### 3. 快取 JSON 序列化

```python
# 當前: 每次序列化
message = json.dumps(event)

# 優化: 序列化一次
message = json.dumps(event)
for ws in target_sockets:
    await ws.send_text(message)  # 重複使用
```

## 監控與除錯

### 連線數統計

```python
def get_stats(self):
    total_connections = sum(len(sockets) for sockets in self.rooms.values())
    return {
        "total_rooms": len(self.rooms),
        "total_connections": total_connections,
        "rooms": {
            session_id: len(sockets)
            for session_id, sockets in self.rooms.items()
        }
    }
```

### 日誌記錄

```python
async def connect(self, session_id: str, ws: WebSocket):
    # ...
    logger.info(f"[{session_id}] Client connected. Total: {len(self.rooms[session_id])}")

async def broadcast(self, event: dict):
    logger.debug(f"Broadcasting to {len(target_sockets)} clients in {session_id}")
    
    if dead_sockets:
        logger.warning(f"Removed {len(dead_sockets)} dead connections from {session_id}")
```

## 錯誤處理

### WebSocket 錯誤

```python
try:
    await ws.send_text(message)
except websockets.exceptions.ConnectionClosed:
    logger.info(f"Connection closed: {ws}")
    dead_sockets.append(ws)
except Exception as e:
    logger.error(f"Broadcast error: {e}")
    dead_sockets.append(ws)
```

### 清理失敗處理

```python
async def disconnect(self, session_id: str, ws: WebSocket):
    try:
        async with self.lock:
            if session_id in self.rooms:
                self.rooms[session_id].discard(ws)  # 使用 discard 而非 remove
    except Exception as e:
        logger.error(f"Disconnect error: {e}")
```

## 擴展方案

### 方案一: Redis Pub/Sub

**適用**: 多伺服器部署

```python
# Server 1
redis_client.publish(f"session:{session_id}", json.dumps(event))

# Server 2
def on_message(channel, message):
    event = json.loads(message)
    await manager.broadcast(event)

redis_client.subscribe(f"session:{session_id}", on_message)
```

### 方案二: 過濾廣播

**需求**: 僅廣播給特定客戶端

```python
async def broadcast(self, event: dict, filter_fn=None):
    target_sockets = [
        ws for ws in self.rooms[session_id]
        if filter_fn is None or filter_fn(ws)
    ]
    # ...
```

**使用**:
```python
# 僅廣播給非發送者
await manager.broadcast(
    event,
    filter_fn=lambda ws: ws != sender_websocket
)
```

## 最佳實踐

1. **快照機制**: 避免迭代時修改
2. **批次清理**: 減少鎖操作
3. **鎖外 I/O**: 降低鎖競爭
4. **錯誤隔離**: 單一連線錯誤不影響其他
5. **日誌記錄**: 便於除錯與監控

## 總結

WebSocket 廣播系統透過精心設計的 Room 機制與並發控制，實現了：

- ✅ 多客戶端即時同步
- ✅ 執行緒安全
- ✅ 自動清理失效連線
- ✅ 高效能廣播
- ✅ 可擴展架構

這是實現多人協作語音轉錄的關鍵組件。
