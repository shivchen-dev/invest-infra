---
protocol_id: AGENT_COLLABORATION_PROTOCOL
version: 1.4
last_updated: 2026-06-13T18:27:25+08:00
author: RAA
approver: <user-2026-06-13-18:27>  # 用户批准 (QQ sender_id: DC04E397170345249B2A928500EEA2DF, message_id: ROBOT1.0_oKw0FxiTNqg3...)
status: approved
approved_at: 2026-06-13T18:27:25+08:00

supersedes: 1.3
trigger_source: 用户 18:17 (CIA 写权限扩展) + 用户 18:21 (协议视角约束)
---

# 投研系统智能体合作开发协议 v1.4

> **协议 ID**：`AGENT_COLLABORATION_PROTOCOL_v1.4`  
> **状态**：✅ **approved**（2026-06-13 18:27 CST，用户批准）  
> **维护者**：用户 + system-architect + RAA  
> **视角**：**全部以投研系统角度出发**（v1.4 新约束，6/13 18:21 用户明确）  
> **同步状态**：⏳ **pending**（Arc 待 sync 到 `invest-infra/docs/AGENT_COLLABORATION_PROTOCOL.md`）  
> **同步建议**：Arc 收到协议后（**仅在协议 status: approved 后**），同步到 `invest-infra/docs/AGENT_COLLABORATION_PROTOCOL.md`（**由 Arc 写入，RAA 不写**）  
> **v1.0 → v1.1 → v1.2 → v1.3 → v1.4 变更**：见附录 D / E / F / G

---

## 0. 协议目的

投研系统（`/home/claw/invest-infra/`）是 7+ 智能体协作开发项目（CIA / WOA / system-architect / data-architect / tech-expert / Arc / RAA）。**当前 6/13 暴露的 HIGH 异常全部源于协作流程缺失**：

| 已暴露问题 | 来源 |
|---|---|
| 状态文件 commit hash 错引 2 处（orphan commit）| P0-RAA-2 / P0-RAA-3 |
| 修复功能不完整（RAA-5 根因未提交）| RAA-5 |
| 18 项 untracked 改动（11 M + 4 D + 3 ??）| ARCH-1/3/4/5/6 + RAA-5 |

**v1.4 关键约束**（6/13 18:21 用户明确）：**协议全部以投研系统角度出发，不出现审计 Agent 工作区路径**。v1.3 之前协议遗留的审计 Agent 工作区引用**全部清除**。

---

## 1. Agent 角色与边界（写权限矩阵）

### 1.1 角色定义

完整档案见 `invest-infra/SYSTEM_PLAYBOOK.md §6.2`，本协议只列**写权限**。

### 1.2 写权限矩阵（按 `invest-infra/` 子路径分层）

| `invest-infra/` 子路径 | Arc | system-architect | data-architect | tech-expert | CIA/WOA | RAA |
|---|---|---|---|---|---|---|
| `SYSTEM_PLAYBOOK.md` | ❌ | ✅ **唯一** | ❌ | ❌ | ❌ | ❌ |
| `docs/`（含 `AGENT_COLLABORATION_PROTOCOL.md`）| ⚠️ 评审 | ✅ **唯一** | ⚠️ 评审 | ⚠️ 评审 | ❌ | ❌ |
| `init-db/*.sql`（DDL）| ⚠️ 评审 | ❌ | ✅ **唯一** | ⚠️ 评审 | ❌ | ❌ |
| `data-pipeline/src/**/*.py` | ✅ | ❌ | ❌ | ✅ 实现 | ❌ | ❌ |
| `data-pipeline/tests/` | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| `data-pipeline/scripts/cron_*.py` | ✅ **唯一** | ❌ | ❌ | ⚠️ 实现 | ❌ | ❌ |
| `data-pipeline/src/reports/` | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| `data-pipeline/src/collector/` | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| `data-pipeline/src/pipeline/` | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| `setup_*.sh` / `setup_*.py` | ✅ | ⚠️ 评审 | ❌ | ⚠️ 评审 | ❌ | ❌ |
| `docker-compose.yml` | ✅ | ⚠️ 评审 | ❌ | ⚠️ 评审 | ❌ | ❌ |
| `start.sh` / `stop.sh` | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `.raa-fix-status.json` | ✅ **完整** + CIA ✅ **限定** | ❌ | ❌ | ❌ | ⚠️ CIA 仅影响评估字段 | ❌（**只读**）|
| `.secrets/*.env` | ❌ **任何 Agent 都禁** | ❌ | ❌ | ❌ | ❌ | ❌ |
| `.env` | ❌（read-only 引用）| ❌ | ❌ | ❌ | ❌ | ❌ |
| `.codegraph/` | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `.gitignore` | ⚠️ 评审 | ❌ | ❌ | ❌ | ❌ | ❌ |
| `README.md` / `CHANGELOG.md` | ⚠️ 评审 | ✅ | ❌ | ❌ | ❌ | ❌ |
| `planning/` | ⚠️ 评审 | ✅ | ✅ | ✅ | ❌ | ❌ |
| `reports/raa-fix-*`（修复报告）| ✅ 写 | ⚠️ 评审 | ❌ | ❌ | ❌ | ❌ |
| `reports/raa-audit-*`（审计报告）| ❌ | ❌ | ❌ | ❌ | ❌ | ✅ **唯一** |
| `evaluation_reports/` | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ |
| `logs/` | ✅ 运行时写入 | ❌ | ❌ | ❌ | ✅ | ❌ |
| `data/`（运行时数据）| ✅ 运行时写入 | ❌ | ❌ | ❌ | ✅ | ❌ |

