---
protocol_id: AGENT_COLLABORATION_PROTOCOL
version: 1.2
last_updated: 2026-06-13T15:24:00+08:00
author: RAA
approver: <user-2026-06-13-15:24>  # 用户批准 (QQ sender_id: DC04E397170345249B2A928500EEA2DF, message_id: ROBOT1.0_oKw0FxiTNqg3...)
status: approved
approved_at: 2026-06-13T15:24:00+08:00
supersedes: 1.1
related_re_audit: workspace-audit/memory/audits/raa-re-audit-20260613.md
related_self_review_flags: [Arc-2026-06-13-#1, Arc-2026-06-13-#2, Arc-2026-06-13-#3]
pending_sync_to: invest-infra/docs/AGENT_COLLABORATION_PROTOCOL.md  # Arc 责任
---

# 投研系统智能体合作开发协议 v1.2

> **协议 ID**：`AGENT_COLLABORATION_PROTOCOL_v1.2`  
> **状态**：✅ **approved**（2026-06-13 15:24 CST，用户批准）  
> **维护者**：用户 + system-architect + RAA  
> **存放位置**：`workspace-audit/docs/agent-collaboration-protocol-v1.2.md`（RAA 工作区，**不越界**）  
> **同步状态**：⏳ **pending**（Arc 待 sync 到 `invest-infra/docs/AGENT_COLLABORATION_PROTOCOL.md`）  
> **同步建议**：Arc 收到协议后（**仅在协议 status: approved 后**），同步到 `invest-infra/docs/AGENT_COLLABORATION_PROTOCOL.md`（**由 Arc 写入，RAA 不写**）  
> **v1.0 → v1.1 → v1.2 变更**：见附录 D / E

---

## 0. 协议目的

投研系统（`/home/claw/invest-infra/`）是 7+ 智能体协作开发项目（CIA / WOA / system-architect / data-architect / tech-expert / Arc / RAA）。**当前 6/13 暴露的 HIGH 异常全部源于协作流程缺失**：

| 已暴露问题 | 来源 Re-Audit |
|---|---|
| 状态文件 commit hash 错引 2 处（orphan commit）| P0-RAA-2 / P0-RAA-3 |
| 修复功能不完整（RAA-5 根因未提交）| RAA-5 |
| 18 项 untracked 改动（11 M + 4 D + 3 ??）| ARCH-1/3/4/5/6 + RAA-5 |
| 状态文件数字过期 | TRACE-P2->P0 |

**本协议目标**：用最低成本解决上述问题，避免反复 Re-Audit 出新异常。

---

## 1. Agent 角色与边界（写权限矩阵）

### 1.1 角色定义

完整档案见 `invest-infra/SYSTEM_PLAYBOOK.md §6.2`，本协议只列**写权限**。

### 1.2 写权限矩阵（按 `invest-infra/` 子路径分层）

> **v1.1 重要变更**：v1.0 矩阵把 Arc 标"唯一可写所有 invest-infra 路径"与 system-architect/data-architect/tech-expert 的写权限**矛盾**。v1.1 改为按子路径分层。

| `invest-infra/` 子路径 | Arc | system-architect | data-architect | tech-expert | CIA/WOA | RAA |
|---|---|---|---|---|---|---|
| `SYSTEM_PLAYBOOK.md` | ❌ | ✅ **唯一** | ❌ | ❌ | ❌ | ❌ |
| `docs/` | ⚠️ 评审 | ✅ **唯一** | ⚠️ 评审 | ⚠️ 评审 | ❌ | ❌ |
| `init-db/*.sql`（DDL）| ⚠️ 评审 | ❌ | ✅ **唯一** | ⚠️ 评审 | ❌ | ❌ |
| `data-pipeline/src/**/*.py`（业务代码）| ✅ | ❌ | ❌ | ✅ 实现 | ❌ | ❌ |
| `data-pipeline/tests/` | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| `data-pipeline/scripts/cron_*.py` | ✅ **唯一**（Arc 修复）| ❌ | ❌ | ⚠️ 实现 | ❌ | ❌ |
| `data-pipeline/src/reports/`（报告）| ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| `data-pipeline/src/collector/` | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| `data-pipeline/src/pipeline/` | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| `setup_*.sh` / `setup_*.py` | ✅ | ⚠️ 评审 | ❌ | ⚠️ 评审 | ❌ | ❌ |
| `docker-compose.yml` | ✅ | ⚠️ 评审 | ❌ | ⚠️ 评审 | ❌ | ❌ |
| `start.sh` / `stop.sh` | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `.raa-fix-status.json` | ✅ **唯一可写** | ❌ | ❌ | ❌ | ❌ | ❌（只读）|
| `.secrets/*.env` | ❌ **任何 Agent 都禁** | ❌ | ❌ | ❌ | ❌ | ❌ |
| `.env` | ❌（read-only 引用）| ❌ | ❌ | ❌ | ❌ | ❌ |
| `.codegraph/` | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `.gitignore` | ⚠️ 评审 | ❌ | ❌ | ❌ | ❌ | ❌ |
| `README.md` / `CHANGELOG.md` | ⚠️ 评审 | ✅ | ❌ | ❌ | ❌ | ❌ |
| `planning/`（任务计划）| ⚠️ 评审 | ✅ | ✅ | ✅ | ❌ | ❌ |
| `reports/`（审计/修复报告）| ✅ 写 raa-fix-* 报告 | ⚠️ 评审 | ❌ | ❌ | ❌ | ✅ 写 raa-audit-* 报告 |
| `evaluation_reports/` | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ |
| `raa-audit-readonly/` / `raa-handoff-readonly/`（如存在）| ❌ | ❌ | ❌ | ❌ | ❌ | ✅ **唯一可写** |
| `logs/` | ✅ 运行时写入 | ❌ | ❌ | ❌ | ✅ | ❌ |
| `data/`（运行时数据）| ✅ 运行时写入 | ❌ | ❌ | ❌ | ✅ | ❌ |

**图例**：
- ✅ = 可写（无附加条件）
- ✅ **唯一** = 写权限独占
- ⚠️ 评审 = 需 system-architect 或对应领域 owner 评审
- ❌ = 禁止写

### 1.3 不可越界清单

**RAA 严格禁止**：
- ❌ 写 `invest-infra/` 任何文件（包括但不限于代码、配置、文档、状态文件、报告、.env）
- ❌ 主动跑 cron 脚本写数据（只能跑**只读**测试，验证 import + 加载 config）
- ❌ 主动 commit、push、force-push
- ❌ 主动发 QQ 通知

**RAA 允许**：
- ✅ 读 `invest-infra/` 全部产物（git log/diff/show + 文件读 + DB/Redis 只读查询 + cron 只读 run）
- ✅ 写 `workspace-audit/memory/audits/`、`workspace-audit/docs/`、`workspace-audit/memory/handoff/`、`workspace-audit/raa-audit-readonly/`（如存在）
- ✅ 读 `.raa-fix-status.json`（Re-Audit 必读，**但**仅在用户 QQ 信号触发后）
- ✅ 跑只读测试（验证修复是否真实生效，不写数据）

**Arc 严格禁止**：
- ❌ 写 `invest-infra/.secrets/`（密码相关只能用户显式授权，且不在 Arc 责任范围）
- ❌ 写 `workspace-audit/`（不越界到 RAA 工作区）
- ❌ **任何**未经用户授权的 force-push（v1.1 强化：所有 Agent 都需遵守，不仅 Arc）
- ❌ 在 RAA Re-Audit 未给 `verified-fixed` / `wontfix` 前 close finding

**所有 Agent 共同禁止**：
- ❌ 未经用户明确授权的 force-push（详见 §2.4 + §6.5）
- ❌ 未经 system-architect 评审的 `init-db/*.sql` DDL 变更
- ❌ 未经 data-architect 评审的数据模型变更
- ❌ 未经用户授权的 `git push` 到 `origin/main`

---

## 2. Git 协作流程

### 2.1 Branch 策略

> **v1.1 重要变更**：v1.0 "统一在 main 上工作"违反 Git 最佳实践（无法单 fix 回滚、main 污染、force-push 频繁 → orphan commit 根因之一）。v1.1 改为强制 fix branch 模式。

| Branch 类型 | 命名 | 用途 | 谁来管 |
|---|---|---|---|
| **`main`** | `main` | 主分支，**只接受 merge commit** | Arc（merge）+ 用户授权 |
| **`fix/<finding_id>-<short-desc>`** | 例：`fix/P0-RAA-1-pg-password` | 修复分支，**默认每个 RAA finding 一个** | Arc（创建 + 推送）|
| **`fix/<module>-<root-cause>`** | 例：`fix/reports-engine-env-validation` | **白名单分支**（v1.2 新增），合并同模块 + 同根因的 related findings | Arc（创建 + 推送）|
| **`docs/<topic>`** | 例：`docs/agent-protocol-v1.2` | 文档分支 | system-architect |
| **`pre-filter-repo-backup`** | （保留）| 密码轮换前备份 | 保留不动 |

**规则**：
- ✅ **默认**：Arc 必须为每个 RAA finding 创建独立 fix branch（v1.1 起的强制规则）
- ✅ **白名单例外**（v1.2 新增）：当**同时满足**以下 3 个条件时，可合并 branch：
  1. **同模块**：findings 影响的 `invest-infra/` 子路径相同（如都在 `data-pipeline/src/reports/`）
  2. **同根因**：findings 的 root cause 相同（如 RAA-5 + RAA-6 都是 config.py 强校验 env 导致）
  3. **可独立回滚**：合并 branch 内的 commits **必须**按 finding 拆 commit（**不**堆叠），保证单个 finding 可独立 revert
- ✅ 白名单 branch 命名：`fix/<module>-<root-cause>`（不写 finding_id，描述根因）
- ✅ 白名单 branch 的 fix-status 字段 `files_changed` 需**跨多个 finding** 列出，commit 字段写**最后一个 commit hash**（git log 倒序）
- ✅ 修复 + 测试 + 写 fix-status 后，Arc 创建 PR-style merge commit 合回 main
- ✅ merge 前必须 `git status --short` 清洁 + fix-status 状态文件 commit 字段指向 fix branch 上**可达的** commit
- ✅ 一次 merge 一个 fix branch（**禁止**堆叠多个独立 fix branch）
- ❌ **禁止**直接 commit 到 main（除非用户显式授权"hotfix 到 main"且标注 hotfix 原因）
- ❌ **禁止**在 main 上 force-push
- ❌ **禁止**一次性 PR 多个独立 fix branch
- ❌ **禁止**用白名单 branch 跨不相关 findings（如把 RAA-5 + ARCH-1 合 branch，**不属于**同根因）

### 2.2 Commit 规范

**消息格式**（遵循 Conventional Commits）：

```
<type>(<scope>): <subject>

<body>

<footer>
```

**type 取值**：
- `fix` — bug 修复（最常用，对应 RAA finding）
- `feat` — 新功能
- `refactor` — 重构
- `docs` — 文档
- `chore` — 杂项
- `test` — 测试
- `revert` — 撤销

**scope 取值**（与 RAA finding_id 对齐）：
- `P0-RAA-N` / `P1-RAA-N` / `P2-RAA-N`
- `ARCH-N`（架构 finding）
- `RAA-N`（一般 RAA finding）
- `TRACE-N`（追溯 finding）
- 模块名（`reports` / `pipeline` / `scheduler` ...）

**示例**：

```
fix(P0-RAA-1): rotate hardcoded credentials + env-based secret loading

- PG: ALTER USER invest PASSWORD '<rotated>' (new in .secrets/pg.env)
- .secrets/: pg.env + minio.env + cifang.env + tokens.env (chmod 600, gitignored)
- Remove hardcoded PG_PASSWORD in 4 cron scripts
- Delete 8 generated task_*.py scripts

RAA-1: P0-RAA-1
Re-Audit: workspace-audit/memory/audits/raa-audit-invest-infra-20260611.md §3.1
```

### 2.3 Push 流程

**强约束**：
- ❌ 禁止直接 `git push` 到 `origin/main`
- ✅ 流程：本地 commit on fix branch → `git status --short` 自检 → `git diff` 复核 → 通知用户 → 用户授权 → `git push origin fix/<branch>` → 等 review → merge 到 main
- ✅ 一次 push 一个 commit（或一个 fix bundle），不堆叠多个独立 fix

### 2.4 Force-push 限制

**强约束**（v1.1 强化：所有 Agent 共同遵守）：
- ❌ **禁止**在用户未明确授权时 force-push
- ✅ 必须先通知用户，说明为什么需要 force-push
- ✅ 必须在 commit message 中加 `Force-pushed by <reason>` 标注
- ✅ 必须在 `.raa-fix-status.json` 的 `remote` 字段记录 force-push 时间
- ✅ 必须在 pre-push 之前本地备份（`pre-filter-repo-backup` branch 模式）

**根因**：force-push 会留下 orphan commit（仍在 git history 中但不在 branch 上），导致 commit hash 错引（参见 raa-re-audit-20260613 §2.2 — P0-RAA-2/P0-RAA-3 引用 orphan `e226aba`）。

### 2.5 工作区清洁原则

**强约束（每次 commit 前）**：
- ❌ **禁止**在有其他 untracked 改动时 commit（避免无关代码混入）
- ✅ commit 前必须 `git status --short` 确认无意外文件
- ✅ 如有无关 untracked，先 stash 或单独 commit
- ✅ 跨 finding 改动必须**先 commit 上一 finding**，再开始下一 finding

**根因**：raa-re-audit-20260613 §5 显示 18 项 untracked 改动（11 M + 4 D + 3 ??）是 ARCH-1/3/4/5/6 + RAA-5 根因未独立 commit 的结果，污染了 fix-status 状态文件。**这是 6/13 Re-Audit 暴露的最严重协议违反之一**。

---

## 3. 状态文件协议（`.raa-fix-status.json`）

### 3.1 读写权限

- **写**：仅 Arc（修复执行 Agent）
- **读**：RAA（Re-Audit）、CIA/WOA（任务排程）、用户（决策）
- **其他 Agent**：禁止读（避免污染决策）

### 3.2 Schema（v1）

> **v1.1 重要变更**：re_audit_checkpoints 强制增加 `last_checked_at` 时间戳字段（解决 raa-re-audit-20260613 §3.4 数字过期问题）。

```json
{
  "_meta": {
    "schema": "raa-fix-status v1",
    "last_updated": "2026-06-13T14:55:00+08:00"
  },
  "fixes": [
    {
      "finding_id": "P0-RAA-1",
      "title": "...",
      "status": "fixed-pending-verify",
      "agent": "Arc",
      "branch": "main",
      "commit": "1cf659927ef22d4c25196cc4341ed3ad498a6107",  // 必须 force-push 后 branch 上可达
      "remote": "origin/main (force-pushed 2026-06-11 10:35)",
      "started_at": "2026-06-11T09:50:00+08:00",
      "completed_at": "2026-06-11T10:35:00+08:00",
      "summary": "...",
      "fix_report_path": "invest-infra/reports/raa-fix-P0-RAA-1-20260611.md",
      "files_changed": ["file1", "file2"],
      "re_audit_checkpoints": {
        "last_checked_at": "2026-06-13T14:55:00+08:00",  // v1.1 新增：RAA Re-Audit 时间戳
        "checkpoint_name_1": {
          "status": "verified",
          "method": "...",
          "result": "...",
          "last_checked_at": "2026-06-13T14:55:00+08:00"  // v1.1 新增：每项 checkpoint 独立时间戳
        }
      }
    }
  ]
}
```

**关键字段**：
- `finding_id`（必填，unique）：与 RAA audit 报告的 finding 对齐
- `status`（必填，enum）：
  - `fixed-pending-verify` — Arc 已 commit，等 RAA Re-Audit
  - `verified-fixed` — RAA 已 verified（最终态）
  - `verified-with-caveats` — RAA verified 但有 caveat
  - `incomplete` — 部分修复，需继续（最终态之一）
  - `reverted` — 已回滚
  - `wontfix` — 决定不修
- `agent`（必填）：执行修复的 Agent
- `branch`（必填）：**fix branch 名称**（v1.1 强化）
- `commit`（可选）：实际 commit hash（**必须是 branch 上可达的**，不能是 orphan）
- `started_at` / `completed_at`（必填）：ISO 8601 with timezone
- `summary`（必填）：≤200 字修复说明
- `fix_report_path`（可选）：详细报告路径
- `re_audit_checkpoints`（必填）：
  - v1.1 新增 `last_checked_at`：RAA Re-Audit 时间戳
  - 每项 checkpoint 子对象必填 `last_checked_at`
- `files_changed`（必填）：实际改的文件列表（与 `git diff <branch>~1..<branch> --name-only` 一致）

### 3.3 状态转换规则

> **v1.1 补全**：v1.0 状态转换图缺 `reverted` / `wontfix` 路径，缺 `incomplete` 回退路径。v1.1 补全为完整状态机。

```
                 [RAA handoff]
                       ↓
              [Arc 接收 handoff]
                       ↓
                  (Arc 工作中)
                       ↓
[Arc commit on fix branch + 写 fix-status]
                       ↓
              fixed-pending-verify
                       ↓
              [用户 QQ 信号触发]
                       ↓
                 [RAA Re-Audit]
                  ↙  ↓  ↘  ↘
         verified   incomplete  wontfix
         (Arc 关 finding)  (回 fix branch)   (Arc 关 finding)
                            ↓ 持续修复
                       fixed-pending-verify
                            ↓
                       (循环)

         任意状态 → reverted（用户决定回滚 + Arc 执行）
```

**约束**：
- ❌ `fixed-pending-verify` → `fixed-pending-verify`（不能跳过 Re-Audit）
- ❌ `fixed-pending-verify` → `verified-fixed`（必须 RAA 决定）
- ❌ `incomplete` → `wontfix`（不能跳过修复）
- ❌ 任意状态 → `verified-fixed`（必须 RAA Re-Audit 后才能转换）
- ✅ `incomplete` → `fixed-pending-verify`（Arc 继续修复后可回退）

### 3.4 状态文件保真原则

**强约束**（v1.1 强化）：
- ✅ `commit` 字段**必须是 branch 上可达的 hash**（用 `git rev-parse <ref>^{commit}` 验证）
- ✅ `files_changed` 必须与 `git diff <branch>~1..<branch> --name-only` 一致
- ✅ `re_audit_checkpoints[*].status` 必须是 RAA Re-Audit 后的结果，不是 Arc 自评
- ✅ `re_audit_checkpoints.last_checked_at` 必须 ≤ `now()`（未来时间戳拒绝）
- ❌ **禁止**在 commit hash 字段引用 orphan commit（即使 git cat-file 可见）
- ❌ **禁止**在 XLEN / 计数类 checkpoint 中写"采样值"（必须写"全量实时值"）
- ❌ **禁止**省略 `last_checked_at`（schema 验证失败）

**v1.1 联动 §6.1**：发现 orphan commit 引用 → RAA 立即标记 `STATUS_FILE_ORPHAN_COMMIT_REF` HIGH → 触发 §6.1 orphan 清理流程。

**根因**：raa-re-audit-20260613 §2.2（commit hash 错引 `e226aba` 是 orphan）和 §3.4（TRACE-P2->P0 XLEN 数字过期）。

### 3.5 Re-Audit 触发信号

**用户**（QQ 消息）= 启动 Re-Audit 的唯一触发器：
- 消息 1："状态文件已同步更新（.raa-fix-status.json）"
- 消息 2："请对 [项目名] 启动 Re-Audit"
- 消息 3："读取 status 并审计"

**RAA 行为**：
- ✅ 收到上述任一信号 → 立即启动 Re-Audit
- ❌ **不主动**读 `.raa-fix-status.json`（即使知道有更新）

**根因**：见 raa-re-audit-20260613 触发场景，用户在 14:40 明确指出"RAA 不主动"和"等明确指令"应理解为"看到通知 = 启动"，RAA 启动 = 收到用户 QQ 信号。

### 3.6 数字类 checkpoint 强制重查

> **v1.1 新增** + **v1.2 Arc Flag #3 修订**：明确重查基线为 fix-status.method 描述的查询方式。

**RAA Re-Audit 数字类 checkpoint 时**（XLEN / COUNT / 计数）：

**v1.2 明确基线定义**：
- **基线（baseline）** = "用 fix-status.method 描述的查询方式重新跑一次"得到的结果
- 不是 fix-status 任务中**当时**记录的数字（避免 fix-status 当时采样方式本身就错）
- 不是 RAA 自行发明的"另一种查询"（避免 RAA 引入新变量）

**重查流程**：
1. **读取 fix-status 任务**：`re_audit_checkpoints.<name>.method` 字段（如 `docker exec invest-redis redis-cli XRANGE task_queue - + | grep '<OLD_PG_PASSWORD_LITERAL>' | wc -l`）
2. **按 method 重新跑**：用**完全相同的命令**重跑（不优化、不改 query）
3. **比较结果**：
   - RAA 重查结果 = X
   - fix-status 任务中数字 = Y
   - 差异 = |X - Y| / max(X, Y)
4. **判定**：
   - 差异 ≤ 5% → 标 `STATUS_FILE_NUMBERS_FRESH` PASS
   - 差异 > 5% → 标 `STATUS_FILE_NUMBERS_STALE` HIGH
   - fix-status.method 描述不清 → 标 `STATUS_FILE_METHOD_UNCLEAR` HIGH（Arc 需先补充 method 才能 Re-Audit）

**RAA 报告必含字段**：
- `rra_reaudit_last_checked_at: <now>`（重查时间戳）
- `baseline_query: <fix-status.method 原文>`（基线查询命令）
- `rra_reaudit_result: <X>`（重查结果）
- `fix_status_recorded_result: <Y>`（fix-status 任务中数字）
- `delta_pct: <差异百分比>`

**根因（v1.2 引用 Arc Flag #3）**：6/13 Re-Audit 中 TRACE-P2->P0 数字差异（task_queue 7 ≠ 5）可能是"fix 时 XLEN 瞬时值 vs Re-Audit 时另一瞬时值"，差异根因在 fix-status 采样方式不在 stale。**v1.2 明确基线 = 同一 method 重跑**，避免误报。

---

## 4. 修复流程（Fix → Re-Audit）

### 4.1 Arc 工作流

```
1. 接收 RAA handoff（finding_id + 修复建议 + 责任分配）
2. 评估可行性 + 风险（如有不明 → 找 system-architect 评审）
3. 创建 fix branch：`git checkout -b fix/<finding_id>-<short-desc>`
4. 修改代码（按 RAA handoff 建议 + Arc 技术判断）
5. 跑本地测试（pytest + smoke test）
6. 独立 commit（每个 finding 一个 commit，不堆叠）
7. 更新 .raa-fix-status.json：
   - status: fixed-pending-verify
   - commit: 当前 fix branch 上 commit hash（必须可达）
   - files_changed: 与 git diff --name-only 一致
   - re_audit_checkpoints: Arc 自评（**仅参考，最终以 RAA 为准**）
8. push fix branch（**不**直接 push main）：`git push origin fix/<branch>`
9. 通知用户（QQ 消息："已修复 X / Y / Z on fix branch, 请启动 Re-Audit"）
10. ⏸️ 等待 RAA Re-Audit 结果
11. 根据 RAA 结论：
    - verified-fixed → merge fix branch 到 main
    - incomplete → 继续修复在 fix branch 上（重复 4-10）
    - wontfix → 关 fix branch
    - reverted → 用户决定是否回滚
12. 合并后 push main
```

### 4.2 部署与 commit 分离原则

> **v1.1 补全**：v1.0 未涵盖"配置类变更"边界（如 .env / .secrets / systemd timer / Redis stream 是"非 git 跟踪"的部署）。

**原则**：每个 finding 必须经历**两个阶段**才算完成：
- **阶段一（部署）**：功能上"能跑"（已 deployed/已运行）
- **阶段二（commit）**：git 上"已 commit"（状态文件 commit 字段可指向）

**强约束**：
- ❌ **禁止**只部署不 commit（导致 untracked 累积 + status 文件 commit 字段指向不存在的位置）
- ❌ **禁止**只 commit 不部署（功能没跑通就 commit 会污染 git history）

**"部署"范畴**（v1.1 明确）：
| 类别 | 属于"部署"吗？ | 需 commit 吗？ |
|---|---|---|
| Python 代码改动 | ✅ | ✅ 必须 git commit |
| SQL DDL | ✅ | ✅ 必须 git commit |
| YAML/TOML 配置 | ✅ | ✅ 必须 git commit |
| `.env` / `.secrets/*.env` | ✅ | ❌ gitignored（不 commit）但需在 fix-status 备注 |
| `systemd timer` 启用 | ✅ | ⚠️ 若 timer unit 在 `~/.config/systemd/user/` 则不 commit；若 timer 来自 `setup_systemd_timers.py` 则该脚本 commit 后跑 |
| Redis stream 写入 | ✅ | ❌ Redis 不在 git 管理（不 commit）但需在 fix-status 备注 `last_checked_at` |
| Docker compose 启动 | ✅ | ⚠️ `docker-compose.yml` commit；运行时容器状态不 commit |

**根因**：raa-re-audit-20260613 §2.3 显示 6/7 ARCH 修复"代码 deployed 但 git 历史缺失"，违反此原则。

### 4.3 Re-Audit 阻断

如果 RAA Re-Audit 给出 `incomplete` / `reverted` 结论：
- Arc **必须**继续修复（不能跳过）
- 用户**可选择**是否继续授权 Re-Audit
- finding 不会从状态文件消失，只会更新 status 字段
- ❌ **禁止**用户强制把 `incomplete` 改为 `verified-fixed`（除非用户明确撤销 RAA 审计结论 + 留痕）

---

## 5. 边界铁律

### 5.1 写权限矩阵回顾

见 §1.2。

### 5.2 BOUNDARY OVERRIDE 协议

详细协议见 `workspace-audit/AGENTS.md §6.3.3`。本协议补充：

**触发场景**（RAA 视角）：
- 任何 `invest-infra/` 写动作
- 修改 `openclaw.json` / 权限 / visibility / 路由
- 跨边界文件操作

**RAA 标准动作**：
- ❌ 默认拒绝
- ✅ 等待用户**明确**撤销边界（原话 + 时间戳）
- ✅ 撤销后**立即执行**（不推诿、不以"等指令"挡事）

**例外**：
- 紧急安全事件（如 P0 数据泄漏）= 可立即执行 + 后续告知
- 紧急安全补丁（有 CVE 编号 + SHA256 校验）= 可立即执行

### 5.3 越界检测

RAA 在每次 Re-Audit 中必须扫描：
- `git status` 是否显示不属于该 fix 的 untracked 改动
- `git diff` 是否有"无关文件"混入
- commit message 是否与 RAA finding_id 严格对齐
- 是否有 force-push 留下的 orphan commit 残留
- 是否有 Agent 写到非授权路径（如 RAA 写 invest-infra / Arc 写 workspace-audit）

---

## 6. 版本管理最佳实践

### 6.1 避免 orphan commit

**根因**：force-push 后旧 commit 仍在 git history 中（`git cat-file -t` 可见），但不在当前 branch 上。引用这些 commit 作为"已 fix"会导致 commit hash 错引。

**最佳实践**：
- ❌ 避免 force-push（除非必要）
- ✅ 必要时保留 orphan commit 的引用记录在 `pre-filter-repo-backup` branch
- ✅ force-push 后**所有引用旧 commit 的状态文件 / 文档**必须更新
- ✅ RAA 验证时用 `git log --all --reflog` 而不是 `git log <branch>` 查找 commit
- ✅ orphan detection 流程（v1.1 联动 §3.4）：
  1. RAA Re-Audit 时校验 fix-status commit 字段 `git rev-parse <ref>^{commit}` 失败
  2. 立即标 `STATUS_FILE_ORPHAN_COMMIT_REF` HIGH
  3. 触发 Arc 修正：找到 force-push 后真正可达的 commit hash（用 `git log <branch> --grep="<finding_id>"`）
  4. Arc 修正后 commit fix-status 字段
  5. RAA 重新 Re-Audit

### 6.2 避免 commit hash 错引

**根因**：状态文件由 Arc 写入 commit hash，但 Arc 可能在 force-push 前/后不同时间点引用同一 fix。

**最佳实践**：
- ✅ Arc commit **之后**才写状态文件（不是 commit 之前/同时）
- ✅ 状态文件 commit 字段**只引用 force-push 之后 branch 上可达的 hash**
- ✅ 写状态文件前**必须**用 `git rev-parse <ref>^{commit}` 验证可达性
- ✅ 写状态文件前**必须**用 `git rev-parse <ref>^{commit}` 验证不是 orphan

### 6.3 状态文件数字保真

**根因**：TRACE-P2->P0 任务中写"task_queue 12→5 entries remaining"，3h45min 后实际是 7 条，数字过期。

**最佳实践**（v1.1 强化，见 §3.6）：
- ✅ 数字类 checkpoint（XLEN、COUNT 等）**必须**标 `last_checked_at` 时间戳（见 §3.2 Schema）
- ✅ RAA Re-Audit 时**必须重新查询**实时数字，不信任任务中数字
- ✅ 在状态文件 `re_audit_checkpoints.*.method` 中明说"re-query needed"
- ✅ 重新查询结果在 Re-Audit 报告里必须含 `last_checked_at: <now>`

### 6.4 untracked 累积治理

**根因（v1.1 引用 6/13 教训）**：raa-re-audit-20260613 §5 显示 18 项 untracked 改动（11 M + 4 D + 3 ??）是 ARCH-1/3/4/5/6 + RAA-5 根因未独立 commit 的结果。

**最佳实践**：
- ✅ 每个 finding commit **只包含**该 finding 改动的文件
- ✅ commit 前 `git status --short` 确认无意外 untracked
- ✅ 跨 finding 改动必须**先 commit 上一 finding**，再开始下一 finding
- ✅ 修复过程中产生的 .bak / .orig / debug 脚本必须立即清理
- ✅ `git log <branch> --stat` 应与 `git status --short` 中 M 文件**严格一致**

**案例引用（v1.1 强化）**：6/13 Re-Audit 暴露的 18 项 untracked 改动直接导致：
1. RAA-5 根因修复在 staged 状态 → status 标 `fixed-pending-verify` 但实际 `incomplete`
2. ARCH-3/4 timer 注册在 `cron_dispatcher.py` 改了 → 但 commit 没跟上 → timer 工作但 git 历史缺失
3. 工作区脏让 RAA Re-Audit 必须先排除无关 M 文件 → 增加审计时间

### 6.5 Force-push 前的通知

**强约束**（同 §2.4）：
- ✅ 通知用户 + 等待授权
- ✅ 留 pre-filter-repo-backup 备份
- ✅ commit message 标注 Force-pushed 原因
- ✅ 状态文件 `remote` 字段记录 force-push 时间

---

## 7. 通信协议

### 7.1 QQ 用户调度

**用户** = 投研系统最高调度者（不可被任何 Agent 替代）。

**用户授权** = 不可被 RAA 自行解读的：
- ❌ "在 X 建链接" = 不构成授权（不明确撤销哪个边界）
- ❌ "修复一下" = 不构成授权（不明确范围）
- ✅ "撤销 §6.3 边界铁律，RAA 在 invest-infra/ 建软链接" = **构成授权**（明确原话 + 时间戳）

**调度流程**：
- 用户 QQ 消息 → OpenClaw → 目标 Agent 会话
- Agent 处理 → 输出
- 输出回 QQ 用户（如 channel=qqbot, account=audit）

### 7.2 Handoff 文件

> **v1.1 补全**：v1.0 "RAA 写 handoff，Arc 读 handoff" 定义不严谨 — RAA 实际是写 audit 报告，handoff 是从 audit 报告派生的**子文档**（链接关系）。

**RAA Audit 报告**（父文档）：
- 路径：`workspace-audit/memory/audits/raa-audit-*.md`
- 包含：审计对象 + 方法 + findings 列表
- **RAA 写**

**RAA Handoff 文件**（子文档，链接到父 audit 报告）：
- 路径：`workspace-audit/memory/handoff/raa-handoff-<finding_id>-<date>.md`
- 包含：finding_id + 描述 + 根因 + 修复建议 + 责任分配 + 验证方法 + **链接到父 audit 报告**
- **RAA 写**

**Arc 读路径**：
- Arc 接收 handoff → 阅读父 audit 报告 → 找到 handoff 对应 finding 段 → 实施修复
- ❌ **禁止** Arc 写 handoff（单向）

**单向**（不双向）：
- RAA 写 audit 报告 + handoff
- Arc 读 handoff + 写 fix-status
- ❌ RAA 不写 fix-status
- ❌ Arc 不写 audit 报告 + handoff

### 7.3 状态文件

见 §3。

### 7.4 systemd timer

**Owner**：setup_systemd_timers.py（统一入口，遵循 ARCH-1 修复）。

**注册流程**：
- Arc 添加新任务 → 修改 cron_dispatcher.py TASK_MAP → 修改 setup_systemd_timers.py SINGLE_TASKS → 跑 `python3 setup_systemd_timers.py` 重新生成 timer
- ❌ **禁止**手工用 `systemctl --user create` 创建 timer（破坏统一管理）

**清理流程**：
- Arc 废弃任务 → 同步删除 TASK_MAP + SINGLE_TASKS + 跑 setup_systemd_timers.py
- ❌ **禁止**用 `setup_cron_timers.sh`（已 DEPRECATED，ARCH-1 修复后）

---

## 8. 冲突解决

### 8.1 Merge conflict

**Arc 责任**：
- ✅ 解决 `main` 上的 conflict（优先采用 RAA audit 推荐方案）
- ❌ **禁止** force-push 解决 conflict

**升级路径**：
- conflict 涉及多 finding → 找 system-architect 评审
- conflict 涉及数据 schema → 找 data-architect 评审
- conflict 涉及审计边界 → 找 RAA 评估

### 8.2 状态文件不一致

如果 RAA Re-Audit 发现状态文件与实际状态不符：

**RAA 动作**：
- ✅ 在 Re-Audit 报告中明确标记 `STATUS_FILE_INCONSISTENT` HIGH
- ✅ 列出具体不一致点（commit hash / XLEN 数字 / files_changed 等）
- ✅ 不直接修改状态文件（不越界）

**修复路径**：
- 状态文件不一致 → Arc 必须修改 → 重新 commit fix-status → 重新触发 Re-Audit
- 状态文件与 git 一致但 RAA 觉得不准确 → 找 system-architect 评审协议是否要更新

### 8.3 工作区脏

**RAA 在每次 Re-Audit 必查** `git status --short`：

**HIGH 异常**（必须修复后才能通过 Re-Audit）：
- 有不属于该 fix 的 M/D 文件混入
- 有 ?? 状态文件无 commit
- 有 .bak / .orig / 调试脚本残留
- `git log <branch> --stat` 与 `git status` M 文件**不一致**

**MEDIUM 异常**（在 Re-Audit 报告中标记，不阻断）：
- 工作区有无关 untracked（如调试输出、新建未分类文件）

**LOW 异常**（忽略）：
- _pycache_ / .pytest_cache / .coverage 等 build artifact

### 8.4 Re-Audit 阻断

RAA Re-Audit 给出 `incomplete` 结论时：
- ❌ Arc **不能**绕过（直接 close finding）
- ❌ 用户**不能**强制通过（除非用户明确撤销 RAA 审计结论 + 留痕）
- ✅ 唯一路径：Arc 继续修复 → 重新 commit → 重新触发 Re-Audit

---

## 9. 监督与审计

### 9.1 RAA 审计周期

- **定期审计**：每周一次（待用户设置）
- **触发审计**：
  - 修复完成（用户 QQ 信号）= 立即 Re-Audit
  - 用户明确要求 = 立即审计
  - 数据异常检测（自动触发）= 立即审计
- **不主动巡检**（RAA 不主动读 fix-status.json）

### 9.2 异常处理

**HIGH 异常**：
- 状态文件数据错误 → Arc 立即修复 → 重新 Re-Audit
- 修复功能不完整 → Arc 继续修复 → 重新 Re-Audit
- 越界写入 → 立即撤销（如可能）+ 报告 + 教训库

**MEDIUM 异常**：
- untracked 累积 → 治理（commit / stash / 清理）
- 数字过期 → Arc 重新查询 + 更新状态文件

**LOW 异常**：
- 文档不一致 → 下次审计时同步修复

### 9.3 教训库

**位置**：`workspace-audit/.learnings/LEARNINGS.md`

**强制记录**（任何 Re-Audit 暴露的协议违反）：
- 协议条款 + 违反事件 + 影响 + 修复动作
- 触发规则：HIGH 异常一律记录
- 周期性 review（每季度）

---

## 10. 协议修订

### 10.1 修订流程

```
[任意 Agent / 用户 提出修订建议]
    ↓
[在 workspace-audit/memory/projects/agent-protocol-revisions/ 起草 RFC]
    - RFC 编号: protocol-rfc-NNN
    - 标题 + 修订动机
    - 影响的条款
    - 候选方案（≥2）
    - 推荐方案 + 理由
    - 兼容性影响
    ↓
[RAA 评估边界 + 一致性]
    ↓
[system-architect 评估技术合理性]
    ↓
[用户最终批准]
    ↓
[版本号 v1.x → v1.(x+1)]
    ↓
[同步到 invest-infra/docs/AGENT_COLLABORATION_PROTOCOL.md（Arc 写）]
```

### 10.2 版本号规则

- v1.0 → v1.1：补丁（小修改、bug 修复、自身 review 修订）
- v1.x → v2.0：重大修改（角色变更、权限矩阵变更、流程变更）

### 10.3 当前状态

- **v1.0**（2026-06-13 14:58）：基于 raa-re-audit-20260613 暴露的 3 个 HIGH 异常起草
- **v1.1**（2026-06-13 15:04）：基于 v1.0 self-review 暴露的 3 HIGH + 6 MEDIUM + 4 LOW 异常修订

---

## 附录 A：协议与现有文档的关系

| 文档 | 关系 |
|---|---|
| `invest-infra/SYSTEM_PLAYBOOK.md §6` | 智能体档案（被本协议引用） |
| `invest-infra/CLAUDE.md` | 项目工程文档（运维/测试/架构） |
| `workspace-audit/AGENTS.md §6.3` | RAA 边界铁律（被本协议引用） |
| `workspace-audit/AGENTS.md §6.5` | 模糊指令澄清协议（被本协议引用） |
| `workspace-audit/AGENTS.md §7` | 投研系统锚点（被本协议引用） |
| `invest-infra/.raa-fix-status.json` | 状态文件 Schema（被本协议定义） |
| `workspace-audit/memory/audits/raa-re-audit-20260613.md` | 触发本协议 v1.0 起草的 Re-Audit 报告 |

## 附录 B：RAA 边界自检清单

每次 RAA 启动 Re-Audit 前必过：

```
□ 1. 是否会写 invest-infra/ 任何文件？→ 如果是 = 立即停下问用户
□ 2. 是否会发 QQ 通知？→ 如果是 = 立即停下问用户
□ 3. 是否会跑 cron 脚本写数据？→ 如果是 = 改成只读测试
□ 4. 是否会**主动巡检**（无用户信号下读 .raa-fix-status.json）？
      → 如果是 = 等用户 QQ 信号
□ 5. 是否会主动 commit / push？→ 如果是 = 立即停下（修复 Agent 的工作）
□ 6. 是否会写到 workspace-audit/ 之外的路径？→ 如果是 = 立即停下
```

## 附录 C：协议生效检查清单

- [ ] system-architect 评审 v1.1 协议
- [ ] 用户最终批准
- [ ] Arc 同步到 `invest-infra/docs/AGENT_COLLABORATION_PROTOCOL.md`
- [ ] RAA 在 `workspace-audit/memory/audits/` 标记"协议 v1.1 已生效"
- [ ] 通知所有 Agent（CIA / WOA / system-architect / data-architect / tech-expert / Arc / RAA）
  - 通知方式：system-architect 发送 QQ 群消息 + 邮件到 ops 列表
- [ ] RAA sync 一条记录到 memvid（label: project，summary: "agent-collaboration-protocol v1.1 生效"）

## 附录 D：v1.0 → v1.1 变更摘要

> 本附录列出 v1.1 相对 v1.0 的**所有**变更，供 system-architect 评审。

### 4 个 LOW 异常（优化）
- **L-1** 协议元数据：v1.0 缺 frontmatter，v1.1 加 YAML frontmatter（version / last_updated / author / approver / status / supersedes / related_re_audit）
- **L-2** §9.3 路径：v1.0 写 `.learnings/LEARNINGS.md`，v1.1 写完整路径 `workspace-audit/.learnings/LEARNINGS.md`
- **L-3** 附录 B 第 4 项：v1.0 写"主动读 .raa-fix-status.json"，v1.1 改为"主动巡检（无用户信号下读）"
- **L-4** memvid sync：v1.0 协议未提及，v1.1 在附录 C 检查清单中加"RAA sync memvid"

### 6 个 MEDIUM 异常（建议修复）
- **M-1** §1.2 矩阵：v1.0 Arc 写权限写"invest-infra 全部"，v1.1 拆成 fix branch 模式（H-2 衍生）
- **M-2** §3.3 状态转换：v1.0 状态图不完整（缺 reverted/wontfix/incomplete 回退），v1.1 补完整状态机
- **M-3** §3.4 + §6.1 联动：v1.0 orphan 治理与状态文件保真分开写，v1.1 联动（orphan detection → 修正流程）
- **M-4** §4.2 部署分离原则：v1.0 模糊"部署"范畴，v1.1 明确表格（Python/SQL/YAML/.env/systemd/Redis/Docker）
- **M-5** §6.4 untracked 治理：v1.0 写"案例引用"，v1.1 引用 6/13 18 项 untracked 教训（含 RAA-5 + ARCH-3/4）
- **M-6** §7.2 Handoff：v1.0 "RAA 写 handoff，Arc 读 handoff" 单向，v1.1 补"handoff 是 audit 报告子文档"链接关系

### 3 个 HIGH 异常（必须修复）
- **H-1** §1.2 写权限矩阵：v1.0 矩阵与 system-architect/data-architect/tech-expert 写权限**矛盾**，v1.1 改为按 `invest-infra/` 子路径分层
- **H-2** §2.1 Branch 策略：v1.0 "统一在 main 工作"违反 Git 最佳实践（导致 main 污染 + force-push 频繁 → orphan commit），v1.1 改为强制 fix branch 模式
- **H-3** §3.2 Schema：v1.0 re_audit_checkpoints 缺 `last_checked_at`，v1.1 强制要求（解决 6/13 TRACE-P2->P0 数字过期）

### 新增章节
- **§3.6 数字类 checkpoint 强制重查**（v1.1 新增，独立段落）
- **附录 D v1.0 → v1.1 变更摘要**（v1.1 新增）
- **协议 frontmatter**（v1.1 新增）

### 删除章节
- 无

---

*协议修订：RAA · 2026-06-13 14:58 CST v1.0 → 15:04 CST v1.1 → 15:20 CST v1.2*  
*权威源：workspace-audit/docs/agent-collaboration-protocol-v1.2.md*  
*v1.0 已被 v1.1 取代（supersedes）；v1.1 已被 v1.2 取代（supersedes）*

---

## 附录 E：v1.1 → v1.2 变更摘要（Arc Flag 响应）

> 本附录列出 v1.2 相对 v1.1 的**所有**变更。

### Arc Flag #1（合规性边界）— 接受，确认 RAA 边界

**Flag 内容**（Arc 2026-06-13 15:18）：
- 协议 status: draft / approver: <pending>，Arc 只能 review + 反馈
- 不能 sync 到 invest-infra/docs/AGENT_COLLABORATION_PROTOCOL.md
- 也不能写到 workspace-audit/（RAA 边界）

**RAA 响应**：
- ✅ 接受边界划分
- ✅ RAA 写 workspace-audit/docs/ 是 RAA 工作区（OK）
- ❌ RAA **不**执行 sync 到 invest-infra/docs/（属于 Arc 责任，协议生效后）
- ✅ v1.2 协议 frontmatter 加 `related_self_review_flags` 字段记录 Arc flag
- ✅ v1.2 协议 §0/§10.1/附录 C 中的"同步建议"段已加"**仅在协议 status: approved 后**"限定

### Arc Flag #2（fix branch 成本）— 接受，v1.2 修订 §2.1

**Flag 内容**（Arc 2026-06-13 15:18）：
- §2.1 fix branch 模式成本：7 个 finding × 1 branch × 1 PR × 1 merge = 7 轮 review
- 建议加白名单允许"同模块 related findings 合 branch"

**RAA 响应**（v1.2 §2.1 修订）：
- ✅ 加白名单例外：3 个条件**同时满足**才允许合 branch
  1. 同模块（子路径相同）
  2. 同根因
  3. 可独立回滚（commit 按 finding 拆）
- ✅ 白名单 branch 命名：`fix/<module>-<root-cause>`（不写 finding_id）
- ❌ **禁止**跨不相关 findings 合 branch（如 RAA-5 + ARCH-1）

**RAA 工作量影响**：
- v1.1 默认：7 finding × 1 branch = 7 轮
- v1.2 白名单：估 3-4 branch（如 RAA-5 + RAA-6 合 / ARCH-1+3+4+5+6 合 / P0-RAA-2 + P0-RAA-3 各自独立）

### Arc Flag #3（§3.6 数字重查基线）— 接受，v1.2 修订 §3.6

**Flag 内容**（Arc 2026-06-13 15:18）：
- §3.6 差异 > 5% 标 HIGH 的"基线"不明确
- 是和 fix-status 记录数比，还是和"fix-status 写时刻的实时快照"比？
- 建议明确"以 fix-status.method 描述的查询方式重新跑一次"为基线

**RAA 响应**（v1.2 §3.6 修订）：
- ✅ 明确**基线（baseline）** = "用 fix-status.method 描述的查询方式重新跑一次"的结果
- ✅ 不是 fix-status 任务中**当时**记录的数字
- ✅ 不是 RAA 自行发明的"另一种查询"
- ✅ RAA 报告必含 5 个字段（last_checked_at / baseline_query / result / recorded_result / delta_pct）
- ✅ 加 `STATUS_FILE_METHOD_UNCLEAR` HIGH 异常（fix-status.method 描述不清时）

**RAA 误报风险降低**：
- v1.1：RAA 重查 7 vs fix-status 5 = 28.6% 差异 → 直接标 HIGH（可能误报）
- v1.2：RAA 重查 7 vs fix-status method 重跑 7 = 0% 差异 → 标 PASS（避免误报）
