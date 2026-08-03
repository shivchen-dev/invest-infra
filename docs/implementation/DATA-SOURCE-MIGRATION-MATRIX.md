# DATA-SOURCE-MIGRATION-MATRIX

> 文档版本：v0.1
> 日期：2026-07-30
> 适用范围：`invest-infra-v2` M0 → M1 过渡期（Provider 选型未冻结）
> 输入来源：ARC 已核实的归档系统事实清单
> 边界参考：`docs/adr/0003`、`docs/adr/0004`、`docs/adr/0005`、`docs/adr/0009`、`docs/adr/0010`、`docs/implementation/M0-DECISIONS.md`、`docs/archive/2026-08-02-stage1/invest-infra-v2-etf-vertical-slice-plan.md` §4

## 0. 文档目的与边界

本文件不是 ARC 归档索引，也不是迁移脚本；它只回答三件事：

1. 哪些归档数据源可以进入 v2、以什么角色进入。
2. 从归档字段到 v2 领域契约（`ProviderBatch` / `Instrument` / `DailyBar`）的映射差异。
3. 哪些能力属于“迁移适配边界与可复用 ETF Provider 基础能力”，哪些必须重写或禁止迁移。

不包含：

- 任何对真实凭据的复制、回贴或打印。
- 对归档脚本的直接复用。
- 对价格、SLA、限额或合同关系的编造。

Provider 选型在 ADR-0003 与 M0-DECISIONS 未决事项 O-1 中显式仍未冻结。
本文件记录的**只是适配矩阵**，不是“已选定 Provider”的承诺。下文所有
`推荐角色`列出的角色是在当前归档事实下的合理分组；任何最终切换需以新
ADR/PR + 用户确认（O-1）为准。

## 1. 归档源事实摘要（ARC 提供，禁止再访问归档目录）

| 归档源 | 归档代码位置（仅作为存在性证据，不复制） | 认证变量 | 默认端点（已存在代码中） | 备注 |
|---|---|---|---|---|
| AkShare | `data-pipeline/src/collector/etf.py`、`data-pipeline/src/collector/quotes.py`、`scripts/save_trading_calendar.py` | `AKSHARE_TOKEN` | 由 SDK 内部决定，未在归档代码中显式记录固定端点 | 归档记录存在限流/阻断风险 |
| CifangQuant | `data-pipeline/src/collector/cifang.py`、`data-pipeline/src/config.py`、`scripts/cron_etf_kline_evening.py`、`scripts/sync_cifang_backfill.py` | `CIFANG_TOKEN` | `https://www.cifangquant.com/api`（来自归档 `src/config.py`） | 旧实现默认 `qfq` 复权 |
| RssCast | `data-pipeline/src/collector/rsscast.py` | 归档代码中存在鉴权参数（具体变量名需 O-1 验证后再冻结；本矩阵不复制） | 归档未冻结固定端点 | 主要覆盖股票/指数 MCP 行情 |
| quicktiny MCP | 归档中用于报告/市场快照类能力 | 归档鉴权方式待 O-1 验证后冻结 | 归档未冻结固定端点 | 不属于标准 ETF 日线 Provider |

> 上述表格只引用 ARC 已核实事实，不重复归档目录内容，也不在仓库中粘贴
> 任何归档源码片段、API 路径变体或私钥示例。

## 2. 能力矩阵

| 能力 | AkShare | CifangQuant | RssCast | quicktiny MCP |
|---|---|---|---|---|
| ETF 主数据（symbol/exchange/list_date/status） | ✓ 已观察到覆盖 | ✓ 已观察到覆盖 | ✗ 未观察到 | ✗ 未观察到 |
| ETF 日行情（按 ADR-0005 仅 `adjustment=none`） | ✓ 已观察到覆盖 | ✓ 已观察到覆盖（旧默认 `qfq`，必须显式切到 `none` 才能进入 v2） | ✗ 已声明不能假定为 ETF 日线 | ✗ 不属于 ETF 日线 Provider |
| ETF 交易日历 | ✓ `scripts/save_trading_calendar.py` 表明归档有版本化日历逻辑 | ✗ 未观察到 | ✗ 未观察到 | ✗ 未观察到 |
| 指数行情 | ✓ 间接（聚合库，未作为 v2 主源冻结） | ✓ 间接（与 ETF 数据共用接口，已观察到） | ✓ 主用途 | ✗ 未观察到 |
| 股票行情 | ✓ 间接（聚合库，未作为 v2 主源冻结） | ✗ 不在归档用途内 | ✓ 主用途 | ✓ 间接 |
| 研究/报告/快照 | △ AkShare 可间接拼装，不作为生产路径 | ✗ 不在归档用途内 | △ 仅行情片段 | ✓ 主用途 |
| 鉴权方式 | 归档代码中存在 `AKSHARE_TOKEN`，具体协议待 O-1 确认 | 归档代码中存在 `CIFANG_TOKEN` 头注入 | 待 O-1 确认 | 待 O-1 确认 |
| 限频/并发/SLA | 归档记录有限流与阻断风险 → 不可作为生产 SLA 源 | O-1 待用户/组织确认 | 待 O-1 确认 | 待 O-1 确认 |
| 旧默认值 → 复权口径 | 未在 v1 中作为生产复权源 | 默认 `qfq` → 必须经新 ADR 切到 `none` 才能进入 v2 | n/a | n/a |

