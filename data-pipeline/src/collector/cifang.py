"""次方量化 ETF 数据采集器

API 文档: https://www.cifangquant.com/docs/data-api.html
认证: x-api-key 请求头

主要接口:
  - fund/list       基金列表（全量 ETF/LOF/货基）
  - fund/spot       实时行情（延迟约2分钟）
  - fund/hist_em    历史日K（支持 qfq/hfq 复权）
  - fund/exchange_rank 场内基金收益排行
"""

import logging
from datetime import date, datetime, timedelta
from typing import Optional

import requests

from src.collector.retry import with_retry
from src.config import cifang

logger = logging.getLogger(__name__)

# 请求超时（秒）
TIMEOUT = 15


def _get(path: str, params: Optional[dict] = None) -> dict:
    """统一 GET 请求封装"""
    url = f"{cifang.base_url}{path}"
    try:
        resp = requests.get(url, params=params or {}, headers=cifang.headers, timeout=TIMEOUT)
        resp.raise_for_status()
        d = resp.json()
        if d.get("code") != 0:
            logger.warning("次方量化 API 异常: code=%s message=%s path=%s", d.get("code"), d.get("message"), path)
            return {}
        return d.get("data") or {}
    except requests.exceptions.Timeout:
        logger.warning("次方量化请求超时: %s", path)
        return {}
    except Exception as e:
        logger.warning("次方量化请求失败: %s -> %s", path, e)
        return {}


# ─── 1. 基金列表 ────────────────────────────────────────────────────────────

@with_retry()
def fetch_fund_list() -> list[dict]:
    """
    获取全量基金列表。
    返回: [{fund_code, fund_name, fund_type, fund_market, listing_date, ...}, ...]
    """
    data = _get("/fund/list")
    if not data:
        return []
    logger.info("次方量化基金列表: %d 只", len(data))
    return data


# ─── 2. 实时行情 ─────────────────────────────────────────────────────────────

@with_retry()
def fetch_fund_spot(symbols: Optional[list[str]] = None) -> dict[str, dict]:
    """
    获取场内基金实时行情。

    Args:
        symbols: 基金代码列表，如 ["510300", "518880"]。
                  省略则返回全部（约1674只，响应较大）。

    Returns:
        {fund_code: {fund_code, fund_name, price, change, change_pct, volume,
                     amount, open, high, low, close_yesterday, iopv, premium_rate,
                     fund_type, fund_market, trade_date, update_time}, ...}
    """
    params = {}
    if symbols:
        params["symbol"] = ",".join(symbols)
    data = _get("/fund/spot", params)
    if not data:
        return {}
    logger.info("次方量化实时行情: %d 只", len(data))
    return data


# ─── 3. 历史日K ─────────────────────────────────────────────────────────────

@with_retry()
def fetch_fund_hist(
    symbol: str,
    start_date: date,
    end_date: date,
    adjust: str = "qfq",
) -> list[dict]:
    """
    获取指定基金的历史日K线。

    Args:
        symbol:     基金代码，如 "510300"
        start_date: 开始日期
        end_date:   结束日期
        adjust:     复权方式，qfq=前复权 / hfq=后复权 / 空=不复权

    Returns:
        [{date, open, high, low, close, volume, amount, change, change_pct}, ...]
        date 格式: "2026-05-29"
    """
    params = {
        "symbol":    symbol,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date":   end_date.strftime("%Y-%m-%d"),
        "adjust":    adjust,
    }
    data = _get("/fund/hist_em", params)
    # 返回格式: {fund_code: [[date, open, close, high, low, change_pct, amount], ...]}
    if not data or symbol not in data:
        return []
    raw_list = data[symbol]
    # 转为 dict 列表供 hist_to_etf_quote 使用
    FIELD_NAMES = ["date", "open", "close", "high", "low", "change_pct", "amount"]
    records = [dict(zip(FIELD_NAMES, rec)) for rec in raw_list]
    logger.debug("次方量化历史K线 %s: %d 条 (%s~%s)", symbol, len(records), start_date, end_date)
    return records


# ─── 4. 场内基金收益排行 ────────────────────────────────────────────────────

@with_retry()
def fetch_exchange_rank(sort_by: str = "jnzf", sort_order: str = "desc", limit: int = 100) -> list[dict]:
    """
    获取场内基金收益排行。

    Args:
        sort_by:    排序字段
                      jnzf  = 今年来收益率
                      yzdf  = 近一年收益率
                      yyzf  = 近一月收益率
                      bjyzf = 近一周收益率
                      bnzf  = 本年收益率
                      ljzf  = 累计收益率（成立以来）
        sort_order: asc / desc
        limit:      返回条数上限（最大200）

    Returns:
        [{rank, fund_code, fund_name, fund_type, fund_market, nav, unit_nav,
          accumulated_nav, jnzf, yzdf, yyzf, bjyzf, bnzf, ljzf, ...}, ...]
    """
    params = {"sort_by": sort_by, "sort_order": sort_order, "limit": limit}
    data = _get("/fund/exchange_rank", params)
    if not data:
        return []
    logger.info("次方量化基金排行: %d 只 (%s %s)", len(data), sort_by, sort_order)
    return data


