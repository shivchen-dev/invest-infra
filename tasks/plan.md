# Implementation Plan: StrategyVersion 发布接口瘦身

## 目标

在不降低治理强度的前提下，删除操作者重复提供的 StrategyVersion 发布参数。

目标接口：

```bash
python -m invest_pipeline.strategy_version_cli publish \
  --decision-json-file <local-regular-file> \
  --decision-ref <immutable-evidence-ref> \
  --expected-decision-sha256 <trusted-agentoa-sha256>
```

`activate` 与 `get-active` 保持独立，不新增发布激活组合操作。

## 范围

### 修改

- 批准人白名单从 CLI 参数迁移到 pipeline 配置。
- 治理模块从 Decision、Draft 和 Audit 自动推导发布身份。
- `publish` 必填参数由 9 个降为 3 个。
- 更新现有候选策略操作文档。

### 不修改

- Domain 对象、数据库 schema、Migration、Repository 和 Unit-of-Work。
- Draft → RAA pass Audit → CIA approve → Version 证据链。
- 独立 `activate`、`get-active` 及唯一 active 约束。
- AgentOA 客户端、凭证和证据下载流程。
- HTTP 接口、批量发布、状态机、调度器和兼容层。
- 无关测试体系和历史验证文档。

## 保留的不变量

1. 决策输入必须是普通文件，拒绝符号链接。
2. 决策 JSON 必须严格解析且为 `approve`。
3. Draft、Audit、Decision 的 ID 与 artifact hash 必须一致。
4. Audit verdict 必须为 `pass`。
5. 批准人必须存在于服务配置白名单；空白名单默认拒绝。
6. Decision 文件 SHA-256 由 CLI 对实际字节计算，并与 AgentOA 提供的可信 SHA-256 锚点一致后保存。
7. Version 继续保存不可变 artifact、audit 与 decision 证据。
8. 幂等、冲突、唯一 active 和错误脱敏行为保持不变。

## 设计决策

- `StrategyGovernanceService` 继续作为发布规则的唯一 seam。
- `draft_id`、`audit_id` 和 `artifact_hash` 来自 Decision；strategy key 与 version 来自对应 Draft，不再让操作者重复输入。
- 批准人白名单由 pipeline settings/environment 注入，不允许发布请求覆盖。
- AgentOA 只负责把证据送到本地；业务仓库只验证本地证据及其不可变引用。
- 当前无仓库内旧 CLI 调用方；实施前再次搜索，若发现真实外部依赖则停止并重新评审。

## 实施任务

### Task 1：迁移批准人配置

**说明：** 在 pipeline settings 中加入批准人白名单，默认空集合并 fail closed。

**验收标准：**

- 合法单值或多值配置可稳定解析。
- 空值和空白 agent ID 不会产生授权。
- 配置内容不出现在日志或错误输出中。

**允许文件：**

- `apps/pipeline/src/invest_pipeline/config.py`
- `apps/pipeline/tests/unit/test_config.py`

**验证：** 聚焦配置测试、Ruff、`git diff --check`。
**依赖：** 无
**路由：** OpenCode 实现，ARC 验收

### Task 2：收敛治理模块 interface

**说明：** 删除 `expected_strategy_key`、`expected_version` 等重复输入，由治理模块根据 Decision 和持久化记录完成全部绑定校验。

**验收标准：**

- 调用者不再提供数据库可推导的身份字段。
- 非 pass、错误绑定、未授权、幂等和冲突行为保持不变。
- 发布仍只在所有校验通过后 commit。

**允许文件：**

- `apps/pipeline/src/invest_pipeline/strategy_governance.py`
- `apps/pipeline/tests/unit/test_strategy_governance.py`

**验证：** 聚焦治理测试、Ruff、`git diff --check`。
**依赖：** Task 1
**路由：** OpenCode 实现，ARC 验收

### Task 3：收敛 publish CLI

**说明：** 保留 `publish` 命令名，只接收决策文件、不可变证据引用和 AgentOA 提供的可信 SHA-256；CLI 自动计算文件 SHA-256、执行一致性校验，并从配置加载批准人白名单。

**验收标准：**

- `publish --help` 仅显示三个发布必填参数。
- 普通文件检查、可信哈希一致性、严格 JSON 解析、哈希保存和错误脱敏保持不变。
- `activate` 与 `get-active` 的 interface 和行为不变。

**允许文件：**

- `apps/pipeline/src/invest_pipeline/strategy_version_cli.py`
- `apps/pipeline/tests/unit/test_strategy_version_cli.py`

**验证：** 聚焦 CLI 测试、Ruff、帮助文本检查。
**依赖：** Task 1、2
**路由：** OpenCode 实现，ARC 验收

### Task 4：更新现有操作文档

**说明：** 只更新现有候选策略计划中的发布命令，不新增专项验证文档。

**允许文件：**

- `docs/plan/invest-infra-candidate-strategies-mvp-plan-v1.0.md`

**验收标准：** 文档命令与 CLI `--help` 一致，历史事实不变。
**依赖：** Task 3
**路由：** ARC

## 最终验收

1. Codex 只读复核授权、证据绑定、负面路径和错误脱敏。
2. ARC 检查完整 diff，确认没有 Domain、Storage、Migration 或无关脏文件改动。
3. ARC 独立执行：

```bash
PYTHONPATH=apps/pipeline/src:packages/domain/src:packages/storage/src \
  apps/pipeline/.venv/bin/python -m pytest \
  apps/pipeline/tests/unit/test_config.py \
  apps/pipeline/tests/unit/test_strategy_governance.py \
  apps/pipeline/tests/unit/test_strategy_version_cli.py -q

uv run ruff check apps/pipeline/src apps/pipeline/tests
make arch-check
git diff --check
```

4. 使用临时 PostgreSQL 运行现有 StrategyVersion 集成测试，确认发布、幂等、冲突和唯一 active 行为未回归。

## 停止条件

- 发现真实调用方依赖旧 publish 参数。
- 必须修改 Domain、数据库、Migration 或 AgentOA 才能完成。
- 授权白名单能够被发布请求覆盖。
- 关键负面路径或 PostgreSQL 集成测试回归。
- 实施触碰当前无关脏文件。

## Definition of Done

- `publish` 必填参数由 9 个降为 3 个。
- 八条治理不变量全部保持。
- 生产代码只修改 pipeline 配置、治理和 CLI 三个模块。
- 聚焦测试、PostgreSQL 集成测试、Ruff 和架构检查通过。
- Codex 与 ARC 验收通过。
- 未自动 commit、push、部署或操作生产数据。
