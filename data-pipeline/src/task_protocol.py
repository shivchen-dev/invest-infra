"""
任务协议规范 v1.0
=================
CIA → JiuwenSwarm 主协议，定义任务下发格式、回调机制、结果归约。

设计原则：
- 任务唯一性：idempotency_key 保证重试不重复
- 结果可归约：callback 机制，无需轮询
- SLA 软截止：超时仅记录，不阻塞主流程
- 数据引用：data_refs 用 URI 指向 invest-infra 数据层
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any


# ─── 任务类型枚举 ────────────────────────────────────────────────

class TaskType(str, Enum):
    # 事件分析类
    ANALYZE_COMPANY_EVENT = "analyze_company_event"    # 重大公告/财报分析
    ANALYZE_ETF_EVENT     = "analyze_etf_event"         # ETF 事件分析
    ANALYZE_MARKET_EVENT   = "analyze_market_event"      # 市场整体事件

    # 采集类
    COLLECT_RESEARCH_REPORTS = "collect_research_reports"
    COLLECT_NEWS             = "collect_news"
    COLLECT_FINANCIAL        = "collect_financial"

    # 量化计算类
    COMPUTE_ALPHA_SIGNALS    = "compute_alpha_signals"
    RUN_BACKTEST             = "run_backtest"
    SCORE_ETF                = "score_etf"

    # 综合类
    DAILY_BRIEFING           = "daily_briefing"         # 日报生成（全市场）
    SECTOR_ANALYSIS          = "sector_analysis"

    # 风险类
    RISK_CHECK               = "risk_check"


class Priority(str, Enum):
    HIGH   = "high"
    NORMAL = "normal"
    LOW    = "low"


class CallbackMode(str, Enum):
    DB_WRITE   = "db_write"       # 写入 PostgreSQL
    A2A_STREAM = "a2a_stream"    # 流式推送回调用
    BOTH       = "both"          # 同时执行


# ─── 数据引用 URI ────────────────────────────────────────────────

class DataRef:
    """数据引用 URI，支持以下格式：

    - `duckdb://<table>/<id>`        — DuckDB 表记录
    - `pg://<table>/<id>`           — PostgreSQL 表记录
    - `minio://<bucket>/<path>`     — MinIO 对象存储
    - `memory://<date>/<key>`        — 记忆系统

    解析：
        ref = DataRef.parse("pg://investment_memos/12345")
        ref.table   → "investment_memos"
        ref.record_id → "12345"
    """

    def __init__(self, uri: str):
        self.uri = uri
        scheme, rest = uri.split("://", 1)
        self.scheme = scheme
        if "/" in rest:
            self.table, self.record_id = rest.split("/", 1)
        else:
            self.table, self.record_id = rest, None

    @classmethod
    def parse(cls, uri: str) -> "DataRef":
        return cls(uri)

    def __str__(self) -> str:
        return self.uri


# ─── 核心任务模型 ────────────────────────────────────────────────

@dataclass
class CallbackSpec:
    mode: CallbackMode                          # 回调模式
    target: str                                 # 目标地址（URI）
    schema: dict[str, Any] | None = None        # 期望的返回格式（可选）


@dataclass
class TaskParams:
    """任务参数（task_type 不同，params 结构也不同）"""

    # ── analyze_company_event ──
    company_code:  str | None = None            # 股票代码，如 "000001.SZ"
    event_type:    str | None = None            # earnings_release / abnormal_quote / new_announcement / ...
    data_refs:     list[str] = field(default_factory=list)

    # ── analyze_etf_event ──
    etf_code:      str | None = None            # ETF 代码，如 "512480"

    # ── analyze_market_event ──
    event_scope:   str | None = None            # 范围：global / sector / cross_border

    # ── collect_* ──
    limit:         int = 20                     # 采集数量上限
    days:          int = 3                      # 回溯天数

    # ── compute_alpha_signals / run_backtest ──
    lookback_days: int = 60                     # 回看天数
    strategy:     str | None = None             # 策略名称

    # ── score_etf ──
    min_score:     float = 60.0                 # 最低评分阈值

    # ── daily_briefing ──
    watchlist:     list[str] = field(default_factory=list)  # 关注标的列表

    # ── risk_check ──
    severity_threshold: str = "medium"          # 告警阈值

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TaskParams":
        return cls(**{k: v for k, v in d.items() if k in cls.__annotations__})


@dataclass
class Task:
    """主任务协议单元（CIA → JiuwenSwarm）"""

    task_id:       str
    task_type:     TaskType | None = None
    version:       str = "1.0"
    priority:      Priority = Priority.NORMAL
    created_by:    str = "openclaw_cia"
    created_at:    str = ""
    params:        TaskParams = field(default_factory=TaskParams)
    callback:      CallbackSpec | None = None
    sla_seconds:   int = 600
    max_retries:   int = 2
    idempotency_key: str = ""
    status:        str = "pending"
    tags:          list[str] = field(default_factory=list)


    def __post_init__(self):
        if self.created_at == "":
            from datetime import datetime
            self.created_at = datetime.now().isoformat()
        if isinstance(self.task_type, str):
            self.task_type = TaskType(self.task_type)
        if isinstance(self.priority, str):
            self.priority = Priority(self.priority)
        if isinstance(self.callback, dict):
            self.callback = CallbackSpec(**self.callback)

    # ── 工厂方法 ──────────────────────────────────────────────

    @classmethod
    def new(
        cls,
        task_type: TaskType,
        params: TaskParams | dict[str, Any],
        priority: Priority = Priority.NORMAL,
        callback: CallbackSpec | None = None,
        sla_seconds: int = 600,
        tags: list[str] | None = None,
    ) -> "Task":
        now = datetime.now().isoformat()
        if isinstance(params, dict):
            params = TaskParams.from_dict(params)

        # 生成 idempotency_key（可由调用方自行覆盖）
        key_parts = [
            "openclaw_cia",
            str(params.company_code or params.etf_code or ""),
            now[:10],
            task_type.value,
        ]
        idemp_key = "|".join(key_parts)


        return cls(
            task_id=str(uuid.uuid4()),
            task_type=task_type,
            created_at=now,
            priority=priority,
            params=params,
            callback=callback,
            sla_seconds=sla_seconds,
            idempotency_key=idemp_key,
            tags=tags or [],
        )

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict（含 dataclass 嵌套展开）"""
        d = asdict(self)
        d["task_type"] = self.task_type.value
        d["priority"] = self.priority.value
        d["callback"] = asdict(self.callback) if self.callback else None
        d["params"] = asdict(self.params)
        return d

    def to_jiuwen_prompt(self) -> str:
        """将任务翻译为 JiuwenSwarm 可理解的自然语言指令"""
        prompt = _build_prompt(self)
        return prompt


