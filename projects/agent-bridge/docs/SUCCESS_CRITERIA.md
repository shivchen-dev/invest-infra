# agent-bridge 项目成功标准

## ✅ 项目目标

为 OpenClaw Agent 提供可靠的浏览器自动化对话能力，支持 DeepSeek、Qwen、小红书等平台。

---

## 成功标准

| 功能 | 标准 |
|------|------|
| DeepSeek 对话 | 能发送消息并获取有效回复 |
| Qwen 对话 | 能发送消息并获取有效回复 |
| 小红书搜索 | 能执行搜索并获取笔记列表 |
| 话题连续性 | 多轮对话保持上下文 |
| 登录态保持 | 浏览器关闭后重新打开仍保持登录 |

---

## 验证方法

```python
# DeepSeek Bridge
bridge = DeepSeekBridge()
await bridge.start()
await bridge.ensure_login(timeout=120)
r = await bridge.chat('1+1等于几？')
assert len(r.text) > 0
assert '2' in r.text

# 话题连续性
r2 = await bridge.chat('那2+2呢？')
assert '4' in r2.text
```

---

## 当前状态

- ✅ DeepSeekBridge 已实现
- ✅ QwenBridge 已实现
- ✅ XiaohongshuBridge 已实现
- ✅ 话题连续性已修复
- ⏳ MCP server 集成待完成

---

*2026-04-16*
