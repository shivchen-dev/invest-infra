# Stage 4B：TDX 生产日线降频方案

## 目标

降低生产环境对 Tushare 高频接口的依赖：通达信承担本地股票日线，Tushare 保留为低频股票主数据刷新与质量校验来源。

## 实施顺序

### Phase 1：TDX 日线独立可用

- [ ] 支持 `vipdoc/bj/lday` 北交所文件与 `BJSE` 映射。
- [ ] 增加 TDX 日线目录枚举，避免按日期读取时依赖 Tushare 提供 symbol universe。
- [ ] 将 TDX 日线 fallback 接入真实 Dagster stock asset，并保留 evidence lineage。

### Phase 2：股票主数据低频缓存

- [ ] 保留 `core.instruments` 为权威主数据缓存。
- [ ] Tushare `stock_basic` 改为低频刷新；接口限流时复用最近一次成功快照。
- [ ] TDX 仅补充代码/市场发现，不伪造名称、上市状态等主数据字段。

### Phase 3：生产验收

- [ ] 用真实 TDX 数据跑单日股票日线链路。
- [ ] 验证 Tushare 限流时日线仍可入库、主数据缓存不丢失。
- [ ] 验证沪深北交易所映射、证据链和失败可审计性。

## 约束

- 不删除 Tushare；它仍负责低频主数据刷新和交叉校验。
- 不把 TDX `.day` 文件推断出的信息扩展成未经验证的财务/估值数据。
- 每个阶段独立测试、独立提交，未完成能力保持显式关闭。
