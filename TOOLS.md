# TOOLS.md - Local Notes

## 记忆系统架构

```
MEMORY.md（纯索引 ~50行）
    ↓ 指向
Memvid Smart Frames（叙事层，append-only）
    ↓ 兜底
memory/*.md（原始日志，QMD 搜索）
```

### Memvid（Smart Frames 叙事层）
- **文件**: `memory/arc-memory.mv2`（~5.2MB，40条记录）
- **环境**: `~/.venv/memvid/bin/python3`
- **用途**: append-only Smart Frames，新记忆写入，叙事整合
- **搜索**: `mem.find(query, mode='lex')` — BM25 模式
- **迁移脚本**: `scripts/memvid_migration.py`
- **写入脚本**: `scripts/memvid_writer.py --interactive`

### QMD 检索规则
- **优先级**: `title exact` → `keyword` → `semantic`
- **命中处理**: top-k(3-5) → 片段(5-20行) → 摘要注入
- **入库标准**: 满足≥2条 — 影响决策(>2周)/重复使用/损失风险/可验证
- **注意**: QMD 向量正常（1362 embeddings），BM25 兜底

---

## QMD - 本地文档搜索

- **Collection**: `workspace-memory`
- **Source path**: `/home/claw/.openclaw/workspace/memory`
- **模型缓存**: `~/.cache/qmd/models/`
- **命令**:
  - `qmd search "关键词" -c workspace-memory`（全文 BM25）
  - `qmd query "语义查询" -c workspace-memory`（混合搜索，GPU加速）
  - `qmd vsearch "查询" -c workspace-memory`（向量搜索）
  - `qmd get qmd://workspace-memory/path/to/file.md`（获取文档）
  - `qmd update`（re-index 所有 collection，**不支持 -c**，幂等）
  - `GGML_CUDA_USE_ALLOCATOR=0 qmd embed`（重新嵌入，**不支持 -c**）
- **Context**: Arc记忆系统路由：MEMORY.md → memory/ → QMD检索 → 分层注入
- **GPU**: AMD 780M (Vulkan), VRAM 7.9GB free
- **踩坑（2026-06-11）**:
  - `qmd update` 和 `qmd embed` **都没有 per-collection 过滤**，`-c` 被静默忽略
  - 两者都**幂等**：未变文件 0 工作量；死 collection（路径不存在）自动 0 files
  - 嵌入器: `embeddinggemma-300M-Q8_0.gguf`，3 docs / 9 chunks ≈ 2s

---

## 🚨 MCP 教训 — 投研系统 PG-First 根因（2026-06-15 立）

**背景：** R0.2 数据管道 bug 复盘（commit 3ea5ef3）

| 现象 | 根因 | 修复 |
|------|------|------|
| 14/14 ETF 现价=0 | `mcpClient.ts` 调错服务器（127.0.0.1:19100 = JiuwenClaw Gateway，不是 wudao_aStock MCP）| 换 PG `etf_quotes` 直读（441,979 行 cron 落库）|
| 不同 code 返回同一份数据 | **wudao_aStock MCP vendor bug**（半导体的 26.23 给所有 ETF）| 同上 |
| rebalance 13 alert 全部崩 | 上游现价=0 → 涨跌幅=0 → 偏离度=0 → 无 alert | 改 PG 后全 13 alert 正确 |

**铁律（用户 2026-06-15 15:14 立）：**

- 🚫 投研系统**查询时**只走 PG，禁止 MCP fallback
- ⚠️ 数据缺失 → 修采集层（cron），不修模块
- ✅ 唯一允许接触 MCP 的层 = 采集层（data-pipeline 内的 cron）
- 🚨 采集层异常 → 立即告警，不让消费层察觉（消费层要"看起来一切正常"）

**实现要点（避免重蹈）：**

- 采集层：data-pipeline 的 15:05 / 09:25 / 09:00 cron 仍可调 MCP，但**结果必须落库**（`daily_market_snapshot` / `market_reports` / `etf_quotes` 等）
- 消费层：Node 端 / Python 报表端**只读 PG**，禁止任何 `MCPClient` / `mcp.streamablehttp_client` 调用
- 监控：采集层 fail → cron watchdog 告警 → 不影响消费层运行（消费层读旧数据 + 显示"数据延迟"标记）
- 升级路径：未来加 "立即刷新" 功能 → 起 FastAPI sidecar 在采集层，**不**让消费层直接调 MCP

**测试用例（写进 .learnings/）：**

