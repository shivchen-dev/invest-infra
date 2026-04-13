# Agent Bridge 项目

多智能体（Multi-Agent）对话桥接系统。

支持：DeepSeek / Microsoft Copilot / 未来可扩展其他 LLM

## 项目结构

```
agent-bridge/
├── src/                    # 核心库
│   ├── deepseek_bridge.py  # DeepSeek 桥接（生产就绪）⭐
│   ├── copilot_bridge.py   # Copilot 桥接
│   ├── copilot_api.py      # HTTP API 服务
│   ├── human_behavior_v2.py # 人类行为模拟
│   ├── agent_response_logger.py # 自动保存回复
│   ├── response_extractor.py    # 回复提取
│   └── utils.py            # 工具函数
│
├── examples/               # 使用示例（生产就绪）
│   ├── chat_simple.py      # 简单对话
│   ├── chat_with_topics.py # 话题管理
│   ├── agent_demo.py       # Agent 集成
│   └── README.md           # 使用说明
│
├── tests/                  # 测试脚本
│   └── (保留常用测试)
│
├── archive/                # 归档
│   └── tests/              # 历史测试脚本
│
├── data/                   # 数据目录
│   ├── browser_profile_deepseek/  # 持久化会话
│   ├── agent_responses/           # 自动保存的回复
│   └── screenshots/               # 截图
│
└── docs/                   # 文档
```

## 快速开始

### 简单对话
```bash
python3 examples/chat_simple.py
```

### 话题管理
```bash
python3 examples/chat_with_topics.py
```

### Agent 集成
```python
from examples.agent_demo import ask_deepseek
answer = await ask_deepseek("你的问题")
```

## 核心功能

- ✅ 多平台支持（DeepSeek、Copilot）
- ✅ 持久化登录（Cookie 保存）
- ✅ 话题管理（列表/切换/新建）
- ✅ 人类行为模拟（自然打字）
- ✅ 自动保存回复
- ✅ 多标签页检测

## 依赖

```bash
pip install playwright
playwright install chromium
```

## 配置

VNC 地址：`172.22.224.123:5900`（如需手动操作）

## 扩展计划

- [ ] Claude 桥接
- [ ] GPT 桥接
- [ ] 统一 API 接口
- [ ] Agent 编排管理
