#!/usr/bin/env python3
"""
workspace_cleanup.py — 每周工作区整理检查脚本
按 AGENTS.md 规则评估文件保存状态，输出结构化报告。
"""

import os
import stat
from pathlib import Path

WORKSPACE = Path("/home/claw/.openclaw/workspace")

# === 规则定义 ===

ROOT_FILES = {  # 根目录系统文件（必须保留）
    "AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md",
    "MEMORY.md", "TOOLS.md", "HEARTBEAT.md", "BOOTSTRAP.md",
    "DREAMS.md", "SESSION-STATE.md",
}

SYSTEM_DIRS = {  # 系统目录（不检查内容）
    ".git/", ".openclaw/", "secrets/", "skill/",
}

ALLOWED_TOP_DIRS = {  # 顶层允许的目录
    "memory", "projects", "scripts", "notes",
    "state", "clash-for-linux-install",
}

# memory/.dreams/ 是 OpenClaw 梦境系统生成，由系统管理，不纳入检查
DREAMS_DIR = "memory/.dreams/"

REPORT_FILES_ALLOWED_IN_ROOT = {".md", ".json"}  # 根目录允许的扩展名
REPORT_MAX_SIZE_KB = 50  # 单个报告文件超过此大小应拆分

issues = []
suggestions = []

def check_root_files():
    """检查根目录文件是否符合规则"""
    root = WORKSPACE
    for f in root.iterdir():
        if f.is_file():
            name = f.name
            # 跳过系统文件
            if name in ROOT_FILES:
                continue
            # 允许的配置/数据文件
            if name.endswith(('.json', '.yaml', '.yml', '.toml', '.env')):
                continue
            # 问题：根目录有非系统文件
            issues.append(f"根目录非系统文件: {name} (应归档到 memory/daily/ 或对应目录)")
        elif f.is_dir():
            dirname = f.name
            if dirname.startswith("."):
                continue
            # SYSTEM_DIRS entries may have trailing slash
            system_dirs_no_slash = {d.rstrip("/") for d in SYSTEM_DIRS}
            if dirname in system_dirs_no_slash:
                continue
            if dirname not in ALLOWED_TOP_DIRS:
                if "clash" in dirname or "install" in dirname:
                    suggestions.append(f"第三方安装目录，建议移除或归档: {dirname}/")
                else:
                    issues.append(f"根目录非标准目录: {dirname}/")

def check_memory_structure():
    """检查 memory/ 目录结构"""
    mem = WORKSPACE / "memory"
    if not mem.exists():
        issues.append("memory/ 目录缺失")
        return

    # 检查 daily/ 是否有日志
    daily = mem / "daily"
    if daily.exists():
        logs = list(daily.glob("*.md"))
        if not logs:
            suggestions.append("memory/daily/ 为空，无日常日志")
        else:
            # 检查是否有超大日志文件
            for log in logs:
                size_kb = log.stat().st_size / 1024
                if size_kb > REPORT_MAX_SIZE_KB:
                    issues.append(f"日志过大应拆分: {log.relative_to(WORKSPACE)} ({size_kb:.0f}KB)")

    # 检查残留的巨型单日志文件（直接在 memory/ 下，排除 .dreams/ 和系统文件）
    for f in mem.iterdir():
        if f.is_file() and f.suffix == ".md" and f.name not in ("MEMORY.md",):
            # 2026-04-14.md 是 OpenClaw 梦境系统生成的日志，由系统管理，跳过
            if f.name.startswith("2026-"):
                continue
            size_kb = f.stat().st_size / 1024
            if size_kb > 20:
                issues.append(f"memory/ 根目录遗留日志应归档: {f.name} ({size_kb:.0f}KB)")

def check_daily_log_naming():
    """检查日常日志命名规范"""
    daily = WORKSPACE / "memory" / "daily"
    if not daily.exists():
        return
    for f in daily.glob("*.md"):
        name = f.name
        # 正确格式: YYYY-MM-DD.md 或 YYYY-MM-DD-TOPIC.md
        if not (name[0:4].isdigit() and name[4] == "-" and name[5:7].isdigit()):
            issues.append(f"日志命名不规范: {f.relative_to(WORKSPACE)} (应为 YYYY-MM-DD 或 YYYY-MM-DD-TOPIC.md)")

def check_projects_dir():
    """检查 projects/ 目录"""
    proj = WORKSPACE / "projects"
    if not proj.exists():
        return
    for item in proj.iterdir():
        if item.is_dir():
            # 检查是否有过大的 browser_profile 缓存
            if "browser_profile" in item.name:
                size_mb = sum(f.stat().st_size for f in item.rglob("*") if f.is_file()) / 1024 / 1024
                if size_mb > 500:
                    suggestions.append(f"Browser profile 缓存较大 ({size_mb:.0f}MB): {item.name} — 可考虑清理旧会话缓存")

def check_notes_dir():
    """检查 notes/ 目录"""
    notes = WORKSPACE / "notes"
    if not notes.exists():
        return
    for f in notes.rglob("*"):
        if f.is_file() and f.suffix not in (".md", ".txt", ".pdf"):
            suggestions.append(f"notes/ 包含非标准文件: {f.relative_to(WORKSPACE)}")

def check_learnings_dir():
    """检查 .learnings/ 目录"""
    lrn = WORKSPACE / ".learnings"
    if not lrn.exists():
        return
    # 定期检查是否有过期的 corrections 或空的 record 文件
    for f in lrn.glob("*.md"):
        if f.stat().st_size == 0 and f.name not in ("HOT.md", "ERRORS.md", "FEATURE_REQUESTS.md", "PREFERENCES.md", "corrections.md"):
            suggestions.append(f".learnings/ 空文件可删除: {f.name}")

def check_state_dir():
    """检查 state/ 目录（应为空）"""
    state = WORKSPACE / "state"
    if state.exists() and any(state.iterdir()):
        issues.append("state/ 目录非空，应保持空目录或删除")

def main():
    print("🔍 开始工作区检查...\n")

    check_root_files()
    check_memory_structure()
    check_daily_log_naming()
    check_projects_dir()
    check_notes_dir()
    check_learnings_dir()
    check_state_dir()

    print(f"📊 检查完成\n")
    print(f"❌ 问题 ({len(issues)}):")
    for issue in issues:
        print(f"   • {issue}")

    print(f"\n💡 建议 ({len(suggestions)}):")
    for s in suggestions:
        print(f"   • {s}")

    if not issues and not suggestions:
        print("   ✅ 工作区整洁，无问题")
    elif not issues:
        print("\n   ✅ 无阻塞问题")

    # 输出摘要（供 cron 任务报告用）
    print(f"\n=== SUMMARY ===")
    print(f"issues={len(issues)}")
    print(f"suggestions={len(suggestions)}")

if __name__ == "__main__":
    main()
