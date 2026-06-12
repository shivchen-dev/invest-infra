#!/usr/bin/env python3
"""
盘中异动数据预采集脚本（2026-06-12）

盘中每30分钟批量采集异动数据，写入 intraday_snapshot（PG）。
盘中报从 PG 读，不走 MCP。

数据：
  - limit_events（实时封板/炸板事件）
  - limit_down（跌停池）
  - anomaly_detection（价格异动）

注意：本脚本在每30分钟定时触发，数据以 trade_date=今日 做 upsert，
盘中报读取时直接取 latest（同一 trade_date 下的最新记录）。
"""
import asyncio
import sys
import os
import json
import logging
from datetime import date
from pathlib import Path

_ROOT = Path("/home/claw/invest-infra/data-pipeline")
_SECRETS_DIR = _ROOT / ".secrets"


def _load_secrets(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


for _name in ("pg.env", "minio.env", "cifang.env", "mcp.env"):
    _load_secrets(_SECRETS_DIR / _name)

for _key in ("PG_PASSWORD", "MINIO_SECRET_KEY", "CIFANG_TOKEN"):
    if not os.environ.get(_key):
        raise RuntimeError(f"{_key} not set; expected in .secrets/ or injected by cron_dispatcher")

sys.path.insert(0, str(_ROOT / "src"))

from reports.mcp_client import get_mcp_client, BatchMCPClient as MCPBatchClient
from reports.trading_day import is_trading_day, get_trading_phase
from loader.pg import get_conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

INTRADAY_TOOLS = [
    {
        "name": "limit_events",
        "params": {"type": "limit_up", "limit": 50, "order": "desc", "detailLevel": "standard", "format": "json"},
        "data_type": "limit_events",
    },
    {
        "name": "limit_down",
        "params": {"detailLevel": "standard", "format": "json"},
        "data_type": "limit_down",
    },
    {
        "name": "anomaly_detection",
        "params": {"detailLevel": "standard", "format": "json"},
        "data_type": "anomaly_detection",
    },
]


def save_snapshot(trade_date: str, data_type: str, tool_name: str, raw_data: dict) -> bool:
    """写入 intraday_snapshot，upsert 模式（只保留最新一条）"""
    with get_conn() as conn:
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO intraday_snapshot (trade_date, data_type, tool_name, raw_data, collected_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (trade_date, data_type)
                DO UPDATE SET
                    tool_name = EXCLUDED.tool_name,
                    raw_data = EXCLUDED.raw_data,
                    collected_at = NOW()
                """,
                (trade_date, data_type, tool_name, json.dumps(raw_data, ensure_ascii=False, default=str)),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"写入 intraday_snapshot 失败 [{data_type}]: {e}")
            conn.rollback()
            return False


async def collect_intraday(trade_date: str) -> dict:
    """采集盘中异动数据"""
    logger.info(f"盘中异动采集开始: {trade_date}")

    # 判断是否在交易时段（不在交易时段则跳过）
    phase = get_trading_phase()
    logger.info(f"当前交易阶段: {phase}")

    mcp = MCPBatchClient(get_mcp_client())
    stats = {"total": len(INTRADAY_TOOLS), "success": 0, "failed": 0}

    # 批量采集（每批2个，限流）
    batch_size = 2
    for i in range(0, len(INTRADAY_TOOLS), batch_size):
        chunk = INTRADAY_TOOLS[i:i + batch_size]
        calls = []
        for t in chunk:
            params = dict(t["params"])
            # limit_down 需要日期格式化
            if t["name"] == "limit_down":
                params["date"] = date.today().strftime("%Y%m%d")
            elif t["name"] == "anomaly_detection":
                params["date"] = trade_date
            calls.append({"name": t["name"], "params": params})

        results = await mcp.call_batch(calls)

        for t in chunk:
            data_type = t["data_type"]
            tool_name = t["name"]
            raw_data = results.get(data_type) or results.get(tool_name) or {}
            if raw_data:
                ok = save_snapshot(trade_date, data_type, tool_name, raw_data)
                if ok:
                    logger.info(f"  ✅ {data_type}")
                    stats["success"] += 1
                else:
                    logger.error(f"  ❌ {data_type}")
                    stats["failed"] += 1
            else:
                logger.warning(f"  ⚠️ {data_type} 无数据")
                stats["failed"] += 1

        # 批次间延迟
        if i + batch_size < len(INTRADAY_TOOLS):
            await asyncio.sleep(0.5)

    logger.info(f"盘中异动采集完成: {stats}")
    return stats


async def main() -> int:
    today = date.today()
    trade_date = today.strftime("%Y-%m-%d")

    if not is_trading_day(today):
        logger.info(f"{trade_date} 非交易日，跳过")
        return 0

    stats = await collect_intraday(trade_date)
    sys.exit(0 if stats["failed"] == 0 else 1)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))