- 给 `mcpClient.ts`（如未来复活）加单测：mock MCP 返回错值 → 路由必须 fallback 到 PG 或报 503（**不**静默返回 0）
- 给所有读 PG 的路由加"PG-only" lint 规则：禁止 import `mcpClient` / `wudao_aStock*`

---

## 知识库（KB）
- **路径**: `/home/claw/.openclaw/kb`
- **内容**: Claude Code 使用技巧、router 配置等
- **用途**: 结构化知识沉淀，可通过 QMD 检索

---

## 敏感信息存储

- **目录**: `secrets/`（700 权限，仅自己可读）
- **原则**: 令牌/密钥不写进任何明文 md 文件
- **Gitee 推送凭据**（v2026-06-14 修正）：**`~/.git-credentials`**（git store mode 自动 cache，600 权限）
  - **不要**用 `secrets/gitee-token`（已过时/失效）
  - **不要**手动 `GITEE_TOKEN=*** ...)`（会跳过 git store helper）
  - **正确用法**：直接 `git push -u origin main`（store helper 自动读 ~/.git-credentials）
  - **重置 cache**：`git credential-store --file=~/.git-credentials erase`，再 push 重新输
  - 旧 `secrets/gitee-token` 文件保留作 fallback（curl 调 Gitee API 验证时可能有用）
- **QQBot Browser 令牌**: `secrets/qqbot-browser-token`
- **格式**: `appId:clientSecret`（冒号分隔）
- **使用方式**: `QQBOT_TOKEN=$(cat /home/claw/.openclaw/workspace/secrets/qqbot-browser-token)`

---

---

## 多代理定时任务管理规范

### 核心原则
各 agent cron 完全隔离，时间错峰，owner 明确。

### 命名前缀
`{agent}-{task-name}`，例 `arc-daily-memory-audit`、`cia-daily-learnings-promotion`。

### Arc（workspace）时间分桶
| 时间 | 任务 | 说明 |
|------|------|------|
| 04:00 | arc-memory-consolidate | 记忆整合脚本 |
| 05:00 | arc-daily-memory-audit | 审计过去3天，更新MEMORY.md |
| 周六 06:00 | arc-hindsight-reflect | 回顾反思脚本 |
| 03:00 | Memory Dreaming Promotion | 系统级记忆晋升（managed-by=memory-core） |

### CIA（workspace-cia）时间分桶
| 时间 | 任务 | 说明 |
|------|------|------|
| 04:00 | Daily_Learnings_Promotion | 工作日每日晋升 |
| 06:00（周一） | Weekly_Learnings_Maintenance | 周维护 |
| 06:30（周一） | workspace-cleanup | 清理 |

### 冲突规则
- 同一时段禁止两个重量任务同时跑（内存/CPU 峰值）
- 各 agent 的 isolated session 独立执行，不共享上下文
- sessionTarget 决定哪个 agent 承接，禁止职责模糊

## 本地 AI 服务（llama.cpp）

### Llama Server（127.0.0.1:8080）— Qwen3.5-9B-Q4_0 MTP
- **二进制**: `/home/claw/llama.cpp/build-vulkan/bin/llama-server`（Vulkan GPU 加速）
- **模型**: `/home/claw/models/Qwen3.5-9B-Q4_0.gguf`（Qwen3.5 9B Q4_0 量化，MTP 架构，5.2GB）
- **API**: `http://127.0.0.1:8080/v1/chat/completions`
- **PID**: 当前运行中（`ps aux | grep llama-server` 查看）

### 启动参数（2026-06-04 优化版）
```bash
nohup /home/claw/llama.cpp/build-vulkan/bin/llama-server \
  -m /home/claw/models/Qwen3.5-9B-Q4_0.gguf \
  --host 127.0.0.1 --port 8080 \
  -np 2 -ngl 99 \
  -c 2048 \
  --rope-scaling yarn --rope-scale 1.0 \
  --yarn-orig-ctx 262144 \
  --override-kv qwen35.context_length=int:8192 \
  --spec-type draft-mtp \
  --spec-draft-n-max 2 \
  --chat-template-kwargs '{"enable_thinking":false}' \
  --no-warmup > /tmp/llama-server-vulkan.log 2>&1 &
```

### 性能指标（2026-06-04 实测）
| 指标 | 值 |
|------|-----|
| 推理速度 | 19-24 tok/s |
| MTP 接受率 | 83% |
| GTT 占用 | 6.44 / 7.47 GB |
| Context | 2K（rope 扩展到 8K）|
| 思考模式 | 关闭 |

