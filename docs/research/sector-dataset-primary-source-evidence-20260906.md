# Sector Dataset 四源一手核证（DS-0M）

> 日期：2026-09-06（Asia/Shanghai）
>
> 范围：`sector-ranking`、`sector-constituents`；Industry / Concept；TDX Connector、WeStock MCP、MX-DS MCP、Tushare；公开第一方文档、仓库源码与带时间戳的真实响应证据
>
> 性质：来源可行性证据；凭证仅由 `CredentialStore` 在进程内读取，不进入命令参数、输出或报告；不作 `admitted` 决定

## 1. 结论摘要

四源核证没有发现可以直接通过 Gate DS-FM 的生产来源。当前结论是：

1. **Tushare TDX 板块组**（`tdx_index + tdx_daily + tdx_member`）是官方文档层唯一接近同时覆盖两个 Dataset 的单一路径；**Tushare DC 板块组**可覆盖 Industry/Concept 排名与 Concept 成分，但 `dc_member` 官方页面没有证明 Industry 成分；
2. **TDX Connector** 可核证具名板块行情和具名板块分页成分，但没有 Industry/Concept 全集枚举，且成分时点不显式；
3. **WeStock MCP** 可核证 Industry/Concept 排名字段与清单，但 ranking 的历史 `date` 静默失效；成分接口的 `symbol` 错误，替代工具又排除 ST/北交所并发生截断；
4. **MX-DS MCP** 只核证了具名申万 Industry 的行情和一个 180 行成分样本；未核证 Industry 全集、Concept、稳定板块代码、分页与许可。

Tushare TDX 组覆盖 Industry / Concept，能提供显式 `trade_date`、板块代码/名称、涨跌幅、成交额及带交易所后缀的证券代码。DC 组的排名覆盖 Industry / Concept，但成员页只确认 Concept。相比 WeStock/TDX Connector，两组在已确认范围内避免了“排名日期静默失效”和“成分 symbol 错位”，但当前账户曾观测到目标接口权限阻断，尚未得到真实全量响应。

但当前只能判为**具备进一步探针价值的候选**，不能据公开文档直接进入生产：

- 投研系统集中凭证存在且基础 `stock_basic` 调用成功；既有最小认证探针曾观测到 TDX/DC 六个目标接口均返回 Tushare 业务码 `40203`。因未保留可复算的脱敏响应，本轮把它记为 `blocked_observed`，不提升为完整 B 级证据；
- 文档没有证明指定日期的全量规模、重复 hash、分类修订规则和历史起点（TDX）；
- Tushare 数据服务协议把许可限定为个人、不可转让、非商业、有期限、仅个人查看；没有明确授权自动化生产入库、团队共享或再分发；
- 协议还明确第三方数据的使用与收费由第三方解释，TDX/DC 上游许可仍是独立 `unknown`。

因此：**Gate DS-FM 仍为 `BLOCKED`。** 本轮关闭了四源的真实能力边界、已知分类命名空间和 Tushare 平台级许可/频次事实；仍未关闭“任一单源可完整交付两个 Dataset”“真实全量与重复 hash”“明确自动化留存许可”三个准入条件。

## 2. 当前合同基线

当前收窄 evaluator 的目标组为 `industry`、`concept`，`sector-ranking` 实际读取：

| 目标字段 | evaluator 语义 |
|---|---|
| `group` | `industry` 或 `concept` |
| `bd_code` / `bd_name` | 稳定板块身份 |
| `cje` | 正数成交额，用于组内 Top 20 与 50% 归一化评分 |
| `bd_zdf` | 涨跌幅，用于 50% 归一化评分 |
| `as_of` | 必须与请求日期相同 |

`sector-constituents` 实际读取 `group / bd_code / symbol / name / as_of`，并要求成分只属于已选板块、`(group, bd_code, symbol)` 唯一。代码依据：

- `apps/pipeline/src/invest_pipeline/integrations/sector_evaluator.py:148-192`
- `apps/pipeline/src/invest_pipeline/integrations/sector_evaluator.py:195-235`
- `apps/pipeline/src/invest_pipeline/integrations/sector_evaluator.py:253-285`

注意：已部署 Definition 1.0.0 仍属于 Strategy 2.0.0，并额外要求 `zgb`；本报告只评价当前计划中的 Industry/Concept 收窄目标，不把旧 Definition 当成新版本已经获批。

## 3. 证据口径与登记

### 3.1 证据等级

| 等级 | 含义 | 可关闭的结论 |
|---|---|---|
| A | 数据服务所有者的官方文档/协议，记录 URL、抓取时间和内容哈希 | 文档字段、参数、页面声明的限量/频次/许可 |
| B | 带工具名、参数、调用时间和稳定结果的真实响应记录，文件内容有 SHA-256 | 本次响应的字段、样本规模、错误和可达性；不能外推未探测日期或全量 |
| C | 当前仓库源码/不可变合同，记录 commit、代码路径和内容哈希 | 本系统消费约束和允许列表；不能证明外部来源能力或许可 |
| U | 没有 A/B 级证据，或现有证据不足以支撑外推 | `unknown`，不得推断为支持或不支持 |

