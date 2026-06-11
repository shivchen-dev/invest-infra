"""财报数据采集器 — 通过 akshare 获取 A 股财务报告

akshare stock_financial_abstract 返回格式:
  行=指标(如"归母净利润"), 列=报告期(如"20260331"), 值=指标数值
  需要转置为: 每个报告期一行
"""

import logging
from datetime import datetime
from typing import Optional

import akshare as ak
import socket
import pandas as pd

from src.collector.retry import with_retry

logger = logging.getLogger(__name__)


def _val(df: pd.DataFrame, metrics: dict, d, metric_name: str) -> Optional[float]:
    """从财报 DataFrame 中提取指定指标在指定日期列的值（模块级）"""
    idx = metrics.get(metric_name)
    if idx is None:
        return None
    v = df.iloc[idx][d]
    try:
        return float(v) if pd.notna(v) else None
    except (ValueError, TypeError):
        return None


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
    """获取单只股票的财报摘要数据，返回 list[dict] 每期一条（THS源）"""
    raw_code = stock_code.split(".")[0]
    logger.info(f"正在获取 {raw_code} 财报 (THS)...")

    try:
        df = ak.stock_financial_abstract_ths(symbol=raw_code)
    except Exception as e:
        logger.error(f"{raw_code} 财报获取失败: {e}", exc_info=True)
        return []

    if df is None or df.empty:
        return []

    # THS格式：行=报告期，列=指标；列名固定，值为字符串/数值
    if "报告期" not in df.columns:
        logger.warning(f"{raw_code} 财报缺少「报告期」列，跳过。列: {df.columns.tolist()}")
        return []

    records = []
    for _, row in df.iterrows():
        report_date_raw = row.get("报告期")
        if report_date_raw is None:
            continue
        # 解析报告期：支持 YYYY-MM-DD / YYYY/MM/DD / YYYYMM
        try:
            sd = str(report_date_raw)
            if "-" in sd:
                report_date = datetime.strptime(sd[:10], "%Y-%m-%d").date()
            elif "/" in sd:
                report_date = datetime.strptime(sd[:10], "%Y/%m/%d").date()
            else:
                report_date = datetime.strptime(sd[:8], "%Y%m%d").date()
        except (ValueError, IndexError):
            continue

        fiscal_year = report_date.year
        report_type = _report_type_from_date(str(report_date_raw))
        if not report_type:
            continue

        # 解析带中文单位的数值字段（亿/万/百万）
        def _parse_val(v):
            if v is None or v is False:
                return None
            s = str(v).strip()
            if not s or s in ("False", "True"):
                return None
            try:
                return float(s.replace("%", ""))
            except ValueError:
                return _parse_chinese_number(s)

        # 解析百分比字段
        def _parse_pct(v):
            if v is None or v is False:
                return None
            s = str(v).strip().replace("%", "")
            if not s or s in ("False", "True"):
                return None
            try:
                return float(s)
            except ValueError:
                return None

        records.append({
            "stock_code": stock_code,
            "report_date": report_date,
            "report_type": report_type,
            "fiscal_year": fiscal_year,
            "revenue": _parse_val(row.get("营业总收入")),
            "cost_of_sales": None,  # THS abstract 无成本字段，由 indicator 补充
            "gross_profit": None,
            "net_profit": _parse_val(row.get("净利润")),
            "parent_net_profit": _parse_val(row.get("扣非净利润")) or _parse_val(row.get("净利润")),
            "total_assets": None,  # 由 fetch_financial_indicator 的 THS debt 接口补充
            "total_liabilities": None,
            "total_equity": None,
            "operating_cf": _parse_val(row.get("每股经营现金流")),
            "roa_raw": _parse_pct(row.get("净资产收益率")),
            "debt_ratio_raw": _parse_pct(row.get("资产负债率")),
            "source": "akshare_ths",
        })

    records.sort(key=lambda r: r["report_date"], reverse=True)
    logger.info(f"{raw_code} 财报: {len(records)} 期")
    return records



def _parse_chinese_number(s):
    """解析 '6.03万亿'/'352.77亿' 等中文数值格式 → float(元)"""
    if s is None:
        return None
    s = str(s).strip()
    try:
        return float(s)
    except ValueError:
        pass
    if '万亿' in s:
        return float(s.replace('万亿','')) * 1e12
    elif '亿' in s:
        return float(s.replace('亿','')) * 1e8
    elif '万' in s:
        return float(s.replace('万','')) * 1e4
    return None


