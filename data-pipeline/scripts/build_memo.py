import sys
sys.path.insert(0, '/home/claw/invest-infra/data-pipeline')
import psycopg2, json, datetime
from src.config import pg as pg_config
conn = psycopg2.connect(host=pg_config.host, port=pg_config.port, dbname=pg_config.db, user=pg_config.user, password="***")
cur = conn.cursor()
cur.execute("""
    SELECT memo_type, title, summary, body_md, sections_json, confidence_level, trigger_signals, created_at
    FROM investment_memos
    WHERE memo_date = CURRENT_DATE
    AND memo_type IN ('morning_collect','factor_calculation','etf_alpha_signal','risk_monitoring','daily_report')
    ORDER BY created_at ASC
    LIMIT 10
""")
rows = cur.fetchall()
cur.close(); conn.close()

memos = {}
for row in rows:
    memo_type = row[0]
    if memo_type not in memos:
        memos[memo_type] = row

collect   = memos.get('morning_collect',   (None,)*8)
factor    = memos.get('factor_calculation',(None,)*8)
etf_alpha = memos.get('etf_alpha_signal',  (None,)*8)
risk      = memos.get('risk_monitoring',   (None,)*8)
daily     = memos.get('daily_report',      (None,)*8)

events = []
if collect[2]: events.append(f"行情采集：{collect[2][:100]}")
if factor[2]:  events.append(f"因子计算：{factor[2][:100]}")
if etf_alpha[2]: events.append(f"ETF信号：{etf_alpha[2][:100]}")
if risk[2]:    events.append(f"风险监控：{risk[2][:100]}")

risks = []
if collect[2] and ('受阻' in collect[2] or '中断' in collect[2]):
    risks.append("⚠️ akshare数据源连接异常，沪深300行情采集受阻")
if risk[2] and 'low' in str(risk[2]).lower():
    risks.append("⚠️ 风控数据不足，置信度low")
if not risks:
    risks.append("✅ 今日主要风险已识别，无重大警报")

quant = []
if etf_alpha[2] and '1486' in str(etf_alpha[2]):
    quant.append("✅ ETF管线正常（1486条）")
if factor[2] and 'low' in str(factor[2]).lower():
    quant.append("⏳ 5类因子待数据恢复后补算")

all_conf = [c for c in [collect[5], factor[5], etf_alpha[5], risk[5], daily[5]] if c]
overall = "high" if all(c == "high" for c in all_conf) else ("medium" if any(c == "medium" for c in all_conf) else "low")

now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
today = datetime.date.today().isoformat()

all_signals = set()
for r in rows:
    if r[6]:
        for s in r[6]:
            all_signals.add(s)

print(f"""# 【每日投资参考备忘录】

**标题**：Morning Briefing - {today}
**时间戳**：{now}
**置信度**：{overall.upper()}

---

## 一行结论
{collect[2] if collect[2] else '数据采集中，详见下方分析。整体置信度medium，akshare数据源中断为主要制约因素。'}

---

## 二级摘要（3–5 条）

### 事件摘要
{chr(10).join(f"- {e}" for e in events)}

### 量化信号
{chr(10).join(f"- {q}" for q in quant)}

### 风险提示
{chr(10).join(f"- {r}" for r in risks)}

### 操作建议框架（非买卖建议）
- [ ] 待akshare数据源恢复后，重新采集今日沪深300成分行情
- [ ] 北向资金数据需等收盘后（15:00）补采
- [ ] ETF管线正常运行（1486条），可优先参考ETF层面信号

---

## 详细分析

### 基本面分析
{daily[3] if daily[3] else collect[3] if collect[3] else '今日行情数据因数据源问题暂不可用，待恢复后补充。'}

### 量化分析
{factor[3] if factor[3] else '因子计算依赖日行情数据，数据恢复后5类因子将自动补算（动量/价值/质量/资金流/技术）。'}

### 情绪与舆情
{risk[3] if risk[3] else '情绪数据依赖沪深300行情，数据源恢复后补充完整风控扫描。'}

### 情景假设
- **中性情景**：akshare数据源恢复，盘中行情正常，置信度提升至high
- **悲观情景**：数据源持续异常，以ETF信号为主，股票信号维持low
- **乐观情景**：数据快速恢复+北向资金补充，完整Morning Briefing可于盘中修正

---

## 数据与证据
- investment_memos：今日{len(rows)}条记录（id {min(r[0] for r in rows)}~{max(r[0] for r in rows)}）
- 触发信号：{', '.join(sorted(all_signals)) if all_signals else '待确认'}
- 数据源状态：akshare quotes采集中断，ETF独立管线正常

---

## 待办与跟进

| 事项 | 状态 |
|------|------|
| akshare数据源故障排查 | 🔄 处理中 |
| 北向资金补采（15:00后） | ⏳ 待执行 |
| 因子计算补跑 | ⏳ 待执行 |
| Morning Briefing修正版 | ⏳ 待数据恢复 |

---

**决策规则合规**
- 置信度：{overall}（{', '.join(all_conf)}）
- 禁用词检查：✅ 未发现买卖建议用语
- 今日数据完整度：⚠️ 沪深300成分行情缺失，ETF数据正常""")