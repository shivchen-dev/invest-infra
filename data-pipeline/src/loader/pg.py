"""PostgreSQL 批量数据写入 — Silver 层入库"""

import logging
import math
from typing import Callable

import psycopg2
from psycopg2.extras import execute_batch

from src.config import pg

logger = logging.getLogger(__name__)


def _nan_to_none(v):
    """过滤 NaN/Inf → None（BIGINT 字段不接受 NaN）"""
    if v is None:
        return None
    try:
        if math.isnan(v) or math.isinf(v):
            return None
    except TypeError:
        pass
    return v


def _normalize_date(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, str) and "T" in v:
        return v.split("T")[0]
    return v


# ── 公司 ────────────────────────────────────────────────────────

def get_company_id_map(conn) -> dict[str, int]:
    """返回 {code_stripped: id}，code 去掉 .SZ/.SH/.BJ 后缀"""
    with conn.cursor() as cur:
        cur.execute("SELECT code, id FROM companies")
        return {row[0].split(".")[0]: row[1] for row in cur.fetchall()}


def batch_upsert_quotes(records: list[dict]) -> dict:
    if not records:
        return {"written": 0}
    conn = psycopg2.connect(pg.uri)
    try:
        code_map = get_company_id_map(conn)
        rows, skipped = [], 0
        for r in records:
            raw_code = r.get("stock_code", "")
            code_key = raw_code.split(".")[0]
            cid = code_map.get(code_key)
            if cid is None:
                skipped += 1
                continue
            rows.append((
                cid,
                _normalize_date(r.get("trade_date")),
                _nan_to_none(r.get("open_price")),
                _nan_to_none(r.get("high_price")),
                _nan_to_none(r.get("low_price")),
                _nan_to_none(r.get("close_price")),
                _nan_to_none(r.get("pre_close")),
                _nan_to_none(r.get("volume")),
                _nan_to_none(r.get("amount")),
                _nan_to_none(r.get("turnover_rate")),
                _nan_to_none(r.get("amplitude")),
                _nan_to_none(r.get("change_pct")),
                r.get("source", "akshare"),
            ))

        if not rows:
            return {"written": 0, "skipped": skipped}

        with conn.cursor() as cur:
            execute_batch(cur, """
                INSERT INTO daily_quotes
                    (company_id, trade_date, open_price, high_price, low_price,
                     close_price, pre_close, volume, amount, turnover_rate,
                     amplitude, change_pct, source)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (company_id, trade_date) DO UPDATE SET
                    open_price=EXCLUDED.open_price, high_price=EXCLUDED.high_price,
                    low_price=EXCLUDED.low_price, close_price=EXCLUDED.close_price,
                    pre_close=EXCLUDED.pre_close, volume=EXCLUDED.volume,
                    amount=EXCLUDED.amount, turnover_rate=EXCLUDED.turnover_rate,
                    amplitude=EXCLUDED.amplitude, change_pct=EXCLUDED.change_pct
            """, rows)
        conn.commit()
        logger.info(f"行情入库:写入 {len(rows)}, 跳过 {skipped}")
        return {"written": len(rows), "skipped": skipped}
    finally:
        conn.close()


