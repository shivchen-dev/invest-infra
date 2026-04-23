#!/usr/bin/env python3
"""
Human Behavior Simulator v2.0
模拟真实人类行为的浏览器交互
"""
import asyncio
import random
import math
from typing import List, Tuple

class HumanBehaviorSimulator:
    """人类行为模拟器"""
    
    def __init__(self, page):
        self.page = page
        self.mouse_pos = (0, 0)
    
    async def random_delay(self, min_sec=2, max_sec=8):
        """随机延迟，模拟人类反应时间"""
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)
    
    async def think_delay(self):
        """思考延迟（更长）"""
        await self.random_delay(3, 12)
    
    async def natural_mouse_move(self, target_x: int, target_y: int, duration: float = None):
        """
        自然鼠标移动 - 使用贝塞尔曲线模拟真实轨迹
        """
        if duration is None:
            duration = random.uniform(0.5, 2.0)
        
        start_x, start_y = self.mouse_pos
        
        # 生成控制点（模拟人类移动的不确定性）
        control_x = (start_x + target_x) / 2 + random.randint(-100, 100)
        control_y = (start_y + target_y) / 2 + random.randint(-100, 100)
        
        steps = int(duration * 60)  # 60fps
        
        for i in range(steps + 1):
            t = i / steps
            # 二次贝塞尔曲线
            x = (1-t)**2 * start_x + 2*(1-t)*t * control_x + t**2 * target_x
            y = (1-t)**2 * start_y + 2*(1-t)*t * control_y + t**2 * target_y
            
            # 添加微抖动
            x += random.randint(-2, 2)
            y += random.randint(-2, 2)
            
            await self.page.mouse.move(int(x), int(y))
            await asyncio.sleep(1/60)  # 60fps
        
        self.mouse_pos = (target_x, target_y)
    
    async def natural_click(self, selector: str):
        """自然点击 - 先移动鼠标再点击"""
        element = await self.page.wait_for_selector(selector, timeout=10000)
        
        # 获取元素中心位置
        box = await element.bounding_box()
        target_x = int(box['x'] + box['width'] / 2)
        target_y = int(box['y'] + box['height'] / 2)
        
        # 添加随机偏移（不总是点击中心）
        target_x += random.randint(-10, 10)
        target_y += random.randint(-5, 5)
        
        # 先移动鼠标到目标附近
        await self.natural_mouse_move(target_x, target_y)
        await self.random_delay(0.1, 0.5)  # 短暂停顿
        
        # 执行点击
        await self.page.mouse.click(target_x, target_y)
        await self.random_delay(0.2, 0.8)
    
    async def natural_typing(self, selector: str, text: str):
        """
        自然打字 - 模拟真实人类打字速度
        包含：速度变化、停顿、偶尔回退
        修复：使用 page.fill 代替 element.fill，避免元素分离
        """
        # 使用 page.fill 一次性填充（自动处理元素分离问题）
        # 先聚焦到输入框
        await self.page.wait_for_selector(selector, state='visible', timeout=10000)
        await self.natural_click(selector)
        await self.random_delay(0.3, 0.8)
        
        # 使用 page.fill 填充（比 element.fill 更稳定，自动重新定位元素）
        print(f"  使用 page.fill 填充 {len(text)} 字符...")
        await self.page.fill(selector, text)
        
        # 打完后停顿
        await self.random_delay(0.5, 1.5)
    
    async def natural_scroll(self, amount: int = None, direction: str = 'down'):
        """自然滚动"""
        if amount is None:
            amount = random.randint(200, 800)
        
        if direction == 'up':
            amount = -amount
        
        # 分段滚动，模拟人类
        steps = random.randint(3, 8)
        step_amount = amount // steps
        
        for _ in range(steps):
            await self.page.mouse.wheel(0, step_amount)
            await self.random_delay(0.1, 0.4)
    
    async def random_browsing(self):
        """随机浏览行为 - 模拟用户浏览页面"""
        # 随机滚动几次
        for _ in range(random.randint(1, 3)):
            await self.natural_scroll(random.randint(300, 1000))
            await self.think_delay()
        
        # 偶尔向上滚动
        if random.random() < 0.3:
            await self.natural_scroll(random.randint(100, 400), direction='up')
            await self.random_delay(1, 3)
    
    async def simulate_reading(self, duration: float = None):
        """模拟阅读停顿"""
        if duration is None:
            duration = random.uniform(3, 10)
        await asyncio.sleep(duration)


async def test_human_behavior(page, message: str):
    """
    使用人类行为模拟发送消息
    """
    simulator = HumanBehaviorSimulator(page)
    
    # 先随机浏览一下
    print("🤖 模拟浏览页面...")
    await simulator.random_browsing()
    
    # 找到输入框
    print("🖱️  移动鼠标到输入框...")
    input_selectors = [
        'textarea',
        '[placeholder*="Ask" i]',
        '[placeholder*="Message" i]',
        '[contenteditable="true"]',
    ]
    
    input_selector = None
    for selector in input_selectors:
        try:
            if await page.query_selector(selector):
                input_selector = selector
                print(f"✅ 找到输入框: {selector}")
                break
        except:
            continue
    
    if not input_selector:
        print("❌ 未找到输入框")
        return False
    
    # 自然点击输入框
    print("👆 点击输入框...")
    await simulator.natural_click(input_selector)
    await simulator.think_delay()
    
    # 自然打字
    print(f"⌨️  打字: {message[:30]}...")
    await simulator.natural_typing(input_selector, message)
    
    # 思考后发送
    print("🤔 思考中...")
    await simulator.think_delay()
    
    # 查找发送按钮
    print("📤 发送消息...")
    send_selectors = [
        'button[type="submit"]',
        'button svg[aria-label*="send" i]',
        'button:has-text("Send")',
        '[data-testid="send-button"]',
    ]
    
    for selector in send_selectors:
        try:
            if await page.query_selector(selector):
                await simulator.natural_click(selector)
                print("✅ 消息已发送")
                return True
        except:
            continue
    
    # 如果没找到发送按钮，按回车
    print("⌨️  按回车发送...")
    await page.keyboard.press('Enter')
    return True
