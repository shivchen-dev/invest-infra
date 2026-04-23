# Agent Bridge

> DeepSeek / 通义千问 浏览器自动化对话桥接

通过 Playwright 浏览器自动化，与 DeepSeek / 通义千问 网页版对话，供 AI Agent 调用。

**版本**: v0.2.0

---

## 支持平台

| 平台 | 状态 | Bridge |
|------|------|--------|
| DeepSeek | ✅ 生产可用 | `DeepSeekBridge` |
| 通义千问 | ✅ 生产可用 | `QwenBridge` |

---

## 项目结构

```
agent-bridge/
├── src/
│   ├── deepseek_bridge.py     # DeepSeek 桥接
│   ├── qwen_bridge.py         # 通义千问桥接
│   ├── base_bridge.py         # 公共基类
│   ├── response_extractor.py  # AI 回复提取
│   ├── human_behavior_v2.py   # 人类行为模拟
│   └── config.py              # 配置
├── data/
│   ├── browser_profile_*      # 浏览器持久化 profile
│   ├── agent_responses/       # AI 回复日志
│   └── screenshots/           # 截图
├── examples/                  # 使用示例
├── scripts/                   # 工具脚本
└── agent_bridge_mcp/          # MCP server（开发中）
```

---

## 快速开始

```python
import sys, asyncio
sys.path.insert(0, 'src')

from deepseek_bridge import DeepSeekBridge

async def main():
    bridge = DeepSeekBridge()
    await bridge.start()
    await bridge.ensure_login(timeout=120)

    result = await bridge.chat('你好 DeepSeek')
    print(result.text)

    await bridge.close()

asyncio.run(main())
```

---

## 核心功能

- ✅ 持久化登录（Chrome Profile）
- ✅ 话题连续性（多轮对话）
- ✅ 人类行为模拟（自然打字、随机延迟）
- ✅ 流式响应完成检测（速度下降算法）
- ✅ 自适应超时

---

## 环境要求

- Python 3.8+
- Playwright
- Chromium（自动下载或系统安装）
- Xvfb（Linux 无头模式）

## 安装

```bash
pip install playwright
playwright install chromium
```

---

## 调用方式

通过 `agent-bridge-ask` skill（OpenClaw）调用，或直接 import。
