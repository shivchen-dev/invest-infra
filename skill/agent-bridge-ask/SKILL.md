---
name: agent-bridge-ask
description: 通过直接 import 调用 Agent Bridge 模块向 DeepSeek/Qwen 提问。适用于无法使用 HTTP API 时（如服务未启动）。传入 message 和 template，直接调用 Bridge 类，返回结构化回答。触发场景：用户说"问下 DeepSeek"、"问问 AI"、"咨询智能体"、"让 AI 看看"、"帮我分析这个问题"、"直接问智能体"。
---

# Agent Bridge Ask

直接 import Bridge 模块调用，不走 HTTP API。

## 调用方式

### Python 代码调用

```python
import sys
import asyncio
from pathlib import Path

# 添加 Bridge 路径
BRIDGE_ROOT = Path("/home/chenjian/.openclaw/workspace-browser/projects/active/agent-bridge")
sys.path.insert(0, str(BRIDGE_ROOT / "src"))

from deepseek_bridge import DeepSeekBridge
from qwen_bridge import QwenBridge

async def ask_deepseek(message: str, template: str = "general_query") -> dict:
    """
    向 DeepSeek 提问
    
    Args:
        message: 问题内容
        template: 模板类型 (general_query|code_review|error_analysis|architecture_design)
    
    Returns:
        dict: {
            "success": bool,
            "response": str,      # AI 回答
            "session_id": str,    # 会话ID
            "error": str | None
        }
    """
    bridge = DeepSeekBridge(
        user_data_dir=f"{BRIDGE_ROOT}/data/profiles/deepseek"
    )
    
    try:
        # 1. 启动
        if not await bridge.start():
            return {"success": False, "error": "启动浏览器失败"}
        
        # 2. 确保登录
        if not await bridge.ensure_login(timeout=120):
            return {"success": False, "error": "登录失败"}
        
        # 3. 发送消息（自动复用 session 或创建新 session）
        result = await bridge.chat(message, template=template)
        
        return {
            "success": True,
            "response": result.text,
            "session_id": bridge.current_session_id,
            "error": None
        }
        
    finally:
        await bridge.close()


async def ask_qwen(message: str, template: str = "general_query") -> dict:
    """向 Qwen 提问，同上"""
    bridge = QwenBridge(
        user_data_dir=f"{BRIDGE_ROOT}/data/profiles/qwen"
    )
    
    try:
        if not await bridge.start():
            return {"success": False, "error": "启动浏览器失败"}
        
        if not await bridge.ensure_login(timeout=120):
            return {"success": False, "error": "登录失败"}
        
        result = await bridge.chat(message, template=template)
        
        return {
            "success": True,
            "response": result.text,
            "session_id": bridge.current_session_id,
            "error": None
        }
        
    finally:
        await bridge.close()
```

### 在 exec 工具中调用

```bash
cd /home/chenjian/.openclaw/workspace-browser/projects/active/agent-bridge && \
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
    result = await bridge.chat('你的问题', template='general_query')
    print(result.text)
    await bridge.close()

asyncio.run(main())
"
```

## BridgeResponse 结构

```python
@dataclass
class BridgeResponse:
    text: str           # AI 回答文本
    success: bool       # 是否成功
    error: str | None   # 错误信息
    metadata: dict | None  # 元信息（usage 等）
```

## 模板类型

| 模板 | 用途 | 传给 AI 的格式 |
|------|------|---------------|
| `general_query` | 通用查询 | 直接发送 message |
| `code_review` | 代码审查 | 添加代码审查提示词 |
| `error_analysis` | 错误分析 | 添加错误分析提示词 |
| `architecture_design` | 架构设计 | 添加架构设计提示词 |

详细说明见 [references/templates.md](references/templates.md)。

## 关键文件位置

| 文件 | 路径 |
|------|------|
| DeepSeekBridge | `projects/active/agent-bridge/src/deepseek_bridge.py` |
| QwenBridge | `projects/active/agent-bridge/src/qwen_bridge.py` |
| BaseBridge | `projects/active/agent-bridge/src/base_bridge.py` |
| 配置 | `projects/active/agent-bridge/src/config.py` |
| Profile 目录 | `projects/active/agent-bridge/data/profiles/{platform}/` |

## 注意事项

1. **异步调用**：所有 Bridge 方法都是 `async`，需要 `asyncio.run()` 或在 async 函数中调用
2. **资源释放**：必须 `await bridge.close()` 释放浏览器资源
3. **Profile 隔离**：每个平台用独立 Profile（deepseek/qwen）
4. **登录状态**：Bridge 会自动复用已登录的 Profile，无需每次登录
5. **模板支持**：模板只是给 AI 的提示词增强，实际是 `bridge.chat(message, template=)` 调用
