# Wiki 遷移工具說明

## 問題說明

您提到無法直接操作 GitHub Wiki 頁面，希望能將倉庫中 `wiki/` 目錄的內容轉移到 GitHub Wiki。

## 解決方案

由於 GitHub Wiki 是一個獨立的 Git 倉庫，無法通過 Pull Request 直接操作。因此，我為您創建了以下工具和文檔來協助遷移：

### 1. 詳細遷移指南

📖 **[WIKI_MIGRATION_GUIDE.md](./WIKI_MIGRATION_GUIDE.md)**

這份完整的指南包含：
- Wiki 內容概覽
- 三種遷移方法（Git Clone、Web 界面、自動化腳本）
- 遷移後的檢查清單
- 常見問題解答
- 維護建議

### 2. 自動化遷移腳本

🔧 **[migrate_wiki.sh](./migrate_wiki.sh)**

這個 Bash 腳本可以自動完成整個遷移過程：

```bash
# 使用方法
./migrate_wiki.sh
```

腳本會自動：
1. Clone GitHub Wiki 倉庫
2. 複製 `wiki/` 目錄的所有 Markdown 文件
3. 將 `README.md` 重命名為 `Home.md`（Wiki 首頁）
4. 修正內部連結格式以適配 GitHub Wiki
5. 提交並推送變更

### 3. README 更新

README.md 已更新，加入了 Wiki 遷移說明，讓其他用戶也能了解如何遷移。

## 快速開始

### 最簡單的方法（使用自動化腳本）：

```bash
# 1. 確保您有權限推送到 Wiki 倉庫
# 2. 執行腳本
./migrate_wiki.sh

# 3. 按照提示操作，完成後訪問：
# https://github.com/Sikako/RealtimeSTT/wiki
```

### 手動遷移方法：

如果您偏好手動操作，請按照 [WIKI_MIGRATION_GUIDE.md](./WIKI_MIGRATION_GUIDE.md) 中的詳細步驟進行。

## 遷移後的建議

遷移完成後，您有兩個選擇：

### 選項 1: 移除倉庫中的 wiki/ 目錄

```bash
git rm -r wiki/
git commit -m "移除 wiki/ 目錄，內容已遷移至 GitHub Wiki"
```

這樣可以避免內容重複，所有文檔都統一在 GitHub Wiki 中維護。

### 選項 2: 保留作為備份

保留 `wiki/` 目錄作為離線備份，但在 README 中註明 GitHub Wiki 是主要版本。

## 文件清單

本次新增的文件：

1. **WIKI_MIGRATION_GUIDE.md** - 完整的 Wiki 遷移指南（繁體中文）
2. **migrate_wiki.sh** - 自動化遷移腳本
3. **WIKI_MIGRATION_README.md** - 本說明文件

修改的文件：
- **README.md** - 加入 Wiki 遷移說明

## 技術細節

### Wiki 內容統計

- 總文件數：8 個
- 總行數：3,653 行
- 文件大小：約 83 KB

### 文件列表

| 文件 | 說明 | 行數 |
|------|------|------|
| README.md | Wiki 導航頁 | 42 |
| Architecture.md | 系統架構 | 427 |
| VAD-Mechanism.md | VAD 機制 | 532 |
| GPU-Inference-Pipeline.md | GPU 推論 | 515 |
| WebSocket-Broadcasting.md | WebSocket 廣播 | 505 |
| Offline-Model-Configuration.md | 離線配置 | 501 |
| Performance-Tuning.md | 效能調校 | 620 |
| API-Reference.md | API 參考 | 511 |

## 需要協助？

如果在遷移過程中遇到任何問題：

1. 查看 [WIKI_MIGRATION_GUIDE.md](./WIKI_MIGRATION_GUIDE.md) 的常見問題部分
2. 檢查腳本的錯誤訊息
3. 確認您有權限推送到 Wiki 倉庫

## 總結

雖然我無法直接在 GitHub Wiki 上創建頁面（這需要直接操作 Wiki 的 Git 倉庫），但我已經為您準備了：

✅ 詳細的遷移指南  
✅ 自動化遷移腳本  
✅ README 更新  
✅ 完整的說明文檔  

您只需要執行 `./migrate_wiki.sh` 即可完成遷移！
