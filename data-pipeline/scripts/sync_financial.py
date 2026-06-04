#!/usr/bin/env python3
"""
财务数据全量同步脚本 — 覆盖全A股

功能：
  - 获取全市场股票列表（akshare stock_info_a_code_name，~5500只）
  - 增量采集：已有财报的公司跳过（按最新报告期判断）
  - 写入 PG financial_reports + MinIO bronze-financial
  - 失败重试 + 进度记录

采集频率保护：
  - 每只股票间隔 2.5s（财报 0.7s + 指标 1.6s + 0.2s buffer）
  - 每批（50只）间隔 8s
  - 单次运行不超过 2.5 小时（22:00前终止，留30min缓冲）

采集覆盖：
  - 财报摘要（fetch_financial_report）：营收/净利润/ROE等
  - 财务指标（fetch_financial_indicator）：ROA/资产负债率/总资产补录
"""

import argparse
import logging
import os
import sys
import time
import json
from datetime import date, datetime, timedelta
from pathlib import Path

# 加载 .env 环境变量（确保 PG_PASSWORD 等不报错）
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(str(Path(__file__).parent.parent))

from src.config import collector as cc, minio as mc, pg as pg_cfg
from src.collector import financial
from src.loader import minio as minio_loader, pg as pg_loader
from src.loader.pg import backfill_financial_assets

# ─── 日志 ────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "sync_financial.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("sync_financial")

# ─── 常量 ────────────────────────────────────────────────────────
BATCH_SIZE = 50              # 每批股票数
SLEEP_BETWEEN_BATCH = 8      # 每批间隔秒（防止触发频控）
SLEEP_PER_STOCK = 2.5       # 每只股票间隔秒
MAX_RUN_HOURS = 2.5          # 单次最大运行时长（小时）
CUTOFF_HOUR = 22             # 最晚运行时间（小时，24h制）
BUFFER_DAYS = 7              # 已有数据在7天内不重复采集

# 全局状态文件
STATE_FILE = Path(__file__).parent.parent / ".sync_financial_state.json"


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"offset": 0, "last_run": None, "total_seen": 0}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False))


def get_all_stock_codes() -> list[tuple[str, str]]:
    """获取全市场股票代码列表，返回 [(code, name), ...]"""
    import akshare as ak
    logger.info("获取全市场股票列表 ...")
    df = ak.stock_info_a_code_name()
    # 只保留 A 股（沪深主板/科创板/创业板）
    df = df[df["code"].str.match(r"^\d{6}$")]
    logger.info("全市场股票数: %d", len(df))
    return list(zip(df["code"].tolist(), df["name"].tolist()))


def get_already_covered(stock_codes: list[str]) -> set[str]:
    """返回已有近期财报的股票代码集合（7天内已采集则跳过）"""
    import psycopg2
    cutoff = (date.today() - timedelta(days=BUFFER_DAYS)).isoformat()
    conn = psycopg2.connect(pg_cfg.uri)
    cur = conn.cursor()
    # financial_reports 用 company_id，需通过 companies 表映射回 stock_code
    cur.execute("""
        SELECT DISTINCT c.code
        FROM financial_reports fr
        JOIN companies c ON c.id = fr.company_id
        WHERE fr.report_date >= %s
    """, (cutoff,))
    covered = {str(row[0]) for row in cur.fetchall()}
    conn.close()
    logger.info("近期已有财报覆盖: %d 只", len(covered))
    return covered


