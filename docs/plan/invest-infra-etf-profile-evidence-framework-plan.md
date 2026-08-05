# invest-infra ETF Profile Evidence Framework 实施计划 v1.0

## 目标

将 ETF Profile 从静态维表升级为：

> Evidence-backed ETF Profile（证据驱动 ETF 档案）

服务 AI 投资研判系统。

核心原则：

- 不强行填满字段；
- 不猜测未知数据；
- 每个字段必须有来源、时间、质量和可信度；
- AI 读取 Evidence，而不是读取未经解释的字段。

---

# 1. 架构调整

旧：

Provider
↓
ETF Profile

新：

Provider Raw Evidence
↓
Field Mapping
↓
Field Evidence
↓
Profile Resolver
↓
Canonical ETF Profile
↓
Research Evidence Pack

---

# 2. 数据模型

## 2.1 core.etf_profiles

定位：

当前最佳解析结果。

字段：

- instrument_id
- manager
- benchmark_index
- category
- inception_date
- fund_type
- management_fee
- custody_fee
- aum
- shares

用于：

- 查询
- 展示
- Research API


## 2.2 analytics.etf_profile_fields

新增字段证据表：

```
id
instrument_id
field_key
field_value
value_type
source_provider
source_dataset
observed_at
quality_status
confidence_score
content_hash
created_at
```

示例：

```
field:
manager

value:
华夏基金

source:
fund_company

quality:
verified
```

---

# 3. 字段分级

## Level 0 交易基础

必须：

- symbol
- name
- exchange
- fund_type
- status


## Level 1 研究基础

目标：

- manager
- benchmark_index
- category
- inception_date
- aum
- shares


## Level 2 投资分析

后续：

- tracking_error
- expense_ratio
- index_methodology
- creation_redemption


## Level 3 高级研究

未来：

- institution_rating
- historical_style
- investor_behavior

---

# 4. Provider Mapping 原则

Provider 不直接生成 ETF Profile。

流程：

```
AkShare
EastMoney
基金官网
交易所

↓

Raw Evidence

↓

Mapping

↓

Resolver

↓

ETF Profile
```

---

# 5. Profile Resolver

负责：

## 字段优先级

manager:

基金公告
>
基金公司官网
>
交易所
>
第三方


benchmark:

基金公告
>
指数公司
>
基金公司
>
第三方


AUM:

基金公告
>
基金官网
>
第三方


---

## 冲突处理

禁止覆盖。

例如：

Provider A:

benchmark=沪深300

Provider B:

benchmark=中证300


结果：

```
quality_status=conflict
```

AI 不读取冲突字段。

---

# 6. AUM 特别规则

禁止：

```
market_value -> AUM
```

必须区分：

- aum
- market_value
- turnover_value

原因：

交易市值不是基金资产规模。

---

# 7. 实施 PR

## PR-ETF-PROFILE-01

ETF Profile Field Domain

内容：

- Field Evidence Model
- Quality Status
- Confidence
- Provenance


## PR-ETF-PROFILE-02

Provider Mapping

内容：

- AkShare
- EastMoney
- 基金信息源

要求：

- 不填默认值；
- 保留来源；
- 保留缺失。


## PR-ETF-PROFILE-03

Profile Resolver

内容：

- 字段优先级；
- 冲突检测；
- Canonical View。


## PR-ETF-PROFILE-04

Evidence Pack 集成

输出：

```json
{
 "manager":{
   "value":"xxx",
   "source":"xxx",
   "confidence":0.95
 }
}
```

---

# 8. 测试计划

## Domain

测试：

- 字段合并
- 冲突
- confidence
- quality


## Provider

测试：

- 字段映射
- 缺失字段
- 错误字段
- hash


## Resolver

测试：

- 优先级
- fallback
- 冲突


## Storage

测试：

- 字段证据保存
- revision
- 唯一约束


## Evidence Pack

测试：

- profile引用
- source追踪
- AI JSON输出


---

# 9. Definition of Done

完成：

- ETF Profile 不依赖单 Provider
- 所有字段可追溯
- 缺失明确标记
- 冲突不会覆盖
- AUM 与 market_value 分离
- core.etf_profiles 是 canonical view
- Field Evidence 可查询
- Evidence Pack 可引用
- AI 可以区分事实和未知

---

# 10. 后续路线

ETF Profile 完成后：

```
Index Exposure
        ↓
Holdings
        ↓
Valuation
        ↓
Market Regime
        ↓
External Evidence
        ↓
AI Investment Research
```

最终目标：

构建可信、可追溯的 AI 投研数据底座。
