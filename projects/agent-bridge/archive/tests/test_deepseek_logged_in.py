#!/usr/bin/env python3
"""
DeepSeek Chat 登录态测试
使用用户提供的已登录 cookies
"""
import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from playwright.async_api import async_playwright
from human_behavior_v2 import HumanBehaviorSimulator, test_human_behavior
from utils import (
    get_screenshot_path, USER_DATA_DIR, start_xvfb, 
    load_cookies, fix_cookies
)


async def test_deepseek_with_cookies():
    print("=" * 70)
    print("DeepSeek Chat - 登录态测试")
    print("=" * 70)
    print()
    
    # 启动 Xvfb
    if not start_xvfb():
        print("❌ Xvfb 启动失败")
        return False
    
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    print(f"[1] 使用持久化目录: {USER_DATA_DIR}")
    
    # 加载 DeepSeek cookies
    try:
        with open('data/cookies/deepseek_cookies.json', 'r') as f:
            import json
            raw_cookies = json.load(f)
        cookies = fix_cookies(raw_cookies)
        print(f"[2] 已加载 {len(cookies)} 个 DeepSeek cookies")
    except Exception as e:
        print(f"❌ 加载 cookies 失败: {e}")
        return False
    
    async with async_playwright() as p:
        print("\n[3] 启动浏览器...")
        
        context = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--window-size=1920,1080',
            ],
            viewport={'width': 1920, 'height': 1080},
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
        )
        
        # 添加 DeepSeek cookies
        await context.add_cookies(cookies)
        print("[4] Cookies 已添加到浏览器")
        
        pages = context.pages
        page = pages[0] if pages else await context.new_page()
        simulator = HumanBehaviorSimulator(page)
        
        print("\n[5] 访问 DeepSeek Chat...")
        await page.goto('https://chat.deepseek.com/', timeout=60000)
        
        # 等待页面加载
        print("    - 等待页面渲染 (5-10秒)")
        await simulator.random_delay(5, 10)
        
        # 截图检查
        await page.screenshot(path=get_screenshot_path('deepseek_with_cookies.png'))
        print("[6] 截图已保存")
        
        # 检查页面状态
        html = await page.content()
        
        # 检查是否已登录
        if "登录" in html and "手机号" in html:
            print("⚠️ 仍显示登录页面，cookies 可能已过期")
            await context.close()
            return False
        
        # 查找输入框
        input_selectors = [
            'textarea',
            '[placeholder*="输入" i]',
            '[placeholder*="发送消息" i]',
            '#chat-input',
        ]
        
        input_found = False
        for selector in input_selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    is_visible = await element.is_visible()
                    if is_visible:
                        print(f"✅ 找到输入框: {selector}")
                        input_found = True
                        break
            except:
                continue
        
        if not input_found:
            print("⚠️ 未找到输入框")
            print("可能原因：")
            print("- Cookies 已过期")
            print("- 需要额外的验证步骤")
            await page.screenshot(path=get_screenshot_path('deepseek_no_input.png'))
            await context.close()
            return False
        
        print("\n[7] ✅ 已登录，输入框可用！")
        
        # 模拟浏览
        print("\n[8] 模拟人类浏览...")
        await simulator.random_browsing()
        
        # 发送测试消息
        print("\n[9] 发送测试消息...")
        msg = "你好，请介绍一下你自己"
        
        success = await test_human_behavior(page, msg)
        if not success:
            print("❌ 发送失败")
            await context.close()
            return False
        
        print("✅ 消息已发送，等待回复...")
        await simulator.random_delay(15, 25)
        
        # 截图检查结果
        await page.screenshot(path=get_screenshot_path('deepseek_reply.png'))
        print("[10] 回复截图已保存")
        
        # 尝试查找回复
        texts = await page.eval_on_selector_all('*',
            'els => els.map(e => e.innerText).filter(t => t && t.length > 50 && t.length < 1000)')
        
        reply_found = False
        for text in texts:
            if len(text) > 100 and msg not in text and "DeepSeek" in text:
                print(f"\n📝 DeepSeek 回复:\n{text[:300]}...")
                reply_found = True
                break
        
        if reply_found:
            print("\n✅ 成功收到 DeepSeek 回复！")
        else:
            print("\n⚠️ 未找到明确回复，请检查截图")
        
        # 保存会话 cookies
        try:
            final_cookies = await context.cookies()
            with open('data/cookies/deepseek_cookies_updated.json', 'w') as f:
                import json
                json.dump(final_cookies, f, indent=2)
            print(f"\n[11] 更新后的 cookies 已保存")
        except Exception as e:
            print(f"⚠️ 保存 cookies 失败: {e}")
        
        await context.close()
        return reply_found


if __name__ == "__main__":
    result = asyncio.run(test_deepseek_with_cookies())
    
    print("\n" + "=" * 70)
    if result:
        print("✅ DeepSeek 测试成功！")
    else:
        print("❌ DeepSeek 测试未完全成功")
    print("=" * 70)
