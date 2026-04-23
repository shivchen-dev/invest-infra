#!/usr/bin/env python3
"""
咨询 DeepSeek：Agent Bridge 长文本输入响应提取问题
"""
import sys
import asyncio
from pathlib import Path

BRIDGE_ROOT = Path('/home/claw/.openclaw/workspace/projects/agent-bridge')
sys.path.insert(0, str(BRIDGE_ROOT / 'src'))

from deepseek_bridge import DeepSeekBridge


CONSULT_TOPIC = "Agent Bridge 长文本响应提取问题"


CONSULT_ROUND1 = """# Agent Bridge 响应提取问题咨询（第一轮）

## 项目背景

Agent Bridge 是 AI 智能体桥接系统，通过 Playwright 浏览器自动化与 DeepSeek 网页版对话。核心流程：

1. `send_message()` - 填入 textarea，按 Enter 发送，返回 message_id
2. `_wait_and_save_response()` - 后台任务，等待 AI 回复并保存
3. `get_response()` - 轮询文件，直到 status=completed

**关键技术实现：**
- 持久化 Chrome Profile（保持登录状态）
- `HumanBehaviorSimulator` - 拟人化打字、随机延迟
- `ResponseExtractor` - DOM 选择器提取 AI 回复
- Xvfb 虚拟桌面（无头运行）

---

## 当前响应提取逻辑（wait_for_new_response）

策略：
1. 发送前获取基准文本（baseline）
2. 等 3 秒让 DeepSeek 开始打字
3. 每 2 秒轮询提取最后一条 AI 回复
4. **连续 3 次内容不变且长度 > 阈值 → 认定完成**
5. 同时检测"停止生成"按钮消失 → 辅助判断

关键代码：
```python
STABLE_COUNT = 3       # 连续 N 次稳定则认定完成
POLL_INTERVAL = 2      # 轮询间隔（秒）
PRE_WAIT = 3

# 稳定性判断
if current_text == last_content:
    stable_unchanged += 1
    if stable_unchanged >= STABLE_COUNT:
        return response  # 认定完成
```

---

## 问题：长文本输入时响应丢失

**症状：**
- 短问答（1+1=2）→ ✅ 正常完成
- 长咨询（2000+ 字的问题）→ ❌ 180 秒超时，status=timeout

**初步分析：**
DeepSeek 生成长文本时是**流式输出**，每 2 秒轮询可能只吐出几个新字符，导致 `current_text == last_content` 在大部分轮询中为真。但因为还没达到 `STABLE_COUNT=3`，且停止按钮可能还在，逻辑没有提前终止。

**疑点：**
1. 流式输出场景下，2 秒间隔是否太短？
2. `STABLE_COUNT=3` 对流式生成是否不适用？
3. 停止按钮检测是否可靠？
4. 180 秒超时对长回复是否够用？

---

## 咨询问题

1. 这个响应提取策略对流式输出场景有什么根本性问题？
2. 有哪些更好的检测完成的策略？（除了 DOM 选择器 + 停止按钮，还有什么？）
3. 超时时间应该如何动态计算（根据问题长度预估？）？
4. 你建议的核心修复思路是什么？

第二轮我会问：错误处理与重试、多标签页场景、上下文积累问题。
"""


def make_round2_template(r1_text: str) -> str:
    return f"""# Agent Bridge 响应提取问题咨询（第二轮）

## 第一轮回答摘要

{r1_text[:1500] if r1_text else '(无内容)'}

---

## 第二轮问题

基于你的建议，我想深入：

1. **如果采用"停止按钮检测 + 动态超时"策略**，具体如何实现？超时时间按输入长度比例计算，比例大概多少合适？

2. **多轮对话场景**：同一会话中连续发送多条消息，每次发送后等待响应。当前实现每次都重新创建 `_wait_and_save_response` 后台任务。这样有什么潜在问题？

3. **页面 DOM 结构变化**：如果 DeepSeek 网页改版后选择器失效，有没有自动适应或降级策略？

4. **流式响应期间如果页面滚动**（AI 回复太长导致页面自动滚动），会不会影响 DOM 元素选择？需要锁定在目标消息元素上吗？

请给出具体代码级别的建议。
"""


async def main():
    bridge = DeepSeekBridge()
    try:
        print("🚀 启动 Bridge...")
        if not await bridge.start():
            print("❌ 启动失败")
            return
        if not await bridge.ensure_login(timeout=120):
            print("❌ 登录失败")
            return

        # === 第一轮 ===
        print(f"\n📤 [{CONSULT_TOPIC}] 第一轮...")
        r1 = await bridge.chat(CONSULT_ROUND1, metadata={"topic": CONSULT_TOPIC, "round": 1})
        print(f"\n✅ 第一轮完成 (长度: {len(r1.text) if r1.text else 0})")
        if r1.text:
            print(f"--- 开头 500 字 ---\n{r1.text[:500]}")
        else:
            print(f"❌ 第一轮无响应: {r1.error}")

        if not r1.text:
            return

        # === 第二轮 ===
        print(f"\n📤 [{CONSULT_TOPIC}] 第二轮...")
        round2_query = make_round2_template(r1.text)
        r2 = await bridge.chat(round2_query, metadata={"topic": CONSULT_TOPIC, "round": 2})
        print(f"\n✅ 第二轮完成 (长度: {len(r2.text) if r2.text else 0})")
        if r2.text:
            print(f"--- 开头 800 字 ---\n{r2.text[:800]}")
        else:
            print(f"❌ 第二轮无响应: {r2.error}")

    finally:
        await bridge.close()
        print("\n🔒 Bridge 已关闭")


if __name__ == "__main__":
    asyncio.run(main())
