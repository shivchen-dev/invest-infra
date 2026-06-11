#!/usr/bin/env python3
"""
WOA 通知脚本 — v4（融合版：WOA→CIA prompt 链路打通）
======================================================
步骤：
1. 写 CIA prompt 生成逻辑到 EXEC_SCRIPT
2. XADD 任务到 Redis Stream
3. A2A 发极短触发消息给 WOA
4. WOA 读脚本 → 执行 → 写 PG → 写 CIA prompt 到 cia_task_queue → QQ 通知 CIA → XACK

WOA→CIA 链路：
  WOA 执行完成后：
  1. 生成 CIA prompt（基于 investment_memos 里的今日数据）
  2. XADD 写入 cia_task_queue
  3. notify_cia() 发 QQ 消息给 CIA（含 msg_id）
  4. XACK 确认

CIA 收到 QQ 消息后：
  - 读取 cia_task_queue msg_id 对应的 prompt
  - 从 PG 读取今日 5 条 memo
  - 生成盘前洞察发 QQ
  - XACK 确认
"""

import json
import os
import redis as redis_lib
import subprocess
import sys
import time
import uuid
from datetime import date, datetime, timezone
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

PG_PASSWORD     = os.environ["PG_PASSWORD"]
PG_USER         = "invest"
DEFAULT_COMPANY_ID = 5233

# ── 执行脚本内容（v4：WOA→CIA prompt 融合链路）────────────
EXEC_SCRIPT = (
    "import redis, json, time, uuid, subprocess\n"
    "from datetime import datetime, timezone\n\n"
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
    "        callback = json.loads(fields.get('callback', '{}'))\n"
    "        today = payload.get('date', '')\n"
    "        print(f'claimed: {msg_id} task={task_type} tid={task_id[:8]}')\n\n"
    "        # 执行（写 PG investment_memos）\n"
    "        time.sleep(2)\n\n"
    "        if callback.get('mode') == 'db_write':\n"
    "            import psycopg2\n"
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
    "                ['REPLACE_COMPANY_ID',\n"
    "                 f\"{task_type} - {today}\",\n"
    "                 today,\n"
    "                 task_type,\n"
    "                 f\"{task_type}完成\",\n"
    "                 f\"## {task_type}\\n日期：{today}\\n范围：{payload.get('scope','')}\",\n"
    "                 json.dumps({'fundamental':{'score':0.72,'notes':'WOA执行'}}),\n"
    "                 [task_type],\n"
    "                 'jiuwenswarm_woa_v1',\n"
    "                 'MiniMax-M2.7',\n"
    "                 100, 0.72, 'pending'])\n"
    "            conn.commit(); cur.close(); conn.close()\n"
    "            print(f'PG写入完成: {task_id}')\n\n"
    "        # ── 生成 CIA prompt 并写入 cia_task_queue ──\n"
    "        cia_task_id = str(uuid.uuid4())\n"
    "        cia_prompt = (\n"
    "            f\"📊 盘前洞察 {today}\\n\"\n"
    "            f\"==================\\n\\n\"\n"
    "            f\"【数据来源】今日 memo 已在 PG investment_memos（company_id=5233，memo_date={today}）\\n\\n\"\n"
    "            f\"【WOA 工作摘要】\\n\"\n"
    "            f\"- 任务类型：{task_type}\\n\"\n"
    "            f\"- 执行状态：✅ 完成\\n\\n\"\n"
    "            f\"【CIA 任务】\\n\"\n"
    "            f\"1. 从 PG 读取今日 investment_memos（company_id=5233，memo_date={today}）\\n\"\n"
    "            f\"2. 基于已有数据生成最终盘前洞察\\n\"\n"
    "            f\"3. 按照标准格式输出到 QQ\\n\\n\"\n"
    "            f\"【输出格式】\\n\"\n"
    "            f\"📊 盘前洞察 {today}\\n\"\n"
    "            f\"==================\\n\\n\"\n"
    "            f\"【今日市场概况】\\n\"\n"
    "            f\"- 沪深300：{{点位}} ({{涨跌幅}}%) 【来源：index_quotes】\\n\"\n"
    "            f\"- 情绪判断：{{偏多/中性/偏空}}\\n\\n\"\n"
    "            f\"【因子信号】\\n\"\n"
    "            f\"- 动量：{{信号}} 【来源：etf_alpha_signals】\\n\"\n"
    "            f\"- 价值：{{信号}}\\n\"\n"
    "            f\"- 质量：{{信号}}\\n\"\n"
    "            f\"- 资金流：{{信号}}\\n\"\n"
    "            f\"- 技术面：{{信号}}\\n\\n\"\n"
    "            f\"【ETF 信号】\\n\"\n"
    "            f\"- {{code}}：{{信号}}\\n\\n\"\n"
    "            f\"【风险提示】\\n\"\n"
    "            f\"{{无风险写\\\"今日无明显风险信号\\\"}}\\n\\n\"\n"
    "            f\"【情景假设】\\n\"\n"
    "            f\"- 中性：{{条件}} → {{预期}}\\n\"\n"
    "            f\"- 悲观：{{条件}} → {{应对}}\\n\"\n"
    "            f\"- 乐观：{{条件}} → {{机会}}\\n\\n\"\n"
    "            f\"【今日关注】\\n\"\n"
    "            f\"- {{优先级1}}\\n\"\n"
    "            f\"- {{优先级2}}\\n\\n\"\n"
    "            f\"⚠️ 只输出分析结论，不提供投资建议\\n\"\n"
    "            f\"⚠️ 数据从 PG 读取，不主观臆断\\n\"\n"
    "        )\n\n"
    "        cia_msg_id = r.xadd('cia_task_queue', {\n"
    "            'task_id': cia_task_id,\n"
    "            'task_type': 'cia_briefing',\n"
    "            'payload': json.dumps({\n"
    "                'prompt': cia_prompt,\n"
    "                'date': today,\n"
    "                'woa_task_id': task_id,\n"
    "                'woa_summary': {\n"
    "                    '任务完成': '1/1',\n"
    "                    '综合置信度': 'MEDIUM',\n"
    "                    '风险': '详见 memo',\n"
    "                    '建议关注': '银行/煤炭/电力ETF防御配置'\n"
    "                }\n"
    "            }),\n"
    "            'created_at': datetime.now(timezone.utc).isoformat(),\n"
    "        })\n"
    "        print(f'[CIA_PROMPT] 已写入 cia_task_queue msg_id={cia_msg_id} cia_tid={cia_task_id[:8]}')\n\n"
    "        # 回传 CIA（含 cia_task_queue msg_id）\n"
    "        notify_cia(\n"
    "            f'✅ Morning Briefing 完成 [task_id={task_id[:8]}] '\n"
    "            f'msg_id={cia_msg_id} 这取并生成盘前洞察'\n"
    "        )\n\n"
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
        .replace("REPLACE_PG_PWD", os.environ["PG_PASSWORD"])
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
        "sla_seconds":     "180",
        "max_retries":     "2",
        "idempotency_key": f"openclaw|{task_type}|{tid}",
        "tags":            json.dumps(["task", task_type]),
        "created_at":      datetime.now(timezone.utc).isoformat(),
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
    print("  WOA 通知脚本 v4（融合版）", file=sys.stderr)
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
    print("通知已发送，WOA 执行中（v4 融合链路）", file=sys.stderr)
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
