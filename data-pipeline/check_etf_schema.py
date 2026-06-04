"""检查ETF数据库表结构和现有数据"""

from src.config import pg
import psycopg2

conn = psycopg2.connect(host=pg.host, port=pg.port, dbname=pg.db, user=pg.user, password=pg.password)
cur = conn.cursor()

# 检查所有相关表
tables_to_check = ['etf_alpha_signals', 'etfs', 'etf_quotes', 'news_articles']

for table in tables_to_check:
    try:
        cur.execute(f"""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = '{table}'
            ORDER BY ordinal_position
        """)
        cols = cur.fetchall()
        print(f'\n=== {table} ===')
        print(f'字段数: {len(cols)}')
        for col in cols[:15]:
            print(f'  {col[0]}: {col[1]}')
        if len(cols) > 15:
            print(f'  ... 还有{len(cols)-15}个字段')
    except Exception as e:
        print(f'\n=== {table} === Error: {e}')

# 检查etf_alpha_signals数据
cur.execute('SELECT COUNT(*), MAX(calc_date) FROM etf_alpha_signals')
r = cur.fetchone()
print(f'\n\n因子信号表: {r[0]}条, 最近计算: {r[1]}')

conn.close()