# ─── 字段映射工具 ───────────────────────────────────────────────────────────

def _normalize_fund_record(rec: dict) -> dict:
    """
    将次方量化各接口返回的基金记录统一字段名为 code/name/type/market/listing_date。
    同时处理两种格式：fund_code (list接口) 和 code (spot接口)。
    """
    return {
        "code":          rec.get("code") or rec.get("fund_code", ""),
        "name":          rec.get("name") or rec.get("fund_name", ""),
        "type":          rec.get("type") or rec.get("fund_type", ""),
        "market":        rec.get("market") or rec.get("fund_market", ""),
        "listing_date":  rec.get("listing_date") or rec.get("establish_date", ""),
    }


def spot_to_etf_quote(record: dict, trade_date: date) -> dict:
    """
    将次方量化实时行情记录映射为 etf_quotes 写入格式。

    目标表: etf_quotes(etf_id, trade_date, open_price, high_price, low_price,
                       close_price, volume, amount, change_pct, source)
    """
    change_raw = record.get("change") or record.get("change_pct", "")
    # change 可能是 "1.22%" 或 1.22
    if isinstance(change_raw, str):
        change_pct = float(change_raw.rstrip("%")) if change_raw else None
    else:
        change_pct = change_raw

    return {
        "trade_date":    trade_date,
        "open_price":    record.get("open"),
        "high_price":    record.get("high"),
        "low_price":     record.get("low"),
        "close_price":   record.get("price"),
        "volume":        record.get("volume"),
        "amount":        record.get("amount"),
        "change_pct":    change_pct,
        "pre_close":     record.get("close_yesterday"),
        "source":        "cifang",
    }


def hist_to_etf_quote(record: dict, trade_date: date) -> dict:
    """
    将次方量化历史K线记录映射为 etf_quotes 写入格式。
    """
    return {
        "trade_date":    trade_date,
        "open_price":    record.get("open"),
        "high_price":    record.get("high"),
        "low_price":     record.get("low"),
        "close_price":   record.get("close"),
        "volume":        record.get("volume"),
        "amount":        record.get("amount"),
        "change_pct":    record.get("change_pct"),
        "source":        "cifang",
    }


def fund_list_to_etf(record: dict) -> dict:
    """
    将次方量化基金列表记录映射为 etfs 写入格式。

    目标表: etfs(code, name, category, exchange_code, listing_date, source)
    """
    rec = _normalize_fund_record(record)
    fund_type = rec["type"] or ""
    # 简单分类映射
    if "指数" in fund_type or "ETF" in fund_type:
        category = "stock"
    elif "货币" in fund_type:
        category = "money_market"
    elif "债券" in fund_type or "纯债" in fund_type:
        category = "bond"
    elif "混合" in fund_type:
        category = "hybrid"
    elif "股票" in fund_type:
        category = "stock"
    else:
        category = "other"

    return {
        "code":          rec["code"],
        "name":          rec["name"],
        "category":      category,
        "exchange_code": _market_to_exchange(rec["market"]),
        "listing_date":  rec["listing_date"],
        "source":        "cifang",
    }


def _market_to_exchange(fund_market: str) -> str:
    """fund_market (SH/SZ) -> exchange_code (XSHG/XSHE)"""
    mapping = {"SH": "XSHG", "SZ": "XSHE"}
    return mapping.get(fund_market, fund_market or "")


# ─── 数据库写入 ─────────────────────────────────────────────────────────────

def upsert_etfs_from_cifang(records: list[dict]) -> dict:
    """
    将次方量化基金列表 upsert 到 etfs 表。
    仅处理 ETF 类型（category != "other"），兼容已有记录（不覆盖 name）。
    """
    if not records:
        return {"inserted": 0, "updated": 0}

    with pg.get_conn() as conn:
        try:
            inserted = updated = 0
            with conn.cursor() as cur:
                for r in records:
                    cat = r.get("category", "other")
                    if cat == "other":
                        continue
                    cur.execute(
                        """
                        INSERT INTO etfs (code, name, category, exchange_code, list_date)
                        VALUES (%(code)s, %(name)s, %(category)s, %(exchange_code)s, %(listing_date)s)
                        ON CONFLICT (code) DO UPDATE SET
                            name         = COALESCE(EXCLUDED.name, etfs.name),
                            category     = COALESCE(EXCLUDED.category, etfs.category),
                            exchange_code = COALESCE(EXCLUDED.exchange_code, etfs.exchange_code),
                            list_date    = COALESCE(EXCLUDED.list_date, etfs.list_date),
                            updated_at   = now()
                        """,
                        r,
                    )
                    if cur.rowcount == 1:
                        inserted += 1
                    else:
                        updated += 1
            conn.commit()
            logger.info("次方量化 ETF 列表同步: 新增 %d, 更新 %d", inserted, updated)
            return {"inserted": inserted, "updated": updated}
        except Exception as e:
            logger.error(f"次方量化 ETF 列表同步失败: {e}", exc_info=True)
            conn.rollback()
            return {"inserted": 0, "updated": 0}


