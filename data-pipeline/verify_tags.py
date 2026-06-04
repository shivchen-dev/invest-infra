"""验证 write_memo 参数类型"""
import psycopg2, json

from src.config import pg
conn = psycopg2.connect(host=pg.host, port=pg.port, dbname=pg.db, user=pg.user, password=***)
cur = conn.cursor()

TODAY = '2026-06-02'
task_type = 'test_tags'
tags = ['morning_briefing', 'factor_calculation', 'rsscast']
sig_data = {}

sql = '''INSERT INTO investment_memos
    (company_id, title, memo_date, memo_type, summary, body_md,
     sections_json, tags, generated_by, model_used, total_tokens,
     quality_score, review_status, confidence_level, trigger_signals,
     follow_up_status, version, created_at)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
    ON CONFLICT DO NOTHING'''

try:
    cur.execute(sql, [
        5233, '[LOW] test_tags - '+TODAY, TODAY, task_type, 'test summary', 'test body',
        json.dumps(sig_data), tags,
        'jiuwenswarm_woa_v1','MiniMax-M2.7',500,0.75,
        'draft','low',json.dumps({}),'pending',1
    ])
    conn.commit()
    print('写入成功 - tags 是 Python list 类型')
except Exception as e:
    print('写入失败:', type(e).__name__, e)
finally:
    cur.close()
    conn.close()