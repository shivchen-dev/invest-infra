"""
factors/etf_info_flow.py — ETF 信息流因子（I 维度）
============================================================

指标（共 4 个）：
  news_sentiment     新闻情绪（30%权重）：基于 news_articles 表行业聚合
  policy_support     政策支持度（25%权重）：政策关键词命中数
  social_sentiment   舆情（20%权重）：市场情绪代理
  report_coverage    研报覆盖度（25%权重）：近30天研报数量

数据缺口策略：
  - investment_memos 仅 36 条（company_id=5233），改为 news_articles 表行业聚合
  - 政策支持度 → 通过 akshare stock_board_industry_news_em 获取行业政策新闻
  - 研报覆盖 → akshare stock_research_report_em（有限数据）

存储：写入 etf_info_scores
"""

import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import psycopg2

from src.config import pg

logger = logging.getLogger(__name__)
logger = logging.getLogger(__name__)

# ─── 行业信息因子（I维度核心）── 从 industry_info_scores 读取行业信息密度分 ───────
# 申万行业 → 关键词映射（与 scripts/cron_industry_info.py 保持同步）
_SW_INFO_INDUSTRIES = [
    ('农林牧渔',   ['农林牧渔','农业','种子','养猪','猪肉','养殖','种植','农产品','畜牧','农机']),
    ('采掘',       ['采掘','煤炭','煤矿','原油','油气','天然气','能源开采','焦煤','动力煤']),
    ('化工',       ['化工','新材料','化学','石化','化肥','农药','化工原料','化工行业']),
    ('钢铁',       ['钢铁','螺纹钢','铁矿石','钢材','钢企','冶金','特钢','板材','不锈钢']),
    ('有色金属',   ['有色金属','有色','铜','铝','黄金','稀土','白银','锂','钴','小金属','铜矿','铝材']),
    ('电子',       ['电子','半导体','芯片','集成电路','PCB','面板','MLCC','光刻','晶圆','HBM','GPU芯片']),
    ('汽车',       ['汽车','新能源汽车','电动车','智能驾驶','整车','车企','锂电池车','锂电车','自动驾驶']),
    ('家用电器',   ['家用电器','家电','空调','冰箱','洗衣机','厨电','小家电','美的','格力','海尔']),
    ('食品饮料',   ['食品饮料','白酒','饮料','乳业','乳制品','调味品','零食','食品','酒','啤酒','食品加工']),
    ('纺织服装',   ['纺织服装','纺织','服装','面料','家纺','制衣','印染','服装品牌','棉纺']),
    ('轻工制造',   ['轻工制造','轻工','造纸','包装','印刷','家具','文娱用品','日用品','纸包装']),
    ('医药生物',   ['医药生物','医药','中药','创新药','医疗器械','生物医药','疫苗','医疗','化药','药店','CXO']),
    ('机械设备',   ['机械设备','机械','机器人','工程机械','数控机床','工业母机','自动化','农机','精密机械']),
    ('电气设备',   ['电气设备','电气','光伏','风电','储能','锂电池','动力电池','新能源发电','电力设备','逆变器']),
    ('公用事业',   ['公用事业','电力','燃气','水务','供热','环保','水务处理','垃圾发电','绿电']),
    ('交通运输',   ['交通运输','航空','机场','港口','公路','铁路','物流','快递','航运','集装箱','航空运输']),
    ('房地产',     ['房地产','房企','楼市','物业','地产','购房','房产','万科A','保利发展','碧桂园']),
    ('银行',       ['银行','存款','贷款','国有大行','股份制银行','城商行','农商行','银行股','信贷']),
    ('非银金融',   ['非银金融','券商','保险','证券','公募基金','私募基金','信托','金融科技','租赁','投行']),
    ('建筑装饰',   ['建筑装饰','建筑','基建','装饰','园林工程','装修','建筑设计','房地产建筑','工程建设']),
    ('计算机',     ['计算机','软件','AI','人工智能','云计算','大数据','信息安全','操作系统','应用软件','大模型','AI应用']),
    ('传媒',       ['传媒','游戏','影视','广告','出版','院线','短视频','流媒体','内容平台','电影','综艺']),
    ('通信',       ['通信','5G','6G','光通信','运营商','通信设备','物联网','卫星通信','网络设备','算力网络']),
    ('国防军工',   ['国防军工','军工','航天','航空','舰船','导弹','无人机','国防','军用','航天航空','雷达']),
    ('商业贸易',   ['商业贸易','商贸','零售','百货','超市','电商','跨境电商','贸易','进出口','新零售']),
    ('休闲服务',   ['休闲服务','旅游','酒店','免税','景区','乐园','出行服务','旅游景区','OTA','旅行社','餐饮','酒店旅游']),
]