> `✓` 表示 ARC 已在归档代码或文档中观察到该能力存在；
> `△` 表示可在归档代码中观察到但不进入 v2 生产路径；
> `✗` 表示未观察到或已声明不能假定。

## 3. 推荐角色（在 ADR-0003 仍为 `Proposed` 期间）

| 归档源 | v2 推荐角色 | 角色依据 |
|---|---|---|
| AkShare | `research_only` 或 `secondary`（仅在 O-1 用户明确确认授权与限频规则后升级为 `secondary`） | 聚合库、上游稳定性与生产 SLA 不可证明；已观察到限流/阻断风险 |
| CifangQuant | `secondary`（仅在 O-1 用户完成合同/再分发/限频确认后才可启用，绝不直接沿用旧 `qfq` 默认） | 归档观察到 ETF 主数据、历史日 K 与默认端点；旧实现默认 `qfq` 与 M0 ADR-0005 冲突，必须先确定 `none` 语义接口 |
| RssCast | `out_of_scope_for_etf` / 仅作为研究/指数片段（不视为 ETF 日行情 Provider） | 归档覆盖股票/指数 MCP；不得伪造 ETF 日行情能力 |
| quicktiny MCP | `research_only` / 仅报告与市场快照（不视为 ETF 日行情 Provider） | 归档用途即报告/快照，不属于 ETF 日线 Provider；该决策已通过 `invest_pipeline.provider_catalog.QUICKTINY_MCP` 在代码目录中显式声明，`enabled_by_default=False`，能力集仅含 `research` 与 `market_snapshot`，显式排除 `ETF_DAILY_BARS` / `ETF_MASTER_DATA` 等任何 ETF 行情能力 |
| `fixture_dev`（v2 自带、本仓库内置） | `primary`（仅用于 dev/test；M0-CODING-BRIEF 明确禁止 production 路径默认启用） | 内置可重放、无凭据、不发起任何网络请求 |

不预设“已选 primary”的 Provider；M0 阶段任何标注为 `primary` 的 Provider
必须显式经 O-1 用户确认。本矩阵**禁止**把上述“推荐角色”谎称为已冻结。

## 4. 字段映射（归档 → v2 领域契约）

### 4.1 ETF 主数据：归档字段 → `Instrument`

| 归档字段（概念） | v2 `Instrument` 字段 | 映射说明 |
|---|---|---|
| 数字代码（如 `510300`） | `symbol`（字符串） | 必须按 ADR-0004 与 `exchange` 联合规范化；不得脱离 exchange 单独使用 |
| 名称（中文/英文字符串） | `name` | 仅做展示；不得作为业务主键 |
| 交易所（上交所/深交所） | `exchange` 取值 `SSE` / `SZSE` | 必须在领域校验中受限；归档历史中如出现非 SSE/SZSE 标的直接拒绝 |
| 基金类型 / 分类（宽基/行业/主题/商品） | `category`（可选，由 storage schema 字段承载） | 归档 AkShare/Cifang 的分类口径不一，需在 Adapter 中显式归一化，不直接照搬 |
| 跟踪指数代码 | `underlying_index`（可选） | 仅当有强证据时填写；空值允许 |
| 上市日期 | `list_date: date \| None` | 与日历头表联动，O-3 全历史回补起点仍待确认 |
| 退市日期 | `delist_date: date \| None` | 由 storage 主数据版本化保留历史 |
| 状态（活跃/停牌/退市/未知） | `status: active \| suspended \| delisted \| unknown` | AkShare/Cifang 字段名不完全一致，Adapter 必须显式映射并保留 `unknown` 兜底 |
| 跨代码映射 | `provider_symbol_map: dict[str,str]` | 不重写主键；在 storage 侧 `core.instruments` 额外保留 |
| 来源 Provider | `source_provider`、`source_updated_at` | 由 application service 在事务内回填，Adapter 不持这些字段 |

