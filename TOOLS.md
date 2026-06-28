# TOOLS.md - Local Notes

> 本文件是**工具层执行手册**，记录 how to do。
> 政策层（为什么这么做）→ `CLAUDE-CODE.md`；知识档案 → `kb/`。

---

## GTD 工具（gtd-tools skill）

**⚠️ 操作 GTD 必须使用 gtd-tools skill（v3.6）**

### gtd-sync.py — v3.6 统一入口（唯一）
```bash
# 流转（每个节点完成的唯一合规交付动作）
python3 /home/claw/.openclaw/GTD/scripts/gtd-sync.py route agree   <task_id> <caller>
python3 /home/claw/.openclaw/GTD/scripts/gtd-sync.py route reject  <task_id> <caller> --reason <驳回理由>

# 列表
python3 /home/claw/.openclaw/GTD/scripts/gtd-sync.py list

# 校验（派单创建/流转后必做）
python3 /home/claw/.openclaw/GTD/scripts/gtd-sync.py validate [task_id]

# 打印 dispatch.md 模板
python3 /home/claw/.openclaw/GTD/scripts/gtd-sync.py template

# 单元测试
python3 /home/claw/.openclaw/GTD/scripts/gtd-sync.py test
```

### 目录结构（v3.6）
```
GTD/
├── 进行中/     ← 活着的任务
├── 归档/       ← 已终态
└── _recalled/ ← 召回记录
```
（旧的 1-dispatched/2-in-progress/3-re-audit/4-completed 保留兼容）

### 流转规则（v3.6）
- **agree**：当前节点 → 下一节点；最后节点 → 自动归档
- **reject**：当前节点 → 上一节点；已归档任务 reject → 强制拦截（需用户授权）
- **禁止静默交付**：完成工作 ≠ 交付，`route agree` = 唯一合规交付动作
- **route 后写 Inbox**：每次 `route agree/reject/pause/resume` 成功后，自动向各 Agent Inbox 写 JSONL 事件
- **无 registry.json**：物理目录为唯一权威，禁止手动 edit

### 校验规则（gtd-sync.py validate）
| 规则 | 说明 |
|---|---|
| A1 | project 派单缺 ## 审批流章节 / 工序 N+1 签字时 N 必须先签 |
| A3 | task_source 非法 / D-1 自派单 |
| A4 | 状态变更日志 hash 不匹配（防篡改）|
| A5 | completion_criteria 缺失或为空 |
| P0 | 强制交付物未填写（route agree 时拦截）|
| LOC | dispatch.md 在无效状态目录 |
| ID-MATCH | task_id 文件夹名与 dispatch.md 内的 task_id 不一致 |

### 技能入口
> 派单给 CC 前 / 流转状态 / 校验派单 → 使用 gtd-tools skill

---

## 记忆系统架构

```
MEMORY.md（纯索引 ~50行）
    ↓ 指向
Memvid Smart Frames（叙事层，append-only）
    ↓ 兜底
memory/*.md（原始日志，QMD 搜索）
```

### Memvid（Smart Frames 叙事层）
- **文件**: `memory/arc-memory.mv2`（~5.2MB，40条记录）
- **环境**: `~/.venv/memvid/bin/python3`
- **用途**: append-only Smart Frames，新记忆写入，叙事整合
- **搜索**: `mem.find(query, mode='lex')` — BM25 模式
- **迁移脚本**: `scripts/memvid_migration.py`
- **写入脚本**: `scripts/memvid_writer.py --interactive`

### QMD 检索规则
- **优先级**: `title exact` → `keyword` → `semantic`
- **命中处理**: top-k(3-5) → 片段(5-20行) → 摘要注入
- **入库标准**: 满足≥2条 — 影响决策(>2周)/重复使用/损失风险/可验证
- **注意**: QMD 向量正常（1362 embeddings），BM25 兜底

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
  - `qmd update`（re-index 所有 collection，**不支持 -c**，幂等）
  - `GGML_CUDA_USE_ALLOCATOR=0 qmd embed`（重新嵌入，**不支持 -c**）
- **Context**: Arc记忆系统路由：MEMORY.md → memory/ → QMD检索 → 分层注入
- **GPU**: AMD 780M (Vulkan), VRAM 7.9GB free
- **踩坑（2026-06-11）**:
  - `qmd update` 和 `qmd embed` **都没有 per-collection 过滤**，`-c` 被静默忽略
  - 两者都**幂等**：未变文件 0 工作量；死 collection（路径不存在）自动 0 files
  - 嵌入器: `embeddinggemma-300M-Q8_0.gguf`，3 docs / 9 chunks ≈ 2s

---

## 🚨 MCP 教训 — 投研系统 PG-First 根因（2026-06-15 立）

**背景：** R0.2 数据管道 bug 复盘（commit 3ea5ef3）

| 现象 | 根因 | 修复 |
|------|------|------|
| 14/14 ETF 现价=0 | `mcpClient.ts` 调错服务器（127.0.0.1:19100 = JiuwenClaw Gateway，不是 wudao_aStock MCP）| 换 PG `etf_quotes` 直读（441,979 行 cron 落库）|
| 不同 code 返回同一份数据 | **wudao_aStock MCP vendor bug**（半导体的 26.23 给所有 ETF）| 同上 |
| rebalance 13 alert 全部崩 | 上游现价=0 → 涨跌幅=0 → 偏离度=0 → 无 alert | 改 PG 后全 13 alert 正确 |

