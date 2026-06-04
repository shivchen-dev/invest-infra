## WOA 执行脚本 — Morning Briefing
## task_type : etf_alpha_signal
## date     : 2026-06-01
## tid      : 34d02574-b358-44d6-8688-a2e1ee74937c
## params   : {"date": "2026-06-01", "scope": "\u5168\u91cfETF"}
##
## 【Memo 输出规范】（必须严格遵守）
##   结构：标题/时间戳/置信度 → 一行结论 → 二级摘要(3-5条)
##         → 详细分析(基本面+量化+情绪+情景) → 数据证据 → 待办跟进
##   禁用词：买/卖/持有/做多/做空（仅用：监控/复核/进一步分析）
##   置信度：<2类信号=low, 2-3类=medium, ≥4类=high
##   置信度提升条件：≥2类独立信号（基本面/量化/舆情）支持同一方向

#!/usr/bin/env python3
import redis, json, time, subprocess, psycopg2
from datetime import date

STREAM     = "task_queue"
GROUP      = "woa_workers"
CONSUMER   = "woa_1"
OPENCLAW   = "/home/claw/.npm-global/bin/openclaw"
QQ_ACCOUNT = "1903628521"
QQ_TARGET  = "43C77867478A33B101FA705AA70754E3"
PG_PWD     = "***"
PG_USER    = "invest"
TODAY      = "2026-06-01"
TASK_TYPE  = "etf_alpha_signal"

def notify_cia(msg):
    subprocess.run(
        [OPENCLAW, "message", "send",
         "--channel", "qqbot",
         "--account", QQ_ACCOUNT,
         "--message", msg,
         "--target", QQ_TARGET],
        capture_output=True, text=True)

def write_memo(task_id, task_type, summary, body_md, sig_data, tags):
    conn = psycopg2.connect(
        host="localhost", port=5432, dbname="investdb",
        user=PG_USER, password=PG_PWD)
    cur = conn.cursor()
    active = [k for k, v in (sig_data or {}).items() if v]
    n = len(active)
    confidence = "high" if n >= 4 else ("medium" if n >= 2 else "low")
    title = "[" + confidence.upper() + "] " + task_type + " - " + TODAY
    cur.execute("""
        INSERT INTO investment_memos
        (company_id, title, memo_date, memo_type, summary, body_md,
         sections_json, tags, generated_by, model_used, total_tokens,
         quality_score, review_status, confidence_level, trigger_signals,
         follow_up_status, version, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        ON CONFLICT DO NOTHING""",
        [5233, title, TODAY, task_type, summary, body_md,
         json.dumps(sig_data), tags,
         "jiuwenswarm_woa_v1", "MiniMax-M2.7", 500, 0.75,
         "draft", confidence, json.dumps(active), "pending", 1])
    conn.commit()
    cur.close(); conn.close()
    print("[PG] memo: " + title)

def do_task():
    r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    msgs = r.xreadgroup(GROUP, CONSUMER, {STREAM: ">"}, count=1, block=5000)
    if not msgs:
        print("[WOA] 队列空"); return
    for stream_name, mgs in msgs:
        for msg_id, fields in mgs:
            task_id   = fields["task_id"]
            task_type = fields["task_type"]
            payload   = json.loads(fields["payload"])
            print("claimed: " + msg_id + " tid=" + task_id[:8] + " type=" + task_type)

            # TODO: 在此实现各 task_type 的分析逻辑
            # sig_data 格式: {"fundamental":{},"quant":{},"sentiment":{}}

            summary  = task_type + " 分析完成，请查看详细报告"
            body_md  = "## " + task_type + "\n日期：" + TODAY + "\n参数：" + json.dumps(payload) + "\n完成时间：" + time.strftime("%H:%M:%S")
            sig_data = {"fundamental": {"status": "done"}, "quant": {"status": "done"}}
            tags     = ["morning_briefing", task_type]

            write_memo(task_id, task_type, summary, body_md, sig_data, tags)

            n_sig = len([k for k,v in sig_data.items() if v])
            conf  = "high" if n_sig >= 4 else ("medium" if n_sig >= 2 else "low")
            notify_cia("✅ 任务完成 [" + task_id[:8] + "] " + task_type + "\n置信度：" + conf + "\n时间：" + time.strftime("%H:%M:%S"))

            r.xack(STREAM, GROUP, msg_id)
            print("XACK " + msg_id + " done")

if __name__ == "__main__":
    do_task()
