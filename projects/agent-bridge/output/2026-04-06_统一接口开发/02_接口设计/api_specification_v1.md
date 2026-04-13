# API Specification: Agent Bridge Unified Interface

**版本**: v1.0  
**日期**: 2026-04-06  
**状态**: 设计阶段

---

## 1. API 概述

### 1.1 设计原则
- **RESTful**: 标准 HTTP 方法 + 资源路径
- **平台无关**: 统一接口适配不同 LLM 平台
- **向后兼容**: 预留版本号支持未来扩展
- **错误透明**: 详细错误信息便于调试

### 1.2 基础信息
| 项目 | 值 |
|------|-----|
| 基础路径 | `/api/v1` |
| 内容类型 | `application/json` |
| 编码 | UTF-8 |
| 认证 | 暂不实现（本地服务） |

---

## 2. 端点设计

### 2.1 平台管理

#### GET `/platforms`
获取所有可用平台列表

**响应**:
```json
{
    "success": true,
    "data": {
        "platforms": [
            {"id": "deepseek", "name": "DeepSeek", "status": "ready"},
            {"id": "copilot", "name": "Microsoft Copilot", "status": "ready"},
            {"id": "claude", "name": "Claude", "status": "planned"}
        ]
    }
}
```

---

### 2.2 平台特定接口

所有平台端点遵循: `/api/v1/{platform}/{resource}`

#### 健康检查

##### GET `/{platform}/health`
检查平台桥接状态

**响应**:
```json
{
    "success": true,
    "data": {
        "platform": "deepseek",
        "initialized": true,
        "logged_in": true,
        "current_topic": "topic_xxx",
        "uptime": 3600
    }
}
```

#### 对话接口

##### POST `/{platform}/chat`
发送消息并获取回复

**请求**:
```json
{
    "message": "你好，请介绍一下自己",
    "topic_id": "optional_existing_topic_id",
    "options": {
        "timeout": 60,
        "stream": false
    }
}
```

**响应**:
```json
{
    "success": true,
    "data": {
        "response": "你好！我是 DeepSeek，一个 AI 助手...",
        "topic_id": "topic_abc123",
        "message_id": "msg_456",
        "tokens": {"input": 10, "output": 50},
        "timestamp": "2026-04-06T09:50:00Z"
    }
}
```

#### 话题管理

##### GET `/{platform}/topics`
获取话题列表

**响应**:
```json
{
    "success": true,
    "data": {
        "topics": [
            {"id": "topic_1", "title": "项目讨论", "updated_at": "2026-04-06T08:00:00Z"},
            {"id": "topic_2", "title": "代码审查", "updated_at": "2026-04-05T20:00:00Z"}
        ],
        "current_topic_id": "topic_1",
        "total": 10
    }
}
```

##### POST `/{platform}/topics`
创建新话题

**请求**:
```json
{
    "title": "可选标题"
}
```

**响应**:
```json
{
    "success": true,
    "data": {
        "topic_id": "topic_new123",
        "title": "新话题",
        "created_at": "2026-04-06T09:50:00Z"
    }
}
```

##### PUT `/{platform}/topics/{topic_id}`
切换到指定话题

**响应**:
```json
{
    "success": true,
    "data": {
        "topic_id": "topic_xxx",
        "title": "话题标题",
        "messages_count": 15
    }
}
```

##### DELETE `/{platform}/topics/{topic_id}`
删除话题

**响应**:
```json
{
    "success": true,
    "data": {
        "deleted": true,
        "topic_id": "topic_xxx"
    }
}
```

#### 历史消息

##### GET `/{platform}/topics/{topic_id}/messages`
获取话题历史消息

**查询参数**:
- `limit`: 返回消息数量 (默认 20, 最大 100)
- `before`: 分页游标

**响应**:
```json
{
    "success": true,
    "data": {
        "topic_id": "topic_xxx",
        "messages": [
            {"role": "user", "content": "你好", "timestamp": "2026-04-06T09:00:00Z"},
            {"role": "assistant", "content": "你好！", "timestamp": "2026-04-06T09:00:05Z"}
        ],
        "has_more": false
    }
}
```

---

## 3. 统一响应格式

### 3.1 成功响应
```json
{
    "success": true,
    "data": { ... },
    "meta": {
        "timestamp": "2026-04-06T09:50:00Z",
        "request_id": "req_abc123"
    }
}
```

### 3.2 错误响应
```json
{
    "success": false,
    "error": {
        "code": "PLATFORM_NOT_INITIALIZED",
        "message": "Bridge 未初始化，请先调用 /health 检查",
        "details": { ... }
    },
    "meta": {
        "timestamp": "2026-04-06T09:50:00Z",
        "request_id": "req_abc123"
    }
}
```

