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
| 高层偏好、核心规则、热锚点 | MEMORY.md（只存"去哪找"） |
| 治理策略、角色权限 | AGENTS.md |
| 当日变更日志 | memory/YYYY-MM-DD.md |

## 2) Update files
- MEMORY.md：只写高层摘要和"去哪找"（热锚点 + 指向链接）
- 详细配置写入对应文档
- 避免多文件间复制大段内容

## 3) Append daily log
In `memory/YYYY-MM-DD.md`, record: what changed, why, affected files.

## 4) Git commit
Commit with semantic message: `docs(routing): ...`, `docs(memory): ...`, etc.

## 5) Post-sync - QMD Index Update
When any indexed memory file changes, update QMD:
```bash
# Update collection index
qmd collection update browser-memory 2>/dev/null || qmd update

# Regenerate embeddings (use GGML_CUDA_USE_ALLOCATOR=0 if CUDA error)
GGML_CUDA_USE_ALLOCATOR=0 qmd embed -c browser-memory 2>/dev/null || GGML_CUDA_USE_ALLOCATOR=0 qmd embed
```

**Trigger**: MEMORY.md, AGENTS.md, TOOLS.md, SOUL.md, IDENTITY.md, BOOTSTRAP.md, or memory/*.md changed.

## 6) Return sync report
- List updated files
- Key changes summary
- Commit info
- QMD update status
