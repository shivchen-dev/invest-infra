"""
Callback 执行器 — Task 完成后执行回调

支持的回调模式：
- DB_WRITE:    写入 PostgreSQL investment_memos / analysis_signals / backtest_runs
- A2A_STREAM:  流式推送回调用（待扩展）
- BOTH:        同时执行

URI 格式：
- pg://investment_memos/NEW       → 写入 investment_memos（NEW = 新建）
- pg://investment_memos/<id>     → 更新现有记录
- pg://analysis_signals/NEW      → 写入 analysis_signals
- pg://backtest_runs/NEW         → 写入 backtest_runs
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg2
import psycopg2.extras

from src.config import pg
from src.task_protocol import CallbackSpec, CallbackMode, Task, TaskResult

logger = logging.getLogger(__name__)


# ─── Callback URI 解析 ────────────────────────────────────────────

class DataRef:
    """解析 pg:// URI"""
    def __init__(self, uri: str):
        scheme, rest = uri.split("://", 1)
        self.scheme = scheme
        if "/" in rest:
            self.table, self.record_id = rest.split("/", 1)
        else:
            self.table = rest
            self.record_id = None

    @classmethod
    def parse(cls, uri: str) -> "DataRef":
        return cls(uri)

    def __str__(self) -> str:
        if self.record_id:
            return f"{self.scheme}://{self.table}/{self.record_id}"
        return f"{self.scheme}://{self.table}/<new>"


# ─── Callback Executor ────────────────────────────────────────────

class CallbackExecutor:
    """执行 Task 回调（写入 DB）"""

    def __init__(self):
        self._conn = None

    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(pg.uri)
        return self._conn

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None

    def execute(self, callback: CallbackSpec | None, task: Task, result: TaskResult) -> bool:
        """执行回调，返回是否成功"""
        if callback is None:
            logger.debug(f"Task {task.task_id} 无回调配置")
            return True

        if callback.mode in (CallbackMode.DB_WRITE, CallbackMode.BOTH):
            return self._db_write(callback, task, result)
        return True

    def _db_write(self, callback: CallbackSpec, task: Task, result: TaskResult) -> bool:
        """写入 PostgreSQL"""
        ref = DataRef.parse(callback.target)
        table = ref.table

        if table == "investment_memos":
            return self._write_memo(task, result)
        elif table == "analysis_signals":
            return self._write_signal(task, result)
        elif table == "backtest_runs":
            return self._write_backtest(task, result)
        else:
            logger.warning(f"Unknown callback target table: {table}")
            return False

    def _write_memo(self, task: Task, result: TaskResult) -> bool:
        """写入 investment_memos 表"""
        conn = self._get_conn()
        output = result.output if isinstance(result.output, dict) else {}
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except json.JSONDecodeError:
                output = {"raw": output}

        memo_date = datetime.now().date()
        body_md = result.raw_text or str(result.output or "")

        title = output.get("title") or output.get("summary") or f"晨报 {memo_date}"
        summary = output.get("summary", "")[:500]
        tags = task.tags + [task.task_type.value]

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO investment_memos (
                    company_id, title, memo_date, memo_type,
                    summary, body_md, sections_json, tags,
                    generated_by, model_used, quality_score,
                    review_status, data_range_from, data_range_to,
                    created_at, updated_at
                ) VALUES (
                    NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now()
                )
                RETURNING id
            """, (
                title,
                memo_date,
                task.task_type.value,
                summary,
                body_md,
                json.dumps(output),
                tags,
                task.created_by,
                "jiuwenswarm-a2a",
                output.get("confidence"),
                "pending",
                None,  # data_range_from
                None,  # data_range_to
            ))
            new_id = cur.fetchone()[0]
            conn.commit()

        logger.info(f"✓ investment_memos 写入成功 id={new_id}")
        return True

    def _write_signal(self, task: Task, result: TaskResult) -> bool:
        """写入 analysis_signals 表"""
        conn = self._get_conn()
        output = result.output if isinstance(result.output, dict) else {}
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except json.JSONDecodeError:
                return False

        # 从 output 中提取信号
        code = output.get("code") or output.get("etf_code") or ""
        signal_type = output.get("signal_type", "watch")
        confidence = output.get("confidence", 0.5)
        reasoning = output.get("summary") or output.get("reasoning", "")[:500]
        details = output

        with conn.cursor() as cur:
            # 尝试匹配 company_id
            cur.execute("SELECT id FROM companies WHERE code = %s LIMIT 1", (code,))
            row = cur.fetchone()
            company_id = row[0] if row else None

            if company_id:
                cur.execute("""
                    INSERT INTO analysis_signals (
                        company_id, signal_date, signal_type, confidence,
                        source_module, reasoning, details_json, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, now())
                    RETURNING id
                """, (
                    company_id,
                    datetime.now().date(),
                    signal_type,
                    confidence,
                    f"jiuwen:{task.task_type.value}",
                    reasoning,
                    json.dumps(details),
                ))
                new_id = cur.fetchone()[0]
                conn.commit()
                logger.info(f"✓ analysis_signals 写入成功 id={new_id}")
            else:
                logger.warning(f"无法写入 signal: 未找到 company_code={code}")
                return False

        return True

    def _write_backtest(self, task: Task, result: TaskResult) -> bool:
        """写入 backtest_runs 表"""
        conn = self._get_conn()
        output = result.output if isinstance(result.output, dict) else {}
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except json.JSONDecodeError:
                output = {"raw": result.raw_text}

        params = task.params
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO backtest_runs (
                    run_name, description, strategy_config,
                    start_date, end_date, universe_type, universe_list,
                    status, triggered_by, started_at, completed_at,
                    created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                RETURNING id
            """, (
                f"run_{task.task_id[:8]}",
                f"{task.task_type.value} - {params.etf_code or params.company_code or 'multi'}",
                json.dumps(output),
                None,  # start_date（从 task params 扩展）
                None,  # end_date
                "etf" if params.etf_code else "stock",
                [params.etf_code or c for c in (params.watchlist or [])],
                result.status,
                task.created_by,
                datetime.now(),
                result.completed_at,
            ))
            new_id = cur.fetchone()[0]
            conn.commit()

        logger.info(f"✓ backtest_runs 写入成功 id={new_id}")
        return True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ─── 快捷执行 ────────────────────────────────────────────────────

def execute_callback(
    callback: CallbackSpec | None,
    task: Task,
    result: TaskResult,
) -> bool:
    """一行执行回调（自动创建/关闭 executor）"""
    with CallbackExecutor() as executor:
        return executor.execute(callback, task, result)