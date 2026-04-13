#!/usr/bin/env python3
"""
DeepSeek Chat 测试
基于 Copilot Bridge 项目经验，测试国内 AI 平台
"""
import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from playwright.async_api import async_playwright
from human_behavior_v2 import HumanBehaviorSimulator, test_human_behavior
from utils import get_screenshot_path, USER_DATA_DIR, start_xvfb


async def test_deepseek():
    print("=" * 70)
    print("DeepSeek Chat 测试")
    print("=" * 70)
    print()
    print("特点：")
    print("- 国内网站，无需代理")
    print("- 基于 Copilot Bridge 经验")
    print("- 应用自然化执行策略")
    print()
    
    # 启动 Xvfb
    if not start_xvfb():
        print("❌ Xvfb 启动失败")
        return False
    
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    print(f"[1] 使用持久化目录: {USER_DATA_DIR}")
    
    async with async_playwright() as p:
        print("\n[2] 启动浏览器（无代理）...")
        
        context = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            # 无需代理
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--window-size=1920,1080',
            ],
            viewport={'width': 1920, 'height': 1080},
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
        )
        
        pages = context.pages
        page = pages[0] if pages else await context.new_page()
        simulator = HumanBehaviorSimulator(page)
        
        print("\n[3] 访问 DeepSeek Chat...")
        await page.goto('https://chat.deepseek.com/', timeout=60000)
        
        # 等待页面加载
        print("    - 等待页面渲染 (5-10秒)")
        await simulator.random_delay(5, 10)
        
        # 截图检查
        await page.screenshot(path=get_screenshot_path('deepseek_initial.png'))
        print("[4] 初始截图已保存")
        
        # 检查页面状态
        html = await page.content()
        
        # 检查是否有登录按钮
        if "登录" in html or "Login" in html:
            print("⚠️ 检测到登录按钮，可能需要登录")
            # 检查是否有游客模式
            if "开始对话" in html or "New chat" in html:
                print("✅ 发现开始对话按钮，可能支持游客模式")
        
        # 查找输入框
        input_selectors = [
            'textarea',
            '[placeholder*="输入" i]',
            '[placeholder*="发送" i]',
            '[contenteditable="true"]',
        ]
        
        input_found = False
        for selector in input_selectors:
            try:
                if await page.query_selector(selector):
                    print(f"✅ 找到输入框: {selector}")
                    input_found = True
                    break
            except:
                continue
        
        if not input_found:
            print("⚠️ 未找到输入框，可能需要登录")
            await page.screenshot(path=get_screenshot_path('deepseek_no_input.png'))
            await context.close()
            return False
        
        print("\n[5] 模拟人类浏览...")
        await simulator.random_browsing()
        
        print("\n[6] 发送测试消息...")
        msg = "你好，请介绍一下你自己"
        
        success = await test_human_behavior(page, msg)
        if not success:
            print("❌ 发送失败")
            await context.close()
            return False
        
        print("✅ 消息已发送，等待回复...")
        await simulator.random_delay(15, 25)
        
        # 截图检查结果
        await page.screenshot(path=get_screenshot_path('deepseek_after_send.png'))
        print("[7] 回复截图已保存")
        
        # 检查是否有验证
        html_after = await page.content()
        
        verification_indicators = [
            "验证",
            "验证码",
            "captcha",
            "verify",
            "人机",
        ]
        
        has_verification = any(indicator in html_after for indicator in verification_indicators)
        
        if has_verification:
            print("⚠️ 可能触发验证")
        else:
            print("✅ 未检测到验证拦截")
        
        # 尝试查找回复内容
        texts = await page.eval_on_selector_all('*',
            'els => els.map(e => e.innerText).filter(t => t && t.length > 50 && t.length < 1000)')
        
        reply_found = False
        for text in texts:
            if len(text) > 100 and msg not in text:
                print(f"\n📝 可能的回复:\n{text[:200]}...")
                reply_found = True
                break
        
        if reply_found:
            print("\n✅ 可能收到回复")
        else:
            print("\n⚠️ 未找到明确回复")
        
        await context.close()
        return True


if __name__ == "__main__":
    result = asyncio.run(test_deepseek())
    
    print("\n" + "=" * 70)
    if result:
        print("✅ 测试完成")
    else:
        print("❌ 测试遇到问题")
    print("=" * 70)
