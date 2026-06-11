"""
factors/etf_fundamental.py — ETF 基本面因子（F 维度）
============================================================

指标（共 5 个，满分 100）：
  industry_sentiment      行业景气度（30%权重）← 申万行业指数日涨跌幅
  component_roe          成分股ROE均值（25%权重）
  component_gross_margin  成分股毛利率均值（15%权重）
  cr5                    成分股集中度CR5（15%权重）
  rebalance_freq         指数换仓频率（15%权重）

数据缺口策略（Proxy Indicators）：
  - 行业情绪：申万行业指数日涨跌幅（index_hist_sw）替代 THS 接口
  - 跟踪指数 → 申万行业代码 关键字匹配映射

存储：写入 etf_fundamental_scores（calc_date, etf_id, 各指标原始值）
"""

import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import psycopg2

from src.config import pg

logger = logging.getLogger(__name__)

# ─── 申万行业日涨跌缓存（当日内只调一次 akshare）──────────────────────────────
_sw_change_cache: dict[str, float] = {}   # sw_name → change_pct


# ─── 指数关键字 → 申万行业 映射 ─────────────────────────────────────────────
# 优先级：精确匹配 > 模糊包含
_TRACK_TO_SW = {
    # 精确/细分行业
    "中药":      "医药生物",
    "创新药":    "医药生物",
    "生物医药":  "医药生物",
    "医疗":      "医药生物",
    "疫苗":      "医药生物",
    "半导体":    "电子",
    "芯片":      "电子",
    "光刻机":    "电子",
    "电子":      "电子",
    "有色金属":  "有色金属",
    "稀土":      "有色金属",
    "黄金":      "有色金属",
    "铜":        "有色金属",
    "铝":        "有色金属",
    "食品饮料":  "食品饮料",
    "白酒":      "食品饮料",
    "饮料":      "食品饮料",
    "乳制品":    "食品饮料",
    "调味品":    "食品饮料",
    "银行":      "银行",
    "证券":      "非银金融",
    "保险":      "非银金融",
    "非银金融":  "非银金融",
    "金融":      "银行",
    "科技":      "计算机",
    "人工智能":  "计算机",
    "ai":        "计算机",
    "ai算力":    "计算机",
    "计算机":    "计算机",
    "软件":      "计算机",
    "通信":      "通信",
    "5G":        "通信",
    "物联网":    "通信",
    "新能源":    "电气设备",
    "光伏":      "电气设备",
    "风电":      "电气设备",
    "储能":      "电气设备",
    "锂电池":    "电气设备",
    "动力电池":  "电气设备",
    "煤炭":      "采掘",
    "石油":      "采掘",
    "天然气":    "采掘",
    "钢铁":      "钢铁",
    "化工":      "化工",
    "新材料":    "化工",
    "稀土":      "有色金属",
    "有色":      "有色金属",
    "汽车":      "汽车",
    "新能源汽车": "汽车",
    "无人驾驶":  "汽车",
    "房地产":    "房地产",
    "物业":      "房地产",
    "家电":      "家用电器",
    "家具":      "轻工制造",
    "纺织服装":  "纺织服装",
    "服装":      "纺织服装",
    "传媒":      "传媒",
    "游戏":      "传媒",
    "影视":      "传媒",
    "教育":      "休闲服务",
    "旅游":      "休闲服务",
    "酒店":      "休闲服务",
    "航空":      "交通运输",
    "机场":      "交通运输",
    "港口":      "交通运输",
    "公路":      "交通运输",
    "铁路":      "交通运输",
    "快递":      "交通运输",
    "军工":      "国防军工",
    "国防":      "国防军工",
    "航天":      "国防军工",
    "航天":      "国防军工",
    "机械":      "机械设备",
    "工程机械":  "机械设备",
    "机器人":    "机械设备",
    "数控机床":  "机械设备",
    "环保":      "公用事业",
    "农林牧渔":  "农林牧渔",
    "农业":      "农林牧渔",
    "种子":      "农林牧渔",
    "养猪":      "农林牧渔",
    "猪肉":      "农林牧渔",
    "商业贸易":  "商业贸易",
    "零售":      "商业贸易",
    "商贸":      "商业贸易",
    "建筑":      "建筑装饰",
    "基建":      "建筑装饰",
    "装修":      "建筑装饰",
    "公用事业":  "公用事业",
    "水务":      "公用事业",
    "燃气":      "公用事业",
    "电力":      "公用事业",
    "绿电":      "公用事业",
}


