#!/usr/bin/env python3
"""
简化版：启动浏览器 -> 按回车 -> 验证登录
"""
import os
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from playwright.async_api import async_playwright
from utils import get_screenshot_path, start_xvfb

USER_DATA_DIR = "data/browser_profile_deepseek"


async def simple_test():
    """简化测试"""
    print("=" * 70)
    print("简化测试：回车恢复 + 登录验证")
    print("=" * 70)
    print()
    
    if not start_xvfb():
        print("❌ Xvfb 启动失败")
        return
    
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    
    p = await async_playwright().start()
    
    print("启动浏览器...")
    context = await p.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR,
        headless=False,
        args=[
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--window-size=1920,1080',
        ],
        viewport={'width': 1920, 'height': 1080},
        locale='zh-CN',
    )
    
    # 获取页面
    await asyncio.sleep(2)
    pages = context.pages
    page = pages[0] if pages else await context.new_page()
    
    print(f"页面: {page.url}")
    print()
    
    # 按回车
    print("按回车键恢复页面...")
    await page.keyboard.press('Enter')
    await asyncio.sleep(5)
    
    print(f"回车后: {page.url}")
    await page.screenshot(path=get_screenshot_path('after_enter.png'))
    print("截图: after_enter.png")
    print()
    
    # 访问 DeepSeek
    print("访问 DeepSeek...")
    await page.goto('https://chat.deepseek.com/', timeout=60000)
    await asyncio.sleep(5)
    
    # 验证
    html = await page.content()
    is_logged_in = "登录" not in html
    
    await page.screenshot(path=get_screenshot_path('final_check.png'))
    print("截图: final_check.png")
    print()
    
    print("=" * 70)
    print(f"结果: {'✅ 已登录' if is_logged_in else '❌ 未登录'}")
    print("=" * 70)
    
    try:
        while True:
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        pass
    
    await context.close()


if __name__ == "__main__":
    asyncio.run(simple_test())
