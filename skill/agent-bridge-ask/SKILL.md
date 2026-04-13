---
name: agent-bridge-ask
description: 通过直接 import 调用 Agent Bridge 模块向 DeepSeek/Qwen 提问。适用于无法使用 HTTP API 时（如服务未启动）。传入 message，直接调用 Bridge 类，返回结构化回答。触发场景：用户说"问下 DeepSeek"、"问问 AI"、"咨询智能体"、"让 AI 看看"、"帮我分析这个问题"、"直接问智能体"。
---

# Agent Bridge Ask

通过直接 import Bridge 模块调用，不走 HTTP API。

## 调用方式

### 在 exec 工具中调用

```bash
cd /home/claw/.openclaw/workspace/projects/agent-bridge && \
python3 -c "
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, 'src')
from deepseek_bridge import DeepSeekBridge

async def main():
    bridge = DeepSeekBridge(user_data_dir='data/profiles/deepseek')
    await bridge.start()
    await bridge.ensure_login(timeout=120)
    result = await bridge.chat('你的问题')
    print(result.text)
    await bridge.close()

asyncio.run(main())
"
```

### Python 代码调用

```python
import sys
import asyncio
from pathlib import Path

# 添加 Bridge 路径
BRIDGE_ROOT = Path("/home/claw/.openclaw/workspace/projects/agent-bridge")
sys.path.insert(0, str(BRIDGE_ROOT / "src"))

from deepseek_bridge import DeepSeekBridge
from qwen_bridge import QwenBridge

async def ask_deepseek(message: str) -> dict:
    bridge = DeepSeekBridge(
        user_data_dir=f"{BRIDGE_ROOT}/data/profiles/deepseek"
    )
    try:
        if not await bridge.start():
            return {"success": False, "error": "启动浏览器失败"}
        if not await bridge.ensure_login(timeout=120):
            return {"success": False, "error": "登录失败"}
        result = await bridge.chat(message)
        return {
            "success": True,
            "response": result.text,
            "session_id": bridge.current_session_id,
            "error": None
        }
    finally:
        await bridge.close()

async def ask_qwen(message: str) -> dict:
    bridge = QwenBridge(
        user_data_dir=f"{BRIDGE_ROOT}/data/profiles/qwen"
    )
    try:
        if not await bridge.start():
            return {"success": False, "error": "启动浏览器失败"}
        if not await bridge.ensure_login(timeout=120):
            return {"success": False, "error": "登录失败"}
        result = await bridge.chat(message)
        return {
            "success": True,
            "response": result.text,
            "session_id": bridge.current_session_id,
            "error": None
        }
    finally:
        await bridge.close()
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
3. **Profile 隔离**：每个平台用独立 Profile（deepseek/qwen）
4. **登录状态**：Bridge 会自动复用已登录的 Profile，无需每次登录
5. **VNC 地址**：如需手动登录，参见 `projects/agent-bridge/src/config.py` 中的 `VNC_ADDRESS`
