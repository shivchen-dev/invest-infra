# 行业ETF板块成分股筛选 — 技术设计

**创建日期:** 2026-06-07
**执行者:** Arc
**需求来源:** `docs/方案需求/2026-06-07_行业ETF持仓采集与价格位置筛选.md`
**状态:** 审计修复完成，待实施

---

## 背景

用户需求：从强势行业ETF成分股中，筛选出"价格位置适中"的标的。

**方案选择：** 方案二（实时板块成分股筛选），原因：
- 零外部依赖，直接复用现有 MCP 工具
- 盘中实时可用，不受季报延迟限制
- 实现成本低，落地快

---

## 整体架构

```
早盘 09:00 / 午盘 13:30
        │
        ▼
┌─────────────────────────┐
│  Phase 1: 强势行业识别    │
│  sector_analysis        │
│  60日动量 × 5日强度      │
└──────────┬──────────────┘
           │ top 3 强势行业
           ▼
┌─────────────────────────┐
│  Phase 2: 成分股获取      │
│  stock_screener          │
│  conceptKeywords         │
└──────────┬──────────────┘
           │ 每行业 top 30（按成交额）
           ▼
┌─────────────────────────┐
│  Phase 3: K线数据补充     │
│  kline (ma5/10/20/60)    │
│  valuation_snapshot      │
└──────────┬──────────────┘
           │ 批量 codes
           ▼
┌─────────────────────────┐
│  Phase 4: 本地计算筛选    │
│  均线偏离度 + 涨幅 + 量比 │
│  → 分类标签输出          │
└─────────────────────────┘
```

---

## Phase 1：强势行业识别

**工具：** `sector_analysis`

```python
# 调用
sector_analysis(
    period=60,        # 60日分析周期
    strengthPeriod=5  # 5日强度
)
```

**输出示例：**

```json
{
  "sectors": [
    {
      "name": "AI语料",
      "change_60d": 18.5,
      "strength_5d": 2.3,
      "quadrant": "strong_momentum"
    },
    {
      "name": "半导体设备",
      "change_60d": 15.2,
      "strength_5d": 1.8,
      "quadrant": "strong_momentum"
    }
  ]
}
```

**筛选逻辑：** 取 quadrant="strong_momentum" 且 change_60d > 10% 的前3个行业

---

## Phase 2：成分股获取

**工具：** `stock_screener`

```python
# 调用（每行业一次）
stock_screener(
    conceptKeywords=["AI语料"],  # Phase 1 行业名
    conceptMode="any",
    market="all",
    excludeST=True,
    limit=30,                   # 每行业 top 30
    sortBy="amountYi",          # 按成交额排序
    sortOrder="desc"
)
```

**返回：** 每行业最多30只成分股（代码/名称/行业/市值）

**合并去重：** 多行业可能重叠，持仓股去重后合并

---

## Phase 3：K线 + 估值数据

**工具：** `kline` + `valuation_snapshot`

```python
# 批量 kline（codes 最多20，需分批）
kline(
    codes=["600519", "300750", ...],  # Phase 2 合并后的股票代码
    days=65,                           # 取65天计算 ma20/ma60
    adjust="qfq"                       # 前复权
)

# valuation_snapshot（codes 最多20）
valuation_snapshot(
    codes=["600519", "300750", ...]
)
```

**kline 返回字段：**
```
date, open, high, low, close, volume, amount, turnoverRate
```

**计算派生指标：**
```python
# 均线计算
ma5  = close.rolling(5).mean()
ma20 = close.rolling(20).mean()
ma60 = close.rolling(60).mean()

# 均线偏离度
deviation_ma20 = (price - ma20) / ma20 * 100   # 百分比
deviation_ma60 = (price - ma60) / ma60 * 100

# 20日涨幅
pct_chg_20d = (close - close_20d_ago) / close_20d_ago * 100

# 量比 = 今成交量 / 过去5日均量
volume_ratio = volume / volume_ma5
```

---

## Phase 4：筛选与分类

**筛选条件：**

