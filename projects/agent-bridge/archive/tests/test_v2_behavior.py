#!/usr/bin/env python3
"""
Copilot Bridge v2.0 测试 - 人类行为模拟
"""
import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from human_behavior_v2 import HumanBehaviorSimulator, test_human_behavior
from utils import (
    start_xvfb, load_cookies, get_proxy,
    get_browser_args, get_screenshot_path, SELECTORS,
    ANTIDETECT_SCRIPT
)


async def test_v2():
    print("=" * 70)
    print("Copilot Bridge v2.0 - 人类行为模拟测试")
    print("=" * 70)
    
    if not start_xvfb():
        return False
    
    cookies = load_cookies()
    if not cookies:
        print("❌ 无法加载 cookies")
        return False
    
    async with async_playwright() as p:
        print("\n[1] 启动浏览器...")
        
        browser = await p.chromium.launch(
            headless=False,
            proxy={"server": get_proxy()},
            args=get_browser_args([
                '--disable-blink-features=AutomationControlled',
            ]),
        )
        
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            locale='en-US',
        )
        
        await context.add_init_script(ANTIDETECT_SCRIPT)
        await context.add_cookies(cookies)
        
        page = await context.new_page()
        simulator = HumanBehaviorSimulator(page)
        
        print("\n[2] 访问 Copilot...")
        await page.goto('https://copilot.microsoft.com/', timeout=60000)
        await simulator.random_delay(8, 12)
        await simulator.random_browsing()
        
        await page.screenshot(path=get_screenshot_path('v2_test.png'))
        
        html = await page.content()
        if "not yet available" in html:
            print("❌ 地区限制")
            await browser.close()
            return False
        
        if "Message Copilot" not in html:
            print("⚠️ 页面未正常加载")
            await browser.close()
            return False
        
        print("✅ Copilot 界面已加载！")
        
        # 点击 New chat
        for selector in SELECTORS["new_chat"]:
            try:
                btn = await page.wait_for_selector(selector, timeout=5000)
                if btn:
                    await simulator.natural_click(selector)
                    print("✅ 已点击 New chat")
                    await asyncio.sleep(3)
                    break
            except:
                continue
        
        # 发送消息
        print("\n[3] 发送消息...")
        msg = "Hello! How are you today?"
        
        if not await test_human_behavior(page, msg):
            print("❌ 发送失败")
            await browser.close()
            return False
        
        print("\n[4] 等待回复...")
        await simulator.random_delay(20, 30)
        await page.screenshot(path=get_screenshot_path('v2_reply.png'))
        
        # 检查结果
        html_check = await page.content()
        if "Verify you are human" in html_check:
            print("⚠️ 触发人机验证")
            await browser.close()
            return False
        
        print("✅ 测试完成")
        await browser.close()
        return True


if __name__ == "__main__":
    result = asyncio.run(test_v2())
    
    print("\n" + "=" * 70)
    if result:
        print("✅ v2.0 测试成功！")
    else:
        print("❌ v2.0 测试未成功")
    print("=" * 70)
