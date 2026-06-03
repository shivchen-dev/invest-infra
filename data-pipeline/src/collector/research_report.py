"""研报数据采集器 — 通过 akshare 东方财富接口获取券商研报

完整流程：
1. fetch_research_report(symbol)  # 获取研报列表（akshare API）
2. download_pdf(pdf_url, dest)  # 下载 PDF 到本地
3. extract_text(pdf_path)       # PyMuPDF 文本提取
4. extract_tables(pdf_path)     # pdfplumber 表格提取
5. parse_report(pdf_path)       # LLM 结构化关键信息提取
"""

import logging
import os
import tempfile
import urllib.error
import urllib.request
from datetime import date, datetime
from typing import Optional, Any

import akshare as ak
import fitz
import pdfplumber
from pdfplumber.table import Table as PlumberTable

from src.collector.retry import with_retry

logger = logging.getLogger(__name__)


@with_retry()
def fetch_research_report(symbol: str) -> list[dict]:
    """获取个股研报列表（东方财富源）

    Args:
        symbol: 股票代码，如 '000001' 或 '000001.SZ'

    Returns:
        研报记录列表，每条包含研报基本信息
    """
    raw_code = symbol.split(".")[0]
    logger.info(f"正在获取 {raw_code} 研报 ...")

    try:
        df = ak.stock_research_report_em(symbol=raw_code)
    except Exception as e:
        logger.warning(f"{raw_code} 研报获取失败: {e}")
        return []

    if df is None or df.empty:
        return []

    records = []
    for _, row in df.iterrows():
        records.append({
            "stock_code": symbol,
            "report_name": str(row.get("报告名称", "")),
            "stock_name": str(row.get("股票简称", "")),
            "rating": str(row.get("东财评级", "")),
            "institution": str(row.get("机构", "")),
            "profit_forecast_2026": _parse_numeric(row.get("2026-盈利预测-收益")),
            "pe_forecast_2026": _parse_numeric(row.get("2026-盈利预测-市盈率")),
            "report_date": _parse_date(row.get("日期")),
            "pdf_url": str(row.get("报告PDF链接", "")),
        })
    return records


def download_pdf(pdf_url: str, dest: Optional[str] = None) -> Optional[str]:
    """下载研报 PDF 到本地

    Args:
        pdf_url: PDF 公共链接
        dest: 保存路径（默认 /tmp 下生成临时文件）

    Returns:
        本地文件路径，失败返回 None
    """
    if not pdf_url:
        return None

    if dest is None:
        dest = tempfile.mktemp(suffix=".pdf")

    try:
        request = urllib.request.Request(
            pdf_url,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            content_type = response.headers.get("Content-Type", "")
            if "pdf" not in content_type.lower() and not pdf_url.lower().endswith(".pdf"):
                logger.warning(f"PDF 链接非 PDF 类型: {pdf_url} (Content-Type: {content_type})")
                return None
            with open(dest, "wb") as f:
                f.write(response.read())
        size = os.path.getsize(dest)
        if size < 1024:
            logger.warning(f"PDF 文件异常小 ({size} bytes): {dest}")
            os.remove(dest)
            return None
        logger.info(f"PDF 已下载: {dest} ({size} bytes)")
        return dest
    except urllib.error.HTTPError as e:
        logger.warning(f"PDF 下载 HTTP 错误 {pdf_url}: {e.code}")
        return None
    except Exception as e:
        logger.warning(f"PDF 下载失败 {pdf_url}: {e}")
        return None


def extract_text(pdf_path: str) -> str:
    """从 PDF 提取文本内容（PyMuPDF）

    Args:
        pdf_path: PDF 文件路径

    Returns:
        提取的纯文本内容
    """
    if not os.path.exists(pdf_path):
        return ""

    try:
        with fitz.open(pdf_path) as doc:
            text = "".join(page.get_text() for page in doc)
        return text
    except Exception as e:
        logger.warning(f"文本提取失败 {pdf_path}: {e}")
        return ""


def extract_tables(pdf_path: str) -> list[list[list[str]]]:
    """从 PDF 提取所有表格（pdfplumber）

    Args:
        pdf_path: PDF 文件路径

    Returns:
        每页的表格列表，每表为 rows x cols 的字符串列表
    """
    if not os.path.exists(pdf_path):
        return []

    try:
        tables_by_page: list[list[list[str]]] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                tables: list[list[str]] = []
                raw = page.extract_tables()
                if not raw:
                    tables_by_page.append(tables)
                    continue
                for tbl in raw:
                    if tbl is None:
                        continue
                    # 降级：pdfplumber Table → list[list[str]]
                    if isinstance(tbl, PlumberTable):
                        rows: list[list[str]] = []
                        for row in tbl.rows:
                            rows.append([cell or "" for cell in row.cells])
                        tables.append(rows)
                    elif isinstance(tbl, list):
                        tables.append([[c or "" for c in row] for row in tbl])
                tables_by_page.append(tables)
        return tables_by_page
    except Exception as e:
        logger.warning(f"表格提取失败 {pdf_path}: {e}")
        return []


# ----------------------------------------------------------------------
# 内部辅助
# ----------------------------------------------------------------------


def _parse_numeric(val) -> Optional[float]:
    """解析数值字段，兼容字符串和 None"""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_date(val: Any) -> Optional[date]:
    """解析日期字段"""
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    try:
        return datetime.fromisoformat(str(val).replace("T", " ").split(" ")[0]).date()
    except (ValueError, TypeError, AttributeError):
        return None