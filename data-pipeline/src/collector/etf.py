"""ETF 数据采集器 — 通过 akshare 获取 ETF 实时行情 + 历史K线"""

import logging
from datetime import date, timedelta
from typing import Optional

import akshare as ak

from src.collector.retry import with_retry
from src.config import pg

logger = logging.getLogger(__name__)


# ─── 实时行情 ────────────────────────────────────────────────────────────────


@with_retry()
def fetch_etf_spot() -> list[dict]:
    """
    获取 ETF 实时行情（东方财富），包含 IOPV/溢价率等特有字段。
    返回 [{code, name, latest_price, iopv, premium_rate, volume, amount, ...}, ...]
    """
    logger.info("正在获取 ETF 实时行情 (fund_etf_spot_em) ...")
    try:
        df = ak.fund_etf_spot_em()
    except Exception as e:
        logger.error(f"ETF实时行情获取失败: {e}", exc_info=True)
        return []
    logger.info(f"获取到 {len(df)} 只ETF")
    records = []
    for _, row in df.iterrows():
        code = str(row.get("代码", "")).strip()
        if not code:
            continue
        records.append({
            "code": code,
            "name": str(row.get("名称", "")),
            "short_name": str(row.get("名称", ""))[:6].strip(),
            "category": _categorize(row),
            "exchange_code": "SZSE" if code[0] in ('0', '1', '3') else "SSE",
            "latest_price": row.get("最新价"),
            "iopv": row.get("IOPV实时估值"),
            "premium_rate": row.get("基金折价率"),   # 正=溢价，负=折价
            "volume": row.get("成交量"),
            "amount": row.get("成交额"),
            "open_price": row.get("开盘价"),
            "high_price": row.get("最高价"),
            "low_price": row.get("最低价"),
            "pre_close": row.get("昨收"),
            "change_pct": row.get("涨跌幅"),
            "change_amount": row.get("涨跌额"),
            "amplitude": row.get("振幅"),
            "turnover_rate": row.get("换手率"),
            "update_time": row.get("更新时间"),
        })
    return records


# ─── 历史K线 ──────────────────────────────────────────────────────────────


def _etf_prefix(code: str) -> str:
    """ETF代码转新浪格式：510300 → sh510300, 159919 → sz159919"""
    code = code.strip()
    first = code[0] if code else '5'
    return f"sh{code}" if first == '6' else f"sz{code}"


@with_retry()
def fetch_etf_list() -> list[dict]:
    """
    获取 ETF 列表（实时行情，同 fetch_etf_spot）。
    为兼容旧接口保留。
    """
    return fetch_etf_spot()


def _categorize(row) -> str:
    """根据 ETF 名称关键字判断类别"""
    name = str(row.get("名称", ""))
    if "债券" in name or "国债" in name:
        return "bond"
    elif "黄金" in name or "商品" in name or "原油" in name:
        return "commodity"
    elif "港股" in name or "恒生" in name or "纳斯达克" in name:
        return "cross_border"
    elif "货币" in name or "现金" in name:
        return "money_market"
    return "stock"