@with_retry()
def fetch_financial_indicator(stock_code: str, start_year: int = 2020) -> list[dict]:
    """
    获取单只股票的财务指标数据（从东方财富 EM + 同花顺 THS）。
    Sina stock_financial_analysis_indicator 因页面结构变更已废弃，改用双源方案：
      - 资产负债率：EM stock_financial_analysis_indicator_em 的 ZCFZL 字段
      - 总资产/总负债：THS stock_financial_debt_ths 的 *资产合计/*负债合计
      - ROA：EM PARENTNETPROFIT / THS 总资产
    """
    raw_code = stock_code.split('.')[0]
    suffix = '.SZ' if raw_code.startswith(('0', '3')) else '.SH'
    em_symbol = f"{raw_code}{suffix}"
    logger.info(f"正在获取 {raw_code} 财务指标 (EM+THS)...")

    # ── 全局 socket 超时：10s，防止单次 API 挂死
    _orig_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(10)

    # ── EM：东方财富财务指标（ZCFZL 资产负债率、PARENTNETPROFIT 净利润）
    em_df = None
    try:
        em_df = ak.stock_financial_analysis_indicator_em(symbol=em_symbol, indicator='按报告期')
    except Exception as e:
        logger.warning(f"{raw_code} EM财务指标获取失败，降级: {e}")

    # ── THS：同花顺资产负债表（总资产、总负债）—— 超时则降级跳过
    ths_df = None
    try:
        ths_df = ak.stock_financial_debt_ths(symbol=raw_code)
    except Exception as e:
        logger.warning(f"{raw_code} THS资产负债表获取失败，降级（仅用EM数据）: {e}")

    socket.setdefaulttimeout(_orig_timeout)

    # ── 解析 THS：report_date → (assets_yuan, liabilities_yuan)
    ths_map = {}
    if ths_df is not None and not ths_df.empty:
        for _, row in ths_df.iterrows():
            rdate = str(row.get('报告期', ''))[:10]
            assets = _parse_chinese_number(row.get('*资产合计'))
            liabilities = _parse_chinese_number(row.get('*负债合计'))
            if rdate and assets is not None and liabilities is not None:
                ths_map[rdate] = (assets, liabilities)

    # ── 解析 EM 记录
    records = []
    if em_df is not None and not em_df.empty:
        for _, row in em_df.iterrows():
            report_date_raw = row.get('REPORT_DATE')
            if report_date_raw is None:
                continue
            if hasattr(report_date_raw, 'date'):
                report_date_raw = report_date_raw.date()
            else:
                try:
                    from datetime import date
                    report_date_raw = date.fromisoformat(str(report_date_raw)[:10])
                except ValueError:
                    continue

            fiscal_year = report_date_raw.year
            report_type = _report_type_from_date(str(report_date_raw).replace('-', ''))
            if not report_type:
                continue

            def _f(v):
                try:
                    return float(v) if pd.notna(v) else None
                except (ValueError, TypeError):
                    return None

            debt_ratio_pct = _f(row.get('ZCFZL'))
            net_profit = _f(row.get('PARENTNETPROFIT'))

            rdate_str = str(report_date_raw)
            total_assets_yuan = None
            total_liabilities_yuan = None
            if rdate_str in ths_map:
                total_assets_yuan, total_liabilities_yuan = ths_map[rdate_str]

            roa_pct = None
            if net_profit is not None and total_assets_yuan is not None and total_assets_yuan != 0:
                roa_pct = (net_profit / total_assets_yuan) * 100.0

            records.append({
                'stock_code': stock_code,
                'report_date': report_date_raw,
                'report_type': report_type,
                'fiscal_year': fiscal_year,
                'total_assets': total_assets_yuan,
                'total_liabilities': total_liabilities_yuan,
                'debt_ratio_raw': debt_ratio_pct,
                'roa_raw': roa_pct,
                'source': 'em_ths',
            })

    records.sort(key=lambda r: r['report_date'], reverse=True)
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
        logger.error(f"{raw_code} 详细财报获取失败: {e}", exc_info=True)
        return {}

    if df is None or df.empty:
        return {}

    col_list = df.columns.tolist()
    if "选项" not in col_list or "指标" not in col_list:
        logger.warning(f"{raw_code} 详细财报缺少「选项」或「指标」列，跳过。列: {col_list}")
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
