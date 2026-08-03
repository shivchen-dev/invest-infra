# invest-infra Stage 4A 合并实施方案

> 文档版本：v1.0  
> 文档状态：Draft for Review  
> 制定日期：2026-08-03  
> 适用仓库：`shivchen-dev/invest-infra`  
> 当前基线：`main` / `e250051ec24d156f036b8a6bd1eb687cd99a409b`

## 1. 方案结论

本方案合并以下两份计划：

- `invest-infra-v2-stage4a-ai-research-evidence-foundation-plan.md`
- `invest-infra-ai-research-stage1-plan.md`

采用的主路线是：

> 以 Research Evidence Foundation 作为正式架构底座，以“单 ETF → Evidence Pack → JiuwenSwarm → 结构化报告”作为垂直验收切片。

第一阶段不把完整 JiuwenSwarm 运行治理作为 Evidence Foundation 的完成前置条件。先冻结确定性证据契约，再通过 Fake JiuwenSwarm E2E 和一次真实 JiuwenSwarm 手工验收验证端到端价值。

## 2. 产品定位

`invest-infra V2` 是面向个人和小型研究团队的证据驱动 AI 投资研判基础设施。

系统负责：

- 采集和标准化金融数据；
- 计算版本化、可解释的确定性因子；
- 管理输入快照、数据时间、来源、质量和 revision；
- 构建不可变 Research Evidence Pack；
- 通过受控 API/文件契约向 AI 研判团队提供研究材料；
- 保存研究运行、证据引用、报告摘要和失败信息。

JiuwenSwarm 后续负责：

- 多 Agent 任务拆解；
- 专业角色分析；
- 反方质询和风险识别；
- 形成结构化研判结果。

AI 研判结果不是订单，不直接调用券商接口，也不修改确定性 Evidence。

## 3. 总体范围

### 3.1 Stage 4A 必须交付

```text
指定 ETF / 已发布 Candidate Pool
        ↓
创建 Research Case
        ↓
读取标准化数据和输入快照
        ↓
计算最小因子集
        ↓
构建不可变 Research Evidence Pack
        ↓
PostgreSQL 原子持久化
        ↓
生成稳定 JSON 视图
        ↓
Fake JiuwenSwarm E2E / 真实 JiuwenSwarm 手工验收
        ↓
保存 Research Run 和结构化报告
        ↓
只读 API 查询
```

### 3.2 本阶段不做

- 完整 JiuwenSwarm Agent Team 运行治理；
- E2A 跨机器恢复、动态组队和批量并发；
- 新闻、政策、财报和互联网检索；
- 通用因子注册中心、Factor Store、向量数据库；
- 参数寻优、重型回测、模拟 Broker 和自动交易；
- 用户权限、多租户和新微服务；
- 独立复杂 Research Workbench；
- Web 创建或执行 Research Case。

## 4. 架构决策

### ADR-01：Evidence Foundation 是 Stage 4A 的正式完成边界

Research Case、Evidence Pack、Evidence Item 和 Factor Observation 必须成为正式领域和存储模型，而不是只存在于一次运行的 workspace 文件中。

原因：后续需要支持 revision、历史 Pack、证据引用、API 查询、Agent 重试和结果复盘。

### ADR-02：端到端 AI 验收与底座完成解耦

Fake JiuwenSwarm E2E 和真实 JiuwenSwarm 手工验收属于 Stage 4A 验证层；Evidence Foundation 不依赖外部 Swarm 在线才能完成迁移、构建和 API 验收。

### ADR-03：workspace 是运行产物，不是唯一事实源

workspace 保存请求、Evidence JSON 视图、E2A envelope、events、报告和诊断信息。数据库保存可查询的 Research Case、Evidence Pack、Evidence Item、Factor Observation 和 Research Run 索引。

workspace 丢失不能改变 Evidence Pack 的正式数据身份和 hash；API 不允许暴露任意文件路径。

### ADR-04：确定性 Evidence 与概率性 Research Result 分离

确定性域只负责事实和因子。`stance`、`confidence`、`thesis`、`risks`、`disagreements` 属于 AI Research Result，不写回 Evidence Item，也不参与 Evidence Pack 的内容 hash。

### ADR-05：AI 只读访问

