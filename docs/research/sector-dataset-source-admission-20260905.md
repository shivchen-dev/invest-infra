# Sector Dataset 数据源准入研究（Slice 1C）

> 日期：2026-09-05
>
> 范围：`sector-strength-ranking` 收窄方案，仅 `industry` / `concept`；`area`、`zgb/R-A3` 不在本报告范围
>
> 性质：只读事实与准入建议；不激活策略、不授权实现、不生成 Candidate

## 1. 结论

当前没有任何来源满足完整生产准入条件，Gate B2A 应保持 `BLOCKED`：

- **`sector-ranking`：无 production-admitted 来源。** `westock-mcp.data_sector(mode=ranking)` 能返回 Industry/Concept 的 `bd_code`、`bd_name`、`cje`、`bd_zdf`，但响应不含可信的显式 `as_of`，实测 `date` 参数静默失效、`limit` 不生效；只能定为 `research_only`。
- **`sector-constituents`：无 production-admitted 来源。** westock 历史成分有显式日期和名称，但 `symbol` 字段 100% 错误；`tool_filter` 可补 symbol，却排除 ST/*ST、北交所并出现截断；TDX screener 可形成当日样本，但缺显式历史 `as_of`，分类体系与 westock 不同，部分 Concept 缺稳定 `bd_code`。各路径只能定为 `research_only`。
- **内部 Provider 路径尚未形成。** 路由层虽然冻结了 `stock_block_memberships` dataset/capability，但当前没有 Provider 声明该能力，也没有 runtime wiring；`sector-ranking` 甚至尚未成为内部 routing dataset。TDX `.day` 和 ETF/BaoStock 不覆盖本任务，不能借用其已完成状态推断板块能力。
- **频控、配额和授权证据不足。** DataBundle 合同能记录 `RATE_LIMITED` 并拒绝不完整分页，但 WorkBuddy 报告没有给出 westock/TDX 的 QPS、并发、日配额、`Retry-After` 或许可边界实测；这些项均为 `unknown`，不得据此启动大规模预采集。

因此当前最小后续不是建设通用采集平台，而是分别补两条证据：

1. 为 `sector-ranking` 找到或构造**带显式收盘日期、可完整分页、可复算单位**的 Industry/Concept 全量输入；
2. 为 `sector-constituents` 找到**单一分类体系、完整 symbol/name/bd_code、显式 snapshot date、无静默排除**的快照输入。

在任一来源通过这些门禁前，不应创建预采集代码切片，也不应将 WorkBuddy 的多工具拼接结果伪装成内部 Provider 数据。

## 2. 本次判定口径

五态按以下定义使用；五态相互独立，不能从左到右自动推断：

| 状态 | 含义 |
|---|---|
| `declared` | 数据集/能力或 connector 已出现在受控合同、Catalog 或 DataRequest 定义中 |
| `constructible` | 当前代码/会话可构造对应 adapter/client 或调用对应 connector/tool |
| `wired` | 已接到运行时 Factory/Dagster，或已被正式 DataRequest/DataBundle 接缝引用 |
| `probe_verified` | 有当前环境真实调用证据；仅文档/代码声明不算 |
| `production_admitted` | 已通过覆盖、完整性、新鲜度、身份、授权和准入验收，可进入 evaluator |

准入建议：

- `admit`：允许进入生产输入接缝；
- `research_only`：允许继续探针、人工研究或隔离 raw evidence，不得进入正式 evaluator；
- `reject`：与当前 Dataset 不匹配，或当前凭据/实现已证明不可用；条件变化后可重新提案。

仓库现行准入规则要求：Provider、dataset、观察时间、payload/hash 和 provenance 可保留；Experimental 来源不得进入生产；Canonical 还必须具备唯一 owner、schema、写入和冲突处理。参见 `docs/validation/data-admission-checklist.md:25-44`。

## 3. 当前需求合同

收窄 evaluator 当前只允许 `industry`、`concept`，拒绝 `area`，只读取 `cje` 和 `bd_zdf`，评分权重各 50%；成分必须绑定被选中的 `(group, bd_code)`，并按 `(group, bd_code, symbol)` 生成快照 hash。见：

- `apps/pipeline/src/invest_pipeline/integrations/sector_evaluator.py:23-25`
- `apps/pipeline/src/invest_pipeline/integrations/sector_evaluator.py:78-94`
- `apps/pipeline/src/invest_pipeline/integrations/sector_evaluator.py:148-191`
- `apps/pipeline/src/invest_pipeline/integrations/sector_evaluator.py:195-235`
- `apps/pipeline/src/invest_pipeline/integrations/sector_evaluator.py:264-306`

但已部署的不可变采集定义仍绑定 Strategy `2.0.0`，仍要求 `area` 和 `zgb`，因此不能作为收窄版本的生产合同使用：`config/data-acquisition-definitions/sector-strength-ranking/1.0.0.json:5-58`（SHA-256 `4c3cc562b2711f5108ec6b1c225ef374e5eeb2b7d37730cf56cbbbd8bcd8143d`）。新策略版本未完成治理前，本报告只作准入研究。

DataRequest/DataBundle 已具备的安全边界包括：只允许 `tdx-connector`、`westock-mcp`、`mx-ds-mcp`；attempt 可记录 `RATE_LIMITED`、`AUTHORIZATION_FAILED`、`PAGINATION_FAILED`；交付必须完整分页、字段齐全且同 `as_of`。见：

- `packages/domain/src/invest_domain/strategy/data_acquisition.py:13-17`
- `packages/domain/src/invest_domain/strategy/data_acquisition.py:74-87`
- `packages/domain/src/invest_domain/strategy/data_acquisition.py:580-628`

这些只是校验能力，不证明任何来源已经覆盖或获授权。

## 4. 内部 Provider / Dataset 五态矩阵

### 4.1 数据集级现状

| Dataset | declared | constructible | wired | probe_verified | production_admitted | 建议 |
|---|---:|---:|---:|---:|---:|---|
| `sector-ranking`（Industry/Concept 排行） | 否 | 否 | 否 | 否 | 否 | `reject` 当前内部路径；需要新 Dataset 提案 |
| `stock_block_memberships`（Industry/Concept 成分快照候选） | 是 | 否 | 否 | 否 | 否 | `research_only` 作为冻结契约；不得声称已实现 |

依据：routing enum 包含 `stock_block_memberships`，但源码明确没有 provider 声明匹配能力，调用会 `NoEligibleProviderError`；现有 enum 不含 `sector-ranking`。见 `apps/pipeline/src/invest_pipeline/provider_routing/datasets.py:35-45`、`:55-118`。路由选择只按声明 capability 和 enablement 过滤，不会创建缺失 adapter，见 `apps/pipeline/src/invest_pipeline/provider_routing/selection.py:212-239`。

现有 quality/health 组件也不能替这些 Dataset 背书：注册表目前只有 ETF daily bars（fixture/cifangquant/akshare），见 `apps/pipeline/src/invest_pipeline/provider_quality.py:82-111`；虽然 publishability gate 默认要求覆盖率和完整率均为 1、freshness 为 fresh（`:276-345`），Sector Dataset 尚无 registration，无法产生有效质量分或 health。Health 只从既有 score/registration 派生 `unknown/stale/degraded/healthy`，不会主动探测来源，见 `apps/pipeline/src/invest_pipeline/provider_health.py:104-169`。

### 4.2 来源级现状

| 内部来源 | 当前相关能力 | declared | constructible | wired | probe_verified | production_admitted | 建议 / 原因 |
|---|---|---:|---:|---:|---:|---:|---|
| `tushare` | 股票主数据/日线；行业/概念接口仅研究候选 | 否（未声明 block membership） | 否（当前 Factory 只构造 stock provider） | 否 | 是，但相关接口当前凭据无权限 | 否 | `reject` 当前凭据；权限变化后重做最小探针 |
| `tdx_offline` | `.day` 股票日线 | 否（明确只声明 `STOCK_DAILY_BARS`） | 是（reader/adapter） | 日线已接 Dagster fallback；Sector Dataset 未接线 | 是，仅日线 | 否 | `reject` 本任务；禁止把日线完成度外推为板块能力 |
| `hithink` | research/market snapshot/股票数据声明 | 否（无 block membership） | 否 | 否 | 否 | 否 | `reject`；仅 reserved declaration |
| `akshare` | ETF/指数，不是当前 Industry/Concept 分类 | 否 | 是（ETF runtime） | 否（本 Dataset） | 否 | 否 | `reject` 本任务 |
| `quicktiny_mcp` / `rsscast` | research / market snapshot / index | 否 | 否（无 runtime factory） | 否 | 否 | 否 | `reject` 本任务 |

Catalog 证据：

- `tushare` 仅声明 ETF/股票日线和主数据：`apps/pipeline/src/invest_pipeline/provider_catalog.py:339-350`。
- `tdx_offline` 明确只声明股票日线，排除 block 能力；虽然 runtime Factory 仍视为 catalog-only，但日线已由专用 Dagster asset fallback 接线，不能据此推断 Sector Dataset 可用：`apps/pipeline/src/invest_pipeline/provider_catalog.py:396-429`、`apps/pipeline/src/invest_pipeline/assets.py:1094-1310`。
- `hithink` 是 disabled、catalog-only 的 reserved provider，且未声明板块成员：`apps/pipeline/src/invest_pipeline/provider_catalog.py:364-392`。
- runtime-supported 集合只由 `has_runtime_factory_adapter=True` 派生，且不等同所有专用 asset fallback 的实际 wiring：`apps/pipeline/src/invest_pipeline/provider_catalog.py:497-541`。
- 股票 runtime factory 当前只接受 Tushare：`apps/pipeline/src/invest_pipeline/provider_factory.py:196-214`；TDX Sector Dataset 尚无 factory 分支或专用接线。

Tushare 相关接口的既有实测显示：当前账户对 `index_classify`、`index_member` 等最小请求无权限；概念候选仍需独立验证权限、历史和口径。见 `docs/research/tdx-and-market-intelligence-data-source-capability-research-2026-08-11.md:82-101`、`:120-131`。这是当前凭据状态，不代表平台永久不具备能力。

TDX `.day` 只含日期、OHLC、成交额、成交量，见 `apps/pipeline/src/invest_pipeline/adapters/tdx_offline/README.md:20-36`；本地其他板块缓存没有一手稳定 schema，见 `docs/research/tdx-and-market-intelligence-data-source-capability-research-2026-08-11.md:59-66`，故本 Slice 不重新实施 TDX 日线，也不把未知缓存准入。

## 5. WorkBuddy Connector / Tool 五态矩阵

WorkBuddy connector 是外部任务工具，不是 `invest_pipeline.provider_catalog` 中的内部 Provider。二者必须保留不同 producer、hash 和 lineage；当前 DataRequest artifact 只是允许 connector，并不等于生产准入。

### 5.1 `sector-ranking`

| 外部来源 / tool | declared | constructible | wired | probe_verified | production_admitted | 建议 |
|---|---:|---:|---:|---:|---:|---|
| `westock-mcp.data_sector(mode=ranking, kind=industry)` | 是 | 是 | 是 | 是 | 否 | `research_only` |
| `westock-mcp.data_sector(mode=ranking, kind=concept)` | 是 | 是 | 是 | 是 | 否 | `research_only` |
| `westock-mcp.tool_filter + data_kline` 聚合 `cje/bd_zdf` | 间接 | 是 | 否（非单一固定 tool 合同） | 部分 | 否 | `research_only`，当前不得作为 fallback |
| `tdx-connector` 板块排行/聚合 | 是（connector） | 是 | 是（允许列表） | 部分样本 | 否 | `research_only` 辅助核对，不是排名主源 |
| `mx-ds-mcp` | 仅全局 approved | 当前 session 否 | 否（sector artifact 未允许） | 否 | 否 | `reject` 当前会话 |

westock 正向证据：2026-09-04 早期探针曾得到 Industry top20 字段 20/20 完整、Concept 802/802 完整，`turnover` 与 quote 的 amount 机械换算一致。见共享目录相对路径 `workbuddy/strategy/results/sector-coverage-closure-20260904.ready/coverage-report.md:24-35`；该文件 SHA-256 为 `a48d90437b122877871aa691ac112b42a3964b8aefcf5e9e222164ace9601f7c`（本次重新计算，若目录后续更新必须重算）。

但更新后的缺口修复探针推翻了其历史 `as_of` 可用性：`date=2026-09-02` 与 `2026-09-03` 返回相同内容，且实际对应 09-04；`limit` 也不生效。见 `workbuddy/strategy/results/industry-concept-coverage-remediation-20260904.ready/coverage-report.md:78-86`，报告 SHA-256 `83cedd4272097e36b748980f265a5cfb5bcc8e1b4a767cb3b2e0eb29270e72c3`。所以早期“盘前推断 as_of”不能作为生产日期证据。

聚合路径只在 11 个采样组中为 2 组完成 `cje`，`bd_zdf` 是成分等权派生而非原生板块口径，不能替代要求的全量排行。见同报告 `:43-55`、`:80-92`。

### 5.2 `sector-constituents`

| 外部来源 / tool | declared | constructible | wired | probe_verified | production_admitted | 建议 |
|---|---:|---:|---:|---:|---:|---|
| `westock-mcp.data_sector(mode=constituent, date=...)` | 是 | 是 | 是 | 是 | 否 | `research_only`：日期/名称可用，symbol 失真 |
| `westock-mcp.tool_filter(universe, date)` | 间接 | 是 | 否（artifact 只声明 connector） | 是 | 否 | `research_only`：symbol 可用但静默排除和截断 |
| `westock-mcp.data_search + data_kline` 缺口恢复 | 间接 | 是 | 否 | 小样本 | 否 | `research_only`：人工多工具恢复，不是完整快照接口 |
| `tdx-connector.tdx_screener` | 是（connector） | 是 | 是 | 是，小样本 | 否 | `research_only`：当日推断型时点、分类/代码口径未冻结 |
| `tdx-connector` F10 成分 | 是（connector） | 是 | 是 | 是，失败 | 否 | `reject` 当前功能：503/空结果 |

真实证据：

- westock `constituent(date=2026-09-03)` 在 11 组返回日期和名称，但 `symbol` 100% 返回板块码；`tool_filter` 有真实 symbol，却系统性排除 ST/*ST 和北交所。见 `workbuddy/strategy/results/industry-concept-coverage-remediation-20260904.ready/capability-probes.json:55-84`，SHA-256 `bfdcf6f72415542cd0ef1395b1011c53150143d9a49e2ae4aee0c63de96ed7ae`。
- 大 Concept 板块实测 `totalStocks=303`，`limit=60` 被截断；即使提高到 300 也只返回 177 条，报告没有证明分页或全量完成。见同文件 `:20-23`、`:95-100`。
- TDX 单源曾生成 114 行（Area 34、Industry 31、Concept 49）的当日快照并独立复算 hash，但 `as_of` 来自 HQDate/HQTime 和墙钟推断，Concept 的 `bd_code` 未返回，且只覆盖一个 Industry/一个 Concept 样本。见 `workbuddy/strategy/results/sector-coverage-gap-closure-20260904-v2.ready/coverage-report.md:9-30`、`:38-43`，SHA-256 `2229f9bd664d7b966e7e670698dc1b713c44e6837da6523e5900290c513e8c97`。
- westock/TDX 分类体系存在真实不一致样本（纵横通信在申万二级与通达信二级归属不同），不能按名称静默合并。见 `workbuddy/strategy/results/industry-concept-coverage-remediation-20260904.ready/coverage-report.md:65-76`、`:80-84`。

最新 remediation 报告内部还存在统计矛盾：第 40 行称 11 组均交叉验证，阻塞段第 90 行却称 8/11 只有单源；因此即使文件可解析和 hash 可验证，也必须采用较保守的阻塞结论，不能据摘要字段直接准入。见该报告 `:36-55`、`:88-93`。

## 6. 字段、覆盖和时点判定

| Dataset | 字段 | 当前最好证据 | 判定 |
|---|---|---|---|
| ranking | `group` | westock kind 可区分 Industry/Concept | `research_only`；分类字典版本 unknown |
| ranking | `bd_code` / `bd_name` | westock Industry top20、Concept 802/802 曾完整 | `research_only`；需稳定全集和分类版本 |
| ranking | `cje` | westock `turnover` 与 quote amount 曾精确换算，单位万元 | 字段语义可用；历史 `as_of` 不可用使 dataset 不准入 |
| ranking | `bd_zdf` | westock `changePct` 可得 | 最新值可用；指定历史日期静默失效，dataset 不准入 |
| constituents | `symbol` / `name` | westock 名称完整但 symbol 错；tool_filter/TDX symbol 可得 | 只能研究拼接；无单一路径全量证明 |
| both | `as_of` | westock constituent 有显式日期；ranking 无显式日期；TDX 当日为推断 | 不满足同一可信 cutoff |
| both | 分页/样本 | Concept ranking 曾返回 802 全量；tool_filter 大板块截断 | ranking limit 不可控；constituents 无完整分页证明 |

`DataBundle.pagination.complete=false` 会 fail closed（`packages/domain/src/invest_domain/strategy/data_acquisition.py:607-628`），但 connector 报告必须先能证明 complete；不能将“接口返回了若干行”等同完成分页。

## 7. 频率限制、配额与授权边界

| 来源 | QPS / 并发 | 日配额 | `Retry-After` | 本次观测 | 授权/许可 | 判定 |
|---|---|---|---|---|---|---|
| westock-mcp | unknown | unknown | unknown | 同一会话后段出现持续 service error；无法证明是否限流 | session 可调用；数据使用/缓存/再分发边界 unknown | 不得批量生产 |
| tdx-connector | unknown | unknown | unknown | 当前样本调用成功；F10 能力 503/未注册 | session 可调用；在线协议、缓存和再分发边界 unknown | 不得批量生产 |
| Tushare 当前账户 | unknown（本 Slice 未复测） | 与积分/权限相关，具体 unknown | unknown | `index_classify/index_member` 既有最小请求无权限 | 当前凭据不足；许可/再分发需单独确认 | 当前拒绝 |
| TDX 本地文件 | 本地读取，无 API QPS | 不适用 | 不适用 | 仅 `.day` 已验证 | 只读本地使用边界仍需确认；禁止外部分发 | 与本 Slice Dataset 不匹配 |

本仓库的通用 Provider error 已能识别 HTTP 429，例如 Tushare client 的 retryable status 包含 429，见 `apps/pipeline/src/invest_pipeline/adapters/tushare/client.py:85`、`:402`；这不等于 WorkBuddy connector 已具备受控退避或配额管理。

**停止条件：** 在真实探针给出 QPS/并发/配额前，不执行全量重复采集；若出现 service error、429、超时、无 `Retry-After` 或连续两次结果规模不一致，停止当前批次并记录 `BLOCKED/RATE_LIMITED`，不得自动切源或从头重跑。

## 8. Dataset 准入决定

### 8.1 `sector-ranking`：`research_only`

建议主研究源：`westock-mcp.data_sector(mode=ranking)`；TDX 只作抽样核对，不作为 fallback。

生产准入前必须同时满足：

1. Industry、Concept 都有冻结分类版本和期望全集；
2. 每次响应携带可验证的显式交易日/收盘时点，且 `date` 参数真实生效；
3. `bd_code/bd_name/cje/bd_zdf` 100% 完整，`cje` 单位机械复算；
4. 完整分页或全集数量可证明，重复调用集合/hash 稳定；
5. QPS、并发、配额、退避和授权边界有一手证据；
6. 失败时整体 fail closed，不用 TDX 或逐股聚合静默替代字段口径。

任一条件不满足即停止；不得进入 evaluator。

### 8.2 `sector-constituents`：`research_only`

当前没有可选生产主源或 fallback。westock 和 TDX 都只能作独立研究证据，不允许静默拼成“单源快照”。

生产准入前必须同时满足：

1. 明确并冻结 Industry/Concept 分类供应商与版本；
2. 每条记录有稳定 `group/bd_code/symbol/name/as_of`；
3. 包含 ST/*ST、北交所、停牌等边界，全集数量可证明；
4. 历史/当日 snapshot date 为接口显式字段，不依赖墙钟或行情值推断；
5. 无截断，分页完成可机械验证；
6. `(group,bd_code,symbol)` 唯一、快照 hash 双实现复算一致；
7. QPS、配额和授权边界有一手证据。

任一条件不满足即停止；不得用名称跨分类体系匹配、不得以当前成分回填历史。

## 9. 预采集决策

**本轮不批准预采集。** 原因不是预采集没有价值，而是两个 Dataset 尚无准入来源：现在落库只会把不可信时点、截断和跨分类拼接固化成系统事实。

来源获准后，第一候选应是 `sector-constituents` 的每日收盘快照，因为它时点敏感、历史无法事后可靠补齐，且会被排序和下游股票筛选重复使用。届时只做单 Dataset 垂直切片，并复用现有 request/attempt/batch、hash 和幂等能力；不新建通用限流、checkpoint、全局路由或对象存储。该边界与 `docs/plan/invest-infra-candidate-strategies-mvp-plan-v1.0.md` 的 Slice 1C，以及当前 ACTIVE 的 `docs/plan/invest-infra-target-dataset-source-admission-plan-v1.0.md` 的 DS-0～DS-2 和延期边界一致。

## 10. 下一步最小任务

1. **策略治理先行：** 形成并激活新的不可变收窄 StrategyVersion；当前 active 仍是 2.0.0，不能用测试 profile 代替正式策略身份。
2. **Ranking 定向探针：** 只验证 Industry/Concept 全集、显式 `as_of`、单位、重复 hash、限频/配额；若 westock 无法返回显式日期，则寻找新的候选源，而不是继续包装现接口。
3. **Constituent 定向探针：** 优先验证具有单一分类体系和显式 snapshot date 的结构化源；Tushare 权限若变化，可重试 `index_classify/index_member`，Concept 需独立来源与历史边界。
4. **授权评审：** 由数据源 owner/Ops 提供许可、缓存、内部使用、再分发和凭据权限结论；未知不得默认为允许。
5. **重新作 Gate B2A：** 两个 Dataset 分别给出 `admit/research_only/reject`；只有 `admit` 才另立实现切片。

## 11. 证据清单与验证

### 仓库一手证据

- `apps/pipeline/src/invest_pipeline/provider_catalog.py`
- `apps/pipeline/src/invest_pipeline/provider_factory.py`
- `apps/pipeline/src/invest_pipeline/provider_routing/datasets.py`
- `apps/pipeline/src/invest_pipeline/provider_routing/selection.py`
- `apps/pipeline/src/invest_pipeline/provider_quality.py`
- `apps/pipeline/src/invest_pipeline/provider_health.py`
- `apps/pipeline/src/invest_pipeline/integrations/sector_evaluator.py`
- `packages/domain/src/invest_domain/strategy/data_acquisition.py`
- `config/data-acquisition-definitions/sector-strength-ranking/1.0.0.json`
- `docs/validation/data-admission-checklist.md`
- `docs/plan/invest-infra-candidate-strategies-mvp-plan-v1.0.md`

### WorkBuddy 实测报告（共享根目录相对路径）

| 文件 | SHA-256 |
|---|---|
| `workbuddy/strategy/results/industry-concept-coverage-remediation-20260904.ready/coverage-report.md` | `83cedd4272097e36b748980f265a5cfb5bcc8e1b4a767cb3b2e0eb29270e72c3` |
| `workbuddy/strategy/results/industry-concept-coverage-remediation-20260904.ready/coverage-report.json` | `267a00430050f672ae82fadae10d17657992e6b7fe165dd902dd8497ab90defb` |
| `workbuddy/strategy/results/industry-concept-coverage-remediation-20260904.ready/capability-probes.json` | `bfdcf6f72415542cd0ef1395b1011c53150143d9a49e2ae4aee0c63de96ed7ae` |
| `workbuddy/strategy/results/sector-coverage-gap-closure-20260904-v2.ready/coverage-report.md` | `2229f9bd664d7b966e7e670698dc1b713c44e6837da6523e5900290c513e8c97` |
| `workbuddy/strategy/results/sector-coverage-gap-closure-20260904-v2.ready/capability-probes.json` | `d2ce1f00243bf76fe2e9f3ba8abdb8fc58697ff935911c8319e30adf6b8ced4d` |
| `workbuddy/strategy/results/sector-coverage-closure-20260904.ready/coverage-report.md` | `a48d90437b122877871aa691ac112b42a3964b8aefcf5e9e222164ace9601f7c` |

验证命令（只读）：

```bash
sha256sum <上述共享文件>
python -m json.tool <coverage-report.json> >/dev/null
python -m json.tool <capability-probes.json> >/dev/null
rg -n "sector-ranking|sector-constituents|stock_block_memberships" \
  config packages/domain/src apps/pipeline/src docs/plan docs/validation
git diff --check -- docs/research/sector-dataset-source-admission-20260905.md
```

## 12. 最终 Gate 判定

```text
Gate B2A = BLOCKED
sector-ranking = research_only
sector-constituents = research_only
precollection = not authorized
formal candidate generation = prohibited
```

解除阻塞所需证据已限定在本报告第 8 节，不应通过扩大平台范围、重复实施 TDX 日线或静默多源拼接绕过。