### 3.3 错误码定义
| 错误码 | HTTP 状态 | 说明 |
|--------|----------|------|
| `PLATFORM_NOT_FOUND` | 404 | 平台不存在 |
| `PLATFORM_NOT_INITIALIZED` | 503 | 平台未初始化 |
| `NOT_LOGGED_IN` | 401 | 未登录 |
| `TOPIC_NOT_FOUND` | 404 | 话题不存在 |
| `CHAT_TIMEOUT` | 504 | 对话超时 |
| `INVALID_REQUEST` | 400 | 请求参数错误 |
| `INTERNAL_ERROR` | 500 | 内部错误 |

---

## 4. 架构设计

### 4.1 Bridge 工厂模式

```python
# bridge_factory.py
from typing import Dict, Type, Optional
from base_bridge import BaseBridge

class BridgeFactory:
    """Bridge 工厂 - 管理所有平台实例"""
    
    _registry: Dict[str, Type[BaseBridge]] = {}
    _instances: Dict[str, BaseBridge] = {}
    
    @classmethod
    def register(cls, platform: str, bridge_class: Type[BaseBridge]):
        """注册平台 Bridge 类"""
        cls._registry[platform] = bridge_class
    
    @classmethod
    def get_bridge(cls, platform: str) -> Optional[BaseBridge]:
        """获取或创建 Bridge 实例"""
        if platform not in cls._instances:
            if platform not in cls._registry:
                return None
            cls._instances[platform] = cls._registry[platform]()
        return cls._instances[platform]
    
    @classmethod
    def list_platforms(cls) -> list:
        """列出所有可用平台"""
        return [
            {
                "id": name,
                "name": bridge_class.display_name,
                "status": "ready" if name in cls._instances else "available"
            }
            for name, bridge_class in cls._registry.items()
        ]
```

### 4.2 统一 API 处理器

```python
# unified_api.py
class UnifiedAPIHandler(BaseHTTPRequestHandler):
    """统一 API 处理器"""
    
    def route_request(self, method: str, path: str):
        """路由分发"""
        # /api/v1/{platform}/chat
        pattern = r'^/api/v1/(\w+)/(\w+)(?:/(\w+))?$'
        match = re.match(pattern, path)
        
        if not match:
            return self._send_error(404, "Invalid path")
        
        platform, resource, resource_id = match.groups()
        bridge = BridgeFactory.get_bridge(platform)
        
        if not bridge:
            return self._send_error(404, "Platform not found")
        
        # 根据方法和资源调用对应处理函数
        handler = getattr(self, f"_handle_{resource}", None)
        if handler:
            return handler(bridge, method, resource_id)
        
        return self._send_error(404, "Resource not found")
```

### 4.3 项目结构

```
agent-bridge/
├── src/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── server.py           # HTTP 服务器入口
│   │   ├── handlers.py         # 请求处理器
│   │   ├── responses.py        # 响应格式工具
│   │   └── middleware.py       # 中间件（日志、CORS）
│   ├── bridges/
│   │   ├── __init__.py
│   │   ├── base_bridge.py      # 基类（已有）
│   │   ├── bridge_factory.py   # 工厂类
│   │   ├── deepseek_bridge.py  # DeepSeek（已有）
│   │   └── copilot_bridge.py   # Copilot（已有）
│   └── core/
│       ├── __init__.py
│       └── topic_manager.py    # 话题管理（已有）
├── api_specs/                   # API 文档
│   └── v1_spec.md              # 本文件
└── examples/
    └── api_client.py           # API 调用示例
```

---

## 5. 实现优先级

### P0 - 核心功能
- [ ] Bridge 工厂实现
- [ ] DeepSeek API 端点
- [ ] 统一响应格式
- [ ] 基础错误处理

### P1 - 话题管理
- [ ] 话题列表/创建/切换/删除
- [ ] 历史消息获取

### P2 - 增强功能
- [ ] Copilot 迁移到新 API
- [ ] 多平台并发支持
- [ ] 流式响应 (SSE)
- [ ] API 认证

---

## 6. 与现有代码对比

| 现有 (copilot_api.py) | 新设计 |
|----------------------|--------|
| 单平台 | 多平台统一 |
| 全局 bridge 实例 | Bridge 工厂管理 |
| 固定端点 | 动态路由 `/{platform}/...` |
| 简单响应 | 统一响应格式 + 错误码 |
| http.server | 可扩展架构（预留 FastAPI 迁移） |

---

*设计完成，等待评审进入 Phase 3 实现*
