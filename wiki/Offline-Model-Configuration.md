# 離線模型配置

## 概述

general_stt_server 設計為完全離線運行，無需網路連接即可正常工作。本文檔詳細說明如何配置離線環境，包括模型下載、路徑設定與 Monkey Patching 機制。

## 為何需要離線配置？

### 常見場景

1. **企業內網環境**: 無法訪問外網
2. **軍事/政府**: 安全性要求
3. **邊緣裝置**: 無穩定網路
4. **降低延遲**: 避免模型下載時間

### 預設行為問題

**RealtimeSTT 預設行為**:
```python
# 會嘗試從網路下載
torch.hub.load('snakers4/silero-vad', model='silero_vad')
```

**faster-whisper 預設行為**:
```python
# 會嘗試從 HuggingFace Hub 下載
WhisperModel("medium")
```

**問題**: 離線環境無法使用！

## 模型準備

### 1. Whisper 模型

#### 下載方式

**方法一: 使用 faster-whisper API**

```python
from faster_whisper import WhisperModel

# 首次載入會自動下載
model = WhisperModel("medium", device="cpu", compute_type="int8")
```

**預設下載位置**:
```
Linux: ~/.cache/huggingface/hub/
Windows: C:\Users\<username>\.cache\huggingface\hub\
```

**方法二: 手動下載**

```bash
# 使用 huggingface-cli
pip install huggingface-hub
huggingface-cli download Systran/faster-whisper-medium

# 或直接下載
wget https://huggingface.co/Systran/faster-whisper-medium/resolve/main/model.bin
```

#### 目錄結構

複製到專案的 `models/` 目錄：

```
models/
├── faster-whisper-tiny/
│   ├── model.bin
│   ├── config.json
│   └── vocabulary.txt
├── faster-whisper-small/
│   └── ...
├── faster-whisper-medium/
│   └── ...
└── faster-whisper-large-v2/
    └── ...
```

### 2. Silero VAD 模型

#### 下載方式

**方法一: 自動下載 (有網路時)**

```python
import torch

# 設定下載路徑
import os
os.environ['TORCH_HOME'] = './models'

# 首次載入會下載
model = torch.hub.load('snakers4/silero-vad', model='silero_vad')
```

**方法二: 手動下載**

```bash
# 克隆 Repository
git clone https://github.com/snakers4/silero-vad.git

# 複製到專案
cp -r silero-vad models/hub/snakers4_silero-vad_master
```

#### 目錄結構

```
models/hub/snakers4_silero-vad_master/
├── hubconf.py
├── silero_vad.onnx
├── silero_vad.jit
├── utils_vad.py
└── files/
    └── ...
```

## Monkey Patching 機制

### 為何需要 Monkey Patching？

**問題**: 即使模型在本地，RealtimeSTT 仍會嘗試連網檢查更新

**解決**: 攔截並修改相關函式

### Patch 1: torch.hub.load

#### 實作

```python
import torch

# 儲存原始函式
_original_torch_hub_load = torch.hub.load

def offline_torch_hub_load(repo_or_dir, model, *args, **kwargs):
    """
    攔截 torch.hub.load，若目標是 silero-vad，強制導向本地 Cache 目錄。
    並將 source 設為 'local'，避免聯網檢查。
    """
    if "silero-vad" in repo_or_dir:
        # 建構本地路徑
        local_repo_path = os.path.join(MODELS_DIR, "hub", "snakers4_silero-vad_master")
        
        if os.path.exists(local_repo_path):
            logger.info(f"Redirecting Silero VAD load to local path: {local_repo_path}")
            # 強制改為 local 模式
            kwargs["source"] = "local"
            return _original_torch_hub_load(local_repo_path, model, *args, **kwargs)
        else:
            logger.warning(f"Silero VAD local path not found: {local_repo_path}, falling back to default.")
            
    return _original_torch_hub_load(repo_or_dir, model, *args, **kwargs)

# 應用 Patch
torch.hub.load = offline_torch_hub_load
```

#### 工作原理

