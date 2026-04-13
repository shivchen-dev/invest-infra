#!/usr/bin/env python3
"""
测试话题选取功能
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from deepseek_bridge import DeepSeekBridge

async def test_topics():
    bridge = DeepSeekBridge()
    
    print('='*70)
    print('测试话题选取功能')
    print('='*70)
    
    # 启动
    print('\n[1] 启动浏览器...')
    await bridge.start()
    
    # 确保登录
    print('\n[2] 检查登录状态...')
    await bridge.ensure_login()
    
    # 获取话题列表
    print('\n[3] 获取话题列表...')
    topics = await bridge.list_topics()
    print(f'找到 {len(topics)} 个话题:')
    for i, t in enumerate(topics[:10], 1):
        status = '●' if t['is_active'] else '○'
        print(f'  {i}. {status} {t["title"]} ({t["time"]})')
    
    # 获取当前话题
    print('\n[4] 获取当前话题...')
    current = await bridge.get_current_topic()
    print(f'当前话题: {current}')
    
    # 测试切换话题
    if topics:
        print('\n[5] 测试切换话题...')
        for t in topics:
            if not t['is_active']:
                print(f'尝试切换到: {t["title"]}')
                result = await bridge.switch_topic(t['title'])
                print(f'切换结果: {"成功" if result else "失败"}')
                break
    
    # 测试新建话题
    print('\n[6] 测试新建话题...')
    result = await bridge.new_chat()
    print(f'新建话题: {"成功" if result else "失败"}')
    
    print('\n' + '='*70)
    print('测试完成，按 Ctrl+C 关闭')
    print('='*70)
    
    # 保持运行
    try:
        while True:
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        pass
    
    await bridge.close()

if __name__ == "__main__":
    asyncio.run(test_topics())
