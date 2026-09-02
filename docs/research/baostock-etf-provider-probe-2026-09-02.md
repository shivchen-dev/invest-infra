# BaoStock ETF 备用 Provider 真实探针报告

> 日期：2026-09-02
> 范围：`config/personal-universe.yaml` 当前启用的 16 只 ETF
> 结论：`conditional_admit`（仅日常增量与近期运行窗口）
> 性质：只读网络探针；未写数据库、未修改业务链路、未引入项目依赖

## 1. 决策摘要

BaoStock 0.9.3（包内版本字符串 `00.9.30`）可以返回 16 只目标 ETF 的近期未复权
日线，OHLCV 和 `amount` 均非空：

- 2026-08-03 至 2026-08-31：16/16 成功，每只 21 行；
- 2026-05-01 至 2026-08-31：16/16 成功，每只 83 行，超过系统正式因子所需的
  60/61 个交易日；
- 2020-08-03 至 2020-08-31：16/16 为 `zero_rows`；
- 按项目标的主数据，2020-08-31 前已上市 14 只，生命周期有效覆盖率为 **0/14**；
- 扩展诊断的 2019–2025 各年 8 月窗口同样全部为 `zero_rows`。

本项目不做回测，Provider 的首要标准不是多年历史完备，而是能否支持日常增量采集、
当前因子运行窗口和短期断线恢复。因此本轮结论修正为 `conditional_admit`：可继续评估
最小备用 Adapter，但能力必须明确限制为日常增量与近期窗口；不得宣称支持多年历史重建。

## 2. 一手合同依据

BaoStock 官方历史 K 线文档定义：

- `adjustflag="3"` 为不复权，`1` 为后复权，`2` 为前复权；
- 日线 `volume` 为累计成交量，单位“股”；
- `amount` 为成交额，单位“人民币元”。

来源：

