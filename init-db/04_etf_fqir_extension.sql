-- ================================================================
-- FQIR-ETF 评分体系扩展
-- Version: 1.0
-- Date: 2026-06-02
-- Description: 扩展 etfs / etf_alpha_signals 表，新增基本面、
--              信息流、风险因子原始值表
-- ================================================================

-- ---------------------------------------------------------------
-- 1. etfs 表扩展 — 基本面维度支持
-- ---------------------------------------------------------------
ALTER TABLE etfs ADD COLUMN IF NOT EXISTS cr5 NUMERIC;
ALTER TABLE etfs ADD COLUMN IF NOT EXISTS cr10 NUMERIC;
ALTER TABLE etfs ADD COLUMN IF NOT EXISTS index_rebalance_freq INTEGER DEFAULT 2;  -- 默认每年2次（半年/年）
ALTER TABLE etfs ADD COLUMN IF NOT EXISTS index_category VARCHAR(50);

-- ---------------------------------------------------------------
-- 2. etf_alpha_signals 扩展 — 五维度分项分存储
-- ---------------------------------------------------------------
ALTER TABLE etf_alpha_signals ADD COLUMN IF NOT EXISTS fundamental_score NUMERIC;
ALTER TABLE etf_alpha_signals ADD COLUMN IF NOT EXISTS risk_score NUMERIC;
ALTER TABLE etf_alpha_signals ADD COLUMN IF NOT EXISTS info_score NUMERIC;
ALTER TABLE etf_alpha_signals ADD COLUMN IF NOT EXISTS quant_score NUMERIC;
ALTER TABLE etf_alpha_signals ADD COLUMN IF NOT EXISTS liquidity_score NUMERIC;

-- ---------------------------------------------------------------
-- 3. etf_fundamental_scores — 基本面因子原始值
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS etf_fundamental_scores (
    id SERIAL PRIMARY KEY,
    etf_id INTEGER NOT NULL REFERENCES etfs(id) ON DELETE CASCADE,
    calc_date DATE NOT NULL,
    industry_sentiment NUMERIC,        -- 行业景气度 (0-100)
    component_roe NUMERIC,             -- 成分股加权ROE
    component_gross_margin NUMERIC,    -- 成分股加权毛利率
    component_net_margin NUMERIC,      -- 成分股净利润率
    cr5 NUMERIC,                       -- CR5 集中度 (0-1)
    cr10 NUMERIC,                      -- CR10 集中度 (0-1)
    rebalance_freq INTEGER,           -- 年换仓次数
    index_quality_score NUMERIC,      -- 指数编制质量评分 (0-100)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(etf_id, calc_date)
);

CREATE INDEX IF NOT EXISTS idx_etf_fundamental_scores_etf_id ON etf_fundamental_scores(etf_id);
CREATE INDEX IF NOT EXISTS idx_etf_fundamental_scores_calc_date ON etf_fundamental_scores(calc_date);

-- ---------------------------------------------------------------
-- 4. etf_info_scores — 信息流因子原始值
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS etf_info_scores (
    id SERIAL PRIMARY KEY,
    etf_id INTEGER NOT NULL REFERENCES etfs(id) ON DELETE CASCADE,
    calc_date DATE NOT NULL,
    news_sentiment NUMERIC,           -- 新闻情绪 (-100 ~ 100，正=利好)
    news_count INTEGER,               -- 近N日新闻数量
    policy_support NUMERIC,           -- 政策支持度 (0-100)
    social_sentiment NUMERIC,         -- 舆情情绪 (-100 ~ 100)
    report_coverage INTEGER,          -- 研报覆盖数量
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(etf_id, calc_date)
);

CREATE INDEX IF NOT EXISTS idx_etf_info_scores_etf_id ON etf_info_scores(etf_id);
CREATE INDEX IF NOT EXISTS idx_etf_info_scores_calc_date ON etf_info_scores(calc_date);

-- ---------------------------------------------------------------
-- 5. etf_risk_scores — 风险因子原始值
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS etf_risk_scores (
    id SERIAL PRIMARY KEY,
    etf_id INTEGER NOT NULL REFERENCES etfs(id) ON DELETE CASCADE,
    calc_date DATE NOT NULL,
    policy_risk NUMERIC,              -- 政策风险 (0-100，越高风险越大)
    financial_deterioration NUMERIC,  -- 成分股财务恶化比例 (0-1)
    volatility_spike NUMERIC,          -- 波动率异常 (0-1，0=正常，1=异常)
    liquidity_risk NUMERIC,            -- 流动性风险 (0-1)
    max_drawdown NUMERIC,              -- 最大回撤 (0-1)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(etf_id, calc_date)
);

CREATE INDEX IF NOT EXISTS idx_etf_risk_scores_etf_id ON etf_risk_scores(etf_id);
CREATE INDEX IF NOT EXISTS idx_etf_risk_scores_calc_date ON etf_risk_scores(calc_date);

-- ---------------------------------------------------------------
-- 6. etf_quant_scores — 量化因子原始值（扩展 Q 维度）
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS etf_quant_scores (
    id SERIAL PRIMARY KEY,
    etf_id INTEGER NOT NULL REFERENCES etfs(id) ON DELETE CASCADE,
    calc_date DATE NOT NULL,
    momentum_5d NUMERIC,              -- 5日动量
    momentum_20d NUMERIC,             -- 20日动量
    momentum_60d NUMERIC,             -- 60日动量
    pe_percentile NUMERIC,            -- PE历史分位 (0-100)
    pb_percentile NUMERIC,            -- PB历史分位 (0-100)
    hv_20d NUMERIC,                   -- 20日历史波动率
    max_drawdown NUMERIC,             -- 最大回撤
    backtest_stability NUMERIC,       -- 回测稳定性 (0-100)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(etf_id, calc_date)
);

CREATE INDEX IF NOT EXISTS idx_etf_quant_scores_etf_id ON etf_quant_scores(etf_id);
CREATE INDEX IF NOT EXISTS idx_etf_quant_scores_calc_date ON etf_quant_scores(calc_date);