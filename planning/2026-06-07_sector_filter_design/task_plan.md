# 行业ETF板块成分股筛选 — 实施计划

**创建日期:** 2026-06-07
**负责人:** Arc
**状态:** 待启动

---

## 需求确认

- **持仓数量:** 前20大重仓股（方案二为成分股筛选，无持仓概念）
- **实用性:** 每日收盘后（早盘 09:00、午盘 13:30 执行）
- **方案:** 方案二（实时板块成分股筛选）

---

## 实施阶段

### Phase 1：强势行业识别验证
- [ ] 调用 `sector_analysis` 验证输出
- [ ] 确认 quadrant 和 change_60d 筛选逻辑
- [ ] 输出 top 3 行业列表

### Phase 2：成分股映射验证
- [ ] 调用 `stock_screener` 验证概念板块映射
- [ ] 确认 conceptKeywords 与行业名匹配关系
- [ ] 确认每行业返回数量上限

### Phase 3：K线数据验证
- [ ] 调用 `kline` 批量获取成分股数据
- [ ] 验证 ma5/ma10/ma20/ma60 计算正确性
- [ ] 验证 `valuation_snapshot` 数据格式

### Phase 4：筛选逻辑实现
- [ ] 实现均线偏离度计算
- [ ] 实现 20 日涨幅计算
- [ ] 实现量比计算
- [ ] 实现分类标签逻辑

### Phase 5：Cron 任务注册
- [ ] 创建 `cron_etf_sector_filter.py`
- [ ] 注册早盘（09:05）和午盘（13:35）cron
- [ ] 配置输出格式和日志

### Phase 6：端到端验证
- [ ] 对比人工筛选结果
- [ ] 验证 signal_strength 排序合理性
- [ ] 验证分类标签准确性

---

## 输出物

1. `technical_design.md` — 完整技术设计
2. `scripts/cron_etf_sector_filter.py` — 脚本实现
3. `reports/sector_filter_output_YYYYMMDD.json` — 筛选结果

---

## 时间估算

| Phase | 工作量 | 说明 |
|-------|--------|------|
| Phase 1-2 | 2 小时 | 工具调用验证 |
| Phase 3-4 | 4 小时 | 脚本实现 |
| Phase 5 | 1 小时 | Cron 注册 |
| Phase 6 | 2 小时 | 端到端验证 |
| **合计** | **~1 天** | |