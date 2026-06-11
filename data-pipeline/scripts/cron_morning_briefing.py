#!/usr/bin/env python3
"""
Morning Briefing - OpenClaw cron 触发脚本
==========================================
06:30 周一~周五触发:
  1. 写入 Morning Briefing prompt 到 Redis task_queue(WOA 任务)
  2. 通过 A2A 通知 WOA 去 claim 并执行
  3. WOA 完成 → 写 CIA prompt 到 Redis cia_task_queue → QQ 通知 CIA 去领
  4. CIA claim → 执行 prompt → 记录到 memory(不向 QQ 推送)
  5. 09:00 report_engine 读取 WOA memo + market_cache → 融合推送盘前报(唯一出口)
"""

import json as _json
import uuid
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# 确保能导入 reports 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import redis


# ── Redis 配置 ────────────────────────────────────────────────
STREAM         = "task_queue"        # WOA 领取的任务流
CIA_STREAM     = "cia_task_queue"   # CIA 领取的 prompt 流
GROUP          = "woa_workers"
CIA_GROUP      = "cia_workers"
CONSUMER       = "woa_1"
CIA_CONSUMER   = "cia_1"
REDIS_HOST     = "localhost"
REDIS_PORT     = 6379
REDIS_DB       = 0

# ── A2A 配置(IPv4 强制)───────────────────────────────────────
A2A_URL    = "http://127.0.0.1:19100/a2a"

# ── QQ 统一推送(使用 reports.qq_push)───────────────────────────
QQ_ACCOUNT    = "1903628521"   # 发信账号(与 qq_push.py 默认一致)
QQ_TARGET     = "43C77867478A33B101FA705AA70754E3"  # 收信用户 ID

# ── PG 连接信息(用于查询最新数据日期)────────────────────────────
_PG_KW = dict(host='localhost', port=5432, dbname='investdb', user='invest')


def _get_latest_data_date(today: str) -> str:
    """返回最新有数据的交易日(优先 today,其次最近一个有数据的交易日)。"""
    import psycopg2
    try:
        import os as _os
        pw = _os.environ.get('PG_PASSWORD') or open('/home/claw/invest-infra/data-pipeline/.env').read().split('PG_PASSWORD=')[1].split()[0]
        conn = psycopg2.connect(host='localhost', port=5432, dbname='investdb', user='invest', password=pw)
        cur = conn.cursor()
        # 查 index_quotes 最新有数据的交易日
        cur.execute("SELECT MAX(trade_date) FROM index_quotes")
        idx_date = cur.fetchone()[0]
        # 查 etf_alpha_signals 最新有数据的交易日
        cur.execute("SELECT MAX(calc_date) FROM etf_alpha_signals")
        alpha_date = cur.fetchone()[0]
        conn.close()
        latest = max(idx_date, alpha_date) if idx_date and alpha_date else None
        if latest is None:
            return today
        from datetime import date as date_cls
        today_date = date_cls.fromisoformat(today)
        if latest >= today_date:
            return today
        return latest.isoformat()
    except Exception as e:
        return today  # 出错时降级用 today


def _qq_notify(text: str, silent: bool = False) -> bool:
    import subprocess
    cmd = ['/home/claw/.npm-global/bin/openclaw', 'message', 'send', '--channel', 'qqbot', '--account', '1903628521', '--target', '43C77867478A33B101FA705AA70754E3', '--message', text]
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=10)
        if cp.returncode == 0:
            print(f'[QQ] ✓ {text[:40]}', file=sys.stderr)
        else:
            print(f'[QQ] ✗ {cp.stderr[:100]}', file=sys.stderr)
        return cp.returncode == 0
    except Exception as e:
        print(f'[QQ] ✗ {e}', file=sys.stderr)
        return False


# ══════════════════════════════════════════════════════════════
#  Morning Briefing WOA 任务 prompt
# ══════════════════════════════════════════════════════════════

