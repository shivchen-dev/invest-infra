# formatters.py 修订计划 — 对齐 CIA 三阶段模板

**创建日期:** 2026-06-07
**更新日期:** 2026-06-07
**状态:** 🚧 进行中

---

## 任务目标

修订 `/home/claw/invest-infra/data-pipeline/src/reports/formatters.py` 对齐 CIA 三阶段模板结构：
- 盘前晨报：新增「策略五大方向信号」「ETF溢价率」板块
- 盘中追踪：新增「策略方向实时信号」「ETF溢价率监控」板块
- 盘后复盘：新增「策略方向复盘」「ETF套利信号」「断板与高标杀」板块

---

## 问题清单

| ID | 严重度 | 描述 | 对应 CIA板块 |
|----|--------|------|---------------|
| F-01 | P0 | 盘前报缺少「策略五大方向信号」板块（物理AI/光模块/PCB/CPO/宽基ETF） | 盘前晨报 → 策略方向跟踪 |
| F-02 | P0 | 盘前报缺少「ETF溢价率」专项板块 | 盘前晨报 → ETF盘前信号 |
| F-03 | P0 | 盘中追踪缺少「策略方向实时信号」板块 | 盘中追踪 → 策略方向实时信号 |
| F-04 | P0 | 盘中追踪缺少「ETF盘中溢价率监控」板块 | 盘中追踪 → ETF盘中溢价率监控 |
| F-05 | P0 | 盘后复盘缺少「策略方向复盘」板块（五大方向） | 盘后复盘 → 策略方向复盘 |
| F-06 | P0 | 盘后复盘缺少「ETF套利信号」专项板块 | 盘后复盘 → ETF套利信号复盘 |
| F-07 | P1 | 盘前报缺少「集合竞价」数据板块 | 盘前晨报 → 盘前异动 |
| F-08 | P1 | 盘前报缺少「宏观事件」数据板块 | 盘前晨报 → 宏观/事件面 |
| F-09 | P1 | 盘后复盘缺少「断板与高标杀」板块 | 盘后复盘 → 断板与高标杀 |

---

## 批次计划

### Batch 1: 盘前报结构重构（PreMarketFormatter）
- [ ] F-01: 新增策略五大方向信号板块
- [ ] F-02: 新增 ETF 溢价率专项板块
- [ ] F-07: 新增集合竞价数据接口
- [ ] F-08: 新增宏观事件数据接口
- **Status:** pending

### Batch 2: 盘中追踪结构重构（MiddayFormatter + IntradayAlertFormatter）
- [ ] F-03: 新增策略方向实时信号板块
- [ ] F-04: 新增 ETF 盘中溢价率监控板块
- **Status:** pending

### Batch 3: 盘后复盘结构重构（PostMarketFormatter）
- [ ] F-05: 新增策略五大方向复盘板块
- [ ] F-06: 新增 ETF 套利信号专项板块
- [ ] F-09: 新增断板与高标杀板块
- **Status:** pending

### Batch 4: 统一入口和工具函数
- [ ] 更新 `get_formatter()` 和 `format_report()` 确认接口兼容
- [ ] 验证 `MAX_MSG_LENGTH` 和消息拆分逻辑
- **Status:** pending

---

##验收标准

- [ ] 盘前报包含策略五大方向信号 + ETF 溢价率（新增2 个板块）
- [ ] 盘中追踪包含策略方向实时信号 + ETF 溢价率监控
- [ ] 盘后复盘包含策略方向复盘 + ETF套利信号 + 断板高标杀
- [ ] 宏观事件和集合竞价数据接口就位
- [ ] `python3 -m py_compile` 验证通过
- [ ] CIA 模板格式兼容（标题/分隔线/板块结构对齐）

---

## 输出文件

- `/home/claw/invest-infra/data-pipeline/src/reports/formatters.py`（修订后）
- `/home/claw/invest-infra/planning/2026-06-07_formatters_revision/progress.md`（执行日志）