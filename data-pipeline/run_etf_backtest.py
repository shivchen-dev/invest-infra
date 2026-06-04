#!/usr/bin/env python3
"""ETF动量-风控双因子轮动策略 — 回测入口

用法:
    python run_etf_backtest.py --start 2025-01-01 --end 2026-06-01
    python run_etf_backtest.py --start 2025-06-01 --end 2026-06-01 --etf-codes 512480,159819,562500
"""

import argparse
import logging
import sys
from datetime import date

sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")

from src.backtest.strategies_etf import ETFBacktestConfig, run_etf_backtest
from src.backtest.feeds_etf import compute_all_factors

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)

# ─── 默认候选ETF池（16只物理AI板块）─────────────────────────
DEFAULT_ETF_POOL = [
    # 机器人
    "562500",  # 机器人ETF华夏
    "560630",  # 机器人ETF万家
    # 人工智能
    "159819",  # 人工智能ETF易方达
    "515070",  # 人工智能ETF华夏
    "515980",  # 人工智能ETF华富
    # 半导体
    "512480",  # 半导体ETF国联安
    "159813",  # 半导体ETF鹏华
    "159325",  # 半导体ETF南方
    # 智能汽车
    "515030",  # 新能源车ETF华夏
    "159889",  # 智能汽车ETF国泰
    "516520",  # 智能驾驶ETF华泰柏瑞
    # 军工
    "512660",  # 军工ETF国泰
    "512680",  # 军工ETF广发
    # 工业母机
    "159667",  # 工业母机ETF国泰
    # 新能源
    "515700",  # 新能源车ETF平安
    "516390",  # 新能源车ETF汇添富
]


def print_result(result: dict):
    """格式化打印回测结果 + KPI评分"""
    print("\n" + "=" * 60)
    print(f"  ETF动量-风控双因子轮动策略 回测报告")
    print("=" * 60)

    total_return = result["total_return"] * 100
    annual_return = result.get("annual_return", 0) * 100
    max_dd = result.get("max_drawdown", 0) * 100
    sharpe = result.get("sharpe_ratio", 0)
    pl_ratio = result.get("profit_loss_ratio", 0)
    calmar = result.get("calmar_ratio", 0)
    win_rate = result.get("win_rate", 0) * 100

    print(f"""
【收益】总收益: {total_return:.2f}% | 年化: {annual_return:.2f}%
【回撤】最大回撤: {max_dd:.2f}% | 卡玛: {calmar:.3f}
【风险】夏普: {sharpe:.3f} | 盈亏比: {pl_ratio:.2f} | 胜率: {win_rate:.1f}%
【交易】总交易次数: {result.get('total_trades', 'N/A')}
【账户】初始: {result['initial_cash']:.0f} → 最终: {result['final_value']:.2f}
    """)

    # ── KPI评分 ────────────────────────────────────────────
    print("【KPI评分】")
    kpi_checks = [
        ("年化收益", annual_return, [("Fail", 8, True), ("Pass", 15, False), ("Excellent", float("inf"), False)]),
        ("最大回撤", max_dd, [("Fail", 25, False), ("Pass", 15, False), ("Excellent", 15, True)]),
        ("夏普比率", sharpe, [("Fail", 0.5, True), ("Pass", 1.0, False), ("Excellent", 1.0, True)]),
        ("盈亏比", pl_ratio, [("Fail", 1.5, True), ("Pass", 2.5, False), ("Excellent", 2.5, True)]),
        ("卡玛比率", calmar, [("Fail", 0.5, True), ("Pass", 1.5, False), ("Excellent", 1.5, True)]),
    ]

    score_map = {"Fail": "❌", "Pass": "⚠️", "Excellent": "✅"}
    results_kpi = []
    for name, value, thresholds in kpi_checks:
        for label, threshold, below in thresholds:
            if below:
                condition = value < threshold
            else:
                condition = value >= threshold
            if condition:
                emoji = score_map[label]
                print(f"  {name}: {value:.3f} → {emoji} {label}")
                results_kpi.append((name, label, emoji))
                break

    fail_count = sum(1 for _, label, _ in results_kpi if label == "Fail")
    print(f"\n结论: {fail_count} 项Fail, 建议{'✓ 通过' if fail_count == 0 else '⚠ 调整参数'}")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="ETF动量-风控双因子轮动回测")
    parser.add_argument("--start", default="2025-01-02", help="回测开始日期 YYYY-MM-DD")
    parser.add_argument("--end", default="2026-06-01", help="回测结束日期 YYYY-MM-DD")
    parser.add_argument("--etf-codes", default=None, help="逗号分隔的ETF代码，如 512480,159819")
    parser.add_argument("--hold-count", type=int, default=4, help="持仓数量，默认4")
    parser.add_argument("--initial-cash", type=float, default=1000000.0, help="初始资金，默认100万")
    parser.add_argument("--momentum-window", type=int, default=20, help="动量窗口，默认20日")
    parser.add_argument("--stop-loss", type=float, default=0.05, help="止损线，默认5%")
    parser.add_argument("--reduce-threshold", type=float, default=0.80, help="降仓波动率阈值，默认80%百分位")
    parser.add_argument("--reduce-ratio", type=float, default=0.50, help="降仓比例，默认50%")
    parser.add_argument("--debug", action="store_true", help="开启debug日志")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)

    etf_codes = args.etf_codes.split(",") if args.etf_codes else DEFAULT_ETF_POOL

    config = ETFBacktestConfig(
        name="etf_momentum_risk_v1",
        etf_codes=etf_codes,
        hold_count=args.hold_count,
        momentum_window=args.momentum_window,
        risk_window=20,
        stop_loss_pct=-args.stop_loss,
        reduce_threshold=args.reduce_threshold,
        reduce_ratio=args.reduce_ratio,
        max_position_pct=0.30,
        initial_cash=args.initial_cash,
    )

    result = run_etf_backtest(config, start_date, end_date)

    if "error" in result:
        logger.error(f"回测失败: {result['error']}")
        sys.exit(1)

    print_result(result)


if __name__ == "__main__":
    main()