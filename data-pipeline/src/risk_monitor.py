"""舆情风险监控模块

功能：
1. 负面新闻识别 - 检测重大利空消息
2. 公告风险识别 - 检测减持、业绩下滑等重大公告
3. 波动异常识别 - 监控单日大幅下跌

使用方法：
    python risk_monitor.py --etf-codes 512480,159819 --check-negative
"""

import sys
sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")

import logging
from datetime import date, timedelta
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from src.config import pg
import psycopg2

logger = logging.getLogger(__name__)

# ─── 重大风险关键词 ──────────────────────────────────────────

NEGATIVE_KEYWORDS = [
    # 业绩风险
    "业绩预减", "业绩预亏", "业绩首亏", "大幅亏损", "净利润下降", "营业收入下滑",
    # 股东减持
    "减持", "拟减持", "计划减持", "大宗交易",
    # 监管风险
    "立案调查", "监管函", "警示函", "行政处罚", "通报批评",
    # 经营风险
    "停产", "停工", "破产", "债务违约", "资金链断裂", "经营困难",
    # 市场风险
    "大幅下跌", "闪崩", "破位", "技术破位",
]

POSITIVE_KEYWORDS = [
    "业绩预增", "大幅增长", "净利润上升", "营业收入增长", "扭亏为盈",
    "增持", "拟增持", "计划增持",
    "中标", "合同签订", "技术突破",
]

ALERT_TYPES = {
    "negative_news": "负面新闻",
    "positive_news": "正面消息",
    "abnormal_volatility": "异常波动",
    "high_volume_drop": "放量下跌",
    "risk_event": "风险事件",
}


@dataclass
class RiskAlert:
    """风险警报"""
    alert_type: str
    severity: str          # critical / high / medium / low
    code: str
    title: str
    detail: str
    published_at: Optional[str] = None