- [BaoStock 获取历史 A 股 K 线数据](https://www.baostock.com/mainContent?file=stockKData.md)
- [BaoStock 原始 Markdown 文档](https://www.baostock.com/helpdocs/api/markdown/stockKData.md)
- [BaoStock Python API 总页](https://www.baostock.com/mainContent?file=pythonAPI.md)
- [PyPI baostock 0.9.3](https://pypi.org/project/baostock/)

官方通用历史接口文档以“A股历史K线”为标题，未明确保证 ETF 历史覆盖。客户端包虽含
ETF 单日接口和 ETF 示例，但不能据此推断 `query_history_k_data_plus` 提供完整 ETF 历史。
本报告以真实返回结果作为准入事实。

## 3. 探针方法

### 3.1 标的与映射

探针从 `config/personal-universe.yaml` 动态读取启用分组，共解析 16 只 ETF：

`159901, 159905, 510300, 510500, 159915, 510050, 510180, 510330, 510880, 512000, 512880, 588000, 588080, 513050, 513100, 518880`

映射规则：`5xxxxx -> sh.<symbol>`，`1xxxxx -> sz.<symbol>`。

### 3.2 请求合同

- API：`query_history_k_data_plus`
- fields：`date,code,open,high,low,close,volume,amount`
- frequency：`d`
- adjustflag：`3`
- 登录：一次匿名登录，全部查询完成后一次 best-effort 登出
- 成功判定：登录、初始查询和分页结束后的 `error_code` 均必须为 `0`
- 空结果：单独记录为 `zero_rows`，不计成功覆盖

初始窗口：

- 近期：2026-08-03 至 2026-08-31
- 历史：2020-08-03 至 2020-08-31

因历史窗口异常，追加 2019–2025 各年 8 月窗口用于定位覆盖边界。该追加仅扩大时间样本，
未增加系统模块、数据库或长期运行设施。

根据系统实际用途，另追加 2026-05-01 至 2026-08-31 的运行窗口，验证正式因子所需的
60/61 个交易日，而不是用多年历史覆盖作为回测式硬门槛。

## 4. 结果

### 4.1 登录与运行

| 项目 | 结果 |
|---|---|
| BaoStock 包版本参数 | `0.9.3` |
| 包内版本字符串 | `00.9.30` |
| login | `error_code=0`, `success` |
| 首轮查询单元 | 32（16 标的 × 2 窗口） |
| 首轮耗时 | 3.137 秒 |
| logout | 成功 |

### 4.2 覆盖

| 窗口 | 生命周期有效标的 | 成功 | 零行 | 总行数 | 判断 |
|---|---:|---:|---:|---:|---|
| 2026-08-03..2026-08-31 | 16 | 16 | 0 | 336 | 近期覆盖完整 |
| 2026-05-01..2026-08-31 | 16 | 16 | 0 | 1328 | 每只83行，满足当前运行窗口 |
| 2020-08-03..2020-08-31 | 14 | 0 | 14（API 对16只均零行） | 0 | 历史覆盖失败 |

2020 生命周期分母排除了尚未上市的 `588000` 和 `588080`。其余 14 只在项目标的主数据中
均已于该窗口前上市。

追加诊断：

| 年份窗口 | API 查询标的 | 成功 | 零行 | 总行数 |
|---|---:|---:|---:|---:|
| 2025-08 | 16 | 0 | 16 | 0 |
| 2024-08 | 16 | 0 | 16 | 0 |
| 2023-08 | 16 | 0 | 16 | 0 |
| 2022-08 | 16 | 0 | 16 | 0 |
| 2021-08 | 16 | 0 | 16 | 0 |
| 2020-08 | 16 | 0 | 16 | 0 |
| 2019-08 | 16 | 0 | 16 | 0 |

### 4.3 近期字段质量与单位自洽性

近期窗口全部 336 行：

- OHLCV/amount 均无缺失、无非数值；
- 无重复日期、无倒序；
- 2026-08-31 单日对 16 只 ETF 计算 `amount / volume`，全部落在当日
  `[low, high]` 内。

该结果与官方“volume=股、amount=人民币元”的定义内部一致，但不能替代独立跨源对账。

### 4.4 跨源对账

对 `510300` 的 AkShare 未复权单日请求仍返回：

`ConnectionError: RemoteDisconnected('Remote end closed connection without response')`

因此本次无法完成 BaoStock 与 AkShare 的同日数值对账。该项是 Adapter 真实验收的保留
条件，但不应以多年历史缺失替代对日常运行能力的判断。

## 5. 错误处理验证

探针在真实运行前补充了分页错误负面路径：BaoStock 的 `next()` 在正常 EOF 和分页/网络
错误时都可能返回 `False`，因此脚本在迭代结束后再次检查最终 `error_code/error_msg`。
模拟尾部分页错误 `10005001` 时，结果正确标记为 `error_iterator`，同时保留已获取行的
统计与哈希，不会误报为 `ok` 或 `zero_rows`。

## 6. 准入判断

| 准入项 | 结果 |
|---|---|
| 16只目标 ETF 近期覆盖 | 通过 |
| 未复权请求口径 | 通过（请求合同） |
| volume/amount 单位内部自洽 | 通过 |
| 当前正式因子 60/61 日窗口 | **通过：16/16，每只83行** |
| 多年历史重建能力 | 不支持：2020生命周期有效覆盖0/14 |
| 跨源数值对账 | 阻塞（AkShare 上游断连） |
| 日常增量/近期窗口备用准入 | **conditional_admit** |

BaoStock 可以进入最小 Adapter 的后续评估，但合同必须声明“不支持多年历史重建”，并在
实现验收中继续验证连续调用稳定性、当日增量、错误分类和跨源数值口径。不建设字段路由或
覆盖平台，不执行历史回填、部署或生产切换。

## 7. 可复算证据

运行证据保存在本机 gitignored 目录：`.runs/baostock-phase1-20260902/`。
正式报告不记录绝对宿主机路径、凭证或代理配置。

| 文件 | SHA-256 |
|---|---|
| `probe_baostock_etf.py` | `38ea2b7da800088b7bd5f434d2a859290ffcb38155a6c25f0884a8da265affc9` |
| `probe-result.json` | `fd85d5b2e80d38da40ae256b17c90fb24ab9a74e82dc89c1f7b08301071bbcc0` |
| `probe-history-diagnostic.json` | `1110db06d5c94d3e47ff0d1e76735c9e6f8110d50d9fd83f476d0561f13baae1` |
| `probe-single-day.json` | `3a81aad6086e96c38d8826efcce4f8a65674b9163c80bd22d4c04d0d07498972` |
| `probe-operational-window.json` | `46e4b054916daadbcbc779db5251bcbb0d4e3e92cde68cf2fd9b71fc8ca0b887` |

本次未修改产品依赖，BaoStock 仅通过临时 `uv run --with baostock==0.9.3` 环境执行。
