"""Markdown 回测报告生成器"""

import logging
from datetime import datetime

from src.backtest.engine import BacktestResult
from src.backtest.analyzers import FactorICReport, compare_strategies

logger = logging.getLogger(__name__)


def _fmt_pct(val: float) -> str:
    return f"{val * 100:+.2f}%"


def _fmt_val(val: float, digits: int = 2) -> str:
    return f"{val:,.{digits}f}"


def render_single_report(result: BacktestResult, ic_reports: list[FactorICReport] = None) -> str:
    """生成单次回测的完整 Markdown 报告"""
    d = result.to_dict()
    lines = []

    lines.append(f"# 📊 回测报告: {d['strategy']}")
    lines.append("")
    lines.append(f"- **回测区间**: {d['period']}")
    lines.append(f"- **股票数量**: {d['stock_count']}")
    lines.append(f"- **初始资金**: {_fmt_val(result.portfolio_value_start)}")
    lines.append(f"- **运行耗时**: {d['run_time_sec']} 秒")
    lines.append("")

    # ── 绩效总览 ──
    lines.append("## 绩效总览")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|:---|:---|")
    lines.append(f"| 期末资产 | {_fmt_val(result.portfolio_value_end)} |")
    lines.append(f"| 总收益率 | {_fmt_val(d['total_return_pct'])} |")
    lines.append(f"| 年化收益率 | {_fmt_val(d['annual_return_pct'])} |")
    lines.append(f"| 最大回撤 | {_fmt_val(d['max_drawdown_pct'])} |")
    lines.append(f"| 夏普比率 | {d['sharpe_ratio']} |")
    lines.append(f"| 卡玛比率 | {d['calmar_ratio']} |")
    lines.append(f"| 总交易次数 | {d['total_trades']} |")
    lines.append(f"| 胜率 | {_fmt_val(d['win_rate_pct'])} |")
    lines.append("")

    # ── 基准对比 ──
    lines.append("## 基准对比")
    lines.append("")
    lines.append("| 项目 | 策略 | 基准(等权持有) | 超额 |")
    lines.append("|:---|:---:|:---:|:---:|")
    lines.append(f"| 总收益率 | {_fmt_val(d['total_return_pct'])} | {_fmt_val(d['benchmark_return_pct'])} | {_fmt_val(d['active_return_pct'])} |")
    lines.append(f"| 信息比率 | {d['information_ratio']} | — | — |")
    lines.append("")

    # ── 因子 IC 分析 ──
    if ic_reports:
        lines.append("## 因子 IC 分析")
        lines.append("")
        lines.append("| 因子 | Mean IC | Std IC | IC IR | IC >0 占比 |")
        lines.append("|:---|:---:|:---:|:---:|:---:|")
        for ic in ic_reports:
            lines.append(
                f"| {ic.factor_key} | {ic.rank_ic_mean:.4f} | "
                f"{ic.rank_ic_std:.4f} | {ic.rank_ic_ir:.3f} | "
                f"{ic.rank_ic_positive_pct*100:.1f}% |"
            )
        lines.append("")

    # ── 持仓明细 ──
    lines.append("## 持仓明细")
    lines.append("")
    lines.append(f"共 {result.num_data} 只股票参与回测。")
    lines.append("")
    lines.append("> 💡 如需详细持仓和交易流水，请使用 `result.cerebro` 对象分析。")
    lines.append("")

    # ── 风险提示 ──
    lines.append("## 风险提示")
    lines.append("")
    lines.append("- 回测结果基于历史数据，**不代表未来收益**")
    lines.append("- 本报告未考虑冲击成本和流动性限制")
    lines.append("- 因子信号使用百分位值，需关注极端值影响")
    lines.append("")

    lines.append("---")
    lines.append(f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    lines.append("")

    return "\n".join(lines)


def render_comparison_report(results: list[BacktestResult], title: str = "策略对比") -> str:
    """多策略对比报告"""
    lines = []
    lines.append(f"# 📊 {title}")
    lines.append("")

    df = compare_strategies(results)
    lines.append(df.to_markdown(floatfmt=".2f"))
    lines.append("")

    lines.append("---")
    lines.append(f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    lines.append("")

    return "\n".join(lines)
