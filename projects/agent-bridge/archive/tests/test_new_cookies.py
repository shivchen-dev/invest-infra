#!/usr/bin/env python3
"""
使用新 Cookies 测试 - 应该已绕过验证
"""
import asyncio
import json
from playwright.async_api import async_playwright

def fix_cookies(cookies):
    """修复 cookies 格式"""
    fixed = []
    for cookie in cookies:
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
        
        fixed.append({
            'name': cookie['name'],
            'value': cookie['value'],
            'domain': cookie['domain'],
            'path': cookie.get('path', '/'),
            'expires': expires,
            'httpOnly': cookie.get('httpOnly', False),
            'secure': cookie.get('secure', True),
            'sameSite': same_site
        })
    return fixed

async def test_with_new_cookies():
    print("=" * 70)
    print("使用新 Cookies 测试（已通过验证）")
    print("=" * 70)
    
    proxy = "http://192.168.6.50:7890"
    
    # 加载新 cookies
    with open('data/cookies/copilot_cookies_v2.json', 'r') as f:
        raw_cookies = json.load(f)
    cookies = fix_cookies(raw_cookies)
    print(f"\n[1] 加载了 {len(cookies)} 个新 cookies")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            proxy={"server": proxy},
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--window-size=1920,1080',
            ]
        )
        
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            locale='en-US',
            timezone_id='America/Los_Angeles',
        )
        
        await context.add_cookies(cookies)
        print("[2] 新 cookies 已加载")
        
        page = await context.new_page()
        
        print("\n[3] 访问 Copilot...")
        await page.goto('https://copilot.microsoft.com/', timeout=60000)
        await asyncio.sleep(8)
        
        html = await page.content()
        await page.screenshot(path='new_cookie_test.png')
        
        # 检查状态
        if "not yet available" in html:
            print("❌ 地区限制")
            await browser.close()
            return False
        
        if "Verify you are human" in html:
            print("❌ 仍然出现人机验证")
            await browser.close()
            return False
        
        if "Message Copilot" in html or "Hey, nice to see you" in html:
            print("✅ Copilot 界面已加载！")
            
            # 发送消息
            try:
                input_box = await page.wait_for_selector('textarea', timeout=10000)
                
                msg = "Hello Copilot! Can you tell me how to better avoid bot detection systems?"
                await input_box.fill(msg)
                await input_box.press('Enter')
                
                print("✅ 消息已发送")
                print("[4] 等待回复...")
                await asyncio.sleep(30)
                
                # 截图
                await page.screenshot(path='new_cookie_reply.png')
                
                # 获取回复
                html_after = await page.content()
                
                # 查找回复
                all_texts = await page.eval_on_selector_all('*', 
                    'els => els.map(e => e.innerText).filter(t => t && t.length > 100 && t.length < 5000)')
                
                for text in all_texts:
                    text = text.strip()
                    if (len(text) > 100 and 
                        "Message Copilot" not in text and 
                        "Hey, nice to see you" not in text and
                        "avoid bot detection" not in text.lower()):
                        print(f"\n" + "=" * 70)
                        print("🎉 成功获取 Copilot 回复！")
                        print("=" * 70)
                        print(f"\n问题: 如何更好地规避反自动化验证？")
                        print(f"\nCopilot 回复:\n{text[:1000]}")
                        print("\n" + "=" * 70)
                        await browser.close()
                        return True
                
                print("\n⚠️ 未找到明确回复，但可能已发送成功")
                print("请检查截图: new_cookie_reply.png")
                
            except Exception as e:
                print(f"❌ 发送失败: {e}")
        
        await browser.close()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_with_new_cookies())
    if result:
        print("\n✅ 测试成功！获取到 Copilot 回复")
    else:
        print("\n❌ 测试未完成")
