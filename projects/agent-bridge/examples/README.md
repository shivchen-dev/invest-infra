# DeepSeek Bridge 使用示例

本目录包含 DeepSeek Bridge 的生产就绪使用示例。

## 快速开始

### 1. 简单对话
```bash
cd /home/chenjian/.openclaw/workspace-browser/projects/active/copilot-bridge
python3 examples/chat_simple.py
```

功能：
- 自动启动浏览器
- 检测登录状态（未登录会提示扫码）
- 发送消息并获取回复
- 自动保存回复内容

### 2. 话题管理
```bash
python3 examples/chat_with_topics.py
```

功能：
- 列出所有历史话题
- 切换到指定话题
- 新建话题

### 3. Agent 调用
```python
from examples.agent_demo import ask_deepseek

answer = await ask_deepseek("你的问题")
print(answer)
```

## 文件说明

| 文件 | 用途 | 复杂度 |
|------|------|--------|
| `chat_simple.py` | 最简单的使用方式 | ⭐ |
| `chat_with_topics.py` | 带话题管理 | ⭐⭐ |
| `agent_demo.py` | Agent 集成 | ⭐⭐⭐ |

## 核心库

所有示例都基于 `src/deepseek_bridge.py`：

```python
from deepseek_bridge import DeepSeekBridge

bridge = DeepSeekBridge()
await bridge.start()
await bridge.ensure_login()

# 对话
response = await bridge.chat("你好")
print(response.text)

# 话题管理
topics = await bridge.list_topics()
await bridge.switch_topic("话题名")
await bridge.new_chat()

await bridge.close()
```

## 数据存储

- 浏览器数据：`data/browser_profile_deepseek/`
- 回复记录：`data/agent_responses/deepseek/`
- 截图：`data/screenshots/`

## 注意事项

1. **首次使用**需要扫码登录
2. **登录状态**会持久化保存（通常几小时有效）
3. **VNC 地址**：`172.22.224.123:5900`（如需手动操作）
