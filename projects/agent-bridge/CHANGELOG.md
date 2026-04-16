# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-04-16

### Added
- XiaohongshuBridge（小红书 Bridge，支持持久化上下文）
- bb-browser skill（登录态网页访问，无需 API Key）
- agent-bridge-ask skill（DeepSeek/Qwen 对话桥接）
- agent-bridge 项目（多智能体桥接系统）
- proactive-agent v3.1.0（WAL 协议、Working Buffer、Heartbeat checklist）
- QMD 混合搜索 + MMR + 30天半衰期时间衰减
- 双层记忆架构初始化

### Changed
- workspace_cleanup.py 归档整理
- Ubuntu 24.04 命令参考
- AGENTS.md 新增决策协议和复盘协议
- MEMORY.md 三层检索协议重构

### Fixed
- agent-bridge-ask 话题连续性问题（Bridge 实例复用）
- 移除过时 API 引用
- TopicManagerMixin 引用错误
- .gitignore 白名单路径问题
- .learnings/ 目录切换
- 复盘协议路径更正

---

## [Unreleased]

Initial release roadmap:
- [x] agent-bridge core (DeepSeek/Qwen bridge)
- [x] XiaohongshuBridge
- [x] bb-browser skill
- [x] agent-bridge-ask skill
- [ ] MCP server integration
- [ ] 更多平台 Bridge