def write_spot_to_etf_quotes(spot_data: dict[str, dict], trade_date: date) -> int:
    """
    将次方量化实时行情批量写入 etf_quotes 表（upsert）。

    spot_data: fetch_fund_spot() 返回的字典
    trade_date: 行情日期

    返回: 写入记录数
    """
    if not spot_data:
        return 0

    with pg.get_conn() as conn:
        try:
            written = 0
            with conn.cursor() as cur:
                for fund_code, record in spot_data.items():
                    # 查找 etf_id
                    cur.execute("SELECT id FROM etfs WHERE code = %s", (fund_code,))
                    row = cur.fetchone()
                    if not row:
                        logger.debug("次方量化行情写入跳过（未收录）: %s", fund_code)
                        continue
                    etf_id = row[0]

                    # 写入行情
                    cur.execute(
                        """
                        INSERT INTO etf_quotes
                            (etf_id, trade_date, open_price, high_price, low_price,
                             close_price, pre_close, volume, amount, change_pct, source)
                        VALUES (%(etf_id)s, %(trade_date)s, %(open_price)s, %(high_price)s,
                                %(low_price)s, %(close_price)s, %(pre_close)s,
                                %(volume)s, %(amount)s, %(change_pct)s, %(source)s)
                        ON CONFLICT (etf_id, trade_date) DO UPDATE SET
                            open_price  = EXCLUDED.open_price,
                            high_price  = EXCLUDED.high_price,
                            low_price   = EXCLUDED.low_price,
                            close_price = EXCLUDED.close_price,
                            pre_close   = EXCLUDED.pre_close,
                            volume      = EXCLUDED.volume,
                            amount      = EXCLUDED.amount,
                            change_pct  = EXCLUDED.change_pct,
                            source      = EXCLUDED.source
                        """,
                        {
                            "etf_id":      etf_id,
                            "trade_date":  trade_date,
                            "open_price":  record.get("open"),
                            "high_price":  record.get("high"),
                            "low_price":   record.get("low"),
                            "close_price": record.get("price"),
                            "pre_close":  record.get("close_yesterday"),
                            "volume":     record.get("volume"),
                            "amount":     record.get("amount"),
                            "change_pct": record.get("change_pct"),
                            "source":     "cifang",
                        },
                    )
                    written += 1
            conn.commit()
            logger.info("次方量化实时行情写入: %d 只 -> etf_quotes", written)
            return written
        except Exception as e:
            logger.error(f"次方量化实时行情写入失败: {e}", exc_info=True)
            conn.rollback()
            return 0


def backfill_hist(etf_code: str, start_date: date, end_date: date, adjust: str = "qfq") -> int:
    """
    补充单只 ETF 历史K线（从次方量化），写入 etf_quotes。
    用于填补 akshare 缺失的历史段。
    """
    records = fetch_fund_hist(etf_code, start_date, end_date, adjust)
    if not records:
        return 0

    with pg.get_conn() as conn:
        try:
            written = 0
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM etfs WHERE code = %s", (etf_code,))
                row = cur.fetchone()
                if not row:
                    logger.debug("backfill 跳过（未收录）: %s", etf_code)
                    return 0
                etf_id = row[0]

                for rec in records:
                    trade_date = datetime.strptime(rec["date"], "%Y-%m-%d").date()
                    cur.execute(
                        """
                        INSERT INTO etf_quotes
                            (etf_id, trade_date, open_price, high_price, low_price,
                             close_price, volume, amount, change_pct, source)
                        VALUES (%(etf_id)s, %(trade_date)s, %(open_price)s,
                                %(high_price)s, %(low_price)s, %(close_price)s,
                                %(volume)s, %(amount)s, %(change_pct)s, %(source)s)
                        ON CONFLICT (etf_id, trade_date) DO UPDATE SET
                            open_price  = EXCLUDED.open_price,
                            high_price  = EXCLUDED.high_price,
                            low_price   = EXCLUDED.low_price,
                            close_price = EXCLUDED.close_price,
                            volume      = EXCLUDED.volume,
                            amount      = EXCLUDED.amount,
                            change_pct  = EXCLUDED.change_pct,
                            source      = EXCLUDED.source
                        """,
                        {
                            "etf_id":     etf_id,
                            "trade_date": trade_date,
                            "open_price": rec.get("open"),
                            "high_price": rec.get("high"),
                            "low_price":  rec.get("low"),
                            "close_price": rec.get("close"),
                            "volume":     rec.get("volume"),
                            "amount":     rec.get("amount"),
                            "change_pct": rec.get("change_pct"),
                            "source":     "cifang",
                        },
                    )
                    written += 1
            conn.commit()
            logger.info("次方量化历史K线 backfill %s: %d 条写入", etf_code, written)
            return written
        except Exception as e:
            logger.error(f"次方量化历史K线 backfill {etf_code} 失败: {e}", exc_info=True)
            conn.rollback()
            return 0