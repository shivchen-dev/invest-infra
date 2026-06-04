-- Migration: 替换 fund_flow_big_deal 大单追踪 → 全市场个股资金流日频快照
-- 2026-06-01

-- 新表：个股资金流日频快照（东方财富全市场）
CREATE TABLE IF NOT EXISTS stock_daily_fund_flow (
    id              SERIAL PRIMARY KEY,
    company_id      INT          NOT NULL REFERENCES companies(id),
    calc_date       DATE         NOT NULL,               -- 快照日期

    -- 资金流指标（单位：元）
    inflow_main     NUMERIC(20,2),                      -- 主力流入（超大单+大单）
    inflow_mid      NUMERIC(20,2),                      -- 中单流入
    outflow_main    NUMERIC(20,2),                      -- 主力流出
    outflow_mid    NUMERIC(20,2),                      -- 中单流出
    net_inflow_main NUMERIC(20,2),                      -- 主力净流入
    net_inflow_mid  NUMERIC(20,2),                      -- 中单净流入

    -- 辅助字段
    close_price     NUMERIC(12,4),                      -- 收盘价（快照日）
    change_pct      NUMERIC(10,4),                      -- 涨跌幅
    turnover_rate   NUMERIC(10,4),                      -- 换手率
    amount          NUMERIC(20,2),                      -- 成交额

    source          VARCHAR(50)  DEFAULT 'eastmoney',
    created_at      TIMESTAMPTZ  DEFAULT now(),

    UNIQUE (company_id, calc_date)
);
COMMENT ON TABLE stock_daily_fund_flow IS '个股资金流日频快照（东方财富全市场，替换 fund_flow_big_deal）';
CREATE INDEX idx_sdf_company   ON stock_daily_fund_flow(company_id);
CREATE INDEX idx_sdf_date      ON stock_daily_fund_flow(calc_date);
CREATE INDEX idx_sdf_net       ON stock_daily_fund_flow(net_inflow_main);