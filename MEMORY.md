# MEMORY.md — Arc 热缓存

> 纯索引层。搜记忆用工具，能找到东西是第一准则。
> 搜索优先级：MEMORY.md（索引）→ Memvid Smart Frames → QMD 兜底

---

## 🏛️ 记忆体系运转协议（静态规则）
## ⚠️ 未经授权禁止修改

### 三层架构
```
L1 MEMORY.md    → 索引 + 协议
L2 Memvid       → 叙事层（append-only）
L3 memory/*.md  → 冷存储（兜底检索）
```

### 查询路由（搜记忆时用这棵树）
**触发条件**：用户问及过往项目/决策/事件/偏好

① MEMORY.md 索引命中 → 去 Memvid 查关键词
② Memvid 查询 → 命中 → 使用叙事片段
③ QMD 兜底 → 命中 → 补充上下文
④ 仍不命中 → 告知用户"未找到相关记忆"
⑤ 重要决策需 ≥2 个独立来源确认

### 写入时机
| 层 | 触发 | 说明 |
|---|---|-|
| memory/*.md | 每次对话 | 自动落盘 |
| Memvid | 每日 04:00 cron + 里程碑 | 叙事同步 |
| MEMORY.md | 仅 Agent 人工晋升 | 只写索引指针 |

### 禁止写入红线
❌ 系统自动写 MEMORY.md
❌ 原始对话 copy 到 MEMORY.md
❌ 完整项目细节写 MEMORY.md
❌ 系统自动决定什么该进 MEMORY.md

### 静态 P0 协议
⚠️ 技能安装 → skill-vetter 审查
⚠️ 项目开发 → 授权/开始指令才执行

---

## 🚨 投研系统 PG-First 铁律（2026-06-15 立）
**触发：** R0.2 数据管道修复（commit 3ea5ef3）— MCP vendor bug → 换 PG 解决
**用户原话：** "投研系统数据以本地数据库为主，避免 MCP 等在线数据获取，没有数据就加强采集层，其他任何模块设计前提都是从 PG 获取"

- ✅ **设计前提**：所有投研模块查询时只走 PG（`etf_quotes` / `etf_alpha_signals` / `index_quotes` / `market_reports` / `investment_memos` 等）
- ⚠️ **数据缺失** → 修采集层（cron / etl），**不**修模块去查 MCP
- 🚫 **禁止**：Node 端在查询时 MCP fallback（vendor bug 风险，R0.2 教训）
- ✅ **唯一允许接触 MCP 的层** = 采集层（cron 15:05 盘前 / 09:25 竞价）
- ✅ **采集层异常** → 立即告警，不让消费层察觉

**Phase 1 落地：** 选股 Dashboard 走 C 方案（cron 跑 `PreMarketFormatter` → 落库 `market_reports.messages` → Node 读 PG）

详细规范 → `AGENTS.md` P0 #5 · 教训 → `TOOLS.md` MCP 章节

---

## 📂 项目索引（audit 驱动更新）

| 项目/主题 | Memvid 查询关键词 |
|-----------|------------------|
| **智能投研体系** | `mem.find('智能投研 Phase 0', mode='lex')` |
| **FolderSync-HMOS** | `mem.find('FolderSync', mode='lex')` |
| **JiuwenSwarm** | `mem.find('JiuwenSwarm', mode='lex')` |
| **agent-bridge** | `mem.find('agent-bridge', mode='lex')` |
| **数据采集层** | `mem.find('数据采集层 批量修复', mode='lex')` |
| **投研系统 P0 修复** | `mem.find('投研系统 P0', mode='lex')` |
| **Claude Code 重构工作流** | `mem.find('Claude Code 重构', mode='lex')` |
| **CIA Agent** | `mem.find('CIA Agent', mode='lex')` |
| **KB 知识库** | `/home/claw/.openclaw/kb`（Claude Code 技巧、router 配置） |

---

*最后更新：2026-06-06*  *静态协议区精简完成*