> v2 的 `Instrument` 标识必须升级为 UUID 主键（M0-CODISIONS §6），
> 归档阶段的 `(symbol, exchange)` 在 v2 中只作为稳定业务键存在，不直接
> 作为存储主键。Adapter 输出仍以 `(exchange, symbol)` 锚定。

### 4.2 ETF 日行情：归档字段 → `DailyBar`

| 归档字段（概念） | v2 `DailyBar` 字段 | 映射说明 |
|---|---|---|
| 日期 | `trade_date: date`（Asia/Shanghai 本地日） | 归档接口多以字符串返回，Adapter 必须规范化为 `date`；不得用执行时间代替 |
| OHLC | `open/high/low/close: Decimal` | ADR-0005 §3：仅 `adjustment=none` 时入生产；价格严格 > 0；`high >= max(open, close, low)`；`low <= min(open, close, high)` |
| 昨收 | `prev_close: Decimal \| None` | 归档有的归档点不返回；缺失视为正常 |
| 成交量 | `volume: Decimal \| None`，单位“份” | 归档口径需在 Adapter 中按 ADR-0005 §3 固定语义换算；不得用 `int` |
| 成交额 | `amount: Decimal \| None`，单位 CNY | 同上 |
| 复权字段（`qfq/hfq`） | v2 不进入生产；Adapter 必须显式拒绝 qfq/hfq 写入 | 旧 Cifang 默认 `qfq` 必须经新 ADR 处理；在 v2 默认 Provider 上 `adjustment` 锁死 `none` |
| 停牌/缺失规则 | `trading_status: normal \| suspended`；缺失的 date 不创建合成 bar | 由 ADR-0005 §6、§7 固化 |
| 来源元信息 | `source_provider`、`source_batch_id`、`observed_at`、`revision`、`row_hash` | 由 application service 在同一事务中回填；Adapter 只产出数据 + 元数据 |
| 批次元信息 | `ProviderBatch.provider_key / request_id / requested_at / received_at / records / raw_payload_hash / warnings` | 归档脚本通常把响应直接落 JSON；v2 必须按 ADR-0007 规范计算 hash，并把原始响应摘要写入 `raw.provider_batches` |

### 4.3 交易日历与时区

| 归档字段 | v2 字段 | 映射说明 |
|---|---|---|
| 归档日历（如 `save_trading_calendar.py`） | `exchange`、`date`、`open/closed`、`calendar_key`、`calendar_version/content_hash` | 由 ADR-0004 §7 强制版本化；Adapter 不得以自身日历替代版本化日历 |

### 4.4 `ProviderBatch` 元数据（新增于 ADR-0003）

| 元数据 | 含义 | 来源 |
|---|---|---|
| `provider_key` | 数据源标识 | `akshare` / `cifang` / `rsscast` / `quicktiny_mcp` / `fixture_dev` |
| `request_id` | 供应商回执 ID（若提供） | 仅 Adapter 可填 |
| `requested_at` / `received_at` | UTC `datetime` | 由 application service 或 Adapter 内部 `datetime.now(UTC)` 记录 |
| `records` | 标准领域对象列表 | 仅领域类型，不暴露 SDK 类型 |
| `raw_payload_hash` | 原始响应字节级 SHA-256 | 由 Adapter 计算；大响应按 ADR-0003 §6 处理 |
| `warnings` | 解析告警 | Adapter 记录“字段缺失/类型不匹配/未知字段” |

Adapter 输出**只**含上述元数据 + 标准领域对象；不暴露 SDK 类型、HTTP
response 或数据库 row。

## 5. 可迁移、可复用、可重写与禁止项

### 5.1 可迁移（适配边界、配置契约、目录抽象）

- `akshare`、`cifang`、`rsscast`、`quicktiny_mcp` 四个 Provider Key 与能力
  声明（Quicktiny MCP 的 `research_only` 声明已落地为代码目录，承载于
  `apps/pipeline/src/invest_pipeline/provider_catalog.py` 与对应单元测试
  `apps/pipeline/tests/unit/test_provider_catalog.py`；其余 Provider 的能
  力声明待对应 Adapter 落地后再补齐，避免在没有占位实现的源码里声称
  能力）。