JiuwenSwarm 不直连 PostgreSQL、不执行任意 SQL、不读取 Provider 凭据。Stage 4A 使用一次性 Evidence JSON 视图；后续 Stage 4C 冻结受控 Research Tool Contract。

## 5. 阶段划分

### Phase A：目标和契约冻结

交付：

- 产品目标和架构文档重基线；
- ADR-0012 或等价 ADR；
- Evidence Contract v1.0.0；
- Factor Set v1.0.0；
- Research Result Schema v1.0.0；
- E2A 文件/内容引用约定。

验收：文档目标一致，关键枚举、字段、hash 和引用规则冻结。

### Phase B：Research Domain 与 Storage

交付：

- Research Case；
- Evidence Pack；
- Evidence Item；
- Factor Observation；
- Research Run 索引；
- canonical hashing；
- Repository、Unit of Work 和 Alembic migration。

验收：migration roundtrip、唯一约束、事务回滚、hash golden tests 通过。

### Phase C：Evidence Builder 垂直切片

交付：

- 单 ETF Evidence Builder；
- 第一批确定性因子；
- freshness/quality gate；
- CLI/手工 Dagster Asset；
- `evidence.json` 稳定视图；
- Fixture ETF 完整案例。

验收：完整、partial、failed、重复执行和 revision 场景通过。

### Checkpoint 1：底座验收

- [ ] 不依赖 JiuwenSwarm 可生成并查询 Evidence Pack；
- [ ] 相同输入 hash 一致；
- [ ] revision 生成新 Pack，旧 Pack 保留；
- [ ] 缺失数据不被补全；
- [ ] 敏感信息不进入 Pack、日志和 JSON 视图。

### Phase D：Research Run 与 JiuwenSwarm 验证

交付：

- 固定 `etf_medium_term_assessment` Playbook；
- 4 个固定 Agent 角色；
- E2A 最小 client/orchestrator；
- Fake JiuwenSwarm 流式 E2E；
- 真实 JiuwenSwarm 手工验收；
- Research Result 校验和 Markdown 报告。

验收：单 ETF 能生成引用有效 Evidence ID 的报告；外部调用失败时留下可诊断运行记录，且不影响数据 Pipeline。

### Phase E：Research API、最小 Web 和阶段收口

交付：

- Research Case/Pack/Items/Factors 只读 API；
- Research Run latest/detail/list API；
- OpenAPI 契约和生成客户端；
- ETF 详情页最小只读研判面板；
- Stage 4A 验收记录；
- 文档一致性 Gate。

### Checkpoint 2：Stage 4A 验收

- [ ] Evidence Foundation DoD 全部满足；
- [ ] Fake JiuwenSwarm E2E 通过；
- [ ] 真实 JiuwenSwarm 手工验收通过；
- [ ] API/Web 不影响既有数据链路；
- [ ] 未引入回测、向量库、消息队列或新微服务。

## 6. 领域模型

### 6.1 ResearchCase

```python
@dataclass(frozen=True)
class ResearchCase:
    id: UUID
    case_key: str
    instrument_ids: tuple[UUID, ...]
    as_of_date: date
    question: str
    horizon: ResearchHorizon
    strategy_key: str | None
    strategy_version: str | None
    status: ResearchCaseStatus
    created_at: datetime
```

Stage 4A 仅支持单个 ETF；多标的比较后置。

状态：

```text
draft → evidence_building → evidence_ready
                         ↘ evidence_partial
                         ↘ failed
evidence_ready/evidence_partial → archived
```

### 6.2 ResearchEvidencePack

```python
@dataclass(frozen=True)
class ResearchEvidencePack:
    id: UUID
    research_case_id: UUID
    schema_version: str
    as_of_date: date
    input_snapshot_id: UUID | None
    candidate_pool_run_id: UUID | None
    factor_set_key: str
    factor_set_version: str
    freshness_status: EvidenceFreshness
    quality_status: EvidenceQuality
    content_hash: str
    item_count: int
    factor_count: int
    created_at: datetime
```

`created_at` 不参与 content hash。

### 6.3 EvidenceItem

```python
@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    evidence_key: str
    evidence_type: EvidenceType
    instrument_id: UUID | None
    observed_at: datetime | date
    source_kind: EvidenceSourceKind
    source_ref: str
    payload: Mapping[str, JsonValue]
    quality_status: EvidenceQuality
    content_hash: str
```