本报告把 Connector/MCP 的时间戳响应记录视为其**实际输出证据**，而不是官方产品文档。由于本轮运行上下文没有注入 TDX、WeStock、MX 工具，未新增这三源的现场调用；这不等于来源不可用。公开网页检索工具也返回“未注册处理器”，故没有把搜索失败解释为不存在官方文档。

### 3.2 证据登记表

共享响应根目录：`/home/claw/windows-ltsc/shared/workbuddy/strategy/results/`。

| ID | 等级 | 探针/抓取时间 | URL 或文件路径 | SHA-256 | 用途 |
|---|---|---|---|---|---|
| R-CODE-1 | C | 2026-09-06 取证；commit `eb66f7cbcd5ff6886cdda4d641f6b2288c5ae77a` | `apps/pipeline/src/invest_pipeline/integrations/sector_evaluator.py` | `03ad0f0a343fae7d76ea9f4fbe6828faa7b1c0bc9711b0334db29918f2af5e74` | 两个 Dataset 的实际字段、同日、全组、唯一性和成分绑定要求 |
| R-CODE-2 | C | 同上 | `packages/domain/src/invest_domain/strategy/data_acquisition.py` | `cc4c68bb832c966c48b80269f816b86e21234caea0b7347f49ecfc6b1f4ef400` | WorkBuddy 1.0 只允许 TDX/WeStock/MX；失败尝试错误码合同 |
| R-TWM-1 | B | 2026-09-05 14:55 +08:00 | `sector-new-source-admission-20260905.ready/capability-probes.json` | `2fab442c240fe0b86c707cf084092995ddfc85a8494359067e98202ebafc1825` | TDX 具名 quote/成分页、WeStock ranking、MX 具名/空全集探针 |
| R-WES-1 | B | 2026-09-04 23:26:34 +08:00 | `industry-concept-coverage-remediation-20260904.ready/capability-probes.json` | `bfdcf6f72415542cd0ef1395b1011c53150143d9a49e2ae4aee0c63de96ed7ae` | WeStock date/limit/symbol/ST/BJ 负面边界与分类清单 |
| R-WES-2 | B | 2026-09-04 04:30:09–05:06 +08:00 | `sector-coverage-closure-20260904.ready/capability-probes.json` | `e93d970d8c975a34f41005be279d33b9aa59c66ecabc62efdaad82fef0daed64` | WeStock Industry Top 20、Concept 802 行及 TDX 成分样本 |
| R-MX-1 | B | 2026-09-02 17:08:45–17:14 +08:00 | `data-coverage-active-v2-20260902.delta-v1.ready/capability-probes.json` | `e8d3b17c1c1b8efdaa4053f747c0141e85497a644ac9b2c75d6f15319c11db43` | MX 具名申万 Industry 行情和会话可达性 |
| R-MX-2 | B（历史，带缺陷说明） | 2026-08-28 16:51:30 +08:00 | `data-coverage-active-v2-20260828.ready/_history_v1/capability-probes.json` | `eaee5e7509a077858f0d8b64cfcc55fc9917e2d75e78a15f1c15afb204634f9d` | MX 具名申万 Industry 180 行成分样本；只有 10 行 hash 演示，不能证明契约级全量 hash |
| R-TS-1 | A | 2026-09-06 17:14:13–17:14:15 +08:00 | Tushare 目标接口与协议页面，详见第 11 节 | 逐页列出 | Tushare 字段、单次限量、频次和许可 |
| R-TS-2 | U（既有运行摘要） | 2026-09-06，精确时刻未留存 | 本文件第 11.1 节记录的脱敏认证探针 | 响应正文未留存，无法独立复算 | 当前账户曾观测到访问阻断；不能作为完整 B 级证据，后续应补可复算脱敏存档 |

## 4. 四源逐项核证

### 4.1 总矩阵

