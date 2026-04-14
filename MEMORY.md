# MEMORY.md — Arc 热缓存

> 高价值低噪音。MEMORY 解决"去哪找"，QMD 决定"找到什么"。
> 详细 → memory/ 目录 | 搜索 → QMD

---

## 🔌 QMD 索引入口

- **Collection**: `workspace-memory`
- **Source path**: `/home/claw/.openclaw/workspace/memory`
- **Search priority**: `title exact` → `keyword` → `semantic`
- **命中处理**: top-k(3-5) → 每条片段(5-20行) → 摘要注入

---

## ⚙️ 协议与做事原则

- 做事原则：先方案，后执行；先确认，再推进
- 汇报风格：结论先行，简短
- 记忆入库标准：≥2条 — 影响决策(>2周)/重复使用/损失风险/可验证
- **技能安装：P0 级要求 — 必须通过 skill-vetter 安全审查后方可安装**

---

## 🎯 热缓存锚点词（Hot Anchors）

> MEMORY 只放索引入口，详细内容走 QMD

**身份与上下文**
- Arc · 小A · 主用户 · 用户画像 · 做事原则 · 汇报风格

**记忆系统**
- 双层记忆架构 · 热缓存 · 深度存储 · 原子事实链 · 程序职员
- 晋升/降级 · 入库标准 · QMD · BM25 · 语义搜索 · **skill-vetter（安装前必审）**

**工具与环境**
- OpenClaw · QMD · AMD780M (Phoenix3) · Vulkan · NFS · CPU模式
- **clawhub mirror**: `https://cn.clawhub-mirror.com`（国内镜像）
- **bb-browser**: `npx clawhub install bb-browser --registry https://cn.clawhub-mirror.com`

**项目与知识**
- openclaw-memory-architecture · 双层记忆方案
- llama-docker · DeepSeek-R1-Distill-Qwen-1.5B-Q8_0.gguf · /dev/dri GPU穿透

**⚠️ 已验证错误（防重蹈）**
- Vulkan `No devices found` → 需 `/dev/dri:/dev/dri` docker 挂载 + 移除无效 `--gpu 1` 参数
- `GGML_VULKAN_DEVICE: "0"` 可能冲突，容器内不设置

---

## 📝 最近日志

`memory/daily/2026-04-13.md`

---

> ⚠️ 详细档案（people/projects/glossary）不放 MEMORY，通过 QMD 检索

## Promoted From Short-Term Memory (2026-04-14)

<!-- openclaw-memory-promotion:memory:memory/daily/2026-04-13.md:1:38 -->
- # memory/daily/2026-04-13.md ## 今日事件流 ### 10:34 UTC — 首次会话 - 用户通过 QQBot c2c 发起首次对话 - 用户：我只是一个新人 ### 10:37 UTC — 取名 - 用户给 Agent 取名「小A」 - Agent 正式名 Arc，来源 Architecture - 两个名字都认 ### 10:56 UTC — 项目分享 - 用户分享了 github.com/blessonism/openclaw-memory-architecture - 这是一个双层记忆系统方案（热缓存 + 深度存储） - 核心：解决 AI Agent 跨 session 失忆问题 ### 11:09 UTC — 记忆架构配置 - 用户要求按双层记忆方案配置当前 Agent - 执行了以下操作： 1. 创建 memory/ 子目录结构（people/ projects/ glossary/ knowledge/ daily/ context/） 2. 重构 MEMORY.md 为热缓存格式（~50行结构表） 3. 创建用户档案（memory/people/user-primary.md）+ 原子事实链 4. 创建术语表（memory/glossary/arc-terms.md） 5. 更新本日志（memory/daily/2026-04-13.md） ### 11:20 UTC — QMD 安装 - 用户分享了 github.com/tobi/qmd（本地文档搜索工具） - 安装：npm install -g @tobilu/qmd - 创建 collection：workspace-memory - Embedding 模型已就绪（来自本地缓存路径） - 语义搜索验证通过（CPU 模式可用） ### 11:28 UTC — NFS 检查 - 用户提到 192.168.6.6 有 NFS 和 QMD 模型 - 当前机器 IP：192.168.6.50 - 无 root 权限，无法挂载 NFS [score=0.944 recalls=16 avg=0.941 source=memory/daily/2026-04-13.md:1-38]
<!-- openclaw-memory-promotion:memory:memory/daily/2026-04-13.md:31:54 -->
- - 创建 collection：workspace-memory - Embedding 模型已就绪（来自本地缓存路径） - 语义搜索验证通过（CPU 模式可用） ### 11:28 UTC — NFS 检查 - 用户提到 192.168.6.6 有 NFS 和 QMD 模型 - 当前机器 IP：192.168.6.50 - 无 root 权限，无法挂载 NFS - 模型文件已存在于 ~/.cache/qmd/models/ ## 待处理 - [ ] 创建 memory/projects/ 项目档案（openclaw-memory-architecture） - [ ] 创建 memory/knowledge/ 知识沉淀区 - [ ] 考虑程序职员角色的自动化（cron job 扫描日志） - [ ] 制定晋升/降级机制的执行规则 ## 决策记录 | 决策 | 理由 | |------|------| | 采用双层记忆架构 | 用户明确要求，结构更清晰 | | 不删除旧文件 | BOOTSTRAP.md 和旧 hello 文件保留归档 | [score=0.907 recalls=19 avg=0.817 source=memory/daily/2026-04-13.md:31-54]

---

## 🔧 技术快照（2026-04-14）

**bb-browser**：`npm install -g bb-browser` + `bb-browser site update`（126 社区 adapter）
- 用途：无需 API key 访问需要登录的网站（小红书/知乎/微博等）
- 前提：Chrome 运行于 `--remote-debugging-port=9222`
- 用法：`BB_BROWSER_CDP_URL=http://localhost:9222 bb-browser site xiaohongshu/search "关键词"`
- Skill：已创建 `skill/bb-browser/` 供以后调用

**gateway pairing 解决**：宿主机运行 `openclaw devices list` → `openclaw devices approve <pending-id>`
- 所有 RPC 工具（cron/spawn/send）需要 device pairing，不只是 bind 配置
- 当前已批准，RPC 全部正常

**浏览器持久化**：小红书登录态需保持浏览器运行，profile 目录不关闭
- profile：`projects/agent-bridge/data/browser_profile_xiaohongshu/`
