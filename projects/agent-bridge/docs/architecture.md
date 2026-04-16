# Agent Bridge 架构文档

**版本**: v0.1.0
**日期**: 2026-04-16
**架构**: 直接 Import → Bridge → Browser

> ⚠️ API 方案已移除。当前版本不支持 HTTP API 调用，仅支持直接 import 调用。

---

## 架构概述

### 层级结构
```
┌─────────────────────────────────────┐
│  Caller (Python/Agent)              │  ← 直接 import 调用
│  - 传入消息                          │
│  - 获取 BridgeResponse               │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Bridge Layer (DeepSeekBridge)      │  ← 浏览器控制
│  - 启动/管理 Chrome (Playwright)      │
│  - 登录状态检测                      │
│  - 发送消息                          │
│  - 抓取回复                          │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Browser Layer (Chrome)             │  ← Web 自动化
│  - DeepSeek/Qwen 网站交互            │
└─────────────────────────────────────┘
```

### 调用方式

**直接 Import**（当前唯一方式）:
```python
import sys
sys.path.insert(0, '/path/to/agent-bridge/src')
from deepseek_bridge import DeepSeekBridge

bridge = DeepSeekBridge()
await bridge.start()
await bridge.ensure_login(timeout=120)
result = await bridge.chat('你好')
print(result.text)
await bridge.close()
```

---

## 文件结构

```
agent-bridge/
├── src/
│   ├── deepseek_bridge.py        # DeepSeek Bridge
│   ├── qwen_bridge.py            # Qwen Bridge
│   ├── xiaohongshu_bridge.py     # 小红书 Bridge
│   ├── base_bridge.py            # Bridge 基类
│   ├── config.py                 # 配置（VNC地址、超时等）
│   └── ...
├── skills/
│   └── agent-bridge-ask/         # OpenClaw skill
├── data/
│   └── browser_profile_*/       # 浏览器 Profile（登录态持久化）
└── CHANGELOG.md
```

---

## 支持的 Bridge

| Bridge | 平台 | 状态 |
|--------|------|------|
| DeepSeekBridge | DeepSeek | ✅ 生产 |
| QwenBridge | 通义千问 | ✅ 生产 |
| XiaohongshuBridge | 小红书 | ✅ 生产 |

---

## 技术要点

1. **话题连续性**：多轮对话必须复用同一个 Bridge 实例
2. **异步调用**：所有 Bridge 方法为 async，需 `asyncio.run()` 或在 async 函数中调用
3. **资源释放**：使用完后必须 `await bridge.close()` 释放浏览器资源
4. **Profile 隔离**：每个平台独立 Profile，登录态持久化

---

## 注意事项

- ❌ 不支持 HTTP API 调用（API 方案已移除）
- ❌ 不支持直接 curl/requests 调用
- ✅ 只能通过 Python import 方式调用
- ✅ 支持多轮对话（保持同一 Bridge 实例）

---

*文档版本: v0.1.0 | 2026-04-16*
