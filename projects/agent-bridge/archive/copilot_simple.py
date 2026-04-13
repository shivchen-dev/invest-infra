"""
Microsoft Copilot 对话桥 - 简化有效版
技术信条: 只要人能打开的页面，就没有我抓不到的数据。
"""
import asyncio
import os
from playwright.async_api import async_playwright


class CopilotBridge:
    """Copilot 浏览器自动化桥接"""
    
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
        
        print("[Copilot] 访问页面...")
        await self.page.goto('https://copilot.microsoft.com/', wait_until='networkidle')
        await asyncio.sleep(3)
        
        print("[Copilot] 准备就绪")
        return self
    
    async def ask(self, prompt: str, wait_seconds: int = 25) -> str:
        """
        发送消息并获取回复
        
        Args:
            prompt: 要发送的消息
            wait_seconds: 等待回复的时间（秒）
        """
        print(f"[Copilot] 发送: {prompt[:50]}...")
        
        # 1. 输入消息
        await self.page.fill('textarea#userInput', prompt)
        await asyncio.sleep(0.5)
        
        # 2. 按 Enter 发送
        await self.page.press('textarea#userInput', 'Enter')
        print(f"[Copilot] 等待 {wait_seconds} 秒...")
        
        # 3. 等待回复生成
        await asyncio.sleep(wait_seconds)
        
        # 4. 抓取页面上的回复文本
        response = await self._extract_response()
        
        print(f"[Copilot] 收到回复 ({len(response)} 字符)")
        return response
    
    async def _extract_response(self) -> str:
        """从页面提取回复文本"""
        
        # 使用 JavaScript 提取所有可能的回复内容
        texts = await self.page.evaluate('''() => {
            const results = [];
            
            // 1. 尝试找消息气泡
            const messages = document.querySelectorAll('[data-testid*="message"], .message, [class*="message"]');
            for (const m of messages) {
                const text = m.innerText?.trim();
                if (text && text.length > 20) results.push(text);
            }
            
            // 2. 尝试找主要文本区域
            const mainAreas = document.querySelectorAll('main, [role="main"], article');
            for (const area of mainAreas) {
                const text = area.innerText?.trim();
                if (text && text.length > 50) results.push(text);
            }
            
            // 3. 找所有 div 中的长文本
            const divs = document.querySelectorAll('div');
            for (const div of divs) {
                const text = div.innerText?.trim();
                // 过滤条件
                if (text && text.length > 100 && text.length < 5000 &&
                    !text.includes('Message Copilot') &&
                    !text.includes('Create an image') &&
                    !text.includes('Smart') &&
                    !text.startsWith('Hi there')) {
                    results.push(text);
                }
            }
            
            return results;
        }''')
        
        if texts and len(texts) > 0:
            # 返回最长的文本（最可能是完整回复）
            return max(texts, key=len)
        
        # 兜底：返回页面主要文本
        return await self.page.inner_text('main') or await self.page.inner_text('body')
    
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
    print("Copilot 对话测试 - 简化版")
    print("=" * 60)
    
    os.environ['HTTP_PROXY'] = 'http://127.0.0.1:7890'
    
    bridge = await CopilotBridge().start()
    
    try:
        # 第一轮
        print("\n[测试1] 第一轮对话")
        r1 = await bridge.ask("你好，请介绍你自己", wait_seconds=25)
        print(f"\n🤖 回复:\n{r1[:500]}...")
        
        await bridge.screenshot("response1.png")
        
        # 第二轮
        print("\n[测试2] 第二轮对话")
        r2 = await bridge.ask("Python 的 async/await 是什么？", wait_seconds=25)
        print(f"\n🤖 回复:\n{r2[:500]}...")
        
        await bridge.screenshot("response2.png")
        
        print("\n✅ 测试完成")
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        await bridge.screenshot("error.png")
        raise
    finally:
        await bridge.close()


if __name__ == "__main__":
    asyncio.run(test())
