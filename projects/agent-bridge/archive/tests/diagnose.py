#!/usr/bin/env python3
"""
Copilot Bridge 诊断工具
用于分析页面结构，找到正确的选择器
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from playwright.async_api import async_playwright


async def diagnose_copilot():
    """诊断 Copilot 页面结构"""
    print("=" * 70)
    print("Copilot Bridge 诊断工具")
    print("=" * 70)
    
    proxy = os.getenv('HTTP_PROXY') or "http://192.168.6.50:7890"
    
    async with async_playwright() as p:
        # 启动浏览器
        browser = await p.chromium.launch(
            headless=True,
            proxy={"server": proxy} if proxy else None
        )
        
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080}
        )
        
        page = await context.new_page()
        
        # 访问 Copilot
        print("\n[1] 访问 Copilot...")
        await page.goto('https://copilot.microsoft.com/', timeout=60000)
        await asyncio.sleep(3)
        
        # 截图保存
        await page.screenshot(path='diagnose_initial.png')
        print("✅ 初始页面截图: diagnose_initial.png")
        
        # 检查页面标题
        title = await page.title()
        print(f"\n[2] 页面标题: {title}")
        
        # 查找输入框
        print("\n[3] 查找输入框...")
        input_selectors = [
            'textarea#userInput',
            'textarea[placeholder*="Message" i]',
            'textarea[placeholder*="Ask" i]',
            'textarea',
            'input[type="text"]',
            '[contenteditable="true"]',
        ]
        
        for selector in input_selectors:
            try:
                el = await page.query_selector(selector)
                if el:
                    placeholder = await el.get_attribute('placeholder') or ''
                    print(f"  ✅ 找到: {selector}")
                    print(f"     placeholder: {placeholder[:50]}")
                    break
            except:
                pass
        
        # 发送测试消息
        print("\n[4] 发送测试消息...")
        try:
            input_box = await page.wait_for_selector('textarea', timeout=5000)
            await input_box.click()
            await input_box.fill("你好")
            await input_box.press('Enter')
            print("✅ 消息已发送")
        except Exception as e:
            print(f"❌ 发送失败: {e}")
        
        # 等待回复生成
        print("\n[5] 等待回复生成（15秒）...")
        await asyncio.sleep(15)
        
        # 截图
        await page.screenshot(path='diagnose_after_reply.png')
        print("✅ 回复后截图: diagnose_after_reply.png")
        
        # 分析页面结构
        print("\n[6] 分析回复元素...")
        
        # 获取所有可能的回复容器
        response_selectors = [
            '[data-testid*="message" i]',
            '[data-testid*="chat" i]',
            '[class*="message" i]',
            '[class*="response" i]',
            '[class*="assistant" i]',
            '[class*="bot" i]',
            '.ac-textBlock',
            '[role="log"] > div',
        ]
        
        print("\n  可能的回复元素:")
        for selector in response_selectors:
            try:
                elements = await page.query_selector_all(selector)
                if elements:
                    print(f"\n  选择器: {selector}")
                    print(f"  找到 {len(elements)} 个元素")
                    
                    # 显示前3个元素的文本
                    for i, el in enumerate(elements[:3]):
                        try:
                            text = await el.inner_text()
                            text = text.strip()[:100].replace('\n', ' ')
                            print(f"    [{i+1}] {text}...")
                        except:
                            pass
            except:
                pass
        
        # 保存HTML用于分析
        html = await page.content()
        with open('diagnose_page.html', 'w', encoding='utf-8') as f:
            f.write(html)
        print("\n✅ 页面HTML已保存: diagnose_page.html")
        
        # 检查是否有登录提示
        print("\n[7] 检查登录状态...")
        login_indicators = [
            'text=Sign in',
            'text=登录',
            'text=Sign up',
            '[class*="login" i]',
            '[class*="auth" i]',
        ]
        
        has_login_prompt = False
        for indicator in login_indicators:
            try:
                el = await page.query_selector(indicator)
                if el:
                    print(f"  ⚠️ 发现登录相关元素: {indicator}")
                    has_login_prompt = True
            except:
                pass
        
        if not has_login_prompt:
            print("  ✅ 未发现登录提示")
        
        await browser.close()
        
        print("\n" + "=" * 70)
        print("诊断完成!")
        print("=" * 70)
        print("\n请检查以下文件:")
        print("  - diagnose_initial.png (初始页面)")
        print("  - diagnose_after_reply.png (回复后页面)")
        print("  - diagnose_page.html (页面源码)")


if __name__ == "__main__":
    asyncio.run(diagnose_copilot())
