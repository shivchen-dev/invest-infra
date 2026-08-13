# WorkBuddy 每日报告治理 MVP 执行清单

> 当前状态：M0 合同冻结完成；M1 校验器完成；M2 归档 + latest 指针完成；
> M1/M2 收口补丁已加入路径穿越防护（trade_date / workflow_run_id fail-closed）

## M0 合同冻结

- [x] 定义最小输入字段和版本策略（result 事实优先，quality 诊断化）
- [x] 定义 accepted / partial / rejected 判定
- [x] 冻结最小评分兼容合同
- [x] 冻结合法 Override 规则（首版默认禁用）
- [x] 固定 2026-08-13 遗留样本预期 Finding
- [x] 确定规则 1.1.2 golden candidate 目标合同
- [ ] WorkBuddy 按 1.1.2 重生成真实 golden 三件套
- [x] 用户授权收缩并冻结 M0 合同
- [x] 兼容 `result.status`，取消 `quality_report.producer_status` 硬要求
- [x] 将阶段 count、生产者 hash 和重复追溯字段降为可选/诊断

## M1 校验器

- [x] 输入文件与跨文件标识一致性
- [x] 阶段数量、集合与衔接校验
- [x] 缺失数据处理校验
- [x] 单维分与综合分重算
- [x] 排名与候选状态重算
- [x] source reference 校验
- [x] Markdown 固定字段一致性校验
- [x] 按 1.1.2 合同同步 validator：规则版本、`result.status` 别名、quality_report 最小字段
- [x] governed-quality-report.json 生成
- [x] trade_date 严格 YYYY-MM-DD + 真实日期校验（fail-closed）
- [x] workflow_run_id 单路径段字符集 + 长度上限校验（fail-closed）
  - 安全普通点号（如 `wr.001`）允许；以字母或数字开头；仅 ASCII `[A-Za-z0-9._-]`，长度 1–128
- [x] 路径安全回归测试（绝对路径、`../`、`/`、`\`、空白、超长、`.`、`..`、`.hidden`、`wr.001` 合法）

## M2 归档

- [x] 完整 SHA-256 和 manifest
- [x] 日期/run ID 不可变目录
- [x] 相同内容重复导入幂等
- [x] 同 run ID 不同内容拒绝
- [x] accepted-only latest 原子更新（含 fcntl.flock 并发防护）
- [x] validate/import CLI
- [x] archive 边界对 trade_date / workflow_run_id 再校验（防御纵深）

## M3 验收

- [ ] 2026-08-13 真实样本回归
- [x] 现存 1.1.1 真实三件套按 unsupported version fail-closed（exit 4）
- [x] 异常 fixture 测试（合成异常 / 路径穿越 fixture）
- [x] Pipeline focused tests（test_workbuddy_reports_validator + test_workbuddy_reports_archive）
- [x] 相关全量回归（Pipeline：2071 passed）
- [x] 完整 diff 独立验收（正确性、路径安全、范围与 staged diff）
- [ ] 用户审核结果

## 明确暂缓

- [ ] PostgreSQL
- [ ] API / Web
- [ ] Dagster Sensor
- [ ] ExternalObservation / Evidence
- [ ] 月度索引
- [ ] 原始连接器响应长期保存
