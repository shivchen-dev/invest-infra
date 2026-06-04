#!/usr/bin/env python3
"""
cron_woa_audit.py — WOA Morning Briefing 输出审计

触发时间：每日 07:30（cron_briefing_dispatch 派发前 10 分钟）
职责：
  1. 读取最新 WOA daily_report 的 memo_date
  2. 校验 memo_date 与内容中节日描述的一致性
  3. 发现不一致 → 写入 /tmp/woa_audit_status.json 标记 fallback
  4. 日志写入 audit.log

依赖：
  - investment_memos 表（company_id=5233, generated_by='jiuwenswarm_woa_v1'）
  - festival_calENDar.json（本地的2026年节日日历，本地读取）
"""

import sys, os, json, logging
from datetime import date, datetime
from pathlib import Path

# ── 环境变量加载 ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
_secrets_dir = ROOT / ".secrets"
_pipeline_dir = ROOT / "data-pipeline"

def _load_env(path: Path) -> dict:
    vals = {}
    if not path.exists():
        return vals
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if k:
            os.environ.setdefault(k, v.strip())
            vals[k] = v.strip()
    return vals

_load_env(_secrets_dir / "tokens.env")
_load_env(_pipeline_dir / ".env")

# ── 常量 ──────────────────────────────────────────────
AUDIT_STATUS_FILE = Path("/tmp/woa_audit_status.json")
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "woa_audit.log"

# 2026 年节日日历（硬编码，准确性由国务院通知背书）
FESTIVALS_2026 = {
    "new_year":      {"name": "元旦",  "start": date(2026, 1, 1),  "end": date(2026, 1, 3),   "days": 3},
    "spring":        {"name": "春节",  "start": date(2026, 2, 15), "end": date(2026, 2, 23),  "days": 9},
    "qingming":      {"name": "清明节","start": date(2026, 4, 4),  "end": date(2026, 4, 6),   "days": 3},
    "labor":         {"name": "劳动节","start": date(2026, 5, 1),  "end": date(2026, 5, 5),   "days": 5},
    "dragon_boat":   {"name": "端午节","start": date(2026, 6, 19), "end": date(2026, 6, 21),  "days": 3},
    "mid_autumn":    {"name": "中秋节","start": date(2026, 9, 25), "end": date(2026, 9, 27),  "days": 3},
    "national_day":  {"name": "国庆节","start": date(2026, 10, 1), "end": date(2026, 10, 7), "days": 7},
}

# 节日关键词（用于检测文本中的节日引用）
FESTIVAL_KEYWORDS = {
    "端午": "dragon_boat",
    "中秋": "mid_autumn",
    "春节": "spring",
    "国庆": "national_day",
    "清明": "qingming",
    "劳动": "labor",
    "元旦": "new_year",
}


# ── 日志配置 ──────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("woa_audit")


# ── 核心审计逻辑 ──────────────────────────────────────────────
def is_trading_day(d: date) -> bool:
    """简单判断是否为交易日（排除周末）"""
    return d.weekday() < 5  # 0=Mon, 4=Fri


def in_festival_period(d: date) -> tuple[str, bool]:
    """
    检查日期 d 是否处于某个节日假期中。
    返回 (festival_key, 是否在节日期间)
    """
    for key, fest in FESTIVALS_2026.items():
        if fest["start"] <= d <= fest["end"]:
            return key, True
    return None, False


def detect_festival_reference(text: str) -> list[str]:
    """从文本中检测节日关键词引用"""
    found = []
    text_lower = text  # 保持中文，不转小写
    for kw, fest_key in FESTIVAL_KEYWORDS.items():
        if kw in text_lower:
            found.append(fest_key)
    return found


