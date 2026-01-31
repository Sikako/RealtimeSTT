# general_stt_server 技術文檔

本 Wiki 提供 general_stt_server 的深入技術文檔，涵蓋系統架構、核心機制、效能調校等主題。

## 文檔目錄

### 基礎架構
- [系統架構設計](./Architecture.md) - 整體系統設計與模組劃分
- [資料流程圖](./Data-Flow.md) - 音訊資料的完整處理流程

### 核心機制
- [VAD 機制詳解](./VAD-Mechanism.md) - Silero VAD 的運作原理與優化
- [GPU 推論管線](./GPU-Inference-Pipeline.md) - Whisper 模型推論流程
- [WebSocket 廣播系統](./WebSocket-Broadcasting.md) - 多客戶端廣播機制

### 進階主題
- [離線模型配置](./Offline-Model-Configuration.md) - 離線環境的模型配置與 Monkey Patching
- [效能調校指南](./Performance-Tuning.md) - 系統效能優化策略

### 參考資料
- [API 參考手冊](./API-Reference.md) - 完整的 API 文檔
- [效能調校指南](./Performance-Tuning.md) - 系統效能優化策略

## 快速導航

### 我想了解...

- **系統如何運作？** → 閱讀 [系統架構設計](./Architecture.md)
- **如何調整 VAD 參數？** → 閱讀 [VAD 機制詳解](./VAD-Mechanism.md)
- **如何優化效能？** → 閱讀 [效能調校指南](./Performance-Tuning.md)
- **離線環境如何配置？** → 閱讀 [離線模型配置](./Offline-Model-Configuration.md)
- **完整 API 規格？** → 閱讀 [API 參考手冊](./API-Reference.md)

## 貢獻指南

如果您發現文檔有錯誤或需要改進的地方，歡迎提交 Pull Request。

### 文檔撰寫規範

1. 使用繁體中文撰寫
2. 程式碼範例需包含註解
3. 使用 Markdown 格式
4. 包含實際的使用案例
