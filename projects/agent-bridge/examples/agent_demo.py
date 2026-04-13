#!/usr/bin/env python3
"""
示例：Agent 调用 DeepSeek
供其他 AI Agent 调用 DeepSeek 使用

使用方法:
    from examples.agent_demo import ask_deepseek
    
    response = await ask_deepseek("你的问题")
    print(response.text)

特点:
    - 保持会话长期运行
    - 自动管理登录状态
    - 结构化返回结果
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from deepseek_bridge import DeepSeekBridge, DeepSeekResponse
from typing import Optional


class DeepSeekAgent:
    """DeepSeek Agent 接口"""
    
    def __init__(self):
        self.bridge = DeepSeekBridge()
        self._initialized = False
    
    async def initialize(self) -> bool:
        """初始化（启动+登录）"""
        if self._initialized:
            return True
        
        await self.bridge.start()
        if await self.bridge.ensure_login():
            self._initialized = True
            return True
        return False
    
    async def ask(self, question: str, save: bool = True) -> Optional[str]:
        """
        向 DeepSeek 提问
        
        Args:
            question: 问题文本
            save: 是否保存回复
            
        Returns:
            回复文本，失败返回 None
        """
        if not self._initialized:
            if not await self.initialize():
                return None
        
        response = await self.bridge.chat(question, save_response=save)
        
        if response.success:
            return response.text
        return None
    
    async def close(self):
        """关闭连接"""
        await self.bridge.close()
        self._initialized = False


# 便捷函数
async def ask_deepseek(question: str) -> Optional[str]:
    """
    快速提问函数（自动管理生命周期）
    
    示例:
        answer = await ask_deepseek("Python 是什么？")
    """
    agent = DeepSeekAgent()
    try:
        return await agent.ask(question)
    finally:
        await agent.close()


# 使用示例
async def demo():
    """演示用法"""
    print("=" * 60)
    print("Agent 调用 DeepSeek 示例")
    print("=" * 60)
    
    # 方法1: 使用便捷函数（简单场景）
    print("\n[方法1] 便捷函数...")
    answer = await ask_deepseek("用一句话介绍 Python")
    if answer:
        print(f"回复: {answer[:200]}...")
    
    # 方法2: 使用 Agent 类（需要多次对话的场景）
    print("\n[方法2] Agent 类...")
    agent = DeepSeekAgent()
    
    if await agent.initialize():
        # 第一次提问
        answer1 = await agent.ask("什么是机器学习？")
        print(f"Q1 回复: {answer1[:200]}..." if answer1 else "失败")
        
        # 第二次提问（保持同一话题）
        answer2 = await agent.ask("能举一个机器学习的例子吗？")
        print(f"Q2 回复: {answer2[:200]}..." if answer2 else "失败")
    
    await agent.close()
    
    print("\n" + "=" * 60)
    print("示例完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(demo())
