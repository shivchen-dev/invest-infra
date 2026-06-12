#!/usr/bin/env python3
"""
午盘报数据预采集脚本
======================================================
每日 11:30 一次性批量采集午盘报所需的5项核心数据，写入 daily_market_snapshot

触发时机：每个交易日 11:30（午盘报执行前30分钟）
数据用途：午盘报从 DB 读取，不走 MCP

采集项（MiddayReporter.REQUIRED_DATA_TYPES）：
    - market_overview    大盘状态
    - concept_ranking   概念排行
    - smart_hotlist     股票热榜
    - capital_flow_mkt  市场资金流
    - broken_limit_up   炸板池
"""

import asyncio
import sys
import os
import json

sys.path.insert(0, "/home/claw/invest-infra/data-pipeline/src")
os.environ["CIFANG_TOKEN"] = "dummy"
os.environ.setdefault("MINIO_SECRET_KEY", "")
if not os.environ.get("MINIO_SECRET_KEY"):
    raise RuntimeError("MINIO_SECRET_KEY not set; expected in .env or .secrets/minio.env")

from reports.mcp_client import get_mcp_client, BatchMCPClient as MCPBatchClient
from reports.market_data_cache import MarketDataCache
from reports.trading_day import is_trading_day
from datetime import date

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# 午盘报所需的5项核心数据
MIDDAY_TOOLS = [
    {
        "name": "market_overview",
        "params": {"detailLevel": "standard", "format": "json"},
        "data_type": "market_overview",
    },
    {
        "name": "concept_ranking",
        "params": {"type": "concept", "sortBy": "limitUpNum", "limit": 20, "detailLevel": "standard", "format": "json"},
        "data_type": "concept_ranking",
    },
    {
        "name": "smart_hotlist",
        "params": {"source": "combined", "limit": 20, "detailLevel": "standard", "format": "json"},
        "data_type": "smart_hotlist",
    },
    {
        "name": "capital_flow",
        "params": {"flowType": "market", "limit": 5, "detailLevel": "standard", "format": "json"},
        "data_type": "capital_flow_mkt",
    },
    {
        "name": "broken_limit_up",
        "params": {"detailLevel": "standard", "format": "json"},
        "data_type": "broken_limit_up",
    },
]

# date参数：仅支持的工具才传，且格式需匹配各自API要求
# market_overview: YYYY-MM-DD ✅
# capital_flow: YYYY-MM-DD ✅
# broken_limit_up: YYYYMMDD（不支持YYYY-MM-DD）
# concept_ranking: 不支持date参数 ❌
# smart_hotlist: 不支持date参数 ❌
DATE_PARAM_MAP = {
    "market_overview": "date",       # YYYY-MM-DD
    "capital_flow": "date",          # YYYY-MM-DD
    "broken_limit_up": "date",       # YYYYMMDD（不是YYYY-MM-DD）
}


async def main():
    trade_date_obj = date.today()
    trade_date = trade_date_obj.strftime("%Y-%m-%d")
    logger.info(f"午盘报数据预采集开始 (date={trade_date})")

    if not is_trading_day(trade_date_obj):
        logger.info(f"{trade_date} 非交易日，跳过")
        return {"collected": 0, "failed": 0}

    cache = MarketDataCache(trade_date)
    mcp = MCPBatchClient(get_mcp_client())

    stats = {"collected": 0, "failed": 0}

    # 分批采集，每批2个（限流）
    batch_size = 2
    for i in range(0, len(MIDDAY_TOOLS), batch_size):
        chunk = MIDDAY_TOOLS[i:i + batch_size]
        calls = []
        for t in chunk:
            params = dict(t["params"])
            date_key = DATE_PARAM_MAP.get(t["name"])
            if date_key:
                # broken_limit_up 使用 YYYYMMDD 格式
                if t["name"] == "broken_limit_up":
                    params[date_key] = trade_date_obj.strftime("%Y%m%d")
                else:
                    params[date_key] = trade_date
            calls.append({"name": t["name"], "params": params})

        results = await mcp.call_batch(calls)
        for t in chunk:
            data_type = t["data_type"]
            tool_name = t["name"]
            raw_data = results.get(data_type) or results.get(tool_name) or {}
            if raw_data:
                ok = cache.save(data_type, tool_name, raw_data)
                if ok:
                    stats["collected"] += 1
                    logger.info(f"  ✅ {data_type}")
                else:
                    stats["failed"] += 1
                    logger.error(f"  ❌ {data_type}")
            else:
                stats["failed"] += 1
                logger.warning(f"  ⚠️ {data_type} 无数据")

        # 批次间稍作延迟
        if i + batch_size < len(MIDDAY_TOOLS):
            await asyncio.sleep(1)

    logger.info(f"午盘报数据预采集完成: collected={stats['collected']} failed={stats['failed']}")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return stats


if __name__ == "__main__":
    stats = asyncio.run(main())
    sys.exit(0 if stats["failed"] == 0 else 1)
