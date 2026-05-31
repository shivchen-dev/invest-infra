-- =============================================================
-- 扩展1: 指数主数据表 + 指数行情表
-- =============================================================

CREATE TABLE IF NOT EXISTS indices (
    id              SERIAL PRIMARY KEY,
    code            VARCHAR(20)  NOT NULL UNIQUE,        -- 指数代码：000001, 399001, 000300
    name            VARCHAR(100) NOT NULL,               -- 指数名称：上证指数、沪深300
    short_name      VARCHAR(20),                         -- 简称
    base_date       DATE,                                -- 基期
    base_point      NUMERIC(12,2),                       -- 基点
    category        VARCHAR(30),                         -- 类别：wide_market / sector / strategy / bond
    exchange_code   VARCHAR(10),                         -- 交易所：SSE/SZSE
    is_active       BOOLEAN      DEFAULT TRUE,
    created_at      TIMESTAMPTZ  DEFAULT now(),
    updated_at      TIMESTAMPTZ  DEFAULT now()
);
COMMENT ON TABLE indices IS '股票指数/ETF/国债主数据';

CREATE INDEX idx_indices_code       ON indices(code);
CREATE INDEX idx_indices_category   ON indices(category);
CREATE INDEX idx_indices_exchange   ON indices(exchange_code);

-- 指数行情数据（独立于 daily_quotes）
CREATE TABLE IF NOT EXISTS index_quotes (
    id              SERIAL PRIMARY KEY,
    index_id        INT          NOT NULL REFERENCES indices(id),
    trade_date      DATE         NOT NULL,
    open_point      NUMERIC(12,2),
    high_point      NUMERIC(12,2),
    low_point       NUMERIC(12,2),
    close_point     NUMERIC(12,2),
    pre_close       NUMERIC(12,2),
    volume          BIGINT,                              -- 成交量（手/股）
    amount          NUMERIC(20,2),                       -- 成交额（元）
    change_pct      NUMERIC(10,4),                       -- 涨跌幅（%）
    amplitude       NUMERIC(10,4),                       -- 振幅（%）

    source          VARCHAR(50),                         -- rsscast / akshare / tushare
    created_at      TIMESTAMPTZ  DEFAULT now(),

    UNIQUE (index_id, trade_date)
);
COMMENT ON TABLE index_quotes IS '指数/ETF/国债行情数据';
CREATE INDEX idx_iq_index   ON index_quotes(index_id);
CREATE INDEX idx_iq_date    ON index_quotes(trade_date);

-- 插入常用宽基指数（仅首次初始化）
INSERT INTO indices (code, name, short_name, category, exchange_code)
VALUES
    ('000001', '上证指数', '上证',  'wide_market', 'SSE'),
    ('399001', '深证成指', '深成',  'wide_market', 'SZSE'),
    ('000300', '沪深300',  '沪深300','wide_market', 'SSE'),
    ('000016', '上证50',   '上证50', 'wide_market', 'SSE'),
    ('000688', '科创50',   '科创50', 'wide_market', 'SSE'),
    ('399006', '创业板指', '创业板', 'wide_market', 'SZSE'),
    ('000905', '中证500',  '中证500', 'wide_market', 'SSE'),
    ('000852', '中证1000', '中证1000', 'wide_market', 'SSE')
ON CONFLICT (code) DO NOTHING;

-- =============================================================
-- 扩展2: 优化 companies 同步 — 用批量 upsert 替代逐行 INSERT
-- =============================================================

-- companies 表本身已有 ON CONFLICT，但 INSERT 慢因为逐行。
-- 改用 batch upsert 通过 CTE 批量处理，减少 DB 往返。
CREATE OR REPLACE FUNCTION sync_companies_batch(records JSONB)
RETURNS TABLE(inserted INT, updated INT) AS $$
DECLARE
    inserted_count INT := 0;
    updated_count  INT := 0;
BEGIN
    -- 使用 PostgreSQL 批量 upsert 语法
    WITH data AS (
        SELECT (jsonb_array_elements(records)->>'code')::text                 AS code,
               (jsonb_array_elements(records)->>'name')::text                 AS name,
               (jsonb_array_elements(records)->>'short_name')::text          AS short_name,
               (jsonb_array_elements(records)->>'industry')::text            AS industry,
               (jsonb_array_elements(records)->>'market')::text               AS market
    ),
    upsert AS (
        INSERT INTO companies (code, name, short_name, industry, market, is_active)
        SELECT code, name, COALESCE(short_name, name), industry, market, TRUE
        FROM data
        ON CONFLICT (code) DO UPDATE SET
            name      = EXCLUDED.name,
            short_name = EXCLUDED.short_name,
            industry  = COALESCE(EXCLUDED.industry, companies.industry),
            updated_at = now()
        WHERE companies.name != EXCLUDED.name
           OR companies.short_name != EXCLUDED.short_name
        RETURNING 1
    )
    SELECT COUNT(*) INTO inserted_count FROM upsert;

    -- 总数 - inserted = updated（实际这里 inserted 是实际写入的行）
    RETURN QUERY SELECT inserted_count, (jsonb_array_length(records) - inserted_count)::INT;
END;
$$ LANGUAGE plpgsql;