### 定位
- **适合**：cron 任务、文件处理、总结、代码审查等轻量任务
- **不适合**：长文档分析、复杂推理、多模态
- **分工**：复杂推理 → 35B 远程；日常 cron → 9B 本地

### 内存架构（AMD Phoenix3 APU）
- VRAM aperture: 512 MB（驱动+shader）
- GTT（RAM 映射）: 7.47 GB（llama.cpp Vulkan 使用此区域）
- 系统 RAM: 14 GB（共用池）
- GTT 接近上限时会 OOM，监控 `cat /sys/devices/pci0000:00/0000:00:08.1/0000:05:00.0/mem_info_gtt_used`

### 历史版本
- **Qwen3.5-4B-Q4_0**: 早期版本，context 1024（baked GGUF 元数据限制），已替换
- **Qwen3.5-4B-Q8_0**: 备选高质量量化（4.3 GB），未启用
- **Qwen3.5-9B-Q5_K_M**: 备选高质量量化（5.2GB），未启用

### 远程 AI 服务器（192.168.40.2:6060）
- **模型**: `Qwen3.6-35B-A3B-Q8`
- **用途**: 主用推理服务

---

## Llama.cpp Vulkan 编译记录
- **源码**: `/home/claw/llama.cpp/`
- **Vulkan build**: `/home/claw/llama.cpp/build-vulkan/`
- **编译选项**: `-DGGML_VULKAN=ON -DGGML_CPU=ON -DGGML_HIP=OFF`
- **SPIRV-Headers**: `/tmp/SPIRV-Headers/`（需手动 clone 并从 GitHub main 获取最新 spirv.hpp）
- **Vulkan SDK**: 系统 headers (`/usr/include`) + loader (`/usr/lib/x86_64-linux-gnu/libvulkan.so`)
- **glslc**: 系统自带（支持 cooperative_matrix，不支持 NV_cooperative_matrix2）

---

## Claude Code

### Provider: minimax (Anthropic 协议，2026-06-10 接入)

**配置位置**：`~/.claude-code-router/config.json`

```json
{
  "name": "minimax",
  "api_base_url": "https://api.minimaxi.com/anthropic/v1/messages",
  "models": ["MiniMax-M3"],
  "transformer": { "use": ["Anthropic"] }   // ⚠️ 大写 A
}
```

**3 个易踩的坑**：

1. **`api_base_url` 必须是完整 endpoint**（含 `/v1/messages`），不是 base。ccr 不会自动拼路径。看 log：
   ```
   "requestUrl":"https://api.minimaxi.com/anthropic/v1/messages"  ← 实际发出去的
   ```
   ccr 行为：入站 `/v1/messages` → 出站直接用 `api_base_url`，不拼 endpoint 路径。

2. **`transformer: { use: ["Anthropic"] }` 必须大写 A**。大小写敏感。大写触发 bypass（小写会做"OpenAI↔Anthropic"双转换）。
   - 小写 `anthropic`：请求被转 OpenAI 格式发到 upstream（minimax 真 Anthropic → 错）
   - 大写 `Anthropic`：bypass 路径，请求/响应**原样透传**

3. **正确的 endpoint** 是 `https://api.minimaxi.com/anthropic/v1/messages`（catalog.json 主 provider 写法）。备 provider 的 `https://api.minimaxi.com/anthropic`（不带 `/v1`）会 404。

**当前默认 + fallback 链**：
```json
"Router": { "default": "minimax,MiniMax-M3" },
"fallback": {
  "default": [
    "remote-ai,Qwen3.6-35B-A3B-Q8",
    "deepseek,deepseek-v4-flash"
  ]
}
```

**API key 备份**：`secrets/minimax-key`（700 权限，126 字节 `sk-cp-…`）

**已验证场景**：chat ✅ / streaming SSE ✅ / tool_use ✅

**成本**：¥0.6 input / ¥2.4 output per M tokens（比 35B 自建贵 5-10x），1M context window。

---

### Session
- **固定 session**: `ccr-work`（始终使用，不跟随其他 session）
- **启动 Claude Code**: `tmux attach-session -t ccr-work && ccr`
  - **必须用 `ccr`**，不能直接 `claude` —— `ccr` 加载 router 配置（model=Qwen3.6-35B），直接 `claude` 没有 router 会报 model 错误
  - `ccr` = `/home/claw/.npm-global/bin/ccr` → `@musistudio/claude-code-router`
