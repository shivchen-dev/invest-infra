-- =============================================================
-- 智能投研体系 — 数据库初始化脚本
-- 三层数据架构：Bronze(原始) → MinIO | Silver(清洗) + Gold(分析) → PostgreSQL
-- =============================================================

-- ==================== 扩展 ====================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ==================== 1. 公司主数据 ====================
CREATE TABLE companies (
    id              SERIAL PRIMARY KEY,
    code            VARCHAR(20)  NOT NULL UNIQUE,        -- 股票代码：000001.SZ, 600519.SH
    name            VARCHAR(100) NOT NULL,               -- 公司全称
    short_name      VARCHAR(20),                         -- 简称
    industry        VARCHAR(100),                        -- 所属行业
    listed_date     DATE,                                -- 上市日期
    market          VARCHAR(10),                         -- 交易所：SZ/SH/BJ
    is_active       BOOLEAN      DEFAULT TRUE,
    created_at      TIMESTAMPTZ  DEFAULT now(),
    updated_at      TIMESTAMPTZ  DEFAULT now()
);
COMMENT ON TABLE companies IS '上市公司基本信息';
CREATE INDEX idx_companies_industry ON companies(industry);
CREATE INDEX idx_companies_market   ON companies(market);

-- ==================== 2. 财务报告（Silver 层） ====================
CREATE TABLE financial_reports (
    id              SERIAL PRIMARY KEY,
    company_id      INT          NOT NULL REFERENCES companies(id),
    report_date     DATE         NOT NULL,               -- 报告期（如 2025-12-31）
    report_type     VARCHAR(10)  NOT NULL,               -- Q1 / Q2 / Q3 / Q4 / annual
    fiscal_year     INT          NOT NULL,               -- 会计年份

    -- 利润表核心科目
    revenue         NUMERIC(20,2),                       -- 营业收入
    cost_of_sales   NUMERIC(20,2),                       -- 营业成本
    gross_profit    NUMERIC(20,2),                       -- 毛利润
    operating_profit NUMERIC(20,2),                      -- 营业利润
    net_profit      NUMERIC(20,2),                       -- 净利润
    parent_net_profit NUMERIC(20,2),                     -- 归母净利润

    -- 资产负债表核心科目
    total_assets    NUMERIC(20,2),                       -- 总资产
    total_liabilities NUMERIC(20,2),                     -- 总负债
    total_equity    NUMERIC(20,2),                       -- 总所有者权益
    cash_and_equiv  NUMERIC(20,2),                       -- 货币资金
    accounts_receivable NUMERIC(20,2),                   -- 应收账款
    inventory       NUMERIC(20,2),                       -- 存货

    -- 现金流量表核心科目
    operating_cf    NUMERIC(20,2),                       -- 经营活动现金流净额
    investing_cf    NUMERIC(20,2),                       -- 投资活动现金流净额
    financing_cf    NUMERIC(20,2),                       -- 筹资活动现金流净额
    free_cf         NUMERIC(20,2),                       -- 自由现金流

    -- 元数据
    currency        VARCHAR(10)  DEFAULT 'CNY',
    source          VARCHAR(50),                         -- 数据来源
    quality_score   NUMERIC(3,2),                        -- 数据质量评分 (0-1)
    checksum        VARCHAR(64),                         -- 数据校验
    created_at      TIMESTAMPTZ  DEFAULT now(),
    updated_at      TIMESTAMPTZ  DEFAULT now(),

    UNIQUE (company_id, report_date, report_type)
);
COMMENT ON TABLE financial_reports IS '财报结构化数据（Silver 层）';
CREATE INDEX idx_fr_company    ON financial_reports(company_id);
CREATE INDEX idx_fr_date       ON financial_reports(report_date);
CREATE INDEX idx_fr_fiscal_yr  ON financial_reports(fiscal_year);
CREATE INDEX idx_fr_type       ON financial_reports(report_type);

-- ==================== 3. 日行情数据（Silver 层） ====================
CREATE TABLE daily_quotes (
    id              SERIAL PRIMARY KEY,
    company_id      INT          NOT NULL REFERENCES companies(id),
    trade_date      DATE         NOT NULL,
    open_price      NUMERIC(12,2),
    high_price      NUMERIC(12,2),
    low_price       NUMERIC(12,2),
    close_price     NUMERIC(12,2),
    pre_close       NUMERIC(12,2),
    volume          BIGINT,                              -- 成交量（股）
    amount          NUMERIC(20,2),                       -- 成交额（元）
    turnover_rate   NUMERIC(10,4),                       -- 换手率（%）
    amplitude       NUMERIC(10,4),                       -- 振幅（%）
    change_pct      NUMERIC(10,4),                       -- 涨跌幅（%）
    adj_factor      NUMERIC(12,6) DEFAULT 1.0,           -- 复权因子

    source          VARCHAR(50),
    created_at      TIMESTAMPTZ  DEFAULT now(),

    UNIQUE (company_id, trade_date)
);
COMMENT ON TABLE daily_quotes IS '日行情数据（Silver 层）';
CREATE INDEX idx_dq_company ON daily_quotes(company_id);
CREATE INDEX idx_dq_date    ON daily_quotes(trade_date);

