#!/usr/bin/env python3
"""
每日市场数据采集器
每日 16:00（收盘后）一次性批量采集 MCP 数据，写入 PostgreSQL

用途:
    - 每日 16:00 批量采集，缓存到 daily_market_snapshot 表
    - 盘前/午盘/盘后报告从 DB 读，不走 MCP
    - 历史对比分析可行

用法:
    python market_data_collector.py              # 采集今日数据
    python market_data_collector.py --date 2026-06-06  # 采集指定日期
"""

import sys
import os
import asyncio
import json
import logging
import fcntl
import tempfile
from datetime import date, datetime
from typing import Any, Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from reports.mcp_client import get_mcp_client, BatchMCPClient as MCPBatchClient
from reports.trading_day import is_trading_day
from loader.pg import get_conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# MCP 工具分组（每日 16:00 批量采集）
TRADE_DATE_TOOLS = [
    # Group-A: 大盘/复盘基础
    {
        "name": "market_overview",
        "params": {"detailLevel": "standard", "format": "json"},
        "data_type": "market_overview",
    },
    {
        "name": "limit_stats",
        "params": {"detailLevel": "standard", "format": "json"},
        "data_type": "limit_stats",
    },
    {
        "name": "market_replay_workflow",
        "params": {"detailLevel": "standard", "format": "json"},
        "data_type": "market_replay",
    },
    # Group-B: 涨停/板块 + 主线
    {
        "name": "hot_sectors",
        "params": {"detailLevel": "standard", "format": "json"},
        "data_type": "hot_sectors",
    },
    {
        "name": "limit_up_ladder",
        "params": {"includeFirstBoard": True, "detailLevel": "standard", "format": "json"},
        "data_type": "limit_up_ladder",
    },
    {
        "name": "market_leaders_pick",
        "params": {"detailLevel": "standard", "format": "json"},
        "data_type": "market_leaders",
    },
    {
        "name": "board_break_analysis",
        "params": {"focus": "all", "detailLevel": "standard", "format": "json"},
        "data_type": "board_break",
    },
    {
        "name": "broken_limit_up",
        "params": {"detailLevel": "standard", "format": "json"},
        "data_type": "broken_limit_up",
    },
    # Group-C: 资金流
    {
        "name": "capital_flow",
        "params": {"flowType": "market", "limit": 5, "detailLevel": "standard", "format": "json"},
        "data_type": "capital_flow_mkt",
    },
    # Group-D: 竞价（仅交易日）
    {
        "name": "auction_market_scan",
        "params": {"sortBy": "bidStrength", "limit": 30, "detailLevel": "standard", "format": "json"},
        "data_type": "auction_scan",
    },
    {
        "name": "auction_weak_to_strong",
        "params": {"detailLevel": "standard", "format": "json"},
        "data_type": "auction_wts",
    },
    {
        "name": "auction_limitup_feedback",
        "params": {"detailLevel": "standard", "format": "json"},
        "data_type": "auction_feedback",
    },
    # Group-E: 主力/龙虎
    {
        "name": "stock_rank",
        "params": {"type": "volume", "limit": 20, "detailLevel": "standard", "format": "json"},
        "data_type": "stock_rank_volume",
    },
    {
        "name": "stock_rank",
        "params": {"type": "turnover_rate", "limit": 20, "detailLevel": "standard", "format": "json"},
        "data_type": "stock_rank_turnover",
    },
    # Group-F: 消息面
    {
        "name": "cls_news",
        "params": {"level": "AB", "limit": 20, "detailLevel": "standard", "format": "json"},
        "data_type": "cls_news",
    },
    # Group-G: 概念/板块
    {
        "name": "concept_ranking",
        "params": {"type": "concept", "sortBy": "limitUpNum", "limit": 20, "detailLevel": "standard", "format": "json"},
        "data_type": "concept_ranking",
    },
    {
        "name": "sector_analysis",
        "params": {"source": "dongcai_concept", "period": 20, "detailLevel": "standard", "format": "json"},
        "data_type": "sector_analysis",
    },
]


