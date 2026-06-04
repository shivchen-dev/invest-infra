# Findings: factors 模块修复方案

---

## engine.py

### E01（P0）：迭代器索引错位
**位置:** 约 L139
**问题:** `valid_values` 过滤 None 后长度缩短，percentile/zscore 迭代器与原 `values` 列表索引错位
**修复:** 改用 company_id 做字典映射：
```python
pct_map = {v["company_id"]: p for v, p in zip(valid_values, percentiles)}
for v in values:
    pct = pct_map.get(v["company_id"])
```

---

### E02（P1）：std=0 时 zscore 返回错误
**位置:** 约 L104
**当前代码:**
```python
return [round(float(x - mean), 6) if not np.isnan(x) else None for x in arr]
# std=0 时缺少除以 std 的步骤
```
**修复:** std==0 时返回全 0：
```python
if std == 0:
    return [0.0 if not np.isnan(x) else None for x in arr]
```

---

### E03（P1）：rank 字段永不更新
**位置:** 约 L155
**问题:** INSERT 传入 None，ON CONFLICT UPDATE 未包含 rank
**修复:** 方案1：计算 rank 并写入；方案2：从 INSERT 中移除该字段

---

### E04（P1）：UPSERT 遗漏 3 字段
**位置:** 约 L147
**问题:** ON CONFLICT UPDATE 遗漏 formula_desc/data_source/frequency
**修复:**
```sql
ON CONFLICT ... DO UPDATE SET
  name=EXCLUDED.name, category=EXCLUDED.category,
  formula_desc=EXCLUDED.formula_desc,
  data_source=EXCLUDED.data_source,
  frequency=EXCLUDED.frequency,
  updated_at=now()
```

---

## base.py

### B01（P1）：load_quotes 缺少复权说明
**位置:** 约 L61
**修复:** 补充 docstring 说明数据是否已复权，或暴露 adjust_mode 参数

### B02（P2）：conn 生命周期注释
**修复:** 添加 docstring 说明"建议使用 with 语句或手动 close()"

### B03（P2）：load_financial_reports docstring
**修复:** 补充说明"返回全部历史记录，用于需要历史序列的场景"

---

## registry.py

### R01（P1）：sync UPSERT 遗漏 3 字段
**位置:** 约 L119
**修复:** 同 E04 修复方案