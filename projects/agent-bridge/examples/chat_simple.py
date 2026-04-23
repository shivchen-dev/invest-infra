#!/usr/bin/env python3
"""
示例：简单的 DeepSeek 对话
最简单的使用方式，自动处理登录

使用方法:
    python3 examples/chat_simple.py

功能:
    1. 启动浏览器（自动使用持久化登录）
    2. 如未登录，提示扫码
    3. 发送消息并获取回复
    4. 自动保存回复到 data/agent_responses/
"""
import asyncio
import sys
from pathlib import Path

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from deepseek_bridge import DeepSeekBridge


async def main():
    """主函数"""
    bridge = DeepSeekBridge()
    
    try:
        # 1. 启动（自动使用持久化会话）
        print("启动 DeepSeek Bridge...")
        await bridge.start()
        
        # 2. 确保登录（未登录会提示扫码）
        print("检查登录状态...")
        if not await bridge.ensure_login():
            print("登录未完成")
            return
        
        # 3. 发送消息
        message = "你好，请介绍一下你自己"
        print(f"\n发送: {message}")
        response = await bridge.chat(message)
        
        # 4. 显示结果
        if response.success:
            print(f"\n回复:\n{response.text[:500]}...")
        else:
            print(f"错误: {response.error}")
        
    finally:
        # 5. 关闭
        await bridge.close()


if __name__ == "__main__":
    asyncio.run(main())
