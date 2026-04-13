"""
Microsoft Copilot 对话桥 - 生产稳定版
整合：重试机制 + 精准选择器 + 代理支持 + Xvfb
"""
import asyncio
import os
import subprocess
import time
from typing import Optional
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout


class CopilotBridge:
    """
    Copilot 浏览器自动化桥接 - 生产稳定版
    
    特性：
    - 自动重试机制（网络不稳定也能工作）
    - 精准选择器（不会抓到侧边栏）
    - 代理支持（Clash 自动配置）
    - Xvfb 虚拟桌面支持
    - 多轮对话保持
    """
    
    def __init__(self, proxy: Optional[str] = None, use_xvfb: bool = True, headless: bool = True):
        """
        Args:
            proxy: 代理地址，如 "http://127.0.0.1:7890"
            use_xvfb: 是否使用 Xvfb 虚拟桌面
            headless: 是否无头模式
        """
        self.proxy = proxy or os.getenv('HTTP_PROXY') or os.getenv('http_proxy')
        self.use_xvfb = use_xvfb
        self.headless = headless
        
        self.browser = None
        self.page = None
        self.xvfb_process = None
        self._playwright = None
        
        # 选择器配置（基于实际页面分析）
        self.SELECTORS = {
            'input': 'textarea#userInput',
            'send_button': 'button[type="submit"]',
            'reply': '.ac-textBlock',
        }
    
    def _start_xvfb(self):
        """启动 Xvfb 虚拟桌面"""
        if not self.use_xvfb:
            return
        
        try:
            # 检查是否已有 Xvfb 在运行
            result = subprocess.run(['pgrep', '-f', 'Xvfb :99'], 
                                  capture_output=True, text=True)
            if result.returncode != 0:
                # 启动 Xvfb
                self.xvfb_process = subprocess.Popen([
                    'Xvfb', ':99', '-screen', '0', '1920x1080x24',
                    '-ac', '+extension', 'GLX', '+render', '-noreset'
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(1)
                print("[Copilot] Xvfb 虚拟桌面已启动 :99")
            else:
                print("[Copilot] Xvfb 已在运行")
            
            os.environ['DISPLAY'] = ':99'
        except Exception as e:
            print(f"[Copilot] Xvfb 启动失败: {e}")
    
    async def start(self, max_retries: int = 3) -> 'CopilotBridge':
        """
        启动浏览器（带重试）
        
        Args:
            max_retries: 最大重试次数
        """
        self._start_xvfb()
        
        for attempt in range(max_retries):
            try:
                print(f"[Copilot] 启动浏览器 (尝试 {attempt + 1}/{max_retries})...")
                
                self._playwright = await async_playwright().start()
                
                args = [
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-blink-features=AutomationControlled',
                ]
                
                kwargs = {'headless': self.headless, 'args': args}
                if self.proxy:
                    kwargs['proxy'] = {'server': self.proxy}
                    print(f"[Copilot] 使用代理: {self.proxy}")
                
                self.browser = await self._playwright.chromium.launch(**kwargs)
                
                context = await self.browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                )
                
                self.page = await context.new_page()
                self.page.set_default_timeout(60000)
                
                # 访问 Copilot（带重试）
                for nav_attempt in range(3):
                    try:
                        await self.page.goto('https://copilot.microsoft.com/', 
                                           wait_until='networkidle', timeout=30000)
                        break
                    except Exception as e:
                        if nav_attempt < 2:
                            print(f"[Copilot] 访问失败，重试...")
                            await asyncio.sleep(2)
                        else:
                            raise
                
                await asyncio.sleep(3)
                print("[Copilot] 浏览器启动成功")
                return self
                
            except Exception as e:
                print(f"[Copilot] 启动失败: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                else:
                    raise Exception(f"浏览器启动失败（已重试 {max_retries} 次）")
        
        return self
    
    async def _send_message(self, prompt: str):
        """发送消息（内部方法）"""
        # 1. 输入消息
        input_box = await self.page.wait_for_selector(
            self.SELECTORS['input'], timeout=10000
        )
        await input_box.fill(prompt)
        await asyncio.sleep(0.5)
        
        # 2. 点击发送按钮
        send_btn = await self.page.wait_for_selector(
            self.SELECTORS['send_button'], timeout=10000
        )
        await send_btn.click()
    
    async def _wait_for_reply(self, timeout: int = 60) -> str:
        """等待并获取回复"""
        # 等待回复出现
        await self.page.wait_for_selector(
            self.SELECTORS['reply'], timeout=timeout * 1000
        )
        
        # 获取所有回复
        messages = await self.page.query_selector_all(self.SELECTORS['reply'])
        if not messages:
            return ""
        
        # 返回最后一条
        last_msg = messages[-1]
        return await last_msg.inner_text() or ""
    
    async def ask(self, prompt: str, retries: int = 3) -> str:
        """
        发送消息并获取回复（带重试）
        
        Args:
            prompt: 要发送的消息
            retries: 失败时重试次数
        
        Returns:
            Copilot 的回复文本
        """
        print(f"[Copilot] 发送: {prompt[:50]}...")
        
        for attempt in range(retries):
            try:
                await self._send_message(prompt)
                reply = await self._wait_for_reply()
                
                if reply and len(reply) > 10:
                    print(f"[Copilot] 收到回复 ({len(reply)} 字符)")
                    return reply
                else:
                    raise Exception("回复内容为空")
                    
            except PlaywrightTimeout:
                print(f"[Copilot] 超时，重试 {attempt + 1}/{retries}...")
                await asyncio.sleep(2)
                
            except Exception as e:
                print(f"[Copilot] 错误: {e}，重试 {attempt + 1}/{retries}...")
                await asyncio.sleep(2)
        
        return "Copilot 未能返回有效回复（多次重试失败）"
    
    async def screenshot(self, path: str):
        """保存截图"""
        if self.page:
            await self.page.screenshot(path=path)
            print(f"[Copilot] 截图已保存: {path}")
    
    async def close(self):
        """关闭浏览器"""
        if self.browser:
            await self.browser.close()
        
        if self.xvfb_process:
            self.xvfb_process.terminate()
            try:
                self.xvfb_process.wait(timeout=5)
            except:
                self.xvfb_process.kill()
        
        print("[Copilot] 已关闭")


async def test():
    """测试"""
    print("=" * 60)
    print("Copilot 对话桥 - 生产稳定版测试")
    print("=" * 60)
    
    # 自动检测代理
    bridge = CopilotBridge(use_xvfb=True, headless=True)
    
    try:
        await bridge.start(max_retries=3)
        
        # 第一轮
        print("\n[测试1] 第一轮对话")
        r1 = await bridge.ask("你好，请介绍你自己", retries=3)
        print(f"\n🤖 回复:\n{r1[:500]}...")
        await bridge.screenshot("reply1.png")
        
        # 第二轮
        print("\n[测试2] 第二轮对话")
        r2 = await bridge.ask("Python 的 async/await 是什么？", retries=3)
        print(f"\n🤖 回复:\n{r2[:500]}...")
        await bridge.screenshot("reply2.png")
        
        print("\n✅ 测试完成！")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        await bridge.screenshot("error.png")
        raise
    finally:
        await bridge.close()


if __name__ == "__main__":
    asyncio.run(test())
