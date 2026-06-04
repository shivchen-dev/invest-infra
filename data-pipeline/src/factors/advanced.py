"""
高级因子层 — 补充全部缺失因子

覆盖：
- 反转因子（5日/20日反转）
- 主力资金因子（大单净流入）
- 北向资金因子（沪深港通净买入）
- 龙虎榜因子（上榜次数、净买额）
- 放量因子（5日/20日成交量比、异动）
- 跨市场联动因子（股债联动）
- 板块轮动因子
- 日内形态因子（开盘缺口、盘中突破）
"""

import logging
import time
from datetime import date, timedelta
from typing import Optional

import numpy as np
import psycopg2

from src.config import pg

logger = logging.getLogger(__name__)


# ─── 工具函数 ────────────────────────────────────────────────────────────────


def _parse_pct(val) -> Optional[float]:
    """将 '12.5%' 或 '-3.21%' 转为浮点数"""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace('%', '').replace(' ', '')
    if s in ('', '-', 'nan'):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _clean_num(val):
    """将 pandas NaN/NA/numpy nan 转为 Python None（SQL NULL）"""
    import numpy as np
    import pandas as pd
    if val is None:
        return None
    if isinstance(val, float) and np.isnan(val):
        return None
    if pd.isna(val):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ─── 数据采集 ────────────────────────────────────────────────────────────────


def collect_stock_daily_fund_flow(conn, calc_date=None) -> int:
    """
    采集全市场个股资金流日频快照（东方财富-同花顺），
    替换原来的 stock_fund_flow_big_deal（大单追踪，仅覆盖科创板+沪市主板）。

    新接口 stock_fund_flow_individual(symbol='即时') 返回约 5188 只股票，
    覆盖：创业板(924)、科创板(615)、沪市主板(748+217)、深市主板、北交所(75)。
    """
    import akshare as ak
    from datetime import date

    if calc_date is None:
        calc_date = date.today()

    logger.info("正在采集全市场个股资金流 ...")
    written = 0
    skipped = 0

    def _clean_num(val):
        """'5426.29万' / '3.69亿' → float(元)"""
        if val is None:
            return None
        try:
            if isinstance(val, float) and (val != val or abs(val) == float('inf')):
                return None
        except (TypeError, ValueError):
            pass
        s = str(val).strip().replace('%', '').replace(' ', '')
        if s in ('', '-', 'nan', 'None'):
            return None
        for unit, mult in [('亿', 1e8), ('万', 1e4), ('千', 1e3)]:
            if unit in s:
                try:
                    return float(s.replace(unit, '')) * mult
                except ValueError:
                    return None
        try:
            return float(s)
        except ValueError:
            return None

    def _parse_pct(val):
        if val is None:
            return None
        s = str(val).strip().replace('%', '')
        if s in ('', '-', 'nan'):
            return None
        try:
            return float(s)
        except (ValueError, TypeError):
            return None

    try:
        df = ak.stock_fund_flow_individual(symbol="即时")
        if df is None or df.empty:
            logger.warning("资金流数据为空")
            return 0

        code_map = {}
        with conn.cursor() as cur:
            cur.execute("SELECT code, id FROM companies")
            code_map = {str(r[0]).split('.')[0]: r[1] for r in cur.fetchall()}

        with conn.cursor() as cur:
            for _, row in df.iterrows():
                code_raw = str(row.get("股票代码", "")).strip()
                if code_raw.endswith('.0'):
                    code_raw = code_raw[:-2]
                cid = code_map.get(code_raw)
                if cid is None:
                    skipped += 1
                    continue

                inflow  = _clean_num(row.get("流入资金"))
                outflow = _clean_num(row.get("流出资金"))
                net     = _clean_num(row.get("净额"))
                amount  = _clean_num(row.get("成交额"))
                change_pct = _parse_pct(row.get("涨跌幅"))
                turnover    = _parse_pct(row.get("换手率"))
                close_price = row.get("最新价")

                cur.execute(
                    """
                    INSERT INTO stock_daily_fund_flow
                        (company_id, calc_date,
                         inflow_main, outflow_main, net_inflow_main,
                         amount, close_price, change_pct, turnover_rate, source)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (company_id, calc_date) DO UPDATE SET
                        inflow_main   = EXCLUDED.inflow_main,
                        outflow_main  = EXCLUDED.outflow_main,
                        net_inflow_main = EXCLUDED.net_inflow_main,
                        amount        = EXCLUDED.amount,
                        close_price   = EXCLUDED.close_price,
                        change_pct    = EXCLUDED.change_pct,
                        turnover_rate = EXCLUDED.turnover_rate
                    """,
                    (cid, calc_date,
                     inflow, outflow, net,
                     amount, close_price, change_pct, turnover,
                     "eastmoney-realtime"),
                )
                written += 1

        conn.commit()
        logger.info(f"资金流入库: {written} 条, 跳过(未匹配) {skipped} 条")
    except Exception as e:
        logger.warning(f"资金流采集失败: {e}")
        conn.rollback()

    return written


