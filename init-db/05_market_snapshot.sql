-- 投研系统数据采集层 — 每日市场快照表
-- 创建日期: 2026-06-07
-- 用途: 每日16:00一次性采集MCP数据，缓存到DB，各报告从DB读
-- 执行者: Arc

-- ============================================
-- 每日市场快照表（核心）
-- ============================================
CREATE TABLE IF NOT EXISTS daily_market_snapshot (
    id              BIGSERIAL PRIMARY KEY,
    trade_date      DATE NOT NULL,
    data_type       VARCHAR(50) NOT NULL,   -- limit_stats / auction / capital_flow / ladder 等
    tool_name       VARCHAR(100) NOT NULL,  -- 对应的 MCP 工具名
    raw_data        JSONB NOT NULL,
    collected_at    TIMESTAMP DEFAULT NOW(),

    UNIQUE (trade_date, data_type)
);

CREATE INDEX IF NOT EXISTS idx_dms_date_type ON daily_market_snapshot(trade_date, data_type);
CREATE INDEX IF NOT EXISTS idx_dms_collected ON daily_market_snapshot(collected_at);

COMMENT ON TABLE daily_market_snapshot IS '每日市场快照表：存储每日16:00批量采集的MCP原始数据';
COMMENT ON COLUMN daily_market_snapshot.data_type IS '数据类型：limit_stats/auction/capital_flow/ladder/hot_sectors/board_break等';
COMMENT ON COLUMN daily_market_snapshot.tool_name IS '对应的MCP工具名称';

-- ============================================
-- 数据类型枚举（供参考，程序中使用字符串）
-- ============================================
-- limit_stats      : 涨跌停统计
-- hot_sectors      : 最强风口
-- market_leaders   : 最强主线+龙头
-- limit_up_ladder  : 涨停梯队
-- board_break      : 断板分析
-- broken_limit_up  : 炸板池
-- capital_flow_mkt : 大盘资金流
-- capital_flow_sec : 板块资金流
-- auction_scan     : 集合竞价扫描
-- auction_wts      : 弱转强
-- auction_feedback : 竞价反馈
-- market_overview  : 大盘概况
-- market_replay    : 复盘数据包
-- dragon_tiger     : 龙虎榜
-- cls_news         : 财联社快讯
