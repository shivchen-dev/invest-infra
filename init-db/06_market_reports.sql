-- init-db/06_market_reports.sql
-- 市场汇报模块：market_reports / market_alerts / alert_subscriptions

CREATE TABLE IF NOT EXISTS market_reports (
    id              BIGSERIAL PRIMARY KEY,
    report_type     VARCHAR(32)  NOT NULL,  -- pre_market/midday/post_market/intraday_alert
    trade_date      DATE         NOT NULL,
    content         JSONB        NOT NULL,  -- 报告完整内容
    generated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE(report_type, trade_date)
);

CREATE TABLE IF NOT EXISTS market_alerts (
    id              BIGSERIAL PRIMARY KEY,
    stock_code      VARCHAR(16)  NOT NULL,
    stock_name      VARCHAR(64)  NOT NULL,
    alert_type      VARCHAR(32)  NOT NULL,  -- limit_up/limit_down/anomaly/...
    detail          JSONB        NOT NULL,  -- 告警详情
    trade_date      DATE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alert_subscriptions (
    id              BIGSERIAL PRIMARY KEY,
    user_id         VARCHAR(64)  NOT NULL,
    report_type     VARCHAR(32)  NOT NULL,  -- pre_market/midday/post_market
    enabled         BOOLEAN      NOT NULL DEFAULT TRUE,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE(user_id, report_type)
);

CREATE INDEX IF NOT EXISTS idx_market_reports_type_date ON market_reports(report_type, trade_date);
CREATE INDEX IF NOT EXISTS idx_market_alerts_code       ON market_alerts(stock_code);
CREATE INDEX IF NOT EXISTS idx_market_alerts_created    ON market_alerts(created_at);
CREATE INDEX IF NOT EXISTS idx_market_alerts_trade_date ON market_alerts(trade_date);
CREATE INDEX IF NOT EXISTS idx_alert_subs_user           ON alert_subscriptions(user_id, report_type);
