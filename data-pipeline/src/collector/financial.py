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

from src.collector.retry import with_retry

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


@with_retry()
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
            "total_assets":       _val("总资产"),
            "total_liabilities":   _val("总负债"),
            "total_equity":        _val("股东权益合计(净资产)"),
            "operating_cf":        _val("经营现金流量净额"),
            # ROA（%）和资产负债率（%）—— 用 computed 指标补充原始字段缺失
            "roa_raw":            _val("总资产报酬率(ROA)"),
            "debt_ratio_raw":      _val("资产负债率"),
            "source": "akshare",
        })

    records.sort(key=lambda r: r["report_date"], reverse=True)
    logger.info(f"{raw_code} 财报: {len(records)} 期")
    return records


@with_retry()
def fetch_financial_indicator(stock_code: str, start_year: int = 2020) -> list[dict]:
    """
    获取单只股票的财务指标数据（从 stock_financial_analysis_indicator）。
    用于补充 ROA、DebtRatio、TotalAssets 等财报摘要中缺失的原始字段。

    返回 list[dict]，每期一条，包含:
      report_date, report_type, fiscal_year,
      total_assets, total_liabilities, debt_ratio_raw, roa_raw
    """
    raw_code = stock_code.split(".")[0]
    logger.info(f"正在获取 {raw_code} 财务指标 ...")

    try:
        df = ak.stock_financial_analysis_indicator(symbol=raw_code, start_year=str(start_year))
    except Exception as e:
        logger.warning(f"{raw_code} 财务指标获取失败: {e}")
        return []

    if df is None or df.empty:
        return []

    records = []
    for _, row in df.iterrows():
        report_date = row.get("日期")
        if report_date is None:
            continue
        if hasattr(report_date, "date"):
            report_date = report_date.date()

        fiscal_year = report_date.year
        report_type = _report_type_from_date(str(report_date).replace("-", ""))
        if not report_type:
            continue

        def _f(v) -> Optional[float]:
            try:
                return float(v) if pd.notna(v) else None
            except (ValueError, TypeError):
                return None

        # 总资产（元）
        total_assets = _f(row.get("总资产(元)"))
        # 资产负债率（%）
        debt_ratio_pct = _f(row.get("资产负债率(%)"))
        # 资产报酬率 ROA（%）
        roa_pct = _f(row.get("资产报酬率(%)"))

        # 用资产负债率反推总负债：liabilities = assets * debt_ratio% / 100
        total_liabilities = None
        if total_assets is not None and debt_ratio_pct is not None and total_assets != 0:
            total_liabilities = total_assets * debt_ratio_pct / 100.0

        records.append({
            "stock_code": stock_code,
            "report_date": report_date,
            "report_type": report_type,
            "fiscal_year": fiscal_year,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "debt_ratio_raw": debt_ratio_pct,   # 百分比形式，供验证用
            "roa_raw": roa_pct,                  # 百分比形式，供验证用
            "source": "akshare-indicator",
        })

    records.sort(key=lambda r: r["report_date"], reverse=True)
    logger.info(f"{raw_code} 财务指标: {len(records)} 期")
    return records


@with_retry()
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