-- ==================== 4. 新闻与舆情数据 ====================
CREATE TABLE news_articles (
    id              SERIAL PRIMARY KEY,
    company_id      INT          REFERENCES companies(id),
    title           TEXT         NOT NULL,
    content_summary TEXT,
    source_name     VARCHAR(100),                        -- 来源：东方财富/雪球/新浪
    source_url      TEXT,
    published_at    TIMESTAMPTZ  NOT NULL,
    collected_at    TIMESTAMPTZ  DEFAULT now(),

    -- NLP 分析结果
    sentiment_label VARCHAR(10),                         -- positive/negative/neutral
    sentiment_score NUMERIC(5,4),                        -- -1 ~ 1
    keywords        TEXT[],                              -- 关键词数组
    relevance_score NUMERIC(5,4),                        -- 与公司相关度

    raw_file_path   TEXT,                                -- MinIO 原始文件路径
    checksum        VARCHAR(64),
    created_at      TIMESTAMPTZ  DEFAULT now()
);
COMMENT ON TABLE news_articles IS '新闻舆情数据（含 NLP 分析结果）';
CREATE INDEX idx_na_company ON news_articles(company_id);
CREATE INDEX idx_na_date    ON news_articles(published_at);
CREATE INDEX idx_na_sentiment ON news_articles(sentiment_label);

-- ==================== 5. 因子定义 ====================
CREATE TABLE factor_definitions (
    id              SERIAL PRIMARY KEY,
    factor_key      VARCHAR(50)  NOT NULL UNIQUE,        -- 因子唯一标识：roe_ttm, pb, momentum_60d
    name            VARCHAR(200) NOT NULL,               -- 因子中文名
    category        VARCHAR(30)  NOT NULL,               -- fundamental/technical/alternative/macro
    sub_category    VARCHAR(50),                         -- profitability/valuation/momentum/...
    formula_desc    TEXT,                                -- 计算逻辑描述
    data_source     VARCHAR(100),                        -- 依赖数据源
    frequency       VARCHAR(10)  DEFAULT 'daily',        -- daily/weekly/monthly/quarterly
    is_active       BOOLEAN      DEFAULT TRUE,
    version         INT          DEFAULT 1,
    created_at      TIMESTAMPTZ  DEFAULT now(),
    updated_at      TIMESTAMPTZ  DEFAULT now()
);
COMMENT ON TABLE factor_definitions IS '因子定义元数据';

-- ==================== 6. 因子值（Gold 层） ====================
CREATE TABLE factor_values (
    id              SERIAL PRIMARY KEY,
    company_id      INT          NOT NULL REFERENCES companies(id),
    factor_id       INT          NOT NULL REFERENCES factor_definitions(id),
    calc_date       DATE         NOT NULL,               -- 计算日期
    value           NUMERIC(20,6),                       -- 因子值
    rank            INT,                                 -- 截面排名
    percentile      NUMERIC(6,4),                        -- 截面百分位 (0-1)
    zscore          NUMERIC(10,4),                       -- 标准化值

    -- 元数据
    calc_batch_id   VARCHAR(50),                         -- 计算批次
    quality_flag    VARCHAR(10),                         -- good / warning / stale
    created_at      TIMESTAMPTZ  DEFAULT now(),

    UNIQUE (company_id, factor_id, calc_date)
);
COMMENT ON TABLE factor_values IS '因子计算值（Gold 层）';
CREATE INDEX idx_fv_company  ON factor_values(company_id);
CREATE INDEX idx_fv_factor   ON factor_values(factor_id);
CREATE INDEX idx_fv_date     ON factor_values(calc_date);
CREATE INDEX idx_fv_batch    ON factor_values(calc_batch_id);

-- ==================== 7. 分析信号 ====================
CREATE TABLE analysis_signals (
    id              SERIAL PRIMARY KEY,
    company_id      INT          NOT NULL REFERENCES companies(id),
    signal_date     DATE         NOT NULL,
    signal_type     VARCHAR(30)  NOT NULL,               -- buy / sell / hold / watch
    confidence      NUMERIC(5,4),                        -- 置信度 0-1
    price_target    NUMERIC(12,2),                       -- 目标价（可选）

    -- 信号来源
    source_module   VARCHAR(50)  NOT NULL,               -- factor_signal / news_analysis / combined
    reasoning       TEXT,                                -- 推理逻辑说明
    details_json    JSONB,                               -- 详细信号数据

    created_at      TIMESTAMPTZ  DEFAULT now(),
    UNIQUE (company_id, signal_date, source_module)
);
COMMENT ON TABLE analysis_signals IS '投资分析信号';
CREATE INDEX idx_as_company ON analysis_signals(company_id);
CREATE INDEX idx_as_date    ON analysis_signals(signal_date);
CREATE INDEX idx_as_type    ON analysis_signals(signal_type);

