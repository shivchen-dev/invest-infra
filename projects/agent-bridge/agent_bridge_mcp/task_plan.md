# MCP Server 实现计划

## 目标
实现极简 MCP Server，提供 `ask()` 工具调用 DeepSeek/Qwen

## 架构
```
OpenClaw Agent (MCP Client)
    │ JSON-RPC over stdio
    ▼
MCP Server (agent_bridge_mcp)
    └── ask(platform, message) → response
```

## 文件结构
```
agent_bridge_mcp/
├── server.py          # MCP Server 主入口
├── src/
│   ├── __init__.py
│   ├── bridge_pool.py # Bridge 池管理
│   └── tools/
│       ├── __init__.py
│       └── ask.py     # ask() 工具
├── pyproject.toml
└── .mcp.json
```

## 实现步骤

### Phase 1: 基础设施 ✅
- [x] 创建目录结构
- [x] pyproject.toml 依赖
- [x] bridge_pool.py - Bridge 池

### Phase 2: MCP Server ✅
- [x] server.py - MCP Server 主入口
- [x] tools/ask.py - ask() 工具

### Phase 3: 测试
- [ ] 本地测试

## 关键文件
- 复用: `src/base_bridge.py`, `src/deepseek_bridge.py`, `src/qwen_bridge.py`
- 新增: `agent_bridge_mcp/`
