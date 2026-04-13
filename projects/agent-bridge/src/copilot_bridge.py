"""
Microsoft Copilot 长连接对话桥（支持代理）
保持浏览器常驻，支持多轮对话，带频率控制
"""
import asyncio
import random
import time
import subprocess
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

from utils import (
    get_proxy, start_xvfb, stop_xvfb, get_browser_args,
    find_system_chromium, SELECTORS, ANTIDETECT_SCRIPT,
    get_screenshot_path
)
from human_behavior_v2 import HumanBehaviorSimulator


@dataclass
class CopilotResponse:
    """Copilot 回复结构"""
    text: str
    timestamp: datetime
    turn_id: int


class RateLimiter:
    """频率限制器 - 防止触发反爬"""
    
    def __init__(self, min_interval: float = 8.0, max_interval: float = 15.0):
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.last_request_time: Optional[float] = None
        self.request_count = 0
    
    async def wait(self):
        """等待到可以发送下一个请求"""
        if self.last_request_time is not None:
            elapsed = time.time() - self.last_request_time
            interval = random.uniform(self.min_interval, self.max_interval)
            
            if elapsed < interval:
                wait_time = interval - elapsed
                print(f"[RateLimiter] 等待 {wait_time:.1f}s 以控制频率...")
                await asyncio.sleep(wait_time)
        
        self.last_request_time = time.time()
        self.request_count += 1


