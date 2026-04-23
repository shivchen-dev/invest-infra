# 复盘：Qwen Bridge 开发与事件循环问题修复

## 时间
2026-04-07

## 背景
实现通义千问(Qwen)的浏览器自动化 Bridge，基于 DeepSeek Bridge 的成功经验。

## 开发过程

### Phase 1: 核心类开发 ✅
- 创建 `qwen_bridge.py`，继承 `BaseBridge` + `TopicManagerMixin`
- 实现 `ensure_login()` 持久化登录逻辑（参考 DeepSeek）
- 实现 `chat()` 对话方法，集成 `HumanBehaviorSimulator`
- 在 `ResponseExtractor` 中添加 qwen 选择器配置

### Phase 2: API 服务开发 ⚠️
**问题出现**：
创建 `qwen_api.py` 时遇到事件循环错误：
```
Page.wait_for_selector: The future belongs to a different loop than the one specified as the loop argument
```

**根本原因**：
- HTTP 服务器是同步的（`BaseHTTPRequestHandler`）
- Playwright 需要异步操作
- 每次请求创建新事件循环导致 Playwright 上下文失效

**错误实现**：
```python
# ❌ 错误：在方法内创建新循环
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
response = loop.run_until_complete(bridge.chat(...))
```

**正确实现**（参考 DeepSeek API）：
```python
# ✅ 正确：使用全局单例循环
_loop = None

def get_loop():
    global _loop
    if _loop is None:
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop

# 在同步 handler 中调用
loop = get_loop()
result = loop.run_until_complete(self._async_handler(...))

# 异步方法单独定义
async def _async_handler(self, ...):
    # 使用 await 调用 Bridge
    response = await bridge.chat(...)
```

### Phase 3: 登录验证 ✅
- 通过 VNC 完成千问网站登录
- 登录状态成功持久化到 `data/browser_profile_qwen/`
- 验证持久化登录机制工作正常

## 关键经验

### 1. 事件循环管理
| 场景 | 处理方式 |
|------|----------|
| HTTP API (同步) | 使用全局单例事件循环 |
| Bridge 方法 | 标准 async/await |
| 同步调用异步 | `loop.run_until_complete()` |

### 2. 代码模式对比
**❌ 错误模式**（导致 loop 冲突）：
```python
def handle(self):
    loop = asyncio.new_event_loop()  # 每次请求创建新 loop
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(bridge.chat())
```

**✅ 正确模式**（参考 DeepSeek）：
```python
_loop = None

def get_loop():
    global _loop
    if _loop is None:
        __loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop

def handle(self):
    loop = get_loop()  # 复用全局 loop
    result = loop.run_until_complete(self._async_handle())

async def _async_handle(self):
    result = await bridge.chat()  # 正确 await
```

### 3. Playwright + HTTP Server 最佳实践
1. **全局事件循环**：整个进程共享一个 loop
2. **分离 sync/async**：同步 handler 调用异步方法
3. **延迟初始化**：首次请求时才启动 Bridge
4. **单例模式**：Bridge 实例全局共享

## 修复记录

### 修改文件
- `src/api/qwen_api.py` - 重写 API 服务，修复事件循环管理

### 关键修改点
```diff
- # 错误：方法内创建新 loop
- loop = asyncio.new_event_loop()
- asyncio.set_event_loop(loop)

+ # 正确：使用全局单例 loop
+ _loop = None
+
+ def get_loop():
+     global _loop
+     if _loop is None:
+         _loop = asyncio.new_event_loop()
+         asyncio.set_event_loop(_loop)
+     return _loop
+
+ loop = get_loop()
+ result = loop.run_until_complete(self._async_handler())
```

## 知识库更新

### 新增内容
- `docs/BRIDGE_DEVELOPMENT_KB.md` - Bridge 开发知识库（已创建）
- `docs/LESSONS_EVENT_LOOP.md` - 事件循环问题专项记录（本文件）

### 更新内容
- `IMPLEMENTATION_PLAN.md` - 标记 Qwen Bridge 任务完成
- `.learnings/` - 学习记录

## 后续建议

### 1. 其他 Bridge 开发
参考 Qwen Bridge 模式，使用正确的事件循环管理：
```python
# 模板代码（适用于所有 Bridge API）
_loop = None
_bridge = None

def get_loop():
    global _loop
    if _loop is None:
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop

def get_bridge():
    global _bridge
    if _bridge is None:
        _bridge = XXXBridge()
    return _bridge

class APIHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        loop = get_loop()
        result = loop.run_until_complete(self._handle_async())
    
    async def _handle_async(self):
        bridge = get_bridge()
        response = await bridge.chat(...)
```

### 2. 测试验证
每次新增 Bridge 后必须验证：
1. 语法检查：`python3 -m py_compile src/xxx_bridge.py`
2. 导入测试：`python3 -c "from xxx_bridge import XXXBridge"`
3. 健康检查：`curl http://localhost:xxxx/api/v1/xxx/health`
4. 登录测试：通过 API 触发登录流程
5. 对话测试：验证完整对话流程

### 3. 文档同步
- 更新 `BRIDGE_DEVELOPMENT_KB.md` 中的最佳实践
- 在 `.learnings/` 记录每次重大修复
- 更新 `IMPLEMENTATION_PLAN.md` 任务状态

## 总结

**成功因素**：
- 参考 DeepSeek API 的正确实现模式
- 理解 Playwright 的事件循环要求
- 采用全局单例模式管理 loop 和 Bridge

**教训**：
- 不要盲目创建新的事件循环
- 同步 HTTP 服务调用异步代码需要特殊处理
- 参考现有成功实现比重新造轮子更有效

**产出**：
- ✅ Qwen Bridge 完整实现
- ✅ 持久化登录验证成功
- ✅ 事件循环问题修复方案
- ✅ 开发知识库更新

---

**复盘时间**: 2026-04-07 11:55  
**相关文件**: 
- `src/qwen_bridge.py`
- `src/api/qwen_api.py`
- `docs/BRIDGE_DEVELOPMENT_KB.md`