# ── 兼容旧名（保留避免调用方报错）──────────────────────────────────────────
def collect_fund_flow_big_deal(conn, days: int = 30) -> int:
    """兼容别名：透传到新函数（days 参数保留但不再用于大单历史）"""
    return collect_stock_daily_fund_flow(conn)


def collect_lhb_records(conn, days: int = 30) -> int:
    """采集龙虎榜明细"""
    import akshare as ak

    logger.info("正在采集龙虎榜数据 ...")
    today = date.today()
    written = 0
    try:
        df = ak.stock_lhb_detail_em()
        if df is None or df.empty:
            return 0

        code_map = {}
        with conn.cursor() as cur:
            cur.execute("SELECT code, id FROM companies")
            code_map = {str(r[0]).split('.')[0]: r[1] for r in cur.fetchall()}

        with conn.cursor() as cur:
            for _, row in df.iterrows():
                listing_date = row.get("上榜日")
                if listing_date is None:
                    continue
                if hasattr(listing_date, "date"):
                    listing_date = listing_date.date()

                code_raw = str(row.get("代码", "")).strip()
                code_key = code_raw.split('.')[0]
                cid = code_map.get(code_key)
                if cid is None:
                    continue

                cur.execute(
                    """
                    INSERT INTO lhb_records
                        (company_id, listing_date, close_price, change_pct,
                         net_buy, buy_amount, sell_amount, turnover_rate,
                         reason, source)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (company_id, listing_date) DO UPDATE SET
                        net_buy=EXCLUDED.net_buy,
                        buy_amount=EXCLUDED.buy_amount,
                        sell_amount=EXCLUDED.sell_amount
                    """,
                    (cid, listing_date,
                     row.get("收盘价"), _parse_pct(row.get("涨跌幅")),
                     row.get("龙虎榜净买额"), row.get("龙虎榜买入额"),
                     row.get("龙虎榜卖出额"), row.get("换手率"),
                     row.get("上榜原因"), "akshare"),
                )
                written += 1
        conn.commit()
        logger.info(f"龙虎榜入库: {written} 条")
    except Exception as e:
        logger.warning(f"龙虎榜采集失败: {e}")
        conn.rollback()
    return written


def collect_north_flow(conn) -> int:
    """采集北向资金历史"""
    import akshare as ak

    logger.info("正在采集北向资金数据 ...")
    written = 0
    try:
        df = ak.stock_hsgt_hist_em(symbol="北向资金")
        if df is None or df.empty:
            return 0

        with conn.cursor() as cur:
            for _, row in df.iterrows():
                calc_date = row.get("日期")
                if calc_date is None:
                    continue
                if hasattr(calc_date, "date"):
                    calc_date = calc_date.date()

                cur.execute(
                    """
                    INSERT INTO north_flow_hist
                        (calc_date, daily_net_buy, buy_amount, sell_amount,
                         cum_net_buy, hold_market_val, hs300, source)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (calc_date) DO UPDATE SET
                        daily_net_buy=EXCLUDED.daily_net_buy,
                        buy_amount=EXCLUDED.buy_amount,
                        sell_amount=EXCLUDED.sell_amount
                    """,
                    (calc_date,
                     _clean_num(row.get("当日成交净买额")),
                     _clean_num(row.get("买入成交额")),
                     _clean_num(row.get("卖出成交额")),
                     _clean_num(row.get("历史累计净买额")),
                     _clean_num(row.get("持股市值")),
                     _clean_num(row.get("沪深300")),
                     "akshare"),
                )
                written += 1
        conn.commit()
        logger.info(f"北向资金入库: {written} 条")
    except Exception as e:
        logger.warning(f"北向资金采集失败: {e}")
        conn.rollback()
    return written