```
RealtimeSTT 呼叫 torch.hub.load('snakers4/silero-vad', ...)
        ↓
offline_torch_hub_load() [我們的函式]
        ↓
檢查是否包含 "silero-vad"
        ↓
是 → 轉向本地路徑 (models/hub/snakers4_silero-vad_master)
否 → 使用原始函式
```

#### 關鍵參數

```python
kwargs["source"] = "local"
```

**效果**: 告訴 `torch.hub.load` 不要嘗試從 GitHub 下載或檢查更新

### Patch 2: Threading 模式

#### 實作

```python
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
```

#### 為何需要？

**原始行為**:
```python
# RealtimeSTT 原始碼
if platform.system() == "Windows":
    # Windows 使用 Thread
    thread = threading.Thread(...)
else:
    # Linux/Mac 使用 Process
    process = multiprocessing.Process(...)
```

**問題**:
- Multiprocessing 無法共享模型實例
- 每個 Process 獨立載入模型（高記憶體消耗）
- 不適合高併發場景

**解決**: 強制使用 Thread

### Patch 3: 剝離推論邏輯

#### 實作

```python
def dummy_worker(*args, **kwargs):
    """虛擬 Worker，用於替換 RealtimeSTT 的 Internal Processing"""
    conn = args[0]
    
    try:
        ready_event = args[7]
        if ready_event:
            ready_event.set()  # 通知主程序初始化完成
    except IndexError:
        pass

    # 持續運行但不做任何事
    while True:
        try:
            if conn.poll(0.5): 
                conn.recv()  # 清空 pipe 防止阻塞
        except: 
            break

# 應用 Patch
with patch_lock:
    _original_worker = AudioToTextRecorder._transcription_worker
    AudioToTextRecorder._transcription_worker = dummy_worker
    
    # 初始化
    super().__init__(...)
    
    # 還原
    AudioToTextRecorder._transcription_worker = _original_worker
```

#### 為何需要？

**問題**: RealtimeSTT 內建推論 Worker 會啟動獨立執行緒進行轉錄

**目標**: 我們想要統一管理推論（GPU Pool）

**解決**: 替換為空 Worker，推論邏輯由我們自行實作

## 環境變數設定

### TORCH_HOME

```python
import os
os.environ["TORCH_HOME"] = MODELS_DIR
```

**效果**: 
- 設定 PyTorch 模型快取目錄
- Silero VAD 會從此目錄載入

### HF_HUB_OFFLINE

```python
os.environ["HF_HUB_OFFLINE"] = "1"
```

**效果**:
- 告訴 HuggingFace Hub 不要嘗試聯網
- 僅使用本地快取

### 完整範例

```python
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")

os.environ["TORCH_HOME"] = MODELS_DIR
os.environ["HF_HUB_OFFLINE"] = "1"
```

## 自動模型偵測

### 實作

```python
def find_available_model():
    """自動偵測可用模型 (優先順序: Medium -> Large -> Small -> Tiny)"""
    priorities = ["medium", "large-v2", "small", "tiny"]
    
    for size in priorities:
        for d in os.listdir(MODELS_DIR):
            if f"faster-whisper-{size}" in d and os.path.isdir(os.path.join(MODELS_DIR, d)):
                path = os.path.join(MODELS_DIR, d)
                logger.info(f"Found local model: {size} at {path}")
                return path
    
    logger.warning("No local model found in priority list, defaulting to 'tiny'")
    return "tiny"  # 後備方案（會嘗試下載）

WHISPER_MODEL_PATH = find_available_model()
```

### 優點

- 自動選擇最佳可用模型
- 不需手動配置
- 有後備方案

## 載入驗證

### VAD 模型驗證

```python
def verify_vad_model():
    """驗證 Silero VAD 模型是否可用"""
    try:
        model = torch.hub.load(
            os.path.join(MODELS_DIR, "hub", "snakers4_silero-vad_master"),
            model='silero_vad',
            source='local'
        )
        logger.info("✅ Silero VAD model loaded successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to load Silero VAD model: {e}")
        return False
```