**图例**：✅ = 可写 · ✅ **唯一** = 写权限独占 · ⚠️ 评审 = 需 owner 评审 · ❌ = 禁止写

### 1.3 不可越界清单

**RAA 严格禁止**：
- ❌ 写 `invest-infra/` 任何文件
- ❌ 主动跑 cron 脚本写数据
- ❌ 主动 commit / push / force-push
- ❌ 主动发 QQ 通知

**RAA 允许**：
- ✅ 写审计相关报告（`invest-infra/reports/raa-audit-*` 唯一权限）
- ✅ 写 handoff 文件（`invest-infra/raa-handoff-readonly/` 通过投研系统软链接访问）
- ✅ 读 `invest-infra/` 全部产物（git/diff/DB/Redis/cron 只读 run）
- ✅ 跑只读测试

**Arc 严格禁止**：
- ❌ 写 `invest-infra/.secrets/`
- ❌ **任何**未经用户授权的 force-push
- ❌ 在 RAA Re-Audit 未给 verified 结论前 close finding

**CIA 写权限范围**（v1.4 新增）：
- ✅ 写 `invest-infra/.raa-fix-status.json` 中 `status` + `impact_assessment` 字段
- ❌ 写 `commit` / `files_changed` / `re_audit_checkpoints` 字段
- ❌ 做代码修复
- ❌ 触发 Re-Audit

**所有 Agent 共同禁止**：
- ❌ 未经用户明确授权的 force-push
- ❌ 未经 system-architect 评审的 `init-db/*.sql` DDL 变更
- ❌ 未经用户授权的 `git push` 到 `origin/main`

---

## 2. Git 协作流程

### 2.1 Branch 策略

| Branch 类型 | 命名 | 用途 | 谁来管 |
|---|---|---|---|
| **`main`** | `main` | 主分支，**只接受 merge commit** | Arc（merge）+ 用户授权 |
| **`fix/<finding_id>-<short-desc>`** | 例：`fix/P0-RAA-1-pg-password` | 修复分支，**默认每个 RAA finding 一个** | Arc |
| **`fix/<module>-<root-cause>`** | 例：`fix/reports-engine-env-validation` | **白名单分支**（v1.2 新增），合并同模块 + 同根因的 related findings | Arc |
| **`docs/<topic>`** | 例：`docs/agent-protocol-v1.4` | 文档分支 | Arc（v1.4 沿用） |
| **`pre-filter-repo-backup`** | （保留）| 密码轮换前备份 | 保留不动 |

**白名单例外 3 条件**（v1.2 §2.1 Arc Flag #2 修订）：
- ✅ **同模块**：findings 影响的 `invest-infra/` 子路径相同
- ✅ **同根因**：findings 的 root cause 相同
- ✅ **可独立回滚**：commits 按 finding 拆，可独立 revert

### 2.2 Commit 规范

**Conventional Commits**：

```
<type>(<scope>): <subject>

<body>

<footer>
```

**type 取值**：`fix` / `feat` / `refactor` / `docs` / `chore` / `test` / `revert`  
**scope 取值**：`P0-RAA-N` / `P1-RAA-N` / `P2-RAA-N` / `ARCH-N` / `RAA-N` / `TRACE-N` / 模块名

### 2.3 Push 流程

- ❌ 禁止直接 `git push` 到 `origin/main`
- ✅ 流程：本地 commit → `git status --short` 自检 → 通知用户 → 用户授权 → push
- ✅ 一次 push 一个 commit（或一个 fix bundle）

### 2.4 Force-push 限制

- ❌ **禁止**未经用户授权的 force-push
- ✅ 通知用户 + commit message 标注 `Force-pushed by <reason>` + 状态文件 `remote` 字段记录时间 + `pre-filter-repo-backup` 备份

### 2.5 工作区清洁原则

- ❌ **禁止**在有其他 untracked 改动时 commit
- ✅ commit 前 `git status --short` 确认无意外
- ✅ 跨 finding 改动必须**先** commit 上一 finding

---

## 3. 状态文件协议（`invest-infra/.raa-fix-status.json`）

### 3.1 读写权限

- **写**：
  - **Arc**（修复执行 Agent）— 完整字段
  - **CIA**（首席投资官）— 限定字段（status + impact_assessment）
- **读**：RAA（Re-Audit）、CIA/WOA（任务排程 + 状态追踪）、用户（决策）
- **其他 Agent**：禁止读（避免污染决策）

### 3.1.1 写权限详细范围（v1.4 新增）