# ─── 因子计算 ────────────────────────────────────────────────────────────────


def calc_reversal_factor(conn, calc_date: date) -> list[dict]:
    """反转因子：5日/20日低点以来反弹幅度"""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH recent_prices AS (
                SELECT d.company_id,
                       MAX(d.close_price) FILTER(WHERE d.trade_date = %s) AS close_now,
                       MAX(d.low_price) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS min_low_5d,
                       MAX(d.low_price) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS min_low_20d
                FROM daily_quotes d
                WHERE d.trade_date BETWEEN %s AND %s
                GROUP BY d.company_id
            )
            SELECT company_id,
                   CASE WHEN min_low_5d > 0 AND close_now > 0
                        THEN (close_now / min_low_5d - 1) * 100 ELSE NULL END AS reversal_5d,
                   CASE WHEN min_low_20d > 0 AND close_now > 0
                        THEN (close_now / min_low_20d - 1) * 100 ELSE NULL END AS reversal_20d
            FROM recent_prices
            WHERE close_now IS NOT NULL
            """,
            (calc_date,
             calc_date - timedelta(days=5), calc_date,
             calc_date - timedelta(days=20), calc_date,
             calc_date - timedelta(days=25), calc_date)
        )
        return [{"company_id": r[0], "reversal_5d": r[1], "reversal_20d": r[2]}
                for r in cur.fetchall()]


def calc_main_fund_flow_factor(conn, calc_date: date) -> list[dict]:
    """
    主力资金因子：近5日主力净流入（从 stock_daily_fund_flow 计算）。
    已切换到全市场数据源，覆盖所有板块。
    """
    start = calc_date - timedelta(days=5)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT company_id,
                   SUM(net_inflow_main) AS net_inflow_5d,
                   SUM(amount) AS total_amount_5d
            FROM stock_daily_fund_flow
            WHERE calc_date BETWEEN %s AND %s
            GROUP BY company_id
            HAVING SUM(net_inflow_main) IS NOT NULL
            """,
            (start, calc_date),
        )
        results = []
        for r in cur.fetchall():
            net = r[1] or 0
            total = r[2] or 1
            results.append({
                "company_id": r[0],
                "main_net_flow_5d": net,
                "main_net_flow_ratio_5d": net / total if total != 0 else None,
            })
        return results


