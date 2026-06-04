# 数据采集层缺陷修复计划
<!--
  WHAT: 修复评估报告中确认的22个代码缺陷（P0+P1）
  WHEN: 2026-06-04 启动
  WHY: 数据采集层可靠性不足，影响FQIR数据可信度
-->

## Goal
按批次修复数据采集层所有确认缺陷，每批用Claude Code完成，
最终commit到 `/home/claw/invest-infra/` git工作区。

## Current Phase
Batch 1: pg.py 基础函数修复（2个P0）

---

## Phases

### Batch 1: pg.py — 基础清洗函数（P0）
<!-- NV1 + DV1：_nan_to_none 不处理字符串NaN + _normalize_date 仅处理ISO T格式 -->
- [x] NV1: `_nan_to_none` 增加字符串 "NaN"/"inf"/pandas NA 处理
- [x] DV1: `_normalize_date` 使用 dateutil.parser + 日期合法性校验
- [x] 验证：输出正确（None/合法日期/warning）
- **Status:** ✅ complete

### Batch 2: financial.py + news.py（P0+P1）
<!-- financial: F1(×3裸except) + F2(嵌套函数) + F3(硬编码列名) -->
<!-- news: N1(裸except) + N2(时间解析) + N3(截断) -->
- [x] F1: 3处裸 except → logger.error(... exc_info=True)
- [x] F2: 嵌套函数 `_val()` 提取为模块级
- [x] F3: 硬编码列名增加动态校验
- [x] N1: 裸 except → logger.error(... exc_info=True)
- [x] N2: 时间解析用 dateutil.parser.parse()
- [x] N3: 截断前加非空检查
- **Status:** ✅ complete

### Batch 3: etf.py + cifang.py（P1）
<!-- etf: E1(无异常) + E2(直连) + E3(循环import) + E4(前缀不一致) -->
<!-- cifang: C1(×3直连) -->
- [x] E1: fetch_etf_spot 增加 try/except
- [x] E2: 直连改用 pg.get_conn() 上下文管理器
- [x] E3: 循环内 import 移到文件顶部（原文件无此问题）
- [x] E4: _etf_prefix 与 _market_for_code 逻辑统一
- [x] C1: 3处直连接池化
- **Status:** ✅ complete

### Batch 4: rsscast.py + companies.py（P1）
<!-- rsscast: R1(全局_default_client竞态) -->
<!-- companies: CP1(无异常) + CP2(直连) -->
- [x] R1: 全局 _default_client 改为 threading.Lock + double-checked locking
- [x] CP1: akshare 调用加 try/except + logger.error
- [x] CP2: 直连改用 pg.get_conn() 上下文管理器
- **Status:** ✅ complete

### Batch 5: quotes.py 剩余（P1）
<!-- Q3(默认SH) + Q4(iterrows性能) -->
- [x] Q3: 未知代码不默认SH，抛出 ValueError
- [x] Q4: iterrows 改为 df.to_dict('records') 向量化
- **Status:** ✅ complete

---

## 已完成

### quotes.py（P0 已修复）
- [x] Q1: except Exception → logger.error(... exc_info=True) + 升级为 error
- [x] Q2: 涨跌幅从 (close-open)/open 改为 (close-pre_close)/pre_close，pre_close 用 shift(1) 计算
- **commit:** 工作区未提交，当前会话修复

### 评估报告确认结果
```
模块      | 问题数 | 已确认 | 已修
quotes.py |   4   |   3   | Q1+Q2
financial |   3   |   3   | 0
news.py   |   3   |   3   | 0
etf.py    |   4   |   4   | 0
cifang.py |   1   |   1   | 0
rsscast   |   1   |   1   | 0
companies |   2   |   2   | 0
pg.py     |   2   |   2   | 0
```

---

## Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| 评估报告Q2已修(quotes) | 本地验证 | 确认修复正确 |