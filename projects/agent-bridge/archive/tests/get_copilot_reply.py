#!/usr/bin/env python3
"""
Copilot Bridge - 使用新 cookies 获取回复
"""
import asyncio
import json
import os
from playwright.async_api import async_playwright

COOKIE_FILE = "data/cookies/copilot_cookies_v2.json"

async def human_typing(page, selector, text):
    """自然打字"""
    element = await page.wait_for_selector(selector, timeout=10000)
    await element.click()
    await asyncio.sleep(0.5)
    
    for char in text:
        await element.type(char)
        await asyncio.sleep(0.1)
    
    await asyncio.sleep(0.5)

async def main():
    print("=" * 70)
    print("Copilot Bridge - 获取 AI 回复")
    print("=" * 70)
    
    # 加载并修复 cookies
    with open(COOKIE_FILE, 'r') as f:
        raw_cookies = json.load(f)
    
    cookies = []
    for cookie in raw_cookies:
        same_site = cookie.get('sameSite', 'Lax')
        if same_site == 'no_restriction':
            same_site = 'None'
        elif same_site == 'unspecified':
            same_site = 'Lax'
        elif same_site not in ['Strict', 'Lax', 'None']:
            same_site = 'Lax'
        
        expires = cookie.get('expirationDate', -1)
        if expires and expires != -1:
            expires = int(expires)
        else:
            expires = -1
        
        cookies.append({
            'name': cookie['name'],
            'value': cookie['value'],
            'domain': cookie['domain'],
            'path': cookie.get('path', '/'),
            'expires': expires,
            'httpOnly': cookie.get('httpOnly', False),
            'secure': cookie.get('secure', True),
            'sameSite': same_site
        })
    
    print(f"✅ 加载 {len(cookies)} 个 cookies")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            proxy={"server": "http://192.168.6.50:7890"},
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        
        context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
        await context.add_cookies(cookies)
        
        page = await context.new_page()
        
        print("\n访问 Copilot...")
        await page.goto('https://copilot.microsoft.com/', timeout=60000)
        await asyncio.sleep(5)
        
        # 发送消息
        print("\n发送消息...")
        msg = "Hello Copilot! How can developers make browser automation more stable and reliable?"
        await human_typing(page, 'textarea', msg)
        await page.keyboard.press('Enter')
        
        print("✅ 消息已发送，等待回复...")
        await asyncio.sleep(25)
        
        await page.screenshot(path='copilot_reply.png')
        
        # 获取回复
        html = await page.content()
        
        if "Verify you are human" in html:
            print("⚠️ 触发人机验证")
            await browser.close()
            return False
        
        # 查找回复文本
        texts = await page.eval_on_selector_all('*', 
            'els => els.map(e => e.innerText).filter(t => t && t.length > 100 && t.length < 3000)')
        
        print("\n" + "=" * 70)
        print("🎉 Copilot 回复：")
        print("=" * 70)
        
        for text in texts:
            if (len(text) > 150 and 
                msg not in text and
                "Message Copilot" not in text and
                "Hi there" not in text):
                print(f"\n{text[:800]}")
                print("\n" + "=" * 70)
                await browser.close()
                return True
        
        print("⚠️ 未找到明确回复")
        await browser.close()
        return False

if __name__ == "__main__":
    result = asyncio.run(main())
    
    if result:
        print("\n✅ 成功获取 Copilot 回复！")
    else:
        print("\n❌ 未成功获取回复")