def calc_lhb_factor(conn, calc_date: date, lookback: int = 20) -> list[dict]:
    """龙虎榜因子：上榜次数、累计净买额"""
    start = calc_date - timedelta(days=lookback)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT company_id,
                   COUNT(*) AS lhb_count,
                   SUM(net_buy) AS total_net_buy
            FROM lhb_records
            WHERE listing_date BETWEEN %s AND %s
            GROUP BY company_id
            """,
            (start, calc_date),
        )
        return [{"company_id": r[0], "lhb_count": r[1], "lhb_total_net_buy": r[2]}
                for r in cur.fetchall()]


def calc_volume_surge_factor(conn, calc_date: date) -> list[dict]:
    """放量因子：5日量比、成交量异动、波动系数"""
    end_5 = calc_date - timedelta(days=1)
    start_20 = calc_date - timedelta(days=25)

    with conn.cursor() as cur:
        cur.execute(
            """
            WITH vol_stats AS (
                SELECT d.company_id,
                       AVG(d.volume) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS avg_vol_5d,
                       AVG(d.volume) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS avg_vol_20d,
                       STDDEV(d.volume) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS std_vol_20d,
                       MIN(d.volume) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS min_vol_5d,
                       MAX(d.volume) FILTER(WHERE d.trade_date = %s) AS vol_today
                FROM daily_quotes d
                WHERE d.trade_date BETWEEN %s AND %s
                GROUP BY d.company_id
            )
            SELECT company_id,
                   CASE WHEN avg_vol_20d > 0 THEN avg_vol_5d / avg_vol_20d ELSE NULL END AS volume_ratio_5d,
                   CASE WHEN min_vol_5d > 0 AND vol_today > 0 THEN vol_today / min_vol_5d ELSE NULL END AS volume_surge,
                   CASE WHEN avg_vol_20d > 0 AND std_vol_20d IS NOT NULL
                        THEN std_vol_20d / avg_vol_20d ELSE NULL END AS volume_cv
            FROM vol_stats
            WHERE avg_vol_5d IS NOT NULL
            """,
            (end_5 - timedelta(days=4), end_5,
             start_20, end_5,
             start_20, end_5,
             end_5 - timedelta(days=4), end_5,
             calc_date,
             start_20, calc_date)
        )
        return [{"company_id": r[0],
                 "volume_ratio_5d": r[1],
                 "volume_surge": r[2],
                 "volume_cv": r[3]}
                for r in cur.fetchall()]


def calc_cross_market_factor(conn, calc_date: date) -> dict:
    """跨市场联动：上证/深证 vs 沪深300 相关性"""
    start = calc_date - timedelta(days=25)

    with conn.cursor() as cur:
        # 找最近有数据的日期（指数数据可能比calc_date少几天）
        cur.execute("""
            SELECT MAX(eq.trade_date)
            FROM index_quotes eq
            JOIN indices idx ON idx.id = eq.index_id
            WHERE idx.code = '000001'
        """)
        latest_index_date = cur.fetchone()[0] or calc_date

        cur.execute(
            """
            WITH daily_pct AS (
                SELECT idx.code, eq.trade_date,
                       eq.close_point / NULLIF(LAG(eq.close_point) OVER (
                           PARTITION BY idx.code ORDER BY eq.trade_date), 0) - 1 AS ret
                FROM indices idx
                JOIN index_quotes eq ON idx.id = eq.index_id
                WHERE idx.code IN ('000001','000300','399001')
                  AND eq.trade_date BETWEEN %s AND %s
            ),
            pivoted AS (
                SELECT trade_date,
                       MAX(ret) FILTER(WHERE code='000001') AS sh_ret,
                       MAX(ret) FILTER(WHERE code='000300') AS hs300_ret,
                       MAX(ret) FILTER(WHERE code='399001') AS sz_ret
                FROM daily_pct
                GROUP BY trade_date
            )
            SELECT CORR(sh_ret, hs300_ret), CORR(sz_ret, hs300_ret)
            FROM pivoted
            WHERE sh_ret IS NOT NULL AND hs300_ret IS NOT NULL AND sz_ret IS NOT NULL
            LIMIT 1
            """,
            (start, latest_index_date),
        )
        r = cur.fetchone()
        return {"corr_sh300_hs300": r[0] if r else None,
                "corr_sz300_hs300": r[1] if r else None}


def calc_sector_rotation_factor(conn, calc_date: date) -> list[dict]:
    """板块轮动因子：行业动量差异"""
    start = calc_date - timedelta(days=20)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.company_id,
                   AVG(d.change_pct) FILTER(WHERE d.change_pct > 0) AS avg_up_pct,
                   AVG(d.change_pct) FILTER(WHERE d.change_pct < 0) AS avg_down_pct,
                   COUNT(*) FILTER(WHERE d.change_pct > 0) AS up_days,
                   COUNT(*) FILTER(WHERE d.change_pct < 0) AS down_days
            FROM daily_quotes d
            JOIN companies c ON d.company_id = c.id
            WHERE d.trade_date BETWEEN %s AND %s
              AND c.industry IS NOT NULL
            GROUP BY d.company_id
            """,
            (start, calc_date),
        )
        results = []
        for r in cur.fetchall():
            up, down = r[3] or 0, r[4] or 0
            total = up + down
            if total > 0:
                score = (up / total) * ((r[1] or 0) - abs(r[2] or 0))
            else:
                score = None
            results.append({"company_id": r[0], "industry_momentum": score})
        return results


