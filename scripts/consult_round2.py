#!/usr/bin/env python3
import sys, asyncio
from pathlib import Path
sys.path.insert(0, '/home/claw/.openclaw/workspace/projects/agent-bridge/src')
from deepseek_bridge import DeepSeekBridge

R1_TEXT = """核心矛盾：流式输出的"稳定判断"与"输出速度"之间的冲突

问题本质：
- 长文本：每2秒轮询可能只增加几十个字符
- 连续3次内容不变判定：需要至少6秒无变化
- 但2000字文本以50字/秒输出需要40秒
- 轮询间隔2秒太短 → 每次轮询都有微小变化 → 永远达不到"连续3次不变"

策略A：基于变化速率的自适应检测
策略B：事件驱动 + 最后块标记
策略C：混合检测机制
策略D：Token速率预测"""

CONSULT_ROUND2 = """# Agent Bridge 响应提取问题咨询（第二轮）

## 第一轮回答摘要
""" + R1_TEXT[:600] + """

---

## 第二轮问题

1. 如果采用"停止按钮检测 + 动态超时"策略，具体如何实现？超时按输入长度比例计算，比例大概多少？

2. 多轮对话场景：每次发送后等待响应，当前实现每次都重新创建后台任务。这样有什么潜在问题？

3. 如果 DeepSeek 网页改版后选择器失效，有没有自动适应或降级策略？

4. 流式响应期间如果页面自动滚动，会不会影响 DOM 元素选择？需要锁定目标消息元素吗？

请给出具体代码级别的建议。"""

async def main():
    bridge = DeepSeekBridge()
    try:
        if not await bridge.start():
            print('启动失败')
            return
        if not await bridge.ensure_login(timeout=120):
            print('登录失败')
            return
        print('发送第二轮...')
        r2 = await bridge.chat(CONSULT_ROUND2, metadata={'topic': 'longtext_consult', 'round': 2})
        print(f'第二轮完成，长度: {len(r2.text) if r2.text else 0}')
        if r2.text:
            print(r2.text[:800])
        else:
            print(f'无响应: {r2.error}')
    finally:
        await bridge.close()
        print('Bridge 已关闭')

asyncio.run(main())
