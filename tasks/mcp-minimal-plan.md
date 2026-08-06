# 最小化 MCP 实施计划

## 目标

在不新增 Provider、不开放写操作、不暴露数据库的前提下，为 AI 研究提供
一个本地 stdio MCP 入口，复用现有 Application Query Service。

## 架构决策

- MCP Server 放在 `apps/api` 运行单元内，避免复制查询编排。
- MCP 只依赖 Application service；数据库 Session 和具体 Repository 由现有
  dependency wiring 创建。
- 第一版只提供四个只读工具：data freshness、latest candidate pool、candidate
  pool diff、ETF daily bars。
- 输入使用明确的日期/UUID/分页参数；禁止任意 SQL、写操作和 Provider 调用。
- stdio 是唯一 transport；不做 HTTP/SSE、认证和远程暴露。
- Tool 输出必须是 JSON-safe、有限大小，并携带必要的日期/来源语义。

## 执行切片

### Slice 1：工具契约与适配器

- [x] 增加 MCP SDK 依赖和 stdio 入口。
- [x] 实现四个只读工具，复用现有 Application services。
- [x] 工具层不直接构造 SQL 或 Provider client。

### Slice 2：契约测试与越权测试

- [x] 测试工具注册、参数校验、JSON-safe 输出。
- [x] 测试无写入、无任意 SQL、无 Provider 调用边界。
- [x] 测试异常被转换为安全的工具错误，不泄露连接信息。

### Checkpoint

- [x] API 既有测试通过。
- [x] MCP focused tests、ruff、架构边界检查通过。
- [x] 本地 stdio 初始化和工具列表可复现。

## 明确不做

- 新 Provider 或 Provider routing；
- Evidence/Context 持久化；
- 通用搜索、任意 SQL、写入工具；
- 远程 transport 和生产鉴权体系。