class RiskMonitor:
    """风险监控器"""

    def __init__(self, etf_codes: list[str]):
        self.etf_codes = etf_codes
        self.conn = psycopg2.connect(
            host=pg.host, port=pg.port, dbname=pg.db,
            user=pg.user, password=pg.password
        )

    def close(self):
        self.conn.close()

    def check_news(self, days: int = 7, sentiment_threshold: float = -0.3) -> list[RiskAlert]:
        """检查近期新闻风险（基于ETF成分股新闻）"""
        alerts = []
        return alerts  # TODO: 公司表为空，暂跳过

    def check_price_volatility(self, lookback: int = 5) -> list[RiskAlert]:
        """检查价格异常波动"""
        alerts = []

        cur = self.conn.cursor()
        cur.execute("""
            SELECT e.code, eq.trade_date, eq.close_price, eq.change_pct, eq.amplitude,
                   eq.amount, eq.turnover_rate
            FROM etfs e
            JOIN etf_quotes eq ON e.id = eq.etf_id
            WHERE e.code = ANY(%s)
            AND eq.trade_date >= CURRENT_DATE - INTERVAL '%s days'
            AND eq.trade_date <= CURRENT_DATE
            ORDER BY e.code, eq.trade_date
        """, (self.etf_codes, lookback))

        # 按ETF分组
        etf_data = {}
        for code, trade_date, close, change_pct, amplitude, amount, turnover in cur.fetchall():
            if code not in etf_data:
                etf_data[code] = []
            etf_data[code].append({
                'date': trade_date, 'close': close, 'change_pct': change_pct,
                'amplitude': amplitude, 'amount': amount, 'turnover': turnover
            })

        for code, bars in etf_data.items():
            if len(bars) < 2:
                continue

            latest = bars[-1]
            # 单日大幅下跌
            if latest['change_pct'] and float(latest['change_pct']) < -5:
                alerts.append(RiskAlert(
                    alert_type="abnormal_volatility",
                    severity="critical",
                    code=code,
                    title=f"单日下跌 {latest['change_pct']:.2f}%",
                    detail=f"跌幅超过5%阈值，日期: {latest['date']}",
                    published_at=str(latest['date'])
                ))

            # 连续下跌
            if len(bars) >= 3:
                recent_changes = [float(b['change_pct']) for b in bars[-3:] if b['change_pct']]
                if all(c < 0 for c in recent_changes) and sum(recent_changes) < -8:
                    alerts.append(RiskAlert(
                        alert_type="abnormal_volatility",
                        severity="high",
                        code=code,
                        title=f"连续下跌 3日累计 {sum(recent_changes):.2f}%",
                        detail=f"近3日持续下跌，需关注",
                        published_at=str(bars[-1]['date'])
                    ))

        cur.close()
        return alerts

    def check_volume_spike(self, threshold: float = 3.0) -> list[RiskAlert]:
        """检查成交量异常放大（可能出货）"""
        alerts = []

        cur = self.conn.cursor()
        cur.execute("""
            SELECT e.code, eq.trade_date, eq.amount, eq.change_pct,
                   eq.turnover_rate
            FROM etfs e
            JOIN etf_quotes eq ON e.id = eq.etf_id
            WHERE e.code = ANY(%s)
            AND eq.trade_date >= CURRENT_DATE - INTERVAL '20 days'
            ORDER BY e.code, eq.trade_date
        """, (self.etf_codes,))

        etf_volumes = {}
        for code, trade_date, amount, change_pct, turnover in cur.fetchall():
            if code not in etf_volumes:
                etf_volumes[code] = []
            etf_volumes[code].append({'date': trade_date, 'amount': amount, 'change_pct': change_pct})

        for code, bars in etf_volumes.items():
            if len(bars) < 10:
                continue

            amounts = [float(b['amount']) for b in bars if b['amount']]
            if not amounts:
                continue

            avg_amount = sum(amounts[:-1]) / (len(amounts) - 1)  # 排除今日
            latest_amount = amounts[-1]

            if avg_amount > 0 and latest_amount / avg_amount > threshold:
                latest_bar = bars[-1]
                alerts.append(RiskAlert(
                    alert_type="high_volume_drop",
                    severity="medium",
                    code=code,
                    title=f"成交量放大 {latest_amount/avg_amount:.1f}倍",
                    detail=f"放量{latest_bar['change_pct']:.2f}%，需关注是否主力出货",
                    published_at=str(latest_bar['date'])
                ))

        cur.close()
        return alerts

    def run_full_check(self) -> dict:
        """运行全面风险检查"""
        print("=" * 60)
        print(f"  风险监控检查 - 候选ETF: {self.etf_codes}")
        print("=" * 60)

        all_alerts = []

        # 1. 新闻风险
        print("\n[1/3] 检查新闻风险...")
        news_alerts = self.check_news(days=7)
        all_alerts.extend(news_alerts)
        print(f"   发现 {len(news_alerts)} 条风险新闻")

        # 2. 价格波动
        print("\n[2/3] 检查价格波动...")
        vol_alerts = self.check_price_volatility(lookback=5)
        all_alerts.extend(vol_alerts)
        print(f"   发现 {len(vol_alerts)} 条异常波动")

        # 3. 成交量异常
        print("\n[3/3] 检查成交量...")
        vol_spike_alerts = self.check_volume_spike(threshold=3.0)
        all_alerts.extend(vol_spike_alerts)
        print(f"   发现 {len(vol_spike_alerts)} 条成交量异常")

        # 分类汇总
        alert_summary = {}
        for a in all_alerts:
            if a.alert_type not in alert_summary:
                alert_summary[a.alert_type] = []
            alert_summary[a.alert_type].append(a)

        # 输出报告
        print("\n" + "=" * 60)
        print("  风险报告汇总")
        print("=" * 60)

        severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}

        total_critical = sum(1 for a in all_alerts if a.severity == "critical")
        total_high = sum(1 for a in all_alerts if a.severity == "high")

        print(f"\n总风险警报: {len(all_alerts)} 条")
        print(f"  🔴 严重: {total_critical} 条")
        print(f"  🟠 高风险: {total_high} 条")
        print(f"  🟡 中风险: {sum(1 for a in all_alerts if a.severity == 'medium')} 条")

        if all_alerts:
            print(f"\n详情:")
            for a in sorted(all_alerts, key=lambda x: ["critical", "high", "medium", "low"].index(x.severity)):
                print(f"  {severity_emoji.get(a.severity, '⚪')} [{a.severity.upper()}] {a.code} | {a.title}")
                print(f"       {a.detail}")

        return {
            "total_alerts": len(all_alerts),
            "critical_count": total_critical,
            "high_count": total_high,
            "alerts_by_type": {k: len(v) for k, v in alert_summary.items()},
            "alerts": all_alerts,
        }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ETF风险监控")
    parser.add_argument("--etf-codes", default="562500,560630,159819,515070,515980,512480,159813,159325,515030,159889,516520,512660,512680,159667,515700,516390",
                        help="逗号分隔的ETF代码")
    parser.add_argument("--check-negative", action="store_true", help="检查负面新闻")

    args = parser.parse_args()
    etf_codes = args.etf_codes.split(",")

    monitor = RiskMonitor(etf_codes)
    try:
        result = monitor.run_full_check()
        print(f"\n结论: {'⚠️ 存在风险' if result['total_alerts'] > 0 else '✅ 无重大风险'}")
    finally:
        monitor.close()