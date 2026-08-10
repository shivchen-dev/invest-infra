# TDX .day offline reader — Spike

最小只读实现，用于解析通达信本地日线数据文件（``.day``）。本 Spike 不入
库、不复权、不做主数据映射，仅完成读取与规范化。

## 文件来源

Spike 不内置示例数据；任何调用方按如下布局自行准备目录：

```
<root>/vipdoc/sh/lday/sh600000.day
<root>/vipdoc/sz/lday/sz000001.day
```

* 市场目录：`sh` 或 `sz`，对应沪市与深市。
* 文件命名：`<market><symbol>.day`，symbol 为六位数字代码（如
  `600000`、`000001`）。
* 子目录必须为 `vipdoc/<market>/lday`。

## 记录格式

每条记录 32 字节，little-endian：

| 偏移 | 长度 | 类型      | 含义                                     |
|------|------|-----------|------------------------------------------|
| 0    | 4    | uint32    | `YYYYMMDD` 日期                          |
| 4    | 4    | uint32    | open，`价格 × 100`                       |
| 8    | 4    | uint32    | high，`价格 × 100`                       |
| 12   | 4    | uint32    | low，`价格 × 100`                        |
| 16   | 4    | uint32    | close，`价格 × 100`                      |
| 20   | 4    | float32   | 成交额（元）                             |
| 24   | 4    | uint32    | 成交量（股）                             |
| 28   | 4    | —         | 保留字节，本实现忽略                     |

struct 表示：`<5IfI4x`。读取时把每条记录拆解为 `TdxDailyBar`，价格与
成交额转换为 `Decimal` 以避免二进制浮点误差在管线内继续传播。

## 公开接口

```python
from invest_pipeline.adapters.tdx_offline import (
    PROVIDER_KEY,         # "tdx_offline"
    DATASET_KEY,          # "stock_daily_bars"
    read_day_file,
    read_symbol,
    TdxDailyBar,
    TdxOfflineError,
)
```

* `read_day_file(path, *, start_date=None, end_date=None)`：读取任意
  `.day` 文件。
* `read_symbol(root, market, symbol, *, start_date=None, end_date=None)`：
  按上述目录布局解析并读取。`start_date`/`end_date` 接受 `YYYYMMDD` int
  或 `datetime.date`，过滤为闭区间。

## 错误模型

所有异常均派生自 `TdxOfflineError`，便于 Spike 作为整体被上游捕获。
具体子类用于精确定位失败原因：

| 异常                       | 触发场景                                         |
|----------------------------|--------------------------------------------------|
| `TdxFileMissingError`      | 文件不存在（含上游目录缺失）                     |
| `TdxInvalidPathError`      | 路径存在但不是常规文件                           |
| `TdxInvalidSizeError`      | 文件大小不是 32 字节的倍数                       |
| `TdxInvalidDateError`      | 日期字段无法解析为合法 `YYYYMMDD`                |
| `TdxInvalidValueError`     | OHLC / amount / volume 出现非有限值或负值        |
| `TdxInvalidMarketError`    | market 不是 `sh` / `sz`                          |
| `TdxInvalidSymbolError`    | symbol 不是六位数字                              |

## 行为说明

* 空文件返回空元组 `()`，不抛异常。
* 大小不是 32 倍数 → `TdxInvalidSizeError`，整文件拒绝。
* 任意单条记录非法 → 整文件拒绝（先于日期过滤之前）。
* 未提供 `start_date`/`end_date` 时不过滤。
* 上游目录（`vipdoc/sh/lday` 等）缺失时，由 `read_symbol` 解析得到的
  文件路径不存在 → `TdxFileMissingError`。

## 明确不做

* ETF 协议解析（仅支持 A 股日线 32 字节格式）。
* 入库或 API 暴露（仅在进程内返回 `TdxDailyBar` 元组）。
* 复权（前/后复权）、主数据映射到 `InstrumentId`。
* 异步 IO、并发、缓存、行情合并。
* 依赖任何非标准库第三方包（仅 `struct` / `pathlib` / `decimal` /
  `math` / `datetime`）。

## 测试

```
cd apps/pipeline
uv run --no-env-file pytest -q tests/unit/test_tdx_offline_reader.py
```

测试覆盖：两条记录的解析与日期过滤、`sh`/`sz` 路径、非 32 倍大小、
非法日期、缺失文件、非法（非有限 / 负）值、最后 4 字节被忽略、空文件、
错误模型。