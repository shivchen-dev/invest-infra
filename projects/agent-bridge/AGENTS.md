# Agent Bridge - Project Operations

## Build Commands

```bash
# 启动 API 服务
python3 src/api/deepseek_api.py

# 简单对话示例
python3 examples/chat_simple.py

# Agent 集成示例
python3 examples/agent_demo.py
```

## Validation

```bash
# 运行单元测试
python3 -m pytest tests/test_smart_topic_manager.py -v

# 运行所有测试
python3 -m pytest tests/ -v

# 类型检查
python3 -m mypy src/ --ignore-missing-imports

# 代码检查
python3 -m ruff check src/ --ignore E501,W291
```

## Test Coverage

| 模块 | 测试文件 | 状态 |
|------|----------|------|
| SmartTopicManager | test_smart_topic_manager.py | 19/19 ✅ |

## Operational Notes

- **测试必须通过**后才能提交代码变更
- **PROGRESS.md 必须更新**每次迭代后
- **IMPLEMENTATION_PLAN.md** 由 Ralph 自动维护
- API 服务运行在端口 8787

## Environment

```bash
# 代理配置（如需要）
export HTTP_PROXY=http://192.168.6.50:7890
export HTTPS_PROXY=http://192.168.6.50:7890

# VNC 访问（手动操作）
# 172.22.224.123:5900
```

## Quick Test

```bash
# 健康检查
curl http://localhost:8787/api/v1/deepseek/health

# 话题建议
curl "http://localhost:8787/api/v1/deepseek/topics/suggest?message=设计API"
```
