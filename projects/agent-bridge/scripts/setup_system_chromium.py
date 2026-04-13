#!/usr/bin/env python3
"""
Playwright 使用系统 Chromium 配置
当 playwright install 失败时，使用系统已安装的 Chromium
"""

import subprocess
import os

def find_system_chromium():
    """查找系统 Chromium 路径"""
    paths = [
        "/snap/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
    ]
    
    for path in paths:
        if os.path.exists(path):
            return path
    
    # 尝试 which 命令
    for cmd in ["chromium-browser", "chromium", "google-chrome"]:
        try:
            result = subprocess.run(
                ["which", cmd],
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except:
            continue
    
    return None


def setup_playwright_with_system_chromium():
    """配置 Playwright 使用系统 Chromium"""
    chromium_path = find_system_chromium()
    
    if not chromium_path:
        print("❌ 未找到系统 Chromium")
        return None
    
    print(f"✅ 找到 Chromium: {chromium_path}")
    
    # 方式1: 设置环境变量
    os.environ["PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"] = chromium_path
    
    print(f"\n设置环境变量:")
    print(f"export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH={chromium_path}")
    
    return chromium_path


if __name__ == "__main__":
    path = setup_playwright_with_system_chromium()
    if path:
        print(f"\n使用方式:")
        print(f"export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH={path}")
        print(f"\n或在 Python 中:")
        print(f'os.environ["PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"] = "{path}"')