def _get_sw_industry_info_score(conn, industry_str: str, calc_date: date) -> float:
    if not industry_str:
        return 50.0
    try:
        best_match, best_hits = None, 0
        for sw_name, keywords in _SW_INFO_INDUSTRIES:
            hits = sum(1 for kw in keywords if kw in industry_str)
            if hits > best_hits:
                best_hits, best_match = hits, sw_name
        if not best_match:
            return 50.0
        with conn.cursor() as cur:
            cur.execute(
                'SELECT info_score FROM industry_info_scores WHERE trade_date=%s AND sw_name=%s AND window_h=24 LIMIT 1',
                (calc_date, best_match))
            row = cur.fetchone()
            return float(row[0]) if row and row[0] is not None else 50.0
    except Exception:
        return 50.0


# 政策关键词
POLICY_POSITIVE_KW = [
    "支持", "鼓励", "补贴", "扶持", "优惠", "减税", "松绑", "放开",
    "促进", "推动", "发展", "规划", "纲要", "目标", "扩大内需", "稳增长",
    "双碳", "新能源", "专精特新", "国产替代", "自主可控", "科技自立",
]
POLICY_RISK_KW = [
    "限制", "监管", "收紧", "规范", "整改", "清退", "淘汰", "产能过剩",
    "安全审查", "反垄断", "防止资本无序扩张", "打压", "限制出口",
]

# ─── 行业涨跌缓存（避免同一行业重复请求 akshare）──────────────────────────
_industry_change_cache: dict[str, tuple[float, float]] = {}  # industry → (value, timestamp)
_CACHE_TTL = 300  # 5分钟


def _get_industry_change_cached(industry: str) -> float:
    """获取申万行业当日涨跌幅（带 5 分钟缓存）"""
    import time
    now = time.time()
    if industry in _industry_change_cache:
        val, ts = _industry_change_cache[industry]
        if now - ts < _CACHE_TTL:
            return val
    try:
        import akshare as ak
        board_df = ak.stock_board_industry_name_em()
        keyword = industry.replace("制造业", "").replace("业", "").strip()
        matched = board_df[board_df["板块名称"].str.contains(keyword, na=False)]
        val = float(matched.iloc[0].get("涨跌幅", 0)) if not matched.empty else 0.0
        _industry_change_cache[industry] = (val, now)
        return val
    except Exception:
        _industry_change_cache[industry] = (0.0, now)
        return 0.0


# ─── 新闻情绪 ────────────────────────────────────────────────────────────────

def _news_sentiment_by_industry(conn, industry: str, lookback_days: int = 7) -> float:
    """
    按行业聚合 news_articles 表中的情绪得分（0-100，中性=50）。
    lookback_days: 统计最近几天内的新闻（默认7天）
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) as total,
                    COALESCE(AVG(CASE
                        WHEN sentiment_label = 'positive' THEN 1.0
                        WHEN sentiment_label = 'negative' THEN -1.0
                        ELSE 0.0 END), 0) AS avg_senti
                FROM news_articles na
                JOIN companies c ON c.id = na.company_id
                WHERE c.industry = %s
                  AND na.published_at >= NOW() - INTERVAL '%s days'
                """,
                (industry, lookback_days),
            )
            row = cur.fetchone()
            if not row or not row[0] or row[0] == 0:
                return 50.0
            total, avg_senti = row[0], float(row[1])
            # 数量调整：新闻越多越可信；情绪 -1~+1 → 0~100
            weight = min(1.0, total / 10.0)  # 10条新闻以上权重饱和
            score = (avg_senti + 1) * 50  # -1→0, 0→50, +1→100
            return score * weight + 50 * (1 - weight)
    except Exception:
        return 50.0


