# 财务数据同步 wrapper — 被 cron 调用
# 用法: run_financial.sh [batch_index]
# 每次采集 150 只（~21min，适配 30min 超时限制）
# offset 由 .sync_financial_state.json 维护，跨批次续跑

cd /home/claw/invest-infra/data-pipeline
source .venv/bin/activate

BATCH_INDEX=${1:-1}
BATCH_COUNT=150

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 财务同步批次 $BATCH_INDEX 开始，采集 $BATCH_COUNT 只"

python scripts/sync_financial.py --count $BATCH_COUNT 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 财务同步批次 $BATCH_INDEX 完成"