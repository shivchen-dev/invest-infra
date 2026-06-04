import redis, psycopg2
from src.config import pg

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

info = r.xinfo_stream('task_queue')
pending = r.xpending('task_queue', 'woa_workers')
print(f"[Stream] length={info['length']} groups={info['groups']}")
print(f"[Pending] pending={pending['pending']}")

entries = r.xrange('task_queue', '-', '+')
print(f"[Entries] {len(entries)} 条:")
for msg_id, fields in entries:
    print(f"  {msg_id}: task_type={fields.get('task_type','?')} tid={fields.get('task_id','?')[:8]}")

conn = psycopg2.connect(host=pg.host, port=pg.port, dbname=pg.db, user=pg.user, password=pg.password)
cur = conn.cursor()
cur.execute("""
    SELECT id, title, memo_type, confidence_level, trigger_signals, created_at
    FROM investment_memos
    WHERE created_at > NOW() - INTERVAL '10 minutes'
    ORDER BY created_at DESC
""")
rows = cur.fetchall()
print(f"\n[PG] investment_memos 新增: {len(rows)} 条")
for row in rows:
    print(f"  id={row[0]} type={row[2]} confidence={row[3]} signals={row[4]} created={row[5]}")
cur.close(); conn.close()