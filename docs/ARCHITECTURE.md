# invest-infra-v2 架构设计

## 1. 系统边界

v2 初期采用三个运行单元：

```text
React Web ──HTTP/OpenAPI──> FastAPI API ──SQL──> PostgreSQL
                                      ↑
Dagster Pipeline ───────────────SQL───┘
```

API 与 Pipeline 可以共享纯领域包和存储包，但拥有独立 `pyproject.toml`、锁文件、镜像和运行生命周期。

## 2. 分层

### Domain

只包含实体、值对象、枚举和端口协议。禁止依赖 FastAPI、SQLAlchemy、Dagster、AkShare。

### Application

组织用例，例如查询标的、执行候选池计算、生成报告。它调用端口，不直接调用具体 SDK。

### Infrastructure

实现 Repository、Provider、日志、配置和数据库连接。

### Entrypoints

FastAPI 路由、Dagster assets 和命令行入口。入口只负责校验、调用用例、转换结果。

## 3. 数据分层

首期建立四个 PostgreSQL Schema：

- `raw`：第三方原始数据和采集元信息；
- `core`：标准化标的、行情和公司主数据；
- `analytics`：因子、信号、候选池和回测结果；
- `app`：用户组合、关注列表、报告索引和工作流状态。

骨架只创建 `core.instruments` 和 `app.pipeline_runs`，其他表应随垂直切片增量增加。

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
