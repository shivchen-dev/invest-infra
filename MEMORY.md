# MEMORY.md — Arc 热缓存

> 高价值低噪音。MEMORY 解决"去哪找"，QMD 决定"找到什么"。
> 详细 → memory/ 目录 | 搜索 → QMD

---

## 🔌 QMD 索引入口

- **Collection**: `workspace-memory`
- **Source path**: `/home/claw/.openclaw/workspace/memory`
- **Search priority**: `title exact` → `keyword` → `semantic`
- **命中处理**: top-k(3-5) → 每条片段(5-20行) → 摘要注入
- **注意**: 向量 embedding 模型下载被系统 kill，BM25 全文搜索可用，向量搜索暂停

---

## ⚙️ 协议与做事原则

- 做事原则：先方案，后执行；先确认，再推进
- 汇报风格：结论先行，简短
- 记忆入库标准：≥2条 — 影响决策(>2周)/重复使用/损失风险/可验证
- **技能安装：P0 级 — 必须通过 skill-vetter 审查后方可安装**
- **项目开发：P0 级 — 必须有用户明确授权（"授权"）或开始指令（"开始"），方可执行**
- **外部咨询：默认进行（除非用户明确说"不咨询"）**
- **搜索 ≠ 安装：clawhub search 只读，安装才需授权**

---

## 🎯 热缓存锚点词（Hot Anchors）

**身份与上下文**
- Arc · 小A · 主用户 · 用户画像 · 做事原则 · 汇报风格

**记忆系统**
- 双层记忆架构 · 热缓存 · 深度存储 · 原子事实链 · 程序职员
- 晋升/降级 · 入库标准 · QMD · BM25 · 语义搜索 · skill-vetter

**工具与环境**
- OpenClaw · QMD · AMD780M (Phoenix3) · Vulkan
- 工具配置详情 → TOOLS.md

**项目与知识**
- openclaw-memory-architecture · 双层记忆方案
- llama-docker · DeepSeek-R1-Distill-Qwen-1.5B-Q8_0.gguf
- agent-bridge v0.1.0 · DeepSeek/Qwen 对话桥
- NiuSync（暂停）· HarmonyOS 同步应用

**⚠️ 已验证错误（防重蹈）**
- Vulkan GPU 穿透 → /dev/dri 配置
- agent-bridge 多轮对话 → Bridge 实例复用

---

## 📝 最近日志

`memory/daily/2026-04-13.md` | `memory/daily/2026-04-14*.md` | `memory/daily/2026-04-16.md`

---

## Promoted From Short-Term Memory

**2026-04-13** — 首日会话，取名 Arc/小A，分享双层记忆方案。完成 QMD 安装、NFS 技能复制、skill-vetter P0 安全门槛确立、agent-bridge 项目从 NFS 复制到 workspace。

**2026-04-14** — 记忆体系对比 + QMD 混合搜索调参（MMR+30天半衰期）；memory_consolidate + hindsight_reflect 脚本落地；browser agent QQ 路由修复；时区改为 Asia/Shanghai；llama-server Docker 配置；gateway pairing 解决。

**2026-04-16** — NiuSync 项目命名、规划（已暂停）；agent-bridge v0.1.0 发布；skills 目录统一到 `skills/`；memory-sync-protocol + memory-audit-guardian 安装；MEMORY.md 净化（审计 B 级）。

---

> ⚠️ 详细档案（people/projects/glossary）不放 MEMORY，通过 QMD 检索
> ⚠️ 工具配置详情 → TOOLS.md
> ⚠️ 每日变更日志 → memory/daily/YYYY-MM-DD.md
