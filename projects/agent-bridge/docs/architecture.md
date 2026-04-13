# Agent Bridge API 架构文档

**版本**: v1.0 (生产版本)  
**日期**: 2026-04-06  
**架构**: API → Bridge → Browser

---

## 架构概述

### 层级结构
```
┌─────────────────────────────────────┐
│  API Layer (deepseek_api.py)        │  ← HTTP 接口
│  - 请求验证                          │
│  - 单例 Bridge 管理                  │
│  - 响应格式化                        │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Bridge Layer (DeepSeekBridge)      │  ← 浏览器控制
│  - 启动/管理 Chrome                  │
│  - 登录状态检测                      │
│  - 发送消息                          │
│  - 抓取回复                          │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Browser Layer (Chrome)             │  ← Web 自动化
│  - DeepSeek 网站交互                 │
└─────────────────────────────────────┘
```

### 关键设计

**单例模式**: API 直接管理 Bridge 单例，避免 Chrome 冲突
```python
# 全局 Bridge 实例
_bridge = None

def get_bridge():
    if _bridge is None:
        _bridge = DeepSeekBridge()
    return _bridge
```

**职责分离**:
| 层级 | 职责 |
|------|------|
| API | HTTP 接口、请求验证、响应格式化 |
| Bridge | 浏览器生命周期、对话流程、回复抓取 |
| Browser | Web 页面交互 |

---

## API 端点

### POST /api/v1/deepseek/ask
发送消息并获取 DeepSeek 回复

**请求**:
```json
{
    "template": "general_query",
    "message": "你好 DeepSeek！"
}
```

**响应**:
```json
{
    "success": true,
    "data": {
        "response": "你好！很高兴见到你...",
        "template": "general_query"
    },
    "meta": {
        "timestamp": "2026-04-06T04:22:47Z",
        "request_id": "req_xxx"
    }
}
```

### GET /api/v1/deepseek/health
健康检查

**响应**:
```json
{
    "success": true,
    "data": {
        "platform": "deepseek",
        "initialized": true
    }
}
```

---

## 文件结构

```
agent-bridge/
├── src/
│   ├── api/
│   │   ├── deepseek_api.py       # API 服务 (生产版本)
│   │   ├── responses.py          # 统一响应格式
│   │   ├── validators.py         # 模板验证
│   │   └── bridge_factory.py     # 工厂模式 (保留备用)
│   ├── deepseek_bridge.py        # DeepSeek Bridge
│   ├── base_bridge.py            # Bridge 基类
│   └── ...
├── .learnings/
│   └── LEARNINGS.md              # 复盘记录
├── task_plan.md                  # 任务计划
└── progress.md                   # 进度记录
```

---

## 使用示例

### Python 调用
```python
import requests

# 发送消息
response = requests.post(
    "http://localhost:8787/api/v1/deepseek/ask",
    json={
        "template": "general_query",
        "message": "你好！"
    }
)

result = response.json()
print(result["data"]["response"])
```

### cURL 调用
```bash
curl -X POST http://localhost:8787/api/v1/deepseek/ask \
  -H "Content-Type: application/json" \
  -d '{"template": "general_query", "message": "你好！"}'
```

---

## 启动方式

```bash
cd ~/.openclaw/workspace-browser/projects/active/agent-bridge
python3 src/api/deepseek_api.py
```

服务启动于 `http://0.0.0.0:8787`

---

## 技术要点

1. **单例模式**: 全局唯一 Bridge 实例，避免 Chrome 冲突
2. **Asyncio 处理**: HTTP 同步与 Bridge 异步的兼容方案
3. **持久化会话**: 使用 `data/browser_profile_deepseek/` 保持登录状态
4. **模板验证**: 强制请求包含 `template` 字段，规范调用方式

---

*文档版本: v1.0 | 生产环境已部署*
