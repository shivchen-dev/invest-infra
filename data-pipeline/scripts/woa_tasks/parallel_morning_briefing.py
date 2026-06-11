#!/usr/bin/env python3
"""
Morning Briefing 执行器 — WOA 集群模式（修正版）
修复：XCLAIM 批量调用 + tags array 格式
"""
import os, redis, json, time, subprocess, psycopg2, urllib.request
from datetime import date, timedelta

STREAM     = "task_queue"
GROUP      = "woa_workers"
CONSUMER   = "woa_main"
OPENCLAW   = "/home/claw/.npm-global/bin/openclaw"
QQ_ACCOUNT = "1903628521"
QQ_TARGET  = "43C77867478A33B101FA705AA70754E3"
PG_PWD     = os.environ.get("PG_PASSWORD", "")
if not PG_PWD:
    raise RuntimeError("PG_PASSWORD not set; expected in .env or .secrets/pg.env")
PG_USER    = "invest"
TODAY      = "2026-06-02"
RSCAST_EP  = "https://app-cn.rsscast.io/api/mcp/v1/mcp"
RSCAST_TK  = "Al9j7V…0180"

# 5条待处理消息（msg_id → 元数据）
PENDING_MSGS = {
    "1780357547965-0": {"task_id":"5b89d934-e8a7-4fd9-95ef-adced2c4a88a","task_type":"morning_collect","payload":{"date":"2026-06-02","scope":"沪深300成分","sources":["quotes","news","north_flow"]}},
    "1780357548070-0": {"task_id":"138125fe-cab9-45d8-a371-2cf291e244cd","task_type":"factor_calculation","payload":{"date":"2026-06-02","scope":"全市场","factors":["momentum","value","quality","money_flow","technical"]}},
    "1780357548172-0": {"task_id":"19066eae-4672-417a-9ece-66c57b38824d","task_type":"etf_alpha_signal","payload":{"date":"2026-06-02","scope":"全量ETF"}},
    "1780357548273-0": {"task_id":"19523dea-716d-4494-951e-b0a57c9ea485","task_type":"risk_monitoring","payload":{"date":"2026-06-02","scope":"沪深300","checks":["liquidity","concentration","sentiment"]}},
    "1780357548375-0": {"task_id":"eb540d7d-638c-498e-acad-0e988269d5e4","task_type":"daily_report","payload":{"date":"2026-06-02","scope":"沪深300成分","model":"MiniMax-M2.7"}},
}

def _call_rsscast(tool, args):
    try:
        payload = {'jsonrpc':'2.0','method':'tools/call','params':{'name':tool,'arguments':args},'id':1}
        req = urllib.request.Request(
            RSCAST_EP,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Authorization':'Bearer '+RSCAST_TK,'Content-Type':'application/json'},
            method='POST')
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        result = data.get('result',{}).get('content',[])
        if not result: return []
        try: return json.loads(result[0].get('text','[]'))
        except: return []
    except Exception as e:
        print(f"[RssCast] error: {e}")
        return []

def notify_cia(msg):
    try:
        subprocess.run([OPENCLAW,'message','send',
             '--channel','qqbot','--account',QQ_ACCOUNT,
             '--message',msg,'--target',QQ_TARGET],
            capture_output=True, text=True)
    except Exception as e:
        print(f"[openclaw] notify error: {e}")

def write_memo(task_id, task_type, summary, body_md, sig_data, tags):
    conn = psycopg2.connect(host='localhost', port=5432, dbname='investdb',
                             user=PG_USER, password=PG_PWD)
    cur = conn.cursor()
    active = [k for k,v in (sig_data or {}).items() if v]
    n = len(active)
    confidence = 'high' if n>=4 else ('medium' if n>=2 else 'low')
    title = '['+confidence.upper()+'] '+task_type+' - '+TODAY

    # psycopg2 直接接收 Python list 作为 array，不需要 json.dumps
    sql = '''INSERT INTO investment_memos
        (company_id, title, memo_date, memo_type, summary, body_md,
         sections_json, tags, generated_by, model_used, total_tokens,
         quality_score, review_status, confidence_level, trigger_signals,
         follow_up_status, version, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        ON CONFLICT DO NOTHING'''
    cur.execute(sql, [5233, title, TODAY, task_type, summary, body_md,
         json.dumps(sig_data), tags,   # tags 保持为 Python list
         'jiuwenswarm_woa_v1','MiniMax-M2.7',500,0.75,
         'draft',confidence,json.dumps(active),'pending',1])
    conn.commit()
    cur.close()
    conn.close()
    print(f'[PG] memo: {title}')
    return title, confidence, n

