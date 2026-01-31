#!/bin/bash

# Wiki 遷移自動化腳本
# Wiki Migration Automation Script
# 
# 此腳本會自動將 wiki/ 目錄的內容遷移到 GitHub Wiki
# This script automatically migrates content from wiki/ directory to GitHub Wiki

set -e  # 遇到錯誤時停止執行

# 顏色定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 函數：打印彩色訊息
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 檢查必要的工具
check_requirements() {
    print_info "檢查必要工具..."
    
    if ! command -v git &> /dev/null; then
        print_error "未找到 git 命令，請先安裝 Git"
        exit 1
    fi
    
    print_info "✓ 所有必要工具已就緒"
}

# 取得當前腳本所在目錄
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIKI_SOURCE_DIR="$SCRIPT_DIR/wiki"
TEMP_WIKI_DIR="/tmp/RealtimeSTT.wiki.$$"

# 顯示歡迎訊息
echo "======================================"
echo "  RealtimeSTT Wiki 遷移工具"
echo "======================================"
echo ""

# 檢查必要條件
check_requirements

# 檢查 wiki 源目錄是否存在
if [ ! -d "$WIKI_SOURCE_DIR" ]; then
    print_error "找不到 wiki 目錄：$WIKI_SOURCE_DIR"
    exit 1
fi

print_info "Wiki 源目錄：$WIKI_SOURCE_DIR"

# 計算 wiki 文件數量
WIKI_FILE_COUNT=$(find "$WIKI_SOURCE_DIR" -name "*.md" | wc -l)
print_info "找到 $WIKI_FILE_COUNT 個 Markdown 文件"

# 列出所有 wiki 文件
echo ""
print_info "將遷移以下文件："
find "$WIKI_SOURCE_DIR" -name "*.md" -exec basename {} \; | sort

echo ""
read -p "是否繼續？(y/N) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_warning "已取消遷移"
    exit 0
fi

# Clone Wiki 倉庫
print_info "正在 Clone GitHub Wiki 倉庫..."
if ! git clone https://github.com/Sikako/RealtimeSTT.wiki.git "$TEMP_WIKI_DIR" 2>/dev/null; then
    print_error "無法 Clone Wiki 倉庫。可能的原因："
    print_error "  1. Wiki 尚未啟用（請先在 GitHub 上創建第一個 Wiki 頁面）"
    print_error "  2. 網路連線問題"
    print_error "  3. 權限不足"
    exit 1
fi

cd "$TEMP_WIKI_DIR"
print_info "✓ Wiki 倉庫 Clone 完成"

# 複製 wiki 文件
print_info "正在複製 wiki 文件..."
cp "$WIKI_SOURCE_DIR"/*.md .
print_info "✓ 文件複製完成"

# 重命名 README.md 為 Home.md
if [ -f "README.md" ]; then
    print_info "正在重命名 README.md → Home.md"
    mv README.md Home.md
fi

# 修正 Wiki 連結格式
print_info "正在修正 Wiki 連結格式..."
for file in *.md; do
    # 替換 ./filename.md 為 filename
    sed -i 's/](\.\/\([^)]*\)\.md)/](\1)/g' "$file"
done
print_info "✓ 連結格式已修正"

# 顯示變更摘要
echo ""
print_info "變更摘要："
git status --short

# 提交變更
echo ""
read -p "是否提交並推送到 GitHub Wiki？(y/N) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_warning "已取消推送，但文件已準備完成在：$TEMP_WIKI_DIR"
    print_info "您可以手動執行以下命令來完成遷移："
    echo "  cd $TEMP_WIKI_DIR"
    echo "  git add ."
    echo "  git commit -m '遷移 wiki 文檔'"
    echo "  git push origin master"
    exit 0
fi

# 提交變更
print_info "正在提交變更..."
git add .

if git diff --cached --quiet; then
    print_warning "沒有檢測到變更，可能 Wiki 內容已經是最新的"
else
    git commit -m "遷移 wiki 文檔從倉庫 wiki/ 目錄到 GitHub Wiki

- 遷移了 $WIKI_FILE_COUNT 個 Markdown 文件
- 將 README.md 重命名為 Home.md
- 修正了內部連結格式以適配 GitHub Wiki"
    print_info "✓ 變更已提交"
fi

# 推送到遠端
print_info "正在推送到 GitHub Wiki..."
if git push origin master; then
    print_info "✓ 推送成功！"
else
    print_error "推送失敗，請檢查網路連線和權限設定"
    exit 1
fi

# 清理臨時目錄
cd "$SCRIPT_DIR"
rm -rf "$TEMP_WIKI_DIR"
print_info "✓ 臨時文件已清理"

# 顯示成功訊息
echo ""
echo "======================================"
print_info "${GREEN}Wiki 遷移完成！${NC}"
echo "======================================"
echo ""
print_info "查看 Wiki：https://github.com/Sikako/RealtimeSTT/wiki"
echo ""
print_info "接下來您可以："
echo "  1. 訪問 Wiki 頁面確認內容正確"
echo "  2. 考慮移除倉庫中的 wiki/ 目錄（避免內容重複）"
echo "  3. 更新 README.md 中的 Wiki 連結"
echo ""
print_info "詳細資訊請參考：WIKI_MIGRATION_GUIDE.md"
