#!/usr/bin/env python3
"""
快速测试话题功能 - 简化版
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from playwright.async_api import async_playwright
from human_behavior_v2 import HumanBehaviorSimulator
from utils import start_xvfb
import os

USER_DATA_DIR = "data/browser_profile_deepseek"

async def test_topics():
    print("="*70)
    print("话题选取功能测试")
    print("="*70)
    
    if not start_xvfb():
        print("❌ Xvfb 启动失败")
        return
    
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    
    print("\n[1] 启动浏览器...")
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
    simulator = HumanBehaviorSimulator(page)
    
    print("[2] 访问 DeepSeek...")
    await page.goto('https://chat.deepseek.com/', timeout=60000)
    await asyncio.sleep(5)
    
    # 截图看页面
    await page.screenshot(path='data/screenshots/topic_test_start.png')
    print("✅ 截图: topic_test_start.png")
    
    # 获取HTML分析话题列表
    html = await page.content()
    
    # 尝试多种选择器找话题
    print("\n[3] 尝试提取话题列表...")
    
    selectors = [
        '[class*="conversation"]',
        '[class*="chat-item"]',
        '[class*="session"]',
        '[class*="history"]',
        '[class*="chat-list"]',
        'div[role="button"]',
        '[class*="sidebar"] div',
        '[class*="menu"]',
    ]
    
    found_topics = []
    for selector in selectors:
        try:
            elements = await page.query_selector_all(selector)
            print(f"  {selector}: 找到 {len(elements)} 个元素")
            
            for i, el in enumerate(elements[:5]):
                try:
                    text = await el.inner_text()
                    if text and len(text) > 0 and len(text) < 200:
                        print(f"    - {text[:50]}")
                        found_topics.append({"selector": selector, "text": text[:100]})
                except:
                    pass
                    
        except Exception as e:
            print(f"  {selector}: 失败 - {e}")
    
    print(f"\n[4] 共找到 {len(found_topics)} 个可能的话题")
    
    # 保存HTML供分析
    with open('data/screenshots/topic_test_inspect.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print("✅ HTML已保存: topic_test_inspect.html")
    
    print("\n" + "="*70)
    print("测试完成")
    print("="*70)
    
    print("\n浏览器保持运行30秒...")
    await asyncio.sleep(30)
    
    await context.close()
    await p.stop()

if __name__ == "__main__":
    asyncio.run(test_topics())