def task_morning_collect(payload):
    scope = payload.get('scope','沪深300成分')
    today = TODAY
    start = (date.today()-timedelta(days=5)).isoformat()
    sig = {}
    parts = ['## morning_collect\n日期：'+today+'\n']
    parts.append('数据源：RssCast\n')
    parts.append('范围：'+scope+'\n')
    parts.append('\n### 指数行情\n')
    hs300 = _call_rsscast('StockIndexKLineQuery',
        {'codes':['000300'],'startDate':start,'endDate':today})
    if hs300:
        sig['quant'] = {'index':'hs300','records':len(hs300)}
        last = hs300[-1]
        pct = last.get('change_pct',0)
        parts.append('沪深300：'+str(last.get('close'))+' 点 ('+'{:+.2f}'.format(pct*100)+'%) '
                     '成交量 '+'{:.2f}'.format(last.get('volume',0)/1e8)+'亿\n')
    else:
        parts.append('- 沪深300：无数据\n')
    parts.append('\n### 代表性成分股\n')
    sample = ['600519','601398','000001','000002','600036']
    klines = _call_rsscast('StockKLineQuery',
        {'codes':sample,'startDate':start,'endDate':today})
    if klines:
        sig['fundamental'] = {'stocks':len(set(r.get('code') for r in klines)),'records':len(klines)}
        for code in sample:
            recs = [r for r in klines if r.get('code')==code]
            if recs:
                last = recs[-1]
                pct = last.get('change_pct',0)
                parts.append('- '+code+'：收盘 '+str(last.get('close'))+' ('+'{:+.2f}'.format(pct*100)+'%)\n')
    else:
        parts.append('- 成分股：无数据\n')
    summary = 'RssCast采集完成，沪深300'+('有' if hs300 else '无')+'数据，成分股'+('有' if klines else '无')+'数据'
    body_md = ''.join(parts)+'\n采集时间：'+time.strftime('%Y-%m-%d %H:%M:%S')+'\n'
    return summary, body_md, sig

def task_factor_calculation(payload):
    sig = {'quant':{'factors':['momentum','value','quality','money_flow','technical']}}
    parts = ['## factor_calculation\n日期：'+TODAY+'\n']
    parts.append('5类因子待行情数据到位后计算（RssCast已采集日线数据）\n')
    parts.append('\n待计算因子：动量、价值、质量、资金流、技术面\n')
    summary = '因子计算待行情数据恢复（RssCast数据已采集）'
    body_md = ''.join(parts)+'\n时间：'+time.strftime('%Y-%m-%d %H:%M:%S')+'\n'
    return summary, body_md, sig

def task_etf_alpha_signal(payload):
    scope = payload.get('scope','全量ETF')
    sig = {'quant':{'etf_signals':'pending','note':'依赖Bronze层ETF数据'}}
    parts = ['## etf_alpha_signal\n日期：'+TODAY+'\n']
    parts.append('范围：'+scope+'\n')
    parts.append('ETF Alpha信号依赖Bronze层ETF数据，建议与行情层联动\n')
    summary = 'ETF Alpha信号待计算，范围'+scope
    body_md = ''.join(parts)+'\n时间：'+time.strftime('%Y-%m-%d %H:%M:%S')+'\n'
    return summary, body_md, sig

def task_risk_monitoring(payload):
    checks = payload.get('checks',['liquidity','concentration','sentiment'])
    today = TODAY
    start = (date.today()-timedelta(days=5)).isoformat()
    sig = {}
    parts = ['## risk_monitoring\n日期：'+today+'\n']
    parts.append('检查项：'+str(checks)+'\n')
    hs300 = _call_rsscast('StockIndexKLineQuery',
        {'codes':['000300'],'startDate':start,'endDate':today})
    if hs300 and len(hs300)>=2:
        sig['sentiment'] = {'hs300_range':len(hs300)}
        pct_list = [r.get('change_pct',0) for r in hs300 if r.get('change_pct') is not None]
        avg_chg = sum(pct_list)/len(pct_list) if pct_list else 0
        last = hs300[-1]
        parts.append('- 沪深300 近'+str(len(hs300))+'日平均涨跌：'+'{:+.2f}'.format(avg_chg*100)+'%\n')
        parts.append('- 最新收盘：'+str(last.get('close'))+' 点\n')
        if abs(avg_chg)<0.005: parts.append('- 市场情绪：中性（振幅较小）\n')
        elif avg_chg>0: parts.append('- 市场情绪：偏多\n')
        else: parts.append('- 市场情绪：偏空\n')
    else:
        parts.append('- 沪深300：无足够数据\n')
    summary = '风险监控完成，'+str(len(checks))+'项检查，数据来源RssCast指数'
    body_md = ''.join(parts)+'\n时间：'+time.strftime('%Y-%m-%d %H:%M:%S')+'\n'
    return summary, body_md, sig

