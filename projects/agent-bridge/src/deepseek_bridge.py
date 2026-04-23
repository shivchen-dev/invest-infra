#!/usr/bin/env python3
"""
DeepSeek Bridge - AI Agent 接口
供其他智能体调用，与 DeepSeek 对话

集成自动存储功能：
- 回复文字自动保存到 data/agent_responses/deepseek/{timestamp}/
- 截图同步保存
- 生成索引文件便于浏览
"""
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from base_bridge import BaseBridge, BridgeResponse
from human_behavior_v2 import HumanBehaviorSimulator
from utils import get_screenshot_path
from agent_response_logger import AgentResponseLogger
from response_extractor import ResponseExtractor
from config import TIMEOUTS, HUMAN_BEHAVIOR, PLATFORM_CONFIGS


class DeepSeekBridge(BaseBridge):
    """
    DeepSeek 对话桥接器
    
    供其他 AI Agent 调用：
    ```python
    bridge = DeepSeekBridge()
    response = await bridge.chat("你好")
    print(response.text)
    print(response.metadata.get("message_id"))  # 查看消息ID
    ```
    """
    
    platform_name = "deepseek"
    login_url = "https://chat.deepseek.com/"
    user_data_dir = "projects/agent-bridge/data/browser_profile_deepseek"
    
    
    def __init__(self):
        super().__init__()
        self.simulator: Optional[HumanBehaviorSimulator] = None
        self.logger: Optional[AgentResponseLogger] = None
        self.extractor: Optional[ResponseExtractor] = None
    
    async def start(self) -> bool:
        """启动浏览器 - 继承基类并初始化 DeepSeek 特有组件"""
        if not await super().start():
            return False
        
        # 初始化 DeepSeek 特有组件
        self.simulator = HumanBehaviorSimulator(self.page)
        self.logger = AgentResponseLogger("deepseek")
        self.extractor = ResponseExtractor("deepseek")
        
        return True
    
    async def ensure_login(self, timeout: int = 120) -> bool:
        """确保已登录 - 检查所有标签页"""
        if self.is_logged_in and self.page:
            return True
        
        if not self.context:
            return False
        
        # 获取所有标签页
        pages = self.context.pages
        print(f"[ensure_login] 发现 {len(pages)} 个标签页")
        
        # 检查每个标签页
        for i, page in enumerate(pages):
            try:
                print(f"  检查标签页 {i+1}: {page.url[:50]}...")
                html = await page.content()
                
                if "登录" not in html and len(html) > 1000:
                    print(f"  ✅ 标签页 {i+1} 已登录")
                    self.page = page
                    self.is_logged_in = True
                    await self.page.bring_to_front()
                    return True
            except Exception as e:
                print(f"  检查标签页 {i+1} 失败: {e}")
                continue
        
        # 没有已登录的标签页，使用第一个或创建新页面
        if pages:
            self.page = pages[0]
        else:
            self.page = await self.context.new_page()
        
        # 访问 DeepSeek
        print("[ensure_login] 访问 DeepSeek...")
        await self.page.goto('https://chat.deepseek.com/', timeout=60000)
        await asyncio.sleep(3)
        
        # 检查登录状态
        html = await self.page.content()
        if "登录" not in html:
            self.is_logged_in = True
            print("✅ 已登录")
            return True
        
        # 需要登录 - 通知用户
        print("⚠️ 需要登录 DeepSeek")
        print(f"   请在 VNC 中完成登录（{timeout}秒）...")

        # 等待登录完成
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
    
    async def send_message(self, message: str, metadata: dict = None) -> str:
        """
        发送消息，立即返回 message_id，不等待回复
        
        Args:
            message: 消息内容
            metadata: 元数据字典（不会发送给 DeepSeek，仅用于记录）
                    可包含 priority, topic 等字段
        
        Returns:
            message_id: 用于后续获取响应的ID
        """
        if not await self.ensure_login():
            raise RuntimeError("未登录")
        
        import time
        message_id = f"msg_{int(time.time() * 1000)}"
        session_dir = Path(f"data/agent_responses/{self.platform_name}/{message_id}")
        session_dir.mkdir(parents=True, exist_ok=True)
        
        # 保存发送时的元信息（标记为发送中）
        meta = {
            "status": "sent",
            "query": message,
            "timestamp": message_id,
            "platform": self.platform_name,
        }
        # 合并外部传入的 metadata（如 priority、topic 等）
        if metadata:
            meta["metadata"] = metadata
        with open(session_dir / "metadata.json", 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
        
        # 发送消息
        print(f"🖱️  移动鼠标到输入框...")
        await self.page.wait_for_selector(
            'textarea', state='visible', timeout=TIMEOUTS["element_wait"] * 1000
        )
        await self.simulator.natural_click('textarea')
        await asyncio.sleep(0.5)
        
        print(f"⌨️  正在输入: {message[:30]}...")
        await self.simulator.natural_typing('textarea', message)
        
        # 获取发送前的最后一条 AI 消息文本作为基准（必须在发送前获取！）
        baseline_response = await self.extractor.extract_last_ai_response(self.page)
        baseline_text = baseline_response["text"] if baseline_response else ""
        
        print(f"🤔 思考中...")
        await self.simulator.think_delay()
        await self.page.keyboard.press('Enter')
        print(f"✅ 消息已发送: {message_id}")
        
        # 启动后台等待任务，传入基准文本
        asyncio.create_task(self._wait_and_save_response(message_id, session_dir, message, metadata, baseline_text))
        
        return message_id
    
    async def _wait_and_save_response(self, message_id: str, session_dir: Path, query: str, metadata: dict = None, baseline_text: str = ""):
        """
        后台任务：等待AI回复并保存到文件
        
        Args:
            message_id: 消息ID
            session_dir: 会话目录
            query: 发送的消息内容
            metadata: 外部元数据（来自调用者）
            baseline_text: 发送消息前的最后一条 AI 回复文本（用于对比）
        """
        try:
            # 基准文本已在发送前获取，直接使用
            print(f"[后台] 等待 AI 回复: {message_id} (基准长度: {len(baseline_text)})")
            # timeout = clamp(10s, query_len * 0.1 + 30s, 120s)
            query_len = len(message)
            adaptive_timeout = min(120, max(10, query_len * 10 // 1000 * 10 + 30))

            response_data = await self.extractor.wait_for_new_response(
                self.page,
                last_text=baseline_text,
                timeout=adaptive_timeout
            )
            
            # 保存响应
            if response_data:
                response_file = session_dir / "response.txt"
                with open(response_file, 'w', encoding='utf-8') as f:
                    f.write(response_data["text"])
                
                # 更新 metadata
                meta = {
                    "status": "completed",
                    "query": query,
                    "timestamp": message_id,
                    "platform": self.platform_name,
                    "response_length": len(response_data["text"]),
                }
                # 合并外部传入的 metadata
                if metadata:
                    meta["metadata"] = metadata
                with open(session_dir / "metadata.json", 'w', encoding='utf-8') as f:
                    json.dump(meta, f, indent=2, ensure_ascii=False)
                
                print(f"💾 回复已保存: {message_id}")
            else:
                # 超时
                meta = {
                    "status": "timeout",
                    "query": query,
                    "timestamp": message_id,
                    "platform": self.platform_name,
                }
                with open(session_dir / "metadata.json", 'w', encoding='utf-8') as f:
                    json.dump(meta, f, indent=2, ensure_ascii=False)
                print(f"⚠️ 回复超时: {message_id}")
                
        except Exception as e:
            print(f"❌ 保存回复失败: {message_id} - {e}")
            meta = {
                "status": "error",
                "query": query,
                "timestamp": message_id,
                "platform": self.platform_name,
                "error": str(e),
            }
            try:
                with open(session_dir / "metadata.json", 'w', encoding='utf-8') as f:
                    json.dump(meta, f, indent=2, ensure_ascii=False)
            except:
                pass
    
    async def get_response(self, message_id: str, timeout: int = 180) -> str:
        """
        从文件读取响应，等待直到准备好
        
        Args:
            message_id: send_message 返回的ID
            timeout: 超时秒数
            
        Returns:
            响应文本
            
        Raises:
            TimeoutError: 超时
            FileNotFoundError: 文件不存在
        """
        import time
        session_dir = Path(f"data/agent_responses/{self.platform_name}/{message_id}")
        response_file = session_dir / "response.txt"
        
        start_time = time.time()
        
        while True:
            # 检查文件是否存在且状态为 completed
            if response_file.exists():
                metadata_file = session_dir / "metadata.json"
                if metadata_file.exists():
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                    
                    if meta.get("status") == "completed":
                        with open(response_file, 'r', encoding='utf-8') as f:
                            return f.read()
                    elif meta.get("status") == "timeout":
                        raise TimeoutError(f"响应超时: {message_id}")
                    elif meta.get("status") == "error":
                        raise RuntimeError(f"响应错误: {meta.get('error', '未知错误')}")
            
            # 检查超时
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                raise TimeoutError(f"等待响应超时: {message_id}")
            
            # 等待1秒再试
            await asyncio.sleep(1)
    
    async def chat(self, message: str, metadata: dict = None, wait_for_reply: bool = True, 
                   save_response: bool = True, take_screenshot: bool = True) -> BridgeResponse:
        """
        发送消息并获取回复
        
        Args:
            message: 消息内容（会发送给 DeepSeek）
            metadata: 元数据字典（不会发送给 DeepSeek，仅记录）
                    可包含 priority, topic 等字段
            wait_for_reply: 是否等待回复
            save_response: 是否保存回复
            take_screenshot: 是否截图
        """
        try:
            # 发送消息，获取 message_id
            message_id = await self.send_message(message, metadata=metadata)
            
            if not wait_for_reply:
                return BridgeResponse(text="消息已发送", success=True)
            
            # 等待响应
            response_text = await self.get_response(message_id, timeout=180)
            
            return BridgeResponse(
                text=response_text,
                success=True,
                metadata={"message_id": message_id}
            )
            
        except TimeoutError as e:
            return BridgeResponse(text="", success=False, error=str(e))
        except Exception as e:
            return BridgeResponse(text="", success=False, error=str(e))


# 示例用法
async def demo():
    """演示用法"""
    bridge = DeepSeekBridge()
    await bridge.start()
    
    response = await bridge.chat(
        "你好 DeepSeek！我是一个 AI Agent，想请教智能体之间如何有效协作？"
    )
    
    if response.success:
        print(f"\n📝 DeepSeek 回复:\n{response.text[:500]}")
        if response.metadata:
            print(f"\n💾 消息ID: {response.metadata.get('message_id')}")
    else:
        print(f"❌ 错误: {response.error}")


if __name__ == "__main__":
    asyncio.run(demo())
