# TOOLS.md - Local Notes

## 记忆系统架构

### 三层检索协议（OpenClaw → Arc）
1. **MEMORY.md** — 热缓存，高价值低噪音（~50行）
2. **QMD** — 触发后二次检索，语义+关键词
3. **memory/ 目录** — 详细档案/日志/知识

### QMD 检索规则
- **优先级**: `title exact` → `keyword` → `semantic`
- **命中处理**: top-k(3-5) → 片段(5-20行) → 摘要注入
- **入库标准**: 满足≥2条 — 影响决策(>2周)/重复使用/损失风险/可验证

---

## QMD - 本地文档搜索

- **Collection**: `workspace-memory`
- **Source path**: `/home/claw/.openclaw/workspace/memory`
- **模型缓存**: `~/.cache/qmd/models/`
- **命令**:
  - `qmd search "关键词" -c workspace-memory`（全文 BM25）
  - `qmd query "语义查询" -c workspace-memory`（混合搜索，GPU加速）
  - `qmd vsearch "查询" -c workspace-memory`（向量搜索）
  - `qmd get qmd://workspace-memory/path/to/file.md`（获取文档）
- **Context**: Arc记忆系统路由：MEMORY.md → memory/ → QMD检索 → 分层注入
- **GPU**: AMD 780M (Vulkan), VRAM 7.9GB free

---

## 环境信息

- **GPU**: AMD Radeon 780M (Phoenix3) — Vulkan 加速
- **NFS**: 192.168.6.6:/（不可用，无 root 权限挂载）
- **模型路径**: ~/.cache/qmd/models/
