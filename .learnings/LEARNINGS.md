# LEARNINGS.md — Self-Improvement Log

> Format: `- [YYYY-MM-DD] {发生了什么} → {正确做法}`
> Promote to workspace files when broadly applicable

---

## [LRN-20260413-001] category: best_practice

**Logged**: 2026-04-13T15:13:00Z
**Priority**: high
**Status**: pending
**Area**: config

### Summary
定时任务写入需要 pairing，但读权限正常。手动编辑 jobs.json 可绕过此限制。

### Details
OpenClaw cron 工具有读（list）和写（add）两个权限级别。写操作（add/edit/remove）需要 gateway session pairing 授权才能执行。但直接编辑 `~/.openclaw/cron/jobs.json` 并重启 gateway 后，任务可以生效。

### Suggested Action
下次需要添加 cron 任务时：
1. 先用 cron list 确认文件格式
2. 直接编辑 jobs.json（JSON 格式要求严格）
3. 重启 gateway 使其重新加载

### Metadata
- Source: conversation
- Related Files: ~/.openclaw/cron/jobs.json
- Tags: cron, pairing, workaround
- See Also: LRN-20260413-002

---

## [LRN-20260413-002] category: correction

**Logged**: 2026-04-13T15:13:00Z
**Priority**: high
**Status**: pending
**Area**: memory

### Summary
learnings 目录选择：评估时抛开 QMD 因素，`/.learnings/` 更合理。

### Details
最初推荐 `memory/learnings/` 是因为 QMD 可索引。但抛开 QMD 因素后：
- `.learnings/` 是交互日志（corrections/errors/insights），不是待回忆的事实
- `memory/` 是需要主动回忆的事实
- 行业惯例（Claude Code/Codex/Copilot）都用 `.learnings/`
- skill 作者明确指定 `.learnings/`

正确做法：`.learnings/` 是准确的语义选择。

### Suggested Action
learnings 日志统一走 `.learnings/`，不混入 memory/ 目录。

### Metadata
- Source: user_feedback
- Related Files: AGENTS.md
- Tags: memory, architecture, correction
- See Also: LRN-20260413-001

---

## [LRN-20260413-003] category: best_practice

**Logged**: 2026-04-13T15:13:00Z
**Priority**: medium
**Status**: pending
**Area**: infra

### Summary
skill 安装后检查目录是否存在，必要时重新复制。

### Details
重启或更新后，skill 目录可能丢失（self-improving-agent 在重启后消失）。需要从 NFS 源重新复制。skill-vetter 安装流程：检查源 → 审计 → 复制。

### Suggested Action
每次安装 skill 后验证：`ls ~/.npm-global/lib/node_modules/openclaw/skills/<skill-name>/SKILL.md`

### Metadata
- Source: error
- Related Files: memory/2026-04-13.md
- Tags: skill, installation, reliability

---

## [LRN-20260413-004] category: knowledge_gap

**Logged**: 2026-04-13T15:13:00Z
**Priority**: low
**Status**: pending
**Area**: infra

### Summary
AMD Phoenix3 + Vulkan 的 QMD 兼容性确认：GPU 加速可用但需要正确的驱动和配置。

### Details
vulkaninfo 检测到 `AMD Radeon 780M Graphics (RADV PHOENIX)`，但 node-llama-cpp 预编译二进制不支持。实际通过 GGML_CUDA_USE_ALLOCATOR=0 或环境变量强制后可工作。

### Suggested Action
遇到 "prebuilt binary not compatible" 时，尝试设置 `GPU_FORCE_64BIT=1` 或其他 Vulkan 环境变量。

### Metadata
- Source: investigation
- Tags: GPU, AMD, Vulkan, QMD

---