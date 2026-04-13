#!/usr/bin/env python3
"""
深度诊断工具 - 检查为什么代理切换不生效
同时测试多种方式绕过地区限制
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from playwright.async_api import async_playwright


async def deep_diagnose():
    """深度诊断"""
    print("=" * 70)
    print("深度诊断 - 代理问题分析")
    print("=" * 70)
    
    proxy = "http://192.168.6.50:7890"
    
    async with async_playwright() as p:
        print("\n[测试1] 基础代理测试 - 查看出口IP...")
        browser1 = await p.chromium.launch(
            headless=True,
            proxy={"server": proxy}
        )
        page1 = await browser1.new_page()
        await page1.goto('https://httpbin.org/ip', timeout=30000)
        html1 = await page1.content()
        print(f"出口IP页面: {html1[:500]}")
        await browser1.close()
        
        print("\n[测试2] 伪装locale和timezone...")
        browser2 = await p.chromium.launch(
            headless=True,
            proxy={"server": proxy}
        )
        context2 = await browser2.new_context(
            locale='en-US',
            timezone_id='America/New_York',
            viewport={'width': 1920, 'height': 1080}
        )
        page2 = await context2.new_page()
        await page2.goto('https://copilot.microsoft.com/', timeout=60000)
        await asyncio.sleep(5)
        
        html2 = await page2.content()
        
        if "not yet available" in html2:
            print("❌ 即使伪装locale，仍然显示地区限制")
        elif "Message Copilot" in html2 or "userInput" in html2:
            print("✅ 可以访问聊天界面！")
            # 尝试发送消息
            try:
                await page2.fill('textarea', "Hello")
                await page2.press('textarea', 'Enter')
                await asyncio.sleep(10)
                
                # 获取所有文本内容
                texts = await page2.eval_on_selector_all('*', 'elements => elements.map(e => e.innerText).filter(t => t && t.length > 50)')
                print(f"\n页面长文本内容:")
                for i, text in enumerate(texts[:5]):
                    print(f"[{i+1}] {text[:200]}...")
            except Exception as e:
                print(f"发送消息失败: {e}")
        else:
            print("⚠️ 未知状态，保存截图...")
            await page2.screenshot(path='deep_diagnose_unknown.png')
        
        await browser2.close()
        
        print("\n[测试3] 检查页面中的地区检测机制...")
        browser3 = await p.chromium.launch(
            headless=True,
            proxy={"server": proxy}
        )
        page3 = await browser3.new_page()
        await page3.goto('https://copilot.microsoft.com/', timeout=60000)
        await asyncio.sleep(3)
        
        # 检查localStorage和cookies
        local_storage = await page3.evaluate('() => JSON.stringify(localStorage)')
        cookies = await page3.context().cookies()
        
        print(f"\nLocalStorage: {local_storage[:500] if local_storage else 'None'}")
        print(f"\nCookies数量: {len(cookies)}")
        for cookie in cookies[:5]:
            print(f"  - {cookie['name']}: {cookie['value'][:50] if cookie['value'] else 'None'}")
        
        await browser3.close()
    
    print("\n" + "=" * 70)
    print("诊断完成")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(deep_diagnose())
