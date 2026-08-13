# ADR-0011：CifangQuant 作为 ETF 主 Provider（选型与契约第一阶段）

- Status：Proposed
- Date：2026-08-01
- Owners：M1 ETF 数据接入

## Context

ADR-0003 冻结了 Adapter 边界、领域端口与三段式原始证据模型，并把真实
Provider 选型延后到 O-1 业务确认之后；ADR-0004 / ADR-0005 进一步冻结了
Phase 1 仅服务 SSE / SZSE 场内 ETF、`adjustment=none` 与版本化日历的契约。
`fixture_dev` 是当前唯一默认启用的 Provider。

`docs/archive/2026-08-13-plan-cleanup/plan.md` 与
`docs/implementation/DATA-SOURCE-MIGRATION-MATRIX.md`
均把 `cifang` 列为“经归档观察到的候选 ETF 主数据来源”，但 ADR-0003 明确
要求：在用户完成合同、再分发、限频、历史回填起点与收盘 cutoff 确认前，
不得宣告 Provider 已选定，更不得直接沿用归档实现的默认 `qfq` 复权。
M0 已冻结首期 `adjustment=none`，旧实现的默认 `qfq` 与之冲突。

本 ADR 是 CifangQuant 接入路径上的**第一阶段**：冻结对官方 CifangQuant
API 的可核验事实（端点、鉴权、参数、字段、限频、错误分类），明确把
`cifangquant` 作为 Provider key 的候选命名；同时显式标记仍未解决的法律
/合同、限频、历史回填起点与收盘 cutoff 项，以保持 M0 门禁不放松。

## Decision

### 1. Provider key 与 Adapter 落点

1. Provider key 候选命名为 **`cifangquant`**（与归档观测的 `cifang`
   key 区分；Phase 1 接入落地后由 Provider Registry 在替换迁移中处理
   历史 `cifang` 调用点；本阶段不修改调用方）。
2. Adapter 代码固定在
   `apps/pipeline/src/invest_pipeline/adapters/cifang/` 子包；领域层
   （`packages/domain`）不得引入 CifangQuant SDK、HTTP 客户端、URL 或
   字段名（ADR-0003 §3 / ADR-0009 §4）。
3. Phase 1 Adapter 实现仅暴露端口 `EtfMarketDataProvider` 要求的
   `provider_key` / `fetch_instruments` / `fetch_daily_bars` 三个成员；
   真实网络调用必须先完成 §4 的全部确认项。

### 2. 已核验的官方 API 事实（Phase 1 接入依据）

下列事实来自官方文档 / 控制台，已核验字段含义与边界；本阶段不得把它们
重新解读或扩大。

| 项 | 核验值 |
|---|---|
| Base URL 模板 | `https://www.cifangquant.com/api`（端点必须挂在该模板下；HTTPS 强制） |
| 鉴权 | `x-api-key: <token>` 请求头；token 由用户在 CifangQuant 控制台生成，仓库不得提交任何真实 token |
| ETF 主数据端点 | `GET /api/fund/list`，按控制台授权账户可访问的场内 ETF 列表返回 |
| 日行情端点 | `GET /api/fund/hist_em`，闭区间 `[start_date, end_date]`，参数包含 `symbol` / `adjust` |
| 复权参数 | `adjust=none`；M0 ADR-0005 锁死 Phase 1 写入路径只接受 `none`；任何 `qfq` / `hfq` 调用必须显式拒绝 |
| 单次请求符号上限 | 官方文档明示最多 50 个 symbol / 请求；超出必须切批并保留 `request_key` / `attempt_no` 边界 |
| 交易所映射 | Provider 返回 `SH` / `SZ`；Adapter 必须映射到领域 `Exchange.SSE` / `Exchange.SZSE`（ADR-0004 §1） |
| 成交额 / 昨收 | 官方响应可能不含 `amount` / `prev_close`；写入路径必须把这两列视为可空（ADR-0005 §6），不得合成 |

