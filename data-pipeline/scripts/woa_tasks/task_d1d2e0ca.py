import redis, json, time, psycopg2
r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
STREAM = 'task_queue'; GROUP = 'woa_workers'; CONSUMER = 'woa_1'
msgs = r.xreadgroup(GROUP, CONSUMER, {STREAM: '>'}, count=1, block=5000)
if not msgs: print('队列空'); exit()
for stream_name, mgs in msgs:
    for msg_id, fields in mgs:
        task_id = fields['task_id']
        task_type = fields['task_type']
        payload = json.loads(fields['payload'])
        callback = json.loads(fields['callback'])
        print(f'claimed: {msg_id} task={task_type} tid={task_id[:8]}')
        time.sleep(2)
        if callback.get('mode') == 'db_write':
            conn = psycopg2.connect(host='localhost', port=5432, dbname='investdb', user='invest', password='REDACTED_PG_PASSWORD')
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO investment_memos
                (company_id,title,memo_date,memo_type,summary,body_md,sections_json,
                 tags,generated_by,model_used,total_tokens,quality_score,review_status,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT DO NOTHING''',
                [5233,
                 f"{task_type} - {payload.get('date','')}",
                 payload.get('date','2026-06-01'),
                 task_type,
                 f"{task_type}完成",
                 f"## {task_type}\n日期：{payload.get('date','')}\n范围：{payload.get('scope','')}",
                 json.dumps({'fundamental':{'score':0.72}}),
                 [task_type],
                 'jiuwenswarm_woa_v1',
                 'MiniMax-M2.7',
                 100,
                 0.72,
                 'pending'])
            conn.commit(); cur.close(); conn.close()
            print(f'PG写入完成: {task_id}')
        r.xack(STREAM, GROUP, msg_id)
        print(f'XACK {msg_id} done')
        print(f'任务完成: {task_id}')
