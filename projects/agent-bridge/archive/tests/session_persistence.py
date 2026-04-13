#!/usr/bin/env python3
"""
Copilot Bridge - 持久化会话方案
合规设计：用户手动登录，保存会话，后续复用
"""
import asyncio
import json
import os
from playwright.async_api import async_playwright, TimeoutError

COOKIE_FILE = "data/cookies/copilot_session.json"
COPILOT_URL = "https://copilot.microsoft.com/"

async def save_cookies(context):
    """保存 cookies 到文件"""
    cookies = await context.cookies()
    # 确保目录存在
    os.makedirs(os.path.dirname(COOKIE_FILE), exist_ok=True)
    with open(COOKIE_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2)
    print(f"✅ Cookies 已保存到 {COOKIE_FILE}")

async def load_cookies(context):
    """从文件加载 cookies"""
    if not os.path.exists(COOKIE_FILE):
        return False

    with open(COOKIE_FILE, "r", encoding="utf-8") as f:
        cookies = json.load(f)

    try:
        await context.add_cookies(cookies)
        print("✅ Cookies 已加载")
        return True
    except Exception as e:
        print("⚠️ Cookies 加载失败：", e)
        return False

async def ensure_login(page, context):
    """确保已登录 Copilot"""
    print("🔍 检查是否已登录 Copilot...")

    try:
        # Copilot 登录后会显示输入框
        await page.wait_for_selector("textarea", timeout=8000)
        print("🎉 已检测到登录状态")
        return True
    except TimeoutError:
        print("⚠️ 未检测到登录，需要手动登录")
        pass

    print("=" * 60)
    print("👉 请在打开的浏览器中手动完成登录")
    print("👉 登录成功后，我会自动保存 Cookie")
    print("=" * 60)

    # 等待用户登录成功
    await page.wait_for_selector("textarea", timeout=0)

    # 登录成功后保存 Cookie
    await save_cookies(context)
    return True

async def main():
    async with async_playwright() as p:
        # 启动 Xvfb
        import subprocess
        import time
        result = subprocess.run(['pgrep', '-f', 'Xvfb :99'], capture_output=True, text=True)
        if result.returncode != 0:
            subprocess.Popen([
                'Xvfb', ':99', '-screen', '0', '1920x1080x24',
                '-ac', '+extension', 'RANDR', '-noreset'
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
        os.environ['DISPLAY'] = ':99'
        
        # 有头模式（配合 Xvfb）
        proxy = "http://192.168.6.50:7890"
        browser = await p.chromium.launch(
            headless=False,
            proxy={"server": proxy},
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080}
        )

        # 1. 尝试加载 Cookie
        cookies_loaded = await load_cookies(context)

        page = await context.new_page()

        # 2. 打开 Copilot
        print("🌐 打开 Copilot...")
        await page.goto(COPILOT_URL)
        await page.wait_for_load_state("networkidle")

        # 3. 确保已登录
        await ensure_login(page, context)

        print("\n" + "=" * 60)
        print("🎉 Copilot 登录完成，可以开始对话了！")
        print("=" * 60)

        # 保持浏览器不退出
        print("\n💡 提示：你可以在此浏览器中正常对话")
        print("   关闭后，下次会自动加载此会话")
        await asyncio.sleep(999999)


if __name__ == "__main__":
    asyncio.run(main())
