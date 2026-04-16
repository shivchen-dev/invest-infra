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
- **技能安装：P0 级要求 — 必须通过 skill-vetter 安全审查后方可安装**
- **项目开发：P0 级要求 — 必须有用户明确授权（"授权"）或开始指令（"开始"），方可开始执行**

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
- **clawhub 搜索规则**: 优先使用 `--registry https://cn.clawhub-mirror.com`，默认镜像不可用时再换官方
- **bb-browser**: `npx clawhub install bb-browser --registry https://cn.clawhub-mirror.com`

**项目与知识**
- openclaw-memory-architecture · 双层记忆方案
- llama-docker · DeepSeek-R1-Distill-Qwen-1.5B-Q8_0.gguf · /dev/dri GPU穿透

**⚠️ 已验证错误（防重蹈）**
- Vulkan `No devices found` → 需 `/dev/dri:/dev/dri` docker 挂载 + 移除无效 `--gpu 1` 参数
- `GGML_VULKAN_DEVICE: "0"` 可能冲突，容器内不设置

---

## 📝 最近日志

`memory/daily/2026-04-13.md` | `memory/daily/2026-04-14*.md`

---

## Promoted From Short-Term Memory

**2026-04-13** — 首日：用户通过 QQBot c2c 首次会话，取名 Arc/小A，分享 openclaw-memory-architecture 双层记忆方案。完成 QMD 安装、NFS 技能复制（`/mnt/nfs-ai/skill/`）、skill-vetter P0 安全门槛确立、agent-bridge 项目及配套技能从 NFS 复制到 workspace，agent-bridge SKILL.md 已移除过时 API 部分。

**2026-04-14** — Wiki 记忆体系对比 + QMD 混合搜索调参（70%向量+30%BM25+MMR+30天半衰期）；memory_consolidate + hindsight_reflect 脚本落地；browser agent QQ 路由问题修复（bindings 配置）；时区改为 Asia/Shanghai；llama-server Docker 运行于 8080 端口，配置为 vLLM provider；gateway pairing 问题解决。

---

## 🔧 技术快照

**bb-browser**：`npm install -g bb-browser` + `bb-browser site update`（126 社区 adapter）
- 用途：无需 API key 访问需要登录的网站（小红书/知乎/微博等）
- 前提：Chrome 运行于 `--remote-debugging-port=9222`
- 用法：`BB_BROWSER_CDP_URL=http://localhost:9222 bb-browser site xiaohongshu/search "关键词"`

**gateway pairing 解决**：宿主机运行 `openclaw devices list` → `openclaw devices approve <pending-id>`
- 所有 RPC 工具（cron/spawn/send）需要 device pairing，不只是 bind 配置

**浏览器持久化**：小红书登录态需保持浏览器运行，profile 目录不关闭
- profile：`projects/agent-bridge/data/browser_profile_xiaohongshu/`

**NFS 已挂载**：`/mnt/nfs-ai/skill/` — 共 21 个自定义技能，workspace 所需可从此处复制

---

> ⚠️ 详细档案（people/projects/glossary）不放 MEMORY，通过 QMD 检索
