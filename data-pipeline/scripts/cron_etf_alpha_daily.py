#!/usr/bin/env python3
"""日结 21:00 计算 ETF Alpha 信号"""
import sys; sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")
from src.signals.etf_alpha import compute_etf_alpha
from datetime import date, datetime
import psycopg2
from src.config import pg
print(f"[{datetime.now()}] ETF Alpha信号计算开始")
conn = psycopg2.connect(pg.uri)
result = compute_etf_alpha(conn, date.today(), lookback_days=60)
print(f"[{datetime.now()}] ETF Alpha信号: {result}")
conn.close()
