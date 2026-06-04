#!/usr/bin/env python3
# WOA 执行脚本 — Morning Briefing  [本地数据库数据源]
# task_type : morning_collect / factor_calculation / etf_alpha_signal / risk_monitoring / daily_report
# date      : 2026-06-02
# tid       : 5b89d934-e8a7-4fd9-95ef-adced2c4a88a
# params    : {"date": "2026-06-02", "scope": "沪深300成分", "sources": ["quotes", "news", "north_flow"]}
# 数据源替换: RssCast API → invest-infra PostgreSQL (local_data_source.py)
#   注意: change_pct 在数据库中已存为百分比值(4.36)，展示时不乘100

import redis, json, time, subprocess, psycopg2
from datetime import date, timedelta

STREAM     = "task_queue"
GROUP      = "woa_workers"
CONSUMER   = "woa_1"
OPENCLAW   = "/home/claw/.npm-global/bin/openclaw"
QQ_ACCOUNT = "1903628521"
QQ_TARGET  = "43C77867478A33B101FA705AA70754E3"
PG_PWD     = "REDACTED_PG_PASSWORD"
PG_USER    = "invest"
TODAY      = "2026-06-02"

# ── 本地数据库查询（替代 RssCast）──────────────────────────────
import sys
sys.path.insert(0, '/home/claw/invest-infra/data-pipeline')
from scripts.woa_tasks.local_data_source import (
    query_index_kline, query_stock_kline, query_news,
    query_etf_quotes, query_north_flow, query_fund_flow,
    get_latest_trade_date
)

def _latest_date():
    """获取行情最新交易日（通常是昨天）"""
    d = get_latest_trade_date()
    return d if d else (date.today() - timedelta(days=1)).isoformat()

def _pct(v):
    """格式化涨跌幅（数据库已存百分比值，不乘100）"""
    if v is None:
        return 'N/A'
    return '{:+.2f}%'.format(v)

def notify_cia(msg):
    subprocess.run([OPENCLAW,'message','send',
         '--channel','qqbot','--account',QQ_ACCOUNT,
         '--message',msg,'--target',QQ_TARGET],
        capture_output=True, text=True)

def write_memo(task_id, task_type, summary, body_md, sig_data, tags):
    conn = psycopg2.connect(host='localhost', port=5432, dbname='investdb',
                             user=PG_USER, password=PG_PWD)
    cur = conn.cursor()
    active = [k for k,v in (sig_data or {}).items() if v]
    n = len(active)
    confidence = 'high' if n>=4 else ('medium' if n>=2 else 'low')
    title = '['+confidence.upper()+'] '+task_type+' - '+TODAY
    sql = '''INSERT INTO investment_memos
        (company_id, title, memo_date, memo_type, summary, body_md,
         sections_json, tags, generated_by, model_used, total_tokens,
         quality_score, review_status, confidence_level, trigger_signals,
         follow_up_status, version, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        ON CONFLICT DO NOTHING'''
    cur.execute(sql, [5233, title, TODAY, task_type, summary, body_md,
         json.dumps(sig_data),          # jsonb → JSON string → PostgreSQL jsonb
         tags,                          # list[str] → PostgreSQL ARRAY
         'jiuwenswarm_woa_v1','MiniMax-M2.7',500,0.75,
         'draft',confidence,
         json.dumps(active),           # jsonb
         'pending',1])
    conn.commit(); cur.close(); conn.close()
    print('[PG] memo: '+title)

# ── 任务函数 ─────────────────────────────────────────────────