def _build_woa_prompt(today: str, latest_data_date: str) -> str:
    return f"""📋 Morning Briefing - 今日 {today}
==============================
你作为团队协调者,需要完成 5 个并行任务,最终整合输出一份盘前洞察。

【重要】实际数据截止日:{latest_data_date}。今日 {today} 的行情/因子数据可能在采集中或尚未生成。
所有数据查询一律使用 latest_data_date='{latest_data_date}' 作为截止日期,并在报告中明确标注「数据截至 YYYY-MM-DD」。

## 任务清单(5 个,全部并行启动)

### 任务 1:morning_collect
- 职责:采集宏观 + 指数 + 代表性成分股数据
- 数据源:query_index_kline()(沪深300指数)+ query_stock_kline()(成分股5日K线)
- 产出:沪深300点位/涨跌幅/成交量 + 成分股简报,每个数据标注来源表和字段

### 任务 2:factor_calculation
- 职责:计算 5 类因子信号
- 因子:动量、价值、质量、资金流、技术面
- 产出:各因子信号状态 + 综合评分

### 任务 3:etf_alpha_signal
- 职责:ETF alpha 信号分析
- 数据源:query_etf_spot()(实时行情)+ get_etf_alpha_signals(today)(因子信号)
- 产出:重点 ETF 信号(代码/方向/置信度),标注来源表

### 任务 4:risk_monitoring
- 职责:风险监控(流动性/集中度/情绪)
- 数据源:query_risk_signals(today)(风险信号)+ 沪深300波动率(index_quotes)
- 产出:风险等级(低/中/高)+ 触发信号,标注数据来源

### 任务 5:daily_report
- 职责:综合日报
- 数据源:morning_collect + factor_calculation + etf_alpha_signal + risk_monitoring 所有输出
- 产出:结构化日报(中性/悲观/乐观三种情景),所有数据必须来自本地 PG

## 执行流程

1. 从 Redis 读取任务:XREADGROUP GROUP woa_workers CONSUMER woa_1 BLOCK 5000 COUNT 1 STREAMS task_queue ">"
2. 组建 5 人团队(信息采集/因子计算/ETF分析/风险监控/综合报告),并行分发任务
3. 等待各子任务完成
4. 整合 5 个任务输出 → 结构化盘前洞察
5. 结果写入 PG investment_memos(5 条 memo,company_id=5233)

## 数据源(必须全部从本地 PostgreSQL 获取,禁止调用外部 API)

### 可用查询函数(在 /home/claw/invest-infra/data-pipeline/src/ 下)

| 查询目标 | 函数 | 表 | 关键字段 |
|---------|------|-----|---------|
| 沪深300指数5日K线 | query_index_kline(['000300'], start_date, latest_data_date) | index_quotes / index_daily | close, change_pct, volume |
| 个股K线 | query_stock_kline(['600519','601398','000001','000002','600036'], start_date, latest_data_date) | stock_daily | code, close, change_pct |
| ETF实时行情 | query_etf_spot() | etf_quotes | code, name, iopv, premium_ratio, turnover_rate, main_flow |
| ETF因子信号 | get_etf_alpha_signals(latest_data_date) | etf_alpha_signals | code, momentum, value, quality, money_flow, tech, composite_score |
| 风险信号 | query_risk_signals(latest_data_date) | risk_alerts | alert_type, severity, trigger_condition |
| 新闻舆情 | query_news(start_date, latest_data_date) | news_articles | title, content_summary, sentiment_label |
| 南向资金 | query_south_flow(latest_data_date) | south_flow_hist | hsgt_type, net_buy, buy, sell |
| 北向成交额 | query_north_turnover(latest_data_date) | north_turnover_hist | nf_deal_amt, ssc_deal_amt, st_deal_amt |

### 数据获取示例

```python
# 沪深300指数(调用本地函数,不走外部API)
df = query_index_kline(['000300'], start_date=latest_data_date, end_date=latest_data_date)
hs300 = df[df['code']=='000300'].iloc[-1]
print(f'沪深300：{{hs300["close"]}} 点 ({{hs300["change_pct"]*100:+.2f}}%) 数据截至 {latest_data_date}')  # 来源：index_quotes.close

# ETF行情 + 因子
etf_df = query_etf_spot()
alpha_df = get_etf_alpha_signals(latest_data_date)
# 合并得出信号

# 新闻舆情
news_df = query_news(latest_data_date, latest_data_date)
```

### 连接信息
- PG: host=localhost, port=5432, db=investdb, user=invest, password=<PG_PASSWORD>
- Redis: localhost:6379/0

### ⚠️ 禁止事项
- 禁止调用 RssCast / akshare / 任何外部行情 API
- 数据缺失时:如实标注「无数据/数据缺失」,禁止自行推断或编造
  示例:「沪深300:无数据(index_quotes 当日无记录)」
- 禁止在报告结论中编造数据
- 每个判断必须标注数据来源:[表名.字段名] [具体值] [日期]
- 示例:沪深300收盘 4935.39点(index_quotes.close)【来源:index_quotes,日期:2026-06-02】

## WOA 完成后的操作(必须全部执行)

### 第一步:生成 CIA prompt 并写入 Redis

将以下 JSON 写入 Redis Stream cia_task_queue(用 XADD):

```json
{{
  "task_id": "<新UUID>",
  "task_type": "cia_briefing",
  "payload": {{
    "prompt": "<完整的 CIA prompt(见下方生成规则)>",
    "date": "{today}",
    "woa_summary": {{
      "任务完成": "5/5",
      "综合置信度": "HIGH/MEDIUM/LOW",
      "风险": "无/有(简述)",
      "建议关注": "<1-2条>"
    }}
  }},
  "created_at": "<ISO timestamp>"
}}
```

### 第二步:QQ 通知 CIA

用以下命令发送简短通知(只有这一句,不要发送其他内容):

```bash
/home/claw/.npm-global/bin/openclaw message send \
  --channel qqbot \
  --account 1903628521 \
  --target 43C77867478A33B101FA705AA70754E3 \
  --message "✅ Morning Briefing 完成,prompt 在 Redis cia_task_queue,task_id=<新UUID前8位>"
```

⚠️ QQ 消息必须极短,只包含"完成通知 + task_id",不要发送任何报告内容

### 第三步:XACK 确认

执行:XACK task_queue woa_workers <msg_id>

---

## CIA prompt 生成规则

WOA 整合完 5 个子任务后,生成一个让 CIA 直接工作的 prompt,内容包括:

1. **WOA 工作摘要**(任务完成数/置信度/风险/建议)
2. **数据来源说明**(今日 5 条 memo 已在 PG investment_memos,company_id=5233,memo_date={today})
3. **CIA 的任务**:
   - 从 PG 读取今日 5 条 memo
   - 基于已有数据生成最终盘前洞察
   - 按照标准格式输出
4. **输出格式**(必须严格按照以下格式,每个数据标注来源):

```
📊 盘前洞察 {today}
==================

【今日市场概况】
- 沪深300:{{点位}} ({{涨跌幅}}%),{{成交量}}亿 【来源:index_quotes】
- 情绪判断:{{偏多/中性/偏空}} 【来源:index_quotes.change_pct趋势】

【因子信号】
- 动量:{{看多/中性/看空}}({{置信度}})【来源:etf_alpha_signals.momentum】
- 价值:{{...}}【来源:etf_alpha_signals.value】
- 质量:{{...}}【来源:etf_alpha_signals.quality】
- 资金流:{{...}}【来源:etf_alpha_signals.money_flow】
- 技术面:{{...}}【来源:etf_alpha_signals.tech】

【ETF 信号】
- {{code}}:{{信号}}({{置信度}})【来源:etf_alpha_signals.composite_score】

【风险提示】
{{无风险写"今日无明显风险信号"}}
{{有风险写:具体描述【来源:risk_alerts.alert_type】}}

【情景假设】
- 中性:{{条件}} → {{预期}}
- 悲观:{{条件}} → {{应对}}
- 乐观:{{条件}} → {{机会}}

【今日关注】
- {{优先级1}}
- {{优先级2}}
```

⚠️ 所有 {{xxx}} 必须用真实数据填充,不得留空或编造

5. **执行原则**:
   - 只输出分析结论,不提供投资建议
   - 数据从 PG 读取,不主观臆断
   - 置信度说明信号强度

---

## PG investment_memos 写入格式
每条 memo:
- company_id: 5233
- title: [HIGH/MEDIUM/LOW] task_type - {today}
- memo_date: {today}
- memo_type: task_type
- summary: 一句话结论
- body_md: 详细分析
- sections_json: {{}}
- tags: ['morning_briefing', task_type, 'rsscast']
- generated_by: 'jiuwenswarm_woa_v1'
- model_used: 'MiniMax-M2.7'
- total_tokens: 500
- quality_score: 0.75
- review_status: 'draft'
- confidence_level: HIGH(≥4信号)/MEDIUM(2-3信号)/LOW(<2信号)
- trigger_signals: JSON,key=信号类型,value=信号内容
- follow_up_status: 'pending'
- version: 1

**PG 连接信息**(请务必使用以下正确配置):
- host: localhost
- port: 5432
- dbname: investdb
- user: invest
- password: <PG_PASSWORD>

⚠️ 注意:如果连接失败请检查密码是否为 <PG_PASSWORD>,不要使用其他密码

## 禁忌
- 禁止使用:买/卖/持有/做多/做空
- 只能用:监控/复核/进一步分析/关注

## 执行方式
- 请以「集群模式」启动团队协作(spawn_mode=cluster, SkillUseRail=true, is_proactive=true)
- 并行执行 5 个子任务
- 等所有子任务完成后整合输出
- 整合完成后:
  1. 生成 CIA prompt 写入 cia_task_queue
  2. QQ 通知 CIA(极短消息)
  3. XACK 确认
  4. 不要等待 CIA 完成,直接结束
"""


