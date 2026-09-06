# Sector Dataset 多源贡献矩阵（DS-0M）

> 日期：2026-09-06（Asia/Shanghai）
>
> 范围：`sector-ranking-industry`、`sector-ranking-concept`、`sector-constituents-industry`、`sector-constituents-concept`
>
> 证据边界：只复用仓库源码、既有真实探针和供应商一手文档；不作生产准入、不修改策略、Definition 或代码
>
> 使用边界：仅供 owner 个人、非商业投资研究参考；不向团队提供数据服务、不对外分发原始数据、不形成商业数据产品
>
> Gate 结论：`DataRequest/DataBundle 1.0 = semantically sufficient`；`Gate DS-FM = READY_FOR_DS-C0`；`Gate B2A = BLOCKED`
>
> 核证状态：DS-0M 四源证据已完成；WorkBuddy 固定多源配方可进入 shadow 实施，但尚未获得生产准入

## 1. 判定口径

本报告把来源角色严格区分为：

- **primary contributor**：在固定 Dataset 配方中提供主要业务字段；不要求单源覆盖整个 Dataset；
- **repair contributor**：在冻结 join key、来源 lineage 和完整度规则下补齐稳定身份等缺失字段；
- **fallback**：仅在前序**同分类体系、同字段口径、同时点语义**的 contributor 明确失败后替代；
- **corroborator**：只形成独立旁证，不覆盖或平均正式输入；
- **candidate**：文档或小样本证明具备潜力，但仍有硬缺口，当前不得进入 evaluator。

当前 evaluator 对排行记录实际要求 `group / bd_code / bd_name / cje / bd_zdf / as_of`；对成分记录要求 `group / bd_code / symbol / name / as_of`，并要求 `(group, bd_code, symbol)` 唯一、成分绑定入选板块。依据：`apps/pipeline/src/invest_pipeline/integrations/sector_evaluator.py:148-192`、`:195-235`、`:253-285`。

以下共享探针路径均相对于：

```text
/home/claw/windows-ltsc/shared/workbuddy/strategy/results/
```

证据冲突采用较晚、较保守结论：早期报告曾把调用方选择日期当作来源 `as_of`，后续探针已证明 WeStock ranking 的 `date` 静默失效，并把 MX 限定为具名板块能力；因此本报告不沿用早期“covered”摘要。

## 2. 总体矩阵