- 配置驱动的 Provider Registry/Factory、`fixture_dev` 与每个归档源对应
  的 redacted config 模板。
- `ProviderAuthenticationError` / `ProviderRateLimitError` 等错误分类
  （与计划 §4.4 对齐），来自计划/ADR；不属于归档实现。
- Domain Port `EtfMarketDataProvider` 的本地 Protocol 占位（位于
  `apps/pipeline/src/invest_pipeline/providers/`，待 Phase 1-B 落地后迁
  回 `packages/domain`）。

### 5.2 可复用（仅作为 ETF Provider 基础能力，非业务实现）

- Adapter 的分层：`client.py` 隔离 HTTP/SDK；`mapper.py` 处理字段映射；
  `provider.py` 暴露领域接口；`config.py` 暴露 redacted settings。
- 错误分类的命名空间 `invest_pipeline.providers.errors`。
- Redacted `BaseSettings` 默认禁用任何真实网络源。

### 5.3 必须重写（不可直接搬迁归档实现）

- 归档脚本中 `sleep`/重试循环应替换为 Adapter 内部限流策略与 ADR-0003
  §8 描述的测试时 fake transport。
- 旧的 cron/systemd/subprocess 调度（`cron_etf_kline_evening.py` 等）
  不得在 v2 沿用；统一由 Dagster 作业承担。
- 旧的数据库直连写入、Redis 缓存、MinIO 对象存储依赖全部不进入 v2；
  v2 走 `raw.provider_batches` + PostgreSQL JSONB（大响应上限 + 摘要 +
  哈希，由 ADR-0003 §6 约束）。
- 复权：`qfq/hfq` 默认值必须丢弃并经新 ADR 才能启用（ADR-0005）。

### 5.4 禁止项

- 禁止访问 `invest-infra-archive-20260730-095515` 任何位置；本矩阵已
  以 ARC 事实为唯一输入。
- 禁止把任何真实 token、Cookie、私钥或内部 URL 提交到仓库；`.env.example`
  仅放变量名与脱敏模板（`*TOKEN=__SET_VIA_PLATFORM_SECRET__`）。
- 禁止在仓库中粘贴归档源码片段、归档脚本逻辑、归档表结构名。
- 禁止把 AkShare 标为生产 SLA 数据源；其限流/阻断风险必须出现在
  `providers/akshare/README.md` 与本矩阵的 §2/§3。
- 禁止把 Cifang 默认 `qfq` 直接沿用；M0 已冻结首期 `adjustment=none`。
- 禁止 RssCast 或 quicktiny_mcp 在能力声明中声称支持 `ETF_DAILY_BARS`；
  测试必须直接断言它们**没有**该能力。Quicktiny MCP 的代码级声明已通
  过 `apps/pipeline/tests/unit/test_provider_catalog.py` 直接断言
  `ProviderCapability.ETF_DAILY_BARS` 不在能力集中。
- 禁止把 Plan 文档示例阈值（流动性金额、波动率、上市天数等）当作生产
  参数；M0-DECISIONS §4 O-5 仍未决。
- 禁止宣告“Provider 已选定/已接入生产 SLA”；O-1 仍阻塞。

## 6. 凭据迁移规则

- **只迁移变量名和脱敏模板**。归档代码中的 `AKSHARE_TOKEN`、
  `CIFANG_TOKEN`、`RSSCAST_*`、`QUICKTINY_MCP_*`（归档中的具体变量名
  需 O-1 验证后冻结；本矩阵先行声明 Key 占位）仅以变量名形式进入
  `.env.example`。
- **不复制**任何真实 secret、Cookie、token、Authorization 头、内部 IP、
  私钥或归档 fixture 的真实响应。
- **不打印**：Adapter 与 settings 的 `__repr__` / `__str__` / 日志输出必
  须显式掩盖 token；测试用例包括“构造 settings 时不能把 token 写入
  repr/log”。
- **不提交**：`.env`、归档 fixture 中的真实凭据或机构/合同标识一律不得
  进入 Git。
- v2 默认所有真实网络源 `enabled=false`；`fixture_dev` 是唯一默认启用
  的 Provider。任何把真实 Provider 切到 `enabled=true` 的操作必须显式
  改动部署平台的 Secret 注入配置并经 ADR/PR 记录。