- **确认状态**: `tmux list-sessions`（每次任务前确认 ccr-work 存活）

### 路由
- Router: `127.0.0.1:3456`
- 默认 provider: `remote-ai`（Qwen3.6-35B）
- 备用: `deepseek`（deepseek-v4-flash）
- 切换: `~/.claude-code-router/config.json` → `Router.default`

### 向 Claude Code 可靠通信机制

**问题**: `tmux send-keys` 注入 TTY 层，交互式 prompt（安全确认、yes/no）会抢先捕获输入，导致命令被 shell 消费。

**方案**: `~/.openclaw/workspace/skills/claude-cmd/claude-cmd-supervisor.py`
- 发指令前检测交互式 prompt（trust_prompt / yes_no / interactive / cancelled / shell）
- 自动处理 prompt 后再发命令
- 用 ACK 确认命令被 Claude Code TUI 消费
- 双向日志：技能文件夹 `tmp/claude-cmd.log`

**用法**:
```bash
python3 ~/.openclaw/workspace/skills/claude-cmd/claude-cmd-supervisor.py "proceed" 60
python3 ~/.openclaw/workspace/skills/claude-cmd/claude-cmd-supervisor.py "Fix the bug" 45
```

**ACK 判定**: 命令文本出现在 tmux pane 输出（非 shell 错误行）= Claude Code 已接收

**前置条件**: tmux session `ccr-work` 必须存在且运行的是 `ccr code` 启动的 Claude Code，用 `tmux list-sessions \| grep ccr-work` 确认

---

## Claude Code Skills / Plugins（2026-06-14 装）

### 已装清单（user scope）

| Plugin | 来源 | **SKILL 真名** (SKILL.md frontmatter `name:`) | 干啥 |
|---|---|---|---|
| `frontend-design@claude-plugins-official` | Anthropic 官方 | **`frontend-design`** (同名) | 反 AI slop，强制 BOLD 美学方向 |
| `react-best-practices@vercel-agent-skills` | Vercel 官方 | **`vercel-react-best-practices`** (带前缀!) | React/Next.js 性能优化 70 条规则 (8 类别) |

### ⚠️ Skill invocation 铁律 (L-2026-06-14-04 14:07 验证)

**plugin 名 ≠ skill 名**。Vercel 命名规范: `vercel-react-best-practices` (skill 真名带前缀)。
- 错用法 (R6.1+R6.2 报 Unknown): `Use the react-best-practices skill to ...` (plugin 名)
- 对用法 (L-04 验证 OK): `Skill(skill: "vercel-react-best-practices")` (colon form / skill 真名)
- 对用法 (frontend-design 同名直接 OK): `Skill(skill: "frontend-design")`

### 3 种 invocation 格式实测 (L-04 排查 14:04-14:07)

| 格式 | 触发? | 结果 |
|------|-------|------|
| 自然语言 `Use the X skill to ...` | ❌ | system 不自动 invoke, 走训练数据 |
| `load the X skill` | ❌ | 同上, 无 tool 调度 |
| **`Skill(skill: "<SKILL.md frontmatter name>")`** | ✅ | colon form / 同名 都行, 必返 skill 内容 |
| 描述触发 `apply the X principles` | ❌ | 无 tool, CC 拼训练数据 (弱) |

### 装新 skill 后必走 (3 步)

1. 读 `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` 找 `SKILL.md` 的 frontmatter `name:` 字段 → 这是 skill 真名
2. 重启 ccr-work session (kill + 重 attach + ccr)
3. 第一个 prompt 试 `Skill(skill: "<真名>")` 验证

### 触发模板 (修后)

```text
# 错（plugin 名）:
Use the react-best-practices skill to refactor [代码/组件].

# 对（skill 真名）:
Skill(skill: "vercel-react-best-practices") — refactor [代码/组件] with 70 React/Next.js 性能规则.
```

### Vercel 70 规则 8 类别 (适用 Vite+React18 SPA 的: client-/rerender-/js- 部分)

| 类别 | 前缀 | 条数 | 影响 | 适用 M2 R6? |
|------|------|------|------|------------|
| Eliminating Waterfalls | async- | 6 | CRITICAL | 部分 (RQ 已 dedup) |
| Bundle Size | bundle- | 6 | CRITICAL | 部分 (tree-shake) |
| Server-Side | server- | 10 | HIGH | ❌ 无 Next.js |
| Client-Side Data Fetching | client- | 4 | MED-HIGH | ✅ (RQ dedup) |
| **Re-render Optimization** | **rerender-** | **15** | MED | **✅ R6.3+ apply** |
| Rendering Performance | rendering- | 11 | MED | ✅ (memo) |
| JavaScript Performance | js- | 14 | LOW-MED | ✅ (filter/slice) |
| Advanced Patterns | advanced- | 4 | LOW | 部分 |