-- ==================== 8. 投资备忘录 ====================
CREATE TABLE investment_memos (
    id              SERIAL PRIMARY KEY,
    company_id      INT          NOT NULL REFERENCES companies(id),
    title           VARCHAR(300) NOT NULL,
    memo_date       DATE         NOT NULL,
    memo_type       VARCHAR(20)  DEFAULT 'periodic',     -- periodic / event_driven / deep_dive

    -- 内容
    summary         TEXT,                                -- 摘要
    body_md         TEXT,                                -- Markdown 正文
    sections_json   JSONB,                               -- 结构化章节
    tags            TEXT[],                              -- 标签

    -- AI 生成元数据
    generated_by    VARCHAR(50),                         -- 生成 agent
    model_used      VARCHAR(100),                        -- 使用的模型
    total_tokens    INT,                                 -- tokens 消耗
    quality_score   NUMERIC(3,2),                        -- 质量评分
    review_status   VARCHAR(20)  DEFAULT 'draft',        -- draft / reviewed / published

    -- 引用
    signal_ids      INT[],                               -- 引用的信号 ID 列表
    data_range_from DATE,
    data_range_to   DATE,

    created_at      TIMESTAMPTZ  DEFAULT now(),
    updated_at      TIMESTAMPTZ  DEFAULT now()
);
COMMENT ON TABLE investment_memos IS 'AI 生成的投资备忘录（Gold 层）';
CREATE INDEX idx_im_company ON investment_memos(company_id);
CREATE INDEX idx_im_date    ON investment_memos(memo_date);
CREATE INDEX idx_im_type    ON investment_memos(memo_type);
CREATE INDEX idx_im_status  ON investment_memos(review_status);

-- ==================== 9. 回测运行记录 ====================
CREATE TABLE backtest_runs (
    id              SERIAL PRIMARY KEY,
    run_name        VARCHAR(200) NOT NULL,
    description     TEXT,
    strategy_config JSONB        NOT NULL,               -- 策略参数配置

    -- 时间范围
    start_date      DATE         NOT NULL,
    end_date        DATE         NOT NULL,

    -- 标的
    universe_type   VARCHAR(30),                         -- all / custom / index
    universe_list   INT[],                               -- 标的 company_id 列表

    -- 状态
    status          VARCHAR(20)  DEFAULT 'pending',      -- pending / running / completed / failed
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,

    -- 元数据
    triggered_by    VARCHAR(50),                         -- 触发方式：manual / scheduled
    error_message   TEXT,
    created_at      TIMESTAMPTZ  DEFAULT now()
);
COMMENT ON TABLE backtest_runs IS '回测运行记录';

-- ==================== 10. 回测结果明细 ====================
CREATE TABLE backtest_results (
    id              SERIAL PRIMARY KEY,
    run_id          INT          NOT NULL REFERENCES backtest_runs(id),
    company_id      INT          NOT NULL REFERENCES companies(id),

    -- 交易记录
    entry_date      DATE         NOT NULL,
    exit_date       DATE,
    direction       VARCHAR(10)  DEFAULT 'long',         -- long / short
    entry_price     NUMERIC(12,2),
    exit_price      NUMERIC(12,2),
    position_size   NUMERIC(14,4),
    pnl             NUMERIC(14,4),                       -- 盈亏
    pnl_pct         NUMERIC(10,4),                       -- 收益率%

    -- 信号
    signal_id       INT          REFERENCES analysis_signals(id),

    -- 绩效指标（聚合层，run_id 级别存一份汇总）
    created_at      TIMESTAMPTZ  DEFAULT now()
);
COMMENT ON TABLE backtest_results IS '回测结果明细';
CREATE INDEX idx_br_run     ON backtest_results(run_id);
CREATE INDEX idx_br_company ON backtest_results(company_id);

-- ==================== 11. 回测绩效汇总 ====================
CREATE TABLE backtest_summary (
    id              SERIAL PRIMARY KEY,
    run_id          INT          NOT NULL REFERENCES backtest_runs(id),
    total_return    NUMERIC(10,4),                       -- 总收益率
    annual_return   NUMERIC(10,4),                       -- 年化收益率
    max_drawdown    NUMERIC(10,4),                       -- 最大回撤
    sharpe_ratio    NUMERIC(10,4),                       -- 夏普比率
    calmar_ratio    NUMERIC(10,4),                       -- 卡玛比率
    win_rate        NUMERIC(10,4),                       -- 胜率
    profit_factor   NUMERIC(10,4),                       -- 盈亏比
    total_trades    INT,                                 -- 总交易次数
    avg_hold_days   NUMERIC(10,2),                       -- 平均持仓天数

    created_at      TIMESTAMPTZ  DEFAULT now(),
    UNIQUE (run_id)
);
COMMENT ON TABLE backtest_summary IS '回测绩效汇总指标';

