#!/usr/bin/env python3
"""
使用 Cookies 测试 Copilot 登录 - 修复版
"""
import asyncio
import json
from playwright.async_api import async_playwright

def fix_cookies(cookies):
    """修复 cookies 格式以适配 Playwright"""
    fixed = []
    for cookie in cookies:
        # 修复 sameSite 值 - Playwright 只接受 Strict/Lax/None
        same_site = cookie.get('sameSite', 'Lax')
        if same_site == 'no_restriction':
            same_site = 'None'
        elif same_site == 'unspecified':
            same_site = 'Lax'
        elif same_site not in ['Strict', 'Lax', 'None']:
            same_site = 'Lax'  # 默认使用 Lax
        
        # 确保 expires 是整数
        expires = cookie.get('expirationDate', -1)
        if expires and expires != -1:
            expires = int(expires)
        else:
            expires = -1
        
        # 构建标准 cookie 对象
        fixed_cookie = {
            'name': cookie['name'],
            'value': cookie['value'],
            'domain': cookie['domain'],
            'path': cookie.get('path', '/'),
            'expires': expires,
            'httpOnly': cookie.get('httpOnly', False),
            'secure': cookie.get('secure', True),
            'sameSite': same_site
        }
        fixed.append(fixed_cookie)
    return fixed

async def test_with_cookies():
    print("=" * 60)
    print("Copilot Cookie 登录测试")
    print("=" * 60)
    
    proxy = "http://192.168.6.50:7890"
    
    # 加载并修复 cookies
    with open('data/cookies/copilot_cookies.json', 'r') as f:
        raw_cookies = json.load(f)
    
    cookies = fix_cookies(raw_cookies)
    print(f"\n[1] 加载了 {len(cookies)} 个 cookies")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            proxy={"server": proxy}
        )
        
        context = await browser.new_context(
            locale='en-US',
            timezone_id='America/Los_Angeles'
        )
        
        # 添加 cookies
        try:
            await context.add_cookies(cookies)
            print("[2] Cookies 已加载到浏览器")
        except Exception as e:
            print(f"⚠️ 加载 cookies 出错: {e}")
            print("继续测试...")
        
        page = await context.new_page()
        
        print("[3] 访问 Copilot...")
        await page.goto('https://copilot.microsoft.com/', timeout=60000)
        await asyncio.sleep(10)
        
        html = await page.content()
        
        # 检查状态
        if "not yet available" in html:
            print("❌ 仍然显示地区限制")
            await browser.close()
            return False
        
        if "sign in" in html.lower() or "login" in html.lower():
            print("⚠️ 仍需要登录，cookies 可能已过期或无效")
            await page.screenshot(path='copilot_cookie_login.png')
            print("截图已保存: copilot_cookie_login.png")
            await browser.close()
            return False
        
        # 检查是否已登录
        if "userInput" in html or "Message Copilot" in html or "composer" in html:
            print("✅ 已成功登录 Copilot！")
            
            # 尝试发送消息
            try:
                input_box = await page.wait_for_selector('textarea, [contenteditable="true"]', timeout=10000)
                if input_box:
                    print("✅ 找到输入框，发送测试消息...")
                    await input_box.fill("Hello Copilot! What can you do?")
                    await input_box.press('Enter')
                    
                    # 等待回复
                    print("等待回复生成...")
                    await asyncio.sleep(30)
                    
                    # 尝试获取回复
                    print("\n尝试获取回复内容...")
                    
                    # 获取页面所有文本
                    all_texts = await page.eval_on_selector_all('*', 
                        'elements => elements.map(e => e.innerText).filter(t => t && t.length > 100 && t.length < 10000)')
                    
                    for text in all_texts:
                        text = text.strip()
                        if len(text) > 100 and "Message Copilot" not in text and "Hello Copilot" not in text and "test" not in text.lower():
                            print(f"\n🎉 找到可能的回复！")
                            print(f"长度: {len(text)} 字符")
                            print(f"内容: {text[:800]}...")
                            await browser.close()
                            return True
                    
                    print("\n⚠️ 未找到明确回复，保存调试信息...")
                    await page.screenshot(path='copilot_with_cookie.png')
                    html_content = await page.content()
                    with open('copilot_response_debug.html', 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    print("调试文件已保存")
                    
            except Exception as e:
                print(f"⚠️ 交互出错: {e}")
                import traceback
                traceback.print_exc()
                await page.screenshot(path='copilot_cookie_error.png')
        else:
            print("⚠️ 未知页面状态，保存截图...")
            await page.screenshot(path='copilot_unknown_state.png')
        
        await browser.close()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_with_cookies())
    if result:
        print("\n" + "=" * 60)
        print("✅ 测试成功！成功获取 Copilot 回复")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("❌ 测试未完成，请检查截图和调试文件")
        print("=" * 60)