| 来源 | `sector-ranking` Industry / Concept | `sector-constituents` Industry / Concept | 分类命名空间 | `as_of` | 分页/全量 | 限流 | 个人非商业自动化、留存、分发 | DS-FM 判断 |
|---|---|---|---|---|---|---|---|---|
| TDX Connector | 具名 Industry/Concept quote 字段可用；无原生全集 | 具名 Industry 可分页；Concept 有 symbol/name 但无显式板块码 | 通达信 Industry `881xxx`、Concept `880xxx`；版本 unknown | quote 显式 `HQDate/HQTime`；成分仅隐含当前 | `pageNo/pageSize/meta.total` 只证明具名板块分页；分类全集 unknown | QPS、日配额、退避 unknown | 全部 unknown | `research_only`；不能单源交付两个 Dataset |
| WeStock MCP | Industry 124 和 Concept 802 的字段样本已核证；ranking 日期不可信 | 原生成分日期可用但 symbol 错；替代工具缺 ST/BJ 且截断 | 申万二级 `pt018...`；聚源概念 `pt02.../indus_...`；版本 unknown | ranking 无可信显式时点；constituent 日期显式 | `limit` 曾静默不生效；Concept 大板块截断，无完整分页证明 | QPS、日配额、退避 unknown | 全部 unknown | `corroborator only`；两个 Dataset 均不准入 |
| MX-DS MCP | 仅具名申万 Industry 的 `成交额/涨跌幅`；全集查询为空；Concept unknown | 仅一个具名申万 Industry 180 行样本；Concept unknown | 样本为申万 Industry，证券码 `.SH/.SZ`；稳定板块 code/version unknown | 具名行情日期显式；成分快照时点隐含 | Industry/Concept 全集、分页、重复 hash unknown | QPS、日配额、退避 unknown | 全部 unknown | `corroborator only`；不可作单一主源或 fallback |
| Tushare TDX 组 | 文档覆盖 Industry/Concept、代码/名称、涨跌幅、成交额 | 文档覆盖 Industry/Concept、证券代码/名称 | TDX `ts_code + idx_type`；类型含行业/概念，版本策略 unknown | 显式 `trade_date` | 1000/3000 单次上限；可按日期/代码分片，无 offset；全量未实测 | 页面无逐接口规则；平台常规数据规则可参考 | 个人、不可转让、非商业、个人查看 confirmed；自动化留存 unknown；分发未获授权 | 文档候选；当前账户 `40203` 为 `blocked_observed` |
| Tushare DC 组 | 文档覆盖 Industry/Concept、代码/名称、涨跌幅、成交额 | Concept confirmed；Industry unknown，`dc_member` 页面只描述概念板块/概念代码 | DC `ts_code + idx_type`；排名类型含行业/概念，成员分类范围未证明，版本策略 unknown | 显式 `trade_date` | 5000/2000/5000 单次上限；无成员计数基准，全量未实测 | 同上 | 同上；东方财富上游权利另为 unknown | Concept 文档候选；不能单源覆盖四个目标 Dataset；历史 `40203` 为 `blocked_observed` |

### 4.2 TDX Connector（R-TWM-1、R-WES-1、R-WES-2）

- **Ranking 字段已核证，全集未核证。** `tdx_quotes(code='880564')` 两次返回一致的 `HQDate=20260904 / HQTime=150006 / Amount=21381732400 / Now / Close`，可机械得到具名 Concept 的 `cje/bd_zdf/as_of`。但 `tdx_lookup_stock` 未返回 880/881 板块全集，不能把具名能力外推为 Dataset 全集。
- **Industry 成分页能力已核证。** `tdx_screener('银行板块成分股', pageNo=1,pageSize=20)` 返回 `meta.total=42` 及 `index_code=881385`；历史响应还记录半导体 185 行、通信设备 90 行完整快照。这里只证明指定板块和当时响应，不证明所有 Industry 分类全集。
- **Concept 身份不闭合。** “人工智能概念板块成分股”返回 `total=1070` 且包含 `*ST康佳A`，但行内无被查询 Concept 的显式 `bd_code`；按名称绑定不能满足稳定身份要求。
- **时点不闭合。** quote 有来源字段时间，screener 成分仅由调用时点推断；不存在本轮证据证明历史成分快照或分类修订规则。
- **频控/许可为 U。** 没有 TDX Connector 所有者发布的 QPS、日配额、自动化、缓存、留存或分发条款。通达信软件或客户端条款不能自动覆盖该 Connector 的数据服务链路。

### 4.3 WeStock MCP（R-WES-1、R-WES-2）

