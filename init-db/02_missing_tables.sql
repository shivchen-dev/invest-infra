-- =============================================================
-- 扩展3: ETF 主数据表 + 实时行情表
-- =============================================================

CREATE TABLE IF NOT EXISTS etfs (
    id              SERIAL PRIMARY KEY,
    code            VARCHAR(20)  NOT NULL UNIQUE,        -- ETF 代码：510300, 159919
    name            VARCHAR(100) NOT NULL,               -- ETF 全称
    short_name      VARCHAR(20),                         -- 简称
    category        VARCHAR(30),                         -- bond / commodity / cross_border / money_market / stock
    exchange_code   VARCHAR(10),                         -- SZSE / SSE
    is_active       BOOLEAN      DEFAULT TRUE,
    created_at      TIMESTAMPTZ  DEFAULT now(),
    updated_at      TIMESTAMPTZ  DEFAULT now()
);
COMMENT ON TABLE etfs IS 'ETF基金主数据';
CREATE INDEX idx_etfs_code ON etfs(code);
CREATE INDEX idx_etfs_category     ON etfs(category);
CREATE INDEX idx_etfs_exchange      ON etfs(exchange_code);

CREATE TABLE IF NOT EXISTS etf_quotes (
    id              SERIAL PRIMARY KEY,
    etf_id          INT          NOT NULL REFERENCES etfs(id),
    trade_date      DATE         NOT NULL,

    -- 实时行情字段（IOPV/溢价率仅实时快照有值，K线记录为 NULL）
    open_price NUMERIC(12,2),
    high_price      NUMERIC(12,2),
    low_price       NUMERIC(12,2),
    close_price     NUMERIC(12,2),
    pre_close       NUMERIC(12,2),
    iopv            NUMERIC(12,4),                       -- IOPV 实时估值（仅实时快照有效）
    premium_rate    NUMERIC(10,4),                       -- 溢价率%（仅实时快照有效）
    discount_rate   NUMERIC(10,4),                       -- 折价率%（仅实时快照有效）
    volume          BIGINT,                              -- 成交量
    amount          NUMERIC(20,2),                       -- 成交额
    turnover_rate   NUMERIC(10,4),                       -- 换手率
    amplitude       NUMERIC(10,4),                       -- 振幅
    change_pct      NUMERIC(10,4),                       -- 涨跌幅
    change_amount   NUMERIC(10,4),                       -- 涨跌额

    source          VARCHAR(50),                         -- akshare-spot / akshare-hist / rsscast
    created_at      TIMESTAMPTZ  DEFAULT now(),

    UNIQUE (etf_id, trade_date)
);
COMMENT ON TABLE etf_quotes IS 'ETF 行情数据（实时快照 + 历史K线）';
CREATE INDEX idx_etq_etf   ON etf_quotes(etf_id);
CREATE INDEX idx_etq_date  ON etf_quotes(trade_date);

-- =============================================================
-- 扩展4: Alpha 信号输出表
-- =============================================================

-- 多因子评分权重配置
CREATE TABLE IF NOT EXISTS factor_weights (
    id              SERIAL PRIMARY KEY,
    factor_key      VARCHAR(50)  NOT NULL UNIQUE,
    category        VARCHAR(30)  NOT NULL,               -- momentum / quality / money_flow / volume / technical
    weight NUMERIC(6,4)  NOT NULL,
    norm_direction  SMALLINT     NOT NULL,               --  1: 越大越好  -1: 越小越好
    description TEXT,
    created_at      TIMESTAMPTZ  DEFAULT now(),
    updated_at      TIMESTAMPTZ  DEFAULT now()
);
COMMENT ON TABLE factor_weights IS '多因子评分卡权重配置';

-- 股票 Alpha 信号（多因子合成）
CREATE TABLE IF NOT EXISTS alpha_signals (
    id              SERIAL PRIMARY KEY,
    company_id      INT          NOT NULL REFERENCES companies(id),
    calc_date       DATE         NOT NULL,

    -- 各分类得分（百分位 0-100）
    norm_momentum   NUMERIC(6,2),
    norm_value       NUMERIC(6,2),
    norm_quality     NUMERIC(6,2),
    norm_money_flow NUMERIC(6,2),
    norm_technical   NUMERIC(6,2),
    norm_volume      NUMERIC(6,2),

    -- 权重原始数据（JSON，方便调试/追溯）
    raw_weights     JSONB,

    -- 综合得分
    composite_score NUMERIC(10,4),                       -- (raw_score-50)*2，取值约 -100~100
    signal SMALLINT,                            --  1=买入信号0=持有  -1=卖出信号
    signal_reason   VARCHAR(200),                        -- 信号来源说明

    score_rank      INT,                                 -- 当日截面排名

    created_at      TIMESTAMPTZ  DEFAULT now(),
    UNIQUE (company_id, calc_date)
);
COMMENT ON TABLE alpha_signals IS '多因子 Alpha合成信号';
CREATE INDEX idx_alpha_company ON alpha_signals(company_id);
CREATE INDEX idx_alpha_date ON alpha_signals(calc_date);
CREATE INDEX idx_alpha_signal  ON alpha_signals(signal);
CREATE INDEX idx_alpha_rank    ON alpha_signals(score_rank);

