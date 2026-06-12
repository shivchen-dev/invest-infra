#!/usr/bin/env python3
"""盘前报触发脚本（改造为真正生成报告 · 2026-06-12）

原版（2026-06-11）只发 QQ 通知，不生成报告。
现改为：
  1. 检查是否为交易日
  2. 调用 ReportEngine("pre_market") 生成报告 → 写入 market_reports 表
  3. 发送 QQ 通知
"""
import asyncio
import sys
import os
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
from reports.report_engine import ReportEngine
from reports.trading_day import is_trading_day


async def main() -> int:
    today = date.today()
    print(f"[pre_market] 启动 {today}", file=sys.stderr)

    if not is_trading_day(today):
        print(f"[pre_market] 今日 {today} 非交易日，跳过", file=sys.stderr)
        return 0

    engine = ReportEngine("pre_market")
    success = await engine.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))