Evidence ID：

```text
evi:{pack_id}:{evidence_key}:{hash_prefix}
```

同一 Pack 内唯一、全局可引用、不包含密钥和敏感值。

### 6.4 FactorObservation

```python
@dataclass(frozen=True)
class FactorObservation:
    instrument_id: UUID
    factor_key: str
    factor_version: str
    as_of_date: date
    window: str
    value_numeric: Decimal | None
    value_text: str | None
    state: str | None
    unit: str | None
    quality_status: EvidenceQuality
    evidence_id: str
```

### 6.5 ResearchRun 与 ResearchResult

`ResearchRun` 保存一次 AI 研判的索引和生命周期，不替代 Evidence Pack：

```text
id
research_case_id
evidence_pack_id
playbook_key
playbook_version
status
workspace_path
result_hash
stance nullable
confidence nullable
error_code nullable
error_summary nullable
started_at
finished_at
created_at
```

`ResearchResult` 只保存结构化 AI 输出：

```text
stance
confidence
horizon
thesis
supporting_evidence_ids
contradicting_evidence_ids
catalysts
risks
invalidation_conditions
watch_items
unresolved_disagreements
```

ResearchResult 不修改 Evidence Pack，不参与 Evidence Pack hash。

## 7. Evidence Contract

### 7.1 状态

`EvidenceFreshness`：

```text
fresh / stale / missing / partial / failed
```

`EvidenceQuality`：

```text
complete / partial / missing / invalid / conflict
```

### 7.2 Canonical Hash

hash 输入必须满足：

- JSON key 按字典序；
- 日期采用 ISO 8601；
- 时间统一 UTC；
- Decimal 使用规范化字符串；
- UUID 使用小写标准格式；
- 列表按业务规则排序；
- 排除 `created_at`、`generated_at`、数据库 ID 等非业务值；
- 禁止使用 Python 默认 `repr()` 和不稳定二进制浮点字符串。

### 7.3 JSON 视图

```json
{
  "schema_version": "1.0.0",
  "research_case": {},
  "evidence_pack": {
    "content_hash": "...",
    "as_of_date": "2026-08-03",
    "freshness_status": "fresh",
    "quality_status": "complete"
  },
  "items": [],
  "factors": [],
  "missing_fields": [],
  "warnings": []
}
```

JSON 视图可作为 JiuwenSwarm 附件，但正式事实仍由数据库中的 Pack/Items/Factors 表示。

## 8. 第一批因子

固定：

```text
factor_set_key: etf_research_daily
factor_set_version: 1.0.0
```

因子共 10 个：

| Factor Key | 窗口 | 缺失处理 |
|---|---:|---|
| `return_20d` | 20 | 数据不足为 missing |
| `return_60d` | 60 | 数据不足为 missing |
| `return_120d` | 120 | 数据不足为 missing |
| `distance_ma20` | 20 | 数据不足为 missing |
| `distance_ma60` | 60 | 数据不足为 missing |
| `realized_volatility_20d` | 20 | 非法价格为 invalid |
| `realized_volatility_60d` | 60 | 非法价格为 invalid |
| `max_drawdown_60d` | 60 | 数据不足为 missing |
| `avg_turnover_amount_20d` | 20 | amount 缺失为 partial |
| `data_completeness_60d` | 60 | 始终返回质量比例 |

第二份计划中的流动性变化率可作为后续补充，不在首版因子契约中强行加入。

因子只描述客观状态，不输出 `buy`、`sell`、`action` 或 `recommendation`。

## 9. Quality Gate

为消除两份原计划的冲突，统一采用以下规则：

### `evidence_ready`

- Instrument 存在；
- 最新有效价格存在；
- `as_of_date` 不晚于市场日期；
- 最长窗口 120 日数据完整度满足要求；
- `data_completeness_60d >= 0.90`；
- 核心 Evidence 无 invalid；
- 所有 Factor Observation 都有 Evidence ID；
- Pack hash 可生成。

### `evidence_partial`

- 只有 60–119 个有效交易日；
- 20/60 日可计算但 120 日窗口不足；
- amount 缺失；
- Candidate Pool Context 缺失；
- 数据 stale 但仍可明确标记。

### `failed`

