# invest-infra-v2

这是一个面向 ETF 的 **Evidence-driven AI 投资研判基础设施**。系统以可追溯的数据事实、确定性分析和不可变 Research Evidence 为基础，为后续 AI 研究执行提供受控输入；AI 输出不修改事实数据，也不触发自动交易。

## 设计目标

1. Python 继续承担金融数据与计算优势，但 API、流水线和研究环境不共享依赖。
2. 先采用模块化单体和独立进程，不提前引入微服务、Kafka、Redis 或 Kubernetes。
3. PostgreSQL 是首期唯一持久化基础设施。
4. 数据源通过 Provider 接口隔离；业务代码不直接依赖 AkShare 等第三方 SDK。
5. 每个计算结果记录 `run_id`、算法版本与数据时间。
6. 前端只通过 OpenAPI API 访问数据。
7. Pipeline、Research 和 AI 使用独立生命周期：数据采集运行不等同于研究运行。
8. Candidate Pool 是研究对象来源之一，不是创建 Research Case 的唯一入口。

## 目录

```text
apps/
  api/             FastAPI 查询与应用接口，轻依赖
  pipeline/        Dagster 采集与计算任务，可安装数据科学依赖
  web/             React + TypeScript + Vite
packages/
  domain/          纯领域模型与接口，不依赖框架和数据库
  storage/         SQLAlchemy 表模型与 Repository
scripts/
  check_architecture.py  自动检查禁止依赖
infra/
  sql/             仅用于开发辅助，不作为正式迁移源
```

## 当前能力链路

```text
Provider Evidence
    ↓
Canonical Core Data
    ↓
Analytics / Candidate Pool
    ↓
Research Evidence / Context Projection
    ↓
AI Research（规划中的受控消费方）
```

正式接入真实数据源时，只新增 Provider 适配器，不能让领域层直接导入数据源 SDK。

## 启动

前置要求：Docker、Docker Compose。

```bash
cp .env.example .env
docker compose up --build
```

然后访问：

- Web: http://localhost:3001
- API 文档: http://localhost:8000/docs
- Dagster: http://localhost:3000

首次启动后执行迁移：

```bash
cd apps/migrations && uv run alembic upgrade head
```

（或使用 `make migrate`，独立 migration app 位于 `apps/migrations/`，API 容器不再包含 alembic）

在 Dagster 页面 materialize `seed_instruments`，再刷新 Web 页面。

Web 数据工作台提供以下只读页面：

- `/dashboard`：数据新鲜度、候选池摘要和最新运行；
- `/candidate-pool`：入选/排除候选、筛选、排除原因和变化；
- `/etf/:instrumentId`：ETF 主数据、日行情和收盘价趋势；
- `/operations`：Pipeline Run 历史、数据新鲜度和只读重跑提示。

本地前端检查：

```bash
cd apps/web
pnpm typecheck
```

`apps/web` 不提供写操作，也不会从浏览器触发 Pipeline。

## 本地开发

推荐安装 `uv`、Node.js 和 pnpm：

```bash
make lock  # 首次联网解析后提交各自的 uv.lock
make arch-check
make test
```

## 明确不做

- 不复制旧系统的 43 张表。
- 不复制旧系统的 cron/systemd/subprocess 业务调度；仅使用 systemd 托管
  Dagster 进程，由 Dagster Schedule 负责交易日触发。
- 不建立 TypeScript 后端和第二套数据库模型。
- 不在第一阶段引入 Redis、MinIO、消息队列和微服务。
- 不把 Notebook 或 `vectorbt[full]` 装进 API 镜像。

自动调度的用户级 systemd unit 位于
`deploy/invest-infra-dagster.service`，安装后使用：

```bash
mkdir -p ~/.config/systemd/user
cp deploy/invest-infra-dagster.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now invest-infra-dagster.service
```

详细决策见 `docs/ARCHITECTURE.md`、`docs/ARCHITECTURE-GOVERNANCE.md`、
`docs/adr/` 和
`docs/plan/invest-infra-evidence-driven-research-lifecycle-implementation-plan.md`。

## 验证状态

当前已具备 ETF 主数据、行情、候选池、ETF Profile、指数成分与持仓 Exposure、Evidence Pack/Context Pack 基础能力。DC-3 已通过真实 AkShare、PostgreSQL 幂等复跑、领域/流水线测试和架构检查。Research Case、Research Run、Research Result 与 AI Adapter 仍按增量计划建设。
