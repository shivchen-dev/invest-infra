#!/usr/bin/env python3
"""
咨询 DeepSeek - 关于 Agent Bridge 接口设计
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from deepseek_bridge import DeepSeekBridge


async def main():
    """向 DeepSeek 咨询 Agent Bridge 设计建议"""
    
    question = """我正在开发一个名为 Agent Bridge 的开源项目，它允许 AI Agent 通过浏览器自动化与网页版 AI（如 DeepSeek、ChatGPT）进行对话。

项目核心功能：
- 自动管理登录状态（持久化 cookie）
- 模拟人类行为（打字、点击、滚动）
- 提取 AI 回复并保存
- 支持多话题切换

当前接口示例：
```python
agent = DeepSeekAgent()
await agent.initialize()
response = await agent.ask("你的问题")
```

问题：如何设计一个更简单、更易用的接口，让其他开发者能快速集成？请从 API 设计、错误处理、会话管理三个角度给出建议。"""

    bridge = DeepSeekBridge()
    
    try:
        print("🚀 启动 DeepSeek Bridge...")
        await bridge.start()
        
        print("检查登录状态...")
        if not await bridge.ensure_login():
            print("❌ 登录未完成")
            return
        
        print(f"\n发送咨询问题 ({len(question)} 字符)...")
        response = await bridge.chat(question)
        
        if response.success:
            print("\n" + "="*60)
            print("📝 DeepSeek 回复:")
            print("="*60)
            print(response.text)
            print("\n" + "="*60)
            print(f"✅ 回复长度: {len(response.text)} 字符")
            print(f"💾 保存位置: {response.saved_path}")
        else:
            print(f"❌ 错误: {response.error}")
        
    finally:
        await bridge.close()


if __name__ == "__main__":
    asyncio.run(main())
