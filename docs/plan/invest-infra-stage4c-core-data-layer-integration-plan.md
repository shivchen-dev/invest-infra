# invest-infra Stage 4C Core Data Layer Integration

> 文档版本：v1.0
> 状态：Draft for review
> 基线：GitHub/Gitee `main`，`4268f96b1d167eb3c18aeb9ae73e1ef521a9bc06`
> 前置：Stage 4B Market Temperature、Market Breadth 与 A 股日线主备链路已经交付

## 1. 目标与范围

Stage 4C 补齐可支撑市场研判的核心事实数据层，使系统能够确定性地产出：

- 全市场宽度及趋势状态；
- 涨跌停、开板和连板情绪；
- 行业、概念板块的强弱与扩散；
- 日频和 1/5 分钟级成交动能；
- 通达信客户端原生公式、条件选股和分析结果。

本阶段只建设数据合同、Provider、质量门禁、持久化和 Analytics 输入，不建设
驾驶舱 UI，不生成投资观点，不执行交易，不把未经授权的网络协议作为生产主源。

## 2. 已确认基线与缺口

已有能力：

- Tushare 为 A 股日线主源，TDX 本地 `.day` 为失败后的备用源；
- `tdx_offline` 已支持沪、深、北三市场发现、解析和 Provider 编排；
- Raw Provider evidence、Market Observation、Market Temperature、Market Breadth 已落地；
- 本机拥有大规模 `.day/.lc1/.lc5` 数据；
- 麒麟容器 TDX 7.64 已验证条件选股、全量刷新和受控导出。

已确认缺口：

- TDX fallback 的 `prev_close` 语义不完整；
- 分钟线、板块、财务和除权尚未进入 Provider 合同；
- 涨跌停、连板和开板没有稳定事实合同；
- 当前板块快照没有 snapshot/history 治理；
- GUI 导出尚无状态机、schema contract、质量门禁和调度入口；
- 北向、主力资金流、逐笔和盘口没有完成授权与稳定性验证。

## 3. 架构决策

### 3.1 所有权链路

```text
Source / Client
      ↓
Raw Provider Evidence
      ↓
Core Canonical Facts
      ↓
Analytics Observation
      ↓
Research Evidence Bundle
```

- Raw 保存原文件、request、attempt、batch、hash 和解析版本；
- Core 只保存口径明确的规范事实；
- Analytics 计算宽度、情绪、轮动和趋势；
- Research 只绑定已发布快照，不直接调用 TDX 或解析文件。

### 3.2 Provider 边界

| Provider | Dataset | 定位 | 上游方式 |
|---|---|---|---|
| `tdx_offline` | `stock_daily_bars` | 保留现有日线备用源 | 自研 `.day` reader |
| `tdx_offline_minute` | `stock_minute_bars` | 本地分钟候选主源 | `.lc1/.lc5` |
| `tdx_local_block` | `stock_block_memberships` | 当前板块快照辅助源 | `block_*.dat/blocknew` |
| `tdx_local_financial` | `stock_financials` | 财务备用源 | `gpcw*.zip/dat` |
| `tdx_gui_analysis` | `tdx_analysis_results` | TDX 特有派生结果源 | GUI 状态机与受控导出 |
| `tushare` | 已有及许可可用数据集 | 规范主源/交叉验证 | 官方 API |

不以 `mootdx` 替换现有 `.day` 适配器。Stage 4C 只允许独立 wrapper 调用所需
MIT 模块，或依据格式知识实现本项目窄接口；采用方式必须通过 Spike 和 ADR 冻结。

### 3.3 Dataset 与时间语义

候选稳定键为：

```text
stock_minute_bars
stock_block_memberships
stock_price_limits
stock_financials
tdx_analysis_results
```

每个 dataset 必须拥有独立 capability。日线/分钟线保存市场时间；板块保存
`snapshot_date`，不得把当前归属伪装成历史归属；财务同时保存报告期、公告期和
采集时间；价格限制绑定规则版本；GUI 结果保存分析时点、公式、参数、证券范围和
客户端版本。

## 4. 核心数据合同

### 4.1 分钟行情

```text
instrument_id, interval, trade_time,
open, high, low, close, volume, amount,
source_batch_id, raw_file_hash, parser_version
```

相同证券、周期、时间点幂等；金额和价格使用 Decimal；损坏记录整文件
fail-closed；本层不计算复权。

### 4.2 板块与成员

```text
block_id, block_type, block_code, block_name, source
block_id, instrument_id, snapshot_date, effective_state, source_batch_id
```

`industry/concept/custom` 显式分类。未知历史区间保持未知，不回填当前成分。

### 4.3 涨跌停事实

```text
instrument_id, trade_date, prev_close,
limit_up_price, limit_down_price, close,
hit_limit_up, close_at_limit_up, hit_limit_down, close_at_limit_down,
rule_version, source_refs
```

