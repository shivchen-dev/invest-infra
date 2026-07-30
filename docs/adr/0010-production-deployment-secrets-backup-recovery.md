# ADR-0010：第一阶段生产部署、密钥、备份和恢复边界

- Status：Accepted
- Date：2026-07-30
- Owners：M0 架构基线

## Context

`compose.yaml` 使用一个开发 PostgreSQL 账户和默认密码，并暴露数据库端口；`.env.example` 只适合本地。当前 Compose 包含 API、Web 和单个 Dagster 开发运行单元，没有生产 secret、迁移 job、备份、TLS、恢复流程或告警。`README.md` 也明确完整容器验证尚未执行。因此当前配置不得描述为生产部署。

ADR-0001 和 ADR-0002 已冻结模块化单体、独立进程与 PostgreSQL-only。第一阶段不应引入 Redis、Kafka、Kubernetes 或对象存储。

## Decision

1. 第一阶段生产拓扑保持最小化：一个 PostgreSQL 16 服务；独立的 migration job；API 进程；Pipeline 的 Dagster webserver/code location/daemon 或等价独立运行进程；静态 Web；一个提供 TLS 和路由的既有入口。可部署在单台受管 VM/容器平台或组织已有平台，不要求 Kubernetes。
2. 开发 `compose.yaml` 不直接用于生产。生产镜像必须以不可变 digest 标识、非 root 运行、固定 Python 3.12 runtime，并把 API 与 Pipeline 依赖分开。应用启动不得自动运行 Alembic。
3. 发布顺序固定为：备份/恢复点确认 → 单实例 `migration_owner` 执行向前兼容迁移 → Pipeline → API → Web → 只读 smoke test。破坏性 schema 变更使用 expand/migrate/contract 至少两次发布。
4. 数据库最少分权：`migration_owner` 仅迁移时使用；`pipeline_writer` 可写 raw/core/analytics/ops 所需对象；`api_reader` 只读服务视图/表；备份身份独立。PostgreSQL 不对公网开放，网络只允许受控应用和运维来源。
5. Provider 凭据只注入 Pipeline；API/Web 不持有。生产密钥来自部署平台 Secret 或组织批准的 secret manager，以环境变量或只读文件运行时注入；不得进入 Git、镜像层、Compose 文件、Dagster run config、日志、异常、fixture 或备份说明文档。支持不重建镜像的轮换。`.env` 仅本地且不提交。
6. 日志必须对 Authorization、Cookie、token、数据库口令和请求敏感参数做结构化脱敏。访问生产 secret、发布和恢复操作必须有操作者审计。
7. PostgreSQL 备份最低边界：加密、自动、异地/故障域隔离、具备完整性校验；至少每日基线备份，并保留满足业务 RPO 的 WAL/PITR 能力。具体保留期、**RPO 和 RTO 待用户确认**，在确认前不得宣称达到生产 SLA。
8. 恢复必须有 `docs/runbooks/database-restore.md`，覆盖新实例恢复、凭据重建、Alembic revision 校验、表/约束计数、snapshot 外键/hash 验证、published pointer 校验、只读 API smoke test。上线前至少完成一次隔离环境恢复演练并保存时间戳、备份 ID、恢复点、耗时和验证结果；之后按组织频率定期演练。
9. 应用回滚优先回滚镜像；数据库仅允许使用事先审查的迁移策略，禁止在生产直接 `alembic downgrade` 作为默认回滚。数据恢复不得覆盖唯一生产实例，先恢复到隔离实例验证后再切换。
10. 最低监控覆盖数据库容量/备份失败、Provider 鉴权与限流、行情新鲜度/覆盖率、Pipeline 失败、候选池未发布。告警通道、责任人、RPO/RTO、备份保留期和部署平台是上线前用户确认项。

## Consequences

- 本地 Compose 仍可用于开发，但生产准备需要独立部署配置、账户、迁移 job 和 runbook。
- PostgreSQL 是唯一强制状态基础设施；原始证据容量必须受控。
- 未确认恢复目标和完成演练前，只能称“生产边界已定义”，不能称“生产就绪”。

## Alternatives

- **直接把当前 Compose 暴露到生产：Rejected。** 默认凭据、端口和进程形态不满足边界。
- **应用启动自动迁移：Rejected。** 多副本竞态且难以控制回滚。
- **首期引入 Kubernetes/Redis/Kafka：Rejected。** 没有需求证据且违反既有 ADR。
- **只做数据库 volume 快照、不演练恢复：Rejected。** 无法证明可恢复性。
