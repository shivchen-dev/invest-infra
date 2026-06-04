---
name: research-report-collector
description: 研报数据采集模块 — 按 invest-infra 数据管道规范实现从 akshare 东方财富研报接口获取研报列表、下载 PDF、提取文本与表格、存入 PostgreSQL 的完整流程。
---

# Research Report Collector — 研报采集模块

当用户需要**采集券商研报数据**、或询问「研报怎么采集/解析/存储」时，按本 Skill 的规范执行。

## 1. 模块定位

```
collector/research_report.py
├── fetch_research_report(symbol)   # 获取研报列表（akshare API）
├── download_pdf(pdf_url, dest)     # 下载 PDF 到本地/MinIO
├── extract_text(pdf_path)          # PyMuPDF 文本提取
├── extract_tables(pdf_path)       # pdfplumber 表格提取
└── parse_report(pdf_path)        # LLM 结构化关键信息提取
```

## 2. 数据模型

### 2.1 研报基础信息（from akshare）

| 字段 | 类型 | 说明 |
|------|------|------|
| `stock_code` | string | 股票代码，如 `000001.SZ` |
| `report_name` | string | 研报标题 |
| `stock_name` | string | 股票简称 |
| `rating` | string | 东财评级：买入/增持/中性/减持 |
| `institution` | string | 出具机构 |
| `profit_forecast_2026` | float | 2026 盈利预测值 |
| `pe_forecast_2026` | float | 2026 市盈率预测 |
| `report_date` | date | 报告日期 |
| `pdf_url` | string | PDF 公共链接 |

### 2.2 解析后结构化数据（LLM 提取）

| 字段 | 类型 | 说明 |
|------|------|------|
| `investment_highlight` | string | 投资亮点（核心逻辑） |
| `target_price` | float | 目标价 |
| `rating_change` | string | 评级变动（上调/维持/下调） |
| `key_metrics` | dict | 关键指标：营收/利润/毛利率等 |
| `risk_factors` | list[str] | 风险因素 |
| `industry_outlook` | string | 行业展望 |

## 3. 开发步骤

### Step 1：定义能力（Skill 元数据）

按 [Bsin-PaaS Skill 设计规范](https://gitee.com/s11e-DAO/bsin-paas-skills/blob/master/docs/01-skill-design-spec.md) 的原则：

- **name**：`fetch_research_report`、`download_research_pdf`、`extract_report_text`、`extract_report_tables`、`parse_report_llm`
- **description**：任务级能力描述，语义可发现
- **input_schema / output_schema**：明确的输入输出结构

```json
{
  "name": "fetch_research_report",
  "description": "获取指定股票的券商研报列表（东方财富源），返回研报基础信息与 PDF 链接",
  "input_schema": {
    "symbol": { "type": "string", "description": "股票代码，如 000001" }
  },
  "output_schema": {
    "reports": {
      "type": "array",
      "items": {
        "stock_code": "string",
        "report_name": "string",
        "rating": "string",
        "institution": "string",
        "pdf_url": "string",
        "report_date": "date"
      }
    }
  },
  "permission_scope": []
}
```

### Step 2：实现接口

文件位置：`src/collector/research_report.py`

```python
"""研报数据采集器 — 通过 akshare 东方财富接口获取券商研报"""

def fetch_research_report(symbol: str) -> list[dict]:
    """获取个股研报列表（东方财富源）"""
    # 单一职责：一个函数只做一件事
    # 输入：stock_code string
    # 输出：list[dict]，每条 dict 对应 output_schema
    ...
```

### Step 3：目录结构

```
data-pipeline/src/collector/
├── __init__.py
├── companies.py      # 股票列表
├── quotes.py        # 行情
├── financial.py     # 财报
├── news.py          # 新闻舆情
├── research_report.py  # ← 本模块
└── etf.py           # ETF

init-db/
├── 00_schema.sql    # 表结构（含 research_reports 表）
└── 02_missing_tables.sql
```

### Step 4：数据库 Schema

```sql
CREATE TABLE research_reports (
    id              SERIAL PRIMARY KEY,
    company_id      INT          REFERENCES companies(id),
    report_name     TEXT         NOT NULL,
    stock_code      VARCHAR(10)  NOT NULL,
    stock_name      VARCHAR(50),
    rating          VARCHAR(20),                         -- 东财评级
    institution     VARCHAR(100),
    report_date     DATE,
    pdf_url         TEXT,

    -- LLM 解析结果
    investment_highlight TEXT,
    target_price        NUMERIC(10,2),
    rating_change       VARCHAR(20),
    key_metrics        JSONB,                            -- {营收:, 利润:, 毛利率:}
    risk_factors        TEXT[],
    industry_outlook    TEXT,

    -- 原始文件
    raw_file_path   TEXT,
    text_content    TEXT,                                -- 提取的文本内容
    checksum       VARCHAR(64),

    collected_at   TIMESTAMPTZ  DEFAULT now(),
    created_at     TIMESTAMPTZ  DEFAULT now()
);
```

## 4. 设计原则

### 4.1 任务级能力

| 推荐（任务级） | 不推荐（技术动作） |
|----------------|-------------------|
| `fetch_research_report` | `call_akshare_api` |
| `download_pdf` | `save_file_to_disk` |
| `extract_report_tables` | `call_pdfplumber` |

### 4.2 原子与可组合

- `fetch_research_report`：获取研报列表（akshare → dict）
- `download_pdf`：下载 PDF（URL → local path）
- `extract_text`：文本提取（PDF path → text）
- `extract_tables`：表格提取（PDF path → list[dict]）
- `parse_report`：LLM 解析（text → 结构化 dict）

**编排**：`fetch` → `download` → `extract_text/tables` → `parse_report`

### 4.3 错误处理

```python
try:
    df = ak.stock_research_report_em(symbol=raw_code)
except Exception as e:
    logger.warning(f"{raw_code} 研报获取失败: {e}")
    return []
```

## 5. 参考文档

| 文档 | 路径 | 用途 |
|------|------|------|
| Bsin-PaaS Skill 设计规范 | `docs/01-skill-design-spec.md` | 元数据模型、设计原则 |
| Skill 调用协议 | `docs/03-skill-invocation-protocol.md` | 请求/响应、鉴权约定 |
| invest-infra 表结构 | `init-db/00_schema.sql` | 数据库 schema 参考 |

路径相对于 `https://gitee.com/s11e-DAO/bsin-paas-skills`