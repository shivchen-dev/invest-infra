#!/usr/bin/env python3
"""
示例：带话题管理的 DeepSeek 对话
展示如何使用话题切换功能

使用方法:
    python3 examples/chat_with_topics.py

功能:
    1. 列出所有历史话题
    2. 切换到指定话题继续对话
    3. 或新建话题开始新对话
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from deepseek_bridge import DeepSeekBridge


async def main():
    """主函数"""
    bridge = DeepSeekBridge()
    
    try:
        # 启动并登录
        print("=" * 60)
        print("DeepSeek 话题管理示例")
        print("=" * 60)
        
        await bridge.start()
        if not await bridge.ensure_login():
            print("登录未完成")
            return
        
        # 1. 获取话题列表
        print("\n获取话题列表...")
        topics = await bridge.list_topics()
        
        if topics:
            print(f"\n找到 {len(topics)} 个话题:")
            for i, topic in enumerate(topics[:10], 1):
                status = "●" if topic.get('is_active') else "○"
                print(f"  {i}. {status} {topic['title'][:40]}")
        else:
            print("\n暂无话题")
        
        # 2. 选择操作
        print("\n选择操作:")
        print("  1. 切换到已有话题")
        print("  2. 新建话题")
        print("  3. 在当前话题继续")
        
        # 这里简化处理，直接新建话题演示
        print("\n[演示] 新建话题...")
        await bridge.new_chat()
        
        # 3. 发送消息
        message = "这是一个新话题的测试消息"
        print(f"\n发送: {message}")
        response = await bridge.chat(message)
        
        if response.success:
            print(f"\n回复:\n{response.text[:300]}...")
        
        print("\n" + "=" * 60)
        print("示例完成")
        print("=" * 60)
        
    finally:
        await bridge.close()


if __name__ == "__main__":
    asyncio.run(main())
