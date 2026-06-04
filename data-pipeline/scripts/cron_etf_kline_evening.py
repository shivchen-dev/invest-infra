#!/usr/bin/env python3
"""
cron_etf_kline_evening.py — 盘后 ETF 历史K线采集（次方量化）
================================================================
调度：每个交易日 16:10（周一~五），接在 cia_index_end_of_day (16:00) 之后
采集：当日 K 线（增量）→ etf_quotes（source=cifang，等比复权 qfq）

数据源：次方量化 fetch_fund_hist(symbol, start_date, end_date, adjust='qfq')
优势：等比复权（分红再投资质量）vs akshare 非等比复权

增量逻辑：
  1. 读取每只 ETF 最近已采日期
  2. 仅采集缺失日期（最多回补 5 天，避免漏采假期）
  3. 全量回补（2025-01-02 起）仅由 sync_cifang_backfill.py 独立处理
"""

import sys
import os
import time
import logging
import logging.handlers
from datetime import date, datetime, timedelta
from pathlib import Path

# ── 路径初始化 ─────────────────────────────────────────────────────────────
_pipeline_dir = Path(__file__).resolve().parent.parent
_secrets_dir = _pipeline_dir.parent / ".secrets"

def _load_env(filepath):
    loaded = []
    if filepath and filepath.exists():
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k:
                    os.environ.setdefault(k, v)
                    loaded.append(k)
    return loaded

_load_env(_secrets_dir / "tokens.env")
_load_env(_pipeline_dir / ".env")

sys.path.insert(0, str(_pipeline_dir))
os.chdir(str(_pipeline_dir))

# ── 日志 ────────────────────────────────────────────────────────────────────
_log_dir = _pipeline_dir / "logs"
_log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(_log_dir / "etf_kline_cifang.log", maxBytes=10_000_000, backupCount=3),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("etf_kline_cifang")

# ── 主逻辑 ─────────────────────────────────────────────────────────────────
from src.collector.cifang import fetch_fund_hist, fetch_fund_spot, backfill_hist
import psycopg2
from src.config import pg

MAX_LOOKBACK_DAYS = 5   # 增量回补最多回看 5 天（防止假期断档漏采）
BATCH_SLEEP_SEC = 1.0  # 每 50 只暂停 1 秒（避免触发次方量化 QPS 限制）


def _get_latest_quote_date(conn, etf_id: int) -> date | None:
    """返回某 ETF 最近已采的行情日期（不含当天 spot 数据）"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(trade_date) FROM etf_quotes WHERE etf_id = %s AND source = 'cifang'",
            (etf_id,),
        )
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def _needs_backfill(conn, etf_id: int, today: date) -> date | None:
    """
    判断是否需要回补。
    返回：需要回补的起始日期（不含已采日期），若无需回补返回 None。
    """
    last_date = _get_latest_quote_date(conn, etf_id)
    if last_date is None:
        # 从 2025-01-02 开始（仅第一次，后续由 sync_cifang_backfill.py 处理全量）
        return date(2025, 1, 2)
    if last_date >= today:
        return None
    # 增量：最多回补 MAX_LOOKBACK_DAYS 天
    cutoff = today - timedelta(days=MAX_LOOKBACK_DAYS)
    if last_date < cutoff:
        # 超过 5 天未采，说明积压严重，触发全量回补（由 sync_cifang_backfill.py 处理）
        return None
    if (today - last_date).days <= 1:
        return None  # 只差 1 天（今天），无需回补
    return last_date + timedelta(days=1)


def main():
    today = date.today()
    logger.info("ETF历史K线采集开始（次方量化，等比复权）: today=%s", today)

    spot = fetch_fund_spot()
    if not spot:
        logger.warning("次方量化返回 0 只 ETF，中止")
        sys.exit(1)

    logger.info("ETF 列表: %d 只", len(spot))

    conn = psycopg2.connect(pg.uri)
    try:
        total_written = 0
        total_skipped = 0
        total_errors = 0
        t0 = time.time()

        for i, (code, etf_info) in enumerate(spot.items(), 1):
            etf_name = etf_info.get("name", "")[:8]

            # 查找 etf_id
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM etfs WHERE code = %s", (code,))
                row = cur.fetchone()
                if not row:
                    logger.debug("  [%d/%d] %s %s: 未收录，跳过", i, len(spot), code, etf_name)
                    continue
                etf_id = row[0]

            start_date = _needs_backfill(conn, etf_id, today)
            if start_date is None:
                logger.debug("  [%d/%d] %s %s: 无需回补", i, len(spot), code, etf_name)
                total_skipped += 1
                continue

            try:
                written = backfill_hist(code, start_date, today, adjust="qfq")
                total_written += written
                if written > 0:
                    logger.info("  [%d/%d] %s %s: 写 %d 条 (%s ~ %s)", i, len(spot), code, etf_name, written, start_date, today)
            except Exception as e:
                total_errors += 1
                logger.warning("  [%d/%d] %s %s: 失败 -> %s", i, len(spot), code, etf_name, e)

            # 限速
            if i % 50 == 0:
                time.sleep(BATCH_SLEEP_SEC)

        elapsed = time.time() - t0
        logger.info("采集完成: 写入 %d 条, 跳过 %d 只, 失败 %d 只, 耗时 %.1fs",
                    total_written, total_skipped, total_errors, elapsed)
    finally:
        conn.close()


if __name__ == "__main__":
    main()