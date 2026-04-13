#!/usr/bin/env python3
"""
使用有头模式测试 - 配合 Xvfb 模拟真实浏览器
"""
import asyncio
import json
import subprocess
import os
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

def start_xvfb():
    """启动 Xvfb"""
    try:
        result = subprocess.run(['pgrep', '-f', 'Xvfb :99'], 
                              capture_output=True, text=True)
        if result.returncode != 0:
            subprocess.Popen([
                'Xvfb', ':99', '-screen', '0', '1920x1080x24',
                '-ac', '+extension', 'RANDR', '-noreset'
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            import time
            time.sleep(1)
        os.environ['DISPLAY'] = ':99'
        return True
    except Exception as e:
        print(f"Xvfb 启动失败: {e}")
        return False

async def test_headed():
    print("=" * 70)
    print("使用有头模式测试（配合 Xvfb）")
    print("=" * 70)
    
    proxy = "http://192.168.6.50:7890"
    
    # 启动 Xvfb
    if not start_xvfb():
        print("❌ Xvfb 启动失败")
        return False
    
    # 加载 cookies
    with open('data/cookies/copilot_cookies_v2.json', 'r') as f:
        raw_cookies = json.load(f)
    cookies = fix_cookies(raw_cookies)
    
    async with async_playwright() as p:
        print("\n[1] 启动有头浏览器（headless=False）...")
        
        browser = await p.chromium.launch(
            headless=False,  # 关键：有头模式
            proxy={"server": proxy},
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--window-size=1920,1080',
                '--start-maximized',
            ]
        )
        
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            locale='en-US',
            timezone_id='America/Los_Angeles',
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        
        # 添加 cookies
        await context.add_cookies(cookies)
        print("[2] Cookies 已加载")
        
        page = await context.new_page()
        
        print("\n[3] 访问 Copilot（有头模式）...")
        await page.goto('https://copilot.microsoft.com/', timeout=60000)
        await asyncio.sleep(10)  # 等待完全加载
        
        html = await page.content()
        await page.screenshot(path='headed_test.png')
        print("[4] 截图已保存: headed_test.png")
        
        # 检查结果
        if "not yet available" in html:
            print("❌ 仍然显示地区限制")
            
            # 检查是否有其他信息
            if "Message Copilot" in html:
                print("⚠️ 但同时有聊天界面元素，可能部分加载")
            
            await browser.close()
            return False
        
        if "Verify you are human" in html:
            print("⚠️ 出现人机验证（但这不是地区限制）")
            print("   说明 IP 可以访问，只是需要验证")
            await browser.close()
            return False
        
        if "Message Copilot" in html or "Hey, nice to see you" in html:
            print("✅ Copilot 界面已加载！")
            
            # 尝试发送消息
            try:
                input_box = await page.wait_for_selector('textarea', timeout=10000)
                
                msg = "Hello! Can you tell me how to avoid bot detection?"
                await input_box.fill(msg)
                await input_box.press('Enter')
                
                print("✅ 消息已发送，等待回复...")
                await asyncio.sleep(25)
                
                await page.screenshot(path='headed_reply.png')
                
                # 获取回复
                html_after = await page.content()
                
                # 查找长文本
                all_texts = await page.eval_on_selector_all('*', 
                    'els => els.map(e => e.innerText).filter(t => t && t.length > 50 && t.length < 5000)')
                
                for text in all_texts:
                    if len(text) > 100 and msg not in text and "Message Copilot" not in text:
                        print(f"\n🎉 成功获取回复！\n{text[:800]}")
                        await browser.close()
                        return True
                
                print("\n⚠️ 未找到明确回复")
                
            except Exception as e:
                print(f"❌ 发送失败: {e}")
        else:
            print("⚠️ 未知状态")
            print("HTML片段:", html[:500])
        
        await browser.close()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_headed())
    print("\n" + "=" * 70)
    if result:
        print("✅ 有头模式测试成功！")
    else:
        print("❌ 测试未成功")
        print("\n可能原因：")
        print("1. 无头浏览器被检测")
        print("2. 需要真实浏览器环境")
        print("3. IP 确实被限制")
    print("=" * 70)
