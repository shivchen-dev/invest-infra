#!/usr/bin/env python3
"""盘后 15:40 追加当日ETF历史K线"""
import sys; sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")
from src.collector.etf import batch_fetch_etf_hist
from datetime import datetime
print(f"[{datetime.now()}] ETF盘后K线采集开始")
count = batch_fetch_etf_hist(start_year=2025, limit=1486)
print(f"[{datetime.now()}] ETF盘后K线采集完成: {count}条")