- **覆盖字段不等于可用时点。** Industry 清单实测 124 条；Concept ranking 实测 802/802 行字段完整，`code/name/changePct/turnover` 可映射业务字段。但 Industry ranking 对 `date=2026-09-02` 与 `2026-09-03` 返回逐字段相同，且 leader 对应 09-04 行情，证明历史日期静默失效。
- **成分接口存在结构性身份错误。** 11/11 组 constituent 返回显式 `date=2026-09-03` 和名称，但 `stocks[].code` 100% 重复板块码，不能作为证券 `symbol`。
- **替代路径不能修复全量。** `tool_filter` 返回真实 symbol，却系统性排除 17 只 ST/*ST 和 8 只北交所样本；跨境电商 `totalStocks=303` 在 `limit=60` 时截断，提高到 300 仍只回 177。当前没有可证明完整分页的参数合同。
- **命名空间已识别但版本 U。** Industry 为申万二级 `pt018...`/`sw2_...`；Concept 出现 `pt02...` 与 `indus_...`。没有一手版本号、变更日志、代码复用/退市规则。
- **频控/许可为 U。** 没有 WeStock 服务所有者的一手 QPS、日配额、Retry-After、自动化留存或分发条款。

### 4.4 MX-DS MCP（R-TWM-1、R-MX-1、R-MX-2）

- **具名 Industry 行情已核证。** 2026-09-02 与 2026-09-04 的“半导体(申万)”查询返回成交额和涨跌幅，且与 WeStock 数值在单位换算/舍入后相符；只证明该具名样本。
- **全集未核证。** 2026-09-05 的“不具名全部申万一级行业排行”响应为空，不能推断为产品不支持，也不能视为全集；需要明确枚举 API 或逐项可核验分类字典。
- **成分只有历史单样本。** 2026-08-28 具名半导体查询记录 180 行 `证券代码/证券简称/申万一级行业/纳入日期`，但来源快照 `as_of` 仍由调用上下文隐含，且历史文件明确只有 10 行 hash 演示，不是完整 180 行契约 hash。
- **Concept、分页、稳定板块身份均为 U。** 未取得 Concept 排行/成分、稳定 `bd_code`、分类版本、offset/cursor 或截断信号的一手响应。
- **运行可达性不稳定但根因 U。** 2026-09-02 17:08 会话可调用，另一次会话不可见；2026-09-05 又可调用。这里只记录观测，不推断连接器根因。
- **频控/许可为 U。** 没有 MX 服务所有者的一手 QPS、配额、自动化留存或分发条款。

## 5. 候选一：Tushare TDX 板块接口组

### 5.1 文档确认项（confirmed）

| 合同维度 | 第一方文档事实 | 映射判断 |
|---|---|---|
| 板块全集 | [`tdx_index`](https://tushare.pro/document/2?doc_id=376) 支持 `trade_date`、`idx_type`；输出 `ts_code / trade_date / name / idx_type / idx_count`，类型包括概念板块与行业板块 | 可生成当日 `group / bd_code / bd_name`，并用 `idx_count` 作成分计数对账 |
| 排名行情 | [`tdx_daily`](https://tushare.pro/document/2?doc_id=378) 支持 `ts_code / trade_date / start_date / end_date`；输出 `trade_date / pct_change / amount`，成交额单位为万元 | `pct_change → bd_zdf`；`amount × 10,000 → cje`，单位转换可机械复算 |
| 成分快照 | [`tdx_member`](https://tushare.pro/document/2?doc_id=377) 支持板块代码和交易日期；输出 `ts_code / trade_date / con_code / con_name` | 可映射 `bd_code / as_of / symbol / name` |
| 证券身份 | `tdx_member` 样例含 `000039.SZ`、`603869.SH`、`833171.BJ`，也包含 `ST智知` | 文档样例确认交易所后缀、北交所与 ST 没有被静默排除 |
| 单次限量 | `tdx_index` 1000 行；`tdx_daily` 3000 行；`tdx_member` 3000 行 | 接口页面均说明可按日期或板块代码循环提取，但是否能覆盖所有当日记录仍需真实探针 |
| 权限门槛 | 三个接口页面均写明 6000 积分 | 存在明确访问门槛，不等于当前账户已获得权限 |

### 5.2 尚未确认项（unknown）

- **实际可访问性**：2026-09-06 既有脱敏最小探针中基础 `stock_basic` 成功，但 `tdx_index / tdx_daily / tdx_member` 均返回业务码 `40203`。本轮未读取凭证，也未重放；因响应正文未留存，状态为 `blocked_observed`。
- **历史起点**：三个页面支持日期参数，但未声明最早可用日期。
- **全量分页**：页面没有 offset/page 参数。虽然可以按日期、板块代码分片，仍需证明：当日板块数不超过 1000、单板块成分不超过 3000、所有 `idx_count` 与成员数一致。
- **分类修订**：没有说明板块代码复用、改名、删除、新增及历史修订政策。
- **频率例外**：接口页没有独立 QPS/日配额说明。Tushare 通用频次表对 5000 积分以上的“常规数据”写明 500 次/分钟、常规数据无日总量上限，但未在接口页确认这三个接口是否存在单独覆盖规则。
- **许可**：自动化生产入库、团队共享及衍生结果发布没有明确许可；TDX 作为真实上游的权利边界也没有由其一手条款关闭。

### 5.3 数据流建议（不构成准入）

```text
tdx_index(trade_date, idx_type in {行业, 概念})
  + tdx_daily(trade_date)
  -> sector-ranking

selected tdx_index.ts_code
  -> tdx_member(trade_date, ts_code)
  -> sector-constituents
```

`tdx_index.idx_count` 与逐板块 `tdx_member` 行数必须逐一相等；任何板块缺行情、缺成员、超过单次上限或日期不一致都应整体 fail closed。

## 6. 候选二：Tushare DC 板块接口组

### 6.1 文档确认项（confirmed）

| 合同维度 | 第一方文档事实 | 映射判断 |
|---|---|---|
| 当日板块列表 | [`dc_index`](https://tushare.pro/document/2?doc_id=362) 按 `trade_date` 查询，`idx_type` 包含行业、概念、地域；输出 `ts_code / trade_date / name / pct_change / idx_type` | 过滤行业/概念后可生成 `group / bd_code / bd_name / bd_zdf` |
| 排名行情 | [`dc_daily`](https://tushare.pro/document/2?doc_id=382) 支持日期与板块类型；输出显式 `trade_date / pct_change / amount`，成交额单位为元；历史数据从 2020 年开始 | `amount → cje` 可直接使用；`pct_change → bd_zdf` |
| 历史成分 | [`dc_member`](https://tushare.pro/document/2?doc_id=363) 支持 `trade_date / start_date / end_date / ts_code / con_code`；输出 `trade_date / ts_code / con_code / name`；文档明确起始日期 2024-12-20，但页面描述和示例只说明概念板块 | 能生成显式日期的 Concept `sector-constituents`；Industry 成分能力仍为 unknown |
| 证券身份 | `dc_member` 样例含 `002117.SZ`、`688165.SH`、`873593.BJ` | 文档样例确认稳定交易所后缀及北交所覆盖 |
| 单次限量 | `dc_index` 5000 行；`dc_daily` 2000 行；`dc_member` 5000 行 | 页面允许按日期/代码循环提取；是否完整仍需用板块数和成员数实测 |
| 权限门槛 | 三个接口页面均写明 6000 积分 | 存在明确访问门槛，不等于当前账户已获得权限 |

### 6.2 尚未确认项（unknown）

- **实际可访问性**：2026-09-06 既有脱敏最小探针记录 `dc_index / dc_daily / dc_member` 均返回业务码 `40203`。本轮未读取凭证，也未重放；因响应正文未留存，状态为 `blocked_observed`。
- **全量定义**：`dc_index` 没有独立、不带行情的版本化分类字典；是否完整返回当天所有行业/概念、停牌或无行情板块未知。
- **Industry 成分未证明**：`dc_index` 的 `idx_type` 包含行业、概念、地域，但 `dc_member` 页面只说明概念板块/概念代码。不得把排名分类范围外推为成员接口范围。
- **成员对账**：`dc_index` 不输出成分计数，无法仅凭两接口字段机械证明 `dc_member` 全量；需要额外计数证据或上游基准。
- **2024-12-20 前历史**：`dc_member` 文档明确不覆盖；不得用当前成分回填更早历史。
- **分类修订**：板块代码复用、改名、合并和历史修订政策未公开说明。
- **频率例外**：接口页没有单独 QPS/日配额；只能引用通用频次表，仍需实际账户页面或书面答复确认。
- **许可**：与 TDX 候选相同，Tushare 协议未明确允许生产系统自动入库、团队共享或再分发；东方财富上游权利边界独立未知。

### 6.3 数据流建议（不构成准入）

```text
dc_index(trade_date, idx_type in {行业板块, 概念板块})
  join dc_daily(trade_date, idx_type)
  -> sector-ranking

selected Concept dc_index.ts_code
  -> dc_member(trade_date, ts_code)
  -> Concept sector-constituents
```

同日 `dc_index` 与 `dc_daily` 应按 `ts_code` 一一对应；Concept `dc_member` 必须逐板块证明完整，不能把单次少于 5000 行自动解释为全量。Industry 成分在取得新的官方或真实响应证据前不得进入该数据流。

## 7. 其他一手候选的排除/降级

### 7.1 Tushare THS：不能独立满足当前合同

- [`ths_index`](https://tushare.pro/document/2?doc_id=259) 提供概念、行业板块代码/名称/成分个数，单次最多 5000 行；只有 `list_date`，不是请求快照 `as_of`。
- [`ths_daily`](https://tushare.pro/document/2?doc_id=260) 提供显式 `trade_date` 和 `pct_change`，但输出只有成交量 `vol`、换手率、市值，**没有成交额 `amount`**，不能直接满足 `cje`。
- [`ths_member`](https://tushare.pro/document/2?doc_id=261) 明确是“最新的概念板块成分”，且 `in_date / out_date / is_new` 标为暂无；不支持历史快照，也没有声明行业成分。
- `ths_member` 页面明确 6000 积分、每分钟 200 次；其余两个页面分别声明 6000 积分和单次 5000/3000 行。

结论：可作研究交叉验证，但不是两个目标 Dataset 的单一完整候选。

### 7.2 申万行业：Industry 可候选，但缺 Concept

- [`index_classify`](https://tushare.pro/document/2?doc_id=181) 明确区分申万 2014/2021 版本，提供分级行业代码；2000 积分。
- [`sw_daily`](https://tushare.pro/document/2?doc_id=327) 提供显式 `trade_date / pct_change / amount`，成交额单位万元；单次 4000 行，5000 积分，交易日 18:30 更新。
- [`index_member_all`](https://tushare.pro/document/2?doc_id=335) 提供三级分类映射、带交易所后缀的 `ts_code`、`in_date / out_date / is_new`；单次 2000 行、总量不限制、2000 积分。

结论：申万链能较好覆盖行业，但没有 Concept。当前业务要求 Industry 与 Concept 都存在，不能单独关闭 DS-0；若未来允许两种分类供应商并行，必须由策略治理显式批准，不能在采集层静默拼接。

## 8. 频率、配额与许可

### 8.1 频率与配额（confirmed / unknown）

Tushare 官方[积分与频次权限对应表](https://tushare.pro/document/1?doc_id=290)写明：

- 2000 积分以上：200 次/分钟，100000 次/日/每 API；
- 5000 积分以上：500 次/分钟，常规数据无日总量上限；
- 部分接口有单独规则，例如 `ths_member` 页面明确 200 次/分钟。

上述是平台级规则。对 TDX/DC 六个目标接口，页面没有逐项写明 QPS 与日配额，也没有公开 `Retry-After`、并发连接数或批量任务退避要求。因此实际生产频控仍为 `unknown`，应以账户权限页面或供应商书面答复为准。

### 8.2 使用许可（confirmed / unknown）

Tushare 官方[数据服务协议](https://tushare.pro/document/1?doc_id=405)明确：

- 服务许可是个人、不可转让、非商业、有期限、非排他；
- 仅可为非商业目的使用，并仅作个人查看；
- 不保证数据准确性、完整性和及时性；
- 对第三方提供的数据，其使用、收费由第三方解释；
- 权益、数据内容可能因规划或版权变化调整、取消或终止。

这意味着“达到积分并能调用 API”只证明访问条件，**不等于自动化生产使用已获许可**。对本项目已经冻结的个人、非商业研究目的，许可目的可记为 confirmed；但协议措辞“仅供个人查看”没有明确授权无人值守自动采集、长期持久化或再分发。因此自动化和留存仍为 `unknown`，对外/团队分发不得视为已授权；TDX/DC 第三方上游权利也仍须独立确认。

## 9. 两个 Dataset 逐项结论

### 9.1 `sector-ranking`

| 项目 | Tushare TDX 组 | Tushare DC 组 |
|---|---|---|
| Industry + Concept | confirmed（文档） | confirmed（文档） |
| `bd_code / bd_name` | confirmed | confirmed |
| `cje` | confirmed：`amount` 万元 | confirmed：`amount` 元 |
| `bd_zdf` | confirmed：`pct_change` | confirmed：`pct_change` |
| 显式 `as_of` | confirmed：`trade_date` | confirmed：`trade_date` |
| 历史起点 | unknown | confirmed：行情始于 2020 |
| 全集/分页 | possible，未实测 | possible，未实测 |
| 实际账户权限 | blocked_observed：三个接口曾返回 `40203`，待可复算存档 | blocked_observed：三个接口曾返回 `40203`，待可复算存档 |
| 生产许可 | blocked/unknown | blocked/unknown |

TDX Connector 只有具名板块能力，WeStock 缺可信 ranking 时点，MX 缺全集与 Concept，三者均不能替代上表的完整文档候选。**结论：** Tushare 两条路径均值得做最小认证探针，但尚未达到生产准入结论。

### 9.2 `sector-constituents`

| 项目 | Tushare TDX 组 | Tushare DC 组 |
|---|---|---|
| Industry + Concept | confirmed（文档） | confirmed（文档） |
| `bd_code / symbol / name` | confirmed | confirmed |
| `.SZ/.SH/.BJ` 身份 | confirmed（样例） | confirmed（样例） |
| ST / 北交所边界 | confirmed（样例包含二者） | 北交所 confirmed；ST unknown |
| 显式 `as_of` | confirmed：`trade_date` | confirmed：`trade_date` |
| 历史起点 | unknown | confirmed：2024-12-20 |
| 全量对账 | 可用 `idx_count` 设计对账，未实测 | 无计数字段，需额外基准 |
| 实际账户权限 | blocked_observed：三个接口曾返回 `40203`，待可复算存档 | blocked_observed：三个接口曾返回 `40203`，待可复算存档 |
| 生产许可 | blocked/unknown | blocked/unknown |

TDX Connector 的成分时点、WeStock 的 symbol/完整度、MX 的全集/Concept 均未闭合。**结论：** Tushare TDX 文档路径因 `idx_count` 对账能力更强，适合作为第一探针；Tushare DC 可作为独立候选，不得与 TDX 静默拼成单源。

## 10. DS-0M 后续最小探针条件

集中凭证已经存在且有效；只有获得目标接口访问权限后，才继续以下数据探针。凭证不得进入命令参数、日志或报告：

1. **TDX 组优先**：权限开通后，在同一已收盘交易日分别调用 `tdx_index / tdx_daily`，再对一个 Industry、一个 Concept 调 `tdx_member`；验证日期、字段、单位和 `idx_count`。
2. **规模检查**：先统计当天行业/概念板块数，确认未触及 1000/3000 上限；对入选 Top 20 逐板块核对成员行数与 `idx_count`。
3. **重复性**：同参数至少两次只读调用，排序规范化后比较 SHA-256；任何规模或内容漂移均停止。
4. **DC 独立复核**：权限开通后以同样边界探测 `dc_index / dc_daily / dc_member`，不得自动混源。
5. **许可先决条件**：在全量或定时采集前取得数据 owner 对自动化、持久化、内部共享和第三方上游权利的明确书面结论。

出现无权限、429、服务错误、截断、日期不一致、计数不一致、字段缺失或许可未决时，停止探针并保持 `research_only/blocked`。

## 11. Tushare 官方页面与认证探针

抓取时间：2026-09-06；其中六个目标接口、频次表和数据服务协议于 17:14:13–17:14:15 +08:00 再次抓取且哈希未变。方式：公开 HTTPS 页面、无登录、无凭证。哈希是本次抓取 HTML 的 SHA-256，用于证明本报告引用时的页面内容版本；页面为动态文档，后续执行前应重新抓取并比较。

| 第一方页面 | SHA-256 |
|---|---|
| `https://tushare.pro/document/2?doc_id=376` (`tdx_index`) | `d5245eda19b4d71381ca4523c587e47ed0475f2fb37c74294773ee63b503fe6b` |
| `https://tushare.pro/document/2?doc_id=377` (`tdx_member`) | `70184af900b200576b298cb808e34d49e840b2a7e2675a964e70cfc60abc844b` |
| `https://tushare.pro/document/2?doc_id=378` (`tdx_daily`) | `8666bc9f61cacec52bb82b5804e99635aafc726f9f3c56ba0cf3bb863d604cfb` |
| `https://tushare.pro/document/2?doc_id=362` (`dc_index`) | `e29ad0bb184e3ad4362d080cafe42df95b8a44c55daa4a893d77398e4bd7d328` |
| `https://tushare.pro/document/2?doc_id=363` (`dc_member`) | `feabad933637b59d22a207dc3f2454a2371ef6ce59dc4d9578029f53523a37ac` |
| `https://tushare.pro/document/2?doc_id=382` (`dc_daily`) | `9ad317be56f210013c3c368b6978ed3f9637d427944c9020066079649fc1284e` |
| `https://tushare.pro/document/2?doc_id=259` (`ths_index`) | `04800a016c9e06296c92717edbfd29bfe7d9ea2ba94b93d0b3993d66e472db20` |
| `https://tushare.pro/document/2?doc_id=260` (`ths_daily`) | `f1f87e791c95b5c3a53c55d4e5d173a63fc2be9a7f8cf3e50472126f54bc7f0d` |
| `https://tushare.pro/document/2?doc_id=261` (`ths_member`) | `087c2d8b0de2078a4c59329c6ced09814286037db353b5a162fce8b90ab923e6` |
| `https://tushare.pro/document/2?doc_id=181` (`index_classify`) | `194e1fadea7c8ecffc97ae3b189c6b7218487f4bb1b722d07db826bf39945401` |
| `https://tushare.pro/document/2?doc_id=327` (`sw_daily`) | `0a26cf540357748bf354234719b5c76498b68e92b0d493123dc84d04d36a437a` |
| `https://tushare.pro/document/2?doc_id=335` (`index_member_all`) | `1eec81c70ab90e67220ff656c2cb260467662825d8c8e3a6f57e29bba820b908` |
| `https://tushare.pro/document/1?doc_id=290`（积分与频次） | `765453b00496cdf9749a7d733c189766e3a2411d3ada03f3d96bb98c3c3ecb27` |
| `https://tushare.pro/document/1?doc_id=405`（数据服务协议） | `f88f4c8fe75cbff421f17d7b53c4f0494ebd5f885b2a25656d5447ed8b029f4c` |
| `https://tushare.pro/document/1?doc_id=409`（用户协议） | `3c50cdd1f52ad0e0342b27476d73e8d0098dbb4c479e11375c658e7c87534a89` |

仓库交叉证据：

- `docs/research/sector-dataset-source-admission-20260905.md`
- `docs/research/tdx-and-market-intelligence-data-source-capability-research-2026-08-11.md`
- `docs/plan/invest-infra-target-dataset-source-admission-plan-v1.0.md`
- `apps/pipeline/src/invest_pipeline/integrations/sector_evaluator.py`
- `config/data-acquisition-definitions/sector-strength-ranking/1.0.0.json`

### 11.1 认证探针结果（2026-09-06）

既有探针通过 `CredentialStore` 在进程内懒加载集中凭证；命令、输出和报告均未包含凭证值。本轮没有读取或重放凭证。既有结果只记录 HTTP 状态、Tushare 业务码、行数及稳定分类：

| 接口 | HTTP | 业务码 | 结果 |
|---|---:|---:|---|
| `stock_basic`（SSE/L，仅 `ts_code`） | 200 | 0 | 成功，2316 行；证明集中凭证有效 |
| `tdx_index` | 200 | 40203 | 目标接口权限拒绝 |
| `tdx_daily` | 200 | 40203 | 目标接口权限拒绝 |
| `tdx_member` | 200 | 40203 | 目标接口权限拒绝 |
| `dc_index` | 200 | 40203 | 目标接口权限拒绝 |
| `dc_daily` | 200 | 40203 | 目标接口权限拒绝 |
| `dc_member` | 200 | 40203 | 目标接口权限拒绝 |

注：`dc_index` 的 HTTP 状态同样为 200；表格保留统一脱敏输出，不保存响应正文。由于缺少脱敏原始响应与独立 hash，该表只能证明“曾观测到阻断”，不能满足 B 级可复算要求。

### 11.2 当前运行态复核（2026-09-06）

- 宿主机集中凭证目录存在，目录权限为 `0700`，已登记凭证文件权限为 `0600`；宿主机 `CredentialStore` 能解析 Tushare 凭证，但不输出其值。
- 当前运行中的 Dagster Compose 容器没有集中凭证挂载，容器内 `TushareSettings().resolved_token()` 返回空；工作树已增加只读挂载与 `INVEST_PIPELINE_SECRETS_DIR=/run/secrets/invest-infra`，但尚未重建/部署，不能把静态配置视为运行态已生效。
- 宿主机和现有 Dagster 容器对 `https://api.tushare.pro` 的 TLS 握手均失败（`ConnectError`）；请求没有到达 Tushare 业务鉴权层，因此本轮没有产生新的业务码、行数或可复算响应 hash。
- 当前阻塞顺序应记录为：`runtime credential mount pending deployment` + `egress TLS blocked`；历史 `40203` 仍是旧观测，不能描述为本轮结果。

## 12. Gate DS-FM 关闭项与阻塞项

### 12.1 本轮关闭的未知项

| Gate 项 | 关闭结果 |
|---|---|
| 四源真实能力边界 | 已关闭：TDX 仅具名、WeStock 有时点/身份/截断缺陷、MX 仅具名申万 Industry、Tushare 两组仅为文档候选 |
| 已知分类命名空间 | 已关闭到样本级：TDX `880/881`、WeStock 申万二级/聚源概念、MX 申万 Industry、Tushare `ts_code + idx_type`；各自分类版本仍 unknown |
| Tushare 字段、单次限量与平台频次 | 已由 A 级官方页面关闭；目标接口是否有单独覆盖规则仍 unknown |
| Tushare 使用目的 | 个人、非商业、不可转让、个人查看已由 A 级协议关闭；自动化和留存没有被该措辞关闭 |
| 当前仓库消费合同 | 已由 C 级源码关闭：两个 Dataset 必须同 `as_of`、全组齐备、稳定身份、唯一且成分与入选板块绑定 |

### 12.2 仍阻塞 Gate DS-FM 的未知项

1. **没有单一路径完成真实全量证明。** TDX/WeStock/MX 均存在结构性缺口；Tushare 尚无目标接口的可复算响应。
2. **分页和完整性未闭合。** 需要同一收盘日的 Industry/Concept 全集、逐板块成员计数、截断信号和两次规范化 SHA-256。
3. **分类治理未闭合。** 四源均缺足以支持生产的版本、改名、合并、代码复用和历史修订政策证据。
4. **频控未闭合。** TDX、WeStock、MX 的 QPS/日配额/Retry-After 全部 unknown；Tushare 目标接口是否受单独规则覆盖仍 unknown。
5. **许可未闭合。** TDX、WeStock、MX 的个人自动化、持久化与分发条款 unknown；Tushare 只明确个人非商业查看，自动化/长期留存 unknown，分发未获授权，第三方上游权利 unknown。
6. **Tushare 访问仍阻断。** 既有探针曾返回 `40203`；本轮宿主机凭证可解析，但当前容器未挂载凭证，且宿主机/容器均在 TLS 握手阶段失败。必须先由 Ops 验证出口，再重建 Dagster 使只读挂载生效，之后才能取得新的脱敏、可复算响应存档。

```text
selected_runtime_path = none
admitted_decision = not_made
Gate DS-FM = BLOCKED
next_allowed_action = close license/rate-limit evidence and run one selected source's minimal read-only full-snapshot probe
```