```python
def filter_candidates(row):
    # 排除停牌股票（volume=0 或 price=NaN）
    if row['volume'] == 0 or pd.isna(row['price']):
        return False
    
    conditions = [
        # 均线位置：price 在 ma20 ±5% 以内，或 ma60 ±10% 以内
        abs(row['deviation_ma20']) <= 5 or abs(row['deviation_ma60']) <= 10,
        
        # 20日涨幅：-15% ~ 30%
        -15 <= row['pct_chg_20d'] <= 30,
        
        # 量比 ≥ 1.0
        row['volume_ratio'] >= 1.0,
        
        # 排除 ST
        not row['is_st']
    ]
    return all(conditions)
```

**分类标签：**

```python
def classify(row):
    # 优先级：超跌 > 稳健 > 进取 > 震荡
    if row['deviation_ma20'] < -10:
        return "超跌型"      # 🟡 均值回归可能（偏离度最大，优先判断）
    elif abs(row['deviation_ma20']) <= 5 and abs(row['deviation_ma60']) <= 10:
        return "稳健型"      # 🟢 价格在多条均线附近
    elif row['price'] > row['ma20'] and row['pct_chg_20d'] > 0:
        return "进取型"      # 🔵 趋势向上
    else:
        return "震荡型"      # ⚪ 反复穿越均线
```

---

## 输出格式

```json
{
  "generated_at": "2026-06-07 14:30:00",
  "trigger": "午盘筛选",
  "strong_sectors": ["AI语料", "半导体设备", "机器人"],
  "summary": {
    "total_candidates": 47,
    "稳健型": 12,
    "进取型": 18,
    "超跌型": 8,
    "震荡型": 9
  },
  "candidates": [
    {
      "rank": 1,
      "stock_code": "600519",
      "stock_name": "贵州茅台",
      "sector": "AI语料",
      "price": 1680.50,
      "ma20": 1650.00,
      "ma60": 1600.00,
      "deviation_ma20": 1.85,
      "deviation_ma60": 5.03,
      "pct_chg_20d": 8.5,
      "volume_ratio": 1.32,
      "classification": "稳健型",
      "pe_ttm": 28.5,
      "market_cap_yi": 2100.0,
      "signal_strength": 0.82
    }
  ]
}
```

**signal_strength 计算：**
```python
signal_strength = max(0, 
    0.3 * max(0, 1 - abs(deviation_ma20) / 10) +      # 偏离度越小越好，下界0
    0.3 * max(0, 1 - abs(pct_chg_20d) / 30) +         # 涨幅适中，下界0
    0.2 * min(volume_ratio, 2) / 2 +                  # 量比正常
    0.2 * (1 if classification in ["稳健型", "进取型"] else 0.5)
)
```

---

## cron 任务设计

```bash
# 每天 09:05（早盘）和 13:35（午盘）执行
# 文件：data-pipeline/scripts/cron_etf_sector_filter.py

05 09 * * 1-5 cd /home/claw/invest-infra && \
  .venv/bin/python scripts/cron_etf_sector_filter.py --trigger morning

35 13 * * 1-5 cd /home/claw/invest-infra && \
  .venv/bin/python scripts/cron_etf_sector_filter.py --trigger afternoon
```

---

## 实施检查清单

| Phase | 任务 | 状态 | 验证日期 |
|-------|------|------|----------|
| 1 | `sector_analysis` 验证强势行业输出 | ✅ | 2026-06-07 |
| 2 | `stock_screener` 概念板块映射验证 | ✅ | 2026-06-07 |
| 3 | `kline` 批量调用 + 均值计算验证 | ✅ | 2026-06-07 |
| 4 | 本地计算逻辑 + 分类标签实现 | ✅ | 2026-06-07 |
| 5 | cron 任务注册 + 输出格式化 | ⬜ | - |
| 6 | 端到端验证（对比人工筛选结果） | ⬜ | - |

---

## 待验证问题

1. ✅ **stock_screener 的 conceptKeywords 覆盖度** — 已验证：sector_analysis 行业名与 stock_screener.conceptKeywords 直接匹配（MLCC/面板/OLED 均通过）
2. **每行业成分股数量上限** — 建议 top 30 按成交额，避免 API 频率限制
3. **筛选时间窗口** — 主要服务于早盘前（09:00）和午后（13:30）