#!/usr/bin/env python3
"""
cron_index_end_of_day.py — 收盘后指数+成分股+北向资金数据采集
========================================================

调度：每个交易日 16:00（周一~五）
  python3 scripts/cron_index_end_of_day.py

采集内容：
  1. 8个宽基指数日线 → index_quotes（RssCast StockIndexKLineQuery）
  2. 5只成分股日线 → daily_quotes（RssCast StockKLineQuery）
  3. 北向资金日数据 → north_flow_hist（akshare stock_hsgt_hist_em）

时序保证：
  16:00 采集当日 K 线数据 → 下一个交易日 06:00 Morning Briefing 直接读取 T-1 数据
"""

import sys
import os
import time
import logging
import logging.handlers
from datetime import date, timedelta
from pathlib import Path

# ── 路径初始化 ─────────────────────────────────────────────────────────────
sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")
os.chdir("/home/claw/invest-infra/data-pipeline")

# ── 环境变量加载（从多个文件读取，合并到 os.environ）────────────────────
# 优先级：os.environ > .env > .secrets/tokens.env
_pipeline_dir = Path(__file__).resolve().parent.parent
_secrets_dir = _pipeline_dir.parent / ".secrets"

def _load_env(filepath):
    """加载 .env 或 tokens.env 文件，解析 k=v 写入 os.environ"""
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

# 先加载 secrets（备用），再加载 .env（优先）
_loaded_secrets = _load_env(_secrets_dir / "tokens.env")
_loaded_dotenv = _load_env(_pipeline_dir / ".env")
sys.stderr.write(f"[ENV] 已加载: .env({len(_loaded_dotenv)}个) + secrets({len(_loaded_secrets)}个)\n")

import psycopg2
import pandas as pd
import akshare as ak
from src.collector.rsscast import RssCastClient
from src.loader import pg as pg_loader

# ── 日志配置 ────────────────────────────────────────────────────────────────
LOG_DIR = Path("/home/claw/invest-infra/data-pipeline/logs")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "cron_index_end_of_day.log"

_log = logging.getLogger()
_log.setLevel(logging.INFO)
if not _log.handlers:
    _log.addHandler(
        logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    )
    _log.addHandler(logging.StreamHandler(sys.stdout))

logger = logging.getLogger("cron_index_end_of_day")

# ── 常量 ──────────────────────────────────────────────────────────────────
WIDE_INDEX_CODES = ["000001", "399001", "000300", "000016", "000688", "399006", "000905", "000852"]
CONSTITUENT_CODES = ["600519", "601398", "000001", "000002", "600036"]
# 北向资金字段映射（akshare 列名 → north_flow_hist 列名）
AKSHARE_NORTH_COLS = {
    "日期": "calc_date",
    "当日成交净买额": "daily_net_buy",
    "买入成交额": "buy_amount",
    "卖出成交额": "sell_amount",
    "历史累计净买额": "cum_net_buy",
    "持股市值": "hold_market_val",
    "沪深300": "hs300",
}


# ── RssCast Client ────────────────────────────────────────────────────────
def get_rsscast_client() -> RssCastClient:
    endpoint = os.environ.get("RSSCAST_ENDPOINT", "")
    token = os.environ.get("RSSCAST_TOKEN", "")
    if not endpoint or not token:
        raise RuntimeError("RSSCAST_ENDPOINT / RSSCAST_TOKEN 未设置")
    return RssCastClient(endpoint, token)


# ── 北向资金（akshare）───────────────────────────────────────────────────
def fetch_north_flow_akshare(days_back: int = 5) -> list[dict]:
    """通过 akshare stock_hsgt_hist_em 获取北向资金数据"""
    records = []
    try:
        df = ak.stock_hsgt_hist_em(symbol="北向资金")
        # 过滤出近 days_back 个交易日
        df["日期_dt"] = pd.to_datetime(df["日期"]).dt.date
        cutoff = (date.today() - timedelta(days=days_back))
        df = df[df["日期_dt"] >= cutoff]
        for _, row in df.iterrows():
            records.append({
                "calc_date": row["日期"],
                "daily_net_buy": row.get("当日成交净买额"),
                "buy_amount": row.get("买入成交额"),
                "sell_amount": row.get("卖出成交额"),
                "cum_net_buy": row.get("历史累计净买额"),
                "hold_market_val": row.get("持股市值"),
                "hs300": row.get("沪深300"),
                "source": "akshare-hsgt",
            })
        logger.info(f"akshare 北向资金读取: {len(records)} 条（近{days_back}日）")
    except Exception as e:
        logger.error(f"akshare 北向资金失败: {e}")
    return records