class CopilotBridge:
    """
    Microsoft Copilot 长连接对话桥
    
    特性：
    - 浏览器常驻，支持多轮对话
    - 自动频率控制（默认 8-15秒间隔）
    - 反检测策略（随机延迟、人类打字模式）
    - 支持代理
    - 自动重试机制
    - 会话状态保持
    """
    
    def __init__(self, headless: bool = True, rate_limit: bool = True, 
                 proxy: Optional[str] = None, use_xvfb: bool = True):
        self.headless = headless
        self.use_xvfb = use_xvfb
        self.xvfb_process = None
        self.rate_limiter = RateLimiter() if rate_limit else None
        self.proxy = proxy or get_proxy()
        self.simulator: Optional[HumanBehaviorSimulator] = None
        
        print(f"[CopilotBridge] 使用代理: {self.proxy}")
        
        # 浏览器实例
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        
        # 会话状态
        self.is_initialized = False
        self.turn_count = 0
        self.session_start_time: Optional[datetime] = None
    
    async def _find_element(self, selectors: List[str], timeout: int = 5000):
        """尝试多个选择器找到元素"""
        for selector in selectors:
            try:
                element = await self.page.wait_for_selector(selector, timeout=timeout)
                if element:
                    return element
            except:
                continue
        return None
    
    async def _find_elements(self, selectors: List[str]):
        """尝试多个选择器找到所有匹配元素"""
        for selector in selectors:
            try:
                elements = await self.page.query_selector_all(selector)
                if elements:
                    return elements
            except:
                continue
        return []
    
    def _start_xvfb(self):
        """启动 Xvfb 虚拟桌面"""
        if not start_xvfb():
            print("[CopilotBridge] Xvfb 启动失败")
    
    async def start(self):
        """启动长连接会话"""
        if self.is_initialized:
            return
        
        if self.use_xvfb:
            self._start_xvfb()
        
        print("[CopilotBridge] 启动浏览器...")
        
        playwright = await async_playwright().start()
        
        browser_kwargs = {
            "headless": self.headless,
            "args": get_browser_args(),
            "proxy": {"server": self.proxy} if self.proxy else None,
        }
        
        system_chromium = find_system_chromium()
        if system_chromium:
            print(f"[CopilotBridge] 使用系统 Chromium: {system_chromium}")
            browser_kwargs["executable_path"] = system_chromium
        
        self.browser = await playwright.chromium.launch(**browser_kwargs)
        
        self.context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            locale='en-US',
            timezone_id='America/Los_Angeles',
        )
        
        await self.context.add_init_script(ANTIDETECT_SCRIPT)
        
        self.page = await self.context.new_page()
        self.simulator = HumanBehaviorSimulator(self.page)
        
        print("[CopilotBridge] 访问 Copilot...")
        try:
            await self.page.goto(
                'https://copilot.microsoft.com/',
                wait_until='networkidle',
                timeout=60000
            )
        except Exception as e:
            print(f"[CopilotBridge] 访问失败: {e}")
            raise
        
        await self.simulator.random_delay(2, 4)
        await self._handle_welcome()
        
        self.is_initialized = True
        self.session_start_time = datetime.now()
        print("[CopilotBridge] 会话已启动")
    
    async def _handle_welcome(self):
        """处理欢迎弹窗"""
        try:
            btn = await self._find_element(SELECTORS["welcome_button"], timeout=5000)
            if btn:
                await btn.click()
                await self.simulator.random_delay(1, 2)
        except:
            pass
    
    async def _close_blocking_modal(self):
        """关闭遮挡弹窗"""
        for selector in SELECTORS["modal_close"]:
            try:
                btn = await self.page.wait_for_selector(selector, timeout=2000)
                if btn:
                    await btn.click(force=True)
                    await self.simulator.random_delay(0.5, 1)
                    return True
            except:
                continue
        
        try:
            await self.page.keyboard.press('Escape')
            await self.simulator.random_delay(0.5, 1)
        except:
            pass
        return False
    
    async def ask(self, prompt: str, timeout: int = 120) -> CopilotResponse:
        """发送消息并获取回复"""
        if not self.is_initialized:
            await self.start()
        
        self.turn_count += 1
        print(f"\n[CopilotBridge] 第 {self.turn_count} 轮对话")
        print(f"[CopilotBridge] 发送: {prompt[:50]}...")
        
        if self.rate_limiter:
            await self.rate_limiter.wait()
        
        try:
            # 找到并点击输入框
            input_box = await self._find_element(SELECTORS["input_box"], timeout=10000)
            if not input_box:
                raise Exception("无法找到输入框")
            
            try:
                await input_box.click(force=True)
            except:
                await self._close_blocking_modal()
                await input_box.click(force=True)
            
            # 使用人类行为模拟打字
            await input_box.fill('')
            await self.simulator.natural_typing('textarea', prompt)
            
            # 发送
            await input_box.press('Enter')
            print("[CopilotBridge] 已发送，等待回复...")
            
            await self.simulator.random_delay(2, 3)
            
            # 等待回复
            response_text = await self._wait_for_response(timeout)
            
            return CopilotResponse(
                text=response_text,
                timestamp=datetime.now(),
                turn_id=self.turn_count
            )
            
        except Exception as e:
            await self.page.screenshot(
                path=get_screenshot_path(f"error_turn{self.turn_count}.png")
            )
            raise Exception(f"对话失败: {str(e)}")
    
    async def _wait_for_response(self, timeout: int) -> str:
        """等待并获取回复内容"""
        print(f"[CopilotBridge] 等待回复（最长 {timeout} 秒）...")
        
        await asyncio.sleep(min(timeout, 30))
        
        response_text = await self._get_latest_response()
        
        if response_text:
            print(f"[CopilotBridge] 回复完成，长度: {len(response_text)}")
        else:
            print("[CopilotBridge] 未获取到回复")
        
        return response_text
    
    async def _get_latest_response(self) -> str:
        """获取最新的回复文本"""
        selectors = [
            '[data-testid="chat-messages"] [class*="text-pretty"]',
            '[class*="text-pretty"]',
            '[class*="ac-textBlock"]',
            '[class*="message-content" i]',
            '[class*="response" i]',
        ]
        
        all_messages = []
        for selector in selectors:
            try:
                elements = await self.page.query_selector_all(selector)
                if elements:
                    all_messages = elements
                    break
            except:
                continue
        
        if not all_messages:
            return ""
        
        valid_messages = []
        for msg in all_messages:
            try:
                text = await msg.inner_text()
                text = text.strip() if text else ""
                
                if not text or len(text) < 30:
                    continue
                if text in ["Message Copilot", "Smart", "New topic"]:
                    continue
                
                valid_messages.append(text)
            except:
                continue
        
        return valid_messages[-1] if valid_messages else ""
    
    async def close(self):
        """关闭长连接会话"""
        print("[CopilotBridge] 关闭会话...")
        
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        
        print(f"[CopilotBridge] 会话已关闭，共 {self.turn_count} 轮对话")
    
    def get_stats(self) -> dict:
        """获取会话统计信息"""
        return {
            "is_initialized": self.is_initialized,
            "turn_count": self.turn_count,
            "session_start_time": self.session_start_time.isoformat() if self.session_start_time else None,
            "request_count": self.rate_limiter.request_count if self.rate_limiter else 0,
            "proxy": self.proxy,
        }


async def demo():
    """演示用法"""
    bridge = CopilotBridge(headless=False, rate_limit=True)
    
    try:
        await bridge.start()
        
        questions = [
            "你好，请用一句话介绍自己",
            "Python 中如何实现异步编程？",
        ]
        
        for q in questions:
            response = await bridge.ask(q)
            print(f"\n👤 用户: {q}")
            print(f"🤖 Copilot: {response.text[:200]}...")
            print("-" * 50)
        
        print(f"\n统计: {bridge.get_stats()}")
        
    finally:
        await bridge.close()


if __name__ == "__main__":
    asyncio.run(demo())
