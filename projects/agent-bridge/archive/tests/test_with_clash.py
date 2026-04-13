"""
Copilot Bridge 代理测试（使用 Clash）

前提：Clash 已安装并运行在本地代理端口（默认 7890）
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from copilot_bridge import CopilotBridge


async def test_with_clash():
    """使用 Clash 代理测试"""
    print("=" * 60)
    print("Copilot Bridge + Clash 代理测试")
    print("=" * 60)
    
    # Clash 默认端口通常是 7890 或 7897
    # 方式1: 设置环境变量
    os.environ['HTTP_PROXY'] = 'http://127.0.0.1:7890'
    os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:7890'
    
    print(f"\n[配置] HTTP_PROXY = {os.getenv('HTTP_PROXY')}")
    print(f"[配置] HTTPS_PROXY = {os.getenv('HTTPS_PROXY')}")
    
    # 方式2: 直接传入代理地址
    # bridge = CopilotBridge(headless=True, proxy="http://127.0.0.1:7890")
    
    # 使用 Xvfb 虚拟桌面 + headless 模式
    bridge = CopilotBridge(headless=True, rate_limit=True, use_xvfb=True)
    
    try:
        print("\n[1] 启动浏览器并连接 Copilot...")
        await bridge.start()
        print("✅ 连接成功！")
        
        print("\n[2] 发送测试消息...")
        response = await bridge.ask("你好，请用20个字以内介绍你自己", timeout=60)
        print(f"✅ 收到回复")
        print(f"\n🤖 Copilot 回复:\n{response.text}")
        
        print("\n[3] 多轮对话测试...")
        response2 = await bridge.ask("Python 的 async/await 是什么？")
        print(f"\n🤖 Copilot:\n{response2.text[:300]}...")
        
        print("\n[4] 获取统计...")
        stats = bridge.get_stats()
        print(f"✅ 统计: {stats}")
        
        print("\n" + "=" * 60)
        print("测试完成! ✅")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        print("\n可能的原因:")
        print("1. Clash 未运行或端口不正确")
        print("2. Clash 配置中未开启 '允许局域网连接'")
        print("3. Copilot 页面结构发生变化")
        import traceback
        traceback.print_exc()
    finally:
        await bridge.close()


async def test_with_custom_proxy(proxy_url: str):
    """使用自定义代理测试"""
    print(f"使用代理: {proxy_url}")
    
    bridge = CopilotBridge(headless=True, rate_limit=True, proxy=proxy_url)
    
    try:
        await bridge.start()
        response = await bridge.ask("你好")
        print(f"回复: {response.text[:200]}")
    finally:
        await bridge.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Test Copilot Bridge with Clash proxy')
    parser.add_argument('--proxy', type=str, default=None, 
                       help='代理地址，如 http://127.0.0.1:7890')
    
    args = parser.parse_args()
    
    if args.proxy:
        asyncio.run(test_with_custom_proxy(args.proxy))
    else:
        asyncio.run(test_with_clash())