STATUS_TAG = "/tmp/woa_morning_briefing_status.json"

def _write_status_tag(task_id: str, phase: str = "enqueued"):
    with open(STATUS_TAG, "w") as f:
        _json.dump({
            "task_id": task_id,
            "phase": phase,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, f)


# ══════════════════════════════════════════════════════════════
#  A2A 通知(备用;主反馈改为日志轮询)
# ══════════════════════════════════════════════════════════════

def _a2a_health_check() -> bool:
    """检查 A2A gateway 是否可达,避免向不可用服务发送消息。"""
    import subprocess
    cmd = [
        "curl", "-s", "--ipv4", "-m", "5", "-o", "/dev/null", "-w", "%{http_code}",
        A2A_URL,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        http_code = result.stdout.strip()
        if result.returncode == 0 and http_code != "000":
            print(f"[A2A] health OK (HTTP {http_code})", file=sys.stderr)
            return True
        print(f"[A2A] health FAIL (curl_exit={result.returncode}, http={http_code})", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[A2A] health check error: {e}", file=sys.stderr)
        return False


def _a2a_notify(message: str) -> bool:
    # 先确认 gateway 可达,再发消息
    if not _a2a_health_check():
        print("[A2A] ⚠ gateway 不可达,跳过 SendMessage", file=sys.stderr)
        return False

    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "SendMessage",
            "params": {
                "message": {
                    "role": 1,
                    "parts": [{"text": message}]
                }
            }
        }
        import subprocess
        cmd = [
            "curl", "-s", "--ipv4", "-m", "20", "-X", "POST",
            "-H", "Content-Type: application/json",
            "-d", _json.dumps(payload), A2A_URL,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            try:
                resp = _json.loads(result.stdout)
                state = resp.get("result", {}).get("task", {}).get("status", {}).get("state", "?")
                print(f"[A2A] WOA state: {state}", file=sys.stderr)
            except Exception:
                # 只要 curl 成功送达且有响应(哪怕无 result 字段),就算成功
                # WOA 通过 E2A wire 异步响应,不走 HTTP 回包
                print(f"[A2A] 消息已送达(响应走 E2A wire)", file=sys.stderr)
            return True
        # curl 送达但 HTTP 响应为空(WS 连接占用端口,但仍算送达)
        if result.returncode == 0 and not result.stdout.strip():
            print("[A2A] 消息已送达(E2A wire 异步响应)", file=sys.stderr)
            return True

        # curl 超时或返回码非零 → 真正失败,不是 E2A wire
        print(f"[A2A] ⚠ 发送失败 (curl_exit={result.returncode}, stderr={result.stderr[:200]})", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[A2A] 通知失败: {e}", file=sys.stderr)
        return False


# ══════════════════════════════════════════════════════════════
#  任务入队(单任务 + 完整 prompt)
# ══════════════════════════════════════════════════════════════

def enqueue_morning_briefing(r: redis.Redis) -> dict:
    today = date.today().isoformat()
    latest_data_date = _get_latest_data_date(today)
    task_id = str(uuid.uuid4())

    prompt = _build_woa_prompt(today, latest_data_date)

    # 写入 Redis Stream(WOA 任务)
    msg_id = r.xadd(STREAM, {
        "task_id":    task_id,
        "task_type":  "morning_briefing",
        "payload":    _json.dumps({
            "prompt": prompt,
            "date": today,
            "note": "完整 Morning Briefing prompt,见 payload.prompt 字段"
        }),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    print(f"[XADD] morning_briefing {msg_id} task_id={task_id[:8]}...", file=sys.stderr)

    # 写入状态标记文件(cron_woa_status.py 轮询依据)
    _write_status_tag(task_id, phase="enqueued")

    return {"task_id": task_id, "msg_id": msg_id, "date": today}


# ══════════════════════════════════════════════════════════════
#  main
# ══════════════════════════════════════════════════════════════

def main() -> int:
    today = date.today().isoformat()
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  Morning Briefing  {today}", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)

    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
        r.ping()
        print(f"[Redis] ✓ {REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}\n", file=sys.stderr)
    except redis.ConnectionError as e:
        print(f"[Redis] 连接失败: {e}", file=sys.stderr)
        return 1

    task_info = enqueue_morning_briefing(r)
    _qq_notify("📋 Morning Briefing 任务已下发 task_id=" + task_info["task_id"][:8] + " WOA 正在处理中...")
    # A2A 通知 WOA(只发简短通知,完整 prompt 在 Redis task_queue)
    a2a_msg = (
        f"📋 Morning Briefing 待执行\n"
        f"今日: {today}\n"
        f"请用 XREADGROUP 领取 task_queue 中的完整任务,执行完成后\n"
        f"结果写入 PG investment_memos + cia_task_queue + QQ 通知 + XACK\n"
        f"task_id: {task_info['task_id']}"
    )

    print("[A2A] 发送触发消息...\n", file=sys.stderr)
    ok = _a2a_notify(a2a_msg)
    if ok:
        print("[A2A] ✓ 触发消息已送达\n", file=sys.stderr)
    else:
        print("[A2A] ⚠ 发送失败\n", file=sys.stderr)

    info = r.xinfo_stream(STREAM)
    print(f"[Stream] {STREAM}: length={info['length']} groups={info['groups']}",
          file=sys.stderr)
    print(f"\n{'='*60}", file=sys.stderr)
    print("Morning Briefing 任务下发完成", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())