"""
ETF 期现套利信号模块
========================

信号触发条件（需同时满足）：
  ① |溢价率| > 阈值（abs_premium > trigger_threshold）
  ② 流动性评分 > min_liquidity
  ③ 持仓周期满足 T+1 规则（今日触发，次日执行）

收益估算：
  理论收益 = |溢价率| × 份额数
  实际收益 = 理论收益 - 滑点成本 - 手续费 - 冲击成本

滑点估算：
  单边滑点  = 价格 × slippage_rate（默认 0.0005 = 0.05%）
  冲击成本  = 成交量占比 × impact_rate（默认 0.0003）
  总成本    = 单边滑点×2 + 冲击成本 + 手续费率
"""

import logging
from dataclasses import dataclass
from datetime import date

import psycopg2

from src.config import pg

logger = logging.getLogger(__name__)


# ─── 方向枚举 ──────────────────────────────────────────────────────────

class ArbitrageDirection:
    """套利方向"""
    PREMIUM = "premium"      # 溢价套利：ETF 价格 > IOPV，卖出 ETF + 申购 ETF
    DISCOUNT = "discount"    # 折价套利：ETF 价格 < IOPV，买入 ETF + 赎回 ETF


# ─── 配置 ──────────────────────────────────────────────────────────────

@dataclass
class ArbitrageConfig:
    """ETF 套利信号配置参数"""
    trigger_threshold: float = 0.003      # 溢价率绝对值 > 0.3% 才触发
    min_liquidity: float = 0.6           # 流动性评分 > 0.6
    slippage_rate: float = 0.0005         # 单边滑点 0.05%
    impact_rate: float = 0.0003           # 冲击成本系数
    commission_rate: float = 0.0003      # 买卖双向手续费率 0.03%
    stamp_tax_rate: float = 0.001        # 印花税 0.1%（仅卖出收取）
    min_profit_threshold: float = 0.001  # 扣除成本后最低收益阈值 0.1%
    min_shares: int = 500000              # 最小份额（约 50 万元）
    signal_valid_days: int = 1            # 信号 T+1 有效


# ─── 信号结果 ──────────────────────────────────────────────────────────

@dataclass
class ArbitrageSignal:
    """套利信号"""
    etf_id: int
    code: str
    name: str
    direction: str                     # premium / discount
    premium_rate: float               # 当前溢价率（%，带符号）
    abs_premium: float                 # 绝对溢价率（%）
    liquidity_score: float             # 流动性评分
    trigger_threshold: float
    theoretical_gain_pct: float        # 理论收益率（%）
    total_cost_pct: float              # 总成本率（%）
    net_gain_pct: float              # 净收益（%）
    signal_action: str                # sell_etf_buy_iopv / buy_etf_sell_iopv
    slippage_cost: float
    impact_cost: float
    commission_cost: float
    stamp_tax_cost: float
    confidence: str                    # high / medium / low
    signal_date: date


# ─── 核心信号生成 ──────────────────────────────────────────────────────


