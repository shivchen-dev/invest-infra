#!/usr/bin/env python3
"""
cron_etf_arbitrage_signal.py — ETF 期现套利信号生成（Cron 调度）
============================================================

调度方式（交易日 16:50，在 ETF 因子计算完成后执行）：
  python3 scripts/cron_etf_arbitrage_signal.py

环境变量（全部可选，有默认值）：
  ARB_TRIGGER     触发阈值（默认 0.003 = 0.3%）
  ARB_MIN_LIQ    最低流动性（默认 0.6）
  ARB_MIN_PROFIT  最低净收益率（默认 0.001 = 0.1%）

输出：
  - 套利信号写入 etf_arbitrage_signals 表
  - 控制台打印触发 ETF 列表和收益估算
"""

import sys, os
sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")

# 加载 .env 环境变量
_dotenv = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
if os.path.exists(_dotenv):
    with open(_dotenv) as f:
        for line in f:
            k, _, v = line.strip().partition("=")
            if k and v:
                os.environ.setdefault(k.strip(), v.strip())

from datetime import date
from src.signals.etf_arbitrage import run_arbitrage_signal_calc, ArbitrageConfig
from src.config import arbitrage

if __name__ == "__main__":
    print("=" * 60)
    print(f"  ETF 期现套利信号 — {date.today()}")
    print("=" * 60)

    cfg = ArbitrageConfig(
        trigger_threshold=arbitrage.trigger_threshold,
        min_liquidity=arbitrage.min_liquidity,
        slippage_rate=arbitrage.slippage_rate,
        impact_rate=arbitrage.impact_rate,
        commission_rate=arbitrage.commission_rate,
        stamp_tax_rate=arbitrage.stamp_tax_rate,
        min_profit_threshold=arbitrage.min_profit_threshold,
        min_shares=arbitrage.min_shares,
    )

    result = run_arbitrage_signal_calc(cfg)

    print(f"\n套利信号数量: {result['signals']}")
    if result["signals"] > 0:
        print(f"总净收益率: {result['total_net_gain_pct']:.4f}%")
    print(f"结论: {'✅ 发现套利机会' if result['signals'] > 0 else '⚪ 无套利机会'}")