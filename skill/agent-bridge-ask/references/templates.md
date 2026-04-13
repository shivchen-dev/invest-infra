# Agent Bridge 模板详解

## general_query

**用途**：通用查询，适合大多数问题

**参数**：
```json
{
  "message": "问题内容",
  "template": "general_query",
  "session_id": null
}
```

**示例**：
```python
requests.post("http://127.0.0.1:8787/api/v1/deepseek/ask", json={
    "message": "解释一下什么是 MVC 架构",
    "template": "general_query"
})
```

---

## code_review

**用途**：代码审查，AI 会分析代码质量、性能、安全性

**参数**：
```json
{
  "message": "审查要求",
  "code": "要审查的代码",
  "template": "code_review",
  "session_id": null
}
```

**示例**：
```python
requests.post("http://127.0.0.1:8787/api/v1/deepseek/ask", json={
    "message": "审查这段代码的性能问题",
    "code": "def fib(n): return n if n < 2 else fib(n-1) + fib(n-2)",
    "template": "code_review"
})
```

**AI 会关注**：
- 代码结构和可读性
- 性能问题（时间/空间复杂度）
- 安全漏洞（SQL注入、XSS等）
- 边界情况处理
- 错误处理

---

## error_analysis

**用途**：错误分析，AI 会诊断错误原因并提供解决方案

**参数**：
```json
{
  "message": "问题描述",
  "error_type": "错误类型",
  "error_message": "错误信息",
  "template": "error_analysis",
  "session_id": null
}
```

**示例**：
```python
requests.post("http://127.0.0.1:8787/api/v1/deepseek/ask", json={
    "message": "程序启动失败，请分析原因",
    "error_type": "ConnectionError",
    "error_message": "Connection refused: localhost:8787",
    "template": "error_analysis"
})
```

**AI 会关注**：
- 错误类型识别
- 错误堆栈分析
- 根本原因定位
- 解决方案建议
- 预防措施

---

## architecture_design

**用途**：架构设计，AI 会提供系统设计方案

**参数**：
```json
{
  "message": "设计需求",
  "template": "architecture_design",
  "session_id": null
}
```

**示例**：
```python
requests.post("http://127.0.0.1:8787/api/v1/deepseek/ask", json={
    "message": "设计一个日处理千万请求的爬虫系统",
    "template": "architecture_design"
})
```

**AI 会关注**：
- 系统架构图
- 核心组件设计
- 技术选型理由
- 扩展性考虑
- 容灾方案

---

## element_locating

**用途**：元素定位（用于浏览器操作场景）

**参数**：
```json
{
  "message": "定位需求描述",
  "selector_type": "css|xpath|id|class",
  "selector_value": "选择器值",
  "template": "element_locating",
  "session_id": null
}
```

**示例**：
```python
requests.post("http://127.0.0.1:8787/api/v1/deepseek/ask", json={
    "message": "点击登录按钮",
    "selector_type": "id",
    "selector_value": "login-btn",
    "template": "element_locating"
})
```

---

## 会话管理

### 创建新会话（不传 session_id）

每次请求不传 `session_id` 会创建新会话：

```python
# 第一次请求 - 创建会话1
requests.post("http://127.0.0.1:8787/api/v1/deepseek/ask", json={
    "message": "什么是闭包",
    "template": "general_query"
})
# 返回: {"data": {"session_id": "sess_abc123", ...}}

# 第二次请求 - 创建会话2
requests.post("http://127.0.0.1:8787/api/v1/deepseek/ask", json={
    "message": "什么是装饰器",
    "template": "general_query"
})
# 返回: {"data": {"session_id": "sess_def456", ...}}
```

### 继续会话（传 session_id）

传 `session_id` 可继续同一会话：

```python
# 继续会话1
requests.post("http://127.0.0.1:8787/api/v1/deepseek/ask", json={
    "message": "闭包和装饰器有什么关系",
    "template": "general_query",
    "session_id": "sess_abc123"
})
```

### 列出所有会话

```python
requests.get("http://127.0.0.1:8787/api/v1/sessions")
```

---

## 完整调用示例

```python
import requests

def ask_deepseek(message, template="general_query", session_id=None):
    """向 DeepSeek 提问"""
    payload = {
        "message": message,
        "template": template,
        "session_id": session_id
    }
    
    response = requests.post(
        "http://127.0.0.1:8787/api/v1/deepseek/ask",
        json=payload,
        timeout=120
    )
    
    result = response.json()
    
    if result["code"] == 0:
        return result["data"]["response"]
    else:
        raise Exception(f"Error {result['code']}: {result['message']}")


def ask_qwen(message, template="general_query", session_id=None):
    """向 Qwen 提问"""
    payload = {
        "message": message,
        "template": template,
        "session_id": session_id
    }
    
    response = requests.post(
        "http://127.0.0.1:8788/api/v1/qwen/ask",
        json=payload,
        timeout=120
    )
    
    result = response.json()
    
    if result["code"] == 0:
        return result["data"]["response"]
    else:
        raise Exception(f"Error {result['code']}: {result['message']}")
```
