#!/usr/bin/env python3
"""日内每15分钟刷新 ETF 实时行情（含主力资金/ IOPV）"""
import sys; sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")
from src.pipeline import run_etf_spot_only
from datetime import datetime
print(f"[{datetime.now()}] ETF日内刷新开始")
result = run_etf_spot_only(limit=1486)
print(f"[{datetime.now()}] ETF日内刷新完成: {result}")
