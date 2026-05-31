"""另类因子计算器 — 从 news_articles 计算舆情类因子"""

import logging
from datetime import date, timedelta

import pandas as pd
import psycopg2

from src.config import pg as pg_cfg
from src.factors.base import FactorCalculator

logger = logging.getLogger(__name__)


class SentimentScoreCalculator(FactorCalculator):
    """7日新闻情感平均分"""
    factor_key = "sentiment_score"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        start = calc_date - timedelta(days=7)
        conn = psycopg2.connect(pg_cfg.uri)
        try:
            sql = """
                SELECT na.company_id, AVG(na.sentiment_score) as avg_sentiment
                FROM news_articles na
                WHERE na.company_id = ANY(%s)
                  AND na.published_at BETWEEN %s AND %s
                  AND na.sentiment_score IS NOT NULL
                GROUP BY na.company_id
            """
            df = pd.read_sql(sql, conn, params=(company_ids, start, calc_date))
            results = []
            for _, row in df.iterrows():
                results.append({
                    "company_id": int(row["company_id"]),
                    "value": round(float(row["avg_sentiment"]), 6),
                })
            # 没有新闻的补 None
            existing = {r["company_id"] for r in results}
            for cid in company_ids:
                if cid not in existing:
                    results.append({"company_id": cid, "value": None})
            return results
        finally:
            conn.close()


class NewsVolume7dCalculator(FactorCalculator):
    """7日新闻量"""
    factor_key = "news_volume_7d"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        start = calc_date - timedelta(days=7)
        conn = psycopg2.connect(pg_cfg.uri)
        try:
            sql = """
                SELECT na.company_id, COUNT(*) as news_count
                FROM news_articles na
                WHERE na.company_id = ANY(%s)
                  AND na.published_at BETWEEN %s AND %s
                GROUP BY na.company_id
            """
            df = pd.read_sql(sql, conn, params=(company_ids, start, calc_date))
            results = []
            for _, row in df.iterrows():
                results.append({
                    "company_id": int(row["company_id"]),
                    "value": float(row["news_count"]),
                })
            existing = {r["company_id"] for r in results}
            for cid in company_ids:
                if cid not in existing:
                    results.append({"company_id": cid, "value": 0.0})
            return results
        finally:
            conn.close()


class NewsVolumeChangeCalculator(FactorCalculator):
    """新闻量变化率 = (本周-上周)/上周"""
    factor_key = "news_volume_change"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        conn = psycopg2.connect(pg_cfg.uri)
        try:
            this_week_start = calc_date - timedelta(days=7)
            last_week_start = calc_date - timedelta(days=14)
            sql = """
                SELECT company_id,
                       SUM(CASE WHEN published_at BETWEEN %s AND %s THEN 1 ELSE 0 END) as this_week,
                       SUM(CASE WHEN published_at BETWEEN %s AND %s THEN 1 ELSE 0 END) as last_week
                FROM news_articles
                WHERE company_id = ANY(%s)
                  AND published_at >= %s
                GROUP BY company_id
            """
            df = pd.read_sql(sql, conn, params=(
                this_week_start, calc_date,
                last_week_start, this_week_start,
                company_ids, last_week_start,
            ))
            results = []
            for _, row in df.iterrows():
                last = row["last_week"] or 0
                if last == 0:
                    val = 0.0
                else:
                    val = ((row["this_week"] or 0) - last) / last
                results.append({
                    "company_id": int(row["company_id"]),
                    "value": round(float(val), 6),
                })
            existing = {r["company_id"] for r in results}
            for cid in company_ids:
                if cid not in existing:
                    results.append({"company_id": cid, "value": 0.0})
            return results
        finally:
            conn.close()
