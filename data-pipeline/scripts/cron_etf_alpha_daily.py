#!/usr/bin/env python3
"""
日结 21:00 — ETF FQIR 评分 + 候选池输出

流程：
  Step 1  计算 Q/L/R 因子（akshare 行情+资金流，分钟级）
  Step 2  计算 F/I 因子（行业情绪，东财接口限流时超时降级）
  Step 3  FQIR 加权综合评分 → etf_alpha_signals
  Step 4  按过滤器输出候选 ETF 池

日志：logs/cron_etf_alpha.log（RotatingFileHandler，10MB/5轮转）
"""
import sys
import os
import time
import logging
import logging.handlers
import subprocess
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")

from src.config import pg
from src.signals.scoring import compute_fqir_etf_score, filter_candidate_pool
from src.signals.etf_alpha import compute_etf_alpha

# ─── 日志配置 ────────────────────────────────────────────────────────────────

LOG_DIR = Path("/home/claw/invest-infra/data-pipeline/logs")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "cron_etf_alpha.log"

_root_logger = logging.getLogger()
_root_logger.setLevel(logging.INFO)
# 避免重复灌日志（reload 时不重置 handler）
if not _root_logger.handlers:
    _root_logger.addHandler(
        logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5,
            encoding="utf-8",
        )
    )
    _root_logger.addHandler(logging.StreamHandler(sys.stdout))

logger = logging.getLogger("cron_etf_alpha")

# ─── 常量 ────────────────────────────────────────────────────────────────────

TODAY = date.today()
INDUSTRY_SENTIMENT_TIMEOUT = 60   # 东财行业情绪接口超时（秒）

# 当前宽松阈值（F/I 维度暂用默认值，待恢复后改为 min_composite=65.0 / max_risk=40.0）
DEFAULT_FILTERS = {
    "min_composite": 0.0,
    "min_amount":    5_000_000,
    "max_risk":      60.0,
}


# ─── Step 2 子进程 ──────────────────────────────────────────────────────────

def _run_fundamental_subprocess(timeout_sec: int) -> dict:
    """
    用独立 Python 进程运行 compute_etf_fundamental，防止阻塞主流程。
    返回 dict:
      ok       : bool   成功/失败
      duration : float  实际耗时（秒）
      message  : str    摘要信息
    """
    script = (
        "import sys, os; "
        "sys.path.insert(0,'/home/claw/invest-infra/data-pipeline'); "
        "os.chdir('/home/claw/invest-infra/data-pipeline'); "
        "from src.config import pg; "
        "from src.factors.etf_fundamental import compute_etf_fundamental; "
        "from datetime import date; "
        "import psycopg2, logging; "
        "logging.basicConfig(level=logging.WARNING); "
        "conn = psycopg2.connect(pg.uri); "
        "n = compute_etf_fundamental(conn, date.today(), dry_run=False); "
        "conn.close(); "
        "print('OK', n)"
    )
    t0 = time.time()
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            timeout=timeout_sec,
            capture_output=True,
            text=True,
            env={**os.environ, "TZ": "Asia/Shanghai"},
        )
        duration = time.time() - t0
        if result.returncode == 0 and "OK" in result.stdout:
            return {"ok": True, "duration": duration,
                    "message": f"完成，{result.stdout.strip()}"}
        return {"ok": False, "duration": duration,
                "message": f"异常: {result.stderr[:120]}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "duration": timeout_sec,
                "message": f"超时（{timeout_sec}s），东财限流中，使用默认值 50.0"}
    except Exception as e:
        return {"ok": False, "duration": time.time() - t0,
                "message": str(e)}


# ─── 数据质量摘要 ───────────────────────────────────────────────────────────

def _dim_stats(conn, calc_date) -> dict:
    """返回各维度有效数据 / 默认值统计"""
    stats = {}
    with conn.cursor() as cur:
        for dim, tbl, col in [
            ("F", "etf_fundamental_scores", "industry_sentiment"),
            ("I", "etf_info_scores",        "news_sentiment"),
            ("R", "etf_risk_scores",         "policy_risk"),
        ]:
            cur.execute(f"""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE {col} IS NOT NULL AND {col} != 50.0) AS real_signal,
                    COUNT(*) FILTER (WHERE {col} IS NULL OR {col} = 50.0) AS default_used
                FROM {tbl}
                WHERE calc_date = %s
            """, (calc_date,))
            r = cur.fetchone()
            stats[dim] = dict(total=r[0], real_signal=r[1], default_used=r[2])
    return stats


def _score_distribution(conn, calc_date) -> dict:
    """返回 composite_score 分布"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                COUNT(*),
                ROUND(MIN(composite_score)::numeric, 2),
                ROUND(MAX(composite_score)::numeric, 2),
                ROUND(AVG(composite_score)::numeric, 2),
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY composite_score) AS q1,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY composite_score) AS q3
            FROM etf_alpha_signals
            WHERE calc_date = %s
        """, (calc_date,))
        r = cur.fetchone()
        return dict(total=r[0], min=r[1], max=r[2], avg=r[3], q1=r[4], q3=r[5])


# ─── 主流程 ─────────────────────────────────────────────────────────────────

