-- 综合市场汇报机制 数据库表结构
-- 创建日期: 2026-06-07
-- 执行者: Arc

-- ============================================
-- 1. 汇报记录表
-- ============================================
CREATE TABLE IF NOT EXISTS market_reports (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    trade_date  DATE NOT NULL COMMENT '交易日期',
    report_type ENUM('pre_market', 'midday', 'post_market', 'intraday_alert') NOT NULL COMMENT '汇报类型',
    content     JSON COMMENT '完整报告内容',
    summary     JSON COMMENT '汇总数据（用于快速查询）',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_date_type (trade_date, report_type),
    INDEX idx_trade_date (trade_date),
    INDEX idx_report_type (report_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='市场汇报记录表';

-- ============================================
-- 2. 汇报订阅配置
-- ============================================
CREATE TABLE IF NOT EXISTS report_subscriptions (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id     VARCHAR(50) NOT NULL COMMENT '用户ID',
    report_type ENUM('pre_market', 'midday', 'post_market', 'intraday_alert') NOT NULL COMMENT '汇报类型',
    enabled     BOOLEAN DEFAULT TRUE COMMENT '是否启用',
    channel     VARCHAR(20) DEFAULT 'qq' COMMENT '推送渠道',
    notify_time TIME COMMENT '自定义通知时间（可选）',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_user_type (user_id, report_type),
    INDEX idx_user_id (user_id),
    INDEX idx_enabled (enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='汇报订阅配置表';

-- ============================================
-- 3. 异动记录表
-- ============================================
CREATE TABLE IF NOT EXISTS intraday_alerts (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    trade_date  DATE NOT NULL COMMENT '交易日期',
    alert_time  DATETIME NOT NULL COMMENT '异动时间',
    alert_type  ENUM('limit_up', 'limit_down', 'break_seal', 'anomaly') NOT NULL COMMENT '异动类型',
    stock_code  VARCHAR(10) COMMENT '股票代码',
    stock_name  VARCHAR(50) COMMENT '股票名称',
    detail      JSON COMMENT '异动详情',
    notified    BOOLEAN DEFAULT FALSE COMMENT '是否已推送',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_trade_date (trade_date),
    INDEX idx_alert_type (alert_type),
    INDEX idx_notified (notified)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='盘中异动记录表';

-- ============================================
-- 4. 行业ETF成分股筛选候选表
-- ============================================
CREATE TABLE IF NOT EXISTS sector_filter_candidates (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    trade_date      DATE NOT NULL COMMENT '交易日期',
    trigger_type    ENUM('morning', 'afternoon') NOT NULL COMMENT '触发类型',
    stock_code      VARCHAR(10) NOT NULL COMMENT '股票代码',
    stock_name      VARCHAR(50) NOT NULL COMMENT '股票名称',
    sector          VARCHAR(50) NOT NULL COMMENT '所属板块',
    price           DECIMAL(10,2) NOT NULL COMMENT '当前价格',
    ma5             DECIMAL(10,2) COMMENT '5日均线',
    ma10            DECIMAL(10,2) COMMENT '10日均线',
    ma20            DECIMAL(10,2) COMMENT '20日均线',
    ma60            DECIMAL(10,2) COMMENT '60日均线',
    deviation_ma20  DECIMAL(8,4) COMMENT 'MA20偏离度(%)',
    deviation_ma60  DECIMAL(8,4) COMMENT 'MA60偏离度(%)',
    pct_chg_20d     DECIMAL(8,4) COMMENT '20日涨幅(%)',
    volume_ratio    DECIMAL(8,4) COMMENT '量比',
    classification  VARCHAR(20) COMMENT '分类：稳健型/进取型/超跌型/震荡型',
    signal_strength DECIMAL(6,4) COMMENT '信号强度',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_date_trigger_stock (trade_date, trigger_type, stock_code),
    INDEX idx_trade_date (trade_date),
    INDEX idx_classification (classification),
    INDEX idx_sector (sector),
    INDEX idx_signal_strength (signal_strength)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='行业ETF成分股筛选候选表';

-- ============================================
-- 5. 行业ETF筛选报告快照表
-- ============================================
CREATE TABLE IF NOT EXISTS sector_filter_reports (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    trade_date      DATE NOT NULL COMMENT '交易日期',
    trigger_type    ENUM('morning', 'afternoon') NOT NULL COMMENT '触发类型',
    strong_sectors JSON COMMENT '强势行业列表',
    summary         JSON COMMENT '汇总统计',
    candidates      JSON COMMENT '候选股明细',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_date_trigger (trade_date, trigger_type),
    INDEX idx_trade_date (trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='行业ETF筛选报告快照表';