def _extract_sw_industry(track_index: str) -> Optional[str]:
    """从跟踪指数名提取匹配的申万行业名"""
    if not track_index:
        return None
    name = track_index.replace("指数", "").replace("R", "").replace("H", "").strip()
    # 最长匹配优先
    best = None
    for kw, sw in _TRACK_TO_SW.items():
        if kw in name:
            if best is None or len(kw) > len(best):
                best = kw
    if best:
        return _TRACK_TO_SW[best]
    return None


def _load_sw_changes(trade_date: date, conn=None):
    """从 DB 加载当日申万行业涨跌，无数据则从 akshare 补调"""
    import akshare as ak

    _conn = conn or psycopg2.connect(pg.uri)
    _cur = _conn.cursor()
    _cur.execute("""
        SELECT sw_name, change_pct FROM etf_sw_industry_sentiment
        WHERE trade_date = %s AND change_pct IS NOT NULL
    """, (trade_date,))
    rows = _cur.fetchall()
    if conn is None:
        _conn.close()

    if rows:
        _sw_change_cache.update({name: float(chg) for name, chg in rows})
        logger.info("申万涨跌从DB加载 %d 个行业", len(rows))
        return

    # DB 无数据，从 akshare 补调
    SW1_INDUSTRIES = {
        "农林牧渔": "801010", "采掘": "801020", "化工": "801030", "钢铁": "801040",
        "有色金属": "801050", "电子": "801080", "汽车": "801110", "家用电器": "801120",
        "食品饮料": "801130", "纺织服装": "801140", "轻工制造": "801150",
        "医药生物": "801170", "机械设备": "801730", "电气设备": "801740",
        "公用事业": "801710", "交通运输": "801720", "房地产": "801760",
        "银行": "801780", "非银金融": "801790", "建筑装饰": "801720",
        "计算机": "801750", "传媒": "801760", "通信": "801770",
        "国防军工": "801710", "商业贸易": "801800", "休闲服务": "801210",
    }
    for sw_name, sw_code in SW1_INDUSTRIES.items():
        try:
            df = ak.index_hist_sw(symbol=sw_code, period="day")
            if len(df) >= 2:
                chg = round((float(df.iloc[-1]["收盘"]) / float(df.iloc[-2]["收盘"]) - 1) * 100, 4)
                _sw_change_cache[sw_name] = float(chg)
        except Exception:
            pass
    logger.info("申万涨跌从akshare补调 %d 个行业", len(_sw_change_cache))


def _get_sw_sentiment(industry: str) -> float:
    """根据申万行业涨跌幅算情绪（0-100，中性=50）"""
    if not industry or industry not in _sw_change_cache:
        return 50.0
    chg = _sw_change_cache[industry]
    # +3% → 80, 0% → 50, -3% → 20（线性缩放，每1%pct=10分）
    score = 50.0 + chg * 10
    return max(0.0, min(100.0, score))


