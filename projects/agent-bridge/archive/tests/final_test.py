#!/usr/bin/env python3
"""
最终测试 - 使用 Cookies 发送消息并获取回复
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

async def final_test():
    print("=" * 70)
    print("Copilot 最终测试 - 获取真正回复")
    print("=" * 70)
    
    proxy = "http://192.168.6.50:7890"
    
    # 加载 cookies
    with open('data/cookies/copilot_cookies.json', 'r') as f:
        raw_cookies = json.load(f)
    cookies = fix_cookies(raw_cookies)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            proxy={"server": proxy}
        )
        
        context = await browser.new_context(
            locale='en-US',
            timezone_id='America/Los_Angeles',
            viewport={'width': 1920, 'height': 1080}
        )
        
        await context.add_cookies(cookies)
        print("✅ Cookies 已加载")
        
        page = await context.new_page()
        
        print("\n[1] 访问 Copilot...")
        await page.goto('https://copilot.microsoft.com/', timeout=60000)
        await asyncio.sleep(8)
        
        print("[2] 发送测试消息...")
        
        # 查找输入框
        input_selectors = [
            'textarea[placeholder*="Message" i]',
            'textarea',
            '[contenteditable="true"]'
        ]
        
        input_box = None
        for selector in input_selectors:
            try:
                input_box = await page.wait_for_selector(selector, timeout=5000)
                if input_box:
                    print(f"✅ 找到输入框: {selector}")
                    break
            except:
                continue
        
        if not input_box:
            print("❌ 未找到输入框")
            await page.screenshot(path='final_test_no_input.png')
            await browser.close()
            return False
        
        # 发送消息
        test_message = "Hello Copilot! Please introduce yourself in one sentence."
        await input_box.fill(test_message)
        await input_box.press('Enter')
        print(f"✅ 已发送: {test_message}")
        
        # 等待回复
        print("\n[3] 等待回复生成...")
        await asyncio.sleep(30)
        
        # 获取回复
        print("\n[4] 尝试获取回复...")
        
        # 截图保存
        await page.screenshot(path='final_test_result.png')
        print("✅ 截图已保存: final_test_result.png")
        
        # 获取页面文本
        html = await page.content()
        
        # 查找回复 - 排除输入框和提示文字
        all_elements = await page.query_selector_all('*')
        potential_responses = []
        
        for el in all_elements:
            try:
                text = await el.inner_text()
                text = text.strip()
                # 过滤条件
                if (len(text) > 50 and 
                    len(text) < 5000 and
                    "Message Copilot" not in text and
                    "Hey, nice to see you" not in text and
                    test_message not in text and
                    "Create an image" not in text and
                    "Recommend a product" not in text and
                    "Smart" not in text):
                    potential_responses.append(text)
            except:
                continue
        
        # 去重并显示
        seen = set()
        unique_responses = []
        for r in potential_responses:
            if r not in seen:
                seen.add(r)
                unique_responses.append(r)
        
        print(f"\n找到 {len(unique_responses)} 个可能的回复:")
        for i, resp in enumerate(unique_responses[:5]):
            print(f"\n--- 候选 {i+1} (长度: {len(resp)}) ---")
            print(resp[:500])
        
        # 保存HTML
        with open('final_test_page.html', 'w', encoding='utf-8') as f:
            f.write(html)
        print("\n✅ HTML已保存: final_test_page.html")
        
        await browser.close()
        
        # 检查是否成功
        if unique_responses:
            for resp in unique_responses:
                if len(resp) > 100 and "I" in resp:
                    print("\n" + "=" * 70)
                    print("🎉 成功获取 Copilot 回复！")
                    print("=" * 70)
                    print(f"\n回复内容:\n{resp[:800]}")
                    return True
        
        print("\n" + "=" * 70)
        print("⚠️ 未找到明确回复，请检查截图和HTML")
        print("=" * 70)
        return False

if __name__ == "__main__":
    asyncio.run(final_test())