- Instrument 不存在；
- 无任何有效行情；
- 基础价格快照无法生成；
- Evidence 冲突或 hash 失败；
- 数据库事务失败。

缺失、过期或冲突数据不得由 LLM 补全。

## 10. 数据库设计

继续使用 `analytics` Schema，新增四张正式研究表和一张运行索引表：

```text
analytics.research_cases
analytics.research_evidence_packs
analytics.research_evidence_items
analytics.factor_observations
analytics.research_runs
```

### 10.1 关键约束

- `case_key` 唯一；
- Pack 外键指向 Research Case；
- Pack `content_hash` 为 64 位 SHA-256；
- `(research_case_id, schema_version, content_hash)` 唯一；
- `(evidence_pack_id, evidence_key)` 唯一；
- `evidence_id` 全局唯一；
- Factor Observation 对 Pack、instrument、factor、version 唯一；
- Evidence Pack 发布必须在单一 Unit of Work 中完成；
- 事务失败不允许留下已发布 Header 或孤立 Items。

### 10.2 workspace 约束

- 根目录固定；
- 运行目录使用 `run_id`；
- 禁止 `..` 路径穿越；
- API 不接受任意文件路径；
- workspace 文件丢失时 API 返回 `report_unavailable`，不伪造报告；
- Research Run 不能只凭 `workspace_path` 判定成功。

## 11. Evidence Builder

目录建议：

```text
apps/pipeline/src/invest_pipeline/research/
├── case_service.py
├── evidence_builder.py
├── factor_calculators.py
├── factor_set.py
├── quality_gate.py
├── serializers.py
├── research_run.py
└── cli.py
```

输入：

```text
research_case_id
instrument_id
as_of_date
factor_set_key
factor_set_version
```

数据只允许来自现有受控 Repository 和表：

- `core.instruments`；
- `core.daily_bars` latest revision；
- `analytics.input_snapshots`；
- `analytics.candidate_pool_runs/items`；
- `ops.pipeline_runs`；
- 既有 freshness 查询逻辑。

构建顺序：

```text
Load Case
→ Load Instrument
→ Load Bars <= as_of_date
→ Load Candidate Context
→ Evaluate Freshness
→ Calculate Factors
→ Build Items
→ Canonical Serialize
→ Hash
→ Quality Gate
→ Atomic Persist
```

相同 Case、日期、输入快照、revision、因子版本和 schema 版本重复运行时，返回同 hash Pack，不重复创建 Items/Factors。

## 12. AI 研判验证切片

### 12.1 Playbook

```text
playbook_key: etf_medium_term_assessment
playbook_version: 1.0.0
horizon: 20-60 trading days
```

允许观点：

```text
bullish
cautiously_bullish
neutral
cautiously_bearish
bearish
insufficient_evidence
```

禁止输出目标价、仓位比例、明确买卖指令和自动订单。

### 12.2 固定角色

1. Research Director：确认材料完整性、组织任务、汇总分歧；
2. Data & Factor Analyst：分析趋势、动量、风险、流动性和质量；
3. ETF & Market Analyst：解释 Candidate Pool 和市场状态，不虚构资料；
4. Risk / Red Team Analyst：反驳主观点，提出风险和失效条件。

### 12.3 结构化结果约束

- `stance` 必须在枚举内；
- `confidence` 为 0–100；
- 所有 Evidence ID 必须存在于本次 Pack；
- `risks` 非空；
- `invalidation_conditions` 非空；
- Evidence 为 partial/missing 时不得输出不受约束的高置信度；
- 解析失败、引用失效或报告缺失时 Research Run 为 failed。

## 13. E2A 最小边界

Stage 4A 只实现验证所需最小集：

- `request_id`；
- `session_id`；
- `method=chat.send`；
- `mode=swarm`；
- playbook key/version；
- Research Case/Evidence Pack 引用；
- 流式 events JSONL；
- 完成、失败、超时和中断处理。

Evidence 传输优先级：

1. 共享 workspace 经验证可用时，使用固定目录附件；
2. 不共享文件系统时，使用受控内容上传或明确的 API 适配层；
3. 禁止假设 `file:///workspace/...` 在所有部署环境可用。

暂不实现跨机器恢复、自动重新规划、动态组队、并发批量研判和通用 ACP/A2A 适配。

## 14. CLI、API 与 Web

### 14.1 CLI

