"""
Microsoft Copilot 对话桥 - 完整版（Cookie 登录 + 自动对话）
技术信条: 只要人能打开的页面，就没有我抓不到的数据。
"""
import asyncio
import json
import os
import subprocess
import time
from typing import Optional
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

COOKIE_FILE = "/home/claw/.openclaw/workspace-cb-browser/scripts/copilot_cookies.json"
COPILOT_URL = "https://copilot.microsoft.com/"


class CopilotBridge:
    """
    Copilot 浏览器自动化桥接 - 完整版
    
    特性：
    - 自动 Cookie 登录（首次手动，之后自动）
    - 自动重试机制
    - 代理支持
    - Xvfb 虚拟桌面
    """
    
    def __init__(self, proxy: Optional[str] = None, use_xvfb: bool = True, headless: bool = True):
        self.proxy = proxy or os.getenv('HTTP_PROXY') or os.getenv('http_proxy')
        self.use_xvfb = use_xvfb
        self.headless = headless
        
        self.browser = None
        self.context = None
        self.page = None
        self._playwright = None
        self.xvfb_process = None
    
    def _start_xvfb(self):
        """启动 Xvfb 虚拟桌面"""
        if not self.use_xvfb:
            return
        
        try:
            result = subprocess.run(['pgrep', '-f', 'Xvfb :99'], 
                                  capture_output=True, text=True)
            if result.returncode != 0:
                self.xvfb_process = subprocess.Popen([
                    'Xvfb', ':99', '-screen', '0', '1920x1080x24',
                    '-ac', '+extension', 'GLX', '+render', '-noreset'
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(1)
                print("[Copilot] Xvfb 已启动 :99")
            else:
                print("[Copilot] Xvfb 已在运行")
            
            os.environ['DISPLAY'] = ':99'
        except Exception as e:
            print(f"[Copilot] Xvfb 启动失败: {e}")
    
    async def _load_cookies(self) -> bool:
        """加载 Cookie"""
        if not os.path.exists(COOKIE_FILE):
            return False
        
        try:
            with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            
            await self.context.add_cookies(cookies)
            print("[Copilot] Cookie 已加载")
            return True
        except Exception as e:
            print(f"[Copilot] Cookie 加载失败: {e}")
            return False
    
    async def _save_cookies(self):
        """保存 Cookie"""
        try:
            cookies = await self.context.cookies()
            with open(COOKIE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, indent=2)
            print(f"[Copilot] Cookie 已保存到 {COOKIE_FILE}")
        except Exception as e:
            print(f"[Copilot] Cookie 保存失败: {e}")
    
    async def _ensure_login(self) -> bool:
        """确保已登录"""
        print("[Copilot] 检查登录状态...")
        
        try:
            # 等待输入框出现（表示已登录）
            await self.page.wait_for_selector('textarea#userInput', timeout=10000)
            print("[Copilot] 已登录")
            return True
        except PlaywrightTimeout:
            pass
        
        # 没有登录，需要手动登录
        if self.headless:
            print("[Copilot] 未登录，但 headless 模式无法手动登录")
            print("[Copilot] 请先运行非 headless 模式登录一次：")
            print("  bridge = CopilotBridge(headless=False)")
            return False
        
        print("[Copilot] 未登录，请在浏览器中手动登录...")
        print("[Copilot] 登录成功后会自动保存 Cookie")
        
        try:
            # 等待用户登录（无限等待直到输入框出现）
            await self.page.wait_for_selector('textarea#userInput', timeout=0)
            
            # 登录成功，保存 Cookie
            await self._save_cookies()
            print("[Copilot] 登录成功，Cookie 已保存")
            return True
            
        except Exception as e:
            print(f"[Copilot] 登录失败: {e}")
            return False
    
    async def start(self, max_retries: int = 3) -> bool:
        """启动浏览器"""
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
                
                self.context = await self.browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                )
                
                # 加载 Cookie
                await self._load_cookies()
                
                self.page = await self.context.new_page()
                self.page.set_default_timeout(60000)
                
                # 访问 Copilot
                await self.page.goto(COPILOT_URL, wait_until='networkidle', timeout=30000)
                await asyncio.sleep(3)
                
                # 确保登录
                if not await self._ensure_login():
                    return False
                
                print("[Copilot] 启动成功")
                return True
                
            except Exception as e:
                print(f"[Copilot] 启动失败: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                else:
                    return False
        
        return False
    
    async def ask(self, prompt: str, wait_seconds: int = 30, retries: int = 3) -> str:
        """发送消息并获取回复"""
        print(f"[Copilot] 发送: {prompt[:50]}...")
        
        for attempt in range(retries):
            try:
                # 输入消息
                await self.page.fill('textarea#userInput', prompt)
                await asyncio.sleep(0.5)
                
                # 点击发送按钮 - 尝试多种选择器
                send_selectors = [
                    'button[type="submit"]',
                    'button[aria-label*="Send" i]',
                    'button[aria-label*="发送" i]',
                    'button svg[class*="send"]',
                    '[data-testid*="send" i]',
                    'button:has(svg)',  # 有 SVG 图标的按钮
                ]
                
                send_btn = None
                for selector in send_selectors:
                    try:
                        send_btn = await self.page.wait_for_selector(selector, timeout=5000)
                        if send_btn:
                            print(f"[Copilot] 找到发送按钮: {selector}")
                            break
                    except:
                        continue
                
                if not send_btn:
                    # 如果都找不到，尝试按 Enter
                    print("[Copilot] 未找到发送按钮，尝试按 Enter")
                    await self.page.press('textarea#userInput', 'Enter')
                else:
                    await send_btn.click()
                
                # 等待回复
                await asyncio.sleep(wait_seconds)
                
                # 抓取回复
                reply = await self._extract_reply()
                
                if reply and len(reply) > 10:
                    print(f"[Copilot] 收到回复 ({len(reply)} 字符)")
                    return reply
                else:
                    raise Exception("回复内容为空")
                    
            except Exception as e:
                print(f"[Copilot] 错误: {e}，重试 {attempt + 1}/{retries}...")
                await asyncio.sleep(2)
        
        return "未能获取有效回复"
    
    async def _extract_reply(self) -> str:
        """提取回复文本"""
        # 尝试多种选择器
        selectors = [
            '.ac-textBlock',
            '[class*="message" i] [class*="text" i]',
            '[data-testid*="message" i]',
        ]
        
        for selector in selectors:
            try:
                messages = await self.page.query_selector_all(selector)
                if messages:
                    texts = []
                    for msg in messages:
                        text = await msg.inner_text()
                        if text and len(text) > 20:
                            texts.append(text)
                    if texts:
                        return texts[-1]  # 返回最后一条
            except:
                continue
        
        return ""
    
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
        print("[Copilot] 已关闭")


async def main():
    """主函数 - 首次使用 headless=False 登录"""
    print("=" * 60)
    print("Copilot 对话桥 - 完整版")
    print("=" * 60)
    print()
    
    # 检查是否有 Cookie
    has_cookie = os.path.exists(COOKIE_FILE)
    
    if has_cookie:
        print("📄 检测到已保存的 Cookie，使用 headless 模式")
        headless = True
    else:
        print("⚠️  首次使用，需要手动登录")
        print("👉  将打开浏览器，请完成登录")
        print()
        headless = False
    
    bridge = CopilotBridge(headless=headless, use_xvfb=True)
    
    try:
        success = await bridge.start()
        if not success:
            print("\n❌ 启动失败")
            return
        
        if has_cookie:
            # 已有 Cookie，直接测试对话
            print("\n[测试] 发送消息...")
            reply = await bridge.ask("你好，请介绍你自己", wait_seconds=30)
            print(f"\n🤖 回复:\n{reply[:500]}...")
            
            await bridge.screenshot("test_reply.png")
        else:
            # 首次登录，保持运行
            print("\n✅ 登录成功！Cookie 已保存")
            print("📝 下次运行将自动登录")
            print("\n按 Ctrl+C 退出...")
            await asyncio.sleep(999999)
        
    except KeyboardInterrupt:
        print("\n\n用户中断")
    finally:
        await bridge.close()


if __name__ == "__main__":
    asyncio.run(main())
