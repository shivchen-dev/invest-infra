#!/usr/bin/env python3
"""
验证新 cookies - 快速测试
"""
import asyncio
import json
import os
from playwright.async_api import async_playwright

async def test_new_cookies():
    print("=" * 60)
    print("验证新 Cookies")
    print("=" * 60)
    
    COOKIE_FILE = "data/cookies/copilot_cookies_v2.json"
    
    # 检查文件
    if not os.path.exists(COOKIE_FILE):
        print(f"❌ 找不到文件: {COOKIE_FILE}")
        return False
    
    # 读取并显示信息
    with open(COOKIE_FILE, 'r') as f:
        raw_cookies = json.load(f)
    
    # 修复 cookie 格式
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
    
    print(f"✅ 加载了 {len(cookies)} 个 cookies")
    
    # 显示关键 cookie
    for cookie in cookies:
        name = cookie.get('name', '')
        if name in ['_U', 'MUID', 'MSPRequ', 'MSCC']:
            print(f"  - {name}: {cookie.get('value', '')[:30]}...")
    
    # 启动浏览器测试
    async with async_playwright() as p:
        print("\n启动浏览器...")
        browser = await p.chromium.launch(
            headless=False,
            proxy={"server": "http://192.168.6.50:7890"},
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080}
        )
        
        await context.add_cookies(cookies)
        print("✅ Cookies 已加载到浏览器")
        
        page = await context.new_page()
        
        print("\n访问 Copilot...")
        await page.goto('https://copilot.microsoft.com/', timeout=60000)
        await asyncio.sleep(8)
        
        html = await page.content()
        await page.screenshot(path='new_cookies_test.png')
        print("✅ 截图已保存: new_cookies_test.png")
        
        # 检查结果
        if "not yet available" in html:
            print("❌ 地区限制")
            await browser.close()
            return False
        
        if "Message Copilot" in html or "Hey, nice to see you" in html:
            print("\n🎉 成功！Copilot 已加载")
            
            # 检查是否有人机验证
            if "Verify you are human" in html:
                print("⚠️ 但仍有人机验证")
            else:
                print("✅ 未触发人机验证！")
            
            await browser.close()
            return True
        else:
            print("⚠️ 状态未知")
            print("HTML前500字符:", html[:500])
        
        await browser.close()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_new_cookies())
    
    print("\n" + "=" * 60)
    if result:
        print("✅ 新 cookies 有效！")
    else:
        print("❌ 需要进一步检查")
    print("=" * 60)
