#!/usr/bin/env python3
"""
cron_index_end_of_day.py — 收盘后指数+成分股+南向资金+北向成交额数据采集
========================================================

调度：每个交易日 16:00（周一~五）
  python3 scripts/cron_index_end_of_day.py

采集内容：
  1. 8个宽基指数日线 → index_quotes（RssCast StockIndexKLineQuery）
  2. 5只成分股日线 → daily_quotes（RssCast StockKLineQuery）
  3. 南向资金日数据 → south_flow_hist（Eastmoney RPT_MUTUAL_DEAL_HISTORY）
  4. 北向资金成交额 → north_turnover_hist（Eastmoney RPT_MUTUAL_DEALAMT）

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


# ── 辅助函数 ────────────────────────────────────────────────────────────────
def _enrich_change_pct(records: list[dict]) -> list[dict]:
    """
    为指数 K 线记录补充 pre_close 和 change_pct。
    策略：查询每个指数前一交易日的收盘价，计算 change_pct。
    """
    if not records:
        return records
    trade_date = records[0].get("trade_date")
    if not trade_date:
        return records

    from datetime import date, timedelta
    # 找出前一交易日（查 index_quotes 中该日之前最近有数据的日期）
    today_date = date.fromisoformat(trade_date)
    codes = list({r.get("index_code", "") for r in records})
    with pg_loader.get_conn() as conn:
        with conn.cursor() as cur:
            from src.loader.pg import get_index_id_map
            idx_map = get_index_id_map(conn)
            id_to_code = {v: k for k, v in idx_map.items()}
            # 对每个指数查前一交易日收盘价
            prev_close_map = {}
            for code in codes:
                idx_id = idx_map.get(code)
                if idx_id is None:
                    continue
                cur.execute(
                    "SELECT close_point FROM index_quotes "
                    "WHERE index_id = %s AND trade_date < %s "
                    "ORDER BY trade_date DESC LIMIT 1",
                    (idx_id, trade_date)
                )
                row = cur.fetchone()
                if row and row[0] is not None:
                    prev_close_map[code] = float(row[0])

    for r in records:
        code = r.get("index_code", "")
        prev_close = prev_close_map.get(code)
        r["pre_close"] = prev_close
        if prev_close and prev_close != 0 and r.get("close_point") is not None:
            r["change_pct"] = round((r["close_point"] - prev_close) / prev_close * 100, 4)
        else:
            r["change_pct"] = None
        logger.debug(f"{code}: close={r.get('close_point')} pre_close={prev_close} chg_pct={r.get('change_pct')}")

    return records

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


# ── 南向资金（Eastmoney API，替代已停更的北向数据）───────────────────────
EM_HEADERS = {
    "Referer": "https://data.eastmoney.com/hsgt/index.html",
    "User-Agent": "Mozilla/5.0",
}
EM_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# MUTUAL_TYPE: 002=港股通沪, 004=港股通深, 006=南向资金合计
SOUTH_TYPE_MAP = {
    "002": "港股通沪",
    "004": "港股通深",
    "006": "南向资金合计",
}


def fetch_south_flow_eastmoney(days_back: int = 5) -> list[dict]:
    """
    通过 Eastmoney RPT_MUTUAL_DEAL_HISTORY 获取南向资金数据（港股通沪+深+合计）。
    北向资金已于 2024-08-16 起停更，改采南向资金写入 south_flow_hist。
    """
    records = []
    cutoff = (date.today() - timedelta(days=days_back)).isoformat()

    for type_code, name in SOUTH_TYPE_MAP.items():
        params = {
            "sortColumns": "TRADE_DATE",
            "sortTypes": "-1",
            "pageSize": "100",
            "pageNumber": "1",
            "reportName": "RPT_MUTUAL_DEAL_HISTORY",
            "columns": "TRADE_DATE,NET_DEAL_AMT,BUY_AMT,SELL_AMT,ACCUM_DEAL_AMT",
            "source": "WEB",
            "client": "WEB",
            "filter": f'(MUTUAL_TYPE="{type_code}")',
        }
        try:
            import requests as _req
            r = _req.get(EM_URL, params=params, headers=EM_HEADERS, timeout=10)
            data = r.json()
            if not data.get("success"):
                logger.warning(f"Eastmoney 南向资金({name}) API: {data.get('message')}")
                continue
            result = data["result"]
            for page in range(1, int(result["pages"]) + 1):
                if page > 1:
                    params["pageNumber"] = str(page)
                    r = _req.get(EM_URL, params=params, headers=EM_HEADERS, timeout=10)
                    data = r.json()
                    if not data.get("success"):
                        break
                    result = data["result"]
                for item in result.get("data", []):
                    trade_date = item.get("TRADE_DATE", "")[:10]
                    if trade_date < cutoff:
                        break
                    records.append({
                        "calc_date": trade_date,
                        "hsgt_type": name,
                        "daily_net_buy": float(item.get("NET_DEAL_AMT") or 0),
                        "buy_amount": float(item.get("BUY_AMT") or 0),
                        "sell_amount": float(item.get("SELL_AMT") or 0),
                        "cum_net_buy": float(item.get("ACCUM_DEAL_AMT") or 0),
                        "source": "eastmoney-RPT_MUTUAL_DEAL_HISTORY",
                    })
        except Exception as e:
            logger.error(f"Eastmoney 南向资金({name}) 失败: {e}")

    logger.info(f"Eastmoney 南向资金读取: {len(records)} 条（近{days_back}日）")
    return records


# ── 南向资金写入 ──────────────────────────────────────────────────────────
def upsert_south_flow(records: list[dict]) -> int:
    """写入 south_flow_hist，ON CONFLICT (calc_date, hsgt_type) DO UPDATE"""
    if not records:
        return 0
    rows = []
    for r in records:
        rows.append((
            r.get("calc_date"),
            r.get("hsgt_type"),
            r.get("daily_net_buy"),
            r.get("buy_amount"),
            r.get("sell_amount"),
            r.get("cum_net_buy"),
            r.get("source", "eastmoney-RPT_MUTUAL_DEAL_HISTORY"),
        ))
    with pg_loader.get_conn() as conn:
        with conn.cursor() as cur:
            from psycopg2.extras import execute_batch
            execute_batch(cur, """
                INSERT INTO south_flow_hist
                    (calc_date, hsgt_type, daily_net_buy, buy_amount, sell_amount,
                     cum_net_buy, source)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (calc_date, hsgt_type) DO UPDATE SET
                    daily_net_buy=EXCLUDED.daily_net_buy,
                    buy_amount=EXCLUDED.buy_amount,
                    sell_amount=EXCLUDED.sell_amount,
                    cum_net_buy=EXCLUDED.cum_net_buy
            """, rows)
        conn.commit()
    return len(rows)


# ── 北向资金成交额（Eastmoney RPT_MUTUAL_DEALAMT）────────────────────────
def fetch_north_turnover_eastmoney(days_back: int = 5) -> list[dict]:
    """
    通过 Eastmoney RPT_MUTUAL_DEALAMT 获取北向资金成交额（万元）。
    北向资金净买额已停更，但成交额（NF_DEAL_AMT）仍每日发布。
    """
    cutoff = (date.today() - timedelta(days=days_back)).isoformat()
    params = {
        "sortColumns": "TRADE_DATE",
        "sortTypes": "-1",
        "pageSize": "100",
        "pageNumber": "1",
        "reportName": "RPT_MUTUAL_DEALAMT",
        "columns": "TRADE_DATE,NF_DEAL_AMT,SSC_DEAL_AMT,ST_DEAL_AMT,CSI300_INDEX_PRICE,CSI300_INDEX_RATE",
        "source": "WEB",
        "client": "WEB",
    }
    records = []
    try:
        import requests as _req
        r = _req.get(EM_URL, params=params, headers=EM_HEADERS, timeout=10)
        data = r.json()
        if not data.get("success"):
            logger.warning(f"Eastmoney 北向成交额 API: {data.get('message')}")
            return []
        result = data["result"]
        total_pages = int(result.get("pages", 1))
        for page in range(1, total_pages + 1):
            if page > 1:
                params2 = dict(params, pageNumber=str(page))
                r = _req.get(EM_URL, params=params2, headers=EM_HEADERS, timeout=10)
                data = r.json()
                if not data.get("success"):
                    break
                result = data["result"]
            for item in result.get("data", []):
                trade_date = item.get("TRADE_DATE", "")[:10]
                if trade_date < cutoff:
                    return records
                records.append({
                    "calc_date": trade_date,
                    "nf_deal_amt": float(item.get("NF_DEAL_AMT") or 0),
                    "ssc_deal_amt": float(item.get("SSC_DEAL_AMT") or 0),
                    "st_deal_amt": float(item.get("ST_DEAL_AMT") or 0),
                    "csi300_index_price": float(item.get("CSI300_INDEX_PRICE") or 0),
                    "csi300_index_rate": float(item.get("CSI300_INDEX_RATE") or 0),
                    "source": "eastmoney-RPT_MUTUAL_DEALAMT",
                })
        logger.info(f"Eastmoney 北向成交额读取: {len(records)} 条（近{days_back}日）")
    except Exception as e:
        logger.error(f"Eastmoney 北向成交额失败: {e}")
    return records


def upsert_north_turnover(records: list[dict]) -> int:
    """写入 north_turnover_hist，ON CONFLICT (calc_date) DO UPDATE"""
    if not records:
        return 0
    rows = []
    for r in records:
        rows.append((
            r.get("calc_date"),
            r.get("nf_deal_amt"),
            r.get("ssc_deal_amt"),
            r.get("st_deal_amt"),
            r.get("csi300_index_price"),
            r.get("csi300_index_rate"),
            r.get("source", "eastmoney-RPT_MUTUAL_DEALAMT"),
        ))
    with pg_loader.get_conn() as conn:
        with conn.cursor() as cur:
            from psycopg2.extras import execute_batch
            execute_batch(cur, """
                INSERT INTO north_turnover_hist
                    (calc_date, nf_deal_amt, ssc_deal_amt, st_deal_amt,
                     csi300_index_price, csi300_index_rate, source)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (calc_date) DO UPDATE SET
                    nf_deal_amt=EXCLUDED.nf_deal_amt,
                    ssc_deal_amt=EXCLUDED.ssc_deal_amt,
                    st_deal_amt=EXCLUDED.st_deal_amt,
                    csi300_index_price=EXCLUDED.csi300_index_price,
                    csi300_index_rate=EXCLUDED.csi300_index_rate
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
            idx_klines = _enrich_change_pct(idx_klines)
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

    # ── Step 3：南向资金（北向已停更，改采南向）───────────────────────────
    t0 = time.time()
    try:
        south_records = fetch_south_flow_eastmoney(days_back=5)
        if south_records:
            written = upsert_south_flow(south_records)
            steps["south_flow"] = {"written": written, "elapsed_s": round(time.time() - t0, 2)}
            total_written += written
            logger.info(f"南向资金写入: {written} 条")
        else:
            steps["south_flow"] = {"written": 0, "note": "empty"}
    except Exception as e:
        logger.error(f"南向资金采集失败: {e}")
        steps["south_flow"] = {"error": str(e)}

    # ── Step 4：北向资金成交额（RPT_MUTUAL_DEALAMT）─────────────────────
    t0 = time.time()
    try:
        north_recs = fetch_north_turnover_eastmoney(days_back=5)
        if north_recs:
            written = upsert_north_turnover(north_recs)
            steps["north_turnover"] = {"written": written, "elapsed_s": round(time.time() - t0, 2)}
            total_written += written
            logger.info(f"北向成交额写入: {written} 条")
        else:
            steps["north_turnover"] = {"written": 0, "note": "empty"}
    except Exception as e:
        logger.error(f"北向成交额采集失败: {e}")
        steps["north_turnover"] = {"error": str(e)}

    logger.info(
        f"[{today}] 采集完成: "
        f"index={steps.get('index_kline',{}).get('written',0)} "
        f"stock={steps.get('stock_kline',{}).get('written',0)} "
        f"south={steps.get('south_flow',{}).get('written',0)} "
        f"north_turnover={steps.get('north_turnover',{}).get('written',0)} "
        f"total={total_written}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())