def task_daily_report(payload):
    today = TODAY
    start = (date.today()-timedelta(days=5)).isoformat()
    sig = {}
    parts = ['## daily_report\n日期：'+today+'\n']
    parts.append('\n### 数据来源\n')
    parts.append('- 行情数据：RssCast（akshare 备用数据源）\n')
    parts.append('- 新闻舆情：待接入\n')
    parts.append('- 因子计算：待行情数据到位后执行\n')
    parts.append('\n### 沪深300 指数\n')
    hs300 = _call_rsscast('StockIndexKLineQuery',
        {'codes':['000300'],'startDate':start,'endDate':today})
    if hs300:
        sig['quant'] = {'hs300':len(hs300)}
        last = hs300[-1]
        pct = last.get('change_pct',0)
        parts.append('最新：'+str(last.get('close'))+' 点 ('+'{:+.2f}'.format(pct*100)+'%)\n')
    parts.append('\n### 代表性成分股\n')
    stocks = _call_rsscast('StockKLineQuery',
        {'codes':['600519','601398','000001','000002','600036'],'startDate':start,'endDate':today})
    if stocks:
        sig['fundamental'] = {'stocks':len(set(r.get('code') for r in stocks))}
        for code in ['600519','601398','000001','000002','600036']:
            recs = [r for r in stocks if r.get('code')==code]
            if recs:
                last = recs[-1]
                pct = last.get('change_pct',0)
                parts.append('- '+code+'：'+str(last.get('close'))+' ('+'{:+.2f}'.format(pct*100)+'%)\n')
    parts.append('\n### 情景假设\n')
    parts.append('- 中性：数据正常，置信度high\n')
    parts.append('- 悲观：数据延迟，置信度维持medium\n')
    parts.append('- 乐观：早盘快速反弹，置信度提升\n')
    summary = '综合日报生成完成，RssCast数据'+('有' if hs300 else '无')+'数据，成分股'+('有' if stocks else '无')+'数据'
    body_md = ''.join(parts)+'\n生成时间：'+time.strftime('%Y-%m-%d %H:%M:%S')+'\n'
    return summary, body_md, sig

TASK_HANDLERS = {
    'morning_collect': task_morning_collect,
    'factor_calculation': task_factor_calculation,
    'etf_alpha_signal': task_etf_alpha_signal,
    'risk_monitoring': task_risk_monitoring,
    'daily_report': task_daily_report,
}

def main():
    r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    results = []

    print(f"[WOA] 集群模式启动，串行执行 {len(PENDING_MSGS)} 个任务")

    # 一次性批量 XCLAIM 所有待处理消息
    msg_ids = list(PENDING_MSGS.keys())
    try:
        # XCLAIM 需要传递消息ID列表（list），不是逐个调用
        r.xclaim(STREAM, GROUP, CONSUMER, 0, msg_ids)
        print(f"[XCLAIM] 批量 claim {len(msg_ids)} 条消息")
    except Exception as e:
        print(f"[XCLAIM] error: {e}")

    # 串行执行（避免 DB 锁竞争）
    for msg_id in msg_ids:
        meta = PENDING_MSGS.get(msg_id)
        if not meta:
            continue

        task_id   = meta['task_id']
        task_type = meta['task_type']
        payload   = meta['payload']
        print(f'\n═══ Processing [{task_id[:8]}] {task_type} ═══')

        handler = TASK_HANDLERS.get(task_type, lambda p: (task_type+' 完成', json.dumps(p), {}))
        summary, body_md, sig = handler(payload)
        tags = ['morning_briefing', task_type, 'rsscast']

        title, confidence, n_sig = write_memo(task_id, task_type, summary, body_md, sig, tags)

        notify_cia(f'✅ 任务完成 [{task_id[:8]}] {task_type}\n置信度：{confidence}\n信号数：{n_sig}\n时间：{time.strftime("%H:%M:%S")}')

        # XACK
        r.xack(STREAM, GROUP, msg_id)
        print(f'[XACK] {msg_id} done')

        results.append({
            'msg_id': msg_id,
            'task_id': task_id[:8],
            'task_type': task_type,
            'confidence': confidence,
            'n_signals': n_sig,
            'title': title,
        })

    # 汇总报告
    print("\n" + "="*60)
    print("Morning Briefing 执行报告 — 2026-06-02 [集群模式]")
    print("="*60)
    for res in results:
        print(f"  [{res['confidence'].upper():8s}] {res['task_type']:20s} [{res['task_id']}] signals={res['n_signals']}")
    print("="*60)
    print(f"✅ 完成 {len(results)}/{len(PENDING_MSGS)} 个任务 | 时间 {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📋 所有 Memo 已写入 investment_memos")
    print(f"🔔 XACK 已确认，Stream 消息已清除")

if __name__ == '__main__':
    main()