def run():
    start_time = time.time()
    logger.info("=" * 60)
    logger.info("ETF FQIR 日结开始 [%s]", TODAY)
    logger.info("过滤器: min_composite=%.1f  min_amount=%s  max_risk=%.1f",
                DEFAULT_FILTERS["min_composite"],
                f"{DEFAULT_FILTERS['min_amount']/1e6:.0f}M",
                DEFAULT_FILTERS["max_risk"])

    conn = psycopg2.connect(pg.uri)
    step_results = {}

    try:
        # ── Step 1: Q/L/R 因子 ──────────────────────────────────────────
        s1 = time.time()
        logger.info("[Step 1/4] 计算 Q/L/R 因子（行情+资金流）...")
        alpha_result = compute_etf_alpha(conn, TODAY, lookback_days=60)
        step_results["step1"] = {
            "duration": time.time() - s1,
            "signals": alpha_result.get("signals", 0),
        }
        logger.info("[Step 1/4] 完成: %d 只ETF 评分 (%.1fs)",
                    step_results["step1"]["signals"], step_results["step1"]["duration"])

        # ── Step 2: F/I 因子（子进程隔离） ──────────────────────────────
        s2 = time.time()
        logger.info("[Step 2/4] 计算 F/I 因子（行业情绪，超时%d秒）...", INDUSTRY_SENTIMENT_TIMEOUT)
        fi_result = _run_fundamental_subprocess(INDUSTRY_SENTIMENT_TIMEOUT)
        step_results["step2"] = {"duration": time.time() - s2, **fi_result}
        if fi_result["ok"]:
            logger.info("[Step 2/4] F/I 因子完成 (%.1fs): %s",
                        fi_result["duration"], fi_result["message"])
        else:
            logger.warning("[Step 2/4] F/I 因子失败 (%.1fs): %s — 使用默认值 50.0",
                           fi_result["duration"], fi_result["message"])

        # ── Step 3: FQIR 综合评分 ───────────────────────────────────────
        s3 = time.time()
        logger.info("[Step 3/4] 计算 FQIR 综合评分...")
        score_result = compute_fqir_etf_score(conn, TODAY)
        scores = score_result.get("scores", {})
        step_results["step3"] = {"duration": time.time() - s3, "scores": len(scores)}
        logger.info("[Step 3/4] 完成: %d 只ETF 综合评分 (%.1fs)",
                    len(scores), step_results["step3"]["duration"])

        # ── 维度数据质量摘要 ─────────────────────────────────────────────
        dim_stats = _dim_stats(conn, TODAY)
        for dim, s in dim_stats.items():
            logger.info("[维度质量] %s维度: 合计%d只  真实信号%d只  默认值%d只",
                        dim, s["total"], s["real_signal"], s["default_used"])

        # ── 评分分布 ─────────────────────────────────────────────────────
        dist = _score_distribution(conn, TODAY)
        logger.info("[评分分布] 综合: %d只  范围%.2f~%.2f  均值%.2f  Q25=%.2f Q75=%.2f",
                    dist["total"], dist["min"], dist["max"], dist["avg"], dist["q1"], dist["q3"])

        # ── Step 4: 候选池输出 ──────────────────────────────────────────
        s4 = time.time()
        logger.info("[Step 4/4] 生成候选 ETF 池（top_n=20）...")
        top_etfs = filter_candidate_pool(conn, TODAY, filters=DEFAULT_FILTERS, top_n=20)
        step_results["step4"] = {"duration": time.time() - s4, "pool": len(top_etfs)}
        logger.info("[Step 4/4] 完成: %d 只进入候选池 (%.1fs)",
                    len(top_etfs), step_results["step4"]["duration"])

        # ── 打印表格 ────────────────────────────────────────────────────
        _print_candidate_table(top_etfs, dist)

    finally:
        conn.close()

    total_duration = time.time() - start_time
    logger.info("ETF FQIR 日结完成: 总耗时 %.1fs", total_duration)
    logger.info("步骤耗时: Step1=%.1fs Step2=%.1fs Step3=%.1fs Step4=%.1fs",
               step_results.get("step1", {}).get("duration", 0),
               step_results.get("step2", {}).get("duration", 0),
               step_results.get("step3", {}).get("duration", 0),
               step_results.get("step4", {}).get("duration", 0))
    logger.info("=" * 60)


def _print_candidate_table(top_etfs, dist):
    print(f"\n{'=' * 72}")
    print(f"📊 ETF FQIR 候选池 — {TODAY}  (共 {dist['total']} 只评分)")
    print(f"{'=' * 72}")
    if not top_etfs:
        print("⚠️  无满足当前条件的候选 ETF（请检查过滤器阈值）")
    else:
        hdr = (f"{'代码':<8} {'名称':<12} {'综合':>6} {'F':>5} {'Q':>5} "
               f"{'L':>5} {'I':>5} {'R':>5} {'规模(万)':>10} {'风险值':>7}")
        print(hdr)
        print("-" * 72)
        for e in top_etfs:
            code   = e.get("code", "")
            name   = e.get("name", "")[:10]
            score  = e.get("composite_score", 0)
            f_dim  = e.get("fundamental", 0)
            q_dim  = e.get("quant", 0)
            l_dim  = e.get("liquidity", 0)
            i_dim  = e.get("information", 0)
            r_dim  = e.get("risk", 0)
            amount = e.get("amount_ma5", 0) or 0
            risk   = e.get("risk", 0)          # risk 维度绝对分
            w = amount / 10_000 if amount else 0.0
            print(
                f"{code:<8} {name:<12} {score:>6.2f} "
                f"{f_dim:>5.2f} {q_dim:>5.2f} {l_dim:>5.2f} "
                f"{i_dim:>5.2f} {r_dim:>5.2f} "
                f"{w:>10.1f} {risk:>7.1f}"
            )
        print("-" * 72)
        print(f"评分分布: {dist['min']:.2f}~{dist['max']:.2f}  均值={dist['avg']:.2f}  Q25={dist['q1']:.2f} Q75={dist['q3']:.2f}")
    print(f"{'=' * 72}\n")


# ─── 入口 ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import psycopg2  # noqa: import placement
    run()