def batch_upsert_financial(records: list[dict]) -> dict:
    if not records:
        return {"written": 0}
    conn = psycopg2.connect(pg.uri)
    try:
        code_map = get_company_id_map(conn)
        rows, skipped = [], 0
        for r in records:
            raw_code = r.get("stock_code", "")
            code_key = raw_code.split(".")[0]
            cid = code_map.get(code_key)
            if cid is None:
                skipped += 1
                continue
            rows.append((
                cid,
                r.get("report_date"),
                r.get("report_type"),
                r.get("fiscal_year"),
                _nan_to_none(r.get("revenue")),
                _nan_to_none(r.get("cost_of_sales")),
                _nan_to_none(r.get("net_profit")),
                _nan_to_none(r.get("parent_net_profit")),
                _nan_to_none(r.get("total_assets")),
                _nan_to_none(r.get("total_liabilities")),
                _nan_to_none(r.get("total_equity")),
                _nan_to_none(r.get("operating_cf")),
                r.get("source", "akshare"),
            ))

        if not rows:
            return {"written": 0, "skipped": skipped}

        with conn.cursor() as cur:
            execute_batch(cur, """
                INSERT INTO financial_reports
                    (company_id, report_date, report_type, fiscal_year,
                     revenue, cost_of_sales, net_profit, parent_net_profit,
                     total_assets, total_liabilities, total_equity,
                     operating_cf, source)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (company_id, report_date, report_type) DO UPDATE SET
                    revenue=EXCLUDED.revenue, cost_of_sales=EXCLUDED.cost_of_sales,
                    net_profit=EXCLUDED.net_profit,
                    parent_net_profit=EXCLUDED.parent_net_profit,
                    total_assets=EXCLUDED.total_assets,
                    total_liabilities=EXCLUDED.total_liabilities,
                    total_equity=EXCLUDED.total_equity,
                    operating_cf=EXCLUDED.operating_cf
            """, rows)
        conn.commit()
        logger.info(f"财报入库: 写入 {len(rows)}, 跳过 {skipped}")
        return {"written": len(rows), "skipped": skipped}
    finally:
        conn.close()


def batch_upsert_news(records: list[dict]) -> dict:
    if not records:
        return {"written": 0}
    conn = psycopg2.connect(pg.uri)
    try:
        code_map = get_company_id_map(conn)
        rows, skipped = [], 0
        for r in records:
            raw_code = r.get("stock_code", "")
            code_key = raw_code.split(".")[0]
            cid = code_map.get(code_key)
            if cid is None:
                skipped += 1
                continue
            rows.append((
                cid,
                r.get("title", ""),
                str(r.get("content_summary", ""))[:500],
                r.get("source_name", ""),
                r.get("source_url", ""),
                r.get("published_at"),
            ))

        if not rows:
            return {"written": 0, "skipped": skipped}

        with conn.cursor() as cur:
            execute_batch(cur, """
                INSERT INTO news_articles
                    (company_id, title, content_summary, source_name, source_url, published_at)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
            """, rows)
        conn.commit()
        # execute_batch 不返回 rowcount，逐条再统计太慢，
        # 用 batch size 近似（ON CONFLICT DO NOTHING 时 rowcount 不准确）
        logger.info(f"新闻入库: 写入 ~{len(rows)}")
        return {"written": len(rows), "skipped": skipped}
    finally:
        conn.close()


# ── 指数 ────────────────────────────────────────────────────────

def get_index_id_map(conn) -> dict[str, int]:
    """返回 {code: id} 映射"""
    with conn.cursor() as cur:
        cur.execute("SELECT code, id FROM indices")
        return {row[0]: row[1] for row in cur.fetchall()}


