# Agent Bridge 开发知识库

> 基于 DeepSeek Bridge 开发经验，为第三方智能体接入提供技术沉淀

**版本**: 1.0  
**创建时间**: 2026-04-07  
**参考实现**: DeepSeek Bridge

---

## 一、架构概述

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Unified API Gateway                      │
│                      (Port: 8080)                           │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  DeepSeek    │  │    Qwen      │  │   Claude     │      │
│  │   Bridge     │  │   Bridge     │  │   Bridge     │      │
│  │  (Port 8787) │  │  (Port 8788) │  │  (Port 8789) │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
├─────────────────────────────────────────────────────────────┤
│                      Xvfb 虚拟桌面                          │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 核心组件

| 组件 | 职责 | 关键文件 |
|------|------|----------|
| **BaseBridge** | 公共基类，提供浏览器生命周期管理 | `base_bridge.py` |
| **XXXBridge** | 平台特定实现，继承 BaseBridge | `{platform}_bridge.py` |
| **HumanBehaviorSimulator** | 模拟人类行为（鼠标移动、打字） | `human_behavior_v2.py` |
| **ResponseExtractor** | 从页面提取 AI 回复内容 | `response_extractor.py` |
| **TopicManagerMixin** | 话题管理（列表、切换、新建） | `topic_manager.py` |
| **API Gateway** | 统一入口，路由到各 Bridge | `gateway.py` |

---

## 二、Bridge 开发规范

### 2.1 目录结构

```
projects/active/agent-bridge/
├── src/
│   ├── base_bridge.py              # 公共基类
│   ├── {platform}_bridge.py        # 平台 Bridge 实现
│   ├── human_behavior_v2.py        # 人类行为模拟
│   ├── response_extractor.py       # 回复提取器
│   ├── topic_manager.py            # 话题管理 Mixin
│   ├── config.py                   # 配置管理
│   └── api/
│       ├── gateway.py              # 统一网关
│       ├── {platform}_api.py       # 平台 API 服务
│       └── bridge_factory.py       # Bridge 工厂
├── data/
│   ├── browser_profile_{platform}/ # 浏览器用户数据
│   └── topics/                     # 话题存储
└── scripts/
    └── install-{platform}-service.sh # 服务安装脚本
```

### 2.2 Bridge 类实现模板

```python
#!/usr/bin/env python3
"""
{Platform} Bridge - AI Agent 接口
供其他智能体调用，与 {Platform} 对话
"""
import asyncio
import sys
from pathlib import Path
from typing import Optional, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from base_bridge import BaseBridge, BridgeResponse
from topic_manager import TopicManagerMixin
from human_behavior_v2 import HumanBehaviorSimulator
from response_extractor import ResponseExtractor
from config import VNC_ADDRESS, TIMEOUTS, HUMAN_BEHAVIOR


class {Platform}Bridge(BaseBridge, TopicManagerMixin):
    """
    {Platform} 对话桥接器
    
    供其他 AI Agent 调用
    """
    
    # ===== 必须配置 =====
    platform_name = "{platform}"
    login_url = "https://chat.{platform}.com/"
    user_data_dir = "data/browser_profile_{platform}"
    
    # 话题管理选择器（可选）
    TOPIC_SELECTORS = [
        '//div[contains(@class, "sidebar")]//div',
    ]
    TOPIC_FILTER_WORDS = [
        '新建对话', '设置', '帮助',
    ]
    
    def __init__(self):
        super().__init__()
        self.simulator: Optional[HumanBehaviorSimulator] = None
        self.extractor: Optional[ResponseExtractor] = None
    
    async def start(self) -> bool:
        """启动浏览器并初始化平台组件"""
        if not await super().start():
            return False
        
        # 初始化平台特有组件
        self.simulator = HumanBehaviorSimulator(self.page)
        self.extractor = ResponseExtractor(self.platform_name)
        
        return True
    
    async def ensure_login(self, timeout: int = 120) -> bool:
        """
        确保已登录
        
        策略:
        1. 检查已有标签页是否已登录
        2. 访问登录页面
        3. 检测登录状态
        4. 如未登录，等待用户手动登录
        """
        if self.is_logged_in and self.page:
            return True
        
        if not self.context:
            return False
        
        # 1. 检查所有标签页
        pages = self.context.pages
        for i, page in enumerate(pages):
            try:
                html = await page.content()
                # 根据平台调整登录检测逻辑
                if "登录" not in html and len(html) > 1000:
                    self.page = page
                    self.is_logged_in = True
                    await self.page.bring_to_front()
                    return True
            except:
                continue
        
        # 2. 访问登录页面
        if pages:
            self.page = pages[0]
        else:
            self.page = await self.context.new_page()
        
        await self.page.goto(self.login_url, timeout=60000)
        await asyncio.sleep(3)
        
        # 3. 检测登录状态
        html = await self.page.content()
        if "登录" not in html:  # 根据平台调整
            self.is_logged_in = True
            return True
        
        # 4. 等待用户登录
        print(f"⚠️  请在 VNC 中完成登录（{timeout}秒）...")
        print(f"   VNC: {VNC_ADDRESS}")
        
        for i in range(timeout // 10):
            await asyncio.sleep(10)
            html = await self.page.content()
            if "登录" not in html:
                self.is_logged_in = True
                print("✅ 登录完成")
                return True
        
        return False
    
    async def chat(self, message: str, **kwargs) -> BridgeResponse:
        """
        发送消息并获取回复
        
        Args:
            message: 用户消息
            **kwargs: 可选参数
                - wait_for_reply: 是否等待回复
                - save_response: 是否保存回复
                
        Returns:
            BridgeResponse 对象
        """
        if not await self.ensure_login():
            return BridgeResponse(text="", success=False, error="未登录")
        
        try:
            # 1. 点击输入框
            await self.page.wait_for_selector(
                'textarea', state='visible', timeout=10000
            )
            await self.simulator.natural_click('textarea')
            
            # 2. 输入消息
            await self.simulator.natural_typing('textarea', message)
            
            # 3. 发送
            await self.simulator.think_delay()
            await self.page.keyboard.press('Enter')
            
            # 4. 等待回复
            await self.simulator.random_delay(20, 30)
            
            # 5. 提取回复
            response_data = await self.extractor.extract_last_ai_response(self.page)
            
            return BridgeResponse(
                text=response_data["text"] if response_data else "",
                success=True,
                metadata=response_data
            )
            
        except Exception as e:
            return BridgeResponse(text="", success=False, error=str(e))
```

