"""检查 investment_memos 写库情况"""
from src.config import pg
import psycopg2

conn = psycopg2.connect(host=pg.host, port=pg.port, dbname=pg.db, user=pg.user, password=pg.password)
cur = conn.cursor()

# investment_memos 表结构
cur.execute("""
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'investment_memos' 
ORDER BY ordinal_position
""")
print('investment_memos 表结构:')
for r in cur.fetchall():
    print(f'  {r[0]}: {r[1]} nullable={r[2]}')

print()
# 最近写入的记录
cur.execute("""
SELECT title, memo_type, confidence_level, created_at 
FROM investment_memos 
ORDER BY created_at DESC 
LIMIT 10
""")
print('最近 investment_memos:')
for r in cur.fetchall():
    print(f'  [{r[3]}] {r[0]} type={r[1]} conf={r[2]}')

conn.close()