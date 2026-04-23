#!/bin/bash
# 安装 Chromium 和 Playwright 依赖

echo "=== 安装 Chromium (轻量级方式) ==="

# 方法1: 尝试下载较小的 Chromium 版本
# 使用微软的 CDN，但只下载必要的文件

CHROMIUM_URL="https://playwright.azureedge.net/builds/chromium/1097/chromium-linux.zip"
INSTALL_DIR="$HOME/.cache/ms-playwright/chromium-1097"

echo "📥 下载轻量版 Chromium (约 50MB)..."
mkdir -p /tmp/chromium-install
cd /tmp/chromium-install

# 使用 curl 分段下载
curl -L -o chromium.zip "$CHROMIUM_URL" --max-time 300 || {
    echo "❌ 下载失败，尝试备用源..."
    exit 1
}

echo "📦 解压..."
unzip -q chromium.zip

echo "📂 安装到 Playwright 目录..."
mkdir -p "$INSTALL_DIR"
mv chrome-linux "$INSTALL_DIR/"

echo "✅ Chromium 安装完成!"
echo "位置: $INSTALL_DIR/chrome-linux/chrome"

# 清理
rm -rf /tmp/chromium-install