## 7. v2 中最小 Provider 目录（实现范围）

```text
apps/pipeline/src/invest_pipeline/
├── config.py                 # 已有 Settings（pipeline 级）
├── providers.py              # 旧 MockInstrumentProvider，保留 import 兼容
├── definitions.py            # 已有
├── assets.py                 # 已有
└── providers/                # 新增：M0 → M1 过渡期最小 Provider 基建
    ├── __init__.py           # 对外只导出 capabilities/registry/factory/error
    ├── capabilities.py       # ProviderCapability / ProviderDeclaration / ProviderRole
    ├── errors.py             # Provider*Error 分类（与计划 §4.4 对齐）
    ├── settings.py           # 默认禁用 / 变量名 / redacted 模板
    ├── registry.py           # ProviderRegistry：declaration 注册 + factory 查询
    ├── factory.py            # build_provider_from_settings()；未知 Provider 报错
    ├── fixture_dev.py        # FixtureDevEtfMarketDataProvider（dev/test 用）
    ├── akshare/
    │   ├── __init__.py
    │   ├── config.py         # AkshareSettings（redacted；默认禁用）
    │   ├── adapter.py        # AkShareAdapter：占位 + 显式 NotImplementedError 指向 O-1
    │   └── README.md         # 风险与角色记录
    ├── cifang/
    │   ├── __init__.py
    │   ├── config.py         # CifangSettings（adjustment 锁死 "none"；默认禁用）
    │   ├── adapter.py        # CifangAdapter：占位 + 显式 NotImplementedError 指向 O-1
    │   └── README.md         # 风险与角色记录（旧默认 qfq 的禁止沿用）
    ├── rsscast/
    │   ├── __init__.py
    │   ├── declaration.py    # 仅声明 stock/index；不声明 ETF_DAILY_BARS
    │   └── README.md
    └── quicktiny_mcp/
        ├── __init__.py
        ├── declaration.py    # 仅声明 research/market_snapshot；不声明 ETF_DAILY_BARS
        └── README.md
```

测试位于 `apps/pipeline/tests/`：

```text
apps/pipeline/tests/
├── __init__.py
├── unit/
│   ├── __init__.py
│   ├── test_provider_capabilities.py
│   ├── test_provider_registry.py
│   ├── test_provider_factory_defaults.py     # 默认禁用真实源、未知 Provider 报错
│   ├── test_fixture_dev_provider.py          # fixture_dev 可重放
│   ├── test_akshare_adapter_contract.py       # 占位 + 风险/角色声明 + 凭据不外泄
│   ├── test_cifang_adapter_contract.py        # 锁死 adjustment=none；占位 + 风险声明
│   ├── test_rsscast_capabilities.py           # 断言不含 ETF_DAILY_BARS
│   ├── test_quicktiny_mcp_capabilities.py     # 断言不含 ETF_DAILY_BARS
│   └── test_settings_redaction.py             # 凭据不出现在 repr/str/log
```

## 8. 仍需用户确认的 Provider 事项（与 O-1 对齐）

下表是 M0 阶段已知阻塞“真实 Provider 接入”的清单。本仓库当前默认
`fixture_dev`；任意一项未确认前不得解除 `enabled=false` 默认值。

| 项 | 关联源 | 阻塞 |
|---|---|---|
| Provider 法定/产品名称及首选接入方式 | 全部 | 选型 |
| 合同、再分发与生产自动化使用边界 | 全部 | 选型 |
| `adjustment=none` 语义证据（谁能证明 v1 接口中的“未复权”=未复权） | Cifang | 数据契约 |
| AkShare 限频/阻断风险下的实际 SLA 与退避规则 | AkShare | SLA |
| RssCast、quicktiny_mcp 鉴权方式与端点 | RssCast / quicktiny_mcp | 选型 + 合同 |
| `configured_backfill_start` 与 ETF 历史起点 | AkShare / Cifang | O-3 |
| 收盘 cutoff | AkShare / Cifang | O-4 |
| 候选池阈值（不在本矩阵范围内） | n/a | O-5 |
| 数据质量数值阈值（不在本矩阵范围内） | n/a | O-6 |

上述条款中任何一项被关闭前，仓库不得宣告 Provider “已选定/已接入生产
SLA”。本矩阵的所有 `推荐角色` 也仅是“归档事实下的合理分组”，不得被
任何文档误读为终态承诺。
