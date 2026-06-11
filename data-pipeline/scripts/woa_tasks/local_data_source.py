"""
本地数据库查询 — 替代 RssCast API
Morning Briefing 数据来源：invest-infra PostgreSQL

数据现状（2026-06-02 早08:00）：
  - index_quotes:   最新 2026-05-29（缺5天，沪深300 无数据）
  - daily_quotes:   最新 2026-06-01 ✅
  - news_articles:  昨日 79条 ✅
  - etf_quotes:     昨日 1486只 ✅
  - fund_flow_big_deal: 有数据，需确认日期
"""

import psycopg2
from src.config import pg
from datetime import date, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)

def get_db():
    return psycopg2.connect(host=pg.host, port=pg.port, dbname=pg.db,
                            user=pg.user, password=pg.password)


# ─── 指数 K 线 ───────────────────────────────────────────────────

def query_index_kline(index_code_or_id, start_date: str, end_date: str):
    """
    指数日线（支持名称或数字 ID）

    index_code 映射：
      '000300' / '沪深300' / 3  → 沪深300
      '000001' / '上证指数' / 1 → 上证指数
      '399001' / '深证成指' / 2 → 深证成指
    """
    index_map = {
        '000300': 3, '沪深300': 3, 'hs300': 3,
        '000001': 1, '上证指数': 1,
        '399001': 2, '深证成指': 2,
        '000016': 4, '上证50': 4,
        '000688': 5, '科创50': 5,
        '399006': 6, '创业板指': 6,
        '000905': 7, '中证500': 7,
        '000852': 8, '中证1000': 8,
    }
    numeric_id = index_map.get(index_code_or_id)
    if numeric_id is None:
        # 尝试直接用字符串
        try:
            numeric_id = int(index_code_or_id)
        except (ValueError, TypeError):
            numeric_id = 1  # default 上证

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT i.name, q.trade_date, q.open_point, q.high_point, q.low_point,
               q.close_point, q.volume, q.amount, q.change_pct, q.amplitude
        FROM index_quotes q
        JOIN indices i ON q.index_id = i.id
        WHERE q.index_id = %s AND q.trade_date BETWEEN %s AND %s
        ORDER BY q.trade_date ASC
    """, (numeric_id, start_date, end_date))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return []
    cols = ['name','trade_date','open','high','low','close','volume','amount','change_pct','amplitude']
    return [dict(zip(cols, r)) for r in rows]


# ─── 股票 K 线 ───────────────────────────────────────────────────

def query_stock_kline(codes, start_date: str, end_date: str):
    """
    股票日线
    codes: ['600519.SH', '601398.SH', '000001.SZ', '000002.SZ', '600036.SH']
    （companies.code 带市场后缀）
    """
    if not codes:
        return []

    conn = get_db()
    cur = conn.cursor()
    placeholders = ','.join(['%s'] * len(codes))
    cur.execute(f"""
        SELECT c.code, c.name, d.trade_date, d.open_price, d.high_price, d.low_price,
               d.close_price, d.volume, d.amount, d.change_pct, d.turnover_rate
        FROM daily_quotes d
        JOIN companies c ON d.company_id = c.id
        WHERE c.code IN ({placeholders})
          AND d.trade_date BETWEEN %s AND %s
        ORDER BY c.code, d.trade_date ASC
    """, codes + [start_date, end_date])
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return []
    cols = ['code','name','trade_date','open','high','low','close','volume','amount','change_pct','turnover_rate']
    return [dict(zip(cols, r)) for r in rows]


# ─── 新闻舆情 ───────────────────────────────────────────────────

def query_news(trade_date: str, limit: int = 20):
    """
    指定交易日的新闻舆情（降序，最新在前）
    trade_date: 'YYYY-MM-DD'
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT title, content_summary, source_name, published_at,
               sentiment_label, sentiment_score
        FROM news_articles
        WHERE DATE(published_at) = %s
        ORDER BY published_at DESC
        LIMIT %s
    """, (trade_date, limit))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return []
    cols = ['title', 'summary', 'source', 'published_at', 'sentiment', 'score']
    return [dict(zip(cols, r)) for r in rows]


# ─── ETF 行情 ────────────────────────────────────────────────────

def query_etf_quotes(trade_date: str, limit: int = 50):
    """指定交易日 ETF 行情（成交额排序）"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT e.code, e.name, q.close_price, q.change_pct,
               q.turnover_rate, q.iopv, q.premium_rate,
               q.volume, q.amount
        FROM etf_quotes q
        JOIN etfs e ON q.etf_id = e.id
        WHERE q.trade_date = %s
        ORDER BY q.amount DESC
        LIMIT %s
    """, (trade_date, limit))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return []
    cols = ['code','name','close','change_pct','turnover_rate','iopv','premium_rate','volume','amount']
    return [dict(zip(cols, r)) for r in rows]


# ─── 南向资金（Eastmoney，替代北向）──────────────────────────────────

def query_south_flow(trade_date: str):
    """
    南向资金（港股通沪+深+合计），写入 south_flow_hist。
    北向资金停更后，以此作为北向资金的替代信号。
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT calc_date, hsgt_type, daily_net_buy, buy_amount, sell_amount, cum_net_buy
        FROM south_flow_hist
        WHERE calc_date = %s
        ORDER BY hsgt_type
    """, (trade_date,))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return []
    cols = ['date','type','net_buy','buy','sell','cum_net']
    return [dict(zip(cols, r)) for r in rows]


# ─── 北向资金成交额（Eastmoney RPT_MUTUAL_DEALAMT）───────────────────────

def query_north_turnover(trade_date: str):
    """
    北向资金成交额（万元），来自 RPT_MUTUAL_DEALAMT。
    nf_deal_amt = 北向总成交额
    ssc_deal_amt = 港股通沪成交额
    st_deal_amt = 港股通深成交额
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT calc_date, nf_deal_amt, ssc_deal_amt, st_deal_amt,
               csi300_index_price, csi300_index_rate
        FROM north_turnover_hist
        WHERE calc_date = %s
    """, (trade_date,))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return []
    cols = ['date','nf_deal_amt','ssc_deal_amt','st_deal_amt','csi300_price','csi300_rate']
    return [dict(zip(cols, r)) for r in rows]


# ─── 大盘资金流 ─────────────────────────────────────────────────

def query_fund_flow(trade_date: str, limit: int = 20):
    """指定交易日 大单资金流（成交额排序）"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.name, f.price, f.change_pct, f.volume, f.amount, f.deal_nature
        FROM fund_flow_big_deal f
        JOIN companies c ON f.company_id = c.id
        WHERE DATE(f.trade_time) = %s
        ORDER BY f.amount DESC
        LIMIT %s
    """, (trade_date, limit))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return []
    cols = ['name','price','change_pct','volume','amount','nature']
    return [dict(zip(cols, r)) for r in rows]


# ─── 便捷封装 ───────────────────────────────────────────────────

def get_latest_trade_date() -> str:
    """获取最近有行情数据的交易日（通常是昨天）"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT MAX(trade_date) FROM daily_quotes")
    r = cur.fetchone()[0]
    conn.close()
    return str(r) if r else ''