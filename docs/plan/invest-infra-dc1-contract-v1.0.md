# DC-1 Provider 与数据质量契约 v1.0

> 本文冻结 DC-1 的最小实现边界。当前只定义代码级纯函数契约，不新增数据库表、不发起网络请求。

## 1. Provider Registry

Registry 是代码级策略注册表，不是数据库实体。它建立：

```text
provider_key
dataset
priority
reliability_score
freshness_sla_days
supported_fields
```

Registry 必须校验 Provider 已在 Provider Catalog 中声明，且声明的 capability 能覆盖 Dataset 要求。注册项按 `(priority, provider_key)` 稳定排序。

当前 `priority`、`reliability_score`、`freshness_sla_days` 属于 provisional policy values，不代表真实统计结果；在真实质量样本积累前不得解释为实测可靠性。

## 2. ETF 日行情质量

质量评估输入为现有 `CoverageReportModel`、单个 Provider 注册项、期望 Symbol 集合和评估日期。

### 2.1 覆盖率

```text
coverage_ratio = 完成覆盖的期望 Symbol 数 / 期望 Symbol 总数
```

Symbol 只有同时满足以下条件才算完成覆盖：

- 存在 covered date range；
- 包含 Registry 要求的全部字段；
- 没有 errors。

### 2.2 字段完整率

```text
completeness_ratio = 存在且字段齐全的期望 Symbol 数 / 期望 Symbol 总数
```

当前版本按 Symbol 统计，不按记录数统计。缺失 Provider 视为全部 Symbol 缺失并进入 failed 状态。

### 2.3 新鲜度

使用期望 Symbol 的最新 `covered_end` 与评估日期计算天数：

- `days <= freshness_sla_days`：`fresh`；
- `days <= 2 * freshness_sla_days`：`warning`；
- 其余：`failed`。

当 SLA 为 0 时，仅评估日期当天算 `fresh`，否则为 `failed`。

### 2.4 综合质量分

```text
quality_score =
    coverage_ratio      * 0.30
  + completeness_ratio  * 0.30
  + freshness_score     * 0.20
  + reliability_score   * 0.20
```

其中 freshness score 分别为 `1 / 0.5 / 0`，最终分数限制在 `[0, 1]`，使用 Decimal 计算。

## 3. 本阶段不包含

- Provider 真实网络可用性治理；
- 数据库持久化 Registry；
- Coverage CLI 接入；
- 跨 Provider 值一致性比较（属于后续 DC1-C）。

## 4. 验收门槛

- Registry 能拒绝未知 Provider、能力不匹配和非法策略值；
- 质量评估能覆盖完整、缺失、错误、过期和 SLA 为零的路径；
- 所有结果稳定排序、可重复计算；
- focused tests、Ruff 和相关 pipeline 回归通过。
