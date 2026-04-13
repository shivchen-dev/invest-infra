"""
Copilot Bridge 快速测试（Headless 模式）
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from copilot_bridge import CopilotBridge


async def quick_test():
    """快速测试"""
    print("=" * 60)
    print("Copilot Bridge 快速测试 (headless 模式)")
    print("=" * 60)
    
    # 使用 headless=True 模式
    bridge = CopilotBridge(headless=True, rate_limit=True)
    
    try:
        print("\n[1] 启动浏览器...")
        await bridge.start()
        print("✅ 浏览器启动成功")
        
        print("\n[2] 发送测试消息...")
        response = await bridge.ask("你好，请用20个字以内介绍你自己")
        print(f"✅ 收到回复")
        print(f"\n🤖 Copilot 回复:\n{response.text}")
        
        print("\n[3] 获取统计...")
        stats = bridge.get_stats()
        print(f"✅ 统计: {stats}")
        
        print("\n" + "=" * 60)
        print("测试完成! ✅")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await bridge.close()


if __name__ == "__main__":
    asyncio.run(quick_test())
