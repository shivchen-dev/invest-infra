---
name: memory-sync-protocol
description: Synchronize durable behavior or preference changes across TOOLS.md, MEMORY.md, AGENTS.md, and memory/YYYY-MM-DD.md with one consistent workflow. Use when user says to remember/update rules, skill routing, defaults, operating conventions, or asks for "sync across files" / "记住并同步" / "更新记忆治理".
---

# Memory Sync Protocol

When this skill is triggered, execute the following sequence:

## 1) Classify the change
| 内容类型 | 存储位置 |
|----------|----------|
| 执行细节、工具用法 | TOOLS.md |
| 高层偏好、核心规则、热锚点 | MEMORY.md(只存"去哪找") |
| 叙事性内容(决策/项目/错误) | **Memvid Smart Frames** |
| 治理策略、角色权限 | AGENTS.md |
| 当日变更日志 | memory/YYYY-MM-DD.md |

## 2) Update files
- MEMORY.md:只写高层摘要和"去哪找"(热锚点 + 指向链接)
- 详细配置写入对应文档
- 避免多文件间复制大段内容

## 3) Write to Memvid Smart Frames
```python
import os
from pathlib import Path
from memvid_sdk import use  # verified 2026-06-10: API exists in ~/.venv/memvid

WORKSPACE = Path(os.environ.get("WORKSPACE", "~/.openclaw/workspace")).expanduser()
memvid_file = WORKSPACE / "memory" / "arc-memory.mv2"

if not memvid_file.parent.exists():
    raise FileNotFoundError(f"Memory directory not found: {memvid_file.parent}")

mem = use('basic', str(memvid_file))
mem.put(
    title='变更：...',
    label='sync',
    metadata={'date': 'YYYY-MM-DD', 'files': [...]},
    text='详细变更内容...'
)
```

## 4) Append daily log
In `memory/YYYY-MM-DD.md`, record: what changed, why, affected files.

## 5) Git commit
Commit with semantic message: `docs(routing): ...`, `docs(memory): ...`, etc.

## 6) Post-sync - QMD Index Update
When any indexed memory file changes, update QMD:
```bash
# qmd update / qmd embed do NOT support per-collection filter
# (verified 2026-06-11: `qmd update -c X` silently ignores -c).
# Both are idempotent and fast: only changed files re-index.
# Side benefit: dead collections (e.g. browser-memory after workspace
# deletion) get auto-pruned to 0 files on the next run.

# Re-index all collections (no -c supported)
qmd update || echo "WARN: qmd update failed" >&2

# Regenerate embeddings (GGML_CUDA_USE_ALLOCATOR=0 avoids CUDA allocator errors)
GGML_CUDA_USE_ALLOCATOR=0 qmd embed || \
    echo "WARN: qmd embed failed" >&2
```

**Trigger**: MEMORY.md, AGENTS.md, TOOLS.md, SOUL.md, IDENTITY.md, BOOTSTRAP.md, or memory/*.md changed.

## 7) Return sync report
- List updated files
- Memvid write status
- Key changes summary
- Commit info
- QMD update status

---

## Memvid 环境

- **Python venv**：`$VENV_PYTHON` env var → fallback `~/.venv/memvid/bin/python3` → fallback `python3 -m memvid_sdk` if package is on PYTHONPATH
- **Workspace 根**：`$WORKSPACE` env var → fallback `~/.openclaw/workspace`（每个 agent 设自己的值，例如 cia 设 `~/.openclaw/workspace-cia`）
- **Memvid 文件**：`${WORKSPACE}/memory/arc-memory.mv2`（每个 agent 自己的）
- **写入脚本**：`${WORKSPACE}/scripts/memvid_writer.py --interactive`（已验证存在）

---

## 记忆体系架构(更新后)

```
MEMORY.md(纯索引 ~50行)
    ↓ 指向
Memvid Smart Frames(叙事层,append-only)
    ↓ 兜底
memory/*.md(原始日志,QMD 搜索)
```