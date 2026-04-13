#!/usr/bin/env python3
"""
验证 Playwright 代理是否真正生效
"""
import asyncio
import os
from playwright.async_api import async_playwright

async def test_proxy():
    """测试代理是否生效"""
    print("=" * 60)
    print("Playwright 代理验证")
    print("=" * 60)
    
    # 环境变量代理
    env_proxy = os.getenv('HTTP_PROXY')
    print(f"\n[环境变量] HTTP_PROXY={env_proxy}")
    
    # 手动指定代理
    proxy_url = "http://192.168.6.50:7890"
    print(f"[手动指定] proxy={proxy_url}")
    
    async with async_playwright() as p:
        print("\n[测试1] 使用环境变量代理访问 httpbin.org...")
        try:
            browser1 = await p.chromium.launch(
                headless=True,
                proxy={"server": env_proxy} if env_proxy else None
            )
            context1 = await browser1.new_context()
            page1 = await context1.new_page()
            
            await page1.goto('https://httpbin.org/ip', timeout=30000)
            content1 = await page1.content()
            print(f"页面内容: {content1[:500]}")
            
            await browser1.close()
        except Exception as e:
            print(f"❌ 失败: {e}")
        
        print("\n[测试2] 使用手动代理访问 httpbin.org...")
        try:
            browser2 = await p.chromium.launch(
                headless=True,
                proxy={"server": proxy_url}
            )
            context2 = await browser2.new_context()
            page2 = await context2.new_page()
            
            await page2.goto('https://httpbin.org/ip', timeout=30000)
            content2 = await page2.content()
            print(f"页面内容: {content2[:500]}")
            
            await browser2.close()
        except Exception as e:
            print(f"❌ 失败: {e}")
        
        print("\n[测试3] 访问 Copilot 检查地区...")
        try:
            browser3 = await p.chromium.launch(
                headless=True,
                proxy={"server": proxy_url}
            )
            context3 = await browser3.new_context()
            page3 = await context3.new_page()
            
            await page3.goto('https://copilot.microsoft.com/', timeout=60000)
            await asyncio.sleep(3)
            
            # 检查页面内容
            html = await page3.content()
            
            if "not yet available in your region" in html:
                print("❌ Copilot 显示: 该地区不可用")
                print("   代理 IP 所在地区被 Copilot 限制")
            elif "Message Copilot" in html:
                print("✅ 检测到聊天界面加载")
            else:
                print("⚠️ 页面内容未知，保存截图检查...")
                await page3.screenshot(path='proxy_test_copilot.png')
            
            await browser3.close()
        except Exception as e:
            print(f"❌ 失败: {e}")
    
    print("\n" + "=" * 60)
    print("验证完成")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_proxy())
