#!/usr/bin/env python3
"""
WOA 通知脚本 — 脚本文件方案 v3（加入 WOA→CIA 回传）
====================================================
步骤：
1. 把执行脚本写到磁盘（包含回传逻辑）
2. XADD 任务到 Redis Stream
3. A2A 发极短触发消息给 WOA
4. WOA 读脚本 → 执行 → 结果回传 CIA → XACK

WOA→CIA 回传方式：
  openclaw message send --channel qqbot --account 1903628521 \
    --message "任务完成：{task_id} status=done" --target <sender_id>
"""

import json
import redis as redis_lib
import subprocess
import sys
import time
import uuid
from datetime import date
from pathlib import Path

# ── 配置 ────────────────────────────────────────────────────
STREAM       = "task_queue"
GROUP        = "woa_workers"
CONSUMER     = "woa_1"
A2A_URL      = "http://127.0.0.1:19100/a2a"
SCRIPT_DIR   = Path("/home/claw/invest-infra/data-pipeline/scripts/woa_tasks")
OPENCLAW_BIN = "/home/claw/.npm-global/bin/openclaw"
QQ_ACCOUNT   = "1903628521"
QQ_TARGET    = "43C77867478A33B101FA705AA70754E3"  # CIA's QQ sender_id

PG_PASSWORD     = "REDACTED_PG_PASSWORD"
PG_USER         = "invest"
DEFAULT_COMPANY_ID = 5233

# ── 通知脚本内容 ───────────────────────────────────────────
NOTIFY_SCRIPT = (
    "import subprocess, sys\n"
    "msg = sys.argv[1] if len(sys.argv) > 1 else 'WOA任务完成'\n"
    "result = subprocess.run(\n"
    "    ['REPLACE_OPENCLAW_BIN', 'message', 'send',\n"
    "     '--channel', 'qqbot',\n"
    "     '--account', 'REPLACE_QQ_ACCOUNT',\n"
    "     '--message', msg,\n"
    "     '--target', 'REPLACE_QQ_TARGET'],\n"
    "    capture_output=True, text=True)\n"
    "print(result.stdout.strip())\n"
    "if result.returncode != 0:\n"
    "    print('通知失败:', result.stderr.strip())\n"
)

# ── 执行脚本内容（包含 WOA→CIA 回传）────────────────────
EXEC_SCRIPT = (
    "import redis, json, time, psycopg2, subprocess\n"
    "r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)\n"
    "STREAM = 'task_queue'; GROUP = 'woa_workers'; CONSUMER = 'woa_1'\n"
    "OPENCLAW = 'REPLACE_OPENCLAW_BIN'\n"
    "QQ_ACCOUNT = 'REPLACE_QQ_ACCOUNT'\n"
    "QQ_TARGET = 'REPLACE_QQ_TARGET'\n\n"
    "def notify_cia(msg):\n"
    "    subprocess.run(\n"
    "        [OPENCLAW, 'message', 'send',\n"
    "         '--channel', 'qqbot',\n"
    "         '--account', QQ_ACCOUNT,\n"
    "         '--message', msg,\n"
    "         '--target', QQ_TARGET],\n"
    "        capture_output=True, text=True)\n\n"
    "msgs = r.xreadgroup(GROUP, CONSUMER, {STREAM: '>'}, count=1, block=5000)\n"
    "if not msgs: print('队列空'); exit()\n\n"
    "for stream_name, mgs in msgs:\n"
    "    for msg_id, fields in mgs:\n"
    "        task_id = fields['task_id']\n"
    "        task_type = fields['task_type']\n"
    "        payload = json.loads(fields['payload'])\n"
    "        callback = json.loads(fields['callback'])\n"
    "        print(f'claimed: {msg_id} task={task_type} tid={task_id[:8]}')\n\n"
    "        # 执行\n"
    "        time.sleep(2)\n\n"
    "        if callback.get('mode') == 'db_write':\n"
    "            conn = psycopg2.connect(\n"
    "                host='localhost', port=5432, dbname='investdb',\n"
    "                user='REPLACE_PG_USER', password='REPLACE_PG_PWD')\n"
    "            cur = conn.cursor()\n"
    "            cur.execute('''\n"
    "                INSERT INTO investment_memos\n"
    "                (company_id,title,memo_date,memo_type,summary,body_md,sections_json,\n"
    "                 tags,generated_by,model_used,total_tokens,quality_score,review_status,created_at)\n"
    "                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())\n"
    "                ON CONFLICT DO NOTHING''',\n"
    "                [REPLACE_COMPANY_ID,\n"
    "                 f\"{task_type} - {payload.get('date','')}\",\n"
    "                 payload.get('date','2026-06-01'),\n"
    "                 task_type,\n"
    "                 f\"{task_type}完成\",\n"
    "                 f\"## {task_type}\\n日期：{payload.get('date','')}\\n范围：{payload.get('scope','')}\",\n"
    "                 json.dumps({'fundamental':{'score':0.72,'notes':'WOA执行'}}),\n"
    "                 [task_type],\n"
    "                 'jiuwenswarm_woa_v1',\n"
    "                 'MiniMax-M2.7',\n"
    "                 100, 0.72, 'pending'])\n"
    "            conn.commit(); cur.close(); conn.close()\n"
    "            print(f'PG写入完成: {task_id}')\n\n"
    "        # 回传 CIA\n"
    "        notify_cia(f'✅ 任务完成 [{task_id[:8]}] {task_type} - {payload.get(\"date\",\"\")}')\n\n"
    "        # XACK\n"
    "        r.xack(STREAM, GROUP, msg_id)\n"
    "        print(f'XACK {msg_id} done')\n"
    "        print(f'任务完成: {task_id}')\n"
)


