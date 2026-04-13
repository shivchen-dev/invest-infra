#!/usr/bin/env python3
"""
Copilot Bridge 工具函数模块
存放公共工具函数，避免代码重复
"""
import json
import subprocess
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

# 默认配置
DEFAULT_PROXY = "http://192.168.6.50:7890"
DEFAULT_VIEWPORT = {"width": 1920, "height": 1080}
USER_DATA_DIR = "data/browser_profile"
COOKIES_PATH = "data/cookies/copilot_cookies_v3.json"
SCREENSHOTS_DIR = "data/screenshots"


def get_proxy() -> str:
    """获取代理地址（优先环境变量，其次默认值）"""
    return os.getenv('HTTP_PROXY') or os.getenv('http_proxy') or DEFAULT_PROXY


def start_xvfb(display: str = ":99") -> bool:
    """
    启动 Xvfb 虚拟桌面
    
    Args:
        display: 显示编号，默认 :99
    
    Returns:
        bool: 是否成功启动
    """
    try:
        result = subprocess.run(
            ['pgrep', '-f', f'Xvfb {display}'],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            subprocess.Popen([
                'Xvfb', display, '-screen', '0', '1920x1080x24',
                '-ac', '+extension', 'RANDR', '-noreset'
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            import time
            time.sleep(2)
        os.environ['DISPLAY'] = display
        return True
    except Exception as e:
        print(f"❌ Xvfb 启动失败: {e}")
        return False


def stop_xvfb(xvfb_process=None) -> None:
    """关闭 Xvfb 虚拟桌面"""
    if xvfb_process:
        xvfb_process.terminate()
        try:
            xvfb_process.wait(timeout=5)
            print("[Xvfb] 已关闭")
        except:
            xvfb_process.kill()
            print("[Xvfb] 被强制关闭")


def fix_cookies(raw_cookies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    修复 cookies 格式，确保符合 Playwright 要求
    
    Args:
        raw_cookies: 原始 cookies 列表
    
    Returns:
        修复后的 cookies 列表
    """
    fixed = []
    for cookie in raw_cookies:
        same_site = cookie.get('sameSite', 'Lax')
        if same_site == 'no_restriction':
            same_site = 'None'
        elif same_site == 'unspecified':
            same_site = 'Lax'
        elif same_site not in ['Strict', 'Lax', 'None']:
            same_site = 'Lax'
        
        expires = cookie.get('expirationDate', -1)
        if expires and expires != -1:
            expires = int(expires)
        else:
            expires = -1
        
        fixed.append({
            'name': cookie['name'],
            'value': cookie['value'],
            'domain': cookie['domain'],
            'path': cookie.get('path', '/'),
            'expires': expires,
            'httpOnly': cookie.get('httpOnly', False),
            'secure': cookie.get('secure', True),
            'sameSite': same_site
        })
    return fixed


def load_cookies(cookie_path: str = None) -> List[Dict[str, Any]]:
    """
    从文件加载并修复 cookies
    
    Args:
        cookie_path: cookies 文件路径，默认使用 COOKIES_PATH
    
    Returns:
        修复后的 cookies 列表
    """
    path = cookie_path or COOKIES_PATH
    try:
        with open(path, 'r') as f:
            raw_cookies = json.load(f)
        return fix_cookies(raw_cookies)
    except FileNotFoundError:
        print(f"⚠️ Cookies 文件不存在: {path}")
        return []
    except json.JSONDecodeError as e:
        print(f"❌ Cookies 文件解析失败: {e}")
        return []


def ensure_dir(path: str) -> str:
    """确保目录存在，不存在则创建"""
    os.makedirs(path, exist_ok=True)
    return path


def get_screenshot_path(filename: str) -> str:
    """获取截图完整路径"""
    ensure_dir(SCREENSHOTS_DIR)
    return os.path.join(SCREENSHOTS_DIR, filename)


# Copilot 页面选择器配置
SELECTORS = {
    "input_box": [
        'textarea#userInput',
        'textarea[placeholder*="Message Copilot" i]',
        'textarea[placeholder*="message" i]',
        'textarea[id*="input" i]',
        'textarea',
    ],
    "send_button": [
        'button[type="submit"]',
        'button[aria-label*="发送" i]',
        'button[aria-label*="Send" i]',
        'button:has-text("发送")',
        'button:has-text("Send")',
    ],
    "response_area": [
        '[class*="message-list" i]',
        '[class*="conversation" i]',
        '[class*="chat" i]',
        '[role="log"]',
        '[class*="ac-textBlock"]',
    ],
    "message": [
        '[class*="message" i][class*="bot" i]',
        '[class*="assistant" i]',
        '[class*="response" i]',
        '.ac-textBlock',
        '[class*="markdown" i]',
    ],
    "stop_button": [
        'button[aria-label*="停止" i]',
        'button[aria-label*="Stop" i]',
        'button:has-text("停止生成")',
        'button:has-text("Stop generating")',
    ],
    "welcome_button": [
        'button:has-text("开始使用")',
        'button:has-text("Get started")',
        'button:has-text("开始")',
        'button:has-text("Start")',
    ],
    "new_chat": [
        'button[aria-label="New chat"]',
        'button:has-text("New chat")',
        'button:has-text("New Chat")',
        '[data-testid="new-chat-button"]',
    ],
    "modal_close": [
        'button[aria-label*="关闭" i]',
        'button[aria-label*="Close" i]',
        'button:has-text("关闭")',
        'button:has-text("Close")',
        'button:has-text("知道了")',
        'button:has-text("Got it")',
        'button:has-text("同意")',
        'button:has-text("Accept")',
        '[class*="modal"] button',
        '[class*="dialog"] button',
        '[class*="overlay"] button',
    ],
}


def get_selector(key: str) -> List[str]:
    """获取选择器列表"""
    return SELECTORS.get(key, [])


# 浏览器启动参数
BROWSER_ARGS = [
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-dev-shm-usage',
    '--disable-blink-features=AutomationControlled',
    '--disable-web-security',
    '--disable-features=IsolateOrigins,site-per-process',
    '--window-size=1920,1080',
    '--start-maximized',
]


def get_browser_args(extra_args: List[str] = None) -> List[str]:
    """获取浏览器启动参数"""
    args = BROWSER_ARGS.copy()
    if extra_args:
        args.extend(extra_args)
    return args


# 反检测脚本
ANTIDETECT_SCRIPT = """
// 隐藏 webdriver 标志
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});

// 伪装 plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        {name: 'Chrome PDF Plugin'},
        {name: 'Chrome PDF Viewer'},
        {name: 'Native Client'}
    ]
});

// 伪装 languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en']
});

// 覆盖权限查询
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' 
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters)
);
"""


def find_system_chromium() -> Optional[str]:
    """查找系统安装的 Chromium"""
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
                capture_output=True, text=True, check=True
            )
            return result.stdout.strip()
        except:
            continue
    
    return None
