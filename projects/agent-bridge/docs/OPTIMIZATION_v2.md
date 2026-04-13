# Copilot Bridge v2.0 优化说明

> 优化时间: 2026-04-04

---

## 🚀 优化内容

### 1. **回复抓取逻辑重构** (`_get_latest_response_v2`)

**原问题**: 抓取到 "Message Copilot" 等占位符文本

**优化方案**:
- ✅ 优先使用 `data-testid="chat-message"` 选择器
- ✅ 区分用户消息和助手消息
- ✅ 智能过滤占位符文本
- ✅ 多策略降级，确保能获取到内容

### 2. **响应完成检测** (`_wait_for_response_v2`)

**原问题**: 固定等待30秒后抓取，可能错过回复或抓错元素

**优化方案**:
- ✅ 实时检测 "停止生成" 按钮状态
- ✅ 文本变化检测（对比上次内容）
- ✅ 稳定检测（连续3次无变化认为完成）
- ✅ 动态等待，回复生成完成后立即返回

### 3. **调试模式** (`debug=True`)

**新增功能**:
- ✅ 自动保存错误截图 (`debug_screenshot_*.png`)
- ✅ 自动保存页面HTML (`debug_page_*.html`)
- ✅ 方便排查选择器问题

### 4. **选择器优化**

**更新选择器列表**:
```python
"input_box": [
    'textarea#userInput',
    'textarea[placeholder*="Message Copilot" i]',
    'textarea[placeholder*="Ask me anything" i]',
    'textarea[placeholder*="询问 anything" i]',
    ...
]
```

---

## 📁 文件位置

| 文件 | 说明 |
|------|------|
| `src/copilot_bridge_v2.py` | 优化版核心库 |
| `tests/test_v2.py` | 优化版测试脚本 |

---

## 🎯 使用方式

### 方式1: 命令行测试
```bash
cd /home/chenjian/.openclaw/workspace-browser/projects/active/copilot-bridge
source config/proxy.env
python3 tests/test_v2.py
```

### 方式2: Python 调用
```python
from copilot_bridge_v2 import CopilotBridgeV2

bridge = CopilotBridgeV2(
    headless=True,    # 无头模式
    rate_limit=True,  # 频率限制
    debug=True        # 调试模式（保存截图）
)

await bridge.start()
response = await bridge.ask("你好")
print(response.text)
await bridge.close()
```

---

## 🔍 如果还有问题

### 检查调试文件
测试失败时会生成：
- `debug_screenshot_*.png` - 页面截图
- `debug_page_*.html` - 页面源码

查看这些文件可以确认：
1. Copilot 是否正确加载
2. 回复是否已生成
3. 选择器是否匹配

### 手动检查
```bash
# 加载代理
source projects/active/copilot-bridge/config/proxy.env

# 直接访问 Copilot
playwright open https://copilot.microsoft.com/
```

---

## ⚡ 与原版的区别

| 功能 | 原版 | v2.0 优化版 |
|------|------|-------------|
| 回复检测 | 固定等待30秒 | 动态检测完成 |
| 选择器 | 基础选择器 | 多策略优先级 |
| 调试 | 仅错误截图 | 完整调试模式 |
| 过滤逻辑 | 简单长度过滤 | 智能内容识别 |
| 稳定性 | 可能抓错 | 多重验证 |

---

## 📝 建议

如果 v2.0 仍有问题，请：
1. 检查调试截图确认页面状态
2. 确认 Copilot 服务是否正常
3. 可能需要登录才能获取完整回复

---

*优化完成时间: 2026-04-04*