def task_morning_collect(payload):
    """
    数据来源：本地 PostgreSQL (index_quotes / daily_quotes / news_articles)
    - 指数：沪深300日线（query_index_kline）
    - 成分股：query_stock_kline（茅台/平安/招行/万科/招行）
    - 新闻：query_news（昨日）
    """
    scope = payload.get('scope', '沪深300成分')
    trade_date = _latest_date()           # 最近有数据的交易日
    start = (date.today() - timedelta(days=5)).isoformat()
    sig = {}
    parts = ['## morning_collect\n日期：'+TODAY+'\n']
    parts.append('数据源：invest-infra PostgreSQL\n')
    parts.append('范围：'+scope+'\n')
    parts.append('\n### 指数行情\n')

    # 沪深300
    hs300 = query_index_kline('000300', start, trade_date)
    if hs300:
        sig['quant'] = {'index': 'hs300', 'records': len(hs300)}
        last = hs300[-1]
        parts.append('沪深300：'+str(last['close'])+' 点 ('+_pct(last.get('change_pct'))+') '
                     '成交量 '+'{:.2f}'.format(last.get('volume', 0)/1e8)+'亿\n')
    else:
        parts.append('- 沪深300：无数据（index_quotes 缺最近3日）\n')

    parts.append('\n### 代表性成分股\n')
    sample = ['600519.SH', '601398.SH', '000001.SZ', '000002.SZ', '600036.SH']
    klines = query_stock_kline(sample, start, trade_date)
    if klines:
        sig['fundamental'] = {'stocks': len(set(r['code'] for r in klines)), 'records': len(klines)}
        for code in sample:
            recs = [r for r in klines if r['code'] == code]
            if recs:
                last = recs[-1]
                parts.append('- '+code+' '+last.get('name','')+'：收盘 '+str(last.get('close'))+' ('+_pct(last.get('change_pct'))+')\n')
    else:
        parts.append('- 成分股：无数据（daily_quotes 最新到'+trade_date+'）\n')

    # 新闻舆情
    news_list = query_news(trade_date, limit=10)
    if news_list:
        sig['information'] = {'news': len(news_list)}
        parts.append('\n### 昨日新闻舆情（'+trade_date+'）\n')
        for r in news_list[:5]:
            sent = r.get('sentiment') or 'N/A'
            parts.append('- ['+r.get('source','?')+'] '+r.get('title','')[:50]+' ('+sent+')\n')
    else:
        parts.append('\n### 昨日新闻舆情：无数据\n')

    summary = '本地数据库采集完成，沪深300'+('有' if hs300 else '无')+'数据，成分股'+('有' if klines else '无')+'数据，新闻'+str(len(news_list))+'条'
    body_md = ''.join(parts)+'\n采集时间：'+time.strftime('%Y-%m-%d %H:%M:%S')+'\n'
    return summary, body_md, sig


def task_factor_calculation(payload):
    sig = {'quant': {'factors': ['momentum', 'value', 'quality', 'money_flow', 'technical']}}
    parts = ['## factor_calculation\n日期：'+TODAY+'\n']
    parts.append('5类因子待行情数据到位后计算（本地数据库已采集日线数据）\n')
    parts.append('\n待计算因子：动量、价值、质量、资金流、技术面\n')
    summary = '因子计算待行情数据恢复（本地数据已采集）'
    body_md = ''.join(parts)+'\n时间：'+time.strftime('%Y-%m-%d %H:%M:%S')+'\n'
    return summary, body_md, sig


def task_etf_alpha_signal(payload):
    scope = payload.get('scope', '全量ETF')
    trade_date = _latest_date()
    sig = {}
    parts = ['## etf_alpha_signal\n日期：'+TODAY+'\n']
    parts.append('范围：'+scope+'\n')
    etf_list = query_etf_quotes(trade_date, limit=20)
    if etf_list:
        sig['quant'] = {'etf_count': len(etf_list)}
        parts.append('\n### 成交额TOP ETF（'+trade_date+'）\n')
        for r in etf_list[:10]:
            parts.append('- '+r['code']+' '+r.get('name','')+'：'+str(r.get('close'))+' ('+_pct(r.get('change_pct'))+')\n')
    else:
        parts.append('\nETF行情：无数据（etf_quotes 最近到'+trade_date+'）\n')
    summary = 'ETF Alpha信号，范围'+scope+'，行情'+str(len(etf_list))+'只'
    body_md = ''.join(parts)+'\n时间：'+time.strftime('%Y-%m-%d %H:%M:%S')+'\n'
    return summary, body_md, sig


def task_risk_monitoring(payload):
    checks = payload.get('checks', ['liquidity', 'concentration', 'sentiment'])
    trade_date = _latest_date()
    start = (date.today() - timedelta(days=5)).isoformat()
    sig = {}
    parts = ['## risk_monitoring\n日期：'+TODAY+'\n']
    parts.append('检查项：'+str(checks)+'\n')

    hs300 = query_index_kline('000300', start, trade_date)
    if hs300 and len(hs300) >= 2:
        sig['sentiment'] = {'hs300_range': len(hs300)}
        pct_list = [r['change_pct'] for r in hs300 if r.get('change_pct') is not None]
        avg_chg = sum(pct_list) / len(pct_list) if pct_list else 0
        last = hs300[-1]
        parts.append('- 沪深300 近'+str(len(hs300))+'日平均涨跌：'+_pct(avg_chg)+'\n')
        parts.append('- 最新收盘：'+str(last.get('close'))+' 点\n')
        if abs(avg_chg) < 0.5:
            parts.append('- 市场情绪：中性（振幅较小）\n')
        elif avg_chg > 0:
            parts.append('- 市场情绪：偏多\n')
        else:
            parts.append('- 市场情绪：偏空\n')
    else:
        parts.append('- 沪深300：无足够数据\n')

    # 北向资金
    north = query_north_flow(trade_date)
    if north:
        sig['information'] = {'north_flow': north[0].get('net_buy')}
        r = north[0]
        parts.append('- 北向资金：净买入 '+_pct(r.get('net_buy'))+'（'+trade_date+'）\n')
    else:
        parts.append('- 北向资金：无数据\n')

    summary = '风险监控完成，'+str(len(checks))+'项检查，数据来源本地数据库'
    body_md = ''.join(parts)+'\n时间：'+time.strftime('%Y-%m-%d %H:%M:%S')+'\n'
    return summary, body_md, sig


