#!/usr/bin/env python3
"""
测试话题功能 - 简化版
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from playwright.async_api import async_playwright
from utils import start_xvfb
import os

USER_DATA_DIR = "data/browser_profile_deepseek"

async def test_topics():
    print("="*70)
    print("话题功能测试 - 使用 DeepSeekBridge")
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
    
    # 测试 list_topics
    print("\n[2] 测试 list_topics...")
    topics = []
    
    # 使用 XPath 查找话题
    xpath = '//div[contains(text(), "持久化") or contains(text(), "测试") or contains(text(), "Agent")]'
    elements = await page.query_selector_all(f'xpath={xpath}')
    print(f"  找到 {len(elements)} 个话题元素")
    
    for el in elements:
        text = await el.inner_text()
        print(f"    - {text[:50]}")
        topics.append({"title": text, "is_active": False})
    
    # 测试 switch_topic
    if topics:
        print(f"\n[3] 测试 switch_topic - 切换到: {topics[0]['title']}")
        try:
            xpath = f'xpath=//div[contains(text(), "{topics[0]["title"][:10]}"))]'
            btn = await page.wait_for_selector(xpath, timeout=5000)
            await btn.click()
            await asyncio.sleep(2)
            print("  ✅ 切换成功")
        except Exception as e:
            print(f"  ⚠️ 切换尝试: {e}")
    
    # 测试 new_chat
    print("\n[4] 测试 new_chat - 点击'开启新对话'...")
    try:
        btn = await page.wait_for_selector('text="开启新对话"', timeout=5000)
        await btn.click()
        await asyncio.sleep(3)
        print("  ✅ 新建话题成功")
        await page.screenshot(path='data/screenshots/topic_new_chat.png')
    except Exception as e:
        print(f"  ❌ 失败: {e}")
    
    print("\n" + "="*70)
    print("测试完成")
    print("="*70)
    
    await asyncio.sleep(10)
    await context.close()
    await p.stop()

if __name__ == "__main__":
    asyncio.run(test_topics())