| Dataset | 来源 | 逐字段贡献 | `as_of` | 身份与分类体系 | 分页/完整度 | 限流/许可 | 当前角色与判定 |
|---|---|---|---|---|---|---|---|
| ranking-industry | TDX Connector | `group=industry`；screener 可给行业 `index_code/name`，quotes 可给 `Amount→cje`、`Now/Close→bd_zdf` | quotes 有显式 `HQDate/HQTime`；screener 成员时点仅隐含当日 | 通达信 `881xxx`；版本未声明 | screener 有 `pageNo/pageSize/meta.total`；但无原生板块全集枚举，需逐股扫描派生 | 个人非商业场景已冻结；QPS、日配额、退避、缓存和来源条款仍 unknown | **candidate contributor（research_only）**；不是已准入 fallback |
| ranking-industry | WeStock MCP | 原生返回 `code/name/turnover/changePct`，可映射全部业务字段；`turnover` 为万元 | 响应无可信显式日期；`date` 参数静默失效，只允许 latest shadow 并以独立交易日证据锚定 | 已实测申万二级 `pt018...`；分类版本 unknown | 行业清单 124；Top20 字段 20/20 完整；ranking `limit` 不生效 | 全部 unknown；同会话曾持续 service error | **shadow primary contributor（latest-only）**；不得用于任意历史 `as_of` |
| ranking-industry | MX-DS MCP | 具名申万板块返回 `name/成交额/涨跌幅`，可旁证 `cje/bd_zdf` | 具名日期查询返回显式日期 | 申万 `SWI/BLOCK`；版本和稳定 `bd_code` 输出未冻结 | 不具名全集查询返回空；仅具名样本；单次上限陈述未经本报告取得可核验的一手文档 | 日配额、QPS、许可 unknown；会话工具注入曾不稳定 | **corroborator only**；不可作为全量 contributor/fallback |
| ranking-industry | Tushare | TDX 组：`tdx_index + tdx_daily` 给 `ts_code/name/pct_change/amount`；DC 组：`dc_index + dc_daily` 同样覆盖，单位分别为万元/元 | 两组都有显式 `trade_date` | TDX 与 DC 是不同分类族；均有稳定板块代码；分类修订规则 unknown | TDX 1000/3000、DC 5000/2000 单次上限；尚无真实全量/重复 hash 证明 | 最新 `tdx_index/tdx_daily` 探针均为 `40203`；6000 积分；公开协议只确认个人非商业查看，自动化留存与第三方权利仍待确认 | **文档级 candidate contributor**；当前访问与许可阻塞，不能进入生产 Provider 路径 |
| ranking-concept | TDX Connector | 单板块 quotes 可给 `bd_name/cje/bd_zdf`；`group=concept` 可由请求上下文确定 | quotes 有显式 `HQDate/HQTime` | 通达信 `880xxx` 单板块身份可用；但无 Concept 全集枚举 | 无原生 Concept 清单；screener 概念结果不携带显式概念码，无法可靠反推全集 | QPS/配额/许可 unknown | **corroborator only**；缺全集，不能贡献完整 Dataset |
| ranking-concept | WeStock MCP | 原生 `code/name/turnover/changePct`；曾返回 802 个 Concept 且字段完整 | 无可信显式日期；历史 `date` 静默失效，只允许 latest shadow 并以独立交易日证据锚定 | 聚源概念 `pt02.../indus_...`；分类版本 unknown | 802/802 字段完整；`limit` 不生效，重复全量稳定性待 shadow 复核 | QPS/配额/许可 unknown；服务稳定性不足 | **shadow primary contributor（latest-only）**；不得用于任意历史 `as_of` |
| ranking-concept | MX-DS MCP | 未取得 Concept 排行、Concept 代码或全量字段的真实证据 | unknown | unknown | unknown | QPS/配额/许可 unknown | **unknown / not_tested** |
| ranking-concept | Tushare | TDX 组与 DC 组文档均覆盖 Concept 的代码、名称、涨跌幅、成交额 | 显式 `trade_date` | 各自分类命名空间稳定代码；修订规则 unknown | 有单次上限但无当前账户全量实测 | 最新 TDX 入口探针为 `40203`；许可 blocked/unknown | **文档级 candidate contributor**；当前不可用 |
| constituents-industry | TDX Connector | screener 返回 `sec_code/sec_name/index_code`，用于给已选定 WeStock 板块恢复 `symbol` | 仅隐含最新收盘；最终 `as_of` 继承经验证的 WeStock 成分快照日期，不得由 TDX 补写 | 通达信代码与申万代码不同；只允许冻结板块样本内按规范化名称匹配；样本包含 ST/北交所 | 分页元数据可机械复核；既有 11 组联合快照覆盖 371 条 | QPS/配额/许可 unknown | **shadow repair contributor**；不得独立决定分类或时点 |
| constituents-industry | WeStock MCP | constituent 提供板块代码、名称和显式日期；`symbol` 缺陷由固定 TDX repair 补齐 | constituent 日期显式 | 申万二级代码；名称采用 NFKC + 去空白后与 TDX 匹配 | 11 个 Industry/Concept 样本组共 371 条联合快照已完成去重与双实现 hash | QPS/配额/许可 unknown；服务错误出现过 | **shadow primary contributor**；必须与冻结 TDX repair 配方共同运行 |
| constituents-industry | MX-DS MCP | 早期具名“半导体(申万)”探针返回 180 行 `证券代码/简称/申万一级行业/纳入日期` | 查询指定 2026-08-28，但来源记录的快照时点仍被报告为“隐含”；历史截面接口 unknown | `.SH/.SZ` 证券身份样例可用；申万一级；稳定板块 code/version 未冻结 | 只证明一个具名行业 180 行；完整 hash 只对 10 行演示；全集枚举失败 | QPS/日配额/许可 unknown；会话注入不稳定 | **candidate corroborator（research_only）**；不足以做正式 contributor |
| constituents-industry | Tushare | TDX `tdx_member` 文档覆盖 Industry；DC `dc_member` 页面只说明 Concept，不能外推 Industry | TDX 显式 `trade_date`；DC Industry unknown | TDX `.SZ/.SH/.BJ` 且样例含 ST；DC Industry unknown | TDX 可用 `idx_count` 对账但未实测；单次 3000 | 最新 `tdx_index` 权限拒绝，`tdx_member` 按规则未扩大调用；许可 blocked/unknown | **仅 TDX 组为文档级 candidate contributor**；当前不可用 |
| constituents-concept | TDX Connector | screener 返回真实 `sec_code/sec_name`，用于给请求中已明确的 Concept 恢复 `symbol`；样本包含 *ST | 仅隐含最新收盘；最终 `as_of` 继承经验证的 WeStock 成分快照日期 | 概念行无显式 `bd_code`，因此只允许在已冻结 Concept 名称集合内匹配，不得反推分类全集 | 已参与 11 组/371 条联合快照；独立大 Concept 查询仍有身份边界 | QPS/配额/许可 unknown | **shadow repair contributor**；不得独立决定板块身份 |
| constituents-concept | WeStock MCP | constituent 提供 Concept 身份、名称和显式日期；`symbol` 错误由固定 TDX repair 补齐 | constituent 日期显式 | 聚源概念；跨工具名称采用 NFKC + 去空白；禁止跨分类族同名合并 | 既有联合样本可复算；单独 tool_filter 大 Concept 截断，不作为正式成员来源 | QPS/配额/许可 unknown | **shadow primary contributor**；必须与冻结 TDX repair 配方共同运行 |
| constituents-concept | MX-DS MCP | 未取得 Concept 成分、稳定 Concept code、证券边界或完整度的真实证据 | unknown | unknown | unknown | QPS/配额/许可 unknown | **unknown / not_tested** |
| constituents-concept | Tushare | TDX/DC member 文档均覆盖 Concept 成分、证券代码与日期 | 显式 `trade_date` | 稳定板块/证券代码；分类修订 unknown | TDX 有 `idx_count`；DC 无成员计数基准；仍需逐板块计数与重复 hash | 最新 TDX 入口权限拒绝，成员调用按规则跳过；许可 blocked/unknown | **文档级 candidate contributor**；当前不可用 |