价格限制由规范日线、前收和版本化交易规则计算。连板、开板和炸板属于 Analytics
派生观察；没有分钟或更细粒度证据时返回 unknown，不能从收盘价推测盘中事件。

### 4.4 GUI 分析结果

请求身份包含：

```text
formula_key, formula_version, parameters,
universe_key, analysis_as_of, client_version
```

批次证据包含：

```text
login_state, refresh_state, execution_state, export_state,
reported_match_count, exported_row_count, schema_version,
raw_export_hash, screenshot_refs, started_at, finished_at
```

窗口标题、命中数、文件行数、公式参数任一不一致即拒绝发布。导出强制 ASCII
文件名，按 GB18030/Tab 契约解析；不能根据 `.xls` 扩展名判断格式。

## 5. 数据质量门禁

所有新增 dataset 统一执行：

1. 文件存在、大小、hash 和 parser version 检查；
2. schema、类型、主键唯一性和数值边界检查；
3. universe coverage、交易日完整性和 freshness 检查；
4. 与主源或上一快照的差异阈值检查；
5. Raw batch 完整后单事务发布 Core；
6. partial、stale、invalid 不进入 complete Analytics snapshot。

覆盖阈值不在方案中猜测；Phase 0 根据真实样本生成 baseline 后冻结。

## 6. 首批 Analytics 输出

| 观察族 | 最小指标 |
|---|---|
| Market Breadth v2 | 上涨/下跌、MA20、MA60、新高/新低占比 |
| Limit Sentiment | 涨停数、跌停数、连板高度、开板率、封板率 |
| Block Rotation | 行业/概念涨跌、成交额、上涨家数、强度扩散 |
| Liquidity/Momentum | 全市场及板块成交额、量比、1/5 分钟动量 |

GUI 公式结果保持独立事实输入，不直接混入市场评分。评分算法必须在数据合同稳定后
另行版本化，并能够回放历史输入。

## 7. 分阶段交付

### Phase 0：合同与 Spike

- 冻结 dataset/capability、时间、hash、quality 和 provenance 合同；
- 验证 `.lc1/.lc5`、板块和财务真实样本；
- 形成 `mootdx` 采用 ADR；
- 建立覆盖率、历史深度和容量基线。

### Phase 1：日频研判闭环

- 补齐 TDX `prev_close`；
- 建设价格限制事实、Market Breadth v2 和 Limit Sentiment；
- 以 Tushare 和 TDX 做跨源一致性验证。

### Phase 2：板块轮动闭环

- 接入板块字典与成员快照；
- 生成行业/概念日频聚合；
- 发布 Block Rotation，禁止历史穿越。

### Phase 3：分钟线闭环

- 接入 `.lc1/.lc5`、增量高水位和缺口检测；
- 提供开板、封板及盘中动能证据；
- 验证性能、存储增长和回补策略。

### Phase 4：GUI 原生分析闭环

- 将已验证路径实现为显式状态机；
- 固化 ASCII 导出、GB18030 解析和 schema 版本；
- 以一个白名单公式完成端到端验收。

### Phase 5：Research 集成与验收

- 将 complete Analytics snapshot 注册到 ResearchEvidenceBundle；
- 扩展 ContextProjection，不改变旧 EvidencePack；
- 完成 seeded case 回放、故障降级和审计报告。

## 8. 明确延期

- 北向/主力资金流、Tick、Level-2、盘口；
- 私有在线协议生产化；
- 权威来源缺失时的历史板块成员回溯；
- 估值、投资建议、回测、交易和 Dashboard/UI；
- 多公式无人值守批量运行。

## 9. 风险与控制

| 风险 | 控制 |
|---|---|
| 文件格式或客户端升级 | parser/client version、golden tests、fail-closed |
| 当前板块冒充历史板块 | snapshot_date 强制语义，不回填未知历史 |
| GUI 状态漂移 | 白名单状态机、计数校验、截图证据 |
| `mootdx` 停止维护 | 有边界复用、锁版本、窄适配层 |
| 数据授权不明确 | 只用已授权本地能力；在线协议另设批准闸门 |
| 分钟线体量增长 | 分区、增量高水位、容量基线和保留策略 |

## 10. 完成标准

- 新数据链路均通过 Provider Contract 和 Raw provenance；
- 日频宽度、涨跌停情绪、板块轮动可确定性重算；
- 分钟数据足以证明已判定的盘中事件，不可判定项显式 unknown；
- 一个白名单公式可无人值守执行、导出、解析和发布；
- 相同输入生成相同 hash，不同 revision 保留历史；
- migration、PostgreSQL、focused tests 和 architecture checks 通过；
- Research 可绑定新快照，UI 不承担事实计算。
