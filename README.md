# 智能投研体系 — Phase 0 基础设施

## 服务架构

| 服务 | 端口 | 用途 | 持久化 |
|:----|:----|:-----|:------|
| PostgreSQL | 5432 | 数据仓库（Silver + Gold 层） | pgdata volume |
| Redis | 6379 | 缓存 + 消息队列 | redis-data volume |
| MinIO | 9000 (API) / 9001 (Console) | 对象存储（Bronze 原始层） | minio-data volume |

## 快速启动

```bash
# 启动所有服务
docker compose up -d

# 查看状态
docker compose ps

# 查看日志
docker compose logs -f
```

## 连接信息

**PostgreSQL**
- 主机: localhost:5432
- 库名: investdb
- 用户: invest
- 密码: REDACTED_PG_PASSWORD

**Redis**
- 主机: localhost:6379
- 无需密码

**MinIO**
- API: http://localhost:9000
- Console: http://localhost:9001
- 用户: REDACTED_MINIO_USER
- 密码: REDACTED_MINIO_PASSWORD

## 数据层架构

```
Bronze (原始)  → MinIO 对象存储     → raw-{source}-{date}.{format}
Silver (清洗)  → PostgreSQL 表       → daily_quotes, financial_reports, news_articles
Gold (分析)    → PostgreSQL 表       → factor_values, analysis_signals, investment_memos
```

数据库初始化脚本在 `init-db/00_schema.sql`，首次启动 PostgreSQL 时自动执行。