def generate_arbitrage_signals(
    conn,
    calc_date: date,
    cfg: ArbitrageConfig,
) -> list[ArbitrageSignal]:
    """
    从 etf_factor_values 读取溢价率+流动性，生成触发信号的 ETF 套利信号列表。
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                efv.etf_id,
                e.code,
                e.name,
                efv.premium_rate,
                efv.abs_premium,
                efv.liquidity_score,
                eq.close_price,
                eq.iopv,
                eq.volume,
                eq.amount
            FROM etf_factor_values efv
            JOIN etfs e ON e.id = efv.etf_id
            LEFT JOIN etf_quotes eq ON eq.etf_id = efv.etf_id AND eq.trade_date = efv.calc_date
            WHERE efv.calc_date = %s
              AND efv.abs_premium IS NOT NULL
              AND efv.liquidity_score IS NOT NULL
              AND efv.abs_premium > %s
              AND efv.liquidity_score > %s
            ORDER BY efv.abs_premium DESC
            """,
            (calc_date, cfg.trigger_threshold, cfg.min_liquidity),
        )
        rows = cur.fetchall()

    signals = []
    for row in rows:
        (etf_id, code, name, premium_rate, abs_premium,
         liquidity_score, close_price, iopv, volume, amount) = row

        if premium_rate is None or abs_premium is None:
            continue

        direction = (ArbitrageDirection.PREMIUM
                    if premium_rate > 0
                    else ArbitrageDirection.DISCOUNT)

        # 成本分解
        slippage_cost = cfg.slippage_rate * 2          # 买卖双向
        impact_cost  = cfg.impact_rate                   # 估算冲击成本
        commission_cost = cfg.commission_rate * 2        # 买卖双向
        stamp_tax_cost = cfg.stamp_tax_rate if direction == ArbitrageDirection.PREMIUM else 0  # 仅PREMIUM方向卖出ETF时收取，买入不收

        total_cost_pct = slippage_cost + impact_cost + commission_cost + stamp_tax_cost

        # 收益估算
        theoretical_gain_pct = float(abs_premium) / 100.0
        net_gain_pct = theoretical_gain_pct - total_cost_pct

        # 方向描述
        if direction == ArbitrageDirection.PREMIUM:
            signal_action = "sell_etf_buy_iopv"
        else:
            signal_action = "buy_etf_sell_iopv"

        confidence = _assess_confidence(abs_premium, liquidity_score, total_cost_pct, cfg)

        signals.append(ArbitrageSignal(
            etf_id=etf_id,
            code=code,
            name=name,
            direction=direction,
            premium_rate=float(premium_rate),
            abs_premium=float(abs_premium),
            liquidity_score=float(liquidity_score),
            trigger_threshold=cfg.trigger_threshold,
            theoretical_gain_pct=round(theoretical_gain_pct * 100, 4),
            total_cost_pct=round(total_cost_pct * 100, 4),
            net_gain_pct=round(net_gain_pct * 100, 4),
            signal_action=signal_action,
            slippage_cost=round(slippage_cost * 100, 4),
            impact_cost=round(impact_cost * 100, 4),
            commission_cost=round(commission_cost * 100, 4),
            stamp_tax_cost=round(stamp_tax_cost * 100, 4),
            confidence=confidence,
            signal_date=calc_date,
        ))

    return signals


def _assess_confidence(abs_premium: float, liquidity_score: float, total_cost_pct: float, cfg: ArbitrageConfig) -> str:
    """
    评估信号置信度。
    high:   溢价率 > 0.5% 且 流动性 > 0.8 且 净收益 > cfg.min_profit_threshold
    medium: 溢价率 > 0.3% 且 流动性 > 0.6
    low:    其他
    """
    net_gain = (float(abs_premium) / 100.0) - total_cost_pct
    if abs_premium > 0.5 and liquidity_score > 0.8 and net_gain > cfg.min_profit_threshold:
        return "high"
    elif abs_premium > 0.3 and liquidity_score > 0.6:
        return "medium"
    else:
        return "low"


# ─── 信号写入 DB ──────────────────────────────────────────────────────

def save_arbitrage_signals(conn, signals: list[ArbitrageSignal]) -> int:
    """将套利信号写入 etf_arbitrage_signals 表。"""
    written = 0
    with conn.cursor() as cur:
        for s in signals:
            cur.execute(
                """
                INSERT INTO etf_arbitrage_signals
                    (etf_id, signal_date, direction, premium_rate, abs_premium,
                     liquidity_score, theoretical_gain_pct, total_cost_pct,
                     net_gain_pct, signal_action,
                     slippage_cost, impact_cost, commission_cost, stamp_tax_cost,
                     confidence, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT (etf_id, signal_date) DO UPDATE SET
                    direction = EXCLUDED.direction,
                    premium_rate = EXCLUDED.premium_rate,
                    abs_premium = EXCLUDED.abs_premium,
                    liquidity_score = EXCLUDED.liquidity_score,
                    theoretical_gain_pct = EXCLUDED.theoretical_gain_pct,
                    total_cost_pct = EXCLUDED.total_cost_pct,
                    net_gain_pct = EXCLUDED.net_gain_pct,
                    signal_action = EXCLUDED.signal_action,
                    slippage_cost = EXCLUDED.slippage_cost,
                    impact_cost = EXCLUDED.impact_cost,
                    commission_cost = EXCLUDED.commission_cost,
                    stamp_tax_cost = EXCLUDED.stamp_tax_cost,
                    confidence = EXCLUDED.confidence
                """,
                (s.etf_id, s.signal_date, s.direction,
                 s.premium_rate, s.abs_premium,
                 s.liquidity_score, s.theoretical_gain_pct, s.total_cost_pct,
                 s.net_gain_pct, s.signal_action,
                 s.slippage_cost, s.impact_cost, s.commission_cost, s.stamp_tax_cost,
                 s.confidence),
            )
            written += 1
        conn.commit()
    return written


# ─── 主流程 ──────────────────────────────────────────────────────────────