# ─── Prompt 模板（按 task_type） ─────────────────────────────────

def _build_prompt(task: Task) -> str:
    """将 Task 转换为 JiuwenSwarm 的输入 prompt"""
    t = task.task_type
    p = task.params
    tags = " ".join(task.tags)
    role = "[ETF量化分析师]" if t in (TaskType.ANALYZE_ETF_EVENT, TaskType.SCORE_ETF) else \
           "[A股基本面分析师]" if t == TaskType.ANALYZE_COMPANY_EVENT else \
           "[投研智能体]"

    base = f"{role} 任务标签：{tags}\n"

    if t == TaskType.ANALYZE_COMPANY_EVENT:
        return f"""{base}
请分析以下公司重大事件：

公司代码：{p.company_code}
事件类型：{p.event_type}
数据引用：{p.data_refs}

请按以下结构输出（JSON格式）：
{{
  "event_type": "{p.event_type}",
  "company_code": "{p.company_code}",
  "summary": "事件摘要（50字内）",
  "fundamental_impact": "基本面影响（F）",
  "quant_impact": "量化影响（Q）",
  "risk_signals": ["风险信号列表"],
  "confidence": 0.0-1.0,
  "next_watch": "后续关注点"
}}
"""

    elif t == TaskType.ANALYZE_ETF_EVENT:
        return f"""{base}
请分析以下ETF异动事件：

ETF代码：{p.etf_code}
事件类型：{p.event_type or "异动分析"}
数据引用：{p.data_refs}

请输出（JSON格式）：
{{
  "etf_code": "{p.etf_code}",
  "event_type": "{p.event_type or '异动'}",
  "summary": "异动摘要",
  "premium_impact": "溢价率影响",
  "liquidity_impact": "流动性影响",
  "risk_signals": ["风险信号"],
  "recommendation": "关注/谨慎"
}}
"""

    elif t == TaskType.SCORE_ETF:
        return f"""{base}
请对以下ETF进行综合评分：

ETF代码列表：{p.watchlist or [p.etf_code]}
评分截止日期：{datetime.now().strftime('%Y-%m-%d')}
最低入围分数：{p.min_score}

请输出（JSON格式）：
{{
  "calc_date": "...",
  "etfs": [
    {{
      "code": "...",
      "name": "...",
      "score": 0-100,
      "main_risks": ["..."],
      "highlights": ["..."]
    }}
  ]
}}
"""

    elif t == TaskType.COMPUTE_ALPHA_SIGNALS:
        return f"""{base}
请计算以下标的的 Alpha 信号：

标的列表：{p.watchlist or p.data_refs}
回看天数：{p.lookback_days}天

请输出各因子的标准化分数和综合信号。
"""

    elif t == TaskType.DAILY_BRIEFING:
        return f"""{base}
请生成今日（{datetime.now().strftime('%Y-%m-%d')}）A股市场简要日报：

关注标的：{p.watchlist or '全市场主要指数和ETF'}

请输出：
1. 今日市场概况（100字）
2. 重点关注标的简评（每条30字）
3. 风险提示（50字）
4. 明日关注（50字）
"""

    elif t == TaskType.RISK_CHECK:
        return f"""{base}
请执行风险扫描：

标的：{p.watchlist or '全部持仓标的'}
告警阈值：{p.severity_threshold}

请输出风险告警列表（JSON格式）：
{{
  "alerts": [
    {{
      "code": "...",
      "alert_type": "...",
      "severity": "critical/high/medium/low",
      "title": "...",
      "detail": "..."
    }}
  ]
}}
"""

    elif t == TaskType.COLLECT_RESEARCH_REPORTS:
        return f"""{base}
请采集以下公司最新券商研报：

公司代码：{p.company_code or p.watchlist}
回溯天数：{p.days}天
采集上限：{p.limit}篇

对每篇研报请提取：标题、评级、机构、目标价、核心观点。
"""

    else:
        return f"""{base}
任务类型：{t.value}
参数：{asdict(p)}
请执行并返回结构化结果。
"""


# ─── 结果归约模型 ────────────────────────────────────────────────

@dataclass
class TaskResult:
    """JiuwenSwarm 执行结果（写入 PostgreSQL）"""

    task_id:       str
    status:       str                              # completed / failed / timeout
    output:       dict[str, Any] | str | None     # 解析后结构化结果 or 原始文本
    raw_text:     str | None = None               # 原始文本（保留）
    artifacts:    list[dict] = field(default_factory=list)  # AgentResult artifacts
    completed_at: str | None = None               # ISO 8601
    elapsed_sec:  float | None = None
    retry_count:  int = 0

    def to_db_row(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "output": self.output if isinstance(self.output, str) else __import__("json").dumps(self.output),
            "raw_text": self.raw_text,
            "artifacts": __import__("json").dumps(self.artifacts),
            "completed_at": self.completed_at,
            "elapsed_sec": self.elapsed_sec,
            "retry_count": self.retry_count,
        }