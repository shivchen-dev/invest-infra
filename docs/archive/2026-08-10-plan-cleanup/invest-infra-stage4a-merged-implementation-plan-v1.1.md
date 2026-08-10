# invest-infra Stage 4A 合并实施方案 v1.1

> 文档版本：v1.1  
> 文档状态：Draft for Review  
> 修订日期：2026-08-03  
> 适用仓库：`shivchen-dev/invest-infra`  
> 当前基线：`main` / `e250051ec24d156f036b8a6bd1eb687cd99a409b`  
> 目标定位：**证据驱动的 AI 投资研判系统**  
> 第一阶段名称：**Stage 4A — Lightweight Evidence & AI Research Slice**

---

## 0. v1.1 修订摘要

相对 v1.0，本版本作出以下关键调整：

1. **E2A 治理归属 invest-infra**
   - 不依赖 OpenClaw Skill；
   - `invest-infra` 自身负责 E2A Envelope、request/session、流式事件、超时、重试、中断、workspace 和结果收口；
   - 第一阶段继续复用现有 Pipeline 运行单元，不新增微服务。

2. **第一阶段进一步轻量化**
   - 正式研究表由五张缩减为两张；
   - 复用现有 `ops.pipeline_runs` 管理运行生命周期；
   - 不在首阶段建立独立 Research Case 状态机；
   - 不拆分 Evidence Items 和 Factor Observations 为独立表；
   - Evidence Pack 使用规范化 JSONB 保存。

3. **修正 Evidence ID 与 Hash 设计**
   - Pack Hash 不包含随机数据库 ID、Evidence ID、创建时间和 workspace 路径；
   - Evidence ID 在 Pack Hash 计算完成后生成；
   - 消除 Pack Hash 与 Evidence ID 的循环依赖。

4. **降低数据窗口要求**
   - 第一阶段最长窗口由 120 日降为 60 个交易日；
   - 首批因子由 10 个收敛为 8 个；
   - 增加历史行情准备任务；
   - 120/250 日因子移至 Stage 4B。

5. **缩减产品接口**
   - 第一阶段只提供 3 个只读 API；
   - Web 研判面板不作为 Stage 4A 完成门禁；
   - 先验证 Evidence 和 AI 研判质量，再扩展交互界面。

6. **收窄研判范围**
   - 第一阶段不是完整 ETF 基本面研判；
   - 正式命名为 **ETF 市场状态与风险研判**；
   - 不输出产业、政策、估值和基金结构方面的无证据结论。

7. **补齐五项实施契约**
   - 固定 Stage 4A 的 E2A 最小能力边界；
   - 明确 Research Result 外键和事务收口顺序；
   - 固定 `ops.pipeline_runs` 的幂等键映射；
   - 明确 Pack Hash 的排除字段和 Evidence ID 生成顺序；
   - 固定 60 日因子的样本窗口定义。

---

# 1. 方案结论

Stage 4A 的目标不是建设通用研究平台，也不是一次性完成全部 AI Agent 基础设施。

本阶段只交付一个轻量、可运行的垂直切片：

```text
单个 ETF
→ 现有标准化数据
→ 8 个确定性因子
→ 不可变 Evidence Pack
→ invest-infra 内置 E2A 治理
→ JiuwenSwarm 四角色研判
→ 结构化 Research Result
→ Markdown 报告
→ 最小只读 API
```

核心验收不是新增多少表和页面，而是：

> 同一份可信证据能否被 JiuwenSwarm 团队共同使用，并形成引用有效 Evidence ID、包含反方意见和失效条件的可追溯研判结果。

---

# 2. 产品定位

`invest-infra V2` 是面向个人和小型研究团队的证据驱动 AI 投资研判基础设施。

系统负责：

- 采集和标准化金融数据；
- 管理数据来源、时间、revision 和质量；
- 计算确定性、可解释的研究因子；
- 构建不可变 Research Evidence Pack；
- 在系统内部管理 E2A 研判请求；
- 调度 JiuwenSwarm 多 Agent 团队；
- 保存结构化研判结果、证据引用和运行诊断信息；
- 通过只读 API 提供研究结果。

JiuwenSwarm 负责：

- 任务拆解；
- 多角色并行分析；
- 反方质询；
- 风险识别；
- 综合形成研判结论。

系统当前不以以下能力为目标：

- 重型回测；
- 参数寻优；
- 自动交易；
- 模拟 Broker；
- 高频和分钟级撮合；
- 通用 Factor Store；
- 通用 Agent 平台；
- 向量数据库和大型知识图谱。

AI 研判结果不是订单，不直接调用券商接口，也不修改确定性 Evidence。

---

# 3. 当前开发基线

当前仓库已经具备：

```text
Provider 三层证据模型
ETF 主数据
ETF 日行情及 revision
Input Snapshot
Candidate Pool MVP
Pipeline Run 审计
数据新鲜度 API
Candidate Pool Diff
Dagster 日任务、补跑和幂等控制
FastAPI 只读 API
React 数据工作台
PostgreSQL E2E 与 OpenAPI Contract
```

当前主要缺口：

- 顶层文档仍以 `greenfield v2 starter` 和普通数据工作台为主要定位；
- `analytics` 仍被描述为包含回测结果；
- Fixture 历史行情不足以支持 60 日研究窗口；
- 真实 Provider 验收和 Stage 2 影子运行仍需并行推进；
- 尚无正式 Evidence Pack；
- 尚无 invest-infra 内置 E2A 研判链路；
- 尚无 AI Research Result。

因此建议两条线并行：

```text
开发线：Stage 4A Evidence + 内置 E2A + AI 垂直切片
运行线：真实 Provider 验收 + Stage 2 影子运行
```

真实验收未完成前，可以推进 Fixture 开发，但不得宣布 AI 研判进入生产状态。

---

# 4. 后续总体阶段

| 阶段 | 名称 | 核心目标 |
|---|---|---|
| Stage 4A | Lightweight Evidence & AI Research Slice | 单 ETF、基础因子、Evidence、内置 E2A、JiuwenSwarm 最小研判 |
| Stage 4B | Research Context Expansion | ETF 规模、份额、指数、折溢价、行业暴露、市场环境和外部事件 |
| Stage 4C | Research Team & E2A Governance Enhancement | 多轮会话、恢复、批量研判、更多 Playbook、GPT 独立验收 |
| Stage 4D | Research Workbench | Research Case、Agent 分歧、证据和报告工作台 |
| Stage 4E | Quality & Operations | 5/10/20 日后验、置信度校准、日报和通知 |

Stage 4A 实现 **最小完整 E2A 治理**；Stage 4C 再增强为多轮、批量和复杂恢复能力。

---

# 5. Stage 4A 范围

## 5.1 必须交付

```text
目标文档重基线
历史行情准备
Evidence Contract v1.0.0
Factor Set v1.0.0
单 ETF Evidence Pack
Canonical Hash
invest-infra 内置 E2A Client/Governor
固定 Playbook
四角色 JiuwenSwarm 团队
Fake Swarm E2E
真实 JiuwenSwarm 手工验收
Research Result 持久化
3 个只读 API
```

## 5.2 明确不做

- 120/250 日因子；
- ETF 规模、份额、跟踪误差和成分暴露；
- 新闻、政策、财报和互联网检索；
- 通用 Factor Store；
- 独立 Research Case 生命周期；
- 多标的比较；
- 批量并发研判；
- 动态 Agent 组队；
- 跨机器断点恢复；
- 通用 ACP/A2A 平台；
- Web 创建和执行研判；
- 完整 Research Workbench；
- 回测、参数优化和自动交易；
- 新微服务、Redis、Kafka、Celery 和向量数据库。

---

# 6. 核心架构决策

## ADR-01：invest-infra 自主管理 E2A

E2A 治理是投研系统自身能力，不依赖 OpenClaw Skill。

Stage 4A 由以下目录承担：

```text
apps/pipeline/src/invest_pipeline/research/
├── evidence_builder.py
├── factor_calculators.py
├── factor_set.py
├── canonical.py
├── playbook.py
├── result_schema.py
├── workspace.py
├── e2a_protocol.py
├── e2a_client.py
├── e2a_governor.py
├── orchestrator.py
└── cli.py
```

不新增网络服务，继续使用现有 Pipeline Python 运行环境。

后续只有在 AI 研究任务产生独立扩缩容、权限和发布周期后，才评估拆出 `apps/research`。

## ADR-02：运行生命周期复用 `ops.pipeline_runs`

不新增 `analytics.research_runs`。

AI 研判运行使用：

```text
job_key = ai_investment_research
partition_key = <instrument_id>:<as_of_date>:<playbook_version>
```

复用现有能力：

- running/succeeded/failed/cancelled；
- 幂等和重复运行保护；
- error code/summary；
- started/finished time；
- API 审计基础。

业务研判结果单独保存到：

```text
analytics.research_results
```

## ADR-03：第一阶段只新增两张表

```text
analytics.research_evidence_packs
analytics.research_results
```

不新增：

```text
research_cases
research_evidence_items
factor_observations
research_runs
```

需要跨 Pack 搜索 Evidence、查询因子历史或支持多轮 Case 后，再拆表。

## ADR-04：Evidence Pack 使用 JSONB

正式 Evidence Pack 保存在 PostgreSQL JSONB 中。

数据库保存：

- Instrument；
- as_of_date；
- schema/factor version；
-来源快照引用；
- freshness/quality；
- content hash；
-规范化 payload。

Workspace 保存：

- request；
- Evidence JSON 视图；
- E2A Envelope；
- events；
-报告；
-运行诊断。

数据库是正式事实源，Workspace 是运行产物。

## ADR-05：确定性 Evidence 与概率性结果分离

Evidence Pack 只包含：

- 标准数据；
- 确定性因子；
-质量状态；
-来源引用；
-缺失和告警。

Research Result 才包含：

- stance；
- confidence；
- thesis；
- supporting/contradicting evidence；
- risks；
- invalidation conditions；
- disagreements。

AI Result 不参与 Evidence Pack Hash，也不修改 Evidence。

## ADR-06：Stage 4A 只实现最小 E2A 治理

Stage 4A 必须支持：

- 单次 `request/session`；
- `chat.send`；
- `mode=swarm`；
- 流式事件接收并写入 `events.jsonl`；
- 成功、失败、连接超时和总体超时；
- 最多 2 次“尚未收到服务端确认前”的连接重试；
- Research Result Schema 校验；
- 失败信息脱敏和 Pipeline Run 状态收口。

Stage 4A 暂不支持：

- 断点恢复；
- Session 续接和多轮对话；
- 动态 Agent Team；
- 批量并发研判；
- 自动重规划；
- 跨机器 workspace；
- 复杂重试框架；
- 通用 ACP/A2A 桥接。

收到有效业务事件后，不自动新建 request 重跑，避免重复研判。无法继续时标记为 `failed` 或 `cancelled`，由用户显式重新执行。

## ADR-07：Research Result 与 Pipeline Run 原子收口

`research_results` 必须建立以下外键：

```text
pipeline_run_id  FK → ops.pipeline_runs.id
evidence_pack_id FK → analytics.research_evidence_packs.id
instrument_id    FK → core.instruments.id
```

推荐事务顺序：

```text
创建 Pipeline Run: running
    ↓
构建或读取 Evidence Pack
    ↓
执行 E2A
    ↓
校验 Research Result
    ↓
写入 research_results
    ↓
提交 Research Result
    ↓
Pipeline Run → succeeded
```

E2A、Result 校验或 Result 写入失败时，Pipeline Run 必须收口为 `failed`、`cancelled` 或 `partial`。禁止出现 Pipeline Run 为 `succeeded` 但不存在对应 Research Result 的状态。

## ADR-08：固定 Research Run 幂等键

Stage 4A 统一使用：

```text
job_key = ai_investment_research

partition_key =
{instrument_id}:{as_of_date}:{playbook_version}:{evidence_hash}
```

完整业务幂等键为：

```text
research:{instrument_id}:{as_of_date}:{playbook_version}:{evidence_hash}
```

规则：

- `queued`、`running`、`succeeded`：阻止相同键重复启动；
- `failed`、`cancelled`、`partial`：允许创建新的 Pipeline Run；
- 相同 Evidence Hash 不重复写入 Research Result；
- Evidence Hash 变化时允许产生新的研判结果。

`partition_key` 使用完整字符串，不使用随机 request/session ID。实现时必须验证其长度和 API 序列化行为符合现有 Pipeline Run 约束。

---

# 7. 文档重基线

第一项提交先修改文档，不先写运行代码。

## 7.1 新增

```text
docs/product/AI-INVESTMENT-RESEARCH-SYSTEM.md
docs/adr/0012-evidence-driven-ai-investment-research.md
docs/domain/research-evidence-contract.md
docs/validation/stage4a-ai-research-acceptance.md
```

## 7.2 修改

```text
README.md
docs/ARCHITECTURE.md
openwiki/quickstart.md
openwiki/architecture/overview.md
openwiki/domain/overview.md
openwiki/storage/overview.md
openwiki/pipeline/overview.md
openwiki/api/overview.md
openwiki/testing-and-ops/overview.md
```

## 7.3 顶层定位

README 建议使用：

> `invest-infra V2` 是面向个人和小型研究团队的证据驱动 AI 投资研判基础设施。系统负责采集和标准化金融数据、计算可解释因子、构建不可变 Research Evidence Pack，并通过内置 E2A 治理能力调度 JiuwenSwarm 投资研判团队，形成可追溯、可质询、可复核的研判结果。

## 7.4 架构铁律

增加：

1. AI Agent 不直连 PostgreSQL；
2. Agent 不读取 Provider 凭据；
3. 关键事实必须引用 Evidence ID；
4. AI 不修改历史数据、因子和 Evidence；
5. 缺失数据不得由 LLM 猜测补全；
6. AI 结果不直接生成订单；
7. E2A 运行失败不能影响每日数据 Pipeline；
8. E2A request/session/workspace 由 invest-infra 管理。

## 7.5 轻量一致性 Gate

只检查：

- 必要文档存在；
- README 包含“AI 投资研判”；
- Architecture 包含 Evidence 和 E2A 边界；
- ADR-0012 状态为 Accepted；
- 顶层文档不再将重型回测列为当前建设目标。

不建设语义分析型文档工具。

---

# 8. 历史行情准备

当前 Fixture 不足以计算 20/60 日因子。

Stage 4A 增加 Task 0：

## 8.1 Fixture 扩充

为一个演示 ETF 提供至少 65 个连续交易日的 OHLCV/amount Fixture。

建议新增：

```text
tests/fixtures/research/etf_daily_bars_65d.json
```

不要求扩展所有 12 个 Fixture ETF。

## 8.2 真实数据补齐

增加手工命令：

```bash
make research-history-bootstrap \
  INSTRUMENT_ID=<uuid> \
  START_DATE=YYYY-MM-DD \
  END_DATE=YYYY-MM-DD
```

限制：

- 只允许明确 Instrument；
- 只写标准 Daily Bar 链路；
- 沿用 revision 规则；
- 不加入每日自动 Schedule；
- Provider 凭据继续通过环境变量注入。

---

# 9. Evidence Pack Contract v1.0.0

## 9.1 顶层结构

```json
{
  "schema_version": "1.0.0",
  "factor_set": {
    "key": "etf_market_state_daily",
    "version": "1.0.0"
  },
  "case": {
    "case_id": "...",
    "instrument_id": "...",
    "as_of_date": "2026-08-03",
    "question": "评估该 ETF 当前市场状态与未来 20-60 个交易日主要风险",
    "horizon": "20-60d"
  },
  "instrument": {},
  "candidate_context": {},
  "market_snapshot": {},
  "factors": [],
  "data_quality": {},
  "missing_fields": [],
  "warnings": [],
  "source_refs": []
}
```

Research Case 第一阶段只是 Pack 内的请求对象，不建立独立状态机和表。

## 9.2 Freshness

沿用现有语义：

```text
fresh / stale / missing / partial / failed
```

## 9.3 Quality

```text
complete / partial / missing / invalid / conflict
```

---

# 10. Canonical Hash 与 Evidence ID

## 10.1 Item Hash

每个 Evidence Item 先对以下内容计算 SHA-256：

```text
evidence_key
evidence_type
instrument_id
observed_date/time
source_kind
source_ref
payload
quality_status
```

不包含：

```text
database id
pack id
evidence id
created_at
generated_at
workspace path
```

## 10.2 Pack Hash

Pack Hash 对规范化 Pack 内容计算，不包含：

```text
pack_id
case_id
evidence_id
created_at
generated_at
workspace_path
pipeline_run_id
E2A request/session id
```

规范化要求：

- JSON key 排序；
- 日期 ISO 8601；
- 时间 UTC；
- Decimal 使用字符串；
- UUID 使用小写标准格式；
-列表按明确业务规则排序；
-禁止 Python 默认 `repr()`；
-禁止不稳定二进制浮点文本。

## 10.3 Evidence ID

Pack Hash 计算完成后生成：

```text
evi:{pack_hash前12位}:{evidence_key}:{item_hash前12位}
```

示例：

```text
evi:a81bf4737e91:factor.return_20d:2e04c1b6fc87
```

这样相同输入可得到稳定 Pack Hash 和稳定 Evidence ID。

完整生成顺序固定为：

```text
Item 业务内容 → item_hash
Pack 规范化业务内容 → pack_hash
pack_hash + evidence_key + item_hash → evidence_id
```

`case_id` 如果出现在 JSON 视图中，仅作为上下文展示字段，不参与 Pack Hash。它不得使用随机运行 ID 作为事实 hash 的输入。

---

# 11. 第一批因子

固定：

```text
factor_set_key: etf_market_state_daily
factor_set_version: 1.0.0
```

只实现 8 个因子：

| Factor Key | 窗口 | 说明 |
|---|---:|---|
| `return_20d` | 20 | 近 20 个交易日收益 |
| `return_60d` | 60 | 近 60 个交易日收益 |
| `distance_ma20` | 20 | 收盘价相对 MA20 偏离 |
| `distance_ma60` | 60 | 收盘价相对 MA60 偏离 |
| `realized_volatility_20d` | 20 | 近 20 日日收益年化波动 |
| `max_drawdown_60d` | 60 | 近 60 日最大回撤 |
| `avg_turnover_amount_20d` | 20 | 近 20 日平均成交额 |
| `data_completeness_60d` | 60 | 近 60 日有效数据覆盖率 |

因子只描述状态，不输出：

```text
buy
sell
position
target_price
recommendation
```

120 日收益、60 日波动和流动性变化率后移至 Stage 4B。

## 11.1 因子样本窗口契约

为避免“60 日”在不同实现中的口径漂移，固定如下：

| 因子类型 | 样本要求 | 计算定义 |
|---|---:|---|
| `return_Nd` | N+1 个有效收盘价 | `close[t] / close[t-N] - 1` |
| `distance_maN` | N 个有效收盘价 | `close[t] / MA_N - 1` |
| `realized_volatility_Nd` | N+1 个有效收盘价 | N 个日收益标准差 × √252 |
| `max_drawdown_Nd` | N 个有效收盘价 | 窗口内基于累计峰值的最大回撤 |
| `avg_turnover_amount_20d` | 20 个有效 amount | 20 日算术平均 |
| `data_completeness_60d` | 60 个目标交易日 | 有效行情数 / 目标交易日数 |

因此，`return_60d` 至少需要 61 个有效收盘价；MA60、波动率和回撤按各自定义计算。65 个交易日 Fixture 作为 Stage 4A 的最小安全余量。

---

# 12. Quality Gate

## `complete`

- Instrument 存在；
- 最新有效价格存在；
- 至少 60 个有效交易日；
- `data_completeness_60d >= 0.90`；
- 核心价格和因子无 invalid/conflict；
- Evidence ID 和 Pack Hash 可生成。

## `partial`

- 有 20–59 个有效交易日；
- amount 缺失；
- Candidate Pool Context 缺失；
- 数据 stale；
- 部分因子无法计算。

## `failed`

- Instrument 不存在；
- 无有效行情；
- 基础价格非法；
- Evidence 冲突；
- Hash 失败；
- 数据库事务失败。

数据不足时，Pack 可以保存为 partial，但 AI 研判必须受置信度约束。

---

# 13. 数据库设计

## 13.1 `analytics.research_evidence_packs`

```text
id UUID PRIMARY KEY
instrument_id UUID NOT NULL
as_of_date DATE NOT NULL
schema_version VARCHAR NOT NULL
factor_set_key VARCHAR NOT NULL
factor_set_version VARCHAR NOT NULL
input_snapshot_id UUID NULL
candidate_pool_run_id UUID NULL
freshness_status VARCHAR NOT NULL
quality_status VARCHAR NOT NULL
content_hash CHAR(64) NOT NULL
payload JSONB NOT NULL
created_at TIMESTAMPTZ NOT NULL
```

关键约束：

```text
length(content_hash) = 64
UNIQUE(instrument_id, as_of_date, schema_version, factor_set_version, content_hash)
payload 必须为 JSON object
```

## 13.2 `analytics.research_results`

```text
id UUID PRIMARY KEY
pipeline_run_id UUID NOT NULL
evidence_pack_id UUID NOT NULL
instrument_id UUID NOT NULL
as_of_date DATE NOT NULL
playbook_key VARCHAR NOT NULL
playbook_version VARCHAR NOT NULL
e2a_request_id VARCHAR NOT NULL
e2a_session_id VARCHAR NOT NULL
stance VARCHAR NOT NULL
confidence INTEGER NOT NULL
result_hash CHAR(64) NOT NULL
result_json JSONB NOT NULL
report_path VARCHAR NULL
created_at TIMESTAMPTZ NOT NULL
```

关键约束：

```text
confidence BETWEEN 0 AND 100
length(result_hash) = 64
UNIQUE(pipeline_run_id)
FK → ops.pipeline_runs
FK → analytics.research_evidence_packs
FK → core.instruments
```

Pipeline Run 状态和错误不在此表重复保存。

---

# 14. E2A 内置治理

## 14.1 责任边界

`invest-infra` 负责：

- 构造 `E2AEnvelope`；
-生成 `request_id`、`session_id`、`correlation_id`；
-选择 `mode`；
-连接 JiuwenSwarm Gateway；
-接收流式 `E2AResponse`；
-事件持久化；
-超时和重试；
-中断和取消；
-结果收口；
-workspace 管理；
-错误脱敏；
-更新 `ops.pipeline_runs`；
-写入 `analytics.research_results`。

JiuwenSwarm 负责：

- Leader 分解任务；
-Agent 团队执行；
-反方质询；
-生成结构化结果。

## 14.2 Stage 4A 支持范围

必须支持：

```text
request create
session create
chat.send
mode=swarm
stream receive
final success
explicit failure
connect timeout
overall timeout
safe retry
cancel
events.jsonl
result schema validation
workspace cleanup policy
```

暂不支持：

```text
跨机器断点恢复
自动重新规划
多 Session 合并
批量并发研判
动态 Agent Team
通用 ACP/A2A 桥接
长期会话记忆
```

## 14.3 Request/Session 规则

```text
request_id：每次发送唯一
session_id：一次 Research Run 稳定
correlation_id：与 pipeline_run_id 对齐
message_id：每次消息唯一
```

Workspace：

```text
workspace/research/<pipeline_run_id>/
├── request.json
├── evidence.json
├── envelope.json
├── events.jsonl
├── result.json
├── report.md
└── run.json
```

## 14.4 幂等键

建议：

```text
research:{instrument_id}:{as_of_date}:{playbook_version}:{evidence_hash}
```

若现有 `ops.pipeline_runs` 中同一 key 已经：

```text
queued / running / succeeded
```

则阻止重复运行。

失败、取消和 partial 允许重新运行。

## 14.5 重试策略

只允许安全重试：

- 建立连接失败；
- 尚未收到服务端接受确认；
- 服务端明确返回 retryable；
- Gateway 短暂不可用。

收到有效流式事件后，不自动创建新 request 重跑；应：

- 尝试基于同一 session 继续；
-若无法继续，标记 interrupted/failed；
-由用户显式重新执行。

第一阶段最多 2 次连接重试，指数退避，不建设复杂重试框架。

## 14.6 中断

CLI 收到中断时：

1. 尝试发送 `chat.interrupt` 或等价取消请求；
2. 刷新 `events.jsonl`；
3. 将 Pipeline Run 标记为 cancelled；
4. 不写入成功 Research Result。

---

# 15. Playbook 与 Agent 团队

## 15.1 Playbook

```text
playbook_key: etf_market_state_assessment
playbook_version: 1.0.0
horizon: 20-60 trading days
```

研判问题：

1. 当前趋势结构如何？
2. 当前动量是否得到数据支持？
3. 波动和回撤风险如何？
4. 流动性是否退化？
5. Candidate Pool 上下文如何解释？
6. 哪些证据支持或反驳主观点？
7. 哪些条件会使观点失效？
8. 当前数据是否足以形成判断？

## 15.2 固定角色

1. **Research Director**
   - 检查 Evidence 完整性；
   - 分配任务；
   - 汇总分歧；
   - 形成最终结构。

2. **Data & Factor Analyst**
   - 分析趋势、收益、波动、回撤、流动性和质量；
   - 所有数字引用 Evidence ID。

3. **ETF & Market Analyst**
   - 解释 Candidate Pool 和市场状态；
   - 不生成 Evidence 中不存在的基金结构、行业或政策信息。

4. **Risk / Red Team Analyst**
   - 强制反方分析；
   - 挑战单因子结论；
   - 给出风险和失效条件。

## 15.3 观点枚举

```text
bullish
cautiously_bullish
neutral
cautiously_bearish
bearish
insufficient_evidence
```

## 15.4 置信度约束

```text
complete Evidence：最高 70
partial Evidence：最高 50
missing / invalid / conflict：insufficient_evidence
```

第一阶段只有市场和风险证据，不允许给出高置信度完整投资结论。

## 15.5 禁止输出

- 目标价；
-仓位比例；
-明确买卖指令；
-产业和政策判断；
-估值合理性；
-收益承诺；
-自动订单。

---

# 16. Research Result Schema

```json
{
  "stance": "neutral",
  "confidence": 45,
  "horizon": "20-60d",
  "thesis": [],
  "supporting_evidence_ids": [],
  "contradicting_evidence_ids": [],
  "risks": [],
  "invalidation_conditions": [],
  "watch_items": [],
  "unresolved_disagreements": [],
  "data_limitations": []
}
```

必须校验：

- stance 在枚举内；
- confidence 符合 Evidence 质量上限；
- 所有 Evidence ID 存在于当前 Pack；
- risks 非空；
- invalidation conditions 非空；
- data limitations 非空；
- result hash 稳定；
-解析失败不写成功结果。

---

# 17. CLI 与配置

## 17.1 Make Targets

```bash
make research-history-bootstrap \
  INSTRUMENT_ID=<uuid> \
  START_DATE=YYYY-MM-DD \
  END_DATE=YYYY-MM-DD

make research-evidence-build \
  INSTRUMENT_ID=<uuid> \
  AS_OF=YYYY-MM-DD

make research-run \
  INSTRUMENT_ID=<uuid> \
  AS_OF=YYYY-MM-DD
```

`research-run` 执行：

```text
检查开关
→ 获取/生成 Evidence Pack
→ 创建 Pipeline Run
→ 创建 workspace
→ E2A 调度 JiuwenSwarm
→ 校验 Result
→ 写 Research Result
→ 生成 Markdown
→ 完成 Pipeline Run
```

## 17.2 环境变量

```text
INVEST_RESEARCH_ENABLED=false
INVEST_RESEARCH_WORKSPACE_ROOT=/home/claw/invest-infra/workspace/research
INVEST_RESEARCH_JIUWENSWARM_URL=ws://127.0.0.1:19000/ws
INVEST_RESEARCH_DEFAULT_PLAYBOOK=etf_market_state_assessment
INVEST_RESEARCH_CONNECT_TIMEOUT_SECONDS=10
INVEST_RESEARCH_TIMEOUT_SECONDS=300
INVEST_RESEARCH_MAX_CONNECT_RETRIES=2
```

默认关闭，不加入每日自动 Schedule。

---

# 18. 只读 API

Stage 4A 只增加 3 个接口。

## 最新 Evidence

```http
GET /api/v1/research/evidence/latest?instrument_id=<uuid>
```

## 最新研判结果

```http
GET /api/v1/research/results/latest?instrument_id=<uuid>
```

## 结果详情

```http
GET /api/v1/research/results/{result_id}
```

接口返回：

- Instrument；
- as_of_date；
- Evidence hash；
- freshness/quality；
-因子；
-stance/confidence；
-核心结论；
-支持/反方 Evidence ID；
-risks；
-invalidation conditions；
-data limitations；
-run time。

API 不：

- 触发研判；
-执行因子计算；
-访问 Provider；
-接受任意 SQL；
-返回任意 workspace 文件路径。

Web 面板延后至 Stage 4D；Stage 4A 不作为门禁。

---

# 19. 实施任务

## Task 0：文档与目标对齐

交付：

- README；
- Architecture；
- ADR-0012；
- AI Research 产品文档；
- Evidence Contract；
- OpenWiki 更新。

验收：顶层目标无冲突。

## Task 1：历史行情准备

交付：

- 65 日 Fixture；
-真实 ETF 历史补齐命令；
-无未来数据测试。

验收：至少一个 ETF 满足 60 日窗口。

## Task 2：Evidence Pack

交付：

- Domain 数据结构；
-Canonical Serializer；
-8 个因子；
-Quality Gate；
-`research_evidence_packs` 表；
-Repository/UoW；
-CLI；
-Golden Hash。

验收：complete/partial/failed、幂等和 revision 场景通过。

## Checkpoint A：Evidence Foundation

- [ ] 不依赖 JiuwenSwarm 可生成 Pack；
- [ ] 相同输入 Hash 一致；
- [ ] Revision 产生新 Hash；
- [ ] 旧 Pack 保留；
- [ ] 无敏感信息。

## Task 3：E2A Governor

交付：

- E2A Protocol Adapter；
-Client；
-Request/Session；
-Stream Events；
-Timeout/Retry；
-Cancel；
-Workspace；
-Pipeline Run 集成。

验收：Fake Gateway 成功、失败、超时和中断测试通过。

## Task 4：Playbook 与 JiuwenSwarm

交付：

-固定 Playbook；
-4 个角色；
-Fake JiuwenSwarm E2E；
-真实 JiuwenSwarm 手工验收；
-Result Schema；
-Markdown 报告。

验收：报告引用有效 Evidence ID，且无无依据基本面结论。

## Task 5：Result 与 API

交付：

-`research_results` 表；
-结果 Repository；
-3 个 API；
-OpenAPI Contract；
-API 测试。

验收：最新和详情可查询，API 不暴露路径和凭据。

## Task 6：阶段收口

交付：

-Stage 4A 验收记录；
-Runbook；
-文档一致性 Gate；
-完整测试。

验收：既有每日 Pipeline 无回归。

---

# 20. 建议 PR 拆分

## PR-A：目标重基线与历史数据准备

```text
docs/stage4a-ai-research-v11
```

包含：

- 文档；
-ADR；
-65 日 Fixture；
-历史 Bootstrap 设计。

## PR-B：轻量 Evidence Pack

```text
feat/stage4a-lightweight-evidence-pack
```

包含：

- Canonical Hash；
-因子；
-Quality Gate；
-第一张表；
-CLI；
-测试。

## PR-C：内置 E2A 治理

```text
feat/stage4a-integrated-e2a-governor
```

包含：

- E2A Client；
-Request/Session；
-Stream；
-Retry/Timeout；
-Cancel；
-Workspace；
-Pipeline Run。

## PR-D：JiuwenSwarm 研判切片

```text
feat/stage4a-jiuwenswarm-research-slice
```

包含：

- Playbook；
-角色；
-Fake E2E；
-真实手工验收；
-Result Schema；
-Markdown。

## PR-E：Result API 与验收

```text
feat/stage4a-research-result-api
```

包含：

- 第二张表；
-3 个 API；
-OpenAPI；
-验收记录；
-文档同步。

---

# 21. 测试计划

## Domain

- Canonical JSON；
-Decimal/UUID/日期规范化；
-Item Hash；
-Pack Hash；
-Evidence ID；
-8 个因子；
-窗口不足；
-未来数据阻止；
-Quality Gate。

