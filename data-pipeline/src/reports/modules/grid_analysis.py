"""
网格信号计算引擎 v1.0（2026-06-12）

基于双重自适应间距设计：
  - 第一层：估值区间间距（价格位置驱动）
  - 第二层：CV修正系数（波动率感知）

数据来源：PG etf_quotes（252日窗口）
输出：网格信号（价格位置 / 间距 / 操作建议）
"""
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import date

from loader.pg import get_conn

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# 估值区间间距（第一层）
# ─────────────────────────────────────────
ZONE_GRID = {
    "极低":   {"threshold_low": None,   "threshold_high": 0.85,  "base_spacing": 0.12, "signal": "🟢极低估值", "action": "强烈买入"},
    "低":     {"threshold_low": 0.85,   "threshold_high": 0.90,  "base_spacing": 0.08, "signal": "🟢低估值",    "action": "买入"},
    "偏低":   {"threshold_low": 0.90,   "threshold_high": 0.95,  "base_spacing": 0.06, "signal": "🟡偏低",     "action": "少量买入"},
    "中性":   {"threshold_low": 0.95,   "threshold_high": 1.05,  "base_spacing": 0.05, "signal": "⚪中性",     "action": "观望"},
    "偏高":   {"threshold_low": 1.05,   "threshold_high": 1.10,  "base_spacing": 0.06, "signal": "🟡偏高",     "action": "少量卖出"},
    "高":     {"threshold_low": 1.10,   "threshold_high": 1.15,  "base_spacing": 0.08, "signal": "🔴高估值",   "action": "卖出"},
    "极高":   {"threshold_low": 1.15,   "threshold_high": None,   "base_spacing": 0.10, "signal": "🔴极高估值", "action": "强烈卖出"},
}

# CV修正系数（第二层）
CV_CORRECTION = {
    "high":   {"cv_min": 0.25, "spacing_floor": 0.08},
    "mid":    {"cv_min": 0.15, "spacing_floor": 0.05},
    "low":    {"cv_min": 0.00, "spacing_floor": 0.04},
}


@dataclass
class GridSignal:
    code: str
    name: str
    category: str
    latest_price: float
    mean_252d: float
    std_252d: float
    deviation_pct: float
    cv_pct: float
    zone: str
    base_spacing: float
    cv_spacing_floor: float
    final_spacing_pct: float
    signal: str
    action: str
    grid_lower: float
    grid_upper: float
    status: str  # ok / warning / exclude


def _get_cv_bucket(cv_pct: float) -> str:
    if cv_pct >= 25:
        return "high"
    elif cv_pct >= 15:
        return "mid"
    return "low"


def _get_zone_and_base_spacing(deviation_pct: float) -> Tuple[str, float]:
    for zone_name, zone in ZONE_GRID.items():
        low = zone["threshold_low"]
        high = zone["threshold_high"]
        if low is not None and deviation_pct < low:
            continue
        if high is not None and deviation_pct >= high:
            continue
        return zone_name, zone["base_spacing"]
    return ("极低", ZONE_GRID["极低"]["base_spacing"]) if deviation_pct < 0 else ("极高", ZONE_GRID["极高"]["base_spacing"])


def compute_grid_signal(
    code: str, name: str, category: str,
    latest_price: float, mean_252d: float, std_252d: float,
) -> GridSignal:
    deviation_pct = (latest_price - mean_252d) / mean_252d * 100 if mean_252d != 0 else 0.0
    cv_pct = (std_252d / mean_252d * 100) if mean_252d != 0 else 0.0

    zone, base_spacing = _get_zone_and_base_spacing(deviation_pct)
    bucket = _get_cv_bucket(cv_pct)
    cv_spacing_floor = CV_CORRECTION[bucket]["spacing_floor"]
    final_spacing_pct = max(base_spacing, cv_spacing_floor) * 100

    zone_info = ZONE_GRID[zone]
    grid_lower = mean_252d * (1 - final_spacing_pct / 100)
    grid_upper = mean_252d * (1 + final_spacing_pct / 100)

    status = "exclude" if code == "512930" else ("warning" if abs(deviation_pct) > 50 else "ok")

    return GridSignal(
        code=code, name=name, category=category,
        latest_price=latest_price, mean_252d=mean_252d, std_252d=std_252d,
        deviation_pct=round(deviation_pct, 2), cv_pct=round(cv_pct, 2),
        zone=zone,
        base_spacing=round(base_spacing * 100, 1),
        cv_spacing_floor=round(cv_spacing_floor * 100, 1),
        final_spacing_pct=round(final_spacing_pct, 2),
        signal=zone_info["signal"], action=zone_info["action"],
        grid_lower=round(grid_lower, 4), grid_upper=round(grid_upper, 4),
        status=status,
    )


