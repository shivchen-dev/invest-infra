# Daily Stock Analysis 对 invest-infra 的复用价值调研

- 日期：2026-09-02
- 审查对象：[`ZhuLinsen/daily_stock_analysis`](https://github.com/ZhuLinsen/daily_stock_analysis)
- 固定版本：[`972c31465654d86c52c59abfdb8414b82808f50f`](https://github.com/ZhuLinsen/daily_stock_analysis/tree/972c31465654d86c52c59abfdb8414b82808f50f)
- 目标系统：`invest-infra`
- 方法：GitHub 在线源码审读；未拉取或运行上游项目，未执行真实数据源与端到端测试

## 执行摘要

**该项目的设计参考价值高，但整套直接迁移价值低。** 最值得吸收的不是某一段选股算法，而是它把运行拓扑、任务恢复、过滤解释、信号生命周期、告警结果和降级状态做成了完整产品体验。

`invest-infra` 应继续以不可变输入快照、Provider 证据链、版本化策略和候选池发布状态机为事实边界：

```text
StrategyVersion
  -> ProviderRequest / Attempt / Batch
  -> InputSnapshot + market-data fingerprint
  -> CandidatePool calculated
  -> validated
  -> published
```

对 DSA 的采用原则是：**复用概念与交互，按现有契约重写实现；不引入第二套 API、状态管理、数据证据或发布模型。**

## 审查范围与方法

本轮在线审查覆盖：

- 数据采集、Provider 路由、重试与多源降级；
- 策略声明、因子评分、筛选流水线、LLM 重排与风险覆盖；
- 决策信号、告警、组合风险与事后效果评估；
- Web 技术栈、Run Flow、后台任务恢复和通用状态组件；
- 测试、版本标识、许可及已公开 Issue。

所有判断均绑定上述固定提交，避免上游后续变更造成结论漂移。由于本轮未运行代码，关于真实 ETF 覆盖率、成交额单位、上游端点可用性以及运行时重试行为，均只能视为待实测假设。

## 数据层

### 可参考

1. **BaoStock ETF 代码路由与历史行情调用方式。** [`BaostockFetcher`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/972c31465654d86c52c59abfdb8414b82808f50f/data_provider/baostock_fetcher.py#L168-L288) 展示了 ETF 代码到 `sh.` / `sz.` 的映射，以及 `query_history_k_data_plus` 对 `date/open/high/low/close/volume/amount` 的读取方式。
2. **多数据源优先级、降级和运行诊断的产品思路。** 这些能力适合映射到 `invest-infra` 既有 Provider 编排，而不是迁入其 DataFrame 管理器。
3. **MIT 许可。** 上游 [`LICENSE`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/972c31465654d86c52c59abfdb8414b82808f50f/LICENSE) 允许在保留版权与许可声明的前提下修改复用；该许可不自动授予第三方行情数据或服务的使用与再分发权。

### 必须重写

- DSA 的 BaoStock 请求使用 `adjustflag="2"`（前复权），而 `invest-infra` 当前日线事实层要求未复权口径；接入时应使用并验证 `adjustflag="3"`。
- `amount` 缺少明确单位契约、转换与合理性校验，不能直接进入事实表或候选池。
- Provider 必须产出 `ProviderRequest / Attempt / Batch`，保存原始载荷哈希、错误阶段、时间范围与发布证据。
- 仅瞬时传输错误允许降级；字段缺失、单位异常、日期覆盖不完整、空结果必须 fail closed。
- Efinance 与 AkShare 可能共享东财链路，不能仅因 Python 包不同就视为独立冗余。

### 实施前真实探针

对当前目标 16 只 ETF 至少验证：

- 未复权价格口径；
- `volume` / `amount` 单位及数量级；
- 交易日覆盖、停牌与空结果语义；
- 重复记录和日期排序；
- 与现有可信源的跨源一致性；
- 登录、断线、重试和资源释放行为。

上游已有 ETF 多源同时失败的公开记录，见 [Issue #541](https://github.com/ZhuLinsen/daily_stock_analysis/issues/541)，因此备用 Provider 不能只做静态接口适配，必须通过目标标的实测。

## 业务逻辑

### 高价值设计

1. **声明式策略与分阶段筛选。** 策略配置、硬过滤、因子评分、Top-K、风险覆盖和后处理的分层有利于解释与诊断，可映射为受治理的 `StrategyVersion`。
2. **过滤 waterfall 与因子贡献。** [`screening/scorer.py`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/972c31465654d86c52c59abfdb8414b82808f50f/src/services/screening/scorer.py) 将价值、流动性、动量、反转、活跃度、稳定性、规模与主题等因素拆成可解释分项；适合作为因子词汇和展示结构参考。
3. **确定性主链与可降级增强层。** [`screening/pipeline.py`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/972c31465654d86c52c59abfdb8414b82808f50f/src/services/screening/pipeline.py) 先执行规则评分，再尝试 LLM 重排，失败后回退规则结果，并记录模型与降级信息。`invest-infra` 可借鉴“增强层失败不污染确定性结果”的观念，但 LLM 不应进入正式候选池真值链路。
4. **DecisionSignal 生命周期与幂等思想。** 信号创建、重复处理、刷新、反向失效及终态保护适合作为状态机参考。
5. **AlertRule 与 dry-run。** 逐目标执行结果和技术指标边缘穿越判断可发展为独立的 `AlertRule / AlertEvaluation` 模型。

### 需要治理改造

- 经验权重、斜率和阈值必须版本化并经过统计校准，不能把示例参数直接升级为生产策略。
- 策略版本不能只保存字符串；必须绑定参数规范化哈希、源码 revision、输入快照、市场数据指纹和审批状态。
- 随机候选轮换必须持久化随机种子或完整抽样结果，否则无法重放。
- 缺失成交额不能默认为 `0` 或中性分；应按策略契约明确排除、降级或阻断。
- DecisionSignal 幂等键应至少覆盖 `StrategyVersion + market_data_fingerprint + as_of + universe/policy hash`。
- 告警触发结果必须绑定数据批次、规则版本、评估时点与证据指纹。

### 不作为正式回测引擎

DSA 的事后建议效果追踪有反馈闭环参考价值，但不足以替代正式回测。正式回测仍需明确：点时数据、成交价格与撮合、滑点、费用、企业行动、停牌/涨跌停、基准、持仓路径、现金和再平衡规则。

## Web 界面

### 技术兼容性

两边都使用 React 19、TypeScript、Vite，并采用 Vitest/Playwright 测试思路，组件与交互模式可以参考。主要差异是：

- DSA：Tailwind、React Router、Zustand、Axios、手写 DTO；
- `invest-infra`：现有样式体系、TanStack Query、OpenAPI 自动生成类型。

整套迁移会形成双状态管理、双 API Client 和额外样式依赖，因此应在现有 Web 栈内重建。

### 优先参考

1. **Run Flow。** [`RunFlowPanel`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/972c31465654d86c52c59abfdb8414b82808f50f/apps/dsa-web/src/components/run-flow/RunFlowPanel.tsx#L91-L194) 的“摘要 → 执行拓扑 → 节点详情 → 事件流”适合展示 PipelineRun、Provider 尝试、快照、候选池发布和失败重试。
2. **任务恢复。** 后台任务、刷新恢复、轮询、阶段进度和错误状态适用于数据采集、候选池计算与回测等长任务。
3. **通用状态组件。** Loading、Empty、Error、StatusDot、Badge、ConfirmDialog、Pagination、JsonViewer，以及按钮 loading/禁用/ARIA 行为，可形成统一组件规范。
4. **构建身份。** revision、构建时间和源码指纹适合用于前后端版本核对和问题定位。

### 不迁移

- Axios API Client 与手写 DTO；
- Zustand 管理服务端状态；
- 整套 Tailwind/全局 CSS、Shell 和路由；
- 单管理员文件凭据、弱密码门槛、内存限频等认证实现；
- 与目标系统无关的 LLM 问股、Token 用量、通知和模型设置页面。

## 横向工程能力

| 能力 | 参考价值 | 对 `invest-infra` 的落点 |
|---|---:|---|
| Run Flow / Evidence Timeline | 高 | 映射 PipelineRun、ProviderRequest / Attempt / Batch、Snapshot、Publication Event |
| 后台任务恢复 | 高 | 统一长任务 ID、阶段状态、轮询/恢复和错误证据 |
| 过滤与评分解释 | 中高 | 保存逐规则结果、排除原因和因子贡献 |
| AlertRule / dry-run | 中高 | 独立规则版本与不可变评估记录 |
| DecisionSignal 生命周期 | 中高 | 使用严格幂等键、合法转换和终态保护 |
| 组合风险看板 | 中 | 展示集中度、回撤、止损距离和风险聚合；不充当优化器 |
| 通用状态组件 | 中 | 在现有设计系统内重建 |
| 构建版本标识 | 中 | 展示前后端 revision、构建时间、API schema 版本 |

## 复用分级

| 领域 | 分级 | 决策 |
|---|---|---|
| Run Flow、证据时间线 | A：优先采用 | 在现有技术栈内重建 |
| 后台任务恢复、阶段进度 | A：优先采用 | 接入现有运行模型 |
| BaoStock 备用数据源 | B：有边界采用 | 只借鉴接口与代码路由，按 Provider 契约重写 |
| 策略声明、过滤 waterfall、因子解释 | B：有边界采用 | 编译为受治理的 StrategyVersion |
| AlertRule、DecisionSignal 生命周期 | B：有边界采用 | 加入证据绑定、幂等键与状态机约束 |
| 组合风险展示 | C：参考 | 仅作看板和预警 |
| 通用 Web 组件 | C：参考 | 视觉与交互参考，不搬依赖体系 |
| 正式回测、完整数据管理器、整套 Web | D：不采用 | 不能满足现有证据、版本和发布治理 |

## 明确禁止迁移项

- LLM 直接修改正式候选池排名或发布结果；
- 从 LLM 报告文本生成正式交易信号；
- 数据缺失、单位异常、日期覆盖不足或证据不完整时继续发布；
- DataFrame 非空即认定 Provider 成功，或将空结果记为成功；
- 将全部异常折叠为单一错误，导致瞬时错误与契约错误无法区分；
- 未持久化随机种子或抽样结果的候选轮换；
- 把 Efinance 与 AkShare 当作天然独立冗余；
- 直接迁移 DataFetcherManager、Axios/Zustand/Tailwind 或整套 Shell；
- 将事后建议命中率当作正式回测结论。

## 建议实施优先级

1. **P0：BaoStock 真实探针。** 先验证 16 只 ETF 的未复权口径、成交额单位、覆盖率和跨源一致性，再决定是否实现备用 Provider。
2. **P1：Run Flow + Evidence Timeline。** 将 Provider 尝试、快照构建、候选池状态转换、重试与失败节点统一可视化。
3. **P1：任务恢复。** 建立稳定任务 ID、可恢复轮询、阶段进度和终态错误展示。
4. **P2：策略解释能力。** 引入策略声明 Schema、过滤 waterfall、逐规则结果和因子贡献，但所有参数进入 StrategyVersion 治理。
5. **P2：AlertRule / DecisionSignal。** 先冻结幂等键、状态机、证据关联和 dry-run 契约，再实现 UI。
6. **P3：组合风险看板与构建身份。** 作为消费侧增强，不阻塞数据与候选池主链。
7. **P4：LLM 实验增强。** 仅在独立实验命名空间运行，不改变默认候选池、正式信号或发布指针。

## 验收门槛

任何参考 DSA 的实现都必须满足：

- 每个输入可追溯到不可变数据批次、原始载荷哈希与精确 revision；
- 策略源码、参数、Universe、日历、调整口径和输入快照都有稳定指纹；
- 数据质量错误 fail closed，不能以降级掩盖字段或口径错误；
- 相同业务输入跨重试得到相同业务结果，技术尝试与业务结果分离；
- 候选池继续执行 `calculated -> validated -> published` 门禁，不允许计算即发布；
- LLM 失败不影响确定性结果，且默认不进入候选池真值链路；
- Web 只消费 OpenAPI 契约，不建立第二套 DTO 或服务端状态源；
- 真实 Provider 验收覆盖单位、日期、重复、空结果、断线与跨源对账；
- 正式回测明确点时一致性、交易成本、滑点、企业行动与持仓路径。

## 风险与限制

1. 本轮是静态在线审读，无法证明上游测试在当前环境通过，也无法证明真实行情端点稳定。
2. 上游代码、README 与 Issue 只能说明实现和历史现象；最终接入结论必须由隔离环境探针和本项目契约测试确认。
3. MIT 仅覆盖上游代码版权许可，不覆盖行情数据、第三方服务器、模型服务或再分发授权。
4. 经验因子与阈值具有策略风险；技术可实现不等于投资有效性，不构成投研决策或回测结论。
5. 上游后续提交可能改变行为；任何未来复审都应重新固定 commit，而不是引用浮动分支。

## 主要一手资料

- 固定提交：<https://github.com/ZhuLinsen/daily_stock_analysis/tree/972c31465654d86c52c59abfdb8414b82808f50f>
- BaoStock Fetcher：<https://github.com/ZhuLinsen/daily_stock_analysis/blob/972c31465654d86c52c59abfdb8414b82808f50f/data_provider/baostock_fetcher.py>
- 筛选评分器：<https://github.com/ZhuLinsen/daily_stock_analysis/blob/972c31465654d86c52c59abfdb8414b82808f50f/src/services/screening/scorer.py>
- 筛选流水线：<https://github.com/ZhuLinsen/daily_stock_analysis/blob/972c31465654d86c52c59abfdb8414b82808f50f/src/services/screening/pipeline.py>
- 回测服务：<https://github.com/ZhuLinsen/daily_stock_analysis/blob/972c31465654d86c52c59abfdb8414b82808f50f/src/services/backtest_service.py>
- 决策信号提取：<https://github.com/ZhuLinsen/daily_stock_analysis/blob/972c31465654d86c52c59abfdb8414b82808f50f/src/services/decision_signal_extractor.py>
- 组合风险服务：<https://github.com/ZhuLinsen/daily_stock_analysis/blob/972c31465654d86c52c59abfdb8414b82808f50f/src/services/portfolio_risk_service.py>
- 告警指标：<https://github.com/ZhuLinsen/daily_stock_analysis/blob/972c31465654d86c52c59abfdb8414b82808f50f/src/services/alert_indicators.py>
- Web Run Flow：<https://github.com/ZhuLinsen/daily_stock_analysis/blob/972c31465654d86c52c59abfdb8414b82808f50f/apps/dsa-web/src/components/run-flow/RunFlowPanel.tsx>
- ETF 多源失败 Issue：<https://github.com/ZhuLinsen/daily_stock_analysis/issues/541>
- License：<https://github.com/ZhuLinsen/daily_stock_analysis/blob/972c31465654d86c52c59abfdb8414b82808f50f/LICENSE>

## 最终建议

把 DSA 定位为**产品交互和业务建模参考库**，而不是 `invest-infra` 的基础框架或策略真值来源。近期最优投入顺序是：

```text
BaoStock 实测门槛
  -> Run Flow / Evidence Timeline
  -> 任务恢复
  -> 过滤与因子解释
  -> AlertRule / DecisionSignal
  -> 组合风险看板与构建身份
```

只有通过真实数据探针、契约测试和现有发布门禁后，局部能力才可进入实现阶段。
