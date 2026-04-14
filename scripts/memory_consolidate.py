#!/usr/bin/env python3
"""
memory_consolidate.py — 记忆系统自动整理脚本
基于 Wiki @宁宝 方案：归档 + 查重 + 文件检测 + 冗余清理
"""

import os
import json
import hashlib
import time
from datetime import datetime, timedelta
from pathlib import Path
import re

WORKSPACE = Path("/home/claw/.openclaw/workspace")
MEMORY_DIR = WORKSPACE / "memory"
ARCHIVE_DIR = MEMORY_DIR / "archive"
DAILY_DIR = MEMORY_DIR / "daily"
HINDSIGHT_FILE = WORKSPACE / "memory" / "hindsight-reflections.md"
WAL_FILE = MEMORY_DIR / ".memory_wal.jsonl"

ARCHIVE_THRESHOLD_DAYS = 14
MAX_FILE_SIZE_KB = 50
DEDUP_SIMILARITY_THRESHOLD = 0.85

# ========== WAL 审计日志 ==========

def wal_log(action: str, path: str, detail: str = ""):
    """记录所有记忆操作到 WAL"""
    entry = {
        "ts": datetime.utcnow().isoformat(),
        "action": action,
        "path": str(path),
        "detail": detail
    }
    with open(WAL_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

# ========== 归档：14天前日记 → archive/周摘要 ==========

def get_week_key(date: datetime) -> str:
    """获取日期所在的周键 (e.g. 2026-W15)"""
    week_num = date.isocalendar()[1]
    return f"{date.year}-W{week_num:02d}"

def archive_old_diaries():
    """将 14 天前的日记归档为周度摘要"""
    ARCHIVE_DIR.mkdir(exist_ok=True)
    cutoff = datetime.now() - timedelta(days=ARCHIVE_THRESHOLD_DAYS)
    archived = []

    for df in DAILY_DIR.glob("????-??-??.md"):
        try:
            mtime = datetime.fromtimestamp(df.stat().st_mtime)
        except:
            continue
        if mtime < cutoff:
            # 读取内容
            content = df.read_text(encoding="utf-8")
            week_key = get_week_key(mtime)
            archive_file = ARCHIVE_DIR / f"{week_key}.md"

            # 追加到周度摘要（去重）
            if archive_file.exists():
                existing = archive_file.read_text(encoding="utf-8")
                if content not in existing:
                    with open(archive_file, "a", encoding="utf-8") as f:
                        f.write(f"\n---\n## {df.name}\n{content}")
                    wal_log("archive-append", str(df), week_key)
            else:
                archive_file.write_text(content, encoding="utf-8")
                wal_log("archive-new", str(df), week_key)

            # 标记待删除（不在本次脚本中删除，由调用方确认）
            archived.append(df.name)

    return archived

# ========== 查重：哈希 + 语义相似度 ==========

def sha256_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def simple_similarity(a: str, b: str) -> float:
    """简易词集相似度（避免导入重型依赖）"""
    tokens_a = set(re.findall(r'\w+', a.lower()))
    tokens_b = set(re.findall(r'\w+', b.lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)

def find_duplicates_in_daily():
    """扫描日记目录，检测重复条目"""
    files = sorted(DAILY_DIR.glob("????-??-??.md"), key=lambda f: f.name)
    hashes = {}  # sha256 → (filename, content)
    duplicates = []

    for f in files:
        content = f.read_text(encoding="utf-8")
        h = sha256_content(content)
        if h in hashes:
            duplicates.append((f.name, hashes[h][0]))
            wal_log("dedup-hash-dup", str(f), hashes[h][0])
        else:
            # 语义相似度检测
            for prev_h, (prev_f, prev_c) in hashes.items():
                sim = simple_similarity(content, prev_c)
                if sim >= DEDUP_SIMILARITY_THRESHOLD:
                    duplicates.append((f.name, prev_f, sim))
                    wal_log("dedup-semantic-dup", str(f), f"{prev_f}@{sim:.2f}")
                    break
            hashes[h] = (f.name, content)

    return duplicates

# ========== 文件检测：超限文件 ==========

def check_oversized_files():
    """检测超过 MAX_FILE_SIZE_KB 的 Markdown 文件"""
    oversized = []
    for md in MEMORY_DIR.rglob("*.md"):
        if md.is_file():
            size_kb = md.stat().st_size / 1024
            if size_kb > MAX_FILE_SIZE_KB:
                oversized.append((str(md.relative_to(WORKSPACE)), size_kb))
                wal_log("file-oversized", str(md), f"{size_kb:.1f}KB")
    return oversized

# ========== 孤立 / 空文件清理 ==========

def cleanup_orphan_temp_files():
    """清理孤立的空文件或临时文件"""
    cleaned = []
    patterns = ["*.tmp", "*.temp", "*_backup.md", "*_old.md"]
    for p in patterns:
        for f in MEMORY_DIR.rglob(p):
            if f.is_file() and f.stat().st_size == 0:
                f.unlink()
                cleaned.append(str(f))
                wal_log("cleanup-orphan", str(f))
    return cleaned

# ========== 报告生成 ==========

def generate_report(archived, duplicates, oversized, cleaned):
    """生成整理报告"""
    lines = [
        f"# 记忆整理报告 — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"| 操作类型 | 数量 |",
        f"|----------|------|",
        f"| 归档日记 | {len(archived)} |",
        f"| 重复条目 | {len(duplicates)} |",
        f"| 超限文件 | {len(oversized)} |",
        f"| 清理项   | {len(cleaned)} |",
        "",
    ]
    if archived:
        lines.append(f"### 归档 ({len(archived)}项)")
        for a in archived:
            lines.append(f"- {a}")
    if duplicates:
        lines.append(f"\n### 重复检测 ({len(duplicates)}项)")
        for d in duplicates:
            if len(d) == 2:
                lines.append(f"- {d[0]} ↔ {d[1]} (哈希相同)")
            else:
                lines.append(f"- {d[0]} ↔ {d[1]} (相似度 {d[2]:.2f})")
    if oversized:
        lines.append(f"\n### 超限文件 ({len(oversized)}项)")
        for p, kb in oversized:
            lines.append(f"- {p} ({kb:.1f}KB)")
    if cleaned:
        lines.append(f"\n### 已清理 ({len(cleaned)}项)")
        for c in cleaned:
            lines.append(f"- {c}")

    return "\n".join(lines)

# ========== 主流程 ==========

def run():
    print("[memory_consolidate] 开始整理...")
    archived = archive_old_diaries()
    duplicates = find_duplicates_in_daily()
    oversized = check_oversized_files()
    cleaned = cleanup_orphan_temp_files()

    report = generate_report(archived, duplicates, oversized, cleaned)
    print(report)

    # 写入归档报告
    report_file = DAILY_DIR / f"{datetime.now().strftime('%Y-%m-%d')}-consolidate.md"
    report_file.write_text(report, encoding="utf-8")
    wal_log("report-written", str(report_file))

    print(f"\n整理完成。报告已写入: {report_file.name}")
    return report

if __name__ == "__main__":
    run()