### Whisper 模型驗證

```python
def verify_whisper_model():
    """驗證 Whisper 模型是否可用"""
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(
            WHISPER_MODEL_PATH,
            device="cpu",  # 驗證時使用 CPU
            compute_type="int8",
            local_files_only=True
        )
        logger.info(f"✅ Whisper model loaded successfully: {WHISPER_MODEL_PATH}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to load Whisper model: {e}")
        return False
```

### 啟動時驗證

```python
@app.on_event("startup")
async def startup():
    # 驗證模型
    if not verify_vad_model():
        logger.error("VAD model not available. Please download it first.")
        # 可選擇退出或提示使用者
    
    if not verify_whisper_model():
        logger.error("Whisper model not available. Please download it first.")
    
    # 載入模型
    engine.load_model()
```

## 故障排除

### 問題 1: VAD 模型載入失敗

**錯誤訊息**:
```
FileNotFoundError: models/hub/snakers4_silero-vad_master not found
```

**解決**:
```bash
# 檢查目錄是否存在
ls models/hub/snakers4_silero-vad_master

# 若不存在，手動下載
git clone https://github.com/snakers4/silero-vad.git
mv silero-vad models/hub/snakers4_silero-vad_master
```

### 問題 2: Whisper 模型載入失敗

**錯誤訊息**:
```
OSError: models/faster-whisper-medium does not appear to be a valid model
```

**解決**:
```python
# 檢查模型檔案
import os
model_path = "models/faster-whisper-medium"
required_files = ["model.bin", "config.json", "vocabulary.txt"]

for f in required_files:
    path = os.path.join(model_path, f)
    if not os.path.exists(path):
        print(f"Missing: {path}")
```

### 問題 3: 仍嘗試連網

**錯誤訊息**:
```
urllib.error.URLError: <urlopen error [Errno -3] Temporary failure in name resolution>
```

**解決**:
```python
# 確認環境變數已設定
import os
print(os.environ.get("TORCH_HOME"))
print(os.environ.get("HF_HUB_OFFLINE"))

# 確認 Monkey Patch 已執行
import torch
print(torch.hub.load == offline_torch_hub_load)  # 應為 True
```

## 模型更新流程

### 1. 下載新模型

```bash
# 使用 huggingface-cli
huggingface-cli download Systran/faster-whisper-large-v3 \
    --local-dir models/faster-whisper-large-v3
```

### 2. 更新配置

```python
# 方法一: 修改優先順序
def find_available_model():
    priorities = ["large-v3", "medium", "large-v2", "small", "tiny"]
    # ...

# 方法二: 直接指定
WHISPER_MODEL_PATH = "models/faster-whisper-large-v3"
```

### 3. 重啟伺服器

```bash
# 停止
Ctrl+C

# 啟動
python general_stt_server.py
```

## 最佳實踐

1. **預先下載**: 在有網路時下載所有模型
2. **版本控制**: 記錄模型版本與下載來源
3. **驗證機制**: 啟動時驗證模型可用性
4. **後備方案**: 準備多個模型以防主要模型損壞
5. **文檔化**: 記錄模型下載與配置步驟

## 部署檢查清單

- [ ] 下載 Whisper 模型到 `models/`
- [ ] 下載 Silero VAD 模型到 `models/hub/`
- [ ] 設定環境變數 (`TORCH_HOME`, `HF_HUB_OFFLINE`)
- [ ] 應用 Monkey Patches
- [ ] 驗證模型可載入
- [ ] 測試離線環境（斷網測試）
- [ ] 記錄模型版本與配置

## 總結

離線模型配置透過以下機制確保系統完全離線運行：

- ✅ Monkey Patching (攔截網路呼叫)
- ✅ 環境變數設定 (離線模式)
- ✅ 本地模型載入 (無需下載)
- ✅ 自動模型偵測 (智慧選擇)
- ✅ 驗證機制 (確保可用)

這使得 general_stt_server 可以在完全隔離的環境中穩定運行。
