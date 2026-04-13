#!/usr/bin/env python3
"""
测试切换到 "qmd工具" 话题
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from playwright.async_api import async_playwright
from utils import start_xvfb
import os

USER_DATA_DIR = "data/browser_profile_deepseek"

async def switch_to_qmd():
    print("="*70)
    print("测试切换到 'qmd工具' 话题")
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
    
    await page.screenshot(path='data/screenshots/switch_qmd_start.png')
    print("✅ 截图: switch_qmd_start.png")
    
    # 先查找 qmd 相关话题
    print("\n[2] 查找 'qmd' 相关话题...")
    html = await page.content()
    
    # 查找包含 qmd 的元素
    xpath = 'xpath=//div[contains(text(), "qmd") or contains(text(), "QMD")]'
    elements = await page.query_selector_all(xpath)
    print(f"  找到 {len(elements)} 个包含 'qmd' 的元素")
    
    for i, el in enumerate(elements[:5]):
        try:
            text = await el.inner_text()
            print(f"    {i+1}. {text[:60]}")
        except:
            pass
    
    # 尝试点击第一个匹配的
    if elements:
        print(f"\n[3] 尝试点击第一个匹配元素...")
        try:
            await elements[0].click()
            await asyncio.sleep(3)
            print("✅ 点击成功")
            await page.screenshot(path='data/screenshots/switch_qmd_after.png')
            print("✅ 截图: switch_qmd_after.png")
        except Exception as e:
            print(f"❌ 点击失败: {e}")
    else:
        print("\n  未找到 'qmd' 相关话题")
        print("  尝试模糊搜索...")
        # 尝试其他可能的写法
        keywords = ['工具', 'QMD', 'qmd工具']
        for kw in keywords:
            xpath = f'xpath=//div[contains(text(), "{kw}")]'
            els = await page.query_selector_all(xpath)
            if els:
                print(f"  找到包含 '{kw}' 的元素:")
                for el in els[:3]:
                    text = await el.inner_text()
                    print(f"    - {text[:50]}")
    
    # 如果上面没找到，尝试获取所有话题
    print("\n[4] 获取所有话题列表...")
    xpath = 'xpath=//div[contains(text(), "持久化") or contains(text(), "测试") or contains(text(), "Agent") or contains(text(), "qmd")]'
    all_topics = await page.query_selector_all(xpath)
    print(f"  找到 {len(all_topics)} 个话题")
    for i, el in enumerate(all_topics[:10]):
        text = await el.inner_text()
        print(f"    {i+1}. {text[:50]}")
    
    print("\n" + "="*70)
    print("测试完成，浏览器保持运行30秒...")
    print("="*70)
    
    await asyncio.sleep(30)
    await context.close()
    await p.stop()

if __name__ == "__main__":
    asyncio.run(switch_to_qmd())
