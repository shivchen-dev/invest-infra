"""
Copilot Bridge v2.0 优化版测试脚本
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from copilot_bridge_v2 import CopilotBridgeV2


async def test_optimized():
    """测试优化版本"""
    print("=" * 60)
    print("Copilot Bridge v2.0 优化版测试")
    print("=" * 60)
    
    # 使用调试模式，保存截图和HTML
    bridge = CopilotBridgeV2(headless=True, rate_limit=True, debug=True)
    
    try:
        await bridge.start()
        
        # 测试1: 简单问候
        print("\n[测试1] 简单问候...")
        response = await bridge.ask("你好，请用一句话介绍自己", timeout=90)
        print(f"回复: {response.text}")
        print(f"长度: {len(response.text)} 字符")
        
        # 测试2: 技术问题
        print("\n[测试2] 技术问题...")
        response = await bridge.ask("Python是什么？", timeout=90)
        print(f"回复: {response.text[:300]}...")
        print(f"长度: {len(response.text)} 字符")
        
        # 统计信息
        print("\n[统计信息]")
        stats = bridge.get_stats()
        print(f"对话轮数: {stats['turn_count']}")
        print(f"代理: {stats['proxy']}")
        
        print("\n" + "=" * 60)
        print("✅ 测试完成!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        await bridge.close()


if __name__ == "__main__":
    asyncio.run(test_optimized())
