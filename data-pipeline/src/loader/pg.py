"""PostgreSQL 批量数据写入 — Silver 层入库"""

import logging

import psycopg2

from src.config import pg

logger = logging.getLogger(__name__)


def get_company_id_map(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT code, id FROM companies")
        return {row[0]: row[1] for row in cur.fetchall()}


def batch_upsert_quotes(records: list[dict]) -> dict:
    if not records:
        return {"written": 0}
    conn = psycopg2.connect(pg.uri)
    try:
        code_map = get_company_id_map(conn)
        written = skipped = 0
        with conn.cursor() as cur:
            for r in records:
                cid = code_map.get(r.get("stock_code", ""))
                if cid is None:
                    skipped += 1
                    continue
                cur.execute(
                    """
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
                    """,
                    (
                        cid,
                        r.get("trade_date"),
                        r.get("open_price"),
                        r.get("high_price"),
                        r.get("low_price"),
                        r.get("close_price"),
                        r.get("pre_close"),
                        r.get("volume"),
                        r.get("amount"),
                        r.get("turnover_rate"),
                        r.get("amplitude"),
                        r.get("change_pct"),
                        r.get("source", "akshare"),
                    ),
                )
                written += 1
        conn.commit()
        logger.info(f"行情入库: 写入 {written}, 跳过 {skipped}")
        return {"written": written, "skipped": skipped}
    finally:
        conn.close()


def batch_upsert_financial(records: list[dict]) -> dict:
    if not records:
        return {"written": 0}
    conn = psycopg2.connect(pg.uri)
    try:
        code_map = get_company_id_map(conn)
        written = skipped = 0
        with conn.cursor() as cur:
            for r in records:
                cid = code_map.get(r.get("stock_code", ""))
                if cid is None:
                    skipped += 1
                    continue
                cur.execute(
                    """
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
                    """,
                    (
                        cid,
                        r.get("report_date"),
                        r.get("report_type"),
                        r.get("fiscal_year"),
                        r.get("revenue"),
                        r.get("cost_of_sales"),
                        r.get("net_profit"),
                        r.get("parent_net_profit"),
                        r.get("total_assets"),
                        r.get("total_liabilities"),
                        r.get("total_equity"),
                        r.get("operating_cf"),
                        r.get("source", "akshare"),
                    ),
                )
                written += 1
        conn.commit()
        logger.info(f"财报入库: 写入 {written}, 跳过 {skipped}")
        return {"written": written, "skipped": skipped}
    finally:
        conn.close()


def batch_upsert_news(records: list[dict]) -> dict:
    if not records:
        return {"written": 0}
    conn = psycopg2.connect(pg.uri)
    try:
        code_map = get_company_id_map(conn)
        written = 0
        with conn.cursor() as cur:
            for r in records:
                cid = code_map.get(r.get("stock_code", ""))
                if cid is None:
                    continue
                cur.execute(
                    """
                    INSERT INTO news_articles
                        (company_id, title, content_summary, source_name, source_url, published_at)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        cid,
                        r.get("title", ""),
                        str(r.get("content_summary", ""))[:500],
                        r.get("source_name", ""),
                        r.get("source_url", ""),
                        r.get("published_at"),
                    ),
                )
                if cur.rowcount:
                    written += 1
        conn.commit()
        logger.info(f"新闻入库: 写入 {written}")
        return {"written": written}
    finally:
        conn.close()
