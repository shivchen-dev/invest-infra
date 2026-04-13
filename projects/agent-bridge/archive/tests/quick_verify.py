#!/usr/bin/env python3
"""
快速验证测试 - 检查Copilot是否可访问
"""
import asyncio
from playwright.async_api import async_playwright

async def quick_test():
    print("=" * 60)
    print("Copilot 快速验证测试")
    print("=" * 60)
    
    proxy = "http://192.168.6.50:7890"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            proxy={"server": proxy}
        )
        context = await browser.new_context(
            locale='en-US',
            timezone_id='America/Los_Angeles'
        )
        page = await context.new_page()
        
        print("\n[1] 访问 Copilot...")
        await page.goto('https://copilot.microsoft.com/', timeout=60000)
        await asyncio.sleep(5)
        
        html = await page.content()
        
        # 检查是否地区限制
        if "not yet available" in html:
            print("❌ 仍然显示地区限制")
            await browser.close()
            return False
        
        # 检查是否加载聊天界面
        if "Message Copilot" in html or "userInput" in html or "composer" in html:
            print("✅ Copilot 聊天界面已加载！")
            
            # 尝试找到输入框
            try:
                input_box = await page.wait_for_selector('textarea[placeholder*="Message"], textarea[placeholder*="Ask"], #userInput', timeout=5000)
                if input_box:
                    print("✅ 找到输入框")
                    
                    # 发送测试消息
                    await input_box.fill("Hello, can you hear me?")
                    await input_box.press('Enter')
                    print("✅ 消息已发送，等待回复...")
                    
                    # 等待回复
                    await asyncio.sleep(15)
                    
                    # 检查回复
                    # 尝试多种选择器
                    selectors = [
                        '[data-testid*="message"]',
                        '[class*="assistant"]',
                        '.ac-textBlock',
                        '[class*="response"]'
                    ]
                    
                    for selector in selectors:
                        elements = await page.query_selector_all(selector)
                        if elements:
                            for el in elements[-3:]:  # 最后3个元素
                                text = await el.inner_text()
                                if text and len(text) > 50 and "Message Copilot" not in text:
                                    print(f"\n🎉 成功获取回复！")
                                    print(f"回复长度: {len(text)} 字符")
                                    print(f"回复内容: {text[:300]}...")
                                    await browser.close()
                                    return True
                    
                    print("\n⚠️ 可能已回复但未找到内容，保存截图...")
                    await page.screenshot(path='copilot_success_test.png')
                    
            except Exception as e:
                print(f"⚠️ 交互测试出错: {e}")
                await page.screenshot(path='copilot_error_test.png')
        else:
            print("⚠️ 未知页面状态，保存截图...")
            await page.screenshot(path='copilot_unknown.png')
        
        await browser.close()
        return False

if __name__ == "__main__":
    result = asyncio.run(quick_test())
    if result:
        print("\n" + "=" * 60)
        print("✅ 测试成功！Copilot 可以正常获取回复")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("❌ 测试未完成，请检查截图")
        print("=" * 60)
