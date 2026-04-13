#!/usr/bin/env python3
"""
Copilot Bridge v4.0 - Stealth 反检测版
使用 playwright-stealth 绕过检测
"""
import asyncio
import random
import json
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

async def test_stealth():
    """使用 stealth 插件测试"""
    print("=" * 60)
    print("Copilot v4.0 - Stealth 反检测测试")
    print("=" * 60)
    
    proxy = "http://192.168.6.50:7890"
    
    # 加载 cookies
    with open('data/cookies/copilot_cookies.json', 'r') as f:
        raw_cookies = json.load(f)
    
    async with async_playwright() as p:
        print("\n[1] 启动浏览器（Stealth 模式）...")
        
        browser = await p.chromium.launch(
            headless=True,
            proxy={"server": proxy},
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--window-size=1920,1080',
            ]
        )
        
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            locale='en-US',
            timezone_id='America/Los_Angeles',
        )
        
        # 修复并添加 cookies
        try:
            fixed_cookies = []
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
                
                fixed_cookies.append({
                    'name': cookie['name'],
                    'value': cookie['value'],
                    'domain': cookie['domain'],
                    'path': cookie.get('path', '/'),
                    'expires': expires,
                    'httpOnly': cookie.get('httpOnly', False),
                    'secure': cookie.get('secure', True),
                    'sameSite': same_site
                })
            
            await context.add_cookies(fixed_cookies)
            print("✅ Cookies 已加载")
        except Exception as e:
            print(f"⚠️ Cookies 加载问题: {e}")
        
        page = await context.new_page()
        
        # 启用 stealth
        stealth = Stealth()
        await stealth.apply_stealth_async(page)
        print("✅ Stealth 模式已启用")
        
        # 等待
        await asyncio.sleep(random.uniform(3, 6))
        
        print("\n[2] 访问 Copilot...")
        await page.goto('https://copilot.microsoft.com/', wait_until='domcontentloaded')
        await asyncio.sleep(random.uniform(10, 15))
        
        # 检查状态
        html = await page.content()
        
        if "not yet available" in html:
            print("❌ 地区限制")
            await browser.close()
            return False
        
        if "Verify you are human" in html:
            print("⚠️ 仍然出现人机验证")
            await page.screenshot(path='stealth_captcha.png')
            print("截图已保存: stealth_captcha.png")
            await browser.close()
            return False
        
        if "Message Copilot" in html:
            print("✅ 界面加载成功！")
            
            # 尝试发送消息
            try:
                input_box = await page.wait_for_selector('textarea', timeout=10000)
                
                # 自然输入
                await input_box.click()
                await asyncio.sleep(random.uniform(0.5, 1.5))
                
                msg = "Hello Copilot! Can you tell me how to avoid bot detection?"
                for char in msg:
                    await input_box.type(char)
                    await asyncio.sleep(random.uniform(0.05, 0.15))
                
                await asyncio.sleep(random.uniform(0.5, 1))
                await input_box.press('Enter')
                
                print("✅ 消息已发送，等待回复...")
                await asyncio.sleep(30)
                
                # 截图
                await page.screenshot(path='stealth_result.png')
                print("✅ 截图已保存: stealth_result.png")
                
                # 检查是否有人机验证
                html_after = await page.content()
                if "Verify you are human" in html_after:
                    print("❌ 发送后出现人机验证")
                else:
                    print("✅ 可能已获取回复！")
                    # 获取文本
                    texts = await page.eval_on_selector_all('*', 
                        'els => els.map(e => e.innerText).filter(t => t && t.length > 100)')
                    for t in texts[:3]:
                        if len(t) > 100 and "Message Copilot" not in t and "avoid bot detection" not in t:
                            print(f"\n🎉 找到回复:\n{t[:500]}")
                            await browser.close()
                            return True
                
            except Exception as e:
                print(f"❌ 发送失败: {e}")
        else:
            print("⚠️ 未知状态")
            await page.screenshot(path='stealth_unknown.png')
        
        await browser.close()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_stealth())
    
    print("\n" + "=" * 60)
    if result:
        print("✅ 成功！")
        print("\n下一步：问 Copilot 如何规避反自动化验证")
    else:
        print("❌ 未成功")
        print("\n建议：")
        print("1. 手动通过验证后更新 cookies")
        print("2. 等待一段时间再试")
        print("3. 考虑使用其他地区的代理节点")
    print("=" * 60)
