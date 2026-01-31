# Wiki 遷移指南 (Wiki Migration Guide)

## 概述 (Overview)

本倉庫的 `wiki/` 目錄包含完整的技術文檔，現在需要將這些內容遷移到 GitHub Wiki 頁面。由於 GitHub Wiki 是一個獨立的 Git 倉庫，無法通過常規的 Pull Request 進行操作，因此需要手動遷移。

This repository's `wiki/` directory contains complete technical documentation that needs to be migrated to GitHub Wiki pages. Since GitHub Wiki is a separate Git repository, it cannot be operated through regular Pull Requests and requires manual migration.

## Wiki 內容概覽 (Wiki Content Overview)

當前 `wiki/` 目錄包含以下文件：

| 文件名 | 說明 | 行數 |
|--------|------|------|
| README.md | Wiki 首頁與導航 | 42 |
| Architecture.md | 系統架構設計 | 427 |
| VAD-Mechanism.md | VAD 機制詳解 | 532 |
| GPU-Inference-Pipeline.md | GPU 推論管線 | 515 |
| WebSocket-Broadcasting.md | WebSocket 廣播系統 | 505 |
| Offline-Model-Configuration.md | 離線模型配置 | 501 |
| Performance-Tuning.md | 效能調校指南 | 620 |
| API-Reference.md | API 參考手冊 | 511 |

**總計**: 8 個文件，3,653 行文檔

## 遷移步驟 (Migration Steps)

### 方法一：使用 Git Clone（推薦）

#### 步驟 1: Clone Wiki 倉庫

```bash
# 在倉庫外的目錄執行
git clone https://github.com/Sikako/RealtimeSTT.wiki.git
cd RealtimeSTT.wiki
```

#### 步驟 2: 複製文件

```bash
# 從主倉庫複製 wiki 內容
cp /path/to/RealtimeSTT/wiki/*.md .
```

#### 步驟 3: 重命名首頁

GitHub Wiki 的首頁必須命名為 `Home.md`：

```bash
# 將 README.md 重命名為 Home.md
mv README.md Home.md
```

#### 步驟 4: 提交並推送

```bash
git add .
git commit -m "遷移 wiki 文檔到 GitHub Wiki"
git push origin master
```

### 方法二：通過 GitHub Web 界面

#### 步驟 1: 啟用 Wiki

1. 進入倉庫頁面：https://github.com/Sikako/RealtimeSTT
2. 點擊 "Settings"
3. 在 "Features" 區域，確認 "Wikis" 已啟用
4. 點擊 "Wiki" 標籤頁

#### 步驟 2: 創建首頁

1. 點擊 "Create the first page"
2. 將 `wiki/README.md` 的內容複製貼上
3. 標題設為 "Home"
4. 點擊 "Save Page"

#### 步驟 3: 創建其他頁面

對於每個 wiki 文件，按照以下步驟操作：

1. 點擊 "New Page"
2. 頁面標題使用文件名（不含 `.md` 擴展名）
   - 例如：`Architecture.md` → 標題為 "Architecture"
3. 複製對應文件的內容
4. 點擊 "Save Page"

**需要創建的頁面**：
- Architecture
- VAD-Mechanism
- GPU-Inference-Pipeline
- WebSocket-Broadcasting
- Offline-Model-Configuration
- Performance-Tuning
- API-Reference

### 方法三：使用自動化腳本（高級）

如果您有 GitHub Personal Access Token，可以使用以下腳本自動遷移：

```bash
# 創建遷移腳本
cat > migrate_wiki.sh << 'EOF'
#!/bin/bash

# 設定變數
REPO_DIR="/path/to/RealtimeSTT"
WIKI_DIR="$REPO_DIR/wiki"
TEMP_WIKI="/tmp/RealtimeSTT.wiki"

# Clone Wiki 倉庫
git clone https://github.com/Sikako/RealtimeSTT.wiki.git "$TEMP_WIKI"
cd "$TEMP_WIKI"

# 複製所有 wiki 文件
cp "$WIKI_DIR"/*.md .

# 重命名 README.md 為 Home.md
if [ -f "README.md" ]; then
    mv README.md Home.md
fi

# 提交並推送
git add .
git commit -m "遷移 wiki 文檔從 wiki/ 目錄到 GitHub Wiki"
git push origin master

echo "Wiki 遷移完成！"
echo "查看結果：https://github.com/Sikako/RealtimeSTT/wiki"

# 清理
cd ..
rm -rf "$TEMP_WIKI"
EOF

chmod +x migrate_wiki.sh
./migrate_wiki.sh
```

## 遷移後的檢查清單 (Post-Migration Checklist)

遷移完成後，請確認以下項目：