### 2.3 元素选择器策略

#### 输入框定位

| 策略 | 选择器示例 | 可靠性 |
|------|-----------|--------|
| placeholder | `textarea[placeholder*="提问"]` | ⭐⭐⭐⭐⭐ |
| aria-label | `textarea[aria-label*="输入"]` | ⭐⭐⭐⭐ |
| class组合 | `.chat-input-area textarea` | ⭐⭐⭐ |
| XPath | `//textarea[contains(@placeholder, "输入")]` | ⭐⭐⭐⭐ |

**推荐代码**:
```python
input_selectors = [
    'textarea[placeholder*="提问"]',
    'textarea[placeholder*="输入"]',
    '[contenteditable="true"]',
]

for selector in input_selectors:
    if await page.query_selector(selector):
        return selector
```

#### 发送按钮定位

| 策略 | 选择器示例 |
|------|-----------|
| type | `button[type="submit"]` |
| aria-label | `button[aria-label*="发送"]` |
| icon | `button svg` |
| XPath | `//button[contains(., "发送")]` |

#### 回复内容定位

在 `response_extractor.py` 中添加平台配置:

```python
PLATFORM_SELECTORS = {
    "{platform}": {
        "message_container": '[class*="chat-messages"]',
        "ai_message": '[class*="message"][class*="assistant"]',
        "user_message": '[class*="message"][class*="user"]',
        "text_content": '.message-content, .text-content',
    },
}
```

---

## 三、持久化登录实现

### 3.1 核心机制

使用 Playwright 的持久化上下文:

```python
# 启动时加载用户数据目录
context = await p.chromium.launch_persistent_context(
    user_data_dir=self.user_data_dir,  # 关键！
    headless=False,
)
```

### 3.2 登录状态保持

```
用户首次登录
    ↓
Playwright 自动保存:
  - Cookies
  - localStorage
  - sessionStorage
  - IndexedDB
    ↓
存储在 user_data_dir 目录
    ↓
下次启动自动恢复登录态
```

### 3.3 登录检测逻辑

```python
async def ensure_login(self, timeout: int = 120) -> bool:
    # 1. 检查已有标签页
    for page in self.context.pages:
        html = await page.content()
        # 根据平台特征判断是否已登录
        if "登录" not in html and "退出" in html:
            return True
    
    # 2. 访问首页检测
    await self.page.goto(self.login_url)
    
    # 3. 等待用户手动登录
    # 在 VNC 中显示登录页面
    # 轮询检测登录成功标志
```

### 3.4 多标签页处理

DeepSeek Bridge 的最佳实践:

```python
# 检查所有标签页，找到已登录的
for i, page in enumerate(self.context.pages):
    html = await page.content()
    if self._is_logged_in(html):
        self.page = page
        self.is_logged_in = True
        await self.page.bring_to_front()  # 激活该标签页
        return True
```

---

## 四、人类行为模拟

### 4.1 模拟器组件

```python
from human_behavior_v2 import HumanBehaviorSimulator

simulator = HumanBehaviorSimulator(page)
```

### 4.2 核心方法

| 方法 | 作用 | 延迟 |
|------|------|------|
| `natural_click(selector)` | 自然点击元素 | 0.1-0.5s移动 + 点击 |
| `natural_typing(selector, text)` | 自然打字 | 50-200ms/字符 |
| `think_delay()` | 思考停顿 | 3-12s |
| `random_delay(min, max)` | 随机延迟 | 自定义 |

### 4.3 打字模拟细节

