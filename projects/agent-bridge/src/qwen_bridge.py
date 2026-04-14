#!/usr/bin/env python3
"""
Qwen Bridge - AI Agent 接口
供其他智能体调用，与通义千问对话
"""
import asyncio
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from base_bridge import BaseBridge, BridgeResponse
from human_behavior_v2 import HumanBehaviorSimulator
from response_extractor import ResponseExtractor


class QwenBridge(BaseBridge):
    """
    通义千问对话桥接器
    
    供其他 AI Agent 调用：
    ```python
    bridge = QwenBridge()
    response = await bridge.chat("你好")
    print(response.text)
    ```
    """
    
    platform_name = "qwen"
    login_url = "https://www.qianwen.com/"
    user_data_dir = "data/browser_profile_qwen"
    
    
    def __init__(self):
        super().__init__()
        self.simulator: Optional[HumanBehaviorSimulator] = None
        self.extractor: Optional[ResponseExtractor] = None
    
    async def start(self) -> bool:
        """启动浏览器 - 继承基类并初始化 Qwen 特有组件"""
        if not await super().start():
            return False
        
        # 初始化 Qwen 特有组件
        self.simulator = HumanBehaviorSimulator(self.page)
        self.extractor = ResponseExtractor("qwen")
        
        return True
    
    async def ensure_login(self, timeout: int = 120) -> bool:
        """
        确保已登录 - 基于 DeepSeek Bridge 的持久化登录逻辑
        
        策略:
        1. 检查已有标签页是否已登录
        2. 访问千问首页
        3. 检测登录状态（检查"登录"按钮）
        4. 如未登录，在VNC等待用户扫码/验证码登录
        """
        if self.is_logged_in and self.page:
            return True
        
        if not self.context:
            return False
        
        # 1. 检查所有标签页是否已登录
        pages = self.context.pages
        print(f"[ensure_login] 发现 {len(pages)} 个标签页")
        
        for i, page in enumerate(pages):
            try:
                print(f"  检查标签页 {i+1}: {page.url[:50]}...")
                html = await page.content()
                
                # 千问登录检测：检查是否包含"登录"按钮
                # 已登录时页面不会显示登录按钮
                if "登录" not in html and len(html) > 1000:
                    print(f"  ✅ 标签页 {i+1} 已登录")
                    self.page = page
                    self.is_logged_in = True
                    await self.page.bring_to_front()
                    return True
            except Exception as e:
                print(f"  检查标签页 {i+1} 失败: {e}")
                continue
        
        # 2. 没有已登录的标签页，访问千问首页
        if pages:
            self.page = pages[0]
        else:
            self.page = await self.context.new_page()
        
        print("[ensure_login] 访问通义千问...")
        await self.page.goto(self.login_url, timeout=60000)
        await asyncio.sleep(3)
        
        # 3. 检查登录状态
        html = await self.page.content()
        if "登录" not in html:
            self.is_logged_in = True
            print("✅ 已登录")
            return True
        
        # 4. 需要登录 - 在VNC中等待用户登录
        from config import VNC_ADDRESS
        print("⚠️ 需要登录通义千问")
        print(f"   请在 VNC 中完成登录（{timeout}秒）...")
        print(f"   VNC 地址: {VNC_ADDRESS}")
        print("   支持登录方式: 手机号+验证码 / 淘宝 / 支付宝 / 钉钉")
        
        # 轮询检测登录完成
        for i in range(timeout // 10):
            await asyncio.sleep(10)
            html = await self.page.content()
            if "登录" not in html:
                self.is_logged_in = True
                print("✅ 登录完成")
                return True
            print(f"   等待中... {timeout-(i+1)*10}秒")
        
        print("❌ 登录超时")
        return False
    
    async def chat(self, message: str, wait_for_reply: bool = True, 
                   save_response: bool = True, take_screenshot: bool = True) -> BridgeResponse:
        """
        发送消息并获取回复
        
        Args:
            message: 用户消息内容
            wait_for_reply: 是否等待AI回复
            save_response: 是否保存回复到本地
            take_screenshot: 是否截图
            
        Returns:
            BridgeResponse: 包含回复文本和元数据
        """
        from config import TIMEOUTS, HUMAN_BEHAVIOR
        from utils import get_screenshot_path
        from agent_response_logger import AgentResponseLogger
        
        if not await self.ensure_login():
            return BridgeResponse(text="", success=False, error="未登录")
        
        try:
            # 1. 等待输入框可见并自然点击
            print("🖱️  移动鼠标到输入框...")
            await self.page.wait_for_selector(
                'textarea', state='visible', timeout=TIMEOUTS["element_wait"] * 1000
            )
            await self.simulator.natural_click('textarea')
            await asyncio.sleep(0.5)
            
            # 2. 自然打字输入消息
            print(f"⌨️  正在输入: {message[:30]}...")
            await self.simulator.natural_typing('textarea', message)
            
            # 3. 思考后发送
            print("🤔 思考中...")
            await self.simulator.think_delay()
            await self.page.keyboard.press('Enter')
            print(f"✅ 消息已发送: {message[:50]}...")
            
            if not wait_for_reply:
                return BridgeResponse(text="消息已发送", success=True)
            
            # 4. 等待AI回复
            print("等待通义千问回复...")
            await self.simulator.random_delay(
                HUMAN_BEHAVIOR["response_wait"]["min"],
                HUMAN_BEHAVIOR["response_wait"]["max"]
            )
            
            # 5. 提取回复内容
            response_data = await self.extractor.extract_last_ai_response(self.page)
            if not response_data:
                return BridgeResponse(
                    text="", 
                    success=False, 
                    error="未能提取回复"
                )
            
            # 6. 截图（可选）
            screenshot_path = None
            if take_screenshot:
                screenshot_path = get_screenshot_path(
                    f'qwen_reply_{int(asyncio.get_event_loop().time())}.png'
                )
                await self.page.screenshot(path=screenshot_path)
            
            # 7. 自动保存回复（可选）
            saved_path = None
            if save_response:
                logger = AgentResponseLogger("qwen")
                result = logger.save_response(
                    text=response_data["text"],
                    screenshot_path=screenshot_path if take_screenshot else None,
                    query=message,
                    metadata={
                        "platform": "qwen",
                        "selector": response_data.get("selector", ""),
                        "html_length": len(response_data.get("html", "")),
                        "has_screenshot": take_screenshot,
                    }
                )
                saved_path = result.get("session_dir")
                print(f"💾 回复已保存到: {saved_path}")
            
            return BridgeResponse(
                text=response_data["text"],
                success=True,
                metadata={
                    "html": response_data["html"],
                    "screenshot_path": screenshot_path,
                    "saved_path": saved_path
                }
            )
            
        except Exception as e:
            return BridgeResponse(
                text="",
                success=False,
                error=str(e)
            )


# 示例用法
async def demo():
    """演示用法"""
    bridge = QwenBridge()
    await bridge.start()
    
    response = await bridge.chat(
        "你好通义千问！我是一个 AI Agent，想请教智能体之间如何有效协作？"
    )
    
    if response.success:
        print(f"\n📝 通义千问回复:\n{response.text[:500]}")
    else:
        print(f"❌ 错误: {response.error}")


if __name__ == "__main__":
    asyncio.run(demo())
