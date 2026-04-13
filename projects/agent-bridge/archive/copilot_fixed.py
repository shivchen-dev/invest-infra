"""
Microsoft Copilot 对话桥 - 修复版
点击发送按钮 + 正确选择器
"""
import asyncio
import os
from playwright.async_api import async_playwright


class CopilotBridge:
    """Copilot 浏览器自动化桥接 - 修复版"""
    
    def __init__(self, proxy=None):
        self.proxy = proxy or os.getenv('HTTP_PROXY')
        self.browser = None
        self.page = None
    
    async def start(self):
        """启动浏览器"""
        print("[Copilot] 启动浏览器...")
        
        p = await async_playwright().start()
        
        args = [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-blink-features=AutomationControlled',
        ]
        
        kwargs = {'headless': True, 'args': args}
        if self.proxy:
            kwargs['proxy'] = {'server': self.proxy}
        
        self.browser = await p.chromium.launch(**kwargs)
        
        context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        
        self.page = await context.new_page()
        self.page.set_default_timeout(60000)  # 60秒超时
        
        # 访问页面（带重试）
        for i in range(3):
            try:
                print(f"[Copilot] 访问页面 (尝试 {i+1}/3)...")
                await self.page.goto('https://copilot.microsoft.com/', 
                                   wait_until='networkidle', timeout=30000)
                break
            except Exception as e:
                print(f"[Copilot] 访问失败: {e}")
                if i < 2:
                    await asyncio.sleep(2)
                else:
                    raise
        
        await asyncio.sleep(3)
        print("[Copilot] 准备就绪")
        return self
    
    async def ask(self, prompt: str, wait_seconds: int = 30) -> str:
        """
        发送消息并获取回复
        
        Args:
            prompt: 要发送的消息
            wait_seconds: 等待回复的时间（秒）
        """
        print(f"[Copilot] 发送: {prompt[:50]}...")
        
        # 1. 输入消息
        input_box = await self.page.wait_for_selector('textarea#userInput', timeout=10000)
        await input_box.fill(prompt)
        await asyncio.sleep(0.5)
        
        # 2. 点击发送按钮（不能用 Enter！）
        # 尝试多种发送按钮选择器
        send_selectors = [
            'button[type="submit"]',
            'button[aria-label*="Send" i]',
            'button[aria-label*="发送" i]',
            'button svg[class*="send"]',  # 包含 send 图标的按钮
        ]
        
        send_btn = None
        for selector in send_selectors:
            try:
                send_btn = await self.page.wait_for_selector(selector, timeout=5000)
                if send_btn:
                    break
            except:
                continue
        
        if not send_btn:
            raise Exception("找不到发送按钮")
        
        await send_btn.click()
        print(f"[Copilot] 已发送，等待 {wait_seconds} 秒...")
        
        # 3. 等待回复渲染
        await asyncio.sleep(wait_seconds)
        
        # 4. 抓取回复 - 使用 .ac-textBlock
        response = await self._extract_response()
        
        print(f"[Copilot] 收到回复 ({len(response)} 字符)")
        return response
    
    async def _extract_response(self) -> str:
        """从页面提取回复文本 - 使用正确选择器"""
        
        # 主要选择器：.ac-textBlock
        try:
            # 等待回复出现
            await self.page.wait_for_selector('.ac-textBlock', timeout=5000)
            
            # 获取所有回复
            messages = await self.page.query_selector_all('.ac-textBlock')
            if messages and len(messages) > 0:
                # 取最后一条
                last_msg = messages[-1]
                text = await last_msg.inner_text()
                if text and len(text) > 10:
                    return text.strip()
        except Exception as e:
            print(f"[Copilot] .ac-textBlock 抓取失败: {e}")
        
        # 备选方案：JavaScript 提取
        try:
            texts = await self.page.evaluate('''() => {
                const results = [];
                // 找 .ac-textBlock
                const blocks = document.querySelectorAll('.ac-textBlock');
                for (const b of blocks) {
                    const text = b.innerText?.trim();
                    if (text && text.length > 20) results.push(text);
                }
                return results;
            }''')
            
            if texts and len(texts) > 0:
                return texts[-1]  # 返回最后一条
        except:
            pass
        
        # 兜底：返回页面文本
        return await self.page.inner_text('body')
    
    async def screenshot(self, path: str):
        """保存截图"""
        await self.page.screenshot(path=path)
        print(f"[Copilot] 截图已保存: {path}")
    
    async def close(self):
        """关闭浏览器"""
        if self.browser:
            await self.browser.close()
            print("[Copilot] 浏览器已关闭")


async def test():
    """测试"""
    print("=" * 60)
    print("Copilot 对话测试 - 修复版（点击发送按钮）")
    print("=" * 60)
    
    os.environ['HTTP_PROXY'] = 'http://127.0.0.1:7890'
    
    bridge = await CopilotBridge().start()
    
    try:
        # 第一轮
        print("\n[测试1] 第一轮对话")
        r1 = await bridge.ask("你好，请介绍你自己", wait_seconds=30)
        print(f"\n🤖 回复:\n{r1[:800]}...")
        await bridge.screenshot("response1_fixed.png")
        
        # 第二轮
        print("\n[测试2] 第二轮对话")
        r2 = await bridge.ask("Python 的 async/await 是什么？", wait_seconds=30)
        print(f"\n🤖 回复:\n{r2[:800]}...")
        await bridge.screenshot("response2_fixed.png")
        
        print("\n✅ 测试完成")
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        await bridge.screenshot("error_fixed.png")
        raise
    finally:
        await bridge.close()


if __name__ == "__main__":
    asyncio.run(test())