| Agent | 写权限 | 范围 | 约束 |
|---|---|---|---|
| **Arc** | ✅ 完整 | status / commit / files_changed / re_audit_checkpoints / reviewed_by 全字段 | v1.2 §3.2 schema 严格 |
| **CIA** | ✅ 限定 | status（影响评估状态）+ `impact_assessment` 自定义字段 | CIA 影响评估类 finding（P1-RAA-2/3/TRACE-P0）|
| **其他 Agent** | ❌ 禁止 | — | — |
| **RAA** | ❌ 禁止（**只读** Re-Audit 决定 status）| — | v1.3 §3.3 状态转换 + §1.2 矩阵 |

**CIA `impact_assessment` 字段 schema**（v1.4 新增）：

```json
{
  "finding_id": "P1-RAA-2",
  "status": "impact-assessed",
  "impact_assessment": {
    "assessor": "CIA",
    "scope": "P1-RAA-2 影响范围：morning briefing 链路",
    "severity": "HIGH",
    "qa_task_count": 5,
    "assessed_at": "2026-06-13T18:00:00+08:00",
    "linked_tasks": []
  }
}
```

**触发条件**（CIA 可写 fix-status）：
- 6/13 14:21 User Decision：3 个系统逻辑类 finding → CIA 角色 A（影响评估 + 状态追踪）
- CIA 评估完影响后，标 `impact_assessment` 字段 + 更新 status

**约束**：
- ❌ CIA **不**做修复（避免越界）
- ❌ CIA **不**触发 Re-Audit（仅用户调度）
- ✅ CIA **可**写新 finding entry（当 CIA 自身发现新 finding 时）—— **但**需走 §11.4 handoff 流程（**不**直接写 fix-status）

### 3.2 Schema（v1）

> **v1.1 重要变更**：re_audit_checkpoints 强制增加 `last_checked_at` 时间戳字段。

**关键字段**：
- `finding_id`（必填，unique）
- `status`（必填，enum）：
  - `fixed-pending-verify`（Arc 提交后）
  - `verified-fixed`（RAA verified，最终态）
  - `verified-with-caveats`（v1.3 新增，介于 verified-fixed 和 incomplete 之间）
  - `impact-assessed`（v1.4 新增，CIA 影响评估后）
  - `incomplete`（部分修复，最终态）
  - `reverted`（已回滚）
  - `wontfix`（决定不修）
- `agent`（必填）：执行修复的 Agent
- `branch`（必填）：**fix branch 名称**
- `commit`（可选）：**branch 上可达的** commit hash（非 orphan）
- `started_at` / `completed_at`（必填）：ISO 8601 with timezone
- `summary`（必填）：≤200 字
- `re_audit_checkpoints`（必填）：
  - v1.1 新增 `last_checked_at`：RAA Re-Audit 时间戳
  - 每项 checkpoint 子对象必填 `last_checked_at`
- `files_changed`（必填）：与 `git diff` 一致
- `impact_assessment`（v1.4 新增，可选）：CIA 影响评估字段

### 3.3 状态转换规则

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
                  ↙   ↓   ↘   ↘   ↘
         verified   verified-   incomplete   wontfix
         (Arc 关)   with-        (回 fix       (Arc 关)
                     caveats      branch)
                     (v1.3 新)     持续修复
                       ↓         fixed-pending-verify
                  (Arc 关 + 写 caveat 说明)
                       ↓
                       (循环)

[CIA 影响评估路径]（v1.4 新增）
fixed-pending-verify
       ↓
[CIA 评估影响]
       ↓
impact-assessed
       ↓
[继续 RAA Re-Audit]
```

**v1.3 新增状态**：`verified-with-caveats`  
**v1.4 新增状态**：`impact-assessed`

### 3.4 状态文件保真原则

- ✅ `commit` 字段**必须是 branch 上可达的 hash**（`git rev-parse <ref>^{commit}` 验证）
- ✅ `files_changed` 必须与 `git diff <branch>~1..<branch> --name-only` 一致
- ✅ `re_audit_checkpoints[*].status` 必须是 RAA Re-Audit 后的结果
- ✅ `re_audit_checkpoints.last_checked_at` 必须 ≤ `now()`
- ❌ **禁止**在 commit hash 字段引用 orphan commit
- ❌ **禁止**在 XLEN / 计数类 checkpoint 中写"采样值"

**v1.1 联动 §6.1**：发现 orphan commit 引用 → RAA 标 `STATUS_FILE_ORPHAN_COMMIT_REF` HIGH → Arc 修正。

### 3.5 Re-Audit 触发信号

**用户**（QQ 消息）= 启动 Re-Audit 的唯一触发器：
- 消息 1："状态文件已同步更新（.raa-fix-status.json）"
- 消息 2："请对 [项目名] 启动 Re-Audit"
- 消息 3："读取 status 并审计"

**RAA 行为**：
- ✅ 收到上述任一信号 → 立即启动 Re-Audit
- ❌ **不主动**读 `.raa-fix-status.json`

### 3.6 数字类 checkpoint 强制重查

> **v1.1 新增** + **v1.2 Arc Flag #3 修订**

**基线（baseline）** = "用 fix-status.method 描述的查询方式重新跑一次"得到的结果

**判定**：
- 差异 ≤ 5% → 标 `STATUS_FILE_NUMBERS_FRESH` PASS
- 差异 > 5% → 标 `STATUS_FILE_NUMBERS_STALE` HIGH
- fix-status.method 描述不清 → 标 `STATUS_FILE_METHOD_UNCLEAR` HIGH

**RAA 报告必含 5 字段**：
- `rra_reaudit_last_checked_at`
- `baseline_query`
- `rra_reaudit_result`
- `fix_status_recorded_result`
- `delta_pct`

---

## 4. 修复流程（Fix → Re-Audit）

### 4.1 Arc 工作流

```
1. 接收 RAA handoff（finding_id + 修复建议 + 责任分配）
2. 评估可行性 + 风险（不明 → 找 system-architect 评审）
3. 创建 fix branch：git checkout -b fix/<finding_id>-<short-desc>
4. 修改代码
5. 跑本地测试（pytest + smoke test）
6. 独立 commit（每个 finding 一个）
7. 更新 .raa-fix-status.json（status: fixed-pending-verify）
8. push fix branch
9. 通知用户（QQ）
10. ⏸️ 等 RAA Re-Audit
11. 根据 RAA 结论：
    - verified-fixed → merge fix branch → main
    - incomplete → 继续修复
    - wontfix → 关 fix branch
    - reverted → 回滚
