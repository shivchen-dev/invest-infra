# Agent Bridge

name: agent-bridge
version: 2.0.0
description: 多智能体（Multi-Agent）对话桥接系统 - 支持 DeepSeek / Copilot / 未来可扩展

## 项目定位

**Agent Bridge** 是 OpenClaw 生态中的**智能体对话基础设施**。

支持多个 AI 平台的长连接对话，供其他 Agent 调用，实现真正的多智能体协作。

## 支持平台

| 平台 | 状态 | 文件 |
|------|------|------|
| DeepSeek | ✅ 生产就绪 | `src/deepseek_bridge.py` |
| Microsoft Copilot | ✅ 可用 | `src/copilot_bridge.py` |
| Claude | 📝 计划中 | - |
| GPT | 📝 计划中 | - |

## 项目结构

```
agent-bridge/
├── src/                    # 核心库
│   ├── deepseek_bridge.py  # DeepSeek 桥接 ⭐ 推荐
│   ├── copilot_bridge.py   # Copilot 桥接
│   ├── copilot_api.py      # HTTP API 服务
│   └── ...                 # 其他模块
│
├── examples/               # 使用示例 ⭐
│   ├── chat_simple.py      # 简单对话
│   ├── chat_with_topics.py # 话题管理
│   └── agent_demo.py       # Agent 集成
│
├── tests/                  # 测试脚本
├── data/                   # 数据目录
└── docs/                   # 文档
```

## 快速开始

### 安装依赖
```bash
pip install playwright
playwright install chromium
```

### 简单对话
```bash
cd /home/chenjian/.openclaw/workspace-browser/projects/active/agent-bridge
python3 examples/chat_simple.py
```

### Agent 集成
```python
from examples.agent_demo import ask_deepseek

# 使用 DeepSeek
answer = await ask_deepseek("你的问题")
print(answer)
```

## 核心功能

- ✅ **多平台支持** - DeepSeek、Copilot
- ✅ **持久化登录** - Cookie 保存，长期有效
- ✅ **话题管理** - 列表、切换、新建
- ✅ **人类行为模拟** - 自然打字，降低检测
- ✅ **Agent 友好** - 供其他 Agent 调用

## 环境要求

- Python 3.8+
- Playwright
- Chromium 浏览器
- Xvfb (Linux)

## 配置

```bash
# 代理（如需）
export HTTP_PROXY=http://192.168.6.50:7890
export HTTPS_PROXY=http://192.168.6.50:7890

# VNC（手动操作）
# 172.22.224.123:5900
```

## API 端点（Copilot）

- `GET /health` - 健康检查
- `GET /stats` - 会话统计
- `POST /init` - 初始化桥接
- `POST /ask` - 发送消息
- `POST /close` - 关闭桥接

## 演进历史

- **v1.0** - Copilot Bridge（单一平台）
- **v2.0** - Agent Bridge（多平台、多智能体支持）

## 未来规划

- [ ] Claude Bridge
- [ ] GPT Bridge
- [ ] 统一多平台 API
- [ ] Agent 编排调度