def audit_woa_report(memo_date: date, body_md: str, summary: str) -> dict:
    """
    审计单条 WOA 报告的一致性。
    同时检查 body_md 和 summary（幻觉可能只出现在 summary）
    返回 {"pass": bool, "issues": list[str], "festival_refs": list[str]}
    """
    # 合并所有文本来检测节日引用
    all_text = (body_md or "") + " " + (summary or "")
    issues = []
    festival_refs = detect_festival_reference(all_text)

    # 无节日引用 → 直接通过
    if not festival_refs:
        return {"pass": True, "issues": [], "festival_refs": []}

    # 有节日引用 → 检查日期一致性
    ref_festival = festival_refs[0]  # 只看第一个（简化版）
    fest = FESTIVALS_2026.get(ref_festival)

    if fest:
        fest_name = fest["name"]
        fest_start = fest["start"]
        fest_end = fest["end"]

        # 场景1：工作日但声称"节后"
        if is_trading_day(memo_date):
            for ref in festival_refs:
                f = FESTIVALS_2026.get(ref)
                if f:
                    # 工作日 ≠ 节日期间 → "节后首个交易日"说法矛盾
                    if not (f["start"] <= memo_date <= f["end"]):
                        issues.append(
                            f"日期 {memo_date} 为工作日，但报告提及「{f['name']}后」，日期不一致"
                        )

        # 场景2：日期描述了节后行情，但 memo_date 不在节后首个交易日附近
        # 节后首个交易日 = 节日结束后第一个 weekday
        if "后" in body_md and festival_refs:
            fest_end = fest["end"]
            # 找节后第一个交易日
            next_day = fest_end
            while next_day <= fest_end.plus(days=3) and not is_trading_day(next_day):
                next_day = date.fromordinal(next_day.toordinal() + 1)
            # 如果 memo_date 不接近 next_day（±1天），则存疑
            if abs((memo_date - next_day).days) > 1:
                issues.append(
                    f"报告提及「{fest_name}后首个交易日」，"
                    f"但实际节日为 {fest_start}~{fest_end}，节后首个交易日应为 {next_day}，"
                    f"而 memo_date={memo_date}，日期偏差 {(memo_date - next_day).days} 天"
                )

    return {
        "pass": len(issues) == 0,
        "issues": issues,
        "festival_refs": [FESTIVALS_2026[k]["name"] for k in festival_refs],
    }


def write_audit_status(audit_result: dict, memo_date: date, memo_id: int):
    """写入审计结果，供 cron_briefing_dispatch 参考"""
    status = {
        "audit_time": datetime.now().isoformat(),
        "memo_date": str(memo_date),
        "memo_id": memo_id,
        "use_fallback": not audit_result["pass"],
        "issues": audit_result["issues"],
        "festival_refs": audit_result["festival_refs"],
    }
    with open(AUDIT_STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    logger.info(f"审计结果写入 {AUDIT_STATUS_FILE}: use_fallback={not audit_result['pass']}")


def main():
    import psycopg2

    logger.info("=== WOA Morning Briefing 审计开始 ===")

    # 连接 PG（使用直接读取的环境变量）
    conn = psycopg2.connect(
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        dbname=os.getenv("PG_DATABASE", "investdb"),
        user=os.getenv("PG_USER", "invest"),
        password=os.getenv("PG_PASSWORD", ""),
    )
    cur = conn.cursor()

    # 取最新一条 WOA daily_report
    cur.execute("""
        SELECT id, memo_date, title, body_md, summary, generated_by
        FROM investment_memos
        WHERE company_id = 5233
          AND generated_by = 'jiuwenswarm_woa_v1'
          AND memo_type = 'daily_report'
        ORDER BY memo_date DESC, created_at DESC
        LIMIT 1
    """)
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        logger.warning("未找到 WOA daily_report，跳过审计")
        return

    memo_id, memo_date, title, body_md, summary, generated_by = row
    logger.info(f"审计记录: id={memo_id}, memo_date={memo_date}")

    # 执行审计（summary 也传入）
    result = audit_woa_report(memo_date, body_md or "", summary or "")

    if result["pass"]:
        logger.info(f"✅ 审计通过 | festival_refs={result['festival_refs']}")
    else:
        logger.warning(f"❌ 审计失败 | issues={result['issues']}")
        for issue in result["issues"]:
            logger.warning(f"   - {issue}")

    # 写入状态文件
    write_audit_status(result, memo_date, memo_id)

    logger.info("=== WOA 审计结束 ===")


if __name__ == "__main__":
    main()