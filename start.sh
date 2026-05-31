#!/bin/bash
# ============================================
# 智能投研体系 — Phase 0 一键启动
# ============================================
set -e

echo "🚀 启动智能投研基础设施..."
cd "$(dirname "$0")"

# 创建 MinIO 启动后需要初始化的 buckets
docker compose up -d

echo ""
echo "⏳ 等待服务就绪..."

# 等待 PostgreSQL
until docker exec invest-postgres pg_isready -U invest -d investdb > /dev/null 2>&1; do
    sleep 2
done
echo "✅ PostgreSQL 就绪"

# 等待 Redis
until docker exec invest-redis redis-cli ping > /dev/null 2>&1; do
    sleep 1
done
echo "✅ Redis 就绪"

# 等待 MinIO 并创建 buckets
until docker exec invest-minio mc ready local > /dev/null 2>&1; do
    sleep 2
done

# 初始化 MinIO buckets
echo "📦 初始化 MinIO buckets..."
BUCKETS=(
    "bronze-financial"
    "bronze-quotes"
    "bronze-news"
    "bronze-social"
    "silver-processed"
    "gold-memos"
    "gold-backtest"
)
for bucket in "${BUCKETS[@]}"; do
    docker exec invest-minio mc mb "local/${bucket}" --ignore-existing 2>/dev/null
    docker exec invest-minio mc policy set download "local/${bucket}"
done
echo "✅ MinIO 就绪（7 buckets 已创建）"

echo ""
echo "===================================================="
echo "🎉 Phase 0 基础设施启动完成！"
echo "===================================================="
echo "PostgreSQL : localhost:5432 / invest / REDACTED_PG_PASSWORD"
echo "Redis      : localhost:6379"
echo "MinIO API  : http://localhost:9000"
echo "MinIO Web  : http://localhost:9001"
echo "===================================================="
