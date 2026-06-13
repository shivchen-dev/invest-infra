#!/usr/bin/env python3
"""
Redis Stream 命令执行器 - 常驻进程
接收 cron 指令，执行脚本，结果回写 Redis
"""
import os, sys, json, time, signal, logging
from datetime import datetime

import redis
import psycopg2

# 加载 .env
from pathlib import Path
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().strip().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

STREAM = "etf_exec_queue"
GROUP  = "etf_exec_workers"
CONSUMER = "executor_1"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("/home/claw/invest-infra/data-pipeline/logs/executor.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("executor")

def load_env():
    for k, v in [
        ("MINIO_ACCESS_KEY", "REDACTED_MINIO_USER"),
        ("MINIO_ENDPOINT", "localhost:9000"),
        ("PG_HOST", "localhost"), ("PG_DB", "investdb"), ("PG_USER", "invest"),
        ("REDIS_HOST", "localhost"), ("REDIS_PORT", "6379"),
    ]:
        os.environ.setdefault(k, v)
    if "PG_PASSWORD" not in os.environ:
        raise RuntimeError(
            "PG_PASSWORD not set; expected in .env or .secrets/pg.env "
            "(see data-pipeline/scripts/cron_dispatcher.py env loader chain)"
        )
    if "MINIO_SECRET_KEY" not in os.environ:
        raise RuntimeError(
            "MINIO_SECRET_KEY not set; expected in .env or .secrets/minio.env"
        )

load_env()

def get_pg_conn():
    return psycopg2.connect(
        host=os.environ["PG_HOST"], port=int(os.environ.get("PG_PORT", 5432)),
        dbname=os.environ["PG_DB"], user=os.environ["PG_USER"],
        password=os.environ["PG_PASSWORD"]
    )

def run_etf_spot():
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.pipeline.pipeline_main import run_etf_spot_only
    return run_etf_spot_only(limit=1486)

def run_etf_pipeline():
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.pipeline.pipeline_main import run_etf_pipeline
    return run_etf_pipeline(days=1, limit=1486)

def run_etf_kline():
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.collector.etf import batch_fetch_etf_hist
    return batch_fetch_etf_hist(start_year=2025, limit=1486)

def run_etf_alpha():
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.signals.etf_alpha import compute_all_etf_signals
    from datetime import date
    result = compute_all_etf_signals(calc_date=date.today())
    return len(result)

SCRIPTS = {
    "etf_spot":      run_etf_spot,
    "etf_pipeline":  run_etf_pipeline,
    "etf_kline":     run_etf_kline,
    "etf_alpha":     run_etf_alpha,
}

def main():
    r = redis.Redis(host=os.environ["REDIS_HOST"], port=int(os.environ.get("REDIS_PORT", 6379)), decode_responses=True)
    
    # 确保 stream 和 consumer group 存在
    try:
        r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except redis.ResponseError:
        pass

    log.info(f"Executor started, listening on {STREAM} group={GROUP} consumer={CONSUMER}")
    
    while True:
        try:
            # 阻塞读取新消息，等待 30 秒超时
            msgs = r.xreadgroup(GROUP, CONSUMER, {STREAM: ">"}, count=1, block=30000)
            if not msgs:
                continue
            
            for stream_name, messages in msgs:
                for msg_id, data in messages:
                    cmd = data.get("cmd", "")
                    log.info(f"Received cmd={cmd} id={msg_id}")
                    
                    start = datetime.now()
                    status = "ok"
                    result = ""
                    error = ""
                    
                    try:
                        if cmd in SCRIPTS:
                            result = SCRIPTS[cmd]()
                        else:
                            error = f"Unknown cmd: {cmd}"
                            status = "error"
                    except Exception as e:
                        error = str(e)
                        status = "error"
                        log.exception(f"Cmd {cmd} failed")
                    
                    duration = (datetime.now() - start).total_seconds()
                    
                    # 回写结果
                    result_key = f"exec_result:{msg_id}"
                    r.hset(result_key, mapping={
                        "cmd": cmd,
                        "status": status,
                        "result": str(result),
                        "error": error,
                        "duration": str(duration),
                        "done_at": datetime.now().isoformat(),
                    })
                    r.expire(result_key, 86400)
                    
                    # ACK
                    r.xack(STREAM, GROUP, msg_id)
                    log.info(f"Cmd {cmd} done status={status} duration={duration:.1f}s")
                    
        except redis.ConnectionError:
            log.warning("Redis connection lost, reconnecting...")
            time.sleep(5)
        except Exception:
            log.exception("Main loop error")
            time.sleep(5)

if __name__ == "__main__":
    main()
