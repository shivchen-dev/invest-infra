# Session: 2026-04-18 14:14:53 UTC

- **Session Key**: agent:main:qqbot:direct:dd8c13beae9d9d0207d4de98f32eadef
- **Session ID**: a3d071cf-d512-438c-830d-61f0e0e4968c
- **Source**: qqbot

## Conversation Summary

user: Conversation info (untrusted metadata):
```json
{
  "message_id": "ROBOT1.0_RPQaJCilLy7lIrkKrVSNnpRcVmkl7xgNJYhQhZCblnnEwBZ2snar9FL80DikpcwAo4Dws9hrl-KuR4pvWW-eBVKTBl0bDXXBybve5OK.Tdk!",
  "sender_id": "DD8C13BEAE9D9D0207D4DE98F32EADEF",
  "sender": "DD8C13BEAE9D9D0207D4DE98F32EADEF",
  "timestamp": "Fri 2026-04-17 06:14 UTC"
}
```

Sender (untrusted metadata):
```json
{
  "label": "DD8C13BEAE9D9D0207D4DE98F32EADEF",
  "id": "DD8C13BEAE9D9D0207D4DE98F32EADEF"
}
```

[QQBot] to=qqbot:c2c:DD8C13BEAE9D9D0207D4DE98F32EADEF

智能体桥系统有推荐给智能代理方便使用的模式吗？比如cli，mcp,api,技能
assistant: 目前 agent-bridge 提供两种使用模式：

---

## 1. Python API（直接 import）⭐ 主力模式

通过直接导入 `Bridge` 类调用，是核心方式：

```python
from deepseek_bridge import DeepSeekBridge
from qwen_bridge import QwenBridge

bridge = DeepSeekBridge()
await bridge.start()
await bridge.ensure_login(timeout=120)
result = await bridge.chat('问题')
await bridge.close()
```

特点：
- 完整异步控制浏览器
- 支持多轮对话（复用同一 Bridge 实例保持上下文）
- Profile 隔离（`data/profiles/deepseek/` / `qwen/`）

---

## 2. OpenClaw Skill（`agent-bridge-ask`）

给 Agent 调用的封装技能，触发词：
> "问下 DeepSeek"、"问问 AI"、"让 AI 看看"、"直接问智能体"

底层走的还是上面的 Python import 方式。

---

## 没有覆盖的模式

| 模式 | 状态 |
|------|------|
| CLI | ❌ 不存在 |
| MCP Server | ❌ 不存在 |
| HTTP API | ❌ 不存在（不走 HTTP，是浏览器自动化） |
| 独立服务 | ❌ 无 |

---

**架构本质**是浏览器自动化（Playwright），Bridge 控制浏览器登录网页版 DeepSeek/Qwen，再模拟用户操作发消息。不是 HTTP API 服务。

需要我扩展成 MCP 或 HTTP API 模式吗？
user: Conversation info (untrusted metadata):
```json
{
  "message_id": "ROBOT1.0_RPQaJCilLy7lIrkKrVSNngayjuTM.EdoHyx7SZTcwQ3O7TuOW8TysXzdvbvI6zyr3EbsIbxh6HpIS18tv57ZFlKTBl0bDXXBybve5OK.Tdk!",
  "sender_id": "DD8C13BEAE9D9D0207D4DE98F32EADEF",
  "sender": "DD8C13BEAE9D9D0207D4DE98F32EADEF",
  "timestamp": "Fri 2026-04-17 06:21 UTC"
}
```

Sender (untrusted metadata):
```json
{
  "label": "DD8C13BEAE9D9D0207D4DE98F32EADEF",
  "id": "DD8C13BEAE9D9D0207D4DE98F32EADEF"
}
```

[QQBot] to=qqbot:c2c:DD8C13BEAE9D9D0207D4DE98F32EADEF

你推荐哪个？
assistant: **推荐 HTTP API**，理由：

1. **语言无关** — 任何 Agent（无论用 Python/JS/其他）都能调用
2. **解耦** — Agent 和 Bridge 服务独立运行，不绑定进程
3. **易于托管** — 可以 Docker 部署，做成长期服务
4. **适合 Agent 场景** — Agent 发 HTTP 请求比 import 模块更自然

---

**次推 MCP**，如果你希望：
- Agent 调用时用标准 Tool Call 协议
- Bridge 能力直接暴露给支持 MCP 的 Agent（OpenClaw 本身支持 MCP）

---

**不建议走 CLI**：Shell 调用笨重，不适合异步 Agent 流程。

---

**要启动哪个？**

如果你有明确需求，告诉我使用场景（比如给什么 Agent 用、调用频率），我帮你选并设计接口。如果只是想完善架构，两个都可以规划。
