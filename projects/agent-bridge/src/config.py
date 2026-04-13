#!/usr/bin/env python3
"""
Agent Bridge 配置文件
集中管理所有常量配置
"""

# 显示配置
VNC_ADDRESS = "172.22.224.123:5900"
DEFAULT_VIEWPORT = {"width": 1920, "height": 1080}

# 超时配置（秒）
TIMEOUTS = {
    "page_load": 60,
    "element_wait": 10,
    "login_wait": 10,
    "response_wait": {
        "min": 20,
        "max": 30,
    },
    "login_check": 120,
}

# 人类行为模拟延迟（秒）
HUMAN_BEHAVIOR = {
    "click_delay": {"min": 0.3, "max": 0.8},
    "typing_speed": {"min": 0.05, "max": 0.2},
    "think_delay": {"min": 0.5, "max": 1.5},
    "response_wait": {"min": 20, "max": 30},
}

# 浏览器启动参数
BROWSER_ARGS = [
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--window-size=1920,1080',
]

# 平台特定配置
PLATFORM_CONFIGS = {
    "deepseek": {
        "url": "https://chat.deepseek.com/",
        "user_data_dir": "data/browser_profile_deepseek",
        "new_chat_button": "开启新对话",
        "login_indicator": "登录",
    },
    "copilot": {
        "url": "https://copilot.microsoft.com/",
        "user_data_dir": "data/browser_profile_copilot",
    },
}
