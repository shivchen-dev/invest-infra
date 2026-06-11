#!/usr/bin/env python3
"""
市场数据采集脚本 — 统一入口
======================================================
每日 15:05 一次性批量采集 MCP 数据，写入 daily_market_snapshot

触发时机：每个交易日 15:05（收盘后）
数据用途：盘前报/午盘报/盘后报从 DB 读取，不走 MCP

实现：直接调用 market_data_collector.run()（17项，限流5批）
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

from reports.market_data_collector import run


if __name__ == "__main__":
    stats = asyncio.run(run())
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    sys.exit(0 if stats["failed"] == 0 else 1)
