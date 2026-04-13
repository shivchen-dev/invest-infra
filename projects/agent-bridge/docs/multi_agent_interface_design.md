# Agent Bridge 多智能体接口设计方案

## 问题分析

### 核心需求
1. **接口方式**：OpenClaw 本地其他智能体如何调用 Agent Bridge
2. **模板规范**：如何强制/引导使用提问模板
3. **轮数界定**：何时结束对话，如何管理多轮交互

---

## 方案一：HTTP API 服务（推荐）

### 架构图
```
其他智能体 ──HTTP──> Agent Bridge API Server ──> DeepSeek Bridge
    │                          │
    │                      模板验证
    │                      轮数管理
    │                      队列控制
```

### API 设计

#### 1. 单轮咨询接口
```python
POST /api/v1/ask
{
    "agent_id": "cb-ecommerce",      # 调用者身份
    "template": "element_locating",   # 使用的模板类型
    "query": {
        "background": "需要定位登录按钮",
        "problem": "ID是动态生成的",
        "attempted": ["使用固定ID", "使用class选择器"],
        "need": "稳定的选择器策略"
    },
    "priority": "reliability",        # reliability/speed/simplicity
    "context": {                      # 可选上下文
        "url": "https://example.com",
        "code_snippet": "...",
        "error_log": "..."
    }
}

Response:
{
    "success": true,
    "response_id": "ds-20240406-001",
    "answer": "DeepSeek的回复内容...",
    "metadata": {
        "template_used": "element_locating",
        "priority": "reliability",
        "saved_path": "data/agent_responses/deepseek/...",
        "tokens_used": 1250,
        "response_time": 15.3
    }
}
```

#### 2. 多轮对话接口
```python
POST /api/v1/conversation/start
{
    "agent_id": "cb-ecommerce",
    "topic": "复杂工作流设计",
    "max_rounds": 5,                  # 最大轮数限制
    "template": "workflow_design"
}

Response:
{
    "conversation_id": "conv-20240406-001",
    "status": "started",
    "current_round": 0,
    "max_rounds": 5
}

POST /api/v1/conversation/{id}/round
{
    "stage": "confirm",               # confirm/execute/feedback
    "query": { ... },
    "previous_result": "..."          # 上一轮执行结果
}

Response:
{
    "round": 1,
    "stage": "confirm",
    "deepseek_response": "...",
    "next_action": "execute",         # 建议的下一步
    "remaining_rounds": 4
}
```

#### 3. 状态查询接口
```python
GET /api/v1/status
GET /api/v1/conversation/{id}/status
```

---

## 方案二：Python SDK/函数调用

### 使用方式
```python
from agent_bridge_sdk import DeepSeekClient

# 初始化
client = DeepSeekClient(
    base_url="http://localhost:8080",
    agent_id="cb-ecommerce"
)

# 单轮咨询（自动使用模板）
response = client.ask(
    template="element_locating",
    background="需要定位登录按钮",
    problem="ID是动态生成的",
    attempted=["使用固定ID"],
    need="稳定的选择器策略",
    priority="reliability"
)

# 多轮对话
conversation = client.start_conversation(
    topic="复杂工作流",
    max_rounds=5,
    template="workflow_design"
)

for round_num in range(5):
    reply = conversation.next_round(
        stage="confirm",
        query=...,
        result=...
    )
    if reply.is_complete:
        break
```

---

## 模板规范强制机制

### 1. 模板验证中间件
```python
class TemplateValidator:
    """验证请求是否符合模板规范"""
    
    TEMPLATES = {
        "element_locating": ["background", "problem", "attempted", "need"],
        "error_handling": ["background", "error_type", "attempted", "environment"],
        "workflow_design": ["background", "complexity", "current_flow", "constraints"],
        # ...
    }
    
    def validate(self, template_name: str, query: dict) -> ValidationResult:
        required_fields = self.TEMPLATES.get(template_name, [])
        missing = [f for f in required_fields if f not in query]
        
        if missing:
            return ValidationResult(
                valid=False,
                error=f"模板 '{template_name}' 缺少必填字段: {missing}",
                example=self.get_example(template_name)
            )
        
        return ValidationResult(valid=True)
```

### 2. 模板自动填充建议
```python
def suggest_template(query: str) -> str:
    """根据查询内容推荐模板"""
    keywords = {
        "element_locating": ["定位", "选择器", "元素", "xpath", "css"],
        "error_handling": ["错误", "异常", "失败", "报错"],
        "anti_detection": ["反爬", "验证码", "检测", "封禁"],
        "data_extraction": ["提取", "抓取", "数据", "解析"],
    }
    
    # 匹配关键词推荐模板
    ...
```