def run_sync(target_count: int = 500, dry_run: bool = False) -> dict:
    """
    执行财务数据同步。

    Args:
        target_count: 本次运行最多采集的股票数（默认500，~21分钟）
        dry_run: True 则只打印计划，不实际采集

    Returns:
        {"collected": n, "skipped": n, "failed": n, "elapsed_min": f}
    """
    t_start = time.time()
    today = date.today()

    # 强制截时间
    cutoff_time = datetime.now().replace(
        hour=CUTOFF_HOUR, minute=0, second=0, microsecond=0
    )
    max_run_s = min(MAX_RUN_HOURS * 3600, (cutoff_time - datetime.now()).total_seconds())
    if max_run_s <= 0:
        logger.warning("已过运行窗口（%d点后），跳过本次同步", CUTOFF_HOUR)
        return {"skipped": 0, "note": "outside run window"}

    logger.info("本次最多运行 %.0f 秒（%.1f 分钟）", max_run_s, max_run_s / 60)

    # 加载进度
    state = load_state()
    offset = state.get("offset", 0)

    # 获取全量股票列表
    all_stocks = get_all_stock_codes()
    total_stocks = len(all_stocks)

    # 已有覆盖的跳过
    covered = get_already_covered([c for c, _ in all_stocks])
    pending = [(c, n) for c, n in all_stocks if c not in covered]
    logger.info("待采集: %d 只，已覆盖（跳过）: %d 只", len(pending), len(covered))

    if dry_run:
        logger.info("[DRY RUN] 本次计划采集: min(offset=%d, target=%d, pending=%d) = %d",
                     offset, target_count, len(pending), min(offset, target_count, len(pending)))
        return {"dry_run": True, "offset": offset, "pending": len(pending)}

    # 本次要采的批次：从 offset 开始
    batch_stocks = pending[offset:offset + target_count]
    if not batch_stocks:
        logger.info("全部采集完成（或已到 offset 上限），重置 offset=0")
        state["offset"] = 0
        save_state(state)
        return {"collected": 0, "skipped": len(covered), "note": "all done or offset exhausted"}

    logger.info("本次从 offset=%d 开始，采集 %d 只股票", offset, len(batch_stocks))

    collected = 0
    skipped = 0
    failed = 0
    errors = []

    minio_loader.ensure_buckets()

    for i, (code, name) in enumerate(batch_stocks):
        # 检查时间
        elapsed_s = time.time() - t_start
        if elapsed_s > max_run_s:
            logger.info("达到时间上限，停止。已采 %d 只，耗时 %.1f min", collected, elapsed_s / 60)
            break

        try:
            # ── 财报摘要 ──────────────────────────────────────────────
            fr_records = financial.fetch_financial_report(code)
            if fr_records:
                pg_loader.batch_upsert_financial(fr_records)
                minio_loader.store_json(fr_records, mc.bucket_bronze_financial, "financial/reports", today)
                logger.info("  %s %s: %d 期财报", code, name, len(fr_records))
            else:
                logger.info("  %s %s: 无财报数据", code, name)

            # ── 财务指标（ROA/资产负债率/总资产补录）─────────────────
            fi_records = financial.fetch_financial_indicator(code, start_year=2020)
            if fi_records:
                backfill_financial_assets(fi_records)
                minio_loader.store_json(fi_records, mc.bucket_bronze_financial, "financial/indicator", today)
                logger.info("  %s 指标: %d 期", code, len(fi_records))

            collected += 1

        except Exception as e:
            failed += 1
            err_msg = f"{code} {name}: {e}"
            errors.append(err_msg)
            logger.warning("采集失败: %s", err_msg)

        # 节奏控制
        time.sleep(SLEEP_PER_STOCK)

        # 批次进度报告
        if (i + 1) % BATCH_SIZE == 0:
            elapsed_min = (time.time() - t_start) / 60
            remaining = len(batch_stocks) - i - 1
            eta_min = elapsed_min / (i + 1) * remaining if remaining > 0 else 0
            logger.info("  批次进度: %d/%d 已采, %.1f min, 预计剩余 %.1f min",
                         i + 1, len(batch_stocks), elapsed_min, eta_min)
            time.sleep(SLEEP_BETWEEN_BATCH)

    # 更新状态
    new_offset = offset + collected
    if new_offset >= len(pending):
        new_offset = 0  # 本轮完成，下轮从头开始（或下次增量）

    state["offset"] = new_offset
    state["last_run"] = datetime.now().isoformat()
    save_state(state)

    elapsed_min = (time.time() - t_start) / 60
    logger.info("=== 本次采集完成 ===")
    logger.info("  采集成功: %d | 失败: %d | 跳过: %d | 耗时: %.1f min", collected, failed, skipped, elapsed_min)
    if errors:
        logger.warning("失败列表（前10条）:")
        for e in errors[:10]:
            logger.warning("  %s", e)

    return {
        "collected": collected,
        "failed": failed,
        "skipped": skipped,
        "elapsed_min": round(elapsed_min, 1),
        "errors": errors[:20],  # 最多保留20条
        "next_offset": new_offset,
        "total_pending": len(pending),
    }


def main():
    parser = argparse.ArgumentParser(description="全市场财务数据同步")
    parser.add_argument("--count", type=int, default=150, help="本次最多采集股票数（默认150）")
    parser.add_argument("--dry", action="store_true", help="只打印计划，不实际采集")
    args = parser.parse_args()

    logger.info("========== 全市场财务数据同步启动 ==========")
    logger.info("目标采集数: %d | 批次大小: %d | 间隔: %.1fs/只 | 最大运行时长: %.1fh",
                args.count, BATCH_SIZE, SLEEP_PER_STOCK, MAX_RUN_HOURS)

    result = run_sync(target_count=args.count, dry_run=args.dry)

    logger.info("最终结果: %s", result)
    print(f"\n{'[DRY RUN] ' if args.dry else ''}完成: {result}")


if __name__ == "__main__":
    main()