def _compute_industry_sentiment(conn, industry: str) -> float:
    """
    综合行业情绪：申万行业指数涨跌幅（主）+ news舆情（辅）
    """
    score = _get_sw_sentiment(industry)
    # news_articles 补充（行业舆情占30%权重）；独立连接避免污染主事务
    try:
        _news_conn = psycopg2.connect(pg.uri)
        _news_conn.autocommit = True
        try:
            with _news_conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*),
                           COALESCE(AVG(CASE WHEN sentiment_label = 'positive' THEN 1.0
                                              WHEN sentiment_label = 'negative' THEN -1.0
                                              ELSE 0.0 END), 0) AS avg_sentiment
                    FROM news_articles na
                    JOIN companies c ON c.id = na.company_id
                    WHERE c.industry = %s
                      AND na.published_at >= NOW() - INTERVAL '7 days'
                    """, (industry,))
                row = cur.fetchone()
                if row and row[0] and row[0] >= 3:
                    news_sentiment = (row[1] + 1) * 50  # -1~+1 → 0~100
                    score = score * 0.7 + news_sentiment * 0.3
        finally:
            _news_conn.close()
    except Exception:
        # news查询失败时静默（申万指数已是有效代理），继续返回申万分数
        pass
    return max(0.0, min(100.0, score))


def _compute_component_roe(conn, etf_code: str) -> Optional[float]:
    """
    成分股 ROE 等权均值（%）：从财务宽表计算 net_profit/total_equity
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 跟踪指数 FROM etfs WHERE code = %s", (etf_code,))
            row = cur.fetchone()
            if not row or not row[0]:
                return None
            index_name = row[0]
            cur.execute(
                """
                SELECT AVG(fr.net_profit::float / NULLIF(fr.total_equity, 0) * 100) as avg_roe
                FROM financial_reports fr
                JOIN companies c ON c.id = fr.company_id
                WHERE fr.report_type = 'annual'
                  AND fr.total_equity IS NOT NULL AND fr.total_equity != 0
                  AND fr.net_profit IS NOT NULL
                  AND c.industry IS NOT NULL AND c.industry != ''
                  AND c.industry LIKE %s
                LIMIT 50
                """,
                (f"%{index_name[:6]}%",),
            )
            result = cur.fetchone()
            if result and result[0] is not None:
                roe = float(result[0])
                if 0 < roe < 100:
                    return roe
            return None
    except Exception as e:
        logger.warning("[fundamental] ROE查询异常 code=%s: %s", etf_code, e)
        try:
            conn.rollback()
        except Exception:
            pass
        return None