# 各工具对应的日期参数名
DATE_PARAM_MAP = {
    "market_overview": "date",
    "limit_stats": "date",
    "market_replay_workflow": "date",
    "hot_sectors": "date",
    "limit_up_ladder": "date",
    "market_leaders_pick": "date",
    "board_break_analysis": "tradeDate",
    "broken_limit_up": "date",
    "auction_market_scan": "tradeDate",
    "auction_weak_to_strong": "tradeDate",
    "auction_limitup_feedback": "tradeDate",
    "capital_flow": "date",
    "stock_rank": "date",
    "cls_news": "date",
    "concept_ranking": "date",
    "sector_analysis": "date",
}


async def collect_tools(mcp, tools: list, trade_date: str) -> Dict[str, Any]:
    """并行调用一组 MCP 工具，注入日期参数"""
    batch = []
    for t in tools:
        params = dict(t["params"])
        date_key = DATE_PARAM_MAP.get(t["name"])
        if date_key:
            params[date_key] = trade_date
        batch.append({"name": t["name"], "params": params})
    results = await mcp.call_batch(batch)
    return results


def save_snapshot(trade_date: date, data_type: str, tool_name: str, raw_data: Any) -> bool:
    """写入 daily_market_snapshot，upsert 模式"""
    with get_conn() as conn:
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO daily_market_snapshot (trade_date, data_type, tool_name, raw_data, collected_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (trade_date, data_type)
                DO UPDATE SET
                    tool_name = EXCLUDED.tool_name,
                    raw_data = EXCLUDED.raw_data,
                    collected_at = NOW()
                """,
                (str(trade_date), data_type, tool_name, json.dumps(raw_data, ensure_ascii=False, default=str)),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"写入 snapshot 失败 [{data_type}]: {e}")
            conn.rollback()
            return False


async def run(trade_date: str = None) -> Dict[str, Any]:
    """
    执行每日数据采集

    Args:
        trade_date: 采集日期，默认为今日

    Returns:
        采集结果统计
    """
    # 确保 trade_date 是字符串（CLI 可能传 date 对象）
    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")
    elif hasattr(trade_date, "strftime"):
        trade_date = trade_date.strftime("%Y-%m-%d")

    logger.info(f"========== 每日市场数据采集开始: {trade_date} ==========")

    # ── 采集开始 ──
    tool_list = [f"  - {t['data_type']} ({t['name']})" for t in TRADE_DATE_TOOLS]
    logger.info(f"待采集工具清单（共 {len(TRADE_DATE_TOOLS)} 项）：\n" + "\n".join(tool_list))

    mcp = MCPBatchClient(get_mcp_client())
    stats = {"total": len(TRADE_DATE_TOOLS), "success": 0, "failed": 0, "skipped": 0}
    # per-tool 状态，用于最终汇总
    tool_status: Dict[str, str] = {}

    # 按组并行采集（减少 MCP 并发压力）
    batch_size = 5
    for i in range(0, len(TRADE_DATE_TOOLS), batch_size):
        group = TRADE_DATE_TOOLS[i:i + batch_size]
        group_names = [t["name"] for t in group]
        logger.info(f"采集批次 {i//batch_size + 1}: {group_names}")

        try:
            results = await collect_tools(mcp, group, trade_date)
        except Exception as e:
            logger.error(f"批次采集异常: {e}")
            stats["failed"] += len(group)
            for tool in group:
                tool_status[tool["data_type"]] = "FAIL"
        else:
            # ── 记录本批次每项工具状态（成功时执行）─────────────
            for tool in group:
                data_type = tool["data_type"]
                tool_name = tool["name"]
                raw_data = results.get(data_type, {})

                # 空数据跳过
                if not raw_data:
                    logger.warning(f"  [SKIP] {data_type} 无数据")
                    stats["skipped"] += 1
                    tool_status[data_type] = "SKIP"
                    continue

                ok = save_snapshot(trade_date, data_type, tool_name, raw_data)
                if ok:
                    logger.info(f"  [OK] {data_type} ({tool_name})")
                    stats["success"] += 1
                    tool_status[data_type] = "OK"
                else:
                    logger.warning(f"  [FAIL] {data_type}")
                    stats["failed"] += 1
                    tool_status[data_type] = "FAIL"

        # 本批次汇总
        batch_ok = sum(1 for t in group if tool_status.get(t["data_type"]) == "OK")
        batch_fail = sum(1 for t in group if tool_status.get(t["data_type"]) == "FAIL")
        batch_skip = sum(1 for t in group if tool_status.get(t["data_type"]) == "SKIP")
        logger.info(f"  批次 {i//batch_size + 1} 完成 → OK={batch_ok} FAIL={batch_fail} SKIP={batch_skip}")

    # ── 最终汇总报告 ──
    ok_list   = [f"  ✓ {dt}" for dt, s in tool_status.items() if s == "OK"]
    fail_list = [f"  ✗ {dt}" for dt, s in tool_status.items() if s == "FAIL"]
    skip_list = [f"  - {dt}" for dt, s in tool_status.items() if s == "SKIP"]
    logger.info(f"========== 采集汇总: OK={stats['success']} FAIL={stats['failed']} SKIP={stats['skipped']} ==========")
    if ok_list:
        logger.info("成功:\n" + "\n".join(ok_list))
    if fail_list:
        logger.warning("失败:\n" + "\n".join(fail_list))
    if skip_list:
        logger.info("跳过:\n" + "\n".join(skip_list))

    # ── 汇总写入日志文件（flock + 临时文件 atomic rename）──
    summary = {
        "trade_date": trade_date,
        "total": stats["total"],
        "success": stats["success"],
        "failed": stats["failed"],
        "skipped": stats["skipped"],
        "tools": {t["data_type"]: {"tool": t["name"], "status": tool_status.get(t["data_type"], "?")} for t in TRADE_DATE_TOOLS}
    }
    summary_path = f"/tmp/market_data_collect_{trade_date.replace('-','')}.json"
    try:
        # 写临时文件再 atomic rename，避免多进程竞争
        fd, tmp_path = tempfile.mkstemp(dir="/tmp", prefix="market_data_collect_", suffix=".json.tmp")
        with os.fdopen(fd, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)          # 抢排他锁
            json.dump(summary, f, ensure_ascii=False, indent=2)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)        # 释放锁
        os.rename(tmp_path, summary_path)                    # atomic
        logger.info(f"采集结果已写入 {summary_path}")
    except Exception as e:
        logger.error(f"采集结果写入失败 {summary_path}: {e}")

    logger.info(f"========== 采集完成: {stats} ==========")
    return stats


def fetch_from_db(trade_date: str, data_type: str) -> Any:
    """
    从 DB 读取采集好的快照数据

    Args:
        trade_date: 交易日期
        data_type: 数据类型

    Returns:
        原始数据字典，无数据返回 None
    """
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT raw_data FROM daily_market_snapshot
            WHERE trade_date = %s AND data_type = %s
            """,
            (trade_date, data_type),
        )
        row = cur.fetchone()
        if row:
            return json.loads(row[0])
        return None
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="每日市场数据采集器")
    parser.add_argument("--date", "-d", help="指定采集日期 YYYY-MM-DD（默认自动找上一个交易日）")
    args = parser.parse_args()

    if args.date:
        trade_date_str = args.date
        trade_date = datetime.strptime(trade_date_str, "%Y-%m-%d").date()
    else:
        # 自动找上一个交易日（今天之前最近的交易日）
        trade_date = date.today()  # 采集当日数据，供次日晨报使用
        trade_date_str = trade_date.strftime("%Y-%m-%d")

    logger.info(f"采集目标日期: {trade_date_str} (is_trading_day={is_trading_day(trade_date)})")

    if not is_trading_day(trade_date):
        logger.info(f"{trade_date} 非交易日，跳过采集")
        sys.exit(0)

    stats = asyncio.run(run(trade_date_str))
    print(json.dumps(stats, ensure_ascii=False, indent=2))
