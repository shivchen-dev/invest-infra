#!/usr/bin/env python3
"""
DeepSeek 持久化会话测试 - 直接测试浏览器配置
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from playwright.async_api import async_playwright
from utils import USER_DATA_DIR, start_xvfb, get_screenshot_path
import os


async def test_persistent_session():
    print("=" * 70)
    print("DeepSeek - 持久化会话测试")
    print("=" * 70)
    print()
    print("此测试直接使用持久化浏览器配置，不添加外部 cookies")
    print()
    
    if not start_xvfb():
        print("❌ Xvfb 启动失败")
        return False
    
    print(f"[1] 使用持久化目录: {USER_DATA_DIR}")
    
    # 检查配置文件
    if os.path.exists(f"{USER_DATA_DIR}/Default/Login Data"):
        size = os.path.getsize(f"{USER_DATA_DIR}/Default/Login Data")
        print(f"[2] Login Data 文件存在: {size} bytes")
    
    if os.path.exists(f"{USER_DATA_DIR}/Default/Cookies"):
        size = os.path.getsize(f"{USER_DATA_DIR}/Default/Cookies")
        print(f"[3] Cookies 文件存在: {size} bytes")
    
    async with async_playwright() as p:
        print("\n[4] 启动浏览器（使用已有配置）...")
        
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
        
        print("[5] 浏览器已启动")
        
        # 列出所有页面
        pages = context.pages
        print(f"[6] 已有 {len(pages)} 个页面")
        
        if pages:
            page = pages[0]
            print(f"    页面 URL: {page.url}")
        else:
            page = await context.new_page()
            print("[6] 创建新页面")
        
        print("\n[7] 访问 DeepSeek Chat...")
        await page.goto('https://chat.deepseek.com/', timeout=60000)
        await asyncio.sleep(5)
        
        # 截图检查
        await page.screenshot(path=get_screenshot_path('deepseek_persistent_test.png'))
        print("[8] 截图已保存")
        
        # 检查登录状态
        html = await page.content()
        
        if "登录" in html and "手机号" in html:
            print("\n❌ 检测到登录页面，持久化会话未保留登录态")
            print("\n可能原因：")
            print("- 浏览器未正常关闭，会话未保存")
            print("- DeepSeek 检测到环境变化，使会话失效")
            print("- 持久化配置中的登录数据已过期")
            await context.close()
            return False
        
        # 查找输入框
        try:
            input_box = await page.wait_for_selector('textarea', timeout=5000)
            if input_box:
                print("\n✅ 找到输入框，可能已登录！")
                
                # 尝试发送消息
                await input_box.click()
                await asyncio.sleep(0.5)
                await input_box.type("你好")
                await asyncio.sleep(0.5)
                await input_box.press('Enter')
                
                print("✅ 消息已发送")
                await asyncio.sleep(10)
                
                await page.screenshot(path=get_screenshot_path('deepseek_persistent_reply.png'))
                print("✅ 回复截图已保存")
                
                await context.close()
                return True
        except:
            pass
        
        print("\n⚠️ 未找到输入框")
        await context.close()
        return False


if __name__ == "__main__":
    result = asyncio.run(test_persistent_session())
    
    print("\n" + "=" * 70)
    if result:
        print("✅ 持久化会话有效！")
    else:
        print("❌ 持久化会话无效")
    print("=" * 70)
