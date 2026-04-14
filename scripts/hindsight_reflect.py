#!/usr/bin/env python3
"""
hindsight_reflect.py — Hindsight 反思系统
基于 Wiki @宁宝 方案：做→记→思→炼→用 闭环

触发方式（任选）：
  1. cron 每日自动运行（每日凌晨 3 点）
  2. 手动: python3 hindsight_reflect.py

流程：
  1. 读取昨日日记 + session transcript
  2. 提取：决策 / 踩坑 / 里程碑 / 问题
  3. 使用 "So what" 框架转化为可复用规则
  4. 写入 hindsight-reflections.md
  5. 如果连续 N 次无新内容，降低反思频率建议
"""

import os
import re
import json
from datetime import datetime, timedelta
from pathlib import Path

WORKSPACE = Path("/home/claw/.openclaw/workspace")
MEMORY_DIR = WORKSPACE / "memory"
DAILY_DIR = MEMORY_DIR / "daily"
HINDSIGHT_FILE = MEMORY_DIR / "hindsight-reflections.md"
SESSION_TRANSCRIPT_DIR = Path("/home/claw/.openclaw/agents/main/sessions")
STATS_FILE = MEMORY_DIR / ".hindsight_stats.json"

# 连续无新内容阈值
STAGNATION_THRESHOLD = 5

# ========== 提取逻辑 ==========

def extract_entries(date_str: str):
    """从指定日期的日记文件中提取条目"""
    diary_file = DAILY_DIR / f"{date_str}.md"
    if not diary_file.exists():
        return []
    content = diary_file.read_text(encoding="utf-8")
    entries = []

    # 提取决策
    decisions = re.findall(r'(?:^|\n)[-⚡*✅]*[Dd]ecision[：:]\s*(.+)', content)
    for d in decisions:
        entries.append({"type": "decision", "text": d.strip()})

    # 提取踩坑
    pitfalls = re.findall(r'(?:^|\n)[-⚡*❌]*([^\n]*(?:error|fail|wrong|mistake|bug|踩坑|错误)[^\n]*)', content, re.IGNORECASE)
    for p in pitfalls:
        entries.append({"type": "pitfall", "text": p.strip()})

    # 提取里程碑
    milestones = re.findall(r'(?:^|\n)[-⚡*🚀]*[Mm]ilestone[：:]\s*(.+)', content)
    for m in milestones:
        entries.append({"type": "milestone", "text": m.strip()})

    # 提取配置变更
    config_changes = re.findall(r'(?:^|\n)[-⚡*⚙️]*[Cc]onfig[：:]\s*(.+)', content)
    for c in config_changes:
        entries.append({"type": "config", "text": c.strip()})

    return entries

def so_what_transform(entry: dict) -> str:
    """
    'So what' 框架：将具体事件转化为抽象规则
    """
    text = entry["text"]
    e_type = entry["type"]

    if e_type == "decision":
        # 决策 → 原则
        return f"以后遇到类似场景，参考此决策：{text}"
    elif e_type == "pitfall":
        # 踩坑 → 预防规则
        return f"防止重蹈：{text}"
    elif e_type == "milestone":
        # 里程碑 → 经验
        return f"经验积累：{text}"
    elif e_type == "config":
        # 配置变更 → 操作规范
        return f"操作规范：{text}"
    return text

# ========== 查重：新内容判断 ==========

def is_new_insight(new_rule: str, existing_content: str) -> bool:
    """判断新反思是否已在已有内容中"""
    existing_lower = existing_content.lower()
    new_lower = new_rule.lower()
    # 简单关键词匹配
    keywords = re.findall(r'\w{4,}', new_lower)
    if not keywords:
        return True
    match_count = sum(1 for kw in keywords if kw in existing_lower)
    return match_count < len(keywords) * 0.6

# ========== 写入反思文件 ==========

def write_reflection(date_str: str, entries: list, existing_insights: str) -> int:
    """写入反思文件，返回新增条目数"""
    if not entries:
        return 0

    new_insights = []
    for entry in entries:
        rule = so_what_transform(entry)
        if is_new_insight(rule, existing_insights):
            new_insights.append(rule)

    if not new_insights:
        return 0

    # 追加到反思文件
    lines = [
        f"\n## {date_str}",
        f"来源：memory/daily/{date_str}.md",
        ""
    ]
    for insight in new_insights:
        lines.append(f"- **{entry['type'].upper()}** {insight}")

    lines.append("")  # 空行分隔

    with open(HINDSIGHT_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return len(new_insights)

# ========== 统计 & 饱和度检测 ==========

def load_stats() -> dict:
    if STATS_FILE.exists():
        return json.loads(STATS_FILE.read_text(encoding="utf-8"))
    return {"consecutive_empty": 0, "last_run": None, "total_insights": 0}

def save_stats(stats: dict):
    STATS_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

def check_stagnation(stats: dict) -> str:
    """连续多次无新内容 → 建议降低频率"""
    if stats["consecutive_empty"] >= STAGNATION_THRESHOLD:
        return f"[⚠️ 反思饱和警告] 连续 {stats['consecutive_empty']} 次无新内容，建议降低反思频率（当前每日）"
    return ""

# ========== 主流程 ==========

def run(days_back: int = 1):
    """
    主流程：
      1. 扫描最近 N 天日记
      2. 提取条目并写入反思文件
      3. 更新统计
      4. 报告结果
    """
    today = datetime.now()
    stats = load_stats()
    total_new = 0

    # 读取已有反思内容（用于去重）
    existing_insights = HINDSIGHT_FILE.read_text(encoding="utf-8") if HINDSIGHT_FILE.exists() else ""

    # 初始化反思文件
    if not HINDSIGHT_FILE.exists():
        HINDSIGHT_FILE.write_text(
            "# Hindsight 反思记录\n\n做→记→思→炼→用 闭环反思。\n",
            encoding="utf-8"
        )

    results = []

    for i in range(days_back):
        date = today - timedelta(days=i+1)
        date_str = date.strftime("%Y-%m-%d")
        entries = extract_entries(date_str)

        if not entries:
            results.append(f"[{date_str}] 无可提取条目")
            continue

        new_count = write_reflection(date_str, entries, existing_insights)
        existing_insights += "\n".join([so_what_transform(e) for e in entries])  # 更新已有内容
        total_new += new_count

        if new_count > 0:
            results.append(f"[{date_str}] +{new_count} 条新反思")
        else:
            results.append(f"[{date_str}] 无新增（重复）")

    # 更新统计
    if total_new > 0:
        stats["consecutive_empty"] = 0
        stats["total_insights"] += total_new
    else:
        stats["consecutive_empty"] += 1

    stats["last_run"] = datetime.now().isoformat()
    save_stats(stats)

    # 报告
    stagnation_msg = check_stagnation(stats)
    report = [
        f"🧠 Hindsight 反思 — {today.strftime('%Y-%m-%d')}",
        f"扫描：最近 {days_back} 天",
        f"新增洞察：{total_new}",
        "",
        "---",
        *results,
        "",
        f"累计洞察：{stats['total_insights']}",
        f"连续空轮次：{stats['consecutive_empty']}",
    ]
    if stagnation_msg:
        report.append(stagnation_msg)

    print("\n".join(report))

    # 写入日志
    log_file = DAILY_DIR / f"{today.strftime('%Y-%m-%d')}-hindsight.md"
    log_file.write_text("\n".join(report), encoding="utf-8")

    return total_new

if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    run(days)
