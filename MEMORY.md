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
- **发布流程：PATCH 直接 push；MINOR/MAJOR 走 release-manager**
- **skills 目录：统一为 `skills/`（plural）**

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
- agent-bridge v0.1.0 · DeepSeek/Qwen 对话桥（NFS /mnt/nfs-ai/skill/ 已挂载）；workspace 已独立清理（废弃文件已移除，git 结构正常）
- NiuSync（暂停）· HarmonyOS 同步应用
- FolderSync-HMOS（用户授权）· 鸿蒙文件同步应用，已推送 Gitee（chen-jian82/foldersync-hmos）；⚠️ MVP 架构风险：代码堆在 entry 模块，无 protocol 接口抽象层 → 后续扩展 SMB/定时同步需重构加 protocol/ 接口层

**⚠️ 已验证错误（防重蹈）**
- Vulkan GPU 穿透 → /dev/dri 配置
- agent-bridge 多轮对话 → Bridge 实例复用
- **工具失败时：停下来，不猜测，不伪造内容** — image 工具报 400 时直接告知用户不可见，请对方提供文字描述
- **cron exec bug：`cd ... && python3` 复合命令被安全策略拦截 → 用 `python3 /full/path/to/script.py`**
- **FolderSync-HMOS 架构缺陷**：当前代码堆在 entry 模块，无接口抽象层 → MVP 后需重构加 protocol/ 接口层

---

## 📝 最近日志

`memory/daily/2026-04-13.md` | `memory/daily/2026-04-14*.md` | `memory/daily/2026-04-16.md`

---

## Promoted From Short-Term Memory

**2026-04-13** — 首日会话，取名 Arc/小A，分享双层记忆方案。完成 QMD 安装、NFS 技能复制、skill-vetter P0 安全门槛确立、agent-bridge 项目从 NFS 复制到 workspace。

**2026-04-14** — 记忆体系对比 + QMD 混合搜索调参（MMR+30天半衰期）；memory_consolidate + hindsight_reflect 脚本落地；browser agent QQ 路由修复；时区改为 Asia/Shanghai；llama-server Docker 配置；gateway pairing 解决。

**2026-04-16** — NiuSync 项目命名、规划（已暂停）；agent-bridge v0.1.0 发布；skills 目录统一到 `skills/`；memory-sync-protocol + memory-audit-guardian 安装；MEMORY.md 净化（审计 B 级）；图片伪造事件复盘（工具失败时不停、捏造内容）

**2026-04-15** — cron exec bug（`cd && python3` 被安全策略拦截）发现；QMD 向量 embedding 仍不可用（被系统 kill）；memory_consolidate 每日归档正常（0 项操作）；/tmp/openclaw-backup 清理（544MB）；workspace_cleanup 脚本误报修复

**2026-04-16** — NiuSync 项目命名、规划（已暂停）；agent-bridge v0.1.0 发布；FolderSync-HMOS 项目启动（用户授权）；skills 目录统一到 `skills/`；memory-sync-protocol + memory-audit-guardian 安装；HOT.md 发布流程规则建立；小红书抓取 skill-xiaohongshu-scraper 审查；图片伪造事件复盘（工具失败时不停、捏造内容）

**2026-04-17** — agent-bridge-ask 外部咨询流程建立；NiuSync 咨询（长文本）response_extractor 稳定性问题发现；图片伪造事件复盘完成

---

> ⚠️ 详细档案（people/projects/glossary）不放 MEMORY，通过 QMD 检索
> ⚠️ 工具配置详情 → TOOLS.md
> ⚠️ 每日变更日志 → memory/daily/YYYY-MM-DD.md

## Promoted From Short-Term Memory (2026-04-17)

<!-- openclaw-memory-promotion:memory:memory/2026-04-14.md:339:342 -->
- - - 创建 collection：workspace-memory - Embedding 模型已就绪（来自本地缓存路径） - 语义搜索验证通过（CPU 模式可用） ### 11:28 UTC — NFS 检查 - 用户提到 192.168.6.6 有 NFS 和 QMD 模型 - 当前机器 IP：192.168.6.50 - 无 root 权限，无法挂载 NFS - 模型文件已存在于 ~/.cache/qmd/models/ ## 待处理 - [ ] 创建 memory/projects/ 项目档案（openclaw-memory-architecture） - [ ] 创建 memory/knowledge/ 知识沉淀区 - [ ] 考虑程序职员角色的自动化（cron job 扫描日志） - [ ] 制定晋升/降级机制的执行规则 ## 决策记录 | 决策 | 理由 | |------|------| | 采用双层记忆架构 | 用户明确要求，结构更清晰 | | 不删除旧文件 | BOOTSTRAP.md 和旧 hello 文件保留归档 | [confidence=0.85 evidence=memory/daily/2026-04-13.md:31-54] - # 2026-04-13 日志归档 > 本文件已归档，内容迁移至 `memory/daily/2026-04-13.md` [confidence=0.70 evidence=memory/2026-04-13.md:1-4] <!-- openclaw:dreaming:rem:end --> [score=0.826 recalls=4 avg=1.000 source=memory/2026-04-14.md:339-342]
<!-- openclaw-memory-promotion:memory:memory/2026-04-14.md:143:162 -->
- - Candidate: Assistant: 模型已经在了！之前下载被 kill 是临时中断，但文件已存在。 检查下当前状态： - confidence: 0.58 - evidence: memory/.dreams/session-corpus/2026-04-13.txt:34-34 - recalls: 0 - status: staged - Candidate: Assistant: 模型文件存在，但 embedding 未完成（之前被 kill 了）。现在跑一次： - confidence: 0.58 - evidence: memory/.dreams/session-corpus/2026-04-13.txt:35-35 - recalls: 0 - status: staged - Candidate: Assistant: Embedding 完成。现在测试搜索： - confidence: 0.58 - evidence: memory/.dreams/session-corpus/2026-04-13.txt:36-36 - recalls: 0 - status: staged - Candidate: Assistant: QMD 语义搜索已就绪。 搜索结果： - `"双层记忆"` → 术语表(0.93) > 每日日志(0.56) > 用户档案(0.43) - `"用户偏好"` → 用户档案(0.92) > 每日日志(0.50) CPU 模式慢（每次 ~8-12 秒），但能跑。模型来自 NFS 那边的路径，之前下载中断但文件已缓存。 更新记忆和 TOOLS.md： - confidence: 0.58 - evidence: memory/.dreams/session-corpus/2026-04-13.txt:37-37 - recalls: 0 - status: staged [score=0.801 recalls=6 avg=0.815 source=memory/2026-04-14.md:143-162]

## Promoted From Short-Term Memory (2026-04-23)

<!-- openclaw-memory-promotion:memory:memory/2026-04-17.md:423:425 -->
- - Candidate: Possible Lasting Truths: - - 创建 collection：workspace-memory - Embedding 模型已就绪（来自本地缓存路径） - 语义搜索验证通过（CPU 模式可用） ### 11:28 UTC — NFS 检查 - 用户提到 192.168.6.6 有 NFS 和 QMD 模型 - 当前机器 IP：192.168.6.50 - 无 root 权限，无法挂载 NFS - 模型文件已存在于 ~/.cache/qmd/models/ ## 待处理 - [ ] 创建 memory/projects/ 项目档案（ - confidence: 0.62 - evidence: memory/2026-04-16.md:448-450 [score=0.856 recalls=0 avg=0.620 source=memory/2026-04-17.md:13-15]
