"""
ETF财务健康监控 - 基于实时行情计算财务指标

覆盖：
1. IOPV溢价率监控 - 检测折溢价异常（重大利空/利好信号）
2. 流动性健康 - 换手率/成交额/主力资金
3. 波动率健康 - 历史波动率与行业均值对比

数据来源：
- akshare fund_etf_spot_em() 实时行情（每15分钟刷新）
- etf_quotes 历史K线（已有数据）
"""

import sys
sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")

import logging
from datetime import date, timedelta, datetime
from dataclasses import dataclass
from typing import Optional
import numpy as np

import pandas as pd
import akshare as ak
import psycopg2
from psycopg2.extras import execute_values

from src.config import pg

logger = logging.getLogger(__name__)

# ─── 风险阈值常量 ──────────────────────────────────────────

IOPV_WARNING_THRESHOLD = 1.0     # IOPV折溢价超过±1% 警告
IOPV_CRITICAL_THRESHOLD = 2.0   # IOPV折溢价超过±2% 严重

TURNOVER_RATE_MIN = 0.001       # 换手率低于0.1% 警告（流动性枯竭）
NET_FLOW_INFLOW = 1_000_000_000  # 单日净流入超过10亿 重大信号
NET_FLOW_OUTFLOW = -1_000_000_000 # 单日净流出超过10亿 重大信号


@dataclass
class ETFHealthAlert:
    """ETF健康警报"""
    code: str
    name: str
    metric: str           # iopv_deviation / turnover_rate / volume_spike / money_flow / volatility
    risk_level: str       # normal / warning / critical
    value: float
    threshold: float
    detail: str
    signal_type: str      # positive / negative / warning
    calc_date: date