-- ==================== 12. 数据采集日志 ====================
CREATE TABLE data_source_log (
    id              SERIAL PRIMARY KEY,
    source_name     VARCHAR(100) NOT NULL,               -- 数据来源
    data_type       VARCHAR(30)  NOT NULL,               -- quote/financial/news/factor
    batch_id        VARCHAR(50),                         -- 采集批次

    status          VARCHAR(20)  NOT NULL,               -- success / partial / failed
    records_fetched INT          DEFAULT 0,
    records_written INT          DEFAULT 0,
    error_detail    TEXT,
    duration_ms     INT,

    -- MinIO 路径
    raw_storage_path TEXT,                               -- Bronze 层文件路径

    started_at      TIMESTAMPTZ  NOT NULL,
    finished_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  DEFAULT now()
);
COMMENT ON TABLE data_source_log IS '数据采集审计日志';
CREATE INDEX idx_dsl_source ON data_source_log(source_name);
CREATE INDEX idx_dsl_type   ON data_source_log(data_type);
CREATE INDEX idx_dsl_batch  ON data_source_log(batch_id);
CREATE INDEX idx_dsl_status ON data_source_log(status);

-- ==================== 13. 定时任务调度记录 ====================
CREATE TABLE scheduler_jobs (
    id              SERIAL PRIMARY KEY,
    job_name        VARCHAR(100) NOT NULL UNIQUE,
    job_type        VARCHAR(30)  NOT NULL,               -- data_collect / factor_calc / backtest / memo_gen
    cron_expr       VARCHAR(100),                        -- Quartz cron 表达式
    enabled         BOOLEAN      DEFAULT TRUE,

    -- 执行记录
    last_run_at     TIMESTAMPTZ,
    last_status     VARCHAR(20),                         -- success / failed
    next_run_at     TIMESTAMPTZ,
    total_runs      INT          DEFAULT 0,
    failed_runs     INT          DEFAULT 0,

    config_json     JSONB,
    created_at      TIMESTAMPTZ  DEFAULT now(),
    updated_at      TIMESTAMPTZ  DEFAULT now()
);
COMMENT ON TABLE scheduler_jobs IS '定时任务调度配置';

-- ==================== 14. 用户持仓与偏好 ====================
CREATE TABLE user_portfolios (
    id              SERIAL PRIMARY KEY,
    user_name       VARCHAR(100) NOT NULL,
    company_id      INT          NOT NULL REFERENCES companies(id),
    position_type   VARCHAR(20)  DEFAULT 'watch',        -- watch / holding / trading
    added_at        TIMESTAMPTZ  DEFAULT now(),
    notes           TEXT,
    UNIQUE (user_name, company_id)
);
COMMENT ON TABLE user_portfolios IS '用户自选股与持仓';
CREATE INDEX idx_up_user ON user_portfolios(user_name);

-- ==================== 15. MinIO Bucket 元数据 ====================
-- MinIO buckets 通过 API 创建，此处记录 bucket 结构和用途
COMMENT ON SCHEMA public IS '
智能投研体系 - 数据库 Schema
==============================
三层数据架构：
  Bronze (原始层)  → MinIO: raw-{source}-{date}.{format}
  Silver (清洗层)  → PostgreSQL: daily_quotes, financial_reports, news_articles
  Gold (分析层)    → PostgreSQL: factor_values, analysis_signals, investment_memos

MinIO Buckets:
  ├── bronze-financial/    — 原始财报 PDF/HTML
  ├── bronze-quotes/       — 原始行情 CSV
  ├── bronze-news/         — 原始新闻 HTML/JSON
  ├── bronze-social/       — 社交媒体原始数据
  ├── silver-processed/    — 清洗后数据归档
  ├── gold-memos/          — 投资备忘录导出 PDF
  └── gold-backtest/       — 回测结果导出
';

-- ==================== 更新时间触发器 ====================
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_companies_updated
    BEFORE UPDATE ON companies FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER trg_financial_reports_updated
    BEFORE UPDATE ON financial_reports FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER trg_factor_definitions_updated
    BEFORE UPDATE ON factor_definitions FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER trg_investment_memos_updated
    BEFORE UPDATE ON investment_memos FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER trg_scheduler_jobs_updated
    BEFORE UPDATE ON scheduler_jobs FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();