def _compute_component_gross_margin(conn, etf_code: str) -> Optional[float]:
    """
    成分股毛利率等权均值（%）：从财务宽表计算 gross_profit/revenue
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 跟踪指数 FROM etfs WHERE code = %s", (etf_code,))
            row = cur.fetchone()
            if not row or not row[0]:
                return None
            index_name = row[0]
            cur.execute(
                """
                SELECT AVG(fr.gross_profit::float / NULLIF(fr.revenue, 0) * 100) as avg_gm
                FROM financial_reports fr
                JOIN companies c ON c.id = fr.company_id
                WHERE fr.report_type = 'annual'
                  AND fr.revenue IS NOT NULL AND fr.revenue != 0
                  AND fr.gross_profit IS NOT NULL
                  AND c.industry IS NOT NULL AND c.industry != ''
                  AND c.industry LIKE %s
                LIMIT 50
                """,
                (f"%{index_name[:6]}%",),
            )
            result = cur.fetchone()
            if result and result[0] is not None:
                gm = float(result[0])
                if 0 < gm < 100:
                    return gm
            return None
    except Exception as e:
        logger.warning("[fundamental] 毛利率查询异常 code=%s: %s", etf_code, e)
        try:
            conn.rollback()
        except Exception:
            pass
        return None

def compute_etf_fundamental(conn, calc_date: date, dry_run: bool = False) -> pd.DataFrame:
    """
    主入口：计算 ETF 基本面因子（F 维度）
    """
    logger.info("[fundamental] 开始计算 F 维度因子 (date=%s)", calc_date)

    # 预加载申万行业涨跌（当日只调一次，使用独立连接，不污染主事务）
    _load_sw_changes(calc_date, conn=None)

    # 读取所有 ETF（带跟踪指数）- 使用 autocommit 避免事务状态污染
    _conn = psycopg2.connect(pg.uri)
    _conn.autocommit = True
    with _conn.cursor() as cur:
        cur.execute(
            """SELECT e.id, e.code, e.name, e.跟踪指数,
                      e.cr5, e.cr10, e.index_rebalance_freq, e.index_category
               FROM etfs e WHERE e.is_active = true"""
        )
        etf_rows = cur.fetchall()
    _conn.close()

    if not etf_rows:
        logger.warning("[fundamental] 无活跃ETF")
        return pd.DataFrame()

    results = []
    for (etf_id, code, name, track_index, cr5, cr10, rebalance_freq, index_category) in etf_rows:
        row_result = {"etf_id": etf_id, "calc_date": calc_date}

        # ── industry_sentiment（申万行业指数替代THS接口）──
        if track_index:
            sw_industry = _extract_sw_industry(track_index)
            if sw_industry:
                industry_sentiment = _compute_industry_sentiment(conn, sw_industry)
            else:
                industry_sentiment = 50.0
        else:
            industry_sentiment = 50.0
        row_result["industry_sentiment"] = round(industry_sentiment, 4)

        # ── component_roe ──
        component_roe = _compute_component_roe(conn, code)
        row_result["component_roe"] = round(component_roe, 4) if component_roe is not None else None

        # ── component_gross_margin ──
        component_gm = _compute_component_gross_margin(conn, code)
        row_result["component_gross_margin"] = round(component_gm, 4) if component_gm is not None else None

        # ── cr5 / cr10 ──
        row_result["cr5"] = float(cr5) if cr5 is not None else None
        row_result["cr10"] = float(cr10) if cr10 is not None else None

        # ── rebalance_freq ──
        row_result["rebalance_freq"] = int(rebalance_freq) if rebalance_freq is not None else 4

        # ── index_quality_score ──
        quality = 40.0
        if track_index:
            quality += 20.0
        if index_category:
            quality += 10.0
        if rebalance_freq in (1, 2, 4):
            quality += 10.0
        elif rebalance_freq == 12:
            quality += 5.0
        row_result["index_quality_score"] = min(100.0, quality)

        results.append(row_result)

    df = pd.DataFrame(results)

    if not dry_run and not df.empty:
        _write_fundamental_scores(conn, df, calc_date)

    logger.info("[fundamental] 完成，计算 %d 只ETF基本面因子", len(df))
    return df


def _write_fundamental_scores(conn, df: pd.DataFrame, calc_date: date):
    """写入 etf_fundamental_scores 表（ON CONFLICT UPDATE）"""
    if df.empty:
        return
    def _to_pg(v):
        """将 numpy/Python 类型转为 PostgreSQL 可接受的纯 Python 类型"""
        if v is None:
            return None
        # numpy 类型优先处理（isinstance(np.float64, float)==True 会导致直接返回）
        if isinstance(v, np.floating):
            return float(v)
        if isinstance(v, np.integer):
            return int(v)
        if isinstance(v, (int, float, str)):
            return v
        try:
            return float(v)
        except (TypeError, ValueError):
            return str(v)

    with conn.cursor() as cur:
        for _, row in df.iterrows():
            cur.execute(
                """
                INSERT INTO etf_fundamental_scores
                  (etf_id, calc_date, industry_sentiment, component_roe, component_gross_margin,
                   cr5, cr10, rebalance_freq, index_quality_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (etf_id, calc_date) DO UPDATE SET
                  industry_sentiment=EXCLUDED.industry_sentiment,
                  component_roe=EXCLUDED.component_roe,
                  component_gross_margin=EXCLUDED.component_gross_margin,
                  cr5=EXCLUDED.cr5, cr10=EXCLUDED.cr10,
                  rebalance_freq=EXCLUDED.rebalance_freq,
                  index_quality_score=EXCLUDED.index_quality_score
                """,
                (_to_pg(row["etf_id"]), calc_date,
                 _to_pg(row.get("industry_sentiment")), _to_pg(row.get("component_roe")),
                 _to_pg(row.get("component_gross_margin")), _to_pg(row.get("cr5")),
                 _to_pg(row.get("cr10")), _to_pg(row.get("rebalance_freq")),
                 _to_pg(row.get("index_quality_score"))))
    conn.commit()
    logger.info("[fundamental] 已写入 %d 条记录到 etf_fundamental_scores", len(df))


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")
    # PG_PASSWORD 由 cron_dispatcher.py 从 .secrets/pg.env 注入

    from src.config import pg
    conn = psycopg2.connect(pg.uri)
    calc_date = date.today()
    df = compute_etf_fundamental(conn, calc_date, dry_run=True)
    print(df.head(10).to_string())
    conn.close()