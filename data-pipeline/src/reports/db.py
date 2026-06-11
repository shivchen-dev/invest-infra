"""
数据库操作模块
市场汇报数据读写
"""
import logging
from datetime import date, datetime, timedelta
from typing import Optional
import json

from src.loader.pg import get_conn

logger = logging.getLogger(__name__)


class Database:
    """数据库操作类"""

    def __init__(self):
        self.params = {}

    def save_report(self, report_type: str, trade_date: date, content: dict) -> int:
        with get_conn() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute("""
                        INSERT INTO market_reports (report_type, trade_date, content)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (report_type, trade_date)
                        DO UPDATE SET content=EXCLUDED.content, created_at=now()
                        RETURNING id
                    """, (report_type, trade_date, json.dumps(content)))
                    rid = cur.fetchone()[0]
                    conn.commit()
                    return rid
                except Exception:
                    logger.error(f"save_report failed: {report_type} {trade_date}")
                    raise

    def get_report(self, report_type: str, trade_date: date) -> Optional[dict]:
        with get_conn() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "SELECT content FROM market_reports WHERE report_type=%s AND trade_date=%s",
                        (report_type, trade_date),
                    )
                    row = cur.fetchone()
                    if row:
                        return json.loads(row[0])
                except Exception:
                    logger.error(f"get_report failed: {report_type} {trade_date}")
                    raise
        return None

    def save_alert(self, alert_type: str, stock_code: str, stock_name: str,
                   detail: dict, trade_date: Optional[date] = None) -> int:
        if trade_date is None:
            trade_date = date.today()
        with get_conn() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute("""
                        INSERT INTO market_alerts (alert_type, stock_code, stock_name, detail, trade_date)
                        VALUES (%s, %s, %s, %s, %s) RETURNING id
                    """, (alert_type, stock_code, stock_name, json.dumps(detail), trade_date))
                    return cur.fetchone()[0]
                except Exception:
                    logger.error(f"save_alert failed: {alert_type} {stock_code}")
                    raise

    def get_recent_alerts(self, trade_date: date, limit: int = 50) -> list[dict]:
        with get_conn() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "SELECT stock_code, stock_name, alert_type, detail, created_at "
                        "FROM market_alerts WHERE trade_date=%s ORDER BY created_at DESC LIMIT %s",
                        (trade_date, limit),
                    )
                    return [
                        {
                            "stock_code": r[0],
                            "alert_type": r[2],
                            "detail": json.loads(r[3]),
                            "created_at": r[4],
                        }
                        for r in cur.fetchall()
                    ]
                except Exception:
                    logger.error(f"get_recent_alerts failed: {trade_date}")
                    raise

    def is_duplicate_alert(self, stock_code: str, alert_type: str,
                           alert_time: datetime, window_minutes: int = 30) -> bool:
        with get_conn() as conn:
            with conn.cursor() as cur:
                try:
                    window = timedelta(minutes=window_minutes)
                    cur.execute("""
                        SELECT COUNT(*) FROM market_alerts
                        WHERE stock_code=%s AND alert_type=%s
                        AND created_at BETWEEN %s AND %s
                    """, (stock_code, alert_type, alert_time - window, alert_time + window))
                    return cur.fetchone()[0] > 0
                except Exception:
                    logger.error(f"is_duplicate_alert failed: {stock_code} {alert_type}")
                    raise

    def update_subscription(self, user_id: str, report_type: str,
                            enabled: bool = True) -> bool:
        with get_conn() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute("""
                        INSERT INTO alert_subscriptions (user_id, report_type, enabled)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (user_id, report_type)
                        DO UPDATE SET enabled=EXCLUDED.enabled, updated_at=now()
                    """, (user_id, report_type, enabled))
                    return True
                except Exception:
                    logger.error(f"update_subscription failed: {user_id} {report_type}")
                    raise


# 全局数据库实例
_db: Optional[Database] = None


def get_db() -> Database:
    """获取全局数据库实例"""
    global _db
    if _db is None:
        _db = Database()
    return _db


if __name__ == "__main__":
    import sys
    db = Database()
    today = date.today()
    test_content = {"message": "hello", "numbers": [1, 2, 3]}

    # save → get round-trip
    rid = db.save_report("pre_market", today, test_content)
    print(f"save_report returned id={rid}")

    row = db.get_report("pre_market", today)
    print(f"get_report returned: {row}")

    assert row == test_content, f"Round-trip mismatch: {row} != {test_content}"
    print("OK — round-trip verified")
    sys.exit(0)
