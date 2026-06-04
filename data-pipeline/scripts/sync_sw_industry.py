#!/usr/bin/env python3
"""
sync_sw_industry.py — 申万一级行业代码与涨跌行情同步

将申万行业涨跌数据写入 etf_sw_industry_sentiment 表：
  trade_date | sw_code | sw_name | change_pct

用法：
    python3 scripts/sync_sw_industry.py          # 同步今日数据
    python3 scripts/sync_sw_industry.py --all   # 全量历史（耗时长）
"""
import argparse
import logging
import sys, os
from datetime import date, timedelta

sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")
_dotenv = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_dotenv):
    with open(_dotenv) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

import akshare as ak
import psycopg2
from src.config import pg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sync_sw_industry")

# 申万一级行业（33个）代码映射
SW1_INDUSTRIES = {
    "农林牧渔": "801010",
    "采掘": "801020",
    "化工": "801030",
    "钢铁": "801040",
    "有色金属": "801050",
    "电子": "801080",
    "汽车": "801110",
    "家用电器": "801120",
    "食品饮料": "801130",
    "纺织服装": "801140",
    "轻工制造": "801150",
    "医药生物": "801170",
    "机械设备": "801730",
    "电气设备": "801740",
    "公用事业": "801710",
    "交通运输": "801720",
    "房地产": "801760",
    "银行": "801780",
    "非银金融": "801790",
    "建筑装饰": "801720",
    "计算机": "801750",
    "传媒": "801760",
    "通信": "801770",
    "国防军工": "801710",
    "商业贸易": "801800",
    "休闲服务": "801210",
    "纺织": "801140",
    "轻工": "801150",
    "环保": "801710",
    "银行": "801780",
    "证券": "801790",
    "保险": "801790",
}


def fetch_sw_change(code: str, trade_date: date) -> float | None:
    """获取申万行业 code 在 trade_date 当日的涨跌幅（%），前日对比"""
    try:
        df = ak.index_hist_sw(symbol=code, period="day")
        if df is None or df.empty:
            return None
        # 找到最近 <= trade_date 的那条记录
        df["日期_dt"] = df["日期"].astype(str)
        trade_str = trade_date.isoformat()
        # 二分查找 <= trade_date 的最近交易日
        valid = df[df["日期_dt"] <= trade_str].copy()
        if len(valid) < 2:
            return None
        latest = valid.iloc[-1]
        prev = valid.iloc[-2]
        chg = (float(latest["收盘"]) / float(prev["收盘"]) - 1) * 100
        return round(chg, 4)
    except Exception as e:
        logger.debug("SW %s @ %s 获取失败: %s", code, trade_date, e)
        return None


def init_table():
    """建表（仅首次需要）"""
    conn = psycopg2.connect(pg.uri)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS etf_sw_industry_sentiment (
            id SERIAL PRIMARY KEY,
            trade_date DATE NOT NULL,
            sw_code TEXT NOT NULL,
            sw_name TEXT NOT NULL,
            change_pct NUMERIC(8, 4),
            UNIQUE(trade_date, sw_code)
        );
        CREATE INDEX IF NOT EXISTS idx_sw_trade_date ON etf_sw_industry_sentiment(trade_date);
        CREATE INDEX IF NOT EXISTS idx_sw_code ON etf_sw_industry_sentiment(sw_code);
    """)
    conn.commit()
    conn.close()
    logger.info("etf_sw_industry_sentiment 表就绪")


def sync_one_day(trade_date: date):
    """同步指定日期（单日，快速）"""
    logger.info("同步申万行业涨跌 %s", trade_date)
    records = []
    for sw_name, sw_code in SW1_INDUSTRIES.items():
        chg = fetch_sw_change(sw_code, trade_date)
        if chg is not None:
            records.append((trade_date, sw_code, sw_name, chg))
        else:
            records.append((trade_date, sw_code, sw_name, None))

    if not records:
        logger.warning("无数据写入")
        return 0

    conn = psycopg2.connect(pg.uri)
    cur = conn.cursor()
    for trade_date, sw_code, sw_name, chg in records:
        cur.execute("""
            INSERT INTO etf_sw_industry_sentiment (trade_date, sw_code, sw_name, change_pct)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (trade_date, sw_code) DO UPDATE SET change_pct=EXCLUDED.change_pct
        """, (trade_date, sw_code, sw_name, chg))
    conn.commit()
    conn.close()
    written = sum(1 for r in records if r[3] is not None)
    logger.info("写入 %d/%d 条（含空值=%d）", written, len(records), len(records) - written)
    return written


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="同步全量历史（2025-01-02至今）")
    parser.add_argument("--date", help="指定日期 YYYY-MM-DD（默认今日）")
    args = parser.parse_args()

    init_table()

    if args.all:
        # 全量历史（仅一次性的补充初始化）
        today = date.today()
        cur_date = date(2025, 1, 2)
        total = 0
        while cur_date <= today:
            n = sync_one_day(cur_date)
            total += n
            if cur_date.weekday() < 5:  # 跳过周末
                cur_date += timedelta(days=1)
            else:
                cur_date += timedelta(days=1)
        logger.info("全量同步完成: 共写入 %d 条", total)
    else:
        target_date = date.fromisoformat(args.date) if args.date else date.today()
        sync_one_day(target_date)