- [ ] 所有 8 個 wiki 頁面都已創建
- [ ] 首頁 (Home) 內容正確顯示
- [ ] 所有內部連結正常工作
  - [ ] 從 Home 頁面的連結可以跳轉到各個子頁面
  - [ ] 各子頁面之間的交叉引用正常
- [ ] 程式碼區塊格式正確
- [ ] 圖表和表格正常顯示
- [ ] 中文內容正確呈現（無亂碼）

## Wiki 連結格式調整 (Link Format Adjustment)

### 原始格式（倉庫內）

```markdown
[系統架構設計](./Architecture.md)
```

### GitHub Wiki 格式

```markdown
[系統架構設計](Architecture)
```

**注意**：如果您使用方法一（Git Clone），可以使用以下命令批次替換連結格式：

```bash
cd RealtimeSTT.wiki

# 替換所有 .md 連結
for file in *.md; do
    sed -i 's/](\.\/\([^)]*\)\.md)/](\1)/g' "$file"
done

git add .
git commit -m "修正 Wiki 連結格式"
git push origin master
```

## 維護建議 (Maintenance Recommendations)

### 選項 1: 移除倉庫中的 wiki/ 目錄

遷移完成後，可以考慮移除主倉庫中的 `wiki/` 目錄，避免內容重複：

```bash
git rm -r wiki/
git commit -m "移除 wiki/ 目錄，內容已遷移至 GitHub Wiki"
```

在 `README.md` 中更新 Wiki 連結：

```markdown
## 技術文檔

詳細的技術說明請參考 [GitHub Wiki](https://github.com/Sikako/RealtimeSTT/wiki)，包含：

- [系統架構設計](https://github.com/Sikako/RealtimeSTT/wiki/Architecture)
- [VAD 機制詳解](https://github.com/Sikako/RealtimeSTT/wiki/VAD-Mechanism)
- [GPU 推論管線](https://github.com/Sikako/RealtimeSTT/wiki/GPU-Inference-Pipeline)
- [WebSocket 廣播系統](https://github.com/Sikako/RealtimeSTT/wiki/WebSocket-Broadcasting)
- [離線模型配置](https://github.com/Sikako/RealtimeSTT/wiki/Offline-Model-Configuration)
- [效能調校指南](https://github.com/Sikako/RealtimeSTT/wiki/Performance-Tuning)
- [API 參考手冊](https://github.com/Sikako/RealtimeSTT/wiki/API-Reference)
```

### 選項 2: 保留 wiki/ 目錄作為備份

如果希望在倉庫中保留 wiki 文檔的副本（例如用於離線查閱），可以保留 `wiki/` 目錄，並在 README.md 中說明：

```markdown
## 技術文檔

技術文檔有兩個版本：
- **GitHub Wiki**（推薦）：https://github.com/Sikako/RealtimeSTT/wiki
- **倉庫內副本**：[wiki/](./wiki/) 目錄（可能不是最新版本）

建議查看 GitHub Wiki 以獲取最新文檔。
```

## 常見問題 (FAQ)

### Q1: 為什麼不能通過 Pull Request 操作 Wiki？

**A**: GitHub Wiki 是一個獨立的 Git 倉庫，與主倉庫分離。它有自己的 Git 歷史記錄，無法通過主倉庫的 PR 進行修改。

### Q2: Wiki 倉庫的 URL 是什麼？

**A**: Wiki 倉庫的 URL 格式為：`https://github.com/[用戶名]/[倉庫名].wiki.git`

對於本倉庫：`https://github.com/Sikako/RealtimeSTT.wiki.git`

### Q3: 誰可以編輯 Wiki？

**A**: 預設情況下，所有能夠訪問倉庫的用戶都可以編輯 Wiki。可以在倉庫設置中更改此權限。

### Q4: Wiki 內容會包含在倉庫的發佈版本中嗎？

**A**: 不會。Wiki 是獨立的，不會包含在 releases 或 tags 中。如果需要在發佈版本中包含文檔，應該保留 `wiki/` 目錄。

### Q5: 如何在本地編輯 Wiki？

**A**: Clone Wiki 倉庫，編輯 Markdown 文件，然後提交並推送：

```bash
git clone https://github.com/Sikako/RealtimeSTT.wiki.git
cd RealtimeSTT.wiki
# 編輯文件
git add .
git commit -m "更新文檔"
git push origin master
```

## 參考資源 (References)

- [GitHub Wiki 官方文檔](https://docs.github.com/en/communities/documenting-your-project-with-wikis)
- [Markdown 語法指南](https://www.markdownguide.org/)
- [GitHub Flavored Markdown](https://github.github.com/gfm/)

## 需要協助？

如果在遷移過程中遇到問題，請：
1. 檢查本指南的常見問題部分
2. 在倉庫中提交 Issue
3. 聯繫倉庫維護者

---

**最後更新**: 2026-01-31