---

## 提问轮数界定策略

### 策略一：固定轮数限制
```python
MAX_ROUNDS = {
    "simple": 1,      # 简单问题，单轮
    "normal": 3,      # 普通问题，3轮
    "complex": 5,     # 复杂问题，5轮
    "deep": 10,       # 深度讨论，10轮
}
```

### 策略二：动态判断（推荐）
```python
class ConversationManager:
    def should_continue(self, conversation) -> bool:
        """判断是否继续对话"""
        
        # 1. 检查是否达到最大轮数
        if conversation.current_round >= conversation.max_rounds:
            return False
        
        # 2. 检查DeepSeek是否给出完整解决方案
        last_response = conversation.last_response
        if self.is_complete_solution(last_response):
            return False
        
        # 3. 检查是否产生新关键信息
        if not self.has_new_information(last_response):
            return False
        
        # 4. 检查用户是否满意（可以主动询问）
        if conversation.user_satisfied:
            return False
        
        return True
    
    def is_complete_solution(self, response: str) -> bool:
        """检查是否是完整解决方案"""
        indicators = [
            "完整代码示例",
            "总结",
            "最佳实践",
            "可以直接使用",
        ]
        return any(i in response for i in indicators)
```

### 策略三：三阶段强制模式
```python
class ThreeStageConversation:
    """强制三阶段对话模式"""
    
    STAGES = ["confirm", "execute", "feedback"]
    
    def next_stage(self):
        """推进到下一阶段"""
        current_idx = self.STAGES.index(self.current_stage)
        if current_idx < len(self.STAGES) - 1:
            self.current_stage = self.STAGES[current_idx + 1]
        else:
            self.completed = True
    
    def get_stage_prompt(self) -> str:
        """获取当前阶段的引导提示"""
        prompts = {
            "confirm": "请确认以下方案是否可行，或需要调整...",
            "execute": "请执行上述方案的第一步，并返回结果...",
            "feedback": "根据执行结果，请给出下一步建议...",
        }
        return prompts.get(self.current_stage, "")
```

---

## 权限与队列管理

### 1. 权限控制
```python
class AccessControl:
    """控制哪些智能体可以访问"""
    
    ALLOWED_AGENTS = [
        "cb-ecommerce",
        "cb-browser",
        "planner-agent",
        "task-agent",
    ]
    
    RATE_LIMITS = {
        "cb-ecommerce": 10,    # 每分钟10次
        "cb-browser": 5,
        "default": 3,
    }
```

### 2. 队列管理
```python
class QueryQueue:
    """管理并发请求队列"""
    
    def __init__(self):
        self.queue = asyncio.Queue()
        self.processing = False
    
    async def enqueue(self, request):
        """加入队列"""
        await self.queue.put(request)
        return {"status": "queued", "position": self.queue.qsize()}
    
    async def process(self):
        """处理队列"""
        while True:
            request = await self.queue.get()
            self.processing = True
            
            try:
                result = await self.call_deepseek(request)
                await self.notify_result(request, result)
            finally:
                self.processing = False
                self.queue.task_done()
```

---

## 推荐实现路径

### 阶段1：基础HTTP API（1-2天）
1. 使用 `copilot_api.py` 作为参考
2. 实现 `/api/v1/ask` 单轮接口
3. 添加模板验证中间件
4. 简单轮数限制

### 阶段2：多轮对话支持（2-3天）
1. 实现对话会话管理
2. 三阶段对话模式
3. 状态持久化
4. 轮数动态判断

### 阶段3：高级功能（3-5天）
1. 权限控制
2. 队列管理
3. 使用统计
4. SDK开发

---

## 接口使用示例

### 智能体调用示例
```python
# cb-ecommerce 需要咨询价格提取问题
import requests

response = requests.post("http://localhost:8080/api/v1/ask", json={
    "agent_id": "cb-ecommerce",
    "template": "data_extraction",
    "query": {
        "background": "需要抓取电商网站价格",
        "problem": "价格是动态加载的，直接抓不到",
        "attempted": ["直接解析HTML", "等待3秒"],
        "need": "可靠的动态内容提取方案"
    },
    "priority": "reliability",
    "context": {
        "url": "https://example.com/product/123",
        "framework": "Playwright"
    }
})

result = response.json()
print(result["answer"])
```

---

## 需要决策的问题

1. **接口协议**: HTTP REST vs gRPC vs 消息队列？
2. **认证方式**: API Key vs JWT vs 白名单？
3. **部署方式**: 独立服务 vs 嵌入主进程？
4. **轮数默认**: 默认3轮 vs 根据模板动态？

请确认方案方向，我可以开始实现。