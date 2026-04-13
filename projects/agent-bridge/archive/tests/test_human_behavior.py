#!/usr/bin/env python3
"""
Copilot Bridge v3.0 - 深度反检测版
更好的模拟人类行为，避免被检测
"""
import asyncio
import random
import time
from datetime import datetime
from playwright.async_api import async_playwright

class HumanBehavior:
    """深度模拟人类行为"""
    
    @staticmethod
    async def realistic_delay(min_sec=3, max_sec=8):
        """真实的人类反应延迟"""
        delay = random.uniform(min_sec, max_sec)
        print(f"[Human] 等待 {delay:.1f}s...")
        await asyncio.sleep(delay)
    
    @staticmethod
    async def natural_typing(page, selector, text):
        """自然打字 - 带错误和修正"""
        element = await page.wait_for_selector(selector, timeout=10000)
        
        # 先点击聚焦
        await element.click()
        await asyncio.sleep(random.uniform(0.5, 1.2))
        
        # 逐字输入，速度变化
        for i, char in enumerate(text):
            # 打字速度变化（60-200 WPM 范围）
            delay = random.uniform(0.05, 0.25)
            
            # 偶尔停顿（思考）
            if random.random() < 0.05:  # 5%概率
                await asyncio.sleep(random.uniform(0.3, 0.8))
            
            # 偶尔打错字然后删除（更真实）
            if random.random() < 0.02 and i > 0:  # 2%概率
                wrong_char = random.choice('abcdefghijklmnopqrstuvwxyz')
                await element.type(wrong_char)
                await asyncio.sleep(0.1)
                await element.press('Backspace')
                await asyncio.sleep(0.1)
            
            await element.type(char)
            await asyncio.sleep(delay)
        
        # 发送前停顿
        await asyncio.sleep(random.uniform(0.5, 1.5))


async def test_with_human_behavior():
    """使用深度人类行为模拟测试"""
    print("=" * 60)
    print("Copilot v3.0 - 深度反检测测试")
    print("=" * 60)
    
    proxy = "http://192.168.6.50:7890"
    
    async with async_playwright() as p:
        print("\n[1] 启动浏览器（带反检测）...")
        
        browser = await p.chromium.launch(
            headless=True,
            proxy={"server": proxy},
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--disable-setuid-sandbox',
                '--no-sandbox',
                '--window-size=1920,1080',
            ]
        )
        
        # 更真实的浏览器指纹
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/Los_Angeles',
            geolocation={'latitude': 34.0522, 'longitude': -118.2437},  # 洛杉矶
            permissions=['geolocation'],
            color_scheme='light',
        )
        
        # 注入反检测脚本
        await context.add_init_script("""
            // 隐藏自动化标志
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            
            // 伪装 plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [
                    {name: 'Chrome PDF Plugin'},
                    {name: 'Chrome PDF Viewer'},
                    {name: 'Native Client'}
                ]
            });
            
            // 伪装 languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
            
            // 伪装 Chrome
            window.chrome = {
                runtime: {
                    OnInstalledReason: {CHROME_UPDATE: "chrome_update"},
                    OnRestartRequiredReason: {APP_UPDATE: "app_update"}
                }
            };
        """)
        
        page = await context.new_page()
        
        # 随机延迟后开始
        await HumanBehavior.realistic_delay(5, 10)
        
        print("\n[2] 访问 Copilot...")
        await page.goto('https://copilot.microsoft.com/', wait_until='domcontentloaded')
        
        # 等待页面完全加载（人类会等待）
        print("[Human] 等待页面加载...")
        await asyncio.sleep(random.uniform(8, 15))
        
        # 检查状态
        html = await page.content()
        
        if "not yet available" in html:
            print("❌ 仍然显示地区限制")
            print("   建议: 更换美国其他地区节点，或等待一段时间")
            await browser.close()
            return False
        
        if "Message Copilot" in html or "Hey, nice to see you" in html:
            print("✅ Copilot 界面已加载！")
            
            # 人类会先浏览一下
            print("[Human] 浏览页面...")
            await asyncio.sleep(random.uniform(3, 5))
            
            # 查找输入框
            try:
                input_box = await page.wait_for_selector(
                    'textarea[placeholder*="Message"], #userInput', 
                    timeout=10000
                )
                
                print("\n[3] 输入消息（模拟人类打字）...")
                test_msg = "Hello! How are you today?"
                await HumanBehavior.natural_typing(page, 'textarea', test_msg)
                
                print("\n[4] 发送消息...")
                await input_box.press('Enter')
                
                # 人类会等待回复
                print("[Human] 等待回复...")
                await asyncio.sleep(random.uniform(25, 35))
                
                # 截图
                await page.screenshot(path='human_test_result.png')
                print("✅ 截图已保存: human_test_result.png")
                
                # 尝试获取回复
                print("\n[5] 获取回复...")
                
                # 查找消息元素
                messages = await page.query_selector_all('[data-testid*="message"], .ac-textBlock')
                
                for msg in messages[-3:]:
                    text = await msg.inner_text()
                    text = text.strip()
                    if (len(text) > 50 and 
                        "Message Copilot" not in text and
                        test_msg not in text and
                        "Hey, nice to see you" not in text):
                        print(f"\n🎉 成功获取回复！")
                        print(f"长度: {len(text)} 字符")
                        print(f"内容: {text[:500]}...")
                        await browser.close()
                        return True
                
                print("\n⚠️ 未找到明确回复")
                
            except Exception as e:
                print(f"❌ 操作失败: {e}")
        else:
            print("⚠️ 未知状态")
            await page.screenshot(path='human_test_unknown.png')
        
        await browser.close()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_with_human_behavior())
    
    print("\n" + "=" * 60)
    if result:
        print("✅ 测试成功！获取到 Copilot 回复")
    else:
        print("❌ 测试未成功")
        print("\n建议:")
        print("1. 更换美国其他地区节点")
        print("2. 等待 10-30 分钟后重试")
        print("3. 检查是否触发 Copilot 频率限制")
    print("=" * 60)
