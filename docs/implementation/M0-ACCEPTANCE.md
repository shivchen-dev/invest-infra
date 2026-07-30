# M0-ACCEPTANCE

> M0 阶段的验收清单。检查命令默认使用仓库根目录路径，命令均为只读；本阶段不执行迁移、安装或部署。

## A. 文件与结构

| ID | 检查项 | 期望 | 检查命令（只读） |
|---|---|---|---|
| A-1 | 新增 `docs/adr/0003` … `0010` 八个 ADR | 全部存在 | `ls docs/adr/000[3-9]*.md docs/adr/0010*.md` |
| A-2 | 新增 `docs/implementation/M0-DECISIONS.md` | 存在 | `ls docs/implementation/M0-DECISIONS.md` |
| A-3 | 新增 `docs/implementation/M0-ACCEPTANCE.md` | 自身 | — |
| A-4 | 新增 `docs/implementation/M0-CODING-BRIEF.md` | 存在 | `ls docs/implementation/M0-CODING-BRIEF.md` |
| A-5 | 现有 `docs/plan/invest-infra-v2-etf-vertical-slice-plan.md` 未修改 | git 未变更 | `git diff -- docs/plan/invest-infra-v2-etf-vertical-slice-plan.md` 输出为空 |
| A-6 | 未创建或修改业务代码、迁移、配置 | git 无变更 | `git status --short` 不显示 `apps/ packages/ scripts/ tests/ compose.yaml` 等路径下变更 |

## B. ADR 结构

| ID | 检查项 | 检查方法 |
|---|---|---|
| B-1 | 每份 ADR 必须包含 Status、Context、Decision、Consequences、Alternatives 标题（或语义等价小节） | `rg -n "^(##? )(Status|Context|Decision|Consequences|Alternatives)" docs/adr/0003*.md docs/adr/0004*.md docs/adr/0005*.md docs/adr/0006*.md docs/adr/0007*.md docs/adr/0008*.md docs/adr/0009*.md docs/adr/0010*.md` 每份至少命中 4 个标题 |
| B-2 | ADR-0003 必须显式标注 Provider 选型未冻结，并列出待确认最小项 | 正文中包含 `Provider 最终选型暂不冻结` 与 `用户需最少确认` |
| B-3 | ADR-0004 必须把市场限定为 SSE/SZSE，时区 `Asia/Shanghai` | 包含 `SSE`/`SZSE`/`Asia/Shanghai` 关键字 |
| B-4 | ADR-0005 必须明确只 `none` 可生产 | 包含 `adjustment="none"` 描述并禁止 `qfq/hfq` |
| B-5 | ADR-0006 必须给出主键 `(instrument_id, trade_date, adjustment, revision)` | 包含此复合键 |
| B-6 | ADR-0007 必须给出 snapshot header + rows 表与 SHA-256/canonical JSON 规则 | 包含 `input_snapshot_rows`、canonical JSON 描述 |
| B-7 | ADR-0008 必须给出状态机转换与发布指针 | 包含 `calculated → validated → published` 与 `publication` 描述 |
| B-8 | ADR-0009 必须把运行基线固定为 3.12.x | 包含 `CPython 3.12` 关键字 |
| B-9 | ADR-0010 必须禁止 M0 引入 Redis/Kafka/Kubernetes | 包含 `不引`/`不得`/`Rejected` 表述 |

## C. 跨文档一致性

| ID | 检查项 | 判定方法 |
|---|---|---|
| C-1 | Python 版本：ADR-0009、M0-DECISIONS、M0-CODING-BRIEF 均声明 3.12 基线 | 关键词 3.12 一致 |
| C-2 | 市场：ADR-0004、M0-DECISIONS、M0-CODING-BRIEF 均限定 SSE/SZSE | 关键词一致 |
| C-3 | 复权：ADR-0005、M0-DECISIONS、M0-CODING-BRIEF 均仅允许 `none` | 关键词一致 |
| C-4 | Provider：ADR-0003 显式 `Proposed` 且未冻结；M0-DECISIONS 列入未决 O-1 | 措辞一致 |
| C-5 | 部署：ADR-0010 与 M0-CODING-BRIEF 不引 Redis/Kafka/K8s | 关键词一致 |
| C-6 | `raw.provider_batches` 持久化归属：ADR-0003、M0-DECISIONS 共同声明由 storage/application service 承担 | 表述一致 |
| C-7 | DailyBar 主键：ADR-0006 与 M0-DECISIONS 表述一致 | 主键列名一致 |
| C-8 | input_snapshots 绑定：ADR-0007 与 M0-DECISIONS 共同声明 header + 行级精确绑定 | 表述一致 |
| C-9 | 候选池状态机：ADR-0008 与 M0-DECISIONS 转换集合一致 | 转换集合一致 |
| C-10 | `app.pipeline_runs` 升级路径：M0-DECISIONS 与 M0-CODING-BRIEF 共同声明为 `ops.pipeline_runs` 升级 | 表述一致 |

## D. 业务代码与基础设施不变

| ID | 检查项 | 检查命令（只读） |
|---|---|---|
| D-1 | 无业务代码变更 | `git status --short` 输出在 `apps/api/src/ apps/pipeline/src/ packages/` 下为空 |
| D-2 | 无 Alembic 迁移变更 | `git status --short` 在 `apps/api/migrations/` 下为空 |
| D-3 | 无依赖变更 | `git status --short` 在 `pyproject.toml`/`uv.lock` 下为空 |
| D-4 | 无 Compose/配置变更 | `git status --short` 在 `compose.yaml` `.env.example` 下为空 |
| D-5 | `scripts/check_architecture.py` 与 `.github/workflows/ci.yml` 未被修改 | `git diff -- scripts .github` 输出为空 |

## E. Git 卫生

| ID | 检查项 | 检查命令（只读） |
|---|---|---|
| E-1 | `git diff --check` 无冲突标记警告 | `git diff --check` |
| E-2 | `git status --short --untracked-files=all` 仅显示新增 ADR 与 implementation 文档 | 人工核验 |
| E-3 | 未生成任何提交 | `git log -1 --oneline` 与 `M0` 任务前保持一致；本任务不执行 `git add`/`commit` |
| E-4 | 文档无伪造事实：Provider 价格、SLA、授权、凭据未在 ADR/implementation 文档中编造 | 全文搜素 `password/token/secret` 仅在 `.env.example`（已存在）与 ADR/impl 提及“禁止提交/日志脱敏/分权”的措辞中 |

## F. 通过标准

- A、B、C、D、E 全部通过。
- 任意 ADR 或 implementation 文档存在与 M0-DECISIONS 冲突的事实陈述，视为不通过。
- 任何在 ADR/implementation 中编造的价格、合同、SLA 或凭据细节，视为不通过。
- 任何对业务代码、迁移或配置的修改，视为不通过。
