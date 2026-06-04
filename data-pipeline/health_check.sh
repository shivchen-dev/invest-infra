#!/bin/bash
cd /home/claw/invest-infra/data-pipeline
source .venv/bin/activate
export $(grep -v '^#' .env | xargs)
python - << 'PYEOF'
from src.config import pg
import psycopg2
conn = psycopg2.connect(host=pg.host, port=pg.port, dbname=pg.db, user=pg.user, password=pg.password)
cur = conn.cursor()
cur.execute('SELECT COUNT(DISTINCT etf_id) FROM etf_quotes WHERE trade_date = CURRENT_DATE')
etf_count = cur.fetchone()[0]
cur.execute('SELECT COUNT(*) FROM etf_quotes WHERE trade_date = CURRENT_DATE')
kline_count = cur.fetchone()[0]
cur.execute('SELECT COUNT(*), MAX(calc_date) FROM etf_alpha_signals')
r = cur.fetchone()
print(f'今日采集ETF数: {etf_count}')
print(f'今日K线条数: {kline_count}')
print(f'因子信号: {r[0]}条, 最近计算: {r[1]}')
conn.close()
PYEOF