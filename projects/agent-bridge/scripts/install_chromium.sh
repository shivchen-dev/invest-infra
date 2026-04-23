#!/bin/bash
# Playwright Chromium 安装脚本

set -e

echo "=== Playwright Chromium 安装脚本 ==="

# 检查是否已安装
if [ -d "$HOME/.cache/ms-playwright/chromium-1208" ]; then
    echo "✅ Chromium 已安装"
    exit 0
fi

# 创建临时目录
TEMP_DIR=$(mktemp -d)
cd "$TEMP_DIR"

echo "📥 下载 Chromium..."
# 使用 wget 断点续传下载
wget -c -O chromium.zip "https://cdn.playwright.dev/chrome-for-testing-public/145.0.7632.6/linux64/chrome-linux64.zip" || {
    echo "❌ 下载失败"
    exit 1
}

echo "📦 解压..."
unzip -q chromium.zip

echo "📂 移动到 Playwright 目录..."
mkdir -p "$HOME/.cache/ms-playwright/chromium-1208"
mv chrome-linux64 "$HOME/.cache/ms-playwright/chromium-1208/"

echo "🧹 清理临时文件..."
rm -rf "$TEMP_DIR"

echo "✅ Chromium 安装完成!"
echo "位置: $HOME/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome"