# invest-infra 后续分阶段路线与第一阶段实施计划

> 文档状态：Draft  
> 制定日期：2026-08-03  
> 适用仓库：`shivchen-dev/invest-infra`  
> 当前基线：`main` 分支，最新检查提交 `e250051ec24d156f036b8a6bd1eb687cd99a409b`  
> 第一阶段主题：从“ETF 数据工作台”升级到“最小可用的 AI 投资研判系统”  
> 建设原则：证据优先、因子辅助、AI 团队研判、全程可追溯、轻量实现、拒绝过度工程化  

---

## 1. 产品目标重新定义

`invest-infra` 的核心目标不再是建设量化回测平台，而是：

> 持续提供可信数据、标准因子、策略研判剧本和可追溯证据，并通过 JiuwenSwarm 组织专业投资研判 Agent 团队，生成结构化、可质询、可复核的投资研判结果。

目标链路：

```text
数据 Provider
    ↓
PostgreSQL：raw / core / analytics / ops
    ↓
标准数据 + 因子快照 + Candidate Pool
    ↓
Research Evidence Pack
    ↓
JiuwenSwarm 投资研判团队
    ↓
多角色分析 / 风险质询 / 综合研判
    ↓
结构化研判报告
    ↓
人工查看、复核和后续跟踪
```

系统的重点是：

1. 数据是否可信、完整、及时；
2. 因子是否计算正确、口径稳定、含义清楚；
3. AI 结论是否能够追溯到具体证据；
4. 不同 Agent 的观点和分歧是否被保留；
5. 最终研判是否给出风险、失效条件和待观察项。

系统当前不以以下能力为主要目标：

- 参数寻优；
- 重型回测；
- 自动交易；
- 高频或分钟级撮合；
- 追求历史收益曲线最优；
- 通用型 Agent 平台；
- 大规模知识图谱或向量数据库。

---

## 2. 总体建议：分 4 个阶段推进

### 阶段一：AI 研判最小闭环

目标：使用现有 ETF 数据完成一次端到端、可追溯的 JiuwenSwarm 多 Agent 研判。

```text
单个 ETF
→ Evidence Pack
→ 基础因子快照
→ 一个研判剧本
→ JiuwenSwarm 多 Agent 分析
→ 结构化 Markdown 报告
→ 结果保存与只读查看
```

本文件后续章节详细描述阶段一。

### 阶段二：证据与因子覆盖扩展

目标：让 AI 获得更完整的 ETF 研究材料，而不是只看价格技术指标。

重点增加：

- ETF 跟踪指数和分类；
- 规模、份额、折溢价、跟踪误差；
- 成交额和流动性结构；
- 行业及风格暴露；
- 相对强弱和市场环境；
- 公告、政策、行业事件等外部证据；
- 多标的比较工具；
- 2～3 个稳定的研判剧本。

阶段二不建设通用因子平台，只增加实际研判需要的因子。

### 阶段三：JiuwenSwarm 研判团队完善

目标：将一次性调用升级为稳定的多角色投资研判流程。

重点增加：

- E2A session / request 管理；
- 中断、恢复、超时和重试；
- Agent 角色边界；
- 证据引用约束；
- 多 Agent 分歧记录；
- Red Team 反方审查；
- 独立验收步骤；
- 单标的、对比研判和 Candidate Pool 批量研判。

### 阶段四：研判工作台与质量闭环

目标：让用户能够持续使用和复盘 AI 研判结果。

重点增加：

- Research Case 页面；
- 研判报告历史；
- 今日观点与前次观点差异；
- 新增证据和风险变化；
- 5/10/20 个交易日后验跟踪；
- Agent 观点质量和置信度校准；
- 每日简报和轻量通知。

这里的后验跟踪只评价研判质量，不做策略参数优化。

---

# 3. 第一阶段定位

## 3.1 阶段名称

**Stage 4A — Evidence-Driven AI Research MVP**

中文名称：

**AI 投资研判最小闭环**

## 3.2 阶段目标

阶段完成后，系统应能够：

1. 从现有 PostgreSQL 数据生成一个 ETF 的 Research Evidence Pack；
2. Evidence Pack 包含基础身份、行情、因子、Candidate Pool 和数据质量信息；
3. 使用一个固定、版本化的 ETF 中期研判剧本；
4. 通过 E2A 调用 JiuwenSwarm 的 Swarm 模式；
5. 由轻量投资研判团队完成多角色分析；
6. 输出结构化 Markdown 研判报告；
7. 报告中的关键结论引用 Evidence ID；
8. 保存本次运行的输入、事件、结果和错误信息；
9. 通过只读 API 或现有 Web 页面查看最近研判结果；
10. 项目顶层文档统一对齐“AI 投资研判系统”目标。

## 3.3 第一阶段成功标准

使用一个 fixture 或真实数据已完整的 ETF，执行：

```bash
make research-run \
  INSTRUMENT_ID=<uuid> \
  AS_OF=YYYY-MM-DD
```

成功生成：

```text
workspace/research/<run_id>/
├── request.json
├── evidence.json
├── envelope.json
├── events.jsonl
├── report.md
└── run.json
```

其中：

- `evidence.json` 可通过 Schema 校验；
- `evidence.json` 有稳定 `content_hash`；
- `report.md` 含观点、证据、风险、反方观点和失效条件；
- 报告引用的 Evidence ID 均存在；
- 同一输入重复生成 Evidence Pack 时 hash 一致；
- 数据缺失时降低置信度或明确拒绝下结论；
- JiuwenSwarm 调用失败时保留完整可诊断运行记录；
- 现有数据 Pipeline、API 和 Web 测试不回归。

---

# 4. 第一阶段轻量化设计原则

## 4.1 复用现有运行单元

不新增微服务。

继续使用：

```text
apps/api
apps/pipeline
apps/web
packages/domain
packages/storage
PostgreSQL
```

AI 研判编排第一阶段放在：

```text
apps/pipeline/src/invest_pipeline/research/
```

原因：

- 它属于长任务；
- 已经具备配置、数据库和运行环境；
- 可复用现有 `domain`、`storage` 和 Provider 数据；
- 不需要创建新的部署单元。

后续只有在 AI 研判任务形成独立扩缩容或权限需求后，才评估拆出 `apps/research`。

## 4.2 第一阶段不建设因子仓库

基础因子按需从 `core.daily_bars` 计算，写入当次 Evidence Pack。

不新增：

```text
factor_definitions
factor_values
factor_jobs
feature_store
factor_registry
```

只有当多个研判剧本重复使用、数据量和查询性能确实需要时，再增加正式因子持久化。

## 4.3 第一阶段只增加一个最小研究表

建议新增：

```text
analytics.research_runs
```

最小字段：

```text
id                  UUID PK
instrument_id       UUID FK
as_of               DATE
playbook_key        TEXT
playbook_version    TEXT
status              TEXT
evidence_hash       TEXT
workspace_path      TEXT
stance              TEXT NULL
confidence          INTEGER NULL
error_code          TEXT NULL
error_summary       TEXT NULL
started_at          TIMESTAMPTZ
finished_at         TIMESTAMPTZ NULL
created_at          TIMESTAMPTZ
```

报告正文和完整 Evidence Pack 第一阶段保存在 workspace 文件中，不把大段事件流和 Markdown 全部塞进数据库。

数据库只保存：

- 索引信息；
- 状态；
- hash；
- 结果摘要；
- workspace 路径；
- 错误摘要。

这样既有审计能力，又避免过度建模。

## 4.4 第一阶段不建设通用工具调用平台

Evidence Pack 由 `invest-infra` 在任务开始前一次性生成，并作为文件附件或内容块交给 JiuwenSwarm。

暂不建设：

- Agent 任意 SQL；
- 通用 MCP Server；
- 动态工具注册中心；
- Agent 工具权限后台；
- 向量检索；
- 研究知识图谱。

第二阶段证据种类明显增加后，再增加受控只读研究工具。

---

# 5. 第一阶段最小业务模型

## 5.1 Domain 模型

建议新增目录：

```text
packages/domain/src/invest_domain/research/
├── __init__.py
├── evidence.py
├── playbook.py
└── result.py
```

只定义以下对象：

```text
EvidenceItem
ResearchEvidencePack
ResearchPlaybook
ResearchDecision
```

### EvidenceItem

```python
@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    category: str
    name: str
    value: object
    unit: str | None
    as_of: date
    source: str
    quality: str
    interpretation_hint: str | None
```

### ResearchEvidencePack

```python
@dataclass(frozen=True)
class ResearchEvidencePack:
    schema_version: str
    instrument_id: UUID
    as_of: date
    generated_at: datetime
    input_snapshot_id: UUID | None
    candidate_pool_run_id: UUID | None
    evidence: tuple[EvidenceItem, ...]
    missing_items: tuple[str, ...]
    freshness_status: str
    content_hash: str
```

### ResearchDecision

```python
@dataclass(frozen=True)
class ResearchDecision:
    stance: str
    confidence: int
    horizon: str
    thesis: tuple[str, ...]
    supporting_evidence_ids: tuple[str, ...]
    contradicting_evidence_ids: tuple[str, ...]
    catalysts: tuple[str, ...]
    risks: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    watch_items: tuple[str, ...]
    unresolved_disagreements: tuple[str, ...]
```

不要在第一阶段增加继承层次、复杂聚合根或插件体系。

---

# 6. 第一阶段 Evidence Pack

## 6.1 基础身份

至少包含：

- instrument ID；
- symbol；
- name；
- exchange；
- instrument status；
- list date；
- 数据日期。

## 6.2 Candidate Pool 上下文

至少包含：

- 是否进入最新已发布 Candidate Pool；
- included / excluded；
- rank；
- exclusion reason；
- Candidate Pool Run ID；
- Input Snapshot ID；
- Candidate Pool 数据日期。

## 6.3 基础行情事实

至少包含：

- 最新收盘价；
- 20 日收益；
- 60 日收益；
- 120 日收益；
- 20 日平均成交量；
- 20 日平均成交额（数据允许时）；
- 近 20 日缺失率；
- 近 60 日最大回撤；
- 20 日年化波动率；
- 60 日年化波动率。

## 6.4 第一批解释型因子

只计算 6 组：

| 因子组 | 最小指标 | AI 使用方式 |
|---|---|---|
| 趋势 | MA20、MA60、价格相对均线 | 判断中短期趋势结构 |
| 动量 | 20/60/120 日收益 | 判断强弱延续 |
| 风险 | 波动率、最大回撤 | 判断风险扩张 |
| 流动性 | 平均成交量/额、变化率 | 判断可交易性和退化 |
| 数据质量 | 缺失率、最后数据日期 | 决定能否研判 |
| 候选池 | included、rank、reason | 提供筛选上下文 |

每个因子必须同时提供：

```text
value
state
as_of
source
quality
interpretation_hint
```

因子只描述状态，不直接输出“买入”或“卖出”。

## 6.5 Evidence ID 规则

使用可读且稳定的 ID：

```text
instrument:symbol
instrument:name
market:close
factor:return_20d
factor:return_60d
factor:ma20
factor:ma60
factor:volatility_20d
factor:max_drawdown_60d
factor:avg_volume_20d
quality:missing_rate_20d
candidate:status
candidate:rank
candidate:reason
```

需要 revision 时追加：

```text
factor:return_20d@2026-08-03
```

第一阶段不引入全局 Evidence Registry。

---

# 7. 第一阶段研判剧本

只实现一个：

```text
playbook_key: etf_medium_term_assessment
playbook_version: 1.0.0
horizon: 20-60 trading days
```

## 7.1 研判问题

1. 当前 ETF 处于什么趋势和风险状态？
2. 当前强弱是否有数据支持？
3. Candidate Pool 结果如何解释？
4. 有哪些支持中期看多或看空的证据？
5. 哪些反方证据会推翻主观点？
6. 当前数据是否足以形成判断？
7. 接下来应重点观察哪些条件？

## 7.2 输出观点

限定为：

```text
bullish
cautiously_bullish
neutral
cautiously_bearish
bearish
insufficient_evidence
```

不要输出：

- 目标价；
- 仓位比例；
- 明确买卖指令；
- 自动订单；
- 收益承诺。

## 7.3 输出模板

```markdown
# ETF AI 研判报告

## 研判摘要
- 标的：
- 数据日期：
- 研判周期：
- 观点：
- 置信度：

## 核心结论

## 支持证据
- 结论 —— `evidence_id`

## 反方证据
- 风险或反证 —— `evidence_id`

## 市场与风险状态

## 失效条件

## 后续观察项

## 数据限制

## Agent 分歧
```

---

# 8. 第一阶段 JiuwenSwarm 团队

为避免过度复杂，第一阶段只使用 4 个角色。

## 8.1 Leader / Research Director

职责：

- 读取研判剧本；
- 确认 Evidence Pack 完整性；
- 将任务分配给其他 Agent；
- 汇总观点和分歧；
- 不独自跳过团队直接下结论。

## 8.2 Data & Factor Analyst

职责：

- 分析趋势、动量、风险、流动性和数据质量；
- 只使用 Evidence Pack；
- 所有数字引用 Evidence ID；
- 明确数据不足之处。

## 8.3 ETF & Market Analyst

职责：

- 解释 Candidate Pool 上下文；
- 分析 ETF 当前市场状态；
- 提供主要观点、催化因素和观察条件；
- 不虚构 Evidence Pack 中不存在的基金信息。

## 8.4 Risk / Red Team Analyst

职责：

- 主动反驳主要观点；
- 找出单因子依赖、趋势反转、波动和流动性风险；
- 检查结论是否超出证据；
- 给出具体失效条件。

由 Leader 兼任 CIO 汇总，不再单独增加第五个 Agent。

---

# 9. E2A 最小集成

## 9.1 请求模式

复杂研判固定使用：

```text
mode=swarm
```

第一阶段只实现：

- `request_id`；
- `session_id`；
- `method=chat.send`；
- `is_stream=true`；
- `params.mode=swarm`；
- Evidence Pack 文件引用；
- playbook key/version；
- workspace 路径。

## 9.2 建议 Envelope

```json
{
  "protocol_version": "1.0",
  "request_id": "research_req_<uuid>",
  "session_id": "research_session_<uuid>",
  "method": "chat.send",
  "is_stream": true,
  "identity_origin": "service",
  "channel": "invest-infra",
  "params": {
    "mode": "swarm",
    "task_type": "investment_research",
    "playbook_key": "etf_medium_term_assessment",
    "playbook_version": "1.0.0",
    "instrument_id": "<uuid>",
    "as_of": "YYYY-MM-DD",
    "files": [
      {
        "uri": "file:///workspace/research/<run_id>/evidence.json",
        "name": "evidence.json",
        "mime_type": "application/json"
      }
    ],
    "workspace": "/workspace/research/<run_id>"
  }
}
```

## 9.3 第一阶段必须处理

- 正常流式响应；
- 最终完成；
- JiuwenSwarm 返回失败；
- 连接超时；
- 无最终报告；
- 用户中断；
- events 写入 JSONL；
- 错误摘要脱敏。

## 9.4 第一阶段暂不处理

- 跨机器 Swarm；
- 多会话恢复 UI；
- 自动重新规划；
- 动态 Agent 组队；
- 通用 ACP/A2A 适配；
- 并发批量研判；
- 自动扩缩容。

---

# 10. 第一阶段实施顺序

建议拆为 4 个 PR。

```text
PR-A1 文档目标对齐
  ↓
PR-A2 Evidence Pack 与基础因子
  ↓
PR-A3 JiuwenSwarm 最小研判闭环
  ↓
PR-A4 结果查询、Web 展示和阶段验收
```

---

## 11. PR-A1：文档目标对齐

### 11.1 目标

让项目所有顶层文档统一表达：

> invest-infra 是证据驱动的 AI 投资研判系统基础设施，而不是以回测为中心的量化平台。

### 11.2 修改文件

#### `README.md`

修改：

- 标题；
- 项目定位；
- 设计目标；
- 当前能力；
- 下一阶段目标；
- “明确不做”。

建议开头替换为：

```markdown
# invest-infra — AI 投资研判基础设施

`invest-infra` 是面向个人投研场景的证据驱动 AI 投资研判系统。
系统使用 PostgreSQL 和 Dagster 建立可信数据与因子基础，
通过 FastAPI 提供结构化研究数据，并由 JiuwenSwarm 组织多 Agent
投资研判团队，形成可追溯、可质询、可复核的研判报告。

系统当前不以自动交易或重型回测为目标。
```

新增目标链路：

```text
Provider
→ 标准数据
→ Candidate Pool / 因子快照
→ Evidence Pack
→ JiuwenSwarm 研判团队
→ 结构化研判报告
```

#### `docs/ARCHITECTURE.md`

修改系统边界为：

```text
React Web ──HTTP/OpenAPI──> FastAPI API ──SQL──> PostgreSQL
                                      ↑
Dagster Pipeline ───────────────SQL───┘
       │
       └── Evidence Pack → JiuwenSwarm E2A → AI 研判报告
```

将 `analytics` 描述从：

```text
因子、信号、候选池和回测结果
```

改为：

```text
因子快照、候选池、AI 研判运行摘要和研判结果索引
```

增加规则：

1. AI 不直接查询数据库；
2. AI 只能消费版本化 Evidence Pack 或受控只读工具；
3. 重要结论必须引用 Evidence ID；
4. AI 输出不直接形成订单；
5. 数据计算与 AI 解释必须分离。

#### `openwiki/quickstart.md`

修改：

- 顶层产品定位；
- 系统链路；
- Backlog；
- 下一阶段入口；
- 增加 AI Research 页面链接。

#### `openwiki/architecture/overview.md`

增加：

- AI Research 边界；
- JiuwenSwarm 是外部协作运行时；
- E2A 是调用协议；
- `invest-infra` 仍拥有数据和 Evidence Pack 口径。

#### `openwiki/domain/overview.md`

增加 `research` bounded context 的最小说明。

#### `openwiki/testing-and-ops/overview.md`

增加：

- Evidence Pack 测试；
- E2A adapter mock 测试；
- workspace artifact 验收；
- AI 运行不会进入现有数据日任务的硬依赖链。

### 11.3 新增文档

```text
docs/AI-RESEARCH.md
docs/plan/invest-infra-stage4a-ai-research-mvp.md
docs/validation/stage4a-ai-research-acceptance.md
```

`docs/AI-RESEARCH.md` 只需要包含：

- 产品目标；
- 核心链路；
- Agent 团队；
- Evidence Pack；
- 研判输出；
- 当前边界。

不要单独建设大型文档站或重复 OpenWiki 全部内容。

### 11.4 文档一致性检查

增加一个轻量测试或脚本，检查以下关键词存在：

```text
AI 投资研判
Evidence Pack
JiuwenSwarm
不以重型回测为目标
```

检查文件：

```text
README.md
docs/ARCHITECTURE.md
docs/AI-RESEARCH.md
openwiki/quickstart.md
```

不建设复杂文档生成器。

### 11.5 PR-A1 验收

- README 和 Architecture 不再把系统描述为回测平台；
- `analytics` 定义不再把回测结果列为当前重点；
- AI 研判目标在所有顶层入口一致；
- 新增第一阶段计划和验收模板；
- 原有架构边界和部署方式不被破坏。

---

## 12. PR-A2：Evidence Pack 与基础因子

### 12.1 目标

从现有数据库为单个 ETF 生成稳定、可复现、可供 AI 读取的 Evidence Pack。

### 12.2 实施内容

新增：

```text
packages/domain/src/invest_domain/research/
apps/pipeline/src/invest_pipeline/research/evidence_builder.py
apps/pipeline/src/invest_pipeline/research/factors.py
apps/pipeline/src/invest_pipeline/research/cli.py
```

Make target：

```bash
make research-evidence \
  INSTRUMENT_ID=<uuid> \
  AS_OF=YYYY-MM-DD
```

### 12.3 计算要求

- 不使用未来日期数据；
- 只读取 `trade_date <= as_of`；
- 滚动窗口不足时返回 missing，不补造数值；
- 浮点数统一精度；
- Evidence 排序稳定；
- content hash 只基于规范化内容；
- 同一输入重复运行 hash 一致。

### 12.4 测试

- 因子公式单元测试；
- 窗口不足测试；
- 数据缺失测试；
- 截止日期测试；
- Evidence ID 唯一性测试；
- hash 确定性测试；
- PostgreSQL integration 测试；
- fixture ETF Evidence Pack snapshot 测试。

### 12.5 PR-A2 验收

生成的 `evidence.json` 至少包含：

- 1 组身份信息；
- 1 组 Candidate Pool 信息；
- 6 组基础因子；
- 数据质量；
- missing items；
- freshness；
- content hash。

---

## 13. PR-A3：JiuwenSwarm 最小研判闭环

### 13.1 目标

将 Evidence Pack 交给 JiuwenSwarm，并获得结构化投资研判报告。

### 13.2 实施内容

新增：

```text
apps/pipeline/src/invest_pipeline/research/playbooks/
└── etf-medium-term-assessment.yaml

apps/pipeline/src/invest_pipeline/research/
├── e2a_client.py
├── orchestrator.py
├── report_parser.py
└── workspace.py
```

新增 Make target：

```bash
make research-run \
  INSTRUMENT_ID=<uuid> \
  AS_OF=YYYY-MM-DD
```

### 13.3 JiuwenSwarm 团队配置

固定 4 个角色，不支持用户动态增删：

```text
Research Director
Data & Factor Analyst
ETF & Market Analyst
Risk / Red Team Analyst
```

### 13.4 输出校验

使用 JSON Schema 或 Pydantic 校验最终结构，不调用第二套复杂模型评审。

必须校验：

- stance 在枚举内；
- confidence 为 0～100；
- supporting evidence IDs 存在；
- contradicting evidence IDs 存在；
- risks 非空；
- invalidation conditions 非空；
- 数据不足时不能输出高置信度；
- Markdown 报告生成成功。

独立 GPT 验收放到后续阶段，避免第一阶段同时引入两套 AI 调用链。

### 13.5 PR-A3 验收

- fixture ETF 能完成一次 Swarm 研判；
- JiuwenSwarm 不可用时运行状态为 failed；
- 事件流和错误信息保存在 workspace；
- 不泄漏 Provider 或模型凭据；
- 不直接执行任何交易动作。

---

## 14. PR-A4：结果查询、Web 展示和阶段验收

### 14.1 目标

让用户能在现有系统查看最近一次 AI 研判结果。

### 14.2 API

只增加只读接口：

```http
GET /api/v1/research-runs/latest?instrument_id=<uuid>
GET /api/v1/research-runs/{run_id}
GET /api/v1/research-runs?instrument_id=<uuid>&limit=20
```

返回：

- run ID；
- 标的；
- as_of；
- playbook；
- status；
- stance；
- confidence；
- evidence hash；
- report availability；
- started/finished time；
- error code/summary。

第一阶段不通过 Web 创建或执行研判。

### 14.3 Web

在 ETF 详情页增加一个轻量面板：

```text
AI 研判
├─ 最近观点
├─ 置信度
├─ 数据日期
├─ 核心结论摘要
├─ 风险
├─ 失效条件
└─ 查看完整 Markdown
```

不新增独立复杂 Research Workbench。

### 14.4 阶段验收模板

`docs/validation/stage4a-ai-research-acceptance.md` 记录：

- 验收提交；
- instrument ID；
- as_of；
- Evidence hash；
- JiuwenSwarm request/session ID；
- Agent 角色；
- 最终 stance/confidence；
- Evidence 引用校验；
- 缺失数据；
- workspace 文件清单；
- API 查询结果；
- Web 展示结果；
- 凭据检查；
- 验收结论。

### 14.5 PR-A4 验收

- API 可读取成功和失败的 Research Run；
- Web 能显示最近研判；
- API 不直接返回任意 workspace 文件；
- 路径访问经过固定目录约束；
- 全部现有测试通过；
- 文档与实现一致。

---

# 15. 第一阶段明确不做

为控制范围，以下内容全部推迟：

## 数据与因子

- 通用因子注册中心；
- Factor Store；
- 分钟级行情；
- 财报全量建模；
- 新闻向量库；
- RAG 平台；
- 知识图谱；
- 多 Provider 自动切换；
- 大规模外部数据抓取。

## AI 与 Agent

- 用户自定义 Agent；
- 动态团队组建；
- Prompt 管理后台；
- Agent 市场；
- 多租户权限；
- 分布式 Swarm；
- 自动 Skill 自我修改；
- 复杂模型路由和成本调度。

## 量化与交易

- 回测引擎；
- 参数寻优；
- 模拟 Broker；
- 自动交易；
- 目标价模型；
- 仓位建议；
- 券商接口。

## 产品界面

- 通用研究工作台；
- 报告编辑器；
- 实时协同；
- 通知中心；
- 移动端适配；
- 批量研判管理后台。

---

# 16. 测试策略

第一阶段保持现有测试分层。

## Domain

验证：

- Evidence 模型；
- hash；
- Research Decision；
- playbook 枚举；
- Evidence ID。

## Storage

验证：

- `research_runs` 新增；
- 状态更新；
- latest/list 查询；
- 错误摘要；
- PostgreSQL migration 往返。

## Pipeline

验证：

- 因子计算；
- Evidence Builder；
- workspace；
- E2A request 构造；
- 流式事件解析；
- JiuwenSwarm mock；
- 报告校验；
- 凭据脱敏。

## API

验证：

- latest/detail/list；
- UUID 和 limit 校验；
- 不存在；
- failed run；
- 错误脱敏；
- workspace 路径不泄漏内部文件。

## Web

验证：

- loading；
- empty；
- success；
- failed；
- insufficient evidence；
- Markdown 摘要展示。

## E2E

只增加一个最小 E2E：

```text
fixture PostgreSQL
→ Evidence Pack
→ Fake JiuwenSwarm 流式响应
→ research_runs succeeded
→ API latest
→ 验证报告摘要
```

真实 JiuwenSwarm 调用使用手工验收，不放入 CI。

---

# 17. 运行和配置

建议新增环境变量：

```text
INVEST_RESEARCH_ENABLED=false
INVEST_RESEARCH_WORKSPACE_ROOT=/home/claw/invest-infra/workspace/research
INVEST_RESEARCH_JIUWENSWARM_URL=ws://127.0.0.1:19000/ws
INVEST_RESEARCH_DEFAULT_PLAYBOOK=etf_medium_term_assessment
INVEST_RESEARCH_TIMEOUT_SECONDS=300
```

默认关闭：

```text
INVEST_RESEARCH_ENABLED=false
```

手工运行时显式开启。

第一阶段不加入每日自动 Schedule。先通过手工研判验证输出质量。

---

# 18. 安全与边界

1. Workspace 根目录固定，禁止 `..` 路径穿越；
2. Evidence Pack 不包含 Provider API Key；
3. E2A envelope 不写明文模型凭据；
4. events 和 error summary 进行 token/key 脱敏；
5. Agent 不直接访问 PostgreSQL；
6. Agent 不执行 shell；
7. Agent 不写仓库源码；
8. Agent 输出仅是研判信息，不是自动交易指令；
9. Web 只读；
10. 运行失败不影响每日数据 Pipeline。

---

# 19. 第一阶段完成定义

第一阶段只有同时满足以下条件才算完成：

- [ ] README 对齐 AI 投资研判目标；
- [ ] Architecture 对齐 Evidence Pack 和 JiuwenSwarm 边界；
- [ ] OpenWiki 顶层入口同步；
- [ ] `docs/AI-RESEARCH.md` 已建立；
- [ ] 单 ETF Evidence Pack 可生成；
- [ ] 6 组基础因子可复现；
- [ ] Evidence hash 稳定；
- [ ] 一个研判剧本已版本化；
- [ ] 4 角色 JiuwenSwarm 团队可运行；
- [ ] 结构化结果可校验；
- [ ] Markdown 报告可生成；
- [ ] Research Run 状态可持久化；
- [ ] API 可读取最新结果；
- [ ] ETF 详情页可显示最近研判；
- [ ] Fake JiuwenSwarm E2E 通过；
- [ ] 真实 JiuwenSwarm 手工验收通过；
- [ ] 无凭据泄漏；
- [ ] 现有数据 Pipeline 无回归；
- [ ] 未引入回测、向量库、消息队列或新微服务。

---

# 20. 第一阶段结束后的决策门

完成后再根据实际使用决定第二阶段优先级。

## 优先补数据

当研判报告频繁出现：

```text
insufficient_evidence
```

或主要结论只依赖价格数据时，优先增加：

- ETF 规模与份额；
- 跟踪指数；
- 折溢价；
- 行业暴露；
- 市场环境；
- 外部事件。

## 优先补研判流程

当 Evidence 已足够，但报告存在：

- 证据引用错误；
- Agent 观点重复；
- Red Team 无有效反驳；
- 结论不稳定；
- 分歧被隐藏；

则优先完善：

- Agent 角色；
- playbook；
- E2A session；
- 独立验收；
- 分歧结构化。

## 优先补产品体验

当结果质量已可用，但使用不便时，再建设：

- Research Workbench；
- 研判历史；
- 多标的比较；
- 每日 Candidate Pool 研判；
- 简报和通知。

---

# 21. 参考基线

本计划依据以下当前资料制定：

- `shivchen-dev/invest-infra/README.md`
- `shivchen-dev/invest-infra/docs/ARCHITECTURE.md`
- `shivchen-dev/invest-infra/docs/plan/invest-infra-v2-stage2-automation-stability-plan-no-matrix.md`
- `openJiuwen-ai/jiuwenswarm/docs/zh/E2A-protocol.md`
- `openJiuwen-ai/jiuwenswarm/README.md`
- `StarChaserLH/stock_monitor`

对参考项目 `stock_monitor` 只借鉴“监测、结果组织、批量输出和可用性”的思路，不迁移其 SQLite 策略引擎、动态 Python 策略执行和回测主线。