def calc_intraday_pattern_factor(conn, calc_date: date) -> list[dict]:
    """日内形态因子：开盘跳空、盘中突破"""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH intraday AS (
                SELECT d.company_id,
                       MAX(d.open_price) FILTER(WHERE d.trade_date = %s) AS open_today,
                       MAX(d.close_price) FILTER(WHERE d.trade_date = %s - INTERVAL '1 day') AS close_yesterday,
                       MAX(d.high_price) FILTER(WHERE d.trade_date = %s) AS high_today,
                       MAX(d.close_price) FILTER(WHERE d.trade_date = %s) AS close_today,
                       MAX(d.high_price) FILTER(WHERE d.trade_date BETWEEN %s AND %s)
                          AS high_20d
                FROM daily_quotes d
                WHERE d.trade_date BETWEEN %s AND %s
                GROUP BY d.company_id
            )
            SELECT company_id,
                   CASE WHEN close_yesterday > 0 AND open_today > 0
                        THEN (open_today - close_yesterday) / close_yesterday * 100
                        ELSE NULL END AS gap_open_pct,
                   CASE WHEN high_20d > 0 AND high_today > 0
                        THEN (high_today - high_20d) / high_20d * 100
                        ELSE NULL END AS intraday_break_pct
            FROM intraday
            WHERE open_today IS NOT NULL AND close_yesterday IS NOT NULL
            """,
            (calc_date, calc_date, calc_date, calc_date,
             calc_date - timedelta(days=20), calc_date,
             calc_date - timedelta(days=25), calc_date)
        )
        return [{"company_id": r[0],
                 "gap_open_pct": r[1],
                 "intraday_break_pct": r[2]}
                for r in cur.fetchall()]


def save_all_factors(conn, calc_date: date,
                     reversal: list, main_fund: list, lhb: list,
                     volume: list, sector: list, intraday: list,
                     cross: dict) -> int:
    """将所有因子值写入 factor_values 表"""
    written = 0

    factor_key_to_id = {}
    with conn.cursor() as cur:
        cur.execute("SELECT id, factor_key FROM factor_definitions")
        factor_key_to_id = {r[1]: r[0] for r in cur.fetchall()}

    def upsert_fv(company_id, factor_key, value):
        nonlocal written
        if company_id is None or factor_key not in factor_key_to_id:
            return
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return
        fid = factor_key_to_id[factor_key]
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO factor_values (company_id, factor_id, calc_date, value)
                    VALUES (%s,%s,%s,%s)
                    ON CONFLICT (company_id, factor_id, calc_date) DO UPDATE SET value = EXCLUDED.value
                    """,
                    (company_id, fid, calc_date, float(value)),
                )
                written += 1
        except Exception as e:
            logger.debug(f"因子写入失败 {factor_key}: {e}")

    for r in reversal:
        upsert_fv(r["company_id"], "reversal_5d", r.get("reversal_5d"))
        upsert_fv(r["company_id"], "reversal_20d", r.get("reversal_20d"))

    for r in main_fund:
        upsert_fv(r["company_id"], "main_net_flow_5d", r.get("main_net_flow_5d"))
        upsert_fv(r["company_id"], "main_net_flow_ratio_5d", r.get("main_net_flow_ratio_5d"))

    for r in lhb:
        upsert_fv(r["company_id"], "lhb_count", r.get("lhb_count"))
        upsert_fv(r["company_id"], "lhb_total_net_buy", r.get("lhb_total_net_buy"))

    for r in volume:
        upsert_fv(r["company_id"], "volume_ratio_5d", r.get("volume_ratio_5d"))
        upsert_fv(r["company_id"], "volume_surge", r.get("volume_surge"))
        upsert_fv(r["company_id"], "volume_cv", r.get("volume_cv"))

    for r in sector:
        upsert_fv(r["company_id"], "industry_momentum", r.get("industry_momentum"))

    for r in intraday:
        upsert_fv(r["company_id"], "gap_open_pct", r.get("gap_open_pct"))
        upsert_fv(r["company_id"], "intraday_break_pct", r.get("intraday_break_pct"))

    conn.commit()
    return written


# ─── 因子定义 ────────────────────────────────────────────────────────────────