```bash
make research-case-create \
  INSTRUMENT_ID=<uuid> \
  AS_OF=YYYY-MM-DD

make research-evidence-build \
  RESEARCH_CASE_ID=<uuid>

make research-run \
  RESEARCH_CASE_ID=<uuid>
```

研究运行默认关闭，手工执行时显式开启：

```text
INVEST_RESEARCH_ENABLED=false
INVEST_RESEARCH_WORKSPACE_ROOT=...
INVEST_RESEARCH_JIUWENSWARM_URL=...
INVEST_RESEARCH_TIMEOUT_SECONDS=300
```

### 14.2 只读 API

```text
GET /api/v1/research-cases/{case_id}
GET /api/v1/research-cases/{case_id}/evidence-pack
GET /api/v1/research-evidence-packs/{pack_id}/items
GET /api/v1/research-evidence-packs/{pack_id}/factors
GET /api/v1/research-runs/latest?instrument_id=<uuid>
GET /api/v1/research-runs/{run_id}
GET /api/v1/research-runs?instrument_id=<uuid>&limit=20
```

API 不在请求过程中计算因子、不访问 Provider、不生成投资结论、不提供任意 SQL，也不返回任意 workspace 文件。

### 14.3 Web

Stage 4A 只增加 ETF 详情页最小只读面板：

- 最近观点；
- 置信度；
- 数据日期；
- 核心结论摘要；
- 风险；
- 失效条件；
- 查看完整 Markdown（通过固定 run ID 受控读取）。

不建设独立 Research Workbench。

## 15. 实施任务与依赖

### Task 1：文档与契约冻结

验收：产品定位、AI 边界、Evidence Contract、Factor Set、Research Result Schema 和 E2A 传输方式完成评审。

依赖：无。

### Task 2：Domain、Hash 与状态机

验收：Research Case 状态转换、Evidence ID、canonical JSON、Decimal/日期/UUID 规范化测试通过。

依赖：Task 1。

### Task 3：Storage、Migration 与 UoW

验收：五张表、外键、唯一约束、migration roundtrip、原子发布和 rollback 测试通过。

依赖：Task 2。

### Task 4：单 ETF Evidence Builder

验收：完整、partial、failed、重复执行和 revision 场景通过；Fixture Pack 与 Golden Hash 一致。

依赖：Task 3。

### Checkpoint A：Evidence Foundation

- [ ] 不依赖 JiuwenSwarm 可完成 Case → Pack → API；
- [ ] 旧 Pack 不被 revision 覆盖；
- [ ] 缺失数据明确返回；
- [ ] 敏感信息扫描通过。

### Task 5：Research Run 与 workspace

验收：运行状态、请求、Evidence JSON、events、报告和错误摘要可保存；路径穿越测试通过。

依赖：Task 4。

### Task 6：Playbook 与 Fake JiuwenSwarm E2E

验收：Fake 流式响应可生成结构化 Result；错误、超时、无最终报告和无效 Evidence 引用均被正确处理。

依赖：Task 5。

### Task 7：真实 JiuwenSwarm 手工验收

验收：至少一个 Fixture 或真实 ETF 完成一次真实调用；报告引用有效 Evidence ID；无凭据泄漏。

依赖：Task 6；不作为 Task 4 的阻塞条件。

### Task 8：Research API、OpenAPI 与最小 Web

验收：Case/Pack/Factor/Run 查询、404、校验、错误脱敏和 Web 面板测试通过。

依赖：Task 4、Task 6。

### Task 9：文档同步与 Stage 4A 验收记录

验收：README、Architecture、OpenWiki、ADR、Domain Contract、Runbook 和验收模板一致；完整测试通过。

依赖：Task 8。

### Checkpoint B：最终交付

- [ ] Domain/Storage/Pipeline/API/Web 测试通过；
- [ ] Fake E2E 通过；
- [ ] 真实 JiuwenSwarm 手工验收通过；
- [ ] 文档一致性 Gate 通过；
- [ ] 既有数据 Pipeline 无回归。

## 16. 测试计划

### Domain

- 状态机；
- Evidence ID 稳定性和唯一性；
- canonical hash；
- 每个因子正常、窗口不足、非法价格和缺失字段；
- 不使用未来数据。

### Storage/PostgreSQL

