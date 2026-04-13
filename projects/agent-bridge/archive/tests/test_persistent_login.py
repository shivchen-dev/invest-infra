#!/usr/bin/env python3
"""
DeepSeek 持久化登录测试 - 完整流程
测试登录态是否能通过持久化配置保留
"""
import os
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from playwright.async_api import async_playwright
from human_behavior_v2 import HumanBehaviorSimulator
from utils import get_screenshot_path, start_xvfb

USER_DATA_DIR = "data/browser_profile_deepseek"


async def test_persistent_login():
    """测试持久化登录"""
    print("=" * 70)
    print("DeepSeek 持久化登录测试")
    print("=" * 70)
    print()
    print("流程:")
    print("1. 启动浏览器（使用持久化配置）")
    print("2. 访问 DeepSeek 并登录")
    print("3. 优雅关闭浏览器（保存会话）")
    print("4. 重新启动浏览器")
    print("5. 验证登录状态是否保留")
    print()
    
    if not start_xvfb():
        print("❌ Xvfb 启动失败")
        return False
    
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    print(f"[1] 持久化目录: {USER_DATA_DIR}")
    
    # 检查目录内容
    if os.path.exists(USER_DATA_DIR):
        files = os.listdir(USER_DATA_DIR)
        print(f"    现有文件数: {len(files)}")
        if files:
            print(f"    文件: {files[:5]}")
    
    # 第一次启动
    print("\n[2] 第一次启动浏览器...")
    p = await async_playwright().start()
    
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
    )
    
    page = await context.new_page()
    simulator = HumanBehaviorSimulator(page)
    
    print("[3] 访问 DeepSeek...")
    await page.goto('https://chat.deepseek.com/', timeout=60000)
    await asyncio.sleep(3)
    
    # 检查当前状态
    html = await page.content()
    is_logged_in = "登录" not in html
    
    if is_logged_in:
        print("✅ 检测到已登录！（来自之前的会话）")
    else:
        print("⚠️ 未登录，请在 VNC 中完成登录")
        print("VNC: 172.22.224.123:5900")
        print("你有 120 秒时间...")
        
        # 等待登录
        for i in range(12):
            await asyncio.sleep(10)
            html = await page.content()
            if "登录" not in html:
                print("✅ 登录完成！")
                is_logged_in = True
                break
            print(f"    等待中... {120-(i+1)*10}秒")
    
    if not is_logged_in:
        print("❌ 未登录，测试终止")
        await context.close()
        return False
    
    # 截图验证
    await page.screenshot(path=get_screenshot_path('deepseek_logged_in.png'))
    print("[4] ✅ 登录截图已保存")
    
    # 发送测试消息
    print("\n[5] 发送测试消息...")
    try:
        input_box = await page.wait_for_selector('textarea', timeout=10000)
        await input_box.click()
        await asyncio.sleep(0.5)
        await input_box.fill("测试持久化登录")
        await asyncio.sleep(0.5)
        await input_box.press('Enter')
        print("    ✅ 消息已发送")
        await asyncio.sleep(5)
    except Exception as e:
        print(f"    ⚠️ 发送失败: {e}")
    
    # 关键：优雅关闭浏览器
    print("\n[6] 优雅关闭浏览器（保存会话）...")
    print("    关闭中...")
    await context.close()
    await p.stop()
    print("    ✅ 浏览器已关闭")
    
    # 检查持久化目录
    print("\n[7] 检查持久化目录...")
    if os.path.exists(USER_DATA_DIR):
        files = os.listdir(USER_DATA_DIR)
        print(f"    文件数: {len(files)}")
        
        # 检查关键文件
        cookies_file = os.path.join(USER_DATA_DIR, 'Default/Cookies')
        login_data = os.path.join(USER_DATA_DIR, 'Default/Login Data')
        
        if os.path.exists(cookies_file):
            size = os.path.getsize(cookies_file)
            print(f"    ✅ Cookies: {size} bytes")
        else:
            print(f"    ❌ Cookies 不存在")
        
        if os.path.exists(login_data):
            size = os.path.getsize(login_data)
            print(f"    ✅ Login Data: {size} bytes")
        else:
            print(f"    ❌ Login Data 不存在")
    
    # 第二次启动
    print("\n[8] 第二次启动浏览器（验证持久化）...")
    p2 = await async_playwright().start()
    
    context2 = await p2.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR,
        headless=False,
        args=[
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--window-size=1920,1080',
        ],
        viewport={'width': 1920, 'height': 1080},
        locale='zh-CN',
    )
    
    page2 = await context2.new_page()
    
    print("[9] 访问 DeepSeek（验证登录状态）...")
    await page2.goto('https://chat.deepseek.com/', timeout=60000)
    await asyncio.sleep(5)
    
    # 验证登录状态
    html2 = await page2.content()
    is_still_logged_in = "登录" not in html2
    
    await page2.screenshot(path=get_screenshot_path('deepseek_second_start.png'))
    
    print("\n" + "=" * 70)
    if is_still_logged_in:
        print("✅ 持久化登录成功！")
        print("   登录状态在浏览器重启后保留")
    else:
        print("❌ 持久化登录失败")
        print("   登录状态在浏览器重启后丢失")
        print("\n可能原因:")
        print("   - DeepSeek 使用设备指纹绑定登录态")
        print("   - Cookies 过期或被清除")
        print("   - 需要特定的 localStorage/sessionStorage 数据")
    print("=" * 70)
    
    # 清理
    await context2.close()
    await p2.stop()
    
    return is_still_logged_in


if __name__ == "__main__":
    result = asyncio.run(test_persistent_login())
    
    print("\n测试完成")
    sys.exit(0 if result else 1)
