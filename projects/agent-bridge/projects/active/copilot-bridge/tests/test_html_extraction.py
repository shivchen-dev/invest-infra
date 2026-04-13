#!/usr/bin/env python3
"""
DeepSeek Bridge - 使用 HTML 提取版本（无截图）
验证 HTML 提取的准确性
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from deepseek_bridge import DeepSeekBridge


async def test_html_extraction():
    """测试 HTML 提取功能"""
    bridge = DeepSeekBridge()
    
    # 启动浏览器
    if not await bridge.start():
        print("❌ 启动失败")
        return
    
    # 确保登录
    print("请在 VNC 中完成登录...")
    if not await bridge.ensure_login(timeout=120):
        print("❌ 登录失败")
        return
    
    # 发送测试问题
    msg = "一张 10M 的照片使用 3060 显卡处理 comfyui 光影工作流能胜任吗？请详细分析显存占用、处理速度和优化建议。"
    
    print(f"\n发送消息: {msg}")
    
    # 使用 HTML 提取，不截图
    response = await bridge.chat(msg, save_response=True, take_screenshot=False)
    
    if response.success:
        print(f"\n{'='*70}")
        print("✅ HTML 提取成功！")
        print(f"{'='*70}\n")
        print(f"📝 回复内容:\n{response.text}\n")
        print(f"💾 保存路径: {response.saved_path}")
        
        # 验证保存的文件
        import os
        if response.saved_path:
            files = os.listdir(response.saved_path)
            print(f"\n📁 文件列表:")
            for f in files:
                size = os.path.getsize(os.path.join(response.saved_path, f))
                print(f"  - {f} ({size} bytes)")
    else:
        print(f"❌ 错误: {response.error}")
    
    # 保持运行
    print("\n浏览器保持运行，按 Ctrl+C 结束")
    try:
        while True:
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        pass
    
    await bridge.close()


if __name__ == "__main__":
    asyncio.run(test_html_extraction())