```python
async def natural_typing(self, selector: str, text: str):
    # 1. 聚焦输入框
    await self.natural_click(selector)
    
    # 2. 清空现有内容
    await element.fill('')
    
    # 3. 逐字输入（带随机延迟）
    for char in text:
        # 基础延迟 50-200ms
        delay = random.uniform(0.05, 0.2)
        
        # 单词间额外停顿
        if char == ' ':
            delay += random.uniform(0.1, 0.3)
        
        # 偶尔长停顿（5%概率）
        if random.random() < 0.05:
            await self.random_delay(0.5, 2.0)
        
        await element.type(char)
        await asyncio.sleep(delay)
```

---

## 五、API 服务开发

### 5.1 服务架构

```
HTTP Request
    ↓
API Handler (BaseHTTPRequestHandler)
    ↓
Bridge 实例
    ↓
Playwright → 浏览器操作
```

### 5.2 API 端点规范

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/{platform}/health` | GET | 健康检查 |
| `/api/v1/{platform}/ask` | POST | 单轮对话 |
| `/api/v1/{platform}/chat` | POST | 多轮对话 |

### 5.3 请求/响应格式

**请求**:
```json
{
  "message": "用户消息",
  "template": "general_query"
}
```

**响应**:
```json
{
  "success": true,
  "data": {
    "response": "AI回复内容",
    "model": "模型名称"
  },
  "meta": {
    "timestamp": "2026-04-07T09:30:00Z"
  }
}
```

---

## 六、systemd 服务配置

### 6.1 服务文件模板

```ini
[Unit]
Description=Agent Bridge - {Platform} API Service
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory={project_path}
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 src/api/{platform}_api.py --port {port}
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=agent-bridge-{platform}

[Install]
WantedBy=multi-user.target
```

### 6.2 安装命令

```bash
# 1. 复制服务文件
sudo cp agent-bridge-{platform}.service /etc/systemd/system/

# 2. 重新加载配置
sudo systemctl daemon-reload

# 3. 启用开机自启
sudo systemctl enable agent-bridge-{platform}

# 4. 启动服务
sudo systemctl start agent-bridge-{platform}

# 5. 查看状态
sudo systemctl status agent-bridge-{platform}
```

---

## 七、开发检查清单

### 7.1 Bridge 实现检查

- [ ] 继承 `BaseBridge` 和 `TopicManagerMixin`
- [ ] 配置 `platform_name`, `login_url`, `user_data_dir`
- [ ] 实现 `start()` 方法，初始化 `HumanBehaviorSimulator`
- [ ] 实现 `ensure_login()` 方法，支持多标签页检查
- [ ] 实现 `chat()` 方法，完成完整对话流程
- [ ] 在 `ResponseExtractor` 中添加平台选择器
- [ ] 在 `BridgeFactory` 中注册新平台

### 7.2 API 服务检查

- [ ] 创建 `{platform}_api.py`
- [ ] 实现 `/health` 端点
- [ ] 实现 `/ask` 端点
- [ ] 处理错误响应
- [ ] 添加日志脱敏

### 7.3 部署检查

- [ ] 创建 systemd 服务文件
- [ ] 设置开机自启
- [ ] 配置网关路由
- [ ] 测试健康检查
- [ ] 测试对话功能

---

## 八、常见问题

### Q1: 登录状态无法保持？

**检查项**:
- 确认 `user_data_dir` 已配置
- 确认使用 `launch_persistent_context`
- 确认未在代码中清理 cookies

### Q2: 元素定位失败？

**解决方案**:
1. 使用浏览器开发者工具确认选择器
2. 添加等待: `page.wait_for_selector(selector, state='visible')`
3. 使用多个备选选择器
4. 考虑页面动态加载，增加延迟

### Q3: 回复提取为空？

**排查步骤**:
1. 确认回复已完全生成（增加等待时间）
2. 检查 `ResponseExtractor` 平台选择器配置
3. 截图确认页面状态
4. 打印 HTML 内容调试

### Q4: 被风控/限制？

**应对策略**:
1. 增加请求间隔（>5秒）
2. 使用 `HumanBehaviorSimulator` 模拟真实行为
3. 保持持久化会话，不频繁重启
4. 避免高频相同操作

---

## 九、扩展阅读

### 相关文件

| 文件 | 说明 |
|------|------|
| `deepseek_bridge.py` | 完整参考实现 |
| `base_bridge.py` | 公共基类定义 |
| `human_behavior_v2.py` | 人类行为模拟 |
| `response_extractor.py` | 回复提取逻辑 |
| `gateway.py` | 统一网关实现 |

### 开发流程

根据 P0 规则，新平台接入必须遵循:

1. **制定方案** - 参考本知识库
2. **咨询智能体** - 通过 Agent Bridge API 咨询
3. **总结汇报** - 整理技术方案
4. **获得授权** - 明确"开始"指令
5. **正式开发** - 按检查清单执行

---

*文档版本: 1.0*  
*最后更新: 2026-04-07*
