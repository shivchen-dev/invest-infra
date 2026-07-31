# invest-infra-v2 starter

这是一个面向投研系统的 **greenfield v2 骨架**。它不迁移旧系统数据，只复用经过确认的业务语义、算法与验收样例。

## 设计目标

1. Python 继续承担金融数据与计算优势，但 API、流水线和研究环境不共享依赖。
2. 先采用模块化单体和独立进程，不提前引入微服务、Kafka、Redis 或 Kubernetes。
3. PostgreSQL 是首期唯一持久化基础设施。
4. 数据源通过 Provider 接口隔离；业务代码不直接依赖 AkShare 等第三方 SDK。
5. 每个计算结果记录 `run_id`、算法版本与数据时间。
6. 前端只通过 OpenAPI API 访问数据。

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

## 首个垂直切片

```text
Fixture Provider (fixture_dev)
    ↓
Dagster seed_instruments asset
    ↓
PostgreSQL core.instruments
    ↓
FastAPI /v1/instruments
    ↓
React 仪表盘
```

正式接入真实数据源时，只新增 Provider 适配器，不能让领域层直接导入数据源 SDK。

## 启动

前置要求：Docker、Docker Compose。

```bash
cp .env.example .env
docker compose up --build
```

然后访问：

- Web: http://localhost:5173
- API 文档: http://localhost:8000/docs
- Dagster: http://localhost:3000

首次启动后执行迁移：

```bash
docker compose exec api uv run alembic upgrade head
```

在 Dagster 页面 materialize `seed_instruments`，再刷新 Web 页面。

## 本地开发

推荐安装 `uv`、Node.js 和 pnpm：

```bash
make lock  # 首次联网解析后提交各自的 uv.lock
make arch-check
make test
```

## 明确不做

- 不复制旧系统的 43 张表。
- 不复制 cron/systemd/subprocess 调度。
- 不建立 TypeScript 后端和第二套数据库模型。
- 不在第一阶段引入 Redis、MinIO、消息队列和微服务。
- 不把 Notebook 或 `vectorbt[full]` 装进 API 镜像。

详细决策见 `docs/ARCHITECTURE.md` 和 `docs/REWRITE_PLAN.md`。

## 骨架验证状态

已执行 Python 语法编译、领域单元测试和架构依赖检查。由于生成环境没有 Docker 与外部包下载能力，容器构建和完整依赖安装需要在实际开发机或 CI 中完成。
