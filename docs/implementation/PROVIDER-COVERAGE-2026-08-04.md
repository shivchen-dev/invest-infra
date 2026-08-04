# Provider Coverage Probe — 2026-08-04

本记录来自 V2 只读 Coverage CLI 的真实 CifangQuant 验收，不写 PostgreSQL，
不执行历史回填。认证与网络均通过显式进程级配置启用，输出不包含 token。

## 探测范围

- Provider：`cifangquant`
- Symbols：当前 fixture active ETF universe 的 16 个标的
- 字段：`open/high/low/close/volume/amount`
- 复权口径：`none`
- 认证与网络：显式 opt-in，输出已脱敏

## 结果

| 区间 | ETF 数 | 有效条数 | 有数据 ETF 数 | 字段完整度 | 错误 |
|---|---:|---:|---:|---|---:|
| 2016-01-01 — 2016-12-31 | 16 | 0 | 0 | 无记录 | 0 |
| 2020-01-01 — 2020-12-31 | 16 | 3470 | 16 | 16/16 为 6/6 | 0 |
| 2026-07-01 — 2026-07-31 | 16 | 368 | 16 | 16/16 为 6/6 | 0 |

## 结论边界

- CifangQuant 对当前 16 个 active ETF 的 2016 年历史数据均为空，不能执行
  2016 年回填。
- 2020 年和 2026-07 近期数据全部返回完整 6 字段，说明接口链路和字段映射可用。
- 本次是 CifangQuant 单源全量 active-universe 探测；跨 Provider 一致性仍未完成。
- QuickTiny、RssCast、AkShare 本次未被当作 ETF 日线生产源参与探测。

## AkShare SDK 安装与真实探测状态

- SDK：`akshare 1.18.81`，已安装到 `apps/pipeline/.venv`，导入验证通过。
- 适配器单 ETF 调用曾成功返回 23 条记录；随后对 16 个 active ETF 的近期窗口进行有限重试，均在 EastMoney 上游请求阶段失败。
- 失败类型：`ProviderBadResponseError`，根因是经当前代理连接 EastMoney 时 `ProxyError / RemoteDisconnected`。
- 结论：当前不能据此判定 AkShare 字段映射或覆盖能力不足；真实全量覆盖报告待代理/上游链路恢复后重跑。
