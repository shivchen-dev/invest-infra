---
name: agent-bridge-ask
description: 通过直接 import 调用 Agent Bridge 模块向 DeepSeek/Qwen 提问。适用于无法使用 HTTP API 时（如服务未启动）。传入 message，直接调用 Bridge 类，返回结构化回答。触发场景：用户说"问下 DeepSeek"、"问问 AI"、"咨询智能体"、"让 AI 看看"、"帮我分析这个问题"、"直接问智能体"。
---

# Agent Bridge Ask

通过直接 import Bridge 模块调用，不走 HTTP API。

## 核心原则

**话题连续性：同一个对话主题内，必须复用同一个 Bridge 实例。**

每次 `new DeepSeekBridge()` 都会创建新页面 → 断开上下文。

## 单轮问答

```python
import sys
import asyncio
sys.path.insert(0, '/home/claw/.openclaw/workspace/projects/agent-bridge/src')

from deepseek_bridge import DeepSeekBridge

async def main():
    bridge = DeepSeekBridge()
    await bridge.start()
    await bridge.ensure_login(timeout=120)
    result = await bridge.chat('你的问题')
    print(result.text)
    await bridge.close()

asyncio.run(main())
```

## 多轮连续对话（保持话题）

```python
import sys
import asyncio
sys.path.insert(0, '/home/claw/.openclaw/workspace/projects/agent-bridge/src')

from deepseek_bridge import DeepSeekBridge

async def main():
    bridge = DeepSeekBridge()
    await bridge.start()
    await bridge.ensure_login(timeout=120)

    # === 第一轮 ===
    result1 = await bridge.chat('第一轮问题')
    print('Round 1:', result1.text)

    # === 第二轮（同一 bridge 实例，上下文连续）===
    result2 = await bridge.chat('基于上轮回答的追问')
    print('Round 2:', result2.text)

    # === 第三轮（继续追问）===
    result3 = await bridge.chat('继续深入')
    print('Round 3:', result3.text)

    await bridge.close()  # 对话全部结束后关闭

asyncio.run(main())
```

## 完整模板：多轮咨询流程

```python
import sys
import asyncio
sys.path.insert(0, '/home/claw/.openclaw/workspace/projects/agent-bridge/src')

from deepseek_bridge import DeepSeekBridge
from qwen_bridge import QwenBridge

async def咨询流程(bridge, 话题: str, 第一轮问题: str, 第二轮问题_template: str):
    """
    通用多轮咨询流程。
    bridge: 已初始化的 Bridge 实例
    话题: 字符串，用于日志标记
    第一轮问题: 首次提出的完整问题
    第二轮问题_template: 基于第一轮回答，生成追问字符串的函数
    """
    print(f'=== [{话题}] 第一轮 ===')
    r1 = await bridge.chat(第一轮问题)
    print(r1.text[:500] if r1.text else '(无响应)')

    print(f'=== [{话题}] 第二轮 ===')
    第二轮问题 = 第二轮问题_template(r1.text)
    r2 = await bridge.chat(第二轮问题)
    print(r2.text[:500] if r2.text else '(无响应)')

    return r1, r2

async def main():
    # 根据平台选 bridge
    platform = 'deepseek'  # 或 'qwen'
    Bridge = DeepSeekBridge if platform == 'deepseek' else QwenBridge

    bridge = Bridge()
    await bridge.start()
    await bridge.ensure_login(timeout=120)

    # 执行多轮咨询
    r1, r2 = await 咨询流程(
        bridge,
        话题='项目架构咨询',
        第一轮问题='你的第一轮完整问题',
        第二轮问题_template=lambda r1: f'基于你的回复：{r1[:200]}... 追问：...'
    )

    await bridge.close()

asyncio.run(main())
```

## Python 代码调用封装

```python
import sys
import asyncio
from pathlib import Path

BRIDGE_ROOT = Path('/home/claw/.openclaw/workspace/projects/agent-bridge')
sys.path.insert(0, str(BRIDGE_ROOT / 'src'))

from deepseek_bridge import DeepSeekBridge
from qwen_bridge import QwenBridge

# === 单轮调用 ===
async def ask_deepseek(message: str) -> dict:
    bridge = DeepSeekBridge()
    try:
        if not await bridge.start():
            return {'success': False, 'error': '启动浏览器失败'}
        if not await bridge.ensure_login(timeout=120):
            return {'success': False, 'error': '登录失败'}
        result = await bridge.chat(message)
        return {'success': True, 'response': result.text, 'error': None}
    finally:
        await bridge.close()

# === 多轮调用（复用 bridge，保持话题） ===
class ContinuousConsultant:
    """多轮对话咨询器，保持同一会话"""

    def __init__(self, platform: str = 'deepseek'):
        Bridge = DeepSeekBridge if platform == 'deepseek' else QwenBridge
        self.bridge = Bridge()
        self.platform = platform

    async def __aenter__(self):
        await self.bridge.start()
        await self.bridge.ensure_login(timeout=120)
        return self

    async def __aexit__(self, *args):
        await self.bridge.close()

    async def ask(self, message: str, round_num: int = 1) -> dict:
        print(f'[{self.platform}] Round {round_num}: {message[:50]}...')
        result = await self.bridge.chat(message)
        return {'success': True, 'response': result.text, 'error': None}

# 使用方式：
async def main():
    async with ContinuousConsultant('deepseek') as consultant:
        r1 = await consultant.ask('第一轮问题', round_num=1)
        r2 = await consultant.ask('基于上轮的追问', round_num=2)
        r3 = await consultant.ask('继续深入', round_num=3)
        print('最终结论:', r3['response'])

asyncio.run(main())
```

## BridgeResponse 结构

```python
@dataclass
class BridgeResponse:
    text: str           # AI 回答文本
    success: bool       # 是否成功
    error: str | None   # 错误信息
    metadata: dict | None  # 元信息
```

## 关键文件位置

| 文件 | 路径 |
|------|------|
| DeepSeekBridge | `projects/agent-bridge/src/deepseek_bridge.py` |
| QwenBridge | `projects/agent-bridge/src/qwen_bridge.py` |
| BaseBridge | `projects/agent-bridge/src/base_bridge.py` |
| 配置 | `projects/agent-bridge/src/config.py` |
| Profile 目录 | `projects/agent-bridge/data/profiles/{platform}/` |

## 注意事项

1. **异步调用**：所有 Bridge 方法都是 `async`，需要 `asyncio.run()` 或在 async 函数中调用
2. **资源释放**：必须 `await bridge.close()` 释放浏览器资源
3. **话题连续性**：多轮对话必须**创建一次 bridge，发送多条消息，最后统一 close**。每次 new Bridge() 都会开新页面 → 上下文丢失
4. **Profile 隔离**：每个平台用独立 Profile（deepseek/qwen）
5. **VNC 地址**：如需手动登录，参见 `projects/agent-bridge/src/config.py` 中的 `VNC_ADDRESS`
6. **DeepSeek 构造函数**：不接受 `user_data_dir` 参数，使用类属性默认值
