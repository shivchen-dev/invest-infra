#!/usr/bin/env python3
"""日内 ETF 实时行情采集 — 次方量化 API"""
import sys, os, time
import argparse
from pathlib import Path
from datetime import date, datetime

# ── 路径初始化 ─────────────────────────────────────────────────────────────
_pipeline_dir = Path("/home/claw/invest-infra/data-pipeline")
_secrets_dir = _pipeline_dir.parent / ".secrets"

def _load_env(filepath):
    loaded = []
    if filepath and filepath.exists():
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k:
                    os.environ.setdefault(k, v)
                    loaded.append(k)
    return loaded

# 加载 secrets（备用），再加载 .env（优先）
_load_env(_secrets_dir / "tokens.env")
_load_env(_secrets_dir / "cifang.env")   # CIFANG_TOKEN（次方量化）
_load_env(_pipeline_dir / ".env")

sys.path.insert(0, str(_pipeline_dir))
os.chdir(str(_pipeline_dir))

from src.collector.cifang import fetch_fund_spot, write_spot_to_etf_quotes

parser = argparse.ArgumentParser(description="日内 ETF 实时行情采集")
parser.add_argument("--minute-bucket", default="", help="分钟桶标识，如 1000、1015 等，空串表示日线")
args = parser.parse_args()
minute_bucket = args.minute_bucket

today = date.today()
t0 = time.time()

print(f"[{datetime.now()}] ETF日内刷新开始（次方量化） minute_bucket={minute_bucket or '日线'}")

spot = fetch_fund_spot()
if not spot:
    print(f"[{datetime.now()}] 次方量化返回空，中止")
    sys.exit(1)

written = write_spot_to_etf_quotes(spot, today, minute_bucket)
elapsed = time.time() - t0

print(f"[{datetime.now()}] 完成: {written} 只 ETF 写入 etf_quotes ({elapsed:.1f}s)")