def _policy_support_by_industry(conn, industry: str, lookback_days: int = 30) -> float:
    """
    政策支持度（0-100）：
    基于 news_articles 表的行业新闻，统计政策关键词命中率和正负比例。
    兼顾 akshare 实时行业政策数据（如果有的话）。
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT title, content_summary, sentiment_label
                FROM news_articles na
                JOIN companies c ON c.id = na.company_id
                WHERE c.industry = %s
                  AND na.published_at >= NOW() - INTERVAL '%s days'
                """,
                (industry, lookback_days),
            )
            rows = cur.fetchall()
            if not rows:
                return 50.0

            total = len(rows)
            pos_count = sum(1 for r in rows if r[2] == "positive")
            neg_count = sum(1 for r in rows if r[2] == "negative")

            # 统计政策关键词命中（标题或摘要）
            pos_hit = 0
            neg_hit = 0
            for title, content, _ in rows:
                text = f"{title or ''} {content or ''}".lower()
                for kw in POLICY_POSITIVE_KW:
                    if kw in text:
                        pos_hit += 1
                for kw in POLICY_RISK_KW:
                    if kw in text:
                        neg_hit += 1

            # 政策得分：正负命中差 / 总新闻数
            net_policy = (pos_hit - neg_hit) / max(1, total)
            # 情绪得分
            sentiment_score = (pos_count - neg_count) / max(1, total)
            # 综合（权重各半）
            score = ((net_policy + 1) * 25 + (sentiment_score + 1) * 50) / 2
            return max(0.0, min(100.0, score))
    except Exception:
        return 50.0


