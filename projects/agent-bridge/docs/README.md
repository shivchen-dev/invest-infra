# Microsoft Copilot 对话桥

基于 Playwright 的长连接浏览器自动化方案，支持多轮对话和频率控制。

## 文件说明

| 文件 | 用途 |
|------|------|
| `copilot_bridge.py` | 核心库，提供 CopilotBridge 类 |
| `copilot_api.py` | HTTP API 服务，供其他 Agent 调用 |
| `test_copilot.py` | 测试脚本 |

## 快速开始

### 1. 基础用法（Python 调用）

```python
import asyncio
from copilot_bridge import CopilotBridge

async def main():
    bridge = CopilotBridge(headless=False, rate_limit=True)
    
    try:
        await bridge.start()
        
        # 发送消息
        response = await bridge.ask("你好，请介绍你自己")
        print(response.text)
        
        # 多轮对话（保持上下文）
        response2 = await bridge.ask("能举一个具体的例子吗？")
        print(response2.text)
        
    finally:
        await bridge.close()

asyncio.run(main())
```

### 2. HTTP API 服务

```bash
# 启动服务
python3 copilot_api.py --port 8080

# 初始化
POST http://localhost:8080/init
{}

# 发送消息
POST http://localhost:8080/ask
{"prompt": "你好"}

# 关闭
POST http://localhost:8080/close
```

### 3. 运行测试

```bash
# 基础测试
python3 test_copilot.py basic

# 多轮对话测试
python3 test_copilot.py multi

# 频率限制测试
python3 test_copilot.py rate
```

## 配置参数

### CopilotBridge 初始化参数

```python
CopilotBridge(
    headless=False,      # 是否无头模式（有虚拟桌面可设为 True）
    rate_limit=True      # 是否启用频率限制
)
```

### 频率限制

默认配置：
- 最小间隔：8 秒
- 最大间隔：15 秒（随机）

如需调整，修改 `RateLimiter` 类：
```python
rate_limiter = RateLimiter(min_interval=5.0, max_interval=10.0)
```

## 反检测策略

本实现包含以下反检测措施：

1. **浏览器指纹伪装**
   - 隐藏 `navigator.webdriver`
   - 伪装 plugins 和 languages
   - 随机 viewport

2. **人类行为模拟**
   - 随机延迟（1-3 秒）
   - 逐字输入（50-200ms/字符）
   - 自然的页面交互间隔

3. **频率控制**
   - 请求间隔 8-15 秒
   - 避免触发反爬机制

## 注意事项

⚠️ **重要警告：**

1. **选择器可能失效**
   - Copilot 前端经常更新
   - 如果报错"无法找到输入框"，需要更新 `self.selectors` 中的选择器

2. **游客模式限制**
   - 每日约 30 次对话限制
   - 登录后可增加额度

3. **不保证稳定性**
   - 网页版可能有反自动化检测
   - 建议用于非关键场景

4. **更稳定的替代方案**
   - Azure OpenAI API（企业级）
   - DeepSeek API（性价比高）

## 调试

如果运行失败：

1. 查看截图：`copilot_error_turn{N}.png`
2. 检查选择器：使用浏览器开发者工具获取最新选择器
3. 更新选择器：修改 `copilot_bridge.py` 中的 `self.selectors`

## 依赖

```bash
pip install playwright
playwright install chromium
```

如需虚拟桌面：
```bash
sudo apt-get install xvfb
```
