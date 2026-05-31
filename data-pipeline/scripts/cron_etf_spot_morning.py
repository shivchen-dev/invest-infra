#!/usr/bin/env python3
"""盘前 09:25 同步 ETF 实时行情（IOPV/溢价率/换手率/主力资金全量）"""
import sys; sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")
from src.pipeline import run_etf_pipeline
from datetime import datetime
print(f"[{datetime.now()}] ETF盘前同步开始")
result = run_etf_pipeline(days=1, limit=1486)
print(f"[{datetime.now()}] ETF盘前同步完成: {result}")