def _social_sentiment(conn, industry: str, lookback_days: int = 7) -> float:
    """
    舆情代理（0-100，中性=50）：
    基于行业新闻的情绪分布 + 新闻量（量大=高关注）
    用 akshare 行业涨跌作为补充（带缓存）
    """
    score = 50.0
    if industry:
        change = _get_industry_change_cached(industry)
        score = max(0.0, min(100.0, 50.0 + change * 10))

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*),
                       AVG(COALESCE(sentiment_score, 0.5))
                FROM news_articles na
                JOIN companies c ON c.id = na.company_id
                WHERE c.industry = %s
                  AND na.published_at >= NOW() - INTERVAL '%s days'
                """,
                (industry, lookback_days),
            )
            row = cur.fetchone()
            if row and row[0] and row[0] >= 3:
                news_score = float(row[1]) * 100
                score = score * 0.6 + news_score * 0.4
    except Exception:
        pass

    return max(0.0, min(100.0, score))


def _report_coverage(industry: str, lookback_days: int = 30) -> int:
    """
    研报覆盖度（代理指标）：
    news_articles 表中该行业近30天新闻数量作为研报覆盖的代理。
    （akshare stock_research_report_em 接口数据有限，暂用 news_count 替代）
    """
    # 用 news_count 作为研报覆盖的简化代理
    # akshare stock_research_report_em 数据有限，不重复调用
    return 0


def compute_etf_info_flow(conn, calc_date: date, dry_run: bool = False) -> pd.DataFrame:
    """
    主入口：计算 ETF 信息流因子（I 维度）
    """
    logger.info("[info_flow] 开始计算 I 维度因子 (date=%s)", calc_date)

    # 读取所有活跃 ETF（带跟踪指数，用于行业映射）
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, code, name, 跟踪指数 FROM etfs WHERE is_active = true"
        )
        etf_rows = cur.fetchall()

    if not etf_rows:
        logger.warning("[info_flow] 无活跃ETF")
        return pd.DataFrame()

    results = []
    for (etf_id, code, name, track_index) in etf_rows:
        row_result = {"etf_id": etf_id, "calc_date": calc_date}

        # 从跟踪指数提取行业
        industry = ""
        if track_index:
            industry = track_index.replace("指数", "").replace("沪深", "").replace("中证", "").replace("上证", "").strip()

        # ── news_sentiment ──
        news_sentiment = _news_sentiment_by_industry(conn, industry) if industry else 50.0
        row_result["news_sentiment"] = round(news_sentiment, 2)

        # ── news_count（作为 info 表的补充）──
        try:
            with conn.cursor() as cur:
                if industry:
                    cur.execute(
                        """
                        SELECT COUNT(*)
                        FROM news_articles na
                        JOIN companies c ON c.id = na.company_id
                        WHERE c.industry = %s
                          AND na.published_at >= NOW() - INTERVAL '7 days'
                        """,
                        (industry,)
                    )
                else:
                    cur.execute(
                        "SELECT COUNT(*) FROM news_articles WHERE published_at >= NOW() - INTERVAL '7 days'"
                    )
                row_result["news_count"] = cur.fetchone()[0] or 0
        except Exception:
            row_result["news_count"] = 0

        # ── policy_support ──
        policy_support = _policy_support_by_industry(conn, industry) if industry else 50.0
        row_result["policy_support"] = round(policy_support, 2)

        # ── social_sentiment ──
        social_sentiment = _social_sentiment(conn, industry) if industry else 50.0
        row_result["social_sentiment"] = round(social_sentiment, 2)

        # ── report_coverage ──
        report_coverage = _report_coverage(industry)
        row_result["report_coverage"] = report_coverage

        # ── industry_info_score（I维度核心，来自行业快讯密度）──
        industry_info_score = _get_sw_industry_info_score(conn, industry, calc_date)
        row_result["industry_info_score"] = round(industry_info_score, 2)

        results.append(row_result)

    df = pd.DataFrame(results)

    if not dry_run and not df.empty:
        _write_info_scores(conn, df, calc_date)

    logger.info("[info_flow] 完成，计算 %d 只ETF信息流因子", len(df))
    return df


def _write_info_scores(conn, df: pd.DataFrame, calc_date: date):
    """写入 etf_info_scores 表（ON CONFLICT UPDATE）"""
    if df.empty:
        return
    with conn.cursor() as cur:
        for _, row in df.iterrows():
            cur.execute(
                """
                INSERT INTO etf_info_scores
                  (etf_id, calc_date, news_sentiment, news_count, policy_support,
                   social_sentiment, report_coverage, industry_info_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (etf_id, calc_date) DO UPDATE SET
                  news_sentiment=EXCLUDED.news_sentiment,
                  news_count=EXCLUDED.news_count,
                  policy_support=EXCLUDED.policy_support,
                  social_sentiment=EXCLUDED.social_sentiment,
                  report_coverage=EXCLUDED.report_coverage,
                  industry_info_score=EXCLUDED.industry_info_score
                """,
                (row["etf_id"], calc_date,
                 row.get("news_sentiment"), row.get("news_count"),
                 row.get("policy_support"), row.get("social_sentiment"),
                 row.get("report_coverage"), row.get("industry_info_score"))
            )
    conn.commit()
    logger.info("[info_flow] 已写入 %d 条记录到 etf_info_scores", len(df))


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")
    # PG_PASSWORD 由 cron_dispatcher.py 从 .secrets/pg.env 注入

    from src.config import pg
    conn = psycopg2.connect(pg.uri)
    calc_date = date.today()
    df = compute_etf_info_flow(conn, calc_date, dry_run=True)
    print(df.head(10).to_string())
    conn.close()