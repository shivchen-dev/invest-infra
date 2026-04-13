#!/usr/bin/env python3
"""
使用 DeepSeekBridge 正常流程问问题
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from deepseek_bridge import DeepSeekBridge

async def ask_question():
    bridge = DeepSeekBridge()
    
    print("="*70)
    print("启动 DeepSeek Bridge（使用成熟流程）")
    print("="*70)
    
    # 1. 启动（使用持久化上下文）
    print("\n[1] 启动浏览器...")
    await bridge.start()
    
    # 2. 确保登录（会自动检测，需要时提示扫码）
    print("\n[2] 检查登录状态...")
    is_logged_in = await bridge.ensure_login()
    
    if not is_logged_in:
        print("\n❌ 登录未完成")
        await bridge.close()
        return
    
    # 3. 测试话题功能
    print("\n[3] 测试话题列表...")
    topics = await bridge.list_topics()
    print(f"找到 {len(topics)} 个话题:")
    for t in topics[:5]:
        status = "●" if t['is_active'] else "○"
        print(f"  {status} {t['title'][:40]}")
    
    # 4. 切换到 qmd 话题
    print("\n[4] 尝试切换到 'qmd工具' 话题...")
    result = await bridge.switch_topic("qmd")
    if result:
        print("✅ 切换成功")
    else:
        print("⚠️ 切换失败，可能话题不存在")
    
    # 5. 发送消息
    print("\n[5] 发送测试消息...")
    response = await bridge.chat("你好，测试话题切换功能")
    
    if response.success:
        print(f"\n✅ 回复: {response.text[:200]}...")
    else:
        print(f"❌ 错误: {response.error}")
    
    print("\n" + "="*70)
    print("测试完成，保持运行...")
    print("="*70)
    
    try:
        while True:
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        pass
    
    await bridge.close()

if __name__ == "__main__":
    asyncio.run(ask_question())
