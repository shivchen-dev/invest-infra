"""财报数据采集器 — 通过 akshare 获取 A 股财务报告

akshare stock_financial_abstract 返回格式:
  行=指标(如"归母净利润"), 列=报告期(如"20260331"), 值=指标数值
  需要转置为: 每个报告期一行
"""

import logging
from datetime import datetime
from typing import Optional

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)


def _report_type_from_date(date_str: str) -> str:
    """根据日期判断财报类型: Q1/Q2/Q3/annual"""
    if not date_str:
        return ""
    s = str(date_str)
    mm = s[4:6]
    if mm in ("03", "04"):
        return "Q1"
    elif mm in ("06", "07"):
        return "Q2"
    elif mm in ("09", "10"):
        return "Q3"
    else:
        return "annual"


def fetch_financial_report(stock_code: str) -> list[dict]:
    """获取单只股票的财报摘要数据，返回 list[dict] 每期一条"""
    raw_code = stock_code.split(".")[0]
    logger.info(f"正在获取 {raw_code} 财报 ...")

    try:
        df = ak.stock_financial_abstract(symbol=raw_code)
    except Exception as e:
        logger.warning(f"{raw_code} 财报获取失败: {e}")
        return []

    if df is None or df.empty:
        return []

    # 转置: 将指标列转为行，日期列转为记录
    dates = [c for c in df.columns if c not in ("选项", "指标")]
    metrics = dict(zip(df["指标"], range(len(df))))

    records = []
    for d in dates:
        try:
            report_date = datetime.strptime(str(d)[:8], "%Y%m%d").date()
        except (ValueError, IndexError):
            continue

        fiscal_year = report_date.year
        report_type = _report_type_from_date(str(d))
        if not report_type:
            continue

        def _val(metric_name: str) -> Optional[float]:
            idx = metrics.get(metric_name)
            if idx is None:
                return None
            v = df.iloc[idx][d]
            try:
                return float(v) if pd.notna(v) else None
            except (ValueError, TypeError):
                return None

        records.append({
            "stock_code": stock_code,
            "report_date": report_date,
            "report_type": report_type,
            "fiscal_year": fiscal_year,
            "revenue":        _val("营业总收入"),
            "cost_of_sales":  _val("营业成本"),
            "gross_profit":   _val("毛利"),
            "net_profit":     _val("净利润"),
            "parent_net_profit": _val("归母净利润"),
            "total_assets":   _val("总资产"),
            "total_liabilities": _val("总负债"),
            "total_equity":   _val("股东权益合计(净资产)"),
            "operating_cf":   _val("经营现金流量净额"),
            "source": "akshare",
        })

    records.sort(key=lambda r: r["report_date"], reverse=True)
    logger.info(f"{raw_code} 财报: {len(records)} 期")
    return records


def fetch_financial_detail(stock_code: str) -> dict[str, list[dict]]:
    """获取股票详细财务数据，按指标分类返回"""
    raw_code = stock_code.split(".")[0]
    logger.info(f"正在获取 {raw_code} 详细财报 ...")

    try:
        df = ak.stock_financial_abstract(symbol=raw_code)
    except Exception as e:
        logger.warning(f"{raw_code} 详细财报获取失败: {e}")
        return {}

    if df is None or df.empty:
        return {}

    dates = [c for c in df.columns if c not in ("选项", "指标")]
    result = {}
    for _, row in df.iterrows():
        group = str(row.get("选项", ""))
        metric = str(row.get("指标", ""))
        if metric not in result:
            result[metric] = []
        for d in dates:
            v = row[d]
            try:
                val = float(v) if pd.notna(v) else None
            except (ValueError, TypeError):
                val = None
            result[metric].append({"date": str(d)[:8], "value": val})
    return result