ADVANCED_FACTOR_DEFINITIONS = [
    {"factor_key": "reversal_5d",  "name": "5日反转因子",     "category": "technical", "sub_category": "reversal"},
    {"factor_key": "reversal_20d", "name": "20日反转因子",    "category": "technical", "sub_category": "reversal"},
    {"factor_key": "main_net_flow_5d", "name": "主力5日净流入",  "category": "money_flow", "sub_category": "main"},
    {"factor_key": "main_net_flow_ratio_5d", "name": "主力净流入占比","category": "money_flow", "sub_category": "main"},
    {"factor_key": "lhb_count", "name": "龙虎榜上榜次数",     "category": "alternative", "sub_category": "lhb"},
    {"factor_key": "lhb_total_net_buy", "name": "龙虎榜累计净买额","category": "alternative", "sub_category": "lhb"},
    {"factor_key": "volume_ratio_5d", "name": "5日量比",       "category": "technical", "sub_category": "volume"},
    {"factor_key": "volume_surge", "name": "成交量异动",      "category": "technical", "sub_category": "volume"},
    {"factor_key": "volume_cv", "name": "成交量波动系数",     "category": "technical", "sub_category": "volume"},
    {"factor_key": "industry_momentum", "name": "行业动量",    "category": "macro", "sub_category": "sector"},
    {"factor_key": "gap_open_pct", "name": "开盘跳空",         "category": "technical", "sub_category": "intraday_pattern"},
    {"factor_key": "intraday_break_pct", "name": "盘中突破",    "category": "technical", "sub_category": "intraday_pattern"},
    {"factor_key": "corr_sh300_hs300", "name": "上证-沪深300相关性","category": "cross_market", "sub_category": "index"},
    {"factor_key": "corr_sz300_hs300", "name": "深证-沪深300相关性","category": "cross_market", "sub_category": "index"},
]


def register_advanced_factors(conn) -> int:
    """注册高级因子定义"""
    written = 0
    with conn.cursor() as cur:
        for f in ADVANCED_FACTOR_DEFINITIONS:
            cur.execute(
                """
                INSERT INTO factor_definitions
                    (factor_key, name, category, sub_category, formula_desc, data_source, frequency)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (factor_key) DO UPDATE SET
                    name = EXCLUDED.name, category = EXCLUDED.category,
                    sub_category = EXCLUDED.sub_category,
                    version = factor_definitions.version + 1
                """,
                (f["factor_key"], f["name"], f["category"], f["sub_category"],
                 f.get("formula_desc", ""), "daily_quotes", "daily"),
            )
            written += 1
        conn.commit()
    logger.info(f"高级因子注册完成: {written} 个")
    return written


# ─── 主入口 ──────────────────────────────────────────────────────────────────


def run_advanced_factor_pipeline(days: int = 30) -> dict:
    """
    运行全部高级因子计算流程：
    1. 数据采集（大单/龙虎榜/北向）
    2. 因子注册
    3. 各因子计算
    4. 写入 factor_values
    """
    result = {"steps": {}, "records": 0}
    today = date.today()

    conn = psycopg2.connect(pg.uri)
    try:
        t0 = time.time()
        collect_fund_flow_big_deal(conn, days=days)
        result["steps"]["collect_big_deal"] = {"elapsed_s": round(time.time() - t0, 2)}

        t0 = time.time()
        collect_lhb_records(conn, days=days)
        result["steps"]["collect_lhb"] = {"elapsed_s": round(time.time() - t0, 2)}

        t0 = time.time()
        collect_north_flow(conn)
        result["steps"]["collect_north"] = {"elapsed_s": round(time.time() - t0, 2)}

        t0 = time.time()
        register_advanced_factors(conn)
        result["steps"]["register"] = {"elapsed_s": round(time.time() - t0, 2)}

        calc_start = time.time()
        reversal = calc_reversal_factor(conn, today)
        result["steps"]["reversal"] = {"companies": len(reversal)}

        main_fund = calc_main_fund_flow_factor(conn, today)
        result["steps"]["main_fund"] = {"companies": len(main_fund)}

        lhb = calc_lhb_factor(conn, today)
        result["steps"]["lhb"] = {"companies": len(lhb)}

        volume = calc_volume_surge_factor(conn, today)
        result["steps"]["volume"] = {"companies": len(volume)}

        sector = calc_sector_rotation_factor(conn, today)
        result["steps"]["sector"] = {"companies": len(sector)}

        intraday = calc_intraday_pattern_factor(conn, today)
        result["steps"]["intraday"] = {"companies": len(intraday)}

        cross = calc_cross_market_factor(conn, today)
        result["steps"]["cross"] = cross

        result["steps"]["calc"] = {"elapsed_s": round(time.time() - calc_start, 2)}

        t0 = time.time()
        written = save_all_factors(conn, today, reversal, main_fund, lhb,
                                   volume, sector, intraday, cross)
        result["steps"]["save"] = {"records": written, "elapsed_s": round(time.time() - t0, 2)}
        result["records"] = written

        return result
    finally:
        conn.close()
