"""
Copilot Bridge 快速测试 - 验证选择器修复
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from copilot_bridge import CopilotBridge


async def quick_test():
    """快速测试（不使用 Xvfb）"""
    print("=" * 60)
    print("Copilot Bridge 快速测试 - 选择器修复验证")
    print("=" * 60)
    
    # 设置代理
    os.environ['HTTP_PROXY'] = 'http://127.0.0.1:7890'
    os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:7890'
    
    # 不使用 Xvfb，直接用 headless 模式
    bridge = CopilotBridge(headless=True, rate_limit=True, use_xvfb=False)
    
    try:
        print("\n[1] 启动浏览器...")
        await bridge.start()
        print("✅ 浏览器启动成功")
        
        print("\n[2] 发送测试消息...")
        response = await bridge.ask("你好，请介绍一下 Copilot 能做什么？", timeout=90)
        print(f"✅ 收到回复")
        print(f"\n🤖 Copilot 回复:\n{'-'*50}")
        print(response.text[:500] if len(response.text) > 500 else response.text)
        print('-'*50)
        
        print("\n[3] 多轮对话测试...")
        response2 = await bridge.ask("Python 的 async/await 是什么？", timeout=90)
        print(f"✅ 收到回复")
        print(f"\n🤖 Copilot:\n{'-'*50}")
        print(response2.text[:500] if len(response2.text) > 500 else response2.text)
        print('-'*50)
        
        print("\n[4] 获取统计...")
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