# ── 北向资金写入 ────────────────────────────────────────────────────────────
def upsert_north_flow(records: list[dict]) -> int:
    """写入 north_flow_hist，ON CONFLICT (calc_date) DO UPDATE"""
    if not records:
        return 0
    rows = []
    for r in records:
        rows.append((
            r.get("calc_date"),
            r.get("daily_net_buy"),
            r.get("buy_amount"),
            r.get("sell_amount"),
            r.get("cum_net_buy"),
            r.get("hold_market_val"),
            r.get("hs300"),
            r.get("source", "akshare-hsgt"),
        ))
    with pg_loader.get_conn() as conn:
        with conn.cursor() as cur:
            from psycopg2.extras import execute_batch
            execute_batch(cur, """
                INSERT INTO north_flow_hist
                    (calc_date, daily_net_buy, buy_amount, sell_amount,
                     cum_net_buy, hold_market_val, hs300, source)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (calc_date) DO UPDATE SET
                    daily_net_buy=EXCLUDED.daily_net_buy,
                    buy_amount=EXCLUDED.buy_amount,
                    sell_amount=EXCLUDED.sell_amount,
                    cum_net_buy=EXCLUDED.cum_net_buy,
                    hold_market_val=EXCLUDED.hold_market_val,
                    hs300=EXCLUDED.hs300
            """, rows)
        conn.commit()
    return len(rows)


# ── 主流程 ────────────────────────────────────────────────────────────────
def main() -> int:
    today = date.today()
    logger.info(f"[{today}] 收盘后数据采集开始")

    try:
        client = get_rsscast_client()
    except RuntimeError as e:
        logger.error(f"RssCast 初始化失败: {e}")
        return 1

    steps = {}
    total_written = 0

    # ── Step 1：宽基指数 K 线 ────────────────────────────────────────────
    t0 = time.time()
    try:
        idx_klines = client.fetch_index_kline_normalized(
            WIDE_INDEX_CODES,
            start_date=today,
            end_date=today,
        )
        if idx_klines:
            pg_loader.batch_upsert_index_quotes(idx_klines)
            steps["index_kline"] = {"written": len(idx_klines), "elapsed_s": round(time.time() - t0, 2)}
            total_written += len(idx_klines)
            logger.info(f"指数 K 线写入: {len(idx_klines)} 条")
        else:
            steps["index_kline"] = {"written": 0, "note": "empty"}
            logger.warning("RssCast 返回空指数 K 线")
    except Exception as e:
        logger.error(f"指数 K 线采集失败: {e}")
        steps["index_kline"] = {"error": str(e)}

    # ── Step 2：成分股 K 线 ─────────────────────────────────────────────
    t0 = time.time()
    try:
        stock_klines = client.fetch_stock_kline_normalized(
            CONSTITUENT_CODES,
            start_date=today,
            end_date=today,
        )
        if stock_klines:
            pg_loader.batch_upsert_quotes(stock_klines)
            steps["stock_kline"] = {"written": len(stock_klines), "elapsed_s": round(time.time() - t0, 2)}
            total_written += len(stock_klines)
            logger.info(f"成分股 K 线写入: {len(stock_klines)} 条")
        else:
            steps["stock_kline"] = {"written": 0, "note": "empty"}
            logger.warning("RssCast 返回空成分股 K 线")
    except Exception as e:
        logger.error(f"成分股 K 线采集失败: {e}")
        steps["stock_kline"] = {"error": str(e)}

    # ── Step 3：北向资金 ────────────────────────────────────────────────
    t0 = time.time()
    try:
        north_records = fetch_north_flow_akshare(days_back=5)
        if north_records:
            written = upsert_north_flow(north_records)
            steps["north_flow"] = {"written": written, "elapsed_s": round(time.time() - t0, 2)}
            total_written += written
            logger.info(f"北向资金写入: {written} 条")
        else:
            steps["north_flow"] = {"written": 0, "note": "empty"}
    except Exception as e:
        logger.error(f"北向资金采集失败: {e}")
        steps["north_flow"] = {"error": str(e)}

    logger.info(
        f"[{today}] 采集完成: "
        f"index={steps.get('index_kline',{}).get('written',0)} "
        f"stock={steps.get('stock_kline',{}).get('written',0)} "
        f"north={steps.get('north_flow',{}).get('written',0)} "
        f"total={total_written}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())