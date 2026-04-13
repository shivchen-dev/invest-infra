"""
Copilot Bridge 测试脚本
用于验证连接和基本功能
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from copilot_bridge import CopilotBridge


async def test_basic():
    """基础功能测试"""
    print("=" * 60)
    print("Copilot Bridge 基础测试")
    print("=" * 60)
    
    bridge = CopilotBridge(headless=False, rate_limit=True)
    
    try:
        # 测试1: 启动会话
        print("\n[测试1] 启动会话...")
        await bridge.start()
        print("✅ 会话启动成功")
        
        # 测试2: 简单对话
        print("\n[测试2] 发送简单消息...")
        response = await bridge.ask("你好，请用一句话介绍你自己", timeout=60)
        print(f"✅ 收到回复 (长度: {len(response.text)} 字符)")
        print(f"回复预览: {response.text[:100]}...")
        
        # 测试3: 技术问题
        print("\n[测试3] 发送技术问题...")
        response = await bridge.ask("Python 中 async/await 的作用是什么？", timeout=60)
        print(f"✅ 收到回复 (长度: {len(response.text)} 字符)")
        
        # 测试4: 统计信息
        print("\n[测试4] 获取统计信息...")
        stats = bridge.get_stats()
        print(f"✅ 统计: {stats}")
        
        print("\n" + "=" * 60)
        print("所有测试通过! ✅")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        await bridge.close()


async def test_multi_turn():
    """多轮对话测试"""
    print("=" * 60)
    print("Copilot Bridge 多轮对话测试")
    print("=" * 60)
    
    bridge = CopilotBridge(headless=False, rate_limit=True)
    
    try:
        await bridge.start()
        
        # 连续对话
        questions = [
            "什么是机器学习？",
            "能举一个具体的应用例子吗？",
            "Python 中有哪些常用的机器学习库？",
        ]
        
        for i, q in enumerate(questions, 1):
            print(f"\n[第 {i} 轮] {q}")
            response = await bridge.ask(q, timeout=60)
            print(f"回复: {response.text[:150]}...")
            print("-" * 50)
        
        # 获取完整对话历史
        print("\n[对话历史摘要]")
        history = await bridge.get_conversation_history()
        print(f"共 {len(history)} 条消息")
        
    finally:
        await bridge.close()


async def test_rate_limit():
    """频率限制测试"""
    print("=" * 60)
    print("Copilot Bridge 频率限制测试")
    print("=" * 60)
    
    bridge = CopilotBridge(headless=False, rate_limit=True)
    
    try:
        await bridge.start()
        
        # 快速发送多条消息，观察频率控制
        for i in range(3):
            print(f"\n[消息 {i+1}] 发送中...")
            start = asyncio.get_event_loop().time()
            response = await bridge.ask(f"这是第 {i+1} 条测试消息", timeout=60)
            elapsed = asyncio.get_event_loop().time() - start
            print(f"耗时: {elapsed:.1f}s, 回复长度: {len(response.text)}")
        
    finally:
        await bridge.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Test Copilot Bridge')
    parser.add_argument('test', nargs='?', choices=['basic', 'multi', 'rate', 'all'], 
                       default='basic', help='测试类型')
    
    args = parser.parse_args()
    
    if args.test == 'basic':
        asyncio.run(test_basic())
    elif args.test == 'multi':
        asyncio.run(test_multi_turn())
    elif args.test == 'rate':
        asyncio.run(test_rate_limit())
    elif args.test == 'all':
        asyncio.run(test_basic())
        print("\n\n")
        asyncio.run(test_multi_turn())