def batch_upsert_index_quotes(records: list[dict]) -> dict:
    if not records:
        return {"written": 0}
    conn = psycopg2.connect(pg.uri)
    try:
        idx_map = get_index_id_map(conn)
        rows, skipped = [], 0
        for r in records:
            idx_id = idx_map.get(r.get("index_code", ""))
            if idx_id is None:
                skipped += 1
                continue
            rows.append((
                idx_id,
                _normalize_date(r.get("trade_date")),
                _nan_to_none(r.get("open_point")),
                _nan_to_none(r.get("high_point")),
                _nan_to_none(r.get("low_point")),
                _nan_to_none(r.get("close_point")),
                _nan_to_none(r.get("pre_close")),
                _nan_to_none(r.get("volume")),
                _nan_to_none(r.get("amount")),
                _nan_to_none(r.get("change_pct")),
                _nan_to_none(r.get("amplitude")),
                r.get("source", "rsscast"),
            ))

        if not rows:
            return {"written": 0, "skipped": skipped}

        with conn.cursor() as cur:
            execute_batch(cur, """
                INSERT INTO index_quotes
                    (index_id, trade_date, open_point, high_point, low_point,
                     close_point, pre_close, volume, amount, change_pct, amplitude, source)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (index_id, trade_date) DO UPDATE SET
                    open_point=EXCLUDED.open_point, high_point=EXCLUDED.high_point,
                    low_price=EXCLUDED.low_point, close_point=EXCLUDED.close_point,
                    pre_close=EXCLUDED.pre_close, volume=EXCLUDED.volume,
                    amount=EXCLUDED.amount, change_pct=EXCLUDED.change_pct,
                    amplitude=EXCLUDED.amplitude
            """, rows)
        conn.commit()
        logger.info(f"指数行情入库: 写入 {len(rows)}, 跳过 {skipped}")
        return {"written": len(rows), "skipped": skipped}
    finally:
        conn.close()


# ── ETF ─────────────────────────────────────────────────────────

def get_etf_id_map(conn) -> dict[str, int]:
    """返回 {code: id} 映射"""
    with conn.cursor() as cur:
        cur.execute("SELECT code, id FROM etfs")
        return {row[0]: row[1] for row in cur.fetchall()}


def batch_upsert_etf_quotes(records: list[dict]) -> dict:
    if not records:
        return {"written": 0}
    conn = psycopg2.connect(pg.uri)
    try:
        etf_map = get_etf_id_map(conn)
        rows, skipped = [], 0
        for r in records:
            etf_id = etf_map.get(r.get("etf_code", ""))
            if etf_id is None:
                skipped += 1
                continue
            rows.append((
                etf_id,
                _normalize_date(r.get("trade_date")),
                _nan_to_none(r.get("open_price")),
                _nan_to_none(r.get("high_price")),
                _nan_to_none(r.get("low_price")),
                _nan_to_none(r.get("close_price")),
                _nan_to_none(r.get("pre_close")),
                _nan_to_none(r.get("iopv")),
                _nan_to_none(r.get("premium_rate")),
                _nan_to_none(r.get("discount_rate")),
                _nan_to_none(r.get("volume")),
                _nan_to_none(r.get("amount")),
                _nan_to_none(r.get("turnover_rate")),
                _nan_to_none(r.get("amplitude")),
                _nan_to_none(r.get("change_pct")),
                _nan_to_none(r.get("change_amount")),
                r.get("source", "akshare"),
            ))

        if not rows:
            return {"written": 0, "skipped": skipped}

        with conn.cursor() as cur:
            execute_batch(cur, """
                INSERT INTO etf_quotes
                    (etf_id, trade_date, open_price, high_price, low_price,
                     close_price, pre_close, iopv, premium_rate, discount_rate,
                     volume, amount, turnover_rate, amplitude, change_pct,
                     change_amount, source)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (etf_id, trade_date) DO UPDATE SET
                    open_price=EXCLUDED.open_price, high_price=EXCLUDED.high_price,
                    low_price=EXCLUDED.low_price, close_price=EXCLUDED.close_price,
                    pre_close=EXCLUDED.pre_close, iopv=EXCLUDED.iopv,
                    premium_rate=EXCLUDED.premium_rate, discount_rate=EXCLUDED.discount_rate,
                    volume=EXCLUDED.volume, amount=EXCLUDED.amount,
                    turnover_rate=EXCLUDED.turnover_rate, amplitude=EXCLUDED.amplitude,
                    change_pct=EXCLUDED.change_pct, change_amount=EXCLUDED.change_amount
            """, rows)
        conn.commit()
        logger.info(f"ETF行情入库: 写入 {len(rows)}, 跳过 {skipped}")
        return {"written": len(rows), "skipped": skipped}
    finally:
        conn.close()