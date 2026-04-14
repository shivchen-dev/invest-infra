#!/usr/bin/env python3
"""
Xiaohongshu Bridge - AI Agent 接口
供其他智能体调用，与小红书网页版对话

通过 Playwright 浏览器自动化控制小红书网页版，
使用持久化上下文保持登录状态。
"""
import asyncio
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from base_bridge import BaseBridge, BridgeResponse
from human_behavior_v2 import HumanBehaviorSimulator
from response_extractor import ResponseExtractor


class XiaohongshuBridge(BaseBridge):
    """
    小红书对话桥接器
    
    使用方式：
    ```python
    bridge = XiaohongshuBridge()
    await bridge.start()
    await bridge.ensure_login(timeout=600)  # 在 VNC 里完成登录
    response = await bridge.chat("搜索关键词")
    print(response.text)
    ```
    """
    
    platform_name = "xiaohongshu"
    login_url = "https://www.xiaohongshu.com"
    user_data_dir = "data/browser_profile_xiaohongshu"
    
    def __init__(self):
        super().__init__()
        self.simulator: Optional[HumanBehaviorSimulator] = None
        self.extractor: Optional[ResponseExtractor] = None
    
    async def start(self) -> bool:
        """启动浏览器"""
        if not await super().start():
            return False
        
        self.simulator = HumanBehaviorSimulator(self.page)
        self.extractor = ResponseExtractor("xiaohongshu")
        
        return True
    
    async def ensure_login(self, timeout: int = 600) -> bool:
        """
        确保已登录
        
        如果未登录，在 VNC 里打开登录页面，等待用户在浏览器中完成登录。
        登录完成后浏览器保持打开，不关闭。
        
        Args:
            timeout: 等待登录超时时间（秒），默认 10 分钟
            
        Returns:
            bool: 是否已登录
        """
        if self.is_logged_in and self.page:
            return True
        
        if not self.context:
            return False
        
        # 检查所有标签页
        pages = self.context.pages
        print(f"[ensure_login] 发现 {len(pages)} 个标签页")
        
        for i, page in enumerate(pages):
            try:
                print(f"  检查标签页 {i+1}: {page.url[:50]}...")
                text = await page.inner_text("body")
                
                if "登录" not in text and len(text) > 500:
                    print(f"  ✅ 标签页 {i+1} 已登录")
                    self.page = page
                    self.is_logged_in = True
                    await self.page.bring_to_front()
                    return True
            except Exception as e:
                print(f"  检查标签页 {i+1} 失败: {e}")
                continue
        
        # 没有已登录的标签页
        if pages:
            self.page = pages[0]
        else:
            self.page = await self.context.new_page()
        
        print("[ensure_login] 访问小红书...")
        await self.page.goto(self.login_url, timeout=60000)
        await asyncio.sleep(3)
        
        # 检查登录状态
        for attempt in range(timeout // 10):
            try:
                text = await self.page.inner_text("body")
                if "登录" not in text or len(text) < 200:
                    self.is_logged_in = True
                    print("✅ 登录完成")
                    return True
            except:
                pass
            
            remaining = timeout - (attempt + 1) * 10
            print(f"  等待登录... {remaining}秒")
            await asyncio.sleep(10)
        
        print("❌ 登录超时")
        return False
    
    async def chat(self, message: str, **kwargs) -> BridgeResponse:
        """
        在小红书搜索并获取内容
        
        Args:
            message: 搜索关键词或操作指令
            
        Returns:
            BridgeResponse: 搜索结果
        """
        if not await self.ensure_login():
            return BridgeResponse(text="", success=False, error="未登录")
        
        try:
            # 访问搜索页面
            search_url = f"https://www.xiaohongshu.com/search_result?keyword={message}"
            await self.page.goto(search_url, timeout=60000)
            await asyncio.sleep(5)  # 等待页面加载
            
            # 等待内容出现
            await self.page.wait_for_timeout(3000)
            
            # 提取内容
            result = await self.extractor.extract_last_ai_response(self.page)
            
            if result:
                return BridgeResponse(
                    text=result["text"],
                    success=True
                )
            else:
                return BridgeResponse(
                    text=await self.page.inner_text("body")[:2000],
                    success=True
                )
        
        except Exception as e:
            return BridgeResponse(text="", success=False, error=str(e))
    
    async def get_note_content(self, note_url: str) -> BridgeResponse:
        """
        获取笔记详情页内容
        
        Args:
            note_url: 笔记详情页 URL
            
        Returns:
            BridgeResponse: 笔记内容
        """
        if not await self.ensure_login():
            return BridgeResponse(text="", success=False, error="未登录")
        
        try:
            await self.page.goto(note_url, timeout=60000)
            await asyncio.sleep(5)
            
            # 提取正文
            content = await self.page.inner_text("body")
            
            return BridgeResponse(text=content[:5000], success=True)
        
        except Exception as e:
            return BridgeResponse(text="", success=False, error=str(e))


if __name__ == "__main__":
    async def demo():
        bridge = XiaohongshuBridge()
        await bridge.start()
        
        if await bridge.ensure_login(timeout=600):
            print("已登录，开始使用...")
            # result = await bridge.chat("Python 编程")
            # print(result.text)
        
        await bridge.close()
    
    asyncio.run(demo())