def write_task_script(tid: str) -> Path:
    SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    script_path = SCRIPT_DIR / f"task_{tid[:8]}.py"
    content = (
        EXEC_SCRIPT
        .replace("REPLACE_OPENCLAW_BIN", OPENCLAW_BIN)
        .replace("REPLACE_PG_PWD", PG_PASSWORD)
        .replace("REPLACE_PG_USER", PG_USER)
        .replace("REPLACE_COMPANY_ID", str(DEFAULT_COMPANY_ID))
        .replace("REPLACE_QQ_ACCOUNT", QQ_ACCOUNT)
        .replace("REPLACE_QQ_TARGET", QQ_TARGET)
    )
    script_path.write_text(content)
    return script_path


def xadd_task(task_type: str, payload: dict) -> tuple[str, str, Path]:
    r = redis_lib.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    tid = str(uuid.uuid4())
    script_path = write_task_script(tid)

    msg_id = r.xadd(STREAM, {
        "task_id":         tid,
        "task_type":       task_type,
        "payload":         json.dumps(payload),
        "callback":        json.dumps({"mode": "db_write", "target": "investment_memos"}),
        "priority":        "10",
        "sla_seconds":    "180",
        "max_retries":     "2",
        "idempotency_key": f"openclaw|{task_type}|{tid}",
        "tags":            json.dumps(["task", task_type]),
        "created_at":      "2026-06-01T21:45:00+08:00",
    })
    return msg_id, tid, script_path


def curl_a2a(message: str, timeout: int = 15) -> dict | None:
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "SendMessage",
        "params": {"message": {"role": 1, "parts": [{"text": message}]}}
    }
    cmd = [
        "curl", "-s", "--ipv4", "-m", str(timeout), "-X", "POST",
        "-H", "Content-Type: application/json",
        "-d", json.dumps(payload), A2A_URL,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return None
        return json.loads(result.stdout) if result.stdout.strip() else None
    except:
        return None


def reset_woa() -> None:
    result = curl_a2a("new", timeout=10)
    if result:
        print(f"[WOA] new: {result.get('result',{}).get('task',{}).get('status',{}).get('state','?')}", file=sys.stderr)


def send_trigger(tid: str, script_path: Path) -> None:
    msg = (
        f"📋 请执行任务脚本：{script_path}\n\n"
        f"执行方式：python3 {script_path}\n"
        f"完成后请输出：执行状态"
    )
    result = curl_a2a(msg, timeout=15)
    if result:
        print(f"[A2A] ✓ state={result.get('result',{}).get('task',{}).get('status',{}).get('state','?')}", file=sys.stderr)
    else:
        print("[A2A] ⚠ 超时（WOA 异步执行中，正常）", file=sys.stderr)


def main() -> int:
    print(f"{'='*60}", file=sys.stderr)
    print("  WOA 通知测试 v3（含 WOA→CIA 回传）", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)

    # 1. Redis 检查 & 清理
    r = redis_lib.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    r.ping()
    entries = r.xrange(STREAM, '-', '+')
    if entries:
        for msg_id, _ in entries:
            r.xdel(STREAM, msg_id)
        print(f"[XDEL] 清理 {len(entries)} 条旧记录", file=sys.stderr)

    # 2. XADD 新任务
    msg_id, tid, script_path = xadd_task(
        task_type="morning_collect",
        payload={"date": date.today().isoformat(), "scope": "沪深300成分", "sources": ["quotes"]},
    )
    print(f"[XADD] {msg_id} tid={tid[:8]} script={script_path.name}", file=sys.stderr)

    # 3. 重置 WOA session
    reset_woa()
    time.sleep(0.5)

    # 4. 发触发通知
    send_trigger(tid, script_path)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"通知已发送，WOA 执行中（包含回传逻辑）", file=sys.stderr)
    print(f"10秒后验证结果...", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)

    time.sleep(10)

    # 5. 验证
    r2 = redis_lib.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    pending = r2.xpending(STREAM, GROUP)
    info = r2.xinfo_stream(STREAM)
    print(f"[验证] stream={info['length']} pending={pending['pending']}", file=sys.stderr)

    try:
        import psycopg2
        conn = psycopg2.connect(host="localhost", port=5432, dbname="investdb", user=PG_USER, password=PG_PASSWORD)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM investment_memos WHERE generated_by='jiuwenswarm_woa_v1' AND created_at > NOW() - INTERVAL '2 minutes'")
        count = cur.fetchone()[0]
        print(f"[PG] investment_memos 新增: {count} 条", file=sys.stderr)
        cur.close(); conn.close()
    except Exception as e:
        print(f"[PG] 查询失败: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())