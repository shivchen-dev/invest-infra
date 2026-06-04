"""检查 WOA 任务写库情况"""
from src.config import pg
import psycopg2

conn = psycopg2.connect(host=pg.host, port=pg.port, dbname=pg.db, user=pg.user, password=pg.password)
cur = conn.cursor()

print("=== analysis_signals 全部记录 ===")
cur.execute("""
    SELECT signal_date, signal_type, reasoning, source_module, confidence, created_at
    FROM analysis_signals
    ORDER BY created_at DESC
    LIMIT 20
""")
rows = cur.fetchall()
print(f"共 {len(rows)} 条")
for r in rows:
    print(f"  [{r[5]}] date={r[0]} type={r[1]} module={r[3]} conf={r[4]}")
    print(f"    {str(r[2])[:120]}")

print()
print("=== alpha_signals 表结构 ===")
cur.execute("""
    SELECT column_name FROM information_schema.columns
    WHERE table_name = 'alpha_signals'
    ORDER BY ordinal_position
""")
cols = [r[0] for r in cur.fetchall()]
print("列名:", cols)

print()
print("=== alpha_signals 最近记录 ===")
cur.execute("""
    SELECT *
    FROM alpha_signals
    ORDER BY created_at DESC
    LIMIT 5
""")
rows = cur.fetchall()
print(f"共 {len(rows)} 条")
for r in rows:
    print(f"  {r}")

conn.close()
print()
print("=== done ===")