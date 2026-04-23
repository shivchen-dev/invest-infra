#!/usr/bin/env python3
"""
Agent Bridge 工具函数模块
仅保留被引用的函数，移除所有死代码
"""
import os

SCREENSHOTS_DIR = "data/screenshots"


def ensure_dir(path: str) -> str:
    """确保目录存在，不存在则创建"""
    os.makedirs(path, exist_ok=True)
    return path


def get_screenshot_path(filename: str) -> str:
    """获取截图完整路径"""
    ensure_dir(SCREENSHOTS_DIR)
    return os.path.join(SCREENSHOTS_DIR, filename)