@with_retry()
def fetch_etf_hist(code: str, start_date: date, end_date: date) -> list[dict]:
    """
    获取单只 ETF 的历史日线（优先新浪接口，fallback 到东方财富）。

    Returns: [{date, open, high, low, close, volume, amount}, ...]
    """
    sina_symbol = _etf_prefix(code)

    # 优先使用新浪接口（更稳定）
    try:
        df = ak.fund_etf_hist_sina(symbol=sina_symbol)
        if df is not None and not df.empty:
            records = []
            for _, row in df.iterrows():
                date_val = row.get("date")
                if hasattr(date_val, "strftime"):
                    date_str = date_val.strftime("%Y-%m-%d")
                elif isinstance(date_val, str):
                    date_str = str(date_val)[:10]
                else:
                    date_str = str(date_val)

                from datetime import datetime
                try:
                    d = datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if d < start_date or d > end_date:
                    continue

                records.append({
                    "date": date_str,
                    "open": row.get("open"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "close": row.get("close"),
                    "volume": row.get("volume"),
                    "amount": row.get("amount"),
                })
            if records:
                logger.info(f"ETF {code} K线 (新浪): {len(records)} 条")
                return records
    except Exception as e:
        logger.debug(f"ETF {code} 新浪接口失败: {e}")

    # Fallback: 东方财富接口
    try:
        df = ak.fund_etf_hist_em(
            symbol=code,
            period="daily",
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        if df is not None and not df.empty:
            records = []
            for _, row in df.iterrows():
                date_val = row.get("日期")
                if hasattr(date_val, "strftime"):
                    date_str = date_val.strftime("%Y-%m-%d")
                elif isinstance(date_val, str):
                    date_str = str(date_val)[:10]
                else:
                    date_str = str(date_val)
                records.append({
                    "date": date_str,
                    "open": row.get("开盘"),
                    "high": row.get("最高"),
                    "low": row.get("最低"),
                    "close": row.get("收盘"),
                    "volume": row.get("成交量"),
                    "amount": row.get("成交额"),
                })
            if records:
                logger.info(f"ETF {code} K线 (东财): {len(records)} 条")
                return records
    except Exception as e:
        logger.debug(f"ETF {code} 东财接口也失败: {e}")

    logger.warning(f"ETF {code} 历史K线获取失败（新浪+东财均失败）")
    return []


# ─── 同步 ───────────────────────────────────────────────────────────────────


def sync_etfs_to_db(records: list[dict]) -> dict:
    """同步 ETF 列表到 etfs 表（upsert）。"""

    if not records:
        return {"inserted": 0, "updated": 0}

    with pg.get_conn() as conn:
        try:
            with conn.cursor() as cur:
                inserted = updated = 0
                for r in records:
                    cur.execute(
                        """
                        INSERT INTO etfs
                            (code, name, short_name, category, exchange_code)
                        VALUES (%(code)s, %(name)s, %(short_name)s, %(category)s, %(exchange_code)s)
                        ON CONFLICT (code) DO UPDATE SET
                            name = EXCLUDED.name,
                            short_name = EXCLUDED.short_name,
                            category = EXCLUDED.category,
                            updated_at = now()
                        """,
                        r,
                    )
                    if cur.rowcount == 1:
                        inserted += 1
                    else:
                        updated += 1
                conn.commit()
            logger.info(f"ETF列表同步: 新增 {inserted}, 更新 {updated}")
            return {"inserted": inserted, "updated": updated}
        except Exception as e:
            logger.error(f"ETF列表同步失败: {e}", exc_info=True)
            conn.rollback()
            return {"inserted": 0, "updated": 0}


def batch_fetch_etf_hist(start_year: int = 2025, limit: int = 1486) -> int:
    """
    批量采集所有ETF历史K线（2025年至今），写入 etf_quotes 表。

    参数:
        start_year: 起始年份，默认2025
        limit: 最大采集数量，默认1486（全部）
    返回: 写入记录数
    """
    from datetime import date

    # 获取ETF列表
    spot = fetch_etf_spot()
    target = spot[:limit]

    start = date(start_year, 1, 1)
    end = date.today()

    total_written = 0
    errors = 0

    with pg.get_conn() as conn:
        try:
            for i, etf in enumerate(target):
                code = etf["code"]
                sina_symbol = _etf_prefix(code)
                try:
                    df = ak.fund_etf_hist_sina(symbol=sina_symbol)
                    if df is None or df.empty:
                        continue

                    # 过滤2025至今
                    import pandas as pd
                    df["date"] = pd.to_datetime(df["date"]).dt.date
                    df = df[df["date"] >= start]
                    if df.empty:
                        continue

                    # 获取 etf_id
                    with conn.cursor() as cur:
                        cur.execute("SELECT id FROM etfs WHERE code = %s", (code,))
                        row = cur.fetchone()
                        if not row:
                            continue
                        etf_id = row[0]

                    with conn.cursor() as cur:
                        for _, row in df.iterrows():
                            cur.execute("""
                                INSERT INTO etf_quotes
                                    (etf_id, trade_date, open_price, high_price, low_price,
                                     close_price, volume, amount)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                                ON CONFLICT (etf_id, trade_date) DO UPDATE SET
                                    open_price=EXCLUDED.open_price,
                                    high_price=EXCLUDED.high_price,
                                    low_price=EXCLUDED.low_price,
                                    close_price=EXCLUDED.close_price,
                                    volume=EXCLUDED.volume,
                                    amount=EXCLUDED.amount
                                """, (etf_id, row["date"],
                                      row["open"], row["high"], row["low"], row["close"],
                                      row["volume"], row["amount"]))
                            total_written += 1

                    if (i + 1) % 100 == 0:
                        conn.commit()
                        logger.info(f"ETF历史K线进度: {i+1}/{len(target)}, 累计写入: {total_written}")

                except Exception as e:
                    errors += 1
                    logger.debug(f"ETF {code} K线失败: {e}")

            conn.commit()
            logger.info(f"ETF历史K线采集完成: 写入{total_written}条, 失败{errors}只")
            return total_written

        except Exception as e:
            logger.error(f"ETF历史K线批量采集异常: {e}", exc_info=True)
            return total_written
