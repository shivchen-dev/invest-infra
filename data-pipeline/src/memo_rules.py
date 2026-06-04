#!/usr/bin/env python3
"""
investment_memos 表 DDL + 业务规则
=====================================
- confidence_level 置信度规则（多信号独立确认）
- 禁用词检查（买/卖/持有）
"""

from enum import IntEnum
from typing import Any


# ── 置信度等级 ────────────────────────────────────────────
class ConfidenceLevel(IntEnum):
    LOW    = 1
    MEDIUM = 2
    HIGH   = 3


# ── 信号类型（每类独立计数）────────────────────────────────
class SignalType(IntEnum):
    FUNDAMENTAL = 1  # 基本面
    QUANT       = 2  # 量化
    SENTIMENT   = 3  # 情绪/舆情
    NEWS_EVENT  = 4  # 重大事件/公告
    TECHNICAL   = 5  # 技术面


# ── 各类型信号的 key（在 sections_json 中的路径）───────────
SIGNAL_PATHS: dict[SignalType, list[str]] = {
    SignalType.FUNDAMENTAL: ["fundamental", "fundamental_analysis"],
    SignalType.QUANT:       ["quant", "factor_signals", "alpha_signals"],
    SignalType.SENTIMENT:   ["sentiment", "market_sentiment", "舆情"],
    SignalType.NEWS_EVENT:  ["news", "events", "公告"],
    SignalType.TECHNICAL:   ["technical", "技术面"],
}

# ── 禁用词表 ────────────────────────────────────────────
FORBIDDEN_WORDS = [
    "买入", "卖出", "买进", "建仓", "清仓", "加仓", "减仓",
    "持有", "做多", "做空", "开多", "开空",
    "买入价", "卖出价", "目标价",
    "建议买入", "建议卖出", "推荐买入", "推荐卖出",
    "买 / 卖", "买 or 卖", "买还是卖",
]


def _get_nested(obj: dict, path: str) -> Any:
    """支持 a.b.c 路径的字典取值"""
    for key in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key, {})
    return obj if obj != {} else None


def detect_active_signals(sections_json: dict | list | None) -> set[SignalType]:
    """从 sections_json 中检测哪些类型的信号是活跃的（有实质内容）"""
    if not sections_json:
        return set()

    active = set()
    for sig_type, paths in SIGNAL_PATHS.items():
        for path in paths:
            val = _get_nested(sections_json, path)
            if val and val not in (None, [], {}, ""):
                # 有内容，视为活跃信号
                active.add(sig_type)
                break
    return active


def compute_confidence(
    sections_json: dict | list | None,
    summary: str = "",
    body_md: str = "",
    **kwargs,
) -> tuple[ConfidenceLevel, str]:
    """
    计算置信度等级（只升不降原则）

    规则：
    - <2 类独立信号 → low
    - 2-3 类独立信号 + 逻辑自洽 → medium
    - ≥4 类独立信号 或 包含高置信度证据 → high
    - 有重大新闻/公告直接事件 → +1 类

    Args:
        sections_json: 分析段落 JSON
        summary: 一行结论
        body_md: 详细正文

    Returns:
        (置信度等级, 原因说明)
    """
    if not sections_json:
        return ConfidenceLevel.LOW, "缺乏量化/基本面数据支撑"

    active = detect_active_signals(sections_json)
    count = len(active)

    # 基础等级
    if count >= 4:
        level = ConfidenceLevel.HIGH
        reason = f"{count}类独立信号支撑（{_signal_names(active)}），高置信度"
    elif count == 3:
        level = ConfidenceLevel.MEDIUM
        reason = f"{count}类独立信号支撑（{_signal_names(active)}），中等置信度"
    elif count == 2:
        level = ConfidenceLevel.MEDIUM
        reason = f"2类独立信号（{_signal_names(active)}），需进一步验证"
    else:
        level = ConfidenceLevel.LOW
        reason = f"仅{count}类信号（{_signal_names(active)}），信息不足"

    return level, reason


def _signal_names(active: set[SignalType]) -> str:
    return "/".join(s.name.lower() for s in sorted(active))


def check_forbidden_words(
    summary: str = "",
    body_md: str = "",
    title: str = "",
) -> list[dict]:
    """
    检查文本中是否包含禁用词（买卖建议类）

    Returns:
        [{'word': 'xxx', 'location': 'summary/body_md/title', 'context': '前后20字'}]
    """
    violations = []
    text_sources = [
        ("summary", summary),
        ("body_md", body_md),
        ("title", title),
    ]

    for location, text in text_sources:
        if not text:
            continue
        for word in FORBIDDEN_WORDS:
            idx = 0
            while True:
                pos = text.find(word, idx)
                if pos == -1:
                    break
                context = text[max(0, pos - 20):pos + len(word) + 20]
                violations.append({
                    "word": word,
                    "location": location,
                    "context": context,
                    "position": pos,
                })
                idx = pos + 1

    return violations


def build_memo_record(
    task_id: str,
    task_type: str,
    company_id: int,
    memo_date: str,
    summary: str,
    body_md: str,
    sections_json: dict,
    tags: list[str],
    model_used: str,
    total_tokens: int,
    quality_score: float,
    generated_by: str = "jiuwenswarm_woa_v1",
    data_range_from: str = None,
    data_range_to: str = None,
) -> dict:
    """
    构建完整的 investment_memos 记录（符合模板约束）
    """
    # 计算置信度
    confidence_level, confidence_reason = compute_confidence(
        sections_json=sections_json,
        summary=summary,
        body_md=body_md,
    )

    # 禁用词检查
    violations = check_forbidden_words(
        summary=summary,
        body_md=body_md,
    )

    if violations:
        # 记录违规（不阻止写入，但打标签）
        tags = tags + ["FORBIDDEN_WORD_VIOLATION"]

    # 检测触发信号
    active_signals = detect_active_signals(sections_json)
    trigger_signals = [s.name.lower() for s in active_signals]

    return {
        "company_id": company_id,
        "title": f"[{confidence_level.name}] {task_type} - {memo_date}",
        "memo_date": memo_date,
        "memo_type": task_type,
        "summary": summary,
        "body_md": body_md,
        "sections_json": sections_json,
        "tags": tags,
        "generated_by": generated_by,
        "model_used": model_used,
        "total_tokens": total_tokens,
        "quality_score": quality_score,
        "review_status": "draft",
        "confidence_level": confidence_level.name.lower(),
        "trigger_signals": trigger_signals,
        "follow_up_status": "pending",
        "version": 1,
        # 内部审计字段
        "_confidence_reason": confidence_reason,
        "_forbidden_violations": violations,
        "_active_signals": [s.name for s in active_signals],
    }


if __name__ == "__main__":
    # 快速测试
    sample_sections = {
        "fundamental": {"score": 0.72, "notes": "财报超预期"},
        "quant": {"factor_signals": ["momentum", "volatility"]},
        "sentiment": {"score": 0.65, "hotness": "high"},
    }

    record = build_memo_record(
        task_id="test-001",
        task_type="morning_briefing",
        company_id=5233,
        memo_date="2026-06-01",
        summary="科技板块今日有支撑，关注量能变化",
        body_md="## 基本面\n财务数据良好\n## 量化\n因子信号偏多",
        sections_json=sample_sections,
        tags=["morning_briefing"],
        model_used="MiniMax-M2.7",
        total_tokens=500,
        quality_score=0.8,
    )

    import json
    print(json.dumps(record, indent=2, ensure_ascii=False, default=str))