### 3. 配置与脱敏

1. `CifangSettings`（位于 `adapters/cifang/config.py`）使用
   `pydantic_settings.BaseSettings`，`enabled` 默认 **`False`**，必须显式
   打开才能发起真实请求；环境变量命名空间
   `INVEST_PIPELINE_CIFANG_*`。
2. `adjustment` 字段**锁死为字面量 `"none"`**；任何环境变量传入的其它值
   必须在 settings 校验阶段被拒绝，不允许进入请求构造。
3. `api_key` 通过 `pydantic.SecretStr` 承载；`CifangSettings.__repr__`
   /`__str__` 必须把 `api_key` 渲染为 `***`，禁止以任何形式进入日志、
   异常消息、fixture、commit 或回放样例（ADR-0010 §5 / §6）。
4. Adapter 不得在 `request_params` 中写入 token；Provider 请求 ID 仅当
   供应商在响应中给出时方可写入 `ProviderBatch.request_id`。

### 4. 仍未解决、必须保留为阻塞项

下列项目 O-1 未完成前不得解除 `enabled=False` 默认值，亦不得变更
Phase 1 接入路径：

| 项 | 阻塞 |
|---|---|
| 法律 / 合同 / 再分发边界 | 选型 |
| 鉴权 `x-api-key` 的生产轮换与 Secret 注入方式（与 ADR-0010 §5 对齐） | 选型 + 运维 |
| 限频 / 并发 / 5xx 重试预算的官方数值 | SLA |
| `adjustment=none` 的官方语义证据（确认“未复权”就是 M0 §4 含义） | 数据契约 |
| `configured_backfill_start` 与 ETF 历史起点（O-3） | 回填范围 |
| 收盘 cutoff（O-4） | 调度 |
| 候选池阈值（O-5） | 业务算法（不在本 ADR 范围） |

### 5. Phase 1 接入阶段切分（本 ADR 仅冻结第一段）

1. **第一段（本 ADR + 本次增量）**：
   - ADR-0011 Status 为 Proposed；
   - `CifangSettings` 完成（脱敏、默认禁用、`adjustment` 锁死）；
   - Adapter 仅暴露端口形状，两个 `fetch_*` 方法直接
     抛 `ProviderAdapterNotImplementedError`，错误消息指向本 ADR。
2. **第二段（O-1 / O-3 / O-4 解锁后）**：
   - HTTP client（`httpx`，依赖变更需另起 PR；ADR-0009 §4）；
   - mapper（`/api/fund/list`、`/api/fund/hist_em` → 领域对象）；
   - 限流、退避、错误分类；
   - 真实冒烟测试与可重放 fixture。

## Consequences

- 本 ADR 不解除 M0 门禁；`fixture_dev` 仍是默认 Provider；任何把
  `CifangSettings.enabled` 改为 `True` 的改动都必须由新的 ADR / PR 记录
  并附带 §4 的解决证据。
- 后续 Phase 1 第二段若与本 ADR §2 任一核验事实冲突，必须先修订本 ADR
  再继续实现。
- 第一段占位实现不改 `apps/pipeline/src/invest_pipeline/adapters/__init__.py`
  的对外符号表；后续替换 `fixture_dev` 默认值时另起迁移。

## Alternatives

- **直接接入并启用 CifangQuant：Rejected。** O-1 / 合同 / 限频 / 复权语义
  / 历史起点 / cutoff 均未确认，且与 M0 `adjustment=none` 冻结冲突。
- **继续等待其它真实源（AkShare / 商业终端）确认：Deferred。** 本 ADR 不
  阻塞其它候选的独立 ADR；选型最终切换必须重新走 ADR 流程。
- **把 `cifangquant` 与归档 `cifang` 直接视为同一 key：Rejected。** 归档
  默认 `qfq` 与 M0 §4 冲突，无法在不阅读归档实现的前提下保证契约一致。