## 3. 来源证据与边界

### 3.1 TDX Connector

- 行业成分真实探针返回 `total=42`、`sec_code/sec_name` 和显式行业 `index_code=881385`，接口具备分页元数据；概念探针返回 `total=1070` 且包含 *ST，但没有显式概念代码：`sector-new-source-admission-20260905.ready/capability-probes.json:23-29`、`:79-85`。
- 单板块 quote 提供 `HQDate/HQTime`、`Amount` 和可复算涨跌幅；相同请求二次调用逐字段一致：同文件 `:31-37`、`:71-77`。
- TDX 侧板块全集枚举探针失败，F10 成分入口也未注册：同文件 `:87-93`、`:103-109`。
- 真实样本已证明通达信与申万分类不一致，不能按名称跨源合并：`industry-concept-coverage-remediation-20260904.ready/capability-probes.json:86-92`。

因此，TDX 的 Industry 路径是“同 Connector 多工具派生”的候选，不是已经闭合的单一 Dataset 来源；Concept 因缺全集/显式板块码只能旁证。TDX Connector 与 Tushare TDX 接口可能共享通达信上游，在上游 owner/生成链未证明独立前，**不得相互计为独立 corroborator**。

### 3.2 WeStock MCP

- Industry 清单真实返回申万二级 124 条；Concept 搜索返回聚源概念样本：`industry-concept-coverage-remediation-20260904.ready/capability-probes.json:36-45`、`:102-108`。
- 最新排行字段可用，但 `date=2026-09-02` 与 `2026-09-03` 返回逐字段相同，`limit` 也不生效：同文件 `:46-52`；复核报告进一步确认实际对应 09-04：`industry-concept-coverage-remediation-20260904.ready/coverage-report.md:78-86`。
- constituent 日期生效但 `symbol` 100% 错；tool_filter 的 symbol 可用却排除 ST/*ST、北交所：`industry-concept-coverage-remediation-20260904.ready/capability-probes.json:54-68`。
- 大 Concept 的 tool_filter 已出现截断：同文件 `:94-100`。
- 较早探针曾得到 Industry top20 20/20、Concept 802/802 和 `turnover × 10,000 = quote amount`，只证明字段/单位，不证明历史时点：`sector-coverage-closure-20260904.ready/coverage-report.md:24-35`。

所以 WeStock 可作为 latest 排行和显式日期成分的 shadow primary contributor，但必须保留两个边界：排行不得伪装成任意历史快照；成分不得使用错误 `symbol`，只能通过冻结的 TDX repair 配方补齐。

### 3.3 MX-DS MCP

- 2026-09-05 具名申万半导体查询返回显式 2026-09-04、成交额 2154 亿、涨跌幅 -2.855%，与 WeStock 的 2154.126 亿/-2.85% 一致；不具名“全部行业排行”返回空：`sector-new-source-admission-20260905.ready/capability-probes.json:39-45`、`:63-69`。
- 早期具名行业成分探针返回 180 行，字段含证券代码、简称、申万一级行业和纳入日期；但报告明确快照日期为隐含，历史截面接口未知：`data-coverage-active-v2-20260828.ready/_history_v1/capability-probes.json:151-214`。
- 该早期探针只对 10 个样本演示 hash，明确生产需对完整 180 行重算：同文件 `:550-563`。
- MX 在不同会话出现“可用/不可见”两种观测；不得据此断言根因，只能把运行可达性记为未稳定：`data-coverage-active-v2-20260902.delta-v2.ready/capability-probes.json:330-358`。

所以 MX 只能作为具名申万 Industry 的旁证/候选；没有证据支持 Concept 或四个 Dataset 的全量 fallback。

### 3.4 Tushare

Tushare 有一条文档级接近完整候选和一条部分候选，且必须保持分类族隔离：

1. **TDX 组**：[`tdx_index`](https://tushare.pro/document/2?doc_id=376) + [`tdx_daily`](https://tushare.pro/document/2?doc_id=378) + [`tdx_member`](https://tushare.pro/document/2?doc_id=377)；
2. **DC 组**：[`dc_index`](https://tushare.pro/document/2?doc_id=362) + [`dc_daily`](https://tushare.pro/document/2?doc_id=382) + [`dc_member`](https://tushare.pro/document/2?doc_id=363)；排名覆盖 Industry/Concept，但成员页只确认 Concept，因此不是四 Dataset 完整候选。

文档字段、单位、身份和单次上限汇总见 `docs/research/sector-dataset-primary-source-evidence-20260906.md` 第 5～6 节。最新 TDX 最小探针已再次确认 `tdx_index/tdx_daily` 返回业务码 `40203`；执行合同与脱敏指纹见 `docs/research/tushare-tdx-minimal-live-probe-20260906.md`。

官方[频次表](https://tushare.pro/document/1?doc_id=290)只能提供平台级规则，目标接口是否存在覆盖规则仍未知；官方[数据服务协议](https://tushare.pro/document/1?doc_id=405)把许可限定为个人、不可转让、非商业、有期限和个人查看，且第三方数据权利由第三方解释。仓库取证摘录见 `docs/research/sector-dataset-primary-source-evidence-20260906.md` 第 8 节。

因此，Tushare 的“文档字段完整”不能替代目标接口访问、全量、分类修订、个人自动化留存边界和第三方权利证据。TDX 组与 DC 组也不能互为无条件 fallback，因为二者分类体系不同。

## 4. 推荐角色冻结结果

当前证据允许冻结一条**用于 shadow 的确定性 WorkBuddy 配方**，但不允许宣称已生产准入：

| Dataset | contributor | fallback | corroborator |
|---|---|---|---|
| ranking-industry | WeStock latest ranking | **无自动 fallback** | MX 具名申万、TDX 单板块 quote |
| ranking-concept | WeStock latest ranking | **无自动 fallback** | TDX 具名 quote |
| constituents-industry | WeStock 显式日期/名称 + TDX symbol repair | **无自动 fallback** | MX 具名申万样本 |
| constituents-concept | WeStock 显式日期/名称 + TDX symbol repair | **无自动 fallback** | 无已冻结独立旁证 |

硬规则：

1. Industry 与 Concept 用独立 Dataset key；不同分类供应商也不得只按名称 union。
2. merge key 冻结为 `(taxonomy_namespace, group, bd_code)`；成分身份为 `(taxonomy_namespace, group, bd_code, exchange-qualified symbol)`。
3. Dataset 的所有记录必须与请求 `as_of` 相同，`as_of` 必须来自上游显式字段或已批准的、可审计的交易日规则；当前墙钟/调用方赋值不合格。
4. 完整度须由分页终态、上游总数/成分计数或冻结分类全集机械证明；“未触及 limit”不等于完整。
5. 同一真实上游的不同访问路径不得计为独立旁证；WeStock、MX、Tushare-DC 的真实数据 owner 尚未完全确定，也暂不能默认相互独立。
6. 首轮旁证只进入 shadow 诊断；仅当来源同分类、同时点、真实 owner 独立且冲突字段已预声明为关键字段时 fail closed。其他差异进入人工复核，不预建正式 `CrossCheckReport`。

## 5. DataRequest/DataBundle 1.0 判定

### 5.1 结论：WorkBuddy 分支 `1.0 sufficient`（语义层面）

DataBundle 1.0 对每个 Dataset 强制恰好一个成功 Connector，因此固定多源配方必须拆成三个语义独立的采集 Dataset：

| 采集 Dataset | 唯一成功 Connector | 作用 |
|---|---|---|
| `sector-ranking` | `westock-mcp` | latest Industry/Concept 排行字段 |
| `sector-constituent-memberships` | `westock-mcp` | 板块身份、成分名称、显式日期 |
| `sector-constituent-symbol-map` | `tdx-connector` | 请求绑定板块内的证券代码与名称映射 |

evaluator 在请求已冻结的分类和板块范围内确定性 join 后，生成现有 canonical `sector-constituents`。这不需要通用字段级路由引擎：

- 排行由 WeStock latest ranking 提供完整业务字段；独立日期证据只负责锚定快照边界，不覆盖排行值；
- 成分由 WeStock membership Dataset 提供分类身份、名称和显式日期，TDX symbol-map Dataset 只按冻结名称规范恢复证券代码；两者 lineage 必须分别保留；
- MX 与其他 TDX quote 结果只作 shadow 旁证，不平均或静默覆盖正式字段；
- Tushare TDX/DC 仍是按 Dataset 登记的候选 Provider 绑定，其访问失败不改变 WorkBuddy 配方的可执行性。

1.0 已支持多个 Dataset、Dataset 内有序 connector attempts、唯一成功来源、同 `as_of`、完整分页和必需字段校验：`packages/domain/src/invest_domain/strategy/data_acquisition.py:13-17`、`:250-275`、`:397-454`、`:580-631`。三个采集 Dataset 分别满足“恰好一个成功 attempt”，由 evaluator 做窄 join；不需要修改 DataRequest/DataBundle 合同。

### 5.2 Provider/Connector 的真实接口边界与最小实施结论

Tushare 当前是投研系统内部 Provider 候选，不是 WorkBuddy Connector。DS-0M 已冻结 WorkBuddy 配方作为首个 shadow 路径，不同时实现 Provider Adapter：

```text
DatasetSpec → 固定 WorkBuddy DatasetSourceBinding → DataBundle codec → evaluate_sector_bundle()
Tushare Provider → 保留候选绑定，当前不实现
```

- WorkBuddy 路径直接复用现有 DataRequest/DataBundle 1.0 校验、producer、connector/tool、artifact 与 hash lineage，不增加透传型 Adapter；
- Provider 路径保留 ProviderRequest/ProviderAttempt/ProviderBatch，并只为入选 Provider 增加板块映射；
- `ProviderAttempt` 表达单一 ProviderRequest 内的尝试，不承担跨 Provider fallback；来源切换须人工批准并创建新请求/运行；
- 在出现一个真实、获准的 WorkBuddy Tushare Connector 前，Tushare 不得进入 `allowed_connectors`，内部 Provider 来源切换也不得伪装成 Connector attempt。

只有两个真实入口都稳定使用相同板块不变量时，才把 evaluator 私有 seam 提升为正式接口。这不是 DataRequest/DataBundle 2.0，也不是通用 Source Registry。

### 5.3 不是“当前实现已可直接生产”

- 现有 1.0 allowlist 只有 `tdx-connector / westock-mcp / mx-ds-mcp`；这与 Tushare 走内部 Provider 路径并不冲突：`packages/domain/src/invest_domain/strategy/data_acquisition.py:13-17`、`:263-267`、`:428-454`。
- attempt 只记录一个 connector/tool/parameters，且每个 Dataset 必须恰好一个成功 attempt；禁止把 TDX repair 隐藏在 WeStock `sector-constituents` 成功 attempt 内。
- 现有 Definition 仍只有旧的 `sector-ranking`、`sector-constituents`，DS-C0 必须把后者拆为 membership 与 symbol-map 两个采集 Dataset：`config/data-acquisition-definitions/sector-strength-ranking/1.0.0.json:19-58`。
- 2026-09-06 本地核证确认没有 Provider 声明 `stock_block_memberships`，调用 `select_providers(..., enabled_only=False)` 得到 `NoEligibleProviderError`；Provider 路径不是“已有能力只差启用”。相关 WorkBuddy 合同、provider routing 和 sector evaluator 的 49 项 focused tests 通过。

因此本报告判定的是：**无需启动 DataRequest/DataBundle 2.0 设计；Gate DS-FM 已冻结 WorkBuddy 固定配方，可以进入 DS-C0/DS-1 的受控 shadow 实施，但不能绕过 Gate B2A 宣称生产可用。**

## 6. Gate DS-FM 判定

```text
DataRequest/DataBundle path = 1.0 sufficient
shadow dataset recipe        = WorkBuddy fixed multi-source recipe
automatic fallback chain     = none
selected runtime path        = WorkBuddy DataRequest/DataBundle 1.0
usage scope                  = personal non-commercial research only
Gate DS-FM                   = READY_FOR_DS-C0
Gate B2A                     = BLOCKED
```

生产准入前未通过项：

1. **覆盖边界**：当前配方只支持 latest shadow；不得用于任意历史 `as_of`，且 Concept 大板块完整度仍需真实运行复核。
2. **分类**：通达信、申万、聚源、DC 分类不能按名称混合；版本/修订规则均有 unknown。
3. **分页/全量**：WeStock Concept 成分已实测截断；TDX/MX 缺板块全集；Tushare 未获权限，无法实测计数与重复 hash。
4. **限流**：三类 Connector 的 QPS、并发、日配额、退避均 unknown；Tushare 只有平台级频次信息。
5. **许可与场景**：使用场景已冻结为 owner 个人、非商业投资研究参考，且不提供团队数据服务、不对外分发原始数据；但 Connector 来源条款仍 unknown，Tushare 目标接口访问、个人自动化留存边界和第三方数据权利仍未闭合。
6. **运行验收**：尚未完成两次真实 shadow 的行数、分页终态、规范化 hash、成本和失败路径复核。

Gate 标准依据：[`docs/plan/invest-infra-target-dataset-source-admission-plan-v1.0.md`](../plan/invest-infra-target-dataset-source-admission-plan-v1.0.md) 的“Gate DS-FM”章节。

## 7. Gate B2A 前的最小证据

不扩大平台范围，先验证已冻结 WorkBuddy 配方；Tushare 只作为独立候选继续核证：

1. **WorkBuddy 固定配方**——执行两次 latest shadow；核对 Industry/Concept 行数、成分含 ST/*ST/北交所/停牌边界、分页终态、来源 lineage 和重复 hash；明确 QPS/配额/许可。
2. **Tushare 候选绑定**——只有取得 TDX 或 DC 目标接口访问权后，才重新执行其独立只读探针；不得因该候选阻塞而暂停 WorkBuddy shadow。
3. **旁证独立性**——确认真实数据 owner 与生成链；同上游不同入口只算一次，不因数值一致自动视为独立交叉验证。

任一路径仍不得通过跨分类名称匹配、调用方补写 `as_of`、忽略截断或把文档能力当作实际访问来解除 Gate。

## 8. 证据完整性

本报告使用的关键共享 artifact SHA-256（2026-09-06 复算）：

| Artifact | SHA-256 |
|---|---|
| `industry-concept-coverage-remediation-20260904.ready/capability-probes.json` | `bfdcf6f72415542cd0ef1395b1011c53150143d9a49e2ae4aee0c63de96ed7ae` |
| `sector-new-source-admission-20260905.ready/capability-probes.json` | `2fab442c240fe0b86c707cf084092995ddfc85a8494359067e98202ebafc1825` |
| `sector-new-source-admission-20260905.ready/candidate-source-matrix.json` | `a02dd52e4ebf14a01a26b957ea431e486e77bd8742c5f8d97c9b9362857a5319` |
| `data-coverage-active-v2-20260828.ready/_history_v1/capability-probes.json` | `eaee5e7509a077858f0d8b64cfcc55fc9917e2d75e78a15f1c15afb204634f9d` |

建议验证：

```bash
python3 -m json.tool <artifact.json> >/dev/null
sha256sum <artifact.json>
rg -n "unknown|BLOCKED|1.0 sufficient|contributor|fallback|corroborator" \
  docs/research/sector-dataset-multisource-contribution-matrix-20260906.md
git diff --check -- \
  docs/research/sector-dataset-multisource-contribution-matrix-20260906.md
```