def run_arbitrage_signal_calc(cfg: ArbitrageConfig = None) -> dict:
    """
    运行 ETF 套利信号全流程：
    1. 读取 etf_factor_values 计算日数据
    2. 生成信号（过滤 + 收益估算）
    3. 写入 etf_arbitrage_signals
    """
    import time

    if cfg is None:
        cfg = ArbitrageConfig()

    result = {"steps": {}, "signals": 0, "total_net_gain_pct": 0.0}
    today = date.today()

    conn = psycopg2.connect(pg.uri)
    try:
        t0 = time.time()
        signals = generate_arbitrage_signals(conn, today, cfg)
        result["steps"]["generate"] = {
            "signals": len(signals),
            "elapsed_s": round(time.time() - t0, 2),
        }

        if not signals:
            logger.info("今日无套利信号（无 ETF 满足触发条件）")
            result["signals"] = 0
            return result

        viable = [s for s in signals if s.net_gain_pct > cfg.min_profit_threshold * 100]
        result["steps"]["filter_profitable"] = {
            "total": len(signals),
            "profitable": len(viable),
            "min_net_gain": min(s.net_gain_pct for s in signals) if signals else 0,
            "max_net_gain": max(s.net_gain_pct for s in signals) if signals else 0,
        }

        t0 = time.time()
        written = save_arbitrage_signals(conn, viable)
        result["steps"]["save"] = {
            "written": written,
            "elapsed_s": round(time.time() - t0, 2),
        }
        result["signals"] = written
        result["total_net_gain_pct"] = round(sum(s.net_gain_pct for s in viable), 4)
        return result

    finally:
        conn.close()


# ─── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ETF 期现套利信号生成")
    parser.add_argument("--date", default=None, help="指定日期（YYYY-MM-DD），默认今日")
    parser.add_argument("--trigger", type=float, default=0.003,
                        help="触发阈值（溢价率绝对值，默认 0.003 即 0.3%%）")
    parser.add_argument("--min-liquidity", type=float, default=0.6,
                        help="最低流动性评分（默认 0.6）")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅生成信号，不写入 DB")
    args = parser.parse_args()

    calc_date = date.fromisoformat(args.date) if args.date else date.today()
    cfg = ArbitrageConfig(
        trigger_threshold=args.trigger,
        min_liquidity=args.min_liquidity,
    )

    conn = psycopg2.connect(pg.uri)
    try:
        signals = generate_arbitrage_signals(conn, calc_date, cfg)
        profitable = [s for s in signals if s.net_gain_pct > cfg.min_profit_threshold * 100]
        result = {
            "signals": len(profitable),
            "total_net_gain_pct": round(sum(s.net_gain_pct for s in profitable), 4),
            "steps": {
                "filter_profitable": {
                    "total": len(signals),
                    "profitable": len(profitable),
                    "min_net_gain": min(s.net_gain_pct for s in signals) if signals else 0,
                    "max_net_gain": max(s.net_gain_pct for s in signals) if signals else 0,
                }
            },
        }
    finally:
        conn.close()

    print("\n" + "=" * 60)
    print("  ETF 期现套利信号报告")
    print("=" * 60)
    print(f"\n计算日期: {calc_date}  |  触发阈值: {args.trigger*100:.2f}%  |  最低流动性: {args.min_liquidity}")
    print(f"信号数量: {result['signals']}")

    if result.get("steps", {}).get("filter_profitable"):
        fp = result["steps"]["filter_profitable"]
        print(f"  总触发: {fp['total']}  →  盈利过滤后: {fp['profitable']}")
        print(f"  净收益率范围: {fp['min_net_gain']:.4f}% ~ {fp['max_net_gain']:.4f}%")

    if result["signals"] > 0:
        print(f"\n套利信号详情 ({len(profitable)} 条):")
        for s in profitable:
            emoji = "📈" if s.direction == ArbitrageDirection.PREMIUM else "📉"
            print(f"  {emoji} {s.code} ({s.name})")
            print(f"     溢价率: {s.premium_rate:+.3f}%  |  流动性: {s.liquidity_score:.3f}")
            print(f"     理论收益: {s.theoretical_gain_pct:.4f}%  |  成本: {s.total_cost_pct:.4f}%  |  净收益: {s.net_gain_pct:.4f}%")
            print(f"     置信度: {s.confidence}  |  操作: {s.signal_action}")

    print(f"\n结论: {'✅ 发现套利机会' if result['signals'] > 0 else '⚪ 无套利机会'}")