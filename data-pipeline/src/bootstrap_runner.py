#!/usr/bin/env python3
"""
数据采集直连运行器 - 零AI开销
所有 cron 命令统一入口，按 cmd 参数路由到对应脚本

用法:
  python bootstrap_runner.py <cmd> [batch]
  python bootstrap_runner.py etf_spot
  python bootstrap_runner.py etf_alpha
  python bootstrap_runner.py financial 1   # batch 1-4
"""
import sys, os, json
from pathlib import Path

# 采集项目根目录加入 path
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 加载 .env
ENV_FILE = _ROOT / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().strip().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

def run(cmd: str, batch: int = 1) -> dict:
    from datetime import datetime
    import psycopg2
    from src.pipeline_main import run_etf_spot_only, run_etf_pipeline, run_financial
    from src.factors.etf import run_etf_factor_calc
    from src.collector.etf import batch_fetch_etf_hist
    from src.signals.etf_alpha import compute_etf_alpha as _compute_alpha
    from datetime import date as date_cls

    start = datetime.now()
    try:
        if cmd == "etf_spot":
            r = run_etf_spot_only(limit=1486)
        elif cmd == "etf_pipeline":
            r = run_etf_pipeline(days=1, limit=1486)
        elif cmd == "etf_kline":
            r = batch_fetch_etf_hist(start_year=2025, limit=1486)
        elif cmd == "etf_alpha":
            from src.config import pg as _pg
            _conn = psycopg2.connect(host=_pg.host, port=_pg.port, dbname=_pg.db, user=_pg.user, password=_pg.password)
            result_obj = _compute_alpha(_conn, date_cls.today(), lookback_days=60)
            _conn.close()
            r = result_obj.get("signals", 0) if isinstance(result_obj, dict) else 0
        elif cmd == "etf_factor":
            r = run_etf_factor_calc(days=20)
            r = r.get("records", 0)
        elif cmd == "financial":
            r = run_financial(batch=batch)
        else:
            return {"ok": False, "error": f"Unknown cmd: {cmd}"}

        return {
            "ok": True,
            "result": r,
            "duration_s": (datetime.now() - start).total_seconds(),
            "cmd": cmd,
            "batch": batch,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "duration_s": (datetime.now() - start).total_seconds(),
            "cmd": cmd,
            "batch": batch,
        }

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    batch = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    result = run(cmd, batch=batch)
    print(json.dumps(result, ensure_ascii=False, default=str))
    sys.exit(0 if result.get("ok") else 1)