### Bonus (R6.3+ rerender- 候选)

- **rerender-defer-reads**: `isFetching` 触发整表 re-render → useRef 或 query select callback
- CandidatesPanel 90 行 table, refetch 时整表 re-render (invisible at 0 rows, visible at scale)

### 自建 Marketplace：`vercel-agent-skills`

- **原因**：`vercel-labs/agent-skills` 是 monorepo，根目录没 `.claude-plugin/marketplace.json`，不能直接 `marketplace add`
- **方案**：手动 `git clone` + 写包装 `marketplace.json` + 注册到 `known_marketplaces.json`
- **位置**：`/home/claw/.claude/plugins/marketplaces/vercel-agent-skills/`
- **manifest 路径**：`.claude-plugin/marketplace.json`
- **已声明 plugins**（只装了第 1 个）：
  - `react-best-practices` ✅
  - `web-design-guidelines` ⏳
  - `composition-patterns` ⏳

**维护操作**：
```bash
# 拉取最新
cd /home/claw/.claude/plugins/marketplaces/vercel-agent-skills && git pull

# 装备胎
claude plugin install web-design-guidelines@vercel-agent-skills
claude plugin install composition-patterns@vercel-agent-skills
```

### 装新 skill 的标准流程

```bash
# 1. 查 marketplace
claude plugin marketplace list

# 2. 装（标准 marketplace）
claude plugin install <name>@<marketplace>

# 3. 装（非标准仓库）
#    手动 git clone + 写 marketplace.json + 注册到 known_marketplaces.json

# 4. 重启 Claude Code（必须）
tmux kill-session -t ccr-work
tmux new-session -d -s ccr-work -c ~/.openclaw/workspace
tmux send-keys -t ccr-work 'ccr' Enter
```

---

## ⚡ AI 服务配置

### 远程 AI 服务器（192.168.40.2:6060）
- **模型**: `Qwen3.6-35B-A3B-Q8`
- **用途**: 主用推理服务，~95 tok/s
- **Cron 任务默认用此模型**

### 本地 Llama Server（127.0.0.1:8080）
- **二进制**: `/home/claw/llama.cpp/build-vulkan/bin/llama-server`
- **模型**: `/home/claw/models/Qwen3.5-9B-Q4_0.gguf`（Qwen3.5 9B Q4_0，MTP 架构）
- **API**: `http://127.0.0.1:8080/v1/chat/completions`
- **启动参数**:
  ```bash
  nohup /home/claw/llama.cpp/build-vulkan/bin/llama-server \
    -m /home/claw/models/Qwen3.5-9B-Q4_0.gguf \
    --host 127.0.0.1 --port 8080 \
    -np 2 -ngl 99 \
    -c 2048 \
    --rope-scaling yarn --rope-scale 1.0 \
    --yarn-orig-ctx 262144 \
    --override-kv qwen35.context_length=int:8192 \
    --spec-type draft-mtp \
    --spec-draft-n-max 2 \
    --chat-template-kwargs '{"enable_thinking":false}' \
    --no-warmup > /tmp/llama-server-vulkan.log 2>&1 &
  ```
- **性能**: ~19-24 tok/s，MTP 接受率 83%，GTT 占用 6.44/7.47 GB
- **定位**: cron 任务、文件处理、总结、代码审查等轻量任务

### 内存架构（AMD Phoenix3 APU）
- VRAM aperture: 512 MB（驱动+shader）
- GTT（RAM 映射）: 7.47 GB（llama.cpp Vulkan 使用此区域）
- GTT 接近上限时会 OOM，监控 `cat /sys/devices/pci0000:00/0000:00:08.1/0000:05:00.0/mem_info_gtt_used`

### 连接方式
```bash
tmux attach-session -t ccr-work
claude
```

### 常用命令
在 Claude Code TUI 里直接输入自然语言，例如：
```
audit /path/to/file
fix /path/to/file
review /path/to/file
```

### 路由
- Router: `127.0.0.1:3456`
- 默认 provider: `remote-ai`（Qwen3.6-35B）
- 备用: `deepseek`（deepseek-v4-flash）
- 切换: `~/.claude-code-router/config.json` → `Router.default`
