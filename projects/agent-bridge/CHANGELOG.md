# Changelog

## [0.2.0] - 2026-04-16

### Added
- `DeepSeekBridge` — DeepSeek 网页版对话桥接
- `QwenBridge` — 通义千问网页版对话桥接
- `agent-bridge-ask` skill — OpenClaw 集成
- 流式响应速度下降检测算法
- 自适应超时：`clamp(10s, query_len * 0.1 + 30s, 120s)`
- `elif` 链优化 stop_btn 三态处理

### Changed
- `response_extractor.py` — 速度下降检测替代纯稳定判断
- profile 路径修正（`data/browser_profile_*` → `projects/agent-bridge/data/browser_profile_*`）
- `utils.py` 清理（271 → 19 行，移除死代码）

### Fixed
- profile 路径错误导致每次启动都需重新登录
- `stop_btn is None` 时无 fallback 的问题
- VNC 地址硬编码（已移除）
- `qwen_bridge.py` 缩进问题

### Removed
- `copilot_bridge.py`（未实现）
- `xiaohongshu_bridge.py`（未实现）
- `utils.py` 死代码（start_xvfb、stop_xvfb、SELECTORS、BROWSER_ARGS 等）
- `response_extractor.py` 死代码（format_for_learning、extract_*_response、demo）

---

## [0.1.0] - 2026-04-14

Initial release.
