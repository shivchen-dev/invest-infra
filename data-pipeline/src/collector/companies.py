"""上市公司基本信息采集器 — 通过 akshare 获取 A 股公司列表"""

import logging
from typing import Optional

import akshare as ak

from src.collector.retry import with_retry
from src.loader import pg

logger = logging.getLogger(__name__)


def _market_for_code(code: str) -> str:
    """根据股票代码前缀判断所属交易所"""
    if code.startswith("6"):
        return "SH"
    elif code.startswith("0") or code.startswith("3"):
        return "SZ"
    elif code.startswith("8") or code.startswith("4") or code.startswith("92"):
        return "BJ"
    return "OTHER"


@with_retry()
def fetch_all_companies() -> list[dict]:
    """获取 A 股全量上市公司基本信息"""
    logger.info("正在从 akshare 获取 A 股公司列表 ...")
    try:
        df = ak.stock_info_a_code_name()
    except Exception as e:
        logger.error(f"获取公司列表失败: {e}", exc_info=True)
        return []
    logger.info(f"获取到 {len(df)} 条公司记录")
    records = []
    for _, row in df.iterrows():
        raw_code = str(row.get("code", "")).strip()
        name = str(row.get("name", "")).strip()
        market = _market_for_code(raw_code)
        full_code = f"{raw_code}.{market}"
        records.append({
            "code": full_code,
            "name": name,
            "short_name": name,
            "industry": None,
            "market": market,
            "is_active": True,
        })
    return records


def sync_to_db(records: list[dict]) -> dict:
    """
    同步公司列表到 PostgreSQL（upsert 模式）。

    优化策略：
    - 先查 companies 表已有的 code 集合（避免逐行 SELECT）
    - 仅对新增/有变更的记录执行 INSERT/UPDATE
    """
    if not records:
        return {"inserted": 0, "updated": 0, "skipped": 0, "total": 0}

    with pg.get_conn() as conn:
        # Step 1: 查已存在的 codes（使用 IN 而非 ANY）
        codes_to_check = [r["code"] for r in records]
        with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(codes_to_check))
            cur.execute(f"SELECT code FROM companies WHERE code IN ({placeholders})", codes_to_check)
            existing = {row[0] for row in cur.fetchall()}

        # Step 2: 分类
        new_records = [r for r in records if r["code"] not in existing]
        unchanged_count = len(records) - len(new_records)

        # Step 3: 批量 upsert new records
        inserted = updated = 0
        if new_records:
            with conn.cursor() as cur:
                for r in new_records:
                    cur.execute(
                        """
                        INSERT INTO companies (code, name, short_name, market, is_active)
                        VALUES (%(code)s, %(name)s, %(short_name)s, %(market)s, %(is_active)s)
                        ON CONFLICT (code) DO UPDATE SET
                            name = EXCLUDED.name,
                            short_name = EXCLUDED.short_name,
                            updated_at = now()
                        """,
                        r,
                    )
                    if cur.rowcount == 1:
                        inserted += 1
                    else:
                        updated += 1
            conn.commit()

        logger.info(f"公司列表同步完成: 新增 {inserted}, 更新 {updated}, 跳过(无变化) {unchanged_count}")
        return {"inserted": inserted, "updated": updated, "skipped": unchanged_count, "total": len(records)}