-- ETF Alpha 信号
CREATE TABLE IF NOT EXISTS etf_alpha_signals (
    id              SERIAL PRIMARY KEY,
    etf_id          INT          NOT NULL REFERENCES etfs(id),
    calc_date       DATE         NOT NULL,

    -- 分类得分
    norm_value       NUMERIC(6,2),
    norm_liquidity   NUMERIC(6,2),
    norm_momentum NUMERIC(6,2),
    norm_volatility  NUMERIC(6,2),
    norm_money_flow  NUMERIC(6,2),

    -- 综合得分
    composite_score NUMERIC(10,4),
    signal          SMALLINT,                            --  1 / 0 / -1
    signal_reason   VARCHAR(200),

    score_rank      INT,

    created_at      TIMESTAMPTZ  DEFAULT now(),
    UNIQUE (etf_id, calc_date)
);
COMMENT ON TABLE etf_alpha_signals IS 'ETF 多因子 Alpha 信号';
CREATE INDEX idx_etf_alpha_etf    ON etf_alpha_signals(etf_id);
CREATE INDEX idx_etf_alpha_date   ON etf_alpha_signals(calc_date);
CREATE INDEX idx_etf_alpha_rank ON etf_alpha_signals(score_rank);
-- ==================== 研报数据表 ====================
CREATE TABLE research_reports (
    id              SERIAL PRIMARY KEY,
    company_id      INT          REFERENCES companies(id),
    stock_code      VARCHAR(10)  NOT NULL,
    stock_name      VARCHAR(50),
    report_name     TEXT         NOT NULL,
    rating          VARCHAR(20),                         -- 东财评级：买入/增持/中性/减持/卖出
    institution    VARCHAR(100),                        -- 出具机构
    report_date     DATE,                                -- 报告日期
    pdf_url         TEXT,                                -- PDF 公共链接

    -- LLM 解析结果（待补充）
    investment_highlight TEXT,                            -- 投资亮点
    target_price         NUMERIC(10,2),                  -- 目标价
    rating_change        VARCHAR(20),                     -- 评级变动：上调/维持/下调
    key_metrics          JSONB,                           -- 关键指标：{营收:, 利润:, 毛利率:}
    risk_factors         TEXT[],                          -- 风险因素列表
    industry_outlook     TEXT,                            -- 行业展望

    -- 原始文件存储
    raw_file_path   TEXT,                                  -- MinIO Bronze 路径
    text_content    TEXT,                                  -- PyMuPDF 提取文本
    checksum        VARCHAR(64),

    collected_at    TIMESTAMPTZ  DEFAULT now(),
    created_at      TIMESTAMPTZ  DEFAULT now()
);
COMMENT ON TABLE research_reports IS '券商研报数据（东方财富源）';
CREATE INDEX idx_rr_company   ON research_reports(company_id);
CREATE INDEX idx_rr_stock     ON research_reports(stock_code);
CREATE INDEX idx_rr_date      ON research_reports(report_date);
CREATE INDEX idx_rr_institution ON research_reports(institution);
CREATE INDEX idx_rr_rating    ON research_reports(rating);

-- =============================================================
-- 扩展5: ETF 期现套利信号表
-- =============================================================

CREATE TABLE IF NOT EXISTS etf_arbitrage_signals (
    id              SERIAL PRIMARY KEY,
    etf_id          INT          NOT NULL REFERENCES etfs(id),
    signal_date     DATE         NOT NULL,

    -- 溢价状态
    direction       VARCHAR(20)  NOT NULL,               -- premium / discount
    premium_rate    NUMERIC(10,4),                     -- 溢价率%（带符号）
    abs_premium     NUMERIC(10,4),                      -- 绝对溢价率（%）

    -- 流动性
    liquidity_score NUMERIC(8,4),                       -- 流动性评分 0-1

    -- 收益分解（均为 % 单位）
    theoretical_gain_pct  NUMERIC(10,4),                 -- 理论收益率（%）
    total_cost_pct       NUMERIC(10,4),                 -- 总成本率（%）
    net_gain_pct         NUMERIC(10,4),                 -- 净收益率（%）

    signal_action        VARCHAR(40),                   -- sell_etf_buy_iopv / buy_etf_sell_iopv

    -- 成本分解（均为 % 单位）
    slippage_cost   NUMERIC(8,4),                       -- 滑点成本
    impact_cost     NUMERIC(8,4),                       -- 冲击成本
    commission_cost NUMERIC(8,4),                       -- 手续费
    stamp_tax_cost  NUMERIC(8,4),                       -- 印花税（仅溢价卖出时>0）

    -- 置信度
    confidence      VARCHAR(10),                          -- high / medium / low

    -- T+1 执行标记
    executed        BOOLEAN     DEFAULT FALSE,           -- 是否已执行（T+1次日执行）
    executed_date   DATE,                                 -- 执行日期

    created_at      TIMESTAMPTZ  DEFAULT now(),

    UNIQUE (etf_id, signal_date)
);
COMMENT ON TABLE etf_arbitrage_signals IS 'ETF 期现套利信号（基于 IOPV 溢价率 + 流动性）';
CREATE INDEX idx_arb_etf    ON etf_arbitrage_signals(etf_id);
CREATE INDEX idx_arb_date   ON etf_arbitrage_signals(signal_date);
CREATE INDEX idx_arb_direct ON etf_arbitrage_signals(direction);
CREATE INDEX idx_arb_conf   ON etf_arbitrage_signals(confidence);
CREATE INDEX idx_arb_exec   ON etf_arbitrage_signals(executed);
