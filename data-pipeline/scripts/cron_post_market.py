#!/usr/bin/env python3
"""盘后报触发脚本（修复 RAA-5 · 2026-06-11）

RAA-5 fix: 原版硬编码 CIFANG_TOKEN='dummy' 绕过 config.py 强校验。
现改为从 .secrets/*.env 显式 setdefault 加载（与 cron_dispatcher.py 语义一致），
不再覆盖 dispatcher 已加载的真实值。
"""
import asyncio, sys, os
from pathlib import Path

# ── 环境变量加载（与 cron_dispatcher.py 对齐）────────────────────
_ROOT = Path("/home/claw/invest-infra")
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

# 校验关键 3 变量（与 config.py __post_init__ 强校验对齐）
for _key in ("PG_PASSWORD", "MINIO_SECRET_KEY", "CIFANG_TOKEN"):
    if not os.environ.get(_key):
        raise RuntimeError(
            f"{_key} not set; expected in .secrets/ or injected by cron_dispatcher"
        )

sys.path.insert(0, "/home/claw/invest-infra/data-pipeline/src")
from reports.report_engine import ReportEngine


async def main():
    engine = ReportEngine("post_market")
    success = await engine.run()
    sys.exit(0 if success else 1)


asyncio.run(main())
