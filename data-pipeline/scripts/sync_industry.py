#!/usr/bin/env python3
"""
sync_industry.py — 行业分类同步脚本

从巨潮(cninfo)获取每家公司的证监会行业分类，
通过 akshare stock_profile_cninfo 接口逐家抓取，写入 companies.industry 字段。

用法:
    python3 scripts/sync_industry.py              # 全量同步（约 15 分钟）
    python3 scripts/sync_industry.py --limit 100  # 前100家（测试用）
    python3 scripts/sync_industry.py --dry-run      # 只抓取不写入
"""

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")
from src.config import pg

import akshare as ak
import psycopg2

# ─── 配置 ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sync_industry")

BATCH_COMMIT = 100          # 每抓 N 个公司提交一次事务
MAX_WORKERS = 5             # 并发线程数（cninfo 接口有轻微限流）
RETRY_DELAY = 2.0           # 重试前等待秒数
RETRY_MAX = 2               # 最大重试次数
REQUEST_DELAY = 0.5         # 两次请求间冷却（避免被限流）

# ─── akshare 行业抓取 ──────────────────────────────────────────────────

def _raw_code(full_code: str) -> str:
    """从 '000034.SZ' 提取纯数字代码 '000034'"""
    return full_code.split(".")[0]


def fetch_industry(raw_code: str) -> str | None:
    """
    通过 akshare stock_profile_cninfo 获取单只股票的证监会行业分类。
    raw_code: '000001' 格式（6位纯数字）
    返回: '货币金融服务' 或 None（抓不到/无数据）
    """
    try:
        df = ak.stock_profile_cninfo(symbol=raw_code)
        if df is None or df.empty:
            return None
        industry = df["所属行业"].values[0]
        if industry is None or (isinstance(industry, float) and industry != industry):  # NaN
            return None
        return str(industry).strip()
    except Exception:
        return None


def fetch_industry_with_retry(code: str) -> str | None:
    """
    带重试的行业抓取; code 可以是 '000001' 也可以是 '000034.SZ'
    """
    raw = _raw_code(code) if "." in code else code
    for attempt in range(RETRY_MAX):
        result = fetch_industry(raw)
        if result is not None:
            return result
        if attempt < RETRY_MAX - 1:
            time.sleep(RETRY_DELAY)
    return None


# ─── 数据库操作 ─────────────────────────────────────────────────────────

def get_companies_batch(conn, limit: int | None = None, offset: int = 0):
    """读取待同步的公司列表（code 格式: '000034.SZ'，按 code 排序）"""
    with conn.cursor() as cur:
        if limit:
            cur.execute(
                "SELECT id, code, name FROM companies "
                "WHERE industry IS NULL OR industry = '' "
                "ORDER BY code LIMIT %s OFFSET %s",
                (limit, offset),
            )
        else:
            cur.execute(
                "SELECT id, code, name FROM companies "
                "WHERE industry IS NULL OR industry = '' "
                "ORDER BY code",
            )
        return cur.fetchall()


def update_industry_batch(conn, updates: list[tuple[int, str]]):
    """批量更新行业字段"""
    if not updates:
        return
    with conn.cursor() as cur:
        for company_id, industry in updates:
            cur.execute(
                "UPDATE companies SET industry = %s, updated_at = now() WHERE id = %s",
                (industry, company_id),
            )
    conn.commit()


# ─── 主同步逻辑 ─────────────────────────────────────────────────────────

def sync_industry(limit: int | None = None, workers: int = MAX_WORKERS, dry_run: bool = False):
    """
    主同步流程：
    1. 从 PG 读取待同步公司列表（code 格式: '000034.SZ'）
    2. 提取纯数字 code 供 akshare 调用（'000034'）
    3. 并发抓取 akshare 行业数据
    4. 批量提交到 PG
    5. 输出统计
    """
    conn = psycopg2.connect(pg.uri)
    try:
        # ── Step 1: 确认 akshare 接口可用 ──
        logger.info("正在验证 akshare stock_profile_cninfo 接口可用性...")
        test = fetch_industry_with_retry("000001")
        if test is None:
            logger.warning("接口验证失败（返回 None），继续执行...")
        else:
            logger.info(f"接口验证通过: 000001 → {test}")

        # ── Step 2: 读取待同步公司 ──
        companies = get_companies_batch(conn, limit=limit)
        total = len(companies)
        if total == 0:
            logger.info("所有公司的行业字段均已有值，无需同步")
            return
        logger.info(f"待同步公司: {total} 家，并发数={workers}")

        # ── Step 3: 并发抓取 ──
        results = {}   # full_code → industry
        completed = 0
        failed = 0
        batch_updates: list[tuple[int, str]] = []

        with ThreadPoolExecutor(max_workers=workers) as ex:
            future_to_code = {
                ex.submit(fetch_industry_with_retry, full_code): full_code
                for _, full_code, _ in companies
            }

            for future in as_completed(future_to_code):
                full_code = future_to_code[future]
                industry = future.result()
                results[full_code] = industry
                completed += 1

                if industry is not None:
                    for cid, fcode, _ in companies:
                        if fcode == full_code:
                            batch_updates.append((cid, industry))
                            break
                    if len(batch_updates) >= BATCH_COMMIT and not dry_run:
                        update_industry_batch(conn, batch_updates)
                        logger.info(
                            f"  批次提交: {len(batch_updates)} 条 "
                            f"(进度 {completed}/{total})"
                        )
                        batch_updates.clear()
                else:
                    failed += 1

                if completed % 200 == 0 or completed == total:
                    logger.info(
                        f"进度: {completed}/{total} "
                        f"| 成功 {completed - failed} | 失败 {failed}"
                    )

                time.sleep(REQUEST_DELAY)

            if batch_updates and not dry_run:
                update_industry_batch(conn, batch_updates)
                logger.info(f"最终批次提交: {len(batch_updates)} 条")

        # ── Step 4: 结果统计 ──
        success = sum(1 for v in results.values() if v is not None)
        logger.info(f"===== 同步完成 =====")
        logger.info(f"总计: {total} 家")
        logger.info(f"成功: {success} 家 ({success/total*100:.1f}%)")
        logger.info(f"失败: {failed} 家 ({failed/total*100:.1f}%)")
        if failed > 0:
            logger.info(f"失败公司列表（前10）:")
            fails = [(c, results[c]) for c in results if results[c] is None][:10]
            for code, _ in fails:
                logger.info(f"  {code}")

        if dry_run:
            logger.info("Dry-run 模式，未写入数据库")
            for code, ind in list(results.items())[:10]:
                if ind:
                    logger.info(f"  {code} → {ind}")

    finally:
        conn.close()


# ─── CLI ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="同步公司行业分类")
    parser.add_argument("--limit", type=int, default=None,
                        help="限制同步公司数量（用于测试）")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS,
                        help=f"并发线程数（默认 {MAX_WORKERS}）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只抓取不写入数据库")
    args = parser.parse_args()

    logger.info(f"开始行业同步 | limit={args.limit} workers={args.workers} dry={args.dry_run}")
    sync_industry(limit=args.limit, workers=args.workers, dry_run=args.dry_run)


if __name__ == "__main__":
    main()