- 五张表创建；
- FK、CHECK、JSONB、NUMERIC 和唯一约束；
- migration upgrade/downgrade；
- 单事务发布；
- rollback 无孤立 Header/Item；
- 重复 hash 幂等。

### Pipeline

- Fixture 完整 Pack；
- 60–119 日 partial；
- 无行情 failed；
- Candidate Pool 或 amount 缺失；
- revision 后 hash 变化；
- Provider Key、token、原始响应不出现在产物中。

### AI/E2A

- Envelope 构造；
- 流式事件解析；
- Fake 成功/失败/超时/中断；
- 结构化结果 schema；
- Evidence ID 引用校验；
- partial 数据限制 confidence。

### API/Web

- Case/Pack/Items/Factors/Run 查询；
- latest/list/detail；
- UUID、limit、404 和数据库异常；
- workspace 不存在；
- success/failed/insufficient evidence 页面状态。

### E2E

```text
Fixture PostgreSQL
→ Research Case
→ Evidence Pack
→ Fake JiuwenSwarm
→ Research Run succeeded
→ API latest
→ 验证报告摘要和 Evidence 引用
```

真实 JiuwenSwarm 只做手工验收，不进入 CI。

## 17. Definition of Done

### 文档与契约

- [ ] README 明确 AI 投资研判基础设施定位；
- [ ] ADR 明确 Evidence-first、AI 只读和不自动交易；
- [ ] Evidence Contract v1.0.0 冻结；
- [ ] Factor Set v1.0.0 冻结；
- [ ] Research Result Schema v1.0.0 冻结；
- [ ] OpenWiki 和文档一致性 Gate 通过。

### Evidence Foundation

- [ ] Research Case、Pack、Item、Factor Observation 完成；
- [ ] 五张表和 Repository 完成；
- [ ] canonical hashing 完成；
- [ ] 完整/partial/failed 状态正确；
- [ ] 相同输入幂等；
- [ ] revision 产生新 Pack，旧 Pack 保留；
- [ ] 无敏感数据泄漏。

### AI 验证

- [ ] 一个 Playbook 版本化；
- [ ] 四个固定角色可由 Fake Swarm 验证；
- [ ] 结构化 Result 可校验；
- [ ] Markdown 报告可生成；
- [ ] 引用的 Evidence ID 全部存在；
- [ ] Fake E2E 通过；
- [ ] 真实 JiuwenSwarm 手工验收通过。

### 产品查询

- [ ] Research API 完成；
- [ ] Research Run latest/detail/list 完成；
- [ ] Web 最小面板完成或经评审明确延期；
- [ ] 现有 Pipeline/API/Web 测试无回归。

## 18. 风险与控制

| 风险 | 控制 |
|---|---|
| Stage 4A 过重 | 先完成单 ETF 垂直切片；暂不做通用平台和外部数据 |
| AI 依赖阻塞底座 | Fake Swarm 与 Evidence Foundation 解耦，真实调用仅为验证门禁 |
| workspace 成为隐性数据库 | DB 保存正式 Evidence；workspace 只保存运行产物 |
| 文件引用跨环境失效 | 明确共享目录、上传或 API 三种适配模式，不硬编码 file URI 假设 |
| Evidence ID 漂移 | Pack-scoped ID + canonical hash + Golden Case |
| 因子变成机械信号 | 因子层禁止 action/recommendation，AI Result 单独建模 |
| partial 数据诱导高置信度 | Result 校验限制 confidence，并强制输出数据限制 |
| Provider 凭据泄漏 | 白名单序列化、日志脱敏和敏感信息扫描 |
| revision 覆盖历史 | Pack hash 唯一，旧 Pack 保留，latest 仅是查询视图 |
| E2A 失败影响日常数据 | 研究运行独立开关、独立错误状态和手工触发，不加入每日硬依赖 |

## 19. Stage 4B 入口条件

进入下一阶段前必须满足：

- Evidence Contract v1.0.0 稳定；
- 第一批因子公式和单位稳定；
- 至少一个真实 Provider Evidence Pack 通过验收；
- 同日重跑无错误 revision 增长；
- 真实数据下无凭据泄漏；
- Research Result 的证据引用可验证；
- 文档和实现无目标冲突。

Stage 4B 再决定是否增加 ETF Research Profile、市场环境、外部事件证据和更多 Playbook。

