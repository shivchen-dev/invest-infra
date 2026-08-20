# 投研系统运行端口权威

本文件是 `invest-infra` 当前运行端口的唯一文档权威。代码、部署配置和操作手册出现端口时必须与本表一致；历史验收记录中的地址只描述当次证据，不得据此新增业务入口。

## 权威端口

| 端口 | 服务 | 对外用途 | 当前承载方式 |
|---|---|---|---|
| `8000` | FastAPI | API 与 `/docs`；局域网集成统一使用 `<host>:8000` | 用户级 systemd 或 Compose，二选一 |
| `5432` | PostgreSQL | 当前 API 与 Pipeline 的唯一数据库 | `invest-infra-postgres-1` |
| `3001` | React Web | 浏览器访问入口 | Compose 映射到 Web 容器内部端口 |
| `3000` | Dagster | Pipeline 管理界面 | 用户级 systemd 或 Compose，二选一 |

默认本机入口：

```text
Web         http://localhost:3001
API         http://localhost:8000
API Docs    http://localhost:8000/docs
Dagster     http://localhost:3000
PostgreSQL  localhost:5432
```

## 运行方式不得混用

当前宿主机可采用以下任一方式：

1. 用户级 systemd 托管 API/Dagster，Docker 只运行 PostgreSQL；
2. `docker compose up --build` 托管 PostgreSQL、API、Web 和 Dagster。

同一服务不得同时由 systemd 和 Compose 启动。尤其是 API 都使用 `8000`、Dagster 都使用 `3000`，混用会直接产生端口冲突。

状态确认：

```bash
systemctl --user status invest-infra-api.service
systemctl --user status invest-infra-dagster.service
docker compose ps
ss -ltnp | grep -E ':(3000|3001|5432|8000)\\b'
```

## 非业务入口

- `5173` 是 Web 容器内部或本地 Vite 开发端口，不对使用者发布；
- `5174` 仅供 Playwright 测试临时使用；
- `5433` 不属于当前数据库链路，当前应用不得连接；
- `9000/9001` 不属于当前 `invest-infra` 运行合同。

不得在 README、活动计划或运行手册中把这些端口描述成当前投研系统入口。