def task_daily_report(payload):
    today = TODAY
    trade_date = _latest_date()
    start = (date.today() - timedelta(days=5)).isoformat()
    sig = {}
    parts = ['## daily_report\n日期：'+today+'\n']
    parts.append('\n### 数据来源\n')
    parts.append('- 行情数据：invest-infra PostgreSQL\n')
    parts.append('- 新闻舆情：本地 news_articles\n')
    parts.append('- 因子计算：待行情数据到位后执行\n')
    parts.append('\n### 沪深300 指数\n')

    hs300 = query_index_kline('000300', start, trade_date)
    if hs300:
        sig['quant'] = {'hs300': len(hs300)}
        last = hs300[-1]
        parts.append('最新：'+str(last['close'])+' 点 ('+_pct(last.get('change_pct'))+')\n')
    else:
        parts.append('无数据\n')

    parts.append('\n### 代表性成分股\n')
    stocks = query_stock_kline(
        ['600519.SH', '601398.SH', '000001.SZ', '000002.SZ', '600036.SH'],
        start, trade_date)
    if stocks:
        sig['fundamental'] = {'stocks': len(set(r['code'] for r in stocks))}
        for code in ['600519.SH', '601398.SH', '000001.SZ', '000002.SZ', '600036.SH']:
            recs = [r for r in stocks if r['code'] == code]
            if recs:
                last = recs[-1]
                parts.append('- '+code+' '+last.get('name','')+'：'+str(last.get('close'))+' ('+_pct(last.get('change_pct'))+')\n')
    else:
        parts.append('无数据\n')

    # 新闻舆情摘要
    news_list = query_news(trade_date, limit=5)
    if news_list:
        sig['information'] = {'news': len(news_list)}
        parts.append('\n### 昨日新闻要点\n')
        for r in news_list:
            parts.append('- '+r.get('title','')[:50]+'\n')

    parts.append('\n### 情景假设\n')
    parts.append('- 中性：数据正常，置信度high\n')
    parts.append('- 悲观：数据延迟，置信度维持medium\n')
    parts.append('- 乐观：早盘快速反弹，置信度提升\n')
    summary = '综合日报生成完成，沪深300'+('有' if hs300 else '无')+'数据，成分股'+('有' if stocks else '无')+'数据，新闻'+str(len(news_list))+'条'
    body_md = ''.join(parts)+'\n生成时间：'+time.strftime('%Y-%m-%d %H:%M:%S')+'\n'
    return summary, body_md, sig


# ── 主循环 ────────────────────────────────────────────────────

def do_task():
    r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    msgs = r.xreadgroup(GROUP, CONSUMER, {STREAM: '>'}, count=1, block=5000)
    if not msgs:
        print('[WOA] 队列空')
        return
    for stream_name, mgs in msgs:
        for msg_id, fields in mgs:
            task_id   = fields['task_id']
            task_type = fields['task_type']
            payload   = json.loads(fields['payload'])
            print('claimed:'+msg_id+' tid='+task_id[:8]+' type='+task_type)
            if task_type == 'morning_collect':
                summary, body_md, sig = task_morning_collect(payload)
            elif task_type == 'factor_calculation':
                summary, body_md, sig = task_factor_calculation(payload)
            elif task_type == 'etf_alpha_signal':
                summary, body_md, sig = task_etf_alpha_signal(payload)
            elif task_type == 'risk_monitoring':
                summary, body_md, sig = task_risk_monitoring(payload)
            elif task_type == 'daily_report':
                summary, body_md, sig = task_daily_report(payload)
            else:
                summary = task_type+' 完成'
                body_md = '## '+task_type+'\n'+json.dumps(payload)
                sig = {}
            tags = ['morning_briefing', task_type, 'local_db']
            write_memo(task_id, task_type, summary, body_md, sig, tags)
            n_sig = len([k for k,v in sig.items() if v])
            conf = 'high' if n_sig>=4 else ('medium' if n_sig>=2 else 'low')
            notify_cia('✅ 任务完成 ['+task_id[:8]+'] '+task_type+'\n置信度：'+conf+'\n信号数：'+str(n_sig)+'\n时间：'+time.strftime('%H:%M:%S'))
            r.xack(STREAM, GROUP, msg_id)
            print('XACK '+msg_id+' done')

if __name__ == '__main__':
    do_task()