## Storage/PostgreSQL

- 两张表；
-FK/CHECK/JSONB；
-Migration roundtrip；
-重复 Hash 幂等；
-Revision 新 Pack；
-Research Result 与 Pipeline Run 关联；
-Rollback。

## Pipeline

-完整 Pack；
-partial；
-failed；
-amount 缺失；
-Candidate Context 缺失；
-Secret Scanner；
-Workspace 路径；
-Pipeline Run 幂等。

## E2A

-Envelope；
-request/session/correlation；
-流式顺序；
-完成；
-失败；
-连接超时；
-总体超时；
-安全重试；
-中断；
-无最终结果；
-无效 Evidence 引用。

## API

-最新 Evidence；
-最新 Result；
-Result 详情；
-UUID；
-404；
-数据库异常脱敏；
-OpenAPI 类型同步。

## E2E

```text
Fixture PostgreSQL
→ Evidence Pack
→ Fake JiuwenSwarm
→ Pipeline Run succeeded
→ Research Result
→ API latest
→ 验证 Evidence 引用
```

真实 JiuwenSwarm 调用只做手工验收，不进入 CI。

---

# 22. Definition of Done

Stage 4A 完成条件：

- [ ] README 和 Architecture 对齐 AI 投资研判目标；
- [ ] ADR-0012 Accepted；
- [ ] 至少一个 ETF 有 60 个交易日日行情；
- [ ] Evidence Contract v1.0.0；
- [ ] 8 个因子可确定性计算；
- [ ] Pack Hash 稳定；
- [ ] Evidence ID 无循环依赖；
- [ ] Revision 生成新 Pack，旧 Pack 保留；
- [ ] Evidence 无凭据和敏感原始响应；
- [ ] E2A 治理由 invest-infra 内置实现；
- [ ] Request/Session/Stream/Timeout/Retry/Cancel 可测试；
- [ ] 一个市场状态研判 Playbook 可运行；
- [ ] Fake JiuwenSwarm E2E 通过；
- [ ] 至少一次真实 JiuwenSwarm 手工验收通过；
- [ ] Research Result 可持久化；
- [ ] 3 个 API 可查询；
- [ ] 既有数据 Pipeline 无回归；
- [ ] 未引入回测、向量库、消息队列或新微服务。

---

# 23. 风险与控制

| 风险 | 控制 |
|---|---|
| Stage 4A 再次变重 | 两张表、8 个因子、3 个 API、单 ETF |
| E2A 代码重复或失控 | 只实现 Stage 4A 最小治理，通用治理后移 |
| JiuwenSwarm 不可用阻塞数据底座 | Evidence Checkpoint 独立，Fake Gateway 进入 CI |
| Workspace 成为隐性数据库 | DB 是正式事实源，Workspace 只保存运行产物 |
| Hash 不稳定 | Canonical Serializer + Golden Hash |
| Evidence ID 循环 | Pack Hash 先算，Evidence ID 后生成 |
| 只有技术指标却输出完整投资结论 | Playbook 改为市场状态与风险，置信度上限 70 |
| partial 数据诱导高置信度 | Schema 强制置信度上限和 data limitations |
| Provider 凭据泄漏 | 白名单序列化、日志脱敏、Secret Scanner |
| E2A 失败影响日任务 | 独立开关、手工触发、不进入每日硬依赖 |
| 真实数据尚未验收 | 开发线和运行线并行，生产声明以后者为门禁 |

---

# 24. Stage 4B 入口条件

进入 Stage 4B 前：

- Evidence Contract v1.0.0 稳定；
-8 个因子公式、单位和窗口稳定；
-至少一个真实 Provider Evidence Pack 通过验收；
-真实 JiuwenSwarm 研判结果可重复执行；
-E2A 内置治理无关键故障；
-证据引用全部可验证；
-Stage 2 真实运行记录持续更新；
-文档和实现无目标冲突。

Stage 4B 再增加：

- ETF 规模和份额；
-跟踪指数；
-折溢价和跟踪误差；
-行业及风格暴露；
-市场环境；
-外部事件证据；
-更多 Playbook；
-更完整投资研判。

---

# 25. 最终建议

按 v1.1 实施 Stage 4A：

```text
先准备 60 日数据
→ 建立轻量 Evidence Pack
→ 在 invest-infra 内完成 E2A 治理
→ 调度 JiuwenSwarm 四角色团队
→ 保存结构化结果
→ 提供最小 API
```

第一阶段的核心交付不是新的页面，也不是通用 Agent 平台，而是：

> 一份由确定性系统生成、由 invest-infra 自主管理 E2A 调度、可被 JiuwenSwarm 团队共同引用并形成可追溯研判的标准研究材料。