def load_etf_pool() -> List[Dict]:
    with get_conn() as conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT code, name, category FROM etfs
                WHERE code IN ('159393','512500','562500','512480',
                               '512170','512690','512930','512800','159618')
                ORDER BY category, code
            """)
            return [{"code": r[0], "name": r[1], "category": r[2]} for r in cur.fetchall()]
        finally:
            conn.close()


def load_etf_stats(code: str, lookback: int = 252) -> Optional[Dict]:
    """通过 etfs.code 找到 etfs.id，再查 etf_quotes.etf_id"""
    with get_conn() as conn:
        try:
            cur = conn.cursor()
            # 先把6位代码转成数字id
            cur.execute("SELECT id FROM etfs WHERE code = %s", (code,))
            row = cur.fetchone()
            if not row:
                return None
            etf_id = row[0]
            # 再查行情
            cur.execute(f"""
                SELECT close_price FROM etf_quotes
                WHERE etf_id = %s ORDER BY trade_date DESC LIMIT {lookback}
            """, (etf_id,))
            rows = cur.fetchall()
            if not rows:
                return None
            prices = [float(r[0]) for r in rows]
            n = len(prices)
            mean = sum(prices) / n
            var = sum((p - mean) ** 2 for p in prices) / n
            return {"latest_price": prices[0], "mean_252d": mean, "std_252d": var ** 0.5, "window": n}
        finally:
            conn.close()


def compute_all_grid_signals(exclude_codes: List[str] = None) -> List[GridSignal]:
    if exclude_codes is None:
        exclude_codes = []
    pool = load_etf_pool()
    signals = []
    for etf in pool:
        code = etf["code"]
        if code in exclude_codes:
            logger.info(f"排除 {code}（{etf['name']}）")
            continue
        stats = load_etf_stats(code, lookback=252)
        if not stats:
            logger.warning(f"{code} 无足够数据，跳过")
            continue
        sig = compute_grid_signal(code, etf["name"], etf["category"],
                                  stats["latest_price"], stats["mean_252d"], stats["std_252d"])
        signals.append(sig)
        logger.info(f"网格信号 {code}: {sig.deviation_pct:+.2f}%, CV={sig.cv_pct:.1f}%, 间距={sig.final_spacing_pct:.1f}%, {sig.signal}")
    signals.sort(key=lambda s: s.deviation_pct)
    return signals


def signals_to_markdown(signals: List[GridSignal], trade_date: str = None) -> str:
    td = trade_date or date.today().strftime("%Y-%m-%d")
    lines = [
        f"■ 网格信号（{td}）",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"标的              当前价   1年均值    偏离%    CV%   间距%  信号",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for s in signals:
        extra = " ⚠️排除" if s.status == "exclude" else (" ⚠️" if s.status == "warning" else "")
        lines.append(
            f"{s.name:8s}({s.code}) {s.latest_price:.4f} {s.mean_252d:.4f} "
            f"{s.deviation_pct:+7.2f}% {s.cv_pct:5.1f}% {s.final_spacing_pct:5.1f}%  {s.signal}{extra}"
        )
    lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    green = [s for s in signals if "🟢" in s.signal]
    yellow = [s for s in signals if "🟡" in s.signal]
    red = [s for s in signals if "🔴" in s.signal]
    parts = []
    if green: parts.append(f"🟢极低/低估：{', '.join(s.code for s in green)}")
    if yellow: parts.append(f"🟡中性/偏：{', '.join(s.code for s in yellow)}")
    if red: parts.append(f"🔴高估/极高：{', '.join(s.code for s in red)}")
    if parts:
        lines.append("；".join(parts))
    lines.append("")
    lines.append("解读（按双层自适应规则）：")
    for s in signals:
        lines.append(f"- {s.name}({s.code}): {s.deviation_pct:+.2f}% vs 1年均值 → {s.signal}（间距{s.final_spacing_pct:.1f}%，{s.action}）")
    return "\n".join(lines)


POSITION_LIMITS = {
    "max_single_etf_pct": 0.20,
    "max_total_position_pct": 0.80,
    "max_drawdown_stop": -0.10,
    "min_cash_reserve_pct": 0.20,
}


def check_position_constraints(signals: List[GridSignal], current_positions: Dict[str, float]) -> Dict:
    cash_ratio = 1.0 - sum(current_positions.values())
    violations = []
    if cash_ratio < POSITION_LIMITS["min_cash_reserve_pct"]:
        violations.append(f"现金比例{cash_ratio:.1%}<最低{POSITION_LIMITS['min_cash_reserve_pct']:.0%}")
    for sig in signals:
        if sig.code in current_positions and current_positions[sig.code] > POSITION_LIMITS["max_single_etf_pct"]:
            violations.append(f"{sig.code}持仓{current_positions[sig.code]:.1%}>单ETF上限{POSITION_LIMITS['max_single_etf_pct']:.0%}")
    total_pos = sum(current_positions.values())
    if total_pos > POSITION_LIMITS["max_total_position_pct"]:
        violations.append(f"总仓位{total_pos:.1%}>上限{POSITION_LIMITS['max_total_position_pct']:.0%}")
    return {"can_buy": len(violations) == 0, "violations": violations,
            "cash_ratio": round(cash_ratio, 4), "total_position_pct": round(total_pos, 4)}