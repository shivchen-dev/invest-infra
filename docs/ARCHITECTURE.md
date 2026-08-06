# invest-infra-v2 架构设计

> 领域所有权、Evidence 规则和 Repository 准入以
> [`ARCHITECTURE-GOVERNANCE.md`](ARCHITECTURE-GOVERNANCE.md) 为权威来源；本文描述部署与代码分层。

## 1. 系统边界

v2 初期采用三个运行单元：

```text
React Web ──HTTP/OpenAPI──> FastAPI API ──SQL──> PostgreSQL
                                      ↑
Dagster Pipeline ───────────────SQL───┘
```

API 与 Pipeline 可以共享纯领域包和存储包，但拥有独立 `pyproject.toml`、锁文件、镜像和运行生命周期。

Web 边界明确如下：

- Web 只通过 FastAPI 暴露的 OpenAPI/HTTP 契约访问后端；
- Web 不直接连接 PostgreSQL，也不调用 Dagster；
- Web 不持有 Provider 凭据；
- 生成的 OpenAPI TypeScript 类型是 API 契约的权威来源，禁止手工维护响应类型。


## 2. 分层

### Domain

只包含实体、值对象、枚举和端口协议。禁止依赖 FastAPI、SQLAlchemy、Dagster、AkShare。

### Application

组织用例，例如查询标的、执行候选池计算、生成报告。它调用端口，不直接调用具体 SDK。

### Infrastructure

实现 Repository、Provider、日志、配置和数据库连接。

### Entrypoints

FastAPI 路由、Dagster assets 和命令行入口。入口只负责校验、调用用例、转换结果。

## 3. 数据与领域分层

系统使用四个逻辑领域边界；数据库 schema 位置不替代领域所有权：

- **Core**：Provider 原始证据的 canonical 业务对象，包括标的、行情、ETF Profile、指数与 Exposure；
- **Analytics**：确定性因子、风险指标、市场状态、Candidate Pool 与 Quality Gate；
- **Research**：Research Case、Evidence Pack 和可重建的只读 Context projection；
- **AI**：Research Run、Playbook、Research Result、观点、风险解释和报告。

`raw`、`core`、`analytics`、`ops` PostgreSQL schema 继续作为物理存储边界。Evidence Pack 当前暂存于 `analytics`，其逻辑 owner 仍是 Research。

关键约束：

- Factor 是带版本和质量信息的确定性 observation，不是买卖信号；
- Candidate Pool 是 Research Case 的可选输入，不是唯一入口；
- `PipelineRun` 管理采集与确定性计算，`ResearchRun` 管理 AI 研究执行，两者不得共用状态机；
- AI 只消费 Evidence/Context，不修改 Core、Analytics 或 Research Evidence。

## 4. 关键规则

1. 一张业务表只有一个模块拥有写权限。
2. 生产流程不能通过 `subprocess` 调用仓库内另一个 Python 脚本。
3. 数据源 SDK 只能出现在 Provider 适配器中。
4. API 不能安装回测、Notebook 或大规模计算依赖。
5. Pipeline 不承担用户鉴权与前端兼容逻辑。
6. 所有长任务写入 `pipeline_runs`，状态不能保存在本地 JSON 文件。
7. 数据库变更只通过 Alembic 迁移。
8. 不为尚未出现的吞吐量问题提前增加队列。

## 5. 何时拆服务

仅当同时满足以下条件时拆为网络服务：

- 模块有独立扩缩容、权限或发布周期；
- 进程内边界已经稳定；
- 监控证明当前部署模型存在瓶颈；
- 团队愿意承担契约、部署和故障排查成本。

在此之前优先通过独立包、独立进程和数据库所有权维持边界。
