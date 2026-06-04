# 批量修复工作流 — Agent 间协作规范

> 适用场景：大量代码缺陷需要按批次修复，每批由独立的 subagent（Claude Code）执行，主 agent 负责任务拆分、进度追踪、结果汇总。

---

## 核心原则

1. **planning-with-files 先于一切** — 动手前先写 `task_plan.md`，崩溃可恢复
2. **批次隔离** — 每批 2-4 个模块、3-7 个问题，上下文可控
3. **独立 subagent** — 各批次独立运行，主 agent 做其他事
4. **结果写盘** — 每批完成立即更新 task_plan.md，不依赖内存

---

## 工作流图

```
用户/主agent
    │
    ▼
┌─────────────────────────────────────┐
│  Phase 0: 任务梳理                    │
│  step 0.1: 读取评估报告              │
│  step 0.2: Claude Code 独立审计     │ ← 新增：第二审视角
│  step 0.3: 对比报告，生成合并缺陷清单 │ ← 新增：差异对比
│  step 0.4: 创建 planning files       │
│  task_plan.md  — 完整批次计划        │
│  findings.md   — 各问题修复方案     │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Phase 1: 逐批执行                   │
│  sessions_spawn(mode=run)            │
│  每批独立 subagent，background运行   │
└──────────────┬──────────────────────┘
               │
        ┌──────┴───────────────────┐
        ▼                         ▼
   Batch 1                  Batch 2
   (pg.py)                  (financial+news)
        │                         │
        ▼                         ▼
   完成后更新                完成后更新
   task_plan.md             task_plan.md
        │                         │
        └──────┬───────────────────┘
               ▼
        下一批 sessions_spawn
               │
               ▼
         所有批次完成后
         合并 commit → git
         审计归档 → reports/audit_comparison_{date}.md
```

---

## Phase 0: 任务梳理 + 评估报告对比

### Step 0.1: 收集信息
- 读取评估报告，确认所有问题存在
- 如果有审计结果，直接用

### Step 0.2: Claude Code 独立审计（对比环节）
**目的**：评估报告由人工或规则生成，可能遗漏深层 bug；Claude Code 作为第二审视角补充验证。

**操作**：启动 Claude Code subagent，对同一批文件做独立审计，输出格式统一的缺陷列表：
```
| ID | 严重度 | 行号 | 描述 | 修复建议 |
```

**Prompt 结构**：
```
严格审查以下文件，输出每个文件的缺陷列表：
- {文件路径}
- 关键检查点：...（从评估报告提取）

输出格式：
### {文件名}
| ID | 严重度 | 行号 | 描述 | 修复建议 |
```

### Step 0.3: 对比两份报告，生成合并缺陷清单
| 对比维度 | 说明 |
|---------|------|
| 评估报告有 / Claude Code 有 | 交叉验证，确认真实存在 |
| 评估报告有 / Claude Code 无 | 人工复核，判断是否降级或保留 |
| Claude Code 有 / 评估报告无 | **新增发现**，追加到修复计划 |
| 根因深度差异 | 以更深的那个为准 |

**输出**：合并后的缺陷总表（含来源标注），作为 task_plan.md 的输入。

### Step 0.4: 创建 planning files
在项目目录创建：
```bash
task_plan.md   # 批次计划，状态追踪
findings.md    # 各问题修复方案细节
progress.md    # 执行日志（每批结果）
```

### Step 0.5: 编写 task_plan.md
每个批次格式：
```markdown
### Batch N: 模块名（优先级）
<!-- 问题描述 -->
- [ ] 问题编号: 修复要求
- [ ] 问题编号: 修复要求
- **Status:** pending
```

### Step 0.6: 编写 findings.md
每个问题写：
```markdown
## 问题编号: 描述
**当前代码:**
```python
# 当前有问题的代码
```

**修复要求:**
- 要求1
- 要求2

**约束:**
- 不改变函数签名
- 不修改其他函数
```
```

---

## Phase 1: 批次执行

### 启动批次
```python
sessions_spawn(
    mode="run",
    runtime="subagent",
    taskName="fix_batch{N}_{模块名}",
    task="""...""",  # 修复 prompt
)
```

### Prompt 结构（每批次统一）
```
## 修复文件: /path/to/file.py

### 问题1: 简短描述
**位置:** 约 Lxx
**当前代码:**
```python
# 有问题的代码
```
**修复要求:**
- 具体要求

### 问题2: ...
```

**Prompt 尾部必须包含：**
```
## 约束
- 每个修复点单独验证
- 不改变其他函数行为
- 如果行号±3偏差，按实际代码逻辑定位
- 完成后简短输出每模块修复结果

## 通知
完成后输出每模块修复结果摘要。
```

### 监控进度
- subagent 运行中：无需主动 poll
- 等 runtime completion event 回来
- 收到后：更新 task_plan.md → 启动下一批

### 更新 task_plan.md
```markdown
### Batch N: 模块名
- [x] 问题1: 修复说明
- [x] 问题2: 修复说明
- **Status:** ✅ complete
```

---

## 批次划分原则

| 维度 | 建议 |
|------|------|
| 每批问题数 | 3-7 个 |
| 每批模块数 | 2-4 个 |
| 问题相关性 | 同模块或强相关模块放同批 |
| 优先级 | P0 放前面 |

**批次大小参考：**
- 问题 < 5 个 → 1 批
- 问题 5-15 个 → 2-3 批
- 问题 > 15 个 → 按模块拆分

---

## 收尾流程

### 所有批次完成后
```bash
cd /path/to/project
git diff --stat          # 确认改动范围
git add .
git commit -m "fix(data-collector): 修复N个代码缺陷
- Batch 1: pg.py NV1/DV1
- Batch 2: financial.py + news.py
..."
```

### 审计日志归档
将评估报告 + Claude Code 审计报告 + 对比结果合并写入 `reports/audit_comparison_{date}.md`，纳入版本历史。
```

---

## 与 Superpowers 的关系

Superpowers 是 **Claude Code 内部的能力增强**，不是主流程的一部分。

| 场景 | 用不用 Superpowers |
|------|-------------------|
| 复杂逻辑 bug 调试 | ✅ 用 `systematic-debugging` |
| 代码质量审查 | ✅ 用 `code-review` |
| 简单缺陷修复 | ❌ 不需要，直接修 |

主流程通过 **planning-with-files + 批次拆分** 解决上下文爆炸问题，Superpowers 在批次内部 Claude Code 修 bug 时可选择性调用。

---

## 常见问题处理

| 问题 | 处理方式 |
|------|---------|
| subagent 失败 | 检查失败原因，更新 prompt 重新 spawn |
| 修复结果不符合预期 | 在 findings.md 记录，单独手动修 |
| 批次内问题重复 | 合并到下一批次重修 |
| 上下文仍然超载 | 减少每批问题数，拆更多批次 |

---

## 适用场景

**适合：**
- 大量代码缺陷需要批量修复
- 每个缺陷有明确位置和修复方案
- 缺陷之间相对独立

**不适合：**
- 单一复杂系统设计（用方案设计流程）
- 跨多个仓库的大规模重构
- 需要频繁用户确认的决策类任务