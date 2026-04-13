#!/usr/bin/env python3
"""
测试更新后的 ensure_login - 检查所有标签页
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from deepseek_bridge import DeepSeekBridge

async def test_updated_login():
    print("="*70)
    print("测试更新后的 ensure_login")
    print("="*70)
    
    bridge = DeepSeekBridge()
    
    print("\n[1] 启动浏览器...")
    await bridge.start()
    
    print("\n[2] 检查登录状态（新版 - 检查所有标签页）...")
    is_logged_in = await bridge.ensure_login()
    
    if is_logged_in:
        print("\n✅ 已找到登录状态")
        
        print("\n[3] 尝试提取话题...")
        topics = await bridge.list_topics()
        print(f"找到 {len(topics)} 个话题:")
        for t in topics[:10]:
            print(f"  - {t['title'][:50]}")
        
        print("\n[4] 尝试切换到 'qmd工具' 话题...")
        result = await bridge.switch_topic("qmd")
        if result:
            print("✅ 切换成功")
        else:
            print("❌ 切换失败，尝试其他话题...")
            if topics:
                result = await bridge.switch_topic(topics[0]['title'])
                print(f"切换到 '{topics[0]['title']}': {'成功' if result else '失败'}")
    else:
        print("\n❌ 未登录，需要扫码")
    
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
    asyncio.run(test_updated_login())
