#!/usr/bin/env python3
"""
检查 DeepSeek 登录状态 - 使用 HTML 检测
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from playwright.async_api import async_playwright
from utils import start_xvfb
import os

USER_DATA_DIR = "data/browser_profile_deepseek"

async def check_login():
    print("="*70)
    print("检查 DeepSeek 登录状态")
    print("="*70)
    
    if not start_xvfb():
        print("❌ Xvfb 启动失败")
        return
    
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    
    p = await async_playwright().start()
    
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
    
    page = await context.new_page()
    
    print("\n[1] 访问 DeepSeek...")
    await page.goto('https://chat.deepseek.com/', timeout=60000)
    await asyncio.sleep(5)
    
    # 检查登录状态
    print("\n[2] 检查登录状态...")
    html = await page.content()
    
    # 检测关键词
    login_keywords = ['登录', '扫码', '手机号', '请登录']
    logged_in_keywords = ['开启新对话', '深度思考', '智能搜索', '有什么可以帮到你']
    
    found_login = [kw for kw in login_keywords if kw in html]
    found_logged_in = [kw for kw in logged_in_keywords if kw in html]
    
    print(f"  未登录标志: {found_login}")
    print(f"  已登录标志: {found_logged_in}")
    
    if found_login and not found_logged_in:
        print("\n  ❌ 未登录 - 需要重新扫码")
    elif found_logged_in:
        print("\n  ✅ 已登录")
        
        # 尝试提取话题
        print("\n[3] 尝试提取话题...")
        xpath = 'xpath=//div[contains(text(), "持久化") or contains(text(), "测试") or contains(text(), "qmd")]'
        elements = await page.query_selector_all(xpath)
        print(f"  找到 {len(elements)} 个话题")
        for el in elements[:5]:
            text = await el.inner_text()
            print(f"    - {text[:50]}")
    else:
        print("\n  ⚠️ 状态不确定")
    
    print("\n" + "="*70)
    print("检查完成")
    print("="*70)
    
    await asyncio.sleep(10)
    await context.close()
    await p.stop()

if __name__ == "__main__":
    asyncio.run(check_login())