12. merge 后 push main
```

### 4.2 部署与 commit 分离原则

每个 finding 必须经历**两个阶段**：
- **阶段一（部署）**：功能"能跑"（已 deployed/已运行）
- **阶段二（commit）**：git 上"已 commit"（fix-status commit 字段可指向）

**"部署"范畴**：

| 类别 | 属于"部署"吗？ | 需 commit 吗？ |
|---|---|---|
| Python 代码改动 | ✅ | ✅ 必须 git commit |
| SQL DDL | ✅ | ✅ 必须 git commit |
| YAML/TOML 配置 | ✅ | ✅ 必须 git commit |
| `.env` / `.secrets/*.env` | ✅ | ❌ gitignored（不 commit）但需在 fix-status 备注 |
| `systemd timer` 启用 | ✅ | ⚠️ 视 timer 单元位置 |
| Redis stream 写入 | ✅ | ❌ Redis 不在 git 管理 |
| Docker compose 启动 | ✅ | ⚠️ `docker-compose.yml` commit；运行时容器不 commit |

### 4.3 Re-Audit 阻断

RAA Re-Audit 给出 `incomplete` 结论时：
- ❌ Arc **不能**绕过
- ❌ 用户**不能**强制通过（除非明确撤销 RAA 审计结论 + 留痕）
- ✅ 唯一路径：继续修复 → 重新 commit → 重新触发 Re-Audit

---

## 5. 边界铁律

### 5.1 写权限矩阵回顾

见 §1.2。

### 5.2 BOUNDARY OVERRIDE 协议

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
- commit message 是否与 finding_id 严格对齐
- 是否有 force-push 留下的 orphan commit 残留
- 是否有 Agent 写到非授权路径

---

## 6. 版本管理最佳实践

### 6.1 避免 orphan commit

- ❌ 避免 force-push（除非必要）
- ✅ 必要时保留 orphan commit 引用在 `pre-filter-repo-backup` branch
- ✅ force-push 后**所有引用旧 commit 的状态文件 / 文档**必须更新
- ✅ RAA 验证时用 `git log --all --reflog`
- ✅ orphan detection 流程（v1.1 联动 §3.4）：
  1. RAA Re-Audit 时校验 fix-status commit 字段 `git rev-parse <ref>^{commit}` 失败
  2. 标 `STATUS_FILE_ORPHAN_COMMIT_REF` HIGH
  3. Arc 修正
  4. RAA 重新 Re-Audit

### 6.2 避免 commit hash 错引

- ✅ Arc commit **之后**才写状态文件
- ✅ 状态文件 commit 字段**只引用 force-push 之后 branch 上可达的 hash**
- ✅ 写状态文件前**必须**用 `git rev-parse <ref>^{commit}` 验证可达性

### 6.3 状态文件数字保真

- ✅ 数字类 checkpoint（XLEN、COUNT 等）**必须**标 `last_checked_at` 时间戳
- ✅ RAA Re-Audit 时**必须重新查询**实时数字，不信任 fix-status 任务中数字
- ✅ RAA 报告必含 5 字段（last_checked_at / baseline_query / result / recorded_result / delta_pct）

### 6.4 untracked 累积治理

- ✅ 每个 finding commit **只包含**该 finding 改动的文件
- ✅ commit 前 `git status --short` 确认无意外 untracked
- ✅ 跨 finding 改动必须**先 commit 上一 finding**
- ✅ 修复过程中产生的 .bak / .orig / debug 脚本必须立即清理

**案例引用**（v1.1 强化）：6/13 Re-Audit 暴露的 18 项 untracked 改动直接导致 RAA-5 根因修复在 staged 状态。

### 6.5 Force-push 前的通知

- ✅ 通知用户 + 等待授权
- ✅ 留 `pre-filter-repo-backup` 备份
- ✅ commit message 标注 `Force-pushed by <reason>`
- ✅ 状态文件 `remote` 字段记录 force-push 时间

---

## 7. 通信协议

### 7.1 QQ 用户调度

**用户** = 投研系统最高调度者（不可被任何 Agent 替代）。

**用户授权** = 不可被 RAA 自行解读的：
- ❌ "在 X 建链接" = 不构成授权
- ❌ "修复一下" = 不构成授权
- ✅ "撤销 §6.3 边界铁律，RAA 在 invest-infra/ 建软链接" = **构成授权**

### 7.2 Handoff 文件

> **v1.4 补全**：handoff 链接到父 audit 报告。

**RAA Audit 报告**（父文档）：
- 路径：`invest-infra/reports/raa-audit-*.md`（RAA 唯一写权限）
- 包含：审计对象 + 方法 + findings 列表

**RAA Handoff 文件**（子文档）：
- 路径：`invest-infra/raa-handoff-readonly/raa-handoff-<system>-<date>.md`（投研系统软链接）
- 包含：finding_id + 描述 + 根因 + 修复建议 + 责任分配 + 验证方法 + **链接到父 audit 报告**

**Arc 读路径**：
- 读 handoff → 找父 audit 报告 → 实施修复

**单向**：
- RAA 写父 + 子
- Arc 读 handoff + 写 fix-status
- ❌ RAA 不写 fix-status
- ❌ Arc 不写 handoff

### 7.3 状态文件

见 §3。

### 7.4 systemd timer

**Owner**：`setup_systemd_timers.py`（统一入口，遵循 ARCH-1 修复）。

**注册流程**：Arc 修改 `cron_dispatcher.py` TASK_MAP + `setup_systemd_timers.py` SINGLE_TASKS → 跑 `python3 setup_systemd_timers.py` 重新生成 timer。

**清理**：同步删除 TASK_MAP + SINGLE_TASKS + 重跑 `setup_systemd_timers.py`。  
❌ **禁止**用 `setup_cron_timers.sh`（已 DEPRECATED）。

---

## 8. 冲突解决

### 8.1 Merge conflict

**Arc 责任**：
- ✅ 解决 `main` 上的 conflict
- ❌ **禁止** force-push 解决 conflict

**升级路径**：
- 多 finding → system-architect 评审
- 数据 schema → data-architect 评审
- 审计边界 → RAA 评估

### 8.2 状态文件不一致

RAA Re-Audit 发现状态文件与实际状态不符：
- ✅ RAA 在 Re-Audit 报告中标 `STATUS_FILE_INCONSISTENT` HIGH
- ✅ 列出不一致点
- ❌ RAA **不**修改状态文件

**修复路径**：Arc 修改 → 重新 commit → 重新触发 Re-Audit

### 8.3 工作区脏

RAA 每次 Re-Audit 必查 `git status --short`：

**HIGH 异常**（必须修复后才能通过 Re-Audit）：
- 有不属于该 fix 的 M/D 文件混入
- 有 ?? 状态文件无 commit
- 有 .bak / .orig / 调试脚本残留
- `git log <branch> --stat` 与 `git status` M 文件**不一致**

**MEDIUM 异常**（标不阻断）：无关 untracked  
**LOW 异常**（忽略）：build artifact

### 8.4 Re-Audit 阻断

RAA Re-Audit 给出 `incomplete` 结论时：
- ❌ Arc **不能**绕过
- ❌ 用户**不能**强制通过
- ✅ 唯一路径：继续修复 → 重新 commit → 重新触发 Re-Audit

---

## 9. 监督与审计

### 9.1 RAA 审计周期

- **定期审计**：每周一次（待用户设置）
- **触发审计**：
  - 修复完成（用户 QQ 信号）= 立即 Re-Audit
  - 用户明确要求 = 立即审计
  - 数据异常检测 = 立即审计
- **不主动巡检**

### 9.2 异常处理

**HIGH 异常**：
- 状态文件数据错误 → Arc 立即修复 → 重新 Re-Audit
- 修复功能不完整 → Arc 继续修复 → 重新 Re-Audit
- 越界写入 → 立即撤销（如可能）+ 报告

**MEDIUM 异常**：
- untracked 累积 → 治理
- 数字过期 → Arc 重新查询 + 更新

**LOW 异常**：文档不一致 → 下次审计同步修复

### 9.3 教训库

**位置**：`invest-infra/raa-audit-readonly/LEARNINGS.md`（RAA 维护，软链接可见）

**强制记录**：任何 Re-Audit 暴露的协议违反。

---

## 10. 协议修订

### 10.1 修订流程

```
[任意 Agent / 用户 提出修订建议]
    ↓
[起草 RFC（位置：投研系统软链接访问的 handoff 目录）]
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

- **v1.0**（2026-06-13 14:58）：基于 Re-Audit 暴露的 3 个 HIGH 异常起草
- **v1.1**（2026-06-13 15:04）：基于 v1.0 self-review 暴露的 3 HIGH + 6 MEDIUM + 4 LOW 异常修订
- **v1.2**（2026-06-13 15:24）：基于 v1.1 接受 Arc 3 个 flag 修订
- **v1.3**（2026-06-13 16:20）：基于 v1.2 接受 RAA-7 Re-Audit 暴露的 3 项 follow-up + handoff 治理 + RAA 报告精简原则
- **v1.4**（2026-06-13 18:21，draft）：基于 v1.3 接受用户 18:17 明确请求：fix-status 写权限扩展 Arc → Arc + CIA，handoff 目录权限矩阵详细化（消除灰色地带）；**6/13 18:21 用户 18:21 新约束：协议全部以投研系统角度出发，不出现审计 Agent 工作区路径**（v1.4 全文重写）

---

## 11. Handoff 文件治理原则（v1.3 新增，v1.4 重写以投研系统视角）

> **触发**：2026-06-13 15:44 用户问"交接目录过期的文档你是不是要及时归档"+ RAA 6/13 15:44 治理 4 项动作。

### 11.1 治理总则

| 触发条件 | 动作 | 目标位置 | 边界 |
|---|---|---|---|
| 总 handoff 全部 finding 已关闭 | **整体归档** | `invest-infra/raa-handoff-readonly/_archive/` | RAA 写 |
| 总 handoff 部分 finding 已关闭 | **原地更新状态** | 保留 active | RAA 写 |
| 总 handoff 被后续 handoff 取代 | **前者归档 + 后者加 `supersedes` 字段** | 前者 `_archive/` + 后者原地 | RAA 写 |
| 文档类 handoff 子目录 | **完结后加 CHANGELOG §X 状态更新段** | 子目录内 CHANGELOG.md | RAA 写 |

### 11.2 归档强约束

- ✅ **整体归档触发条件严格**：仅当**所有** finding 状态 ∈ {VERIFIED, Wontfix, Withdrawn, verified-with-caveats} 才整体归档
- ✅ **部分归档就地更新**：部分 finding 仍 Pending 时保留 active + §0 表格标进展
- ✅ **取代关系显式记录**：新 handoff 引用旧 handoff 时加 `supersedes` 字段
- ✅ **子目录 doc 类 handoff**：完结后**必须**更新 CHANGELOG，**不**归档子目录
- ❌ **禁止**强制归档仍含 Pending finding 的 handoff
- ❌ **禁止**改动已归档 handoff 内容
- ❌ **禁止** RAA 归档"等用户调度"状态的 finding

### 11.3 投研系统可见路径

> **v1.4 重写**：本节仅描述**投研系统用户视角**，**不暴露**实现细节。

- **handoff 软链接**：`invest-infra/raa-handoff-readonly/`（投研系统内软链接）
- **audit 软链接**：`invest-infra/raa-audit-readonly/`（投研系统内软链接）
- 软链接由架构 Agent / 用户创建（RAA 边界外）
- 投研系统用户通过软链接**直接可见**所有 handoff + audit 文件

### 11.4 Handoff 目录权限详细（v1.4 新增）

> **触发**：2026-06-13 18:14 用户问"rAA 交接目录是你负责，其他智能体不会写入的吧"+ 18:17 用户问"fix-status 扩大下范围包括 cia, raa 交接目录权限明确一下"。

**写权限矩阵**：

| 动作 | Agent | 权限 | 协议依据 |
|---|---|---|---|
| **写新 handoff 文件** | RAA | ✅ 独占 | §1.2 矩阵 + §7.2 单向协议 |
| **写新 handoff 文件** | 其他 Agent | ❌ 禁止 | §1.2 矩阵（灰色 → 严格解读为 RAA 独占）|
| **更新已有 handoff 的 Status 字段** | 修复 Agent | ✅ 可写 | §7.2 option 2 反馈路径（RAA Re-Audit 后覆盖）|
| **更新 handoff 状态字段** | RAA | ✅ 覆盖 | Re-Audit 后写权威状态 |
| **创建 handoff 软链接** | 用户 / 架构 Agent | ✅ 可建 | §11.3（RAA 边界外）|
| **创建 audit 软链接** | 用户 / 架构 Agent | ✅ 可建 | §11.3（RAA 边界外）|
| **写 fix-status（完整字段）** | Arc | ✅ | §3.1 + §1.2 |
| **写 fix-status（影响评估字段）** | CIA | ✅ 限定 | v1.4 §3.1.1 新增 |
| **写 fix-status** | 其他 Agent | ❌ 禁止 | §1.2 矩阵 |

**handoff 目录结构**：

```
invest-infra/raa-handoff-readonly/  (投研系统内软链接)
├── README.md                  [RAA 写]
├── TEMPLATE.md                [RAA 写]
├── _archive/                  [RAA 写]
│   └── raa-handoff-grid-plan-20260612.md  [RAA 归档]
├── raa-handoff-invest-infra-20260611.md  [RAA 写 + 更新]
├── raa-handoff-invest-infra-architecture-20260613.md  [RAA 写 + 更新]
├── raa-handoff-protocol-v1.2-sync-20260613.md  [RAA 写]
├── raa-handoff-protocol-v1.3-sync-20260613.md  [RAA 写]
└── raa-handoff-system-docs-20260612/  [RAA 写 + 架构 Agent 评论]
```

**灰色地带处理原则**：

- **新 handoff 文件** = **RAA 独占**（其他 Agent 灰色 → 按严格解读为"不写"）
- 修复 Agent 发现新 finding（不在 RAA handoff 范围）：
  - **步骤 1**：先**通知 RAA**（QQ / 写 `impact_assessment` 字段）
  - **步骤 2**：RAA 评估后**决定**写新 handoff
  - ❌ 修复 Agent **不**自行写新 handoff 文件
- handoff 命名规则：`raa-handoff-<system>-<YYYYMMDD>.md`（RAA 命名空间）

---

## 12. RAA 报告精简原则（v1.3 新增，v1.4 重写以投研系统视角）

> **触发**：2026-06-13 15:58 用户反馈"不用每次都发边界遵守，不要重复发送噪音，我需要关键决策信息，明确的交接文档路径，不是你工作区的路径"。

### 12.1 报告核心（4 项必含，去除噪音）

| # | 必含 | 去除 |
|---|---|---|
| 1 | **关键决策信息**：状态判定（PASS/FAIL/Caveat）+ 可信度 | 重复的"边界遵守"段 |
| 2 | **风险点**：N 项 follow-up（优先级排序）| 过程性说明（git log/diff 等）|
| 3 | **下一步 action**：Agent 必做 N 件事 | 工具调用统计 |
| 4 | **交接文档路径**：**仅投研系统可见路径** | **不出现 RAA 工作区路径**（v1.4 强化）|

### 12.2 路径报告原则（v1.4 强化）

> **v1.4 强化**：**仅**投研系统可见路径。**不**出现 RAA 工作区路径。

- **首选（且唯一）** = 投研系统可见路径（`invest-infra/...`）— 用户能直接看到
- ❌ **禁止** RAA 工作区路径作为"次选"或"权威源备注"（v1.3 §12.2 错误，v1.4 修正）
- 软链接由用户/架构 Agent 建，**不**由 RAA 维护

### 12.3 精简版 vs 完整版

- **精简版**（chat 回复）：4 项核心，≤300 字
- **完整版**（Re-Audit 报告文件）：保留全部审计证据 + 5 字段齐全（§3.6 强制）
- 两者**不同步**：精简版摘要 + 完整版路径（**仅投研系统路径**）

---

## 附录 A：协议与现有文档的关系

| 文档 | 关系 |
|---|---|
| `invest-infra/SYSTEM_PLAYBOOK.md §6` | 智能体档案（被本协议引用） |
| `invest-infra/CLAUDE.md` | 项目工程文档（运维/测试/架构） |
| `invest-infra/reports/raa-audit-*.md` | 触发本协议起草的 Re-Audit 报告 |

## 附录 B：边界铁律自检清单

每次启动 Re-Audit 前必过：

```
□ 1. 是否会写 invest-infra/ 任何文件？→ 如果是 = 立即停下问用户
□ 2. 是否会发 QQ 通知？→ 如果是 = 立即停下问用户
□ 3. 是否会跑 cron 脚本写数据？→ 如果是 = 改成只读测试
□ 4. 是否会主动巡检（无用户信号下读 .raa-fix-status.json）？
      → 如果是 = 等用户 QQ 信号
□ 5. 是否会主动 commit / push？→ 如果是 = 立即停下
□ 6. 是否会写到非授权路径？→ 如果是 = 立即停下
```

## 附录 C：协议生效检查清单

- [ ] system-architect 评审协议
- [ ] 用户最终批准
- [ ] Arc 同步到 `invest-infra/docs/AGENT_COLLABORATION_PROTOCOL.md`
- [ ] 通知所有 Agent（CIA / WOA / system-architect / data-architect / tech-expert / Arc / RAA）
- [ ] RAA 在 `invest-infra/reports/raa-audit-*.md` 标记"协议 v1.X 已生效"

## 附录 D：v1.0 → v1.1 变更摘要

> **摘要**：v1.0 起草后 self-review 修订，修复 3 HIGH + 6 MEDIUM + 4 LOW。

**关键变更**：
- 写权限矩阵从笼统描述改为按 `invest-infra/` 子路径分层（23 行）
- Branch 策略从"统一在 main"改为强制 fix branch
- Schema 强制 `last_checked_at` 时间戳

## 附录 E：v1.1 → v1.2 变更摘要（Arc Flag 响应）

> **摘要**：v1.1 接受 Arc 3 个 flag 修订（合规性 + fix branch 白名单 + §3.6 基线）。

**关键变更**：
- §2.1 加白名单例外（fix branch `fix/<module>-<root-cause>`）
- §3.6 数字重查基线明确为"fix-status.method 重跑"
- §附录 C 同步建议加"仅在协议 status: approved 后"

## 附录 F：v1.2 → v1.3 变更摘要（6/13 16:10 RAA-7 Re-Audit 触发）

> **摘要**：v1.2 接受 RAA-7 Re-Audit 暴露的 3 项 follow-up + handoff 治理 + RAA 报告精简原则。

**关键变更**：
- §3.3 状态枚举加 `verified-with-caveats`（v1.2 缺失中间态）
- §11 handoff 治理原则（4 总则 + 7 强约束）
- §12 RAA 报告精简原则（4 必含 + 3 去除）

## 附录 G：v1.3 → v1.4 变更摘要（6/13 18:21 用户 18:17 + 18:21 触发）

> **摘要**：v1.3 接受用户 18:17 明确请求（fix-status 写权限扩展 + handoff 目录权限详细化）+ 18:21 新约束（协议全部以投研系统角度出发）。**v1.4 全文重写**。

### 触发源

- **2026-06-13 18:14 用户问**：「rAA 交接目录是你负责，其他智能体不会写入的吧」
- **2026-06-13 18:17 用户问**：「fix-status 扩大下范围包括 cia, raa 交接目录权限明确一下」
- **2026-06-13 18:21 用户问**：「协议全部以投研系统角度出发，不要出现你工作区路径」

### 3 项关键变更

#### 1. §3.1 写权限扩展：Arc → Arc + CIA

**CIA 写权限范围**（§3.1.1）：
- ✅ status（影响评估状态）
- ✅ `impact_assessment` 自定义字段（v1.4 schema 扩展）
- ❌ commit / files_changed / re_audit_checkpoints（**仅 Arc 写**）

**触发条件**：6/13 14:21 User Decision：3 个系统逻辑类 finding → CIA 角色 A（影响评估 + 状态追踪）

**约束**：
- ❌ CIA **不**做修复（避免越界）
- ❌ CIA **不**触发 Re-Audit（仅用户调度）

#### 2. §11.4 Handoff 目录权限详细（v1.4 新增）

**目的**：消除 v1.3 时代"新 handoff 文件写入权限"的灰色地带。

**关键内容**：
- 9 条写权限矩阵（动作 × Agent × 协议依据）
- handoff 目录结构 + 写权限标注
- 灰色地带处理原则（新 finding 发现流程）

#### 3. **v1.4 全文重写（按用户 18:21 新约束）**

**v1.4 之前协议遗留问题**：
- 26 处出现 RAA 工作区路径（v1.3 时代遗留）
- §12.2 路径原则允许"RAA 工作区路径作为次选"（v1.3 错误）
- 附录 D/E/F 都引"权威源"指 RAA 工作区路径
- §0 "存放位置"直接写 RAA 工作区路径
- §1.2 矩阵也写 RAA 工作区为"RAA 写"

**v1.4 重写后**：
- ❌ **完全删除** RAA 工作区路径
- ❌ **完全删除** "RAA 工作区"概念
- ✅ 全部按**投研系统视角**写
- ✅ §12.2 路径原则改为"**仅**投研系统可见路径"
- ✅ §11.3 软链接描述**不**暴露 RAA 实现细节
- ✅ 附录 D/E/F 改为"摘要"形式（不指明 RAA 工作区）

**v1.4 移除的 RAA 工作区引用清单**（26 处）：
- §0 存放位置
- §1.2 矩阵 RAA 写权限（重写为"✅ 写审计相关报告"，不提 RAA 工作区）
- §5.2 BOUNDARY OVERRIDE 协议引用（移除具体路径）
- §7.2 handoff 路径（仅写"投研系统软链接"）
- §7.2 option 2 反馈路径（移除具体路径）
- §9.3 教训库位置（改为投研系统软链接路径）
- §10.1 修订流程（RFC 起草位置改为"投研系统软链接访问的 handoff 目录"）
- §11.3 软链接描述（不暴露 RAA 实现）
- §12.2 路径原则（**仅**投研系统路径）
- 附录 A 文档关系（重写为投研系统视角）
- 附录 B 自检清单（移除 RAA 工作区路径）
- 附录 C 协议生效检查清单（重写为投研系统路径）
- 附录 D/E/F 变更摘要（移除 RAA 工作区路径）
- frontmatter `related_*` 字段（重写为纯描述，不指明 RAA 工作区路径）

### v1.4 未解决项（v1.5 候选）

- WOA 写权限（v1.3 时代仅读，v1.4 未扩展）— 等用户明确需求
- system-architect / data-architect / tech-expert 写权限（v1.4 未涉及）— 同上
- 软链接 `raa-{handoff,audit}-readonly` 自身 untracked（v1.2 §2.5 违反）— 跨周期未解决
- v1.3 协议本身仍含 RAA 工作区路径（v1.3 已 approved 不重写，但 v1.3 supersedes by v1.4 后失效）

---

*协议修订：RAA · 2026-06-13 14:58 CST v1.0 → 15:04 CST v1.1 → 15:24 CST v1.2 (approved) → 16:20 CST v1.3 (approved) → 18:27 CST v1.4 (approved)*  
*权威源：`invest-infra/docs/AGENT_COLLABORATION_PROTOCOL.md`（Arc 待 sync v1.4）*  
*v1.0 已被 v1.1 取代（supersedes）；v1.1 已被 v1.2 取代（supersedes）；v1.2 已被 v1.3 取代（supersedes）；v1.3 已被 v1.4 取代（supersedes）*