**铁律（用户 2026-06-15 15:14 立）：**

- 🚫 投研系统**查询时**只走 PG，禁止 MCP fallback
- ⚠️ 数据缺失 → 修采集层（cron），不修模块
- ✅ 唯一允许接触 MCP 的层 = 采集层（data-pipeline 内的 cron）
- 🚨 采集层异常 → 立即告警，不让消费层察觉（消费层要"看起来一切正常"）

**实现要点（避免重蹈）：**

- 采集层：data-pipeline 的 15:05 / 09:25 / 09:00 cron 仍可调 MCP，但**结果必须落库**（`daily_market_snapshot` / `market_reports` / `etf_quotes` 等）
- 消费层：Node 端 / Python 报表端**只读 PG**，禁止任何 `MCPClient` / `mcp.streamablehttp_client` 调用
- 监控：采集层 fail → cron watchdog 告警 → 不影响消费层运行（消费层读旧数据 + 显示"数据延迟"标记）
- 升级路径：未来加 "立即刷新" 功能 → 起 FastAPI sidecar 在采集层，**不**让消费层直接调 MCP

**测试用例（写进 .learnings/）：**

- 给 `mcpClient.ts`（如未来复活）加单测：mock MCP 返回错值 → 路由必须 fallback 到 PG 或报 503（**不**静默返回 0）
- 给所有读 PG 的路由加"PG-only" lint 规则：禁止 import `mcpClient` / `wudao_aStock*`

---

## 知识库（KB）

### 投研系统知识库（invest-infra） ⚠️
- **路径**: `/home/claw/invest-infra/docs/KB/`
- **结构**: `KB/backend/` · `KB/frontend/` 等，按投研系统模块分类
- **用途**: 投研系统架构文档、故障模式、API 契约
- ⚠️ **不要混淆**：这是投研系统的知识库，**不是** `~/.openclaw/kb/`

### Claude Code 工具知识库（openclaw）
- **路径**: `/home/claw/.openclaw/kb/`
- **结构**: `cc/`（CC 核心用法）· `workflow/`（工程方法论）· `archive/`（过时内容）
- **索引**: `kb/README.md` 主题映射表
- **用途**: CC 工具手册 / 防幻觉 / Router 配置 / 重构实践
- ⚠️ **CC 配置详情**（Provider/Session/Router/Skill）→ `kb/cc/config-cc.md`
- ⚠️ **llama.cpp 档案**（启动参数/性能/编译）→ `kb/infra/llama-server.md`

---

## ETF Dashboard 前端（Vite）

**本机 IP**: `192.168.6.50`

**启动命令**（从 frontend 目录）：
```bash
cd /home/claw/invest-infra/etf-dashboard/frontend
nohup npx vite --host 0.0.0.0 --port 3001 > /tmp/vite-frontend.log 2>&1 &
```

**访问**: `http://192.168.6.50:3001`（局域网）

**注意**:
- 前端是 **Vite**（非 Next.js），`package.json` 中 `dev: "vite"`
- `start.sh` 只启动 Docker 基础设施（PostgreSQL / Redis / MinIO），不包含前端
- 前端需要手动启动，或配置 PM2/systemd 持久化
- 日志：`/tmp/vite-frontend.log`

---

## 敏感信息存储

- **目录**: `secrets/`（700 权限，仅自己可读）
- **原则**: 令牌/密钥不写进任何明文 md 文件
- **Gitee 推送凭据**（v2026-06-14 修正）：**`~/.git-credentials`**（git store mode 自动 cache，600 权限）
  - **不要**用 `secrets/gitee-token`（已过时/失效）
  - **不要**手动 `GITEE_TOKEN=*** ...)`（会跳过 git store helper）
  - **正确用法**：直接 `git push -u origin main`（store helper 自动读 ~/.git-credentials）
  - **重置 cache**：`git credential-store --file=~/.git-credentials erase`，再 push 重新输
  - 旧 `secrets/gitee-token` 文件保留作 fallback（curl 调 Gitee API 验证时可能有用）
- **QQBot Browser 令牌**: `secrets/qqbot-browser-token`
- **格式**: `appId:clientSecret`（冒号分隔）
- **使用方式**: `QQBOT_TOKEN=$(cat /home/claw/.openclaw/workspace/secrets/qqbot-browser-token)`

---

## Claude Code（快速入口）

> **详细配置** → `kb/cc/config-cc.md`
> **CC 使用规范**（铁律/SOP/派单/诊断）→ `CLAUDE-CODE.md`

**启动**: `tmux attach-session -t ccr-work` → pane 里 `ccr code`

**派单**: `skills/claude-cmd/claude-cmd-simple.py`（唯一合法通信方式）

---

*最后更新：2026-06-28（CC 配置迁入 kb/cc/config-cc.md；llama 档案迁入 kb/infra/llama-server.md；多代理定时规范迁入 AGENTS.md）*