class ETFHealthMonitor:
    """ETF财务健康监控器"""

    def __init__(self, etf_codes: Optional[list[str]] = None):
        self.etf_codes = etf_codes
        self.conn = psycopg2.connect(
            host=pg.host, port=pg.port, dbname=pg.db,
            user=pg.user, password=pg.password
        )
        self.alerts: list[ETFHealthAlert] = []

    def close(self):
        self.conn.close()

    def fetch_realtime_data(self) -> pd.DataFrame:
        """从AKShare获取ETF实时行情（包含IOPV/溢价率/主力资金等）"""
        logger.info("获取ETF实时行情...")
        df = ak.fund_etf_spot_em()

        if self.etf_codes:
            df = df[df['代码'].isin(self.etf_codes)].copy()
        else:
            df = df.copy()

        df = df.rename(columns={
            '代码': 'code', '名称': 'name', '最新价': 'latest_price',
            'IOPV实时估值': 'iopv', '基金折价率': 'premium_rate',
            '涨跌幅': 'change_pct', '换手率': 'turnover_rate',
            '成交量': 'volume', '成交额': 'amount',
            '主力净流入-净额': 'main_net_flow',
            '主力净流入-净占比': 'main_net_flow_pct',
            '最新份额': 'shares', '流通市值': 'flow_market_cap',
            '数据日期': 'data_date',
        })

        for col in ['latest_price', 'iopv', 'premium_rate', 'change_pct', 'turnover_rate',
                    'volume', 'amount', 'main_net_flow', 'main_net_flow_pct']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        logger.info(f"获取到 {len(df)} 只ETF实时数据")
        return df

    def compute_iopv_alerts(self, realtime_df: pd.DataFrame) -> list[ETFHealthAlert]:
        """计算IOPV折溢价警报"""
        alerts = []

        for _, row in realtime_df.iterrows():
            if pd.isna(row.get('iopv')) or pd.isna(row.get('latest_price')) or row.get('iopv', 0) <= 0:
                continue

            code = str(row.get('code', ''))
            name = str(row.get('name', ''))
            iopv = float(row['iopv'])
            latest_price = float(row['latest_price'])

            premium_pct = (latest_price - iopv) / iopv * 100

            if abs(premium_pct) >= IOPV_CRITICAL_THRESHOLD:
                level = "critical"
                detail = f"IOPV溢价率 {premium_pct:.2f}% (超过±{IOPV_CRITICAL_THRESHOLD}%阈值)"
            elif abs(premium_pct) >= IOPV_WARNING_THRESHOLD:
                level = "warning"
                detail = f"IOPV溢价率 {premium_pct:.2f}% (超过±{IOPV_WARNING_THRESHOLD}%阈值)"
            else:
                continue

            signal_type = "negative" if premium_pct < 0 else "positive"

            alerts.append(ETFHealthAlert(
                code=code, name=name, metric="iopv_deviation",
                risk_level=level, value=premium_pct,
                threshold=IOPV_WARNING_THRESHOLD if level == "warning" else IOPV_CRITICAL_THRESHOLD,
                detail=detail, signal_type=signal_type, calc_date=date.today()
            ))

        return alerts

    def compute_liquidity_alerts(self, realtime_df: pd.DataFrame) -> list[ETFHealthAlert]:
        """计算流动性警报"""
        alerts = []

        for _, row in realtime_df.iterrows():
            code = str(row.get('code', ''))
            name = str(row.get('name', ''))
            turnover_rate = float(row.get('turnover_rate') or 0)
            main_net_flow = float(row.get('main_net_flow') or 0)

            if 0 < turnover_rate < TURNOVER_RATE_MIN * 100:
                alerts.append(ETFHealthAlert(
                    code=code, name=name, metric="turnover_rate",
                    risk_level="warning", value=turnover_rate,
                    threshold=TURNOVER_RATE_MIN * 100,
                    detail=f"换手率 {turnover_rate:.3f}% 过低，流动性枯竭风险",
                    signal_type="warning", calc_date=date.today()
                ))

            if main_net_flow < NET_FLOW_OUTFLOW:
                alerts.append(ETFHealthAlert(
                    code=code, name=name, metric="money_flow",
                    risk_level="critical", value=main_net_flow,
                    threshold=NET_FLOW_OUTFLOW,
                    detail=f"主力净流出 {abs(main_net_flow)/1e8:.1f}亿",
                    signal_type="negative", calc_date=date.today()
                ))
            elif main_net_flow > NET_FLOW_INFLOW:
                alerts.append(ETFHealthAlert(
                    code=code, name=name, metric="money_flow",
                    risk_level="warning", value=main_net_flow,
                    threshold=NET_FLOW_INFLOW,
                    detail=f"主力净流入 {main_net_flow/1e8:.1f}亿",
                    signal_type="positive", calc_date=date.today()
                ))

        return alerts

    def compute_volatility_alerts(self) -> list[ETFHealthAlert]:
        """计算波动率异常警报"""
        alerts = []
        cur = self.conn.cursor()

        try:
            if self.etf_codes:
                code_list = tuple(self.etf_codes)
                sql = """
                WITH daily_returns AS (
                    SELECT e.code, e.name,
                           eq.close_price / lag(eq.close_price) OVER (PARTITION BY e.code ORDER BY eq.trade_date) - 1 as daily_ret
                    FROM etfs e
                    JOIN etf_quotes eq ON e.id = eq.etf_id
                    WHERE e.code IN %s
                    AND eq.trade_date >= CURRENT_DATE - INTERVAL '20 days'
                    AND eq.trade_date <= CURRENT_DATE
                ),
                vol_stats AS (
                    SELECT code, name, stddev(daily_ret) as daily_vol
                    FROM daily_returns
                    GROUP BY code, name
                )
                SELECT code, name, daily_vol FROM vol_stats
                """
                cur.execute(sql, (code_list,))
            else:
                sql = """
                WITH daily_returns AS (
                    SELECT e.code, e.name,
                           eq.close_price / lag(eq.close_price) OVER (PARTITION BY e.code ORDER BY eq.trade_date) - 1 as daily_ret
                    FROM etfs e
                    JOIN etf_quotes eq ON e.id = eq.etf_id
                    WHERE eq.trade_date >= CURRENT_DATE - INTERVAL '20 days'
                    AND eq.trade_date <= CURRENT_DATE
                ),
                vol_stats AS (
                    SELECT code, name, stddev(daily_ret) as daily_vol
                    FROM daily_returns
                    GROUP BY code, name
                )
                SELECT code, name, daily_vol FROM vol_stats
                """
                cur.execute(sql)

            rows = cur.fetchall()
            vols = [(r[0], r[1], r[2]) for r in rows if r[2] is not None and r[2] > 0]
            if not vols:
                return alerts

            avg_vol = np.mean([v[2] for v in vols])
            vol_std = np.std([v[2] for v in vols])
            threshold_high = avg_vol + 2 * vol_std

            for code, name, daily_vol in vols:
                if daily_vol > threshold_high:
                    alerts.append(ETFHealthAlert(
                        code=code, name=name, metric="volatility",
                        risk_level="warning", value=daily_vol,
                        threshold=threshold_high,
                        detail=f"波动率 {daily_vol*100:.2f}% 超过阈值 {threshold_high*100:.2f}% (均值+2σ)",
                        signal_type="warning", calc_date=date.today()
                    ))
        except Exception as e:
            logger.warning(f"波动率计算失败: {e}")
        finally:
            cur.close()

        return alerts

    def compute_money_flow_alerts(self, realtime_df: pd.DataFrame) -> list[ETFHealthAlert]:
        """计算资金流向警报（主力净流入占比）"""
        alerts = []

        for _, row in realtime_df.iterrows():
            code = str(row.get('code', ''))
            name = str(row.get('name', ''))
            main_net_pct = float(row.get('main_net_flow_pct', 0) or 0)

            if abs(main_net_pct) >= 5.0:
                signal = "positive" if main_net_pct > 0 else "negative"
                level = "critical" if abs(main_net_pct) >= 8.0 else "warning"
                alerts.append(ETFHealthAlert(
                    code=code, name=name, metric="money_flow_ratio",
                    risk_level=level, value=main_net_pct,
                    threshold=5.0,
                    detail=f"主力净流入占比 {main_net_pct:.2f}% ({'净流入' if main_net_pct > 0 else '净流出'})",
                    signal_type=signal, calc_date=date.today()
                ))

        return alerts

    def run_full_check(self) -> dict:
        """运行全面健康检查"""
        logger.info("=" * 60)
        logger.info(f"ETF财务健康检查 - 日期: {date.today()}")
        logger.info("=" * 60)

        all_alerts = []

        try:
            realtime_df = self.fetch_realtime_data()
        except Exception as e:
            logger.error(f"获取实时行情失败: {e}")
            return {"error": str(e), "total_alerts": 0}

        logger.info("\n[1/4] IOPV折溢价检查...")
        iopv_alerts = self.compute_iopv_alerts(realtime_df)
        all_alerts.extend(iopv_alerts)
        logger.info(f"   发现 {len(iopv_alerts)} 条IOPV警报")

        logger.info("\n[2/4] 流动性检查...")
        liq_alerts = self.compute_liquidity_alerts(realtime_df)
        all_alerts.extend(liq_alerts)
        logger.info(f"   发现 {len(liq_alerts)} 条流动性警报")

        logger.info("\n[3/4] 波动率检查...")
        vol_alerts = self.compute_volatility_alerts()
        all_alerts.extend(vol_alerts)
        logger.info(f"   发现 {len(vol_alerts)} 条波动率警报")

        logger.info("\n[4/4] 资金流向检查...")
        flow_alerts = self.compute_money_flow_alerts(realtime_df)
        all_alerts.extend(flow_alerts)
        logger.info(f"   发现 {len(flow_alerts)} 条资金流向警报")

        # 分类汇总
        alert_by_type = {
            "iopv_deviation": [a for a in all_alerts if a.metric == "iopv_deviation"],
            "liquidity": [a for a in all_alerts if a.metric in ("turnover_rate", "volume_spike")],
            "volatility": [a for a in all_alerts if a.metric == "volatility"],
            "money_flow": [a for a in all_alerts if a.metric in ("money_flow", "money_flow_ratio")],
        }

        print("\n" + "=" * 60)
        print(f"  ETF财务健康检查报告 - {date.today()}")
        print("=" * 60)

        total_critical = sum(1 for a in all_alerts if a.risk_level == "critical")
        total_warning = sum(1 for a in all_alerts if a.risk_level == "warning")
        total_negative = sum(1 for a in all_alerts if a.signal_type == "negative")
        total_positive = sum(1 for a in all_alerts if a.signal_type == "positive")

        print(f"\n总警报数: {len(all_alerts)} 条")
        print(f"  🔴 严重: {total_critical} 条")
        print(f"  🟡 警告: {total_warning} 条")
        print(f"  📉 负面信号: {total_negative} 条")
        print(f"  📈 正面信号: {total_positive} 条")

        if all_alerts:
            print(f"\n🔍 警报详情 (显示前30条):")
            for a in sorted(all_alerts, key=lambda x: ["critical", "warning"].index(x.risk_level))[:30]:
                emoji = "🔴" if a.risk_level == "critical" else "🟡"
                sign = "📉" if a.signal_type == "negative" else "📈" if a.signal_type == "positive" else "⚠️"
                print(f"  {emoji}{sign} [{a.risk_level.upper()}] {a.code} {a.name}")
                print(f"       {a.detail}")

        self.save_alerts(all_alerts)

        if total_critical > 0:
            conclusion = f"⚠️ 存在 {total_critical} 条严重警报，需立即关注"
        elif total_warning > 0:
            conclusion = f"⚡ 存在 {total_warning} 条警告，建议关注"
        elif total_positive > 0:
            conclusion = f"✅ 健康，存在 {total_positive} 条正面信号"
        else:
            conclusion = "✅ 全部ETF财务指标正常"

        print(f"\n结论: {conclusion}")

        return {
            "calc_date": str(date.today()),
            "total_alerts": len(all_alerts),
            "critical_count": total_critical,
            "warning_count": total_warning,
            "negative_count": total_negative,
            "positive_count": total_positive,
            "alerts_by_type": {k: len(v) for k, v in alert_by_type.items()},
            "alerts": [
                {"code": a.code, "name": a.name, "metric": a.metric,
                 "risk_level": a.risk_level, "value": a.value,
                 "detail": a.detail, "signal_type": a.signal_type}
                for a in all_alerts
            ],
            "conclusion": conclusion,
        }

    def save_alerts(self, alerts: list[ETFHealthAlert]):
        """保存警报到数据库"""
        if not alerts:
            return

        cur = self.conn.cursor()
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS etf_health_alerts (
                    id SERIAL PRIMARY KEY,
                    calc_date DATE NOT NULL,
                    code VARCHAR(10) NOT NULL,
                    name VARCHAR(100),
                    metric VARCHAR(30),
                    risk_level VARCHAR(10),
                    alert_value NUMERIC,
                    threshold_value NUMERIC,
                    detail TEXT,
                    signal_type VARCHAR(10),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(calc_date, code, metric)
                )
            """)

            values = [
                (a.calc_date, a.code, a.name, a.metric,
                 a.risk_level, a.value, a.threshold,
                 a.detail, a.signal_type)
                for a in alerts
            ]
            execute_values(
                cur,
                """
                INSERT INTO etf_health_alerts
                    (calc_date, code, name, metric, risk_level, alert_value, threshold_value, detail, signal_type)
                VALUES %s
                ON CONFLICT (calc_date, code, metric)
                DO UPDATE SET
                    risk_level = EXCLUDED.risk_level,
                    alert_value = EXCLUDED.alert_value,
                    detail = EXCLUDED.detail,
                    signal_type = EXCLUDED.signal_type
                """,
                values
            )
            self.conn.commit()
            logger.info(f"保存 {len(alerts)} 条告警到数据库")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"保存告警失败: {e}")
        finally:
            cur.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ETF财务健康检查")
    parser.add_argument("--etf-codes", default=None, help="逗号分隔的ETF代码，None表示全部")
    args = parser.parse_args()

    etf_codes = args.etf_codes.split(",") if args.etf_codes else None

    monitor = ETFHealthMonitor(etf_codes=etf_codes)
    try:
        result = monitor.run_full_check()
        print(f"\n返回结果: {result['conclusion']}")
    finally:
        monitor.close()