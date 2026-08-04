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

## AkShare SDK 安装与早期真实探测记录

- SDK：`akshare 1.18.81`，已安装到 `apps/pipeline/.venv`，导入验证通过。
- 适配器单 ETF 调用曾成功返回 23 条记录；随后对 16 个 active ETF 的近期窗口进行有限重试，均在 EastMoney 上游请求阶段失败。
- 失败类型：`ProviderBadResponseError`，根因是经当前代理连接 EastMoney 时 `ProxyError / RemoteDisconnected`。
- 该记录反映早期代理阻塞状态；后续代理链路恢复，见下方“近期窗口复测”。

## 2026-08-04 近期窗口复测

代理链路恢复后，对当前 16 个 active ETF 执行了只读覆盖探测：

| Provider | 日期窗口 | 标的覆盖 | 单标的记录 | 字段完整度 | 错误 |
|---|---|---:|---:|---|---:|
| AkShare | 2026-07-30 — 2026-08-03 | 16/16 | 3 | 6/6 | 0 |
| CifangQuant | 2026-07-30 — 2026-08-03 | 16/16 | 3 | 6/6 | 0 |

- AkShare content hash：`bda9e7852d87ca2c93b08968253328033bb67663695deb3a5469a0dab1a2724a`
- CifangQuant content hash：`15a724b48386ff11c6de92c103b3b92cad8fbf7a37c4e4e8251c52b01799d5e4`
- 两次探测均为只读 CLI，不写 PostgreSQL、不执行历史回填。
- 本结果证明近期窗口的真实可用性，不等同于 2016 年历史覆盖或跨源数值一致性验收。

## 2026-08-04 历史窗口复测（AkShare）

本次仍为只读探测，覆盖同一组 16 个 active ETF，字段为
`open/high/low/close/volume/amount`。闰年窗口按 CLI 的 365 日上限截取至
12 月 30 日。

| 日期窗口 | 标的完整覆盖 | 失败标的 | content hash |
|---|---:|---|---|
| 2016-01-01 — 2016-12-30 | 13/16 | `513050`、`588000`、`588080` | `4fb3390dd02164d1199945c7272406b78847672c5ee2c091f65056fa4e8b9eaa` |
| 2018-01-01 — 2018-12-31 | 14/16 | `588000`、`588080` | `9843a888f30702b7986d0fcacb99830b9eb84d1659202b2cb0dac36777c5da64` |
| 2020-01-01 — 2020-12-30 | 16/16 | 无 | `b7b19d316540c2ba2e510b19f072a7b8835040d45ed9339238d3638e53c94b88` |

- 成功标的均返回完整 6/6 字段；失败均为 EastMoney 上游代理断连，不能据此判定数据不存在。
- CifangQuant 的 2018 对照探测因本机缺少有效认证配置被拒绝，未生成覆盖结论；已有的 CifangQuant 2016/2020/2026-07 结果仍以本文前述记录为准。
- 因历史窗口仍存在 Provider 级失败，PR-05 的全量覆盖矩阵、回填排序和幂等回填暂不宣称完成。
