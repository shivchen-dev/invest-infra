# LEARNINGS — 模式教训

## 2026-06-14 11:58 — Gitee push 失败根因（重要）

**事件**：push 401 → 我错误推断 token 失效 → 用户纠正"一直在 push"

**根因**：
- TOOLS.md 写过时信息（"GITEE_TOKEN env 注入"）
- 我用 `git -c credential.helper=` 强制**绕过** git store helper
- 真实凭据在 `~/.git-credentials`（store mode 自动 cache），不是 `secrets/gitee-token`

**正确做法**：
- `git push -u origin main`（不加 `-c credential.helper=`）→ 自动用 store cache
- 排查顺序：git config helper → ~/.git-credentials → store cache 内容 → 才是 Gitee 端

**推广**：
- 任何 git 操作前先 `git config --global credential.helper` 查
- store/cache/manager helper 存在时，**不要手动 set env var**
- TOOLS.md 是会过时的；遇到 401 不要 jump to "token 失效"

## 2026-06-14 13:25 — ETF API token secret 长度错位 (32 hex vs 64 hex)

**事件**：R3.1a middleware/auth.ts 启动 throw "must be 32 hex chars"
**根因**：findings.md §1.2 写"32 hex"，但 `.secrets/etf_api_token_secret` 实际是 64 hex (32 字节 = 256 bits SHA-256 输出)
**正确做法**：
- 写 spec 前先 `wc -c` + `cat` 实际文件
- 启动 throw 时 `cat -A` 看真实字节（含/不含 newline）
- length 字段应在 doc 标 "32 bytes" 而非 "32 hex"
**推广**：任何"X hex"长度声明 → 先 hexdump 看实际

## 2026-06-14 13:36 — Spec 表名假设错位 2.0 (etf_spot 不存在)

**事件**：R4.1 etf_screener.py spec 假设 `etf_spot` 表存在并读 11 字段
**根因**：v0.8.3 §4.6 提到 "L1 数据采集 (现有 etf.py) fetch_etf_spot() → ..." 但没在 §4.1 列出 etf_spot DDL。`etf_spot` 表从未在 init.sql 创建 — 真存在表是 `etf_quotes` (8 字段 vs spec 11 字段)
**正确做法**：
- 任何 spec 涉及表名 → CC 必须先 `\dt <table>` 验证存在性
- CC 主动发现并改用 etf_quotes + 缺 3 列 NULL (iopv_premium_pct/ma20_pct/ma60_pct) — 文档化 R6 补
- 写 doc 时区分 "spec 引用" vs "DB 实际存在" — 两层都要 grep
**推广**：
- M2 R1 阶段应已 `\dt etf*` 列出所有 ETF 相关表，对比 spec §4.1 找 gap
- R1 1.2 etf_market_data_cache 是新增表, etf_spot 不在 R1 范围 → 错位根因
- 任何 DB-backed spec, 写之前先 `\dt` 一次

## 2026-06-14 13:47 — Claude Code plugin skill 加载失败 (重要)

**事件**：M2 R6.1 + R6.2 两 prompt 都明说 "Use the react-best-practices skill" + "Use the frontend-design skill", CC 都回 "Unknown skill" 两次
**根因（待深查）**：
- TOOLS.md 写 "frontend-design@claude-plugins-official 已装" + "react-best-practices@vercel-agent-skills 已装" + "ccr-work session 已 12:08 重启生效"
- 但 CC 实际回 "Unknown skill" — skill 列表显示这 2 个都在, 但 Skill tool 调用识别不出
- 候选根因: (a) plugin 装到 user scope 但 CC 进程没读, (b) ccr router 拦截了 Skill tool 转发, (c) Skill tool 的 skill name 需 plugin 真实注册名 (不是 marketplace 名), (d) ccr-work 用的不是重启后的进程

**正确做法**：
- 先 `tmux list-sessions` + `tmux capture-pane` 看 ccr-work 是不是真的重启过
- 试 `claude plugin list` 看 plugin 真实状态
- 试 `claude /help` 看 Skill tool 是否暴露
- 试不同的 invocation 格式: 直接说 "apply the frontend-design principles" 而不期望 tool 调

**推广**：
- "Use the X skill" 不是银弹 — CC 看到也会说 Unknown
- 原则手用可行 (CC 会 fallback), 但 skill 设计哲学 (BOLD 美学 / 40+ React 规则) 不会自动激活
- 任何装 plugin 后必须 (a) 重启 session (b) 实际调一次 tool 验证 (c) 失败立刻报告不要 fallback 假装

**影响**:
- M2 R6 表面 OK (4/4 RAA checkpoint PASS), 但 skill 设计哲学未生效
- CandidatesPanel 的 "BOLD distinctive aesthetic" 没真正用上 frontend-design 哲学
- React 性能 40+ 规则未系统应用, CC 手用 4 条

## 2026-06-14 14:07 — L-04 解决: Skill tool 真名 = colon form (display:invocation)

**根因（已验证）**:
- `~/.claude/plugins/installed_plugins.json` 注册的是 **PLUGIN** 名（如 `react-best-practices@vercel-agent-skills`）
- 但 Skill tool 实际找的是 **SKILL** 名（在 plugin 内 `SKILL.md` frontmatter `name:` 字段）
- `react-best-practices` plugin 内的 `SKILL.md` frontmatter 写 `name: vercel-react-best-practices` (Vercel 的命名规范)
- system reminder 的 `react-best-practices:vercel-react-best-practices` 就是 `display-name:invocation-name` 命名空间

**CC 报 "Unknown skill" 的真因**:
- 我 prompt 里写 "Use the react-best-practices skill to ..." — 这是 plugin 名
- Skill tool 找的是 `react-best-practices` 这个 skill, 找不到 (因为真名是 `vercel-react-best-practices`)
- 返 "Unknown skill"

**Frontend-design 不出问题因为同名**:
- `frontend-design@claude-plugins-official` plugin → SKILL.md `name: frontend-design`
- 同名 → `Skill(skill: "frontend-design")` 直接 OK
- 但 R6.2 第一次也报 Unknown (CC 报 R6.1 fail, R6.2 OK) — 可能是 Skill tool 本身的 flaky 行为, 也可能是 cache warmup 时机

**正确用法**（fix L-04）:
- 自然语言 "Use the X skill to ..." 永远不触发 tool (system 不自动)
- "load the X skill" 永远不触发 tool
- `Skill(skill: "display-name")` 可能 OK 如果同名, 否则 Unknown
- **`Skill(skill: "vercel-react-best-practices")` colon form 必 OK** (含 - 前缀的真名)
- 描述触发 "apply the X principles" 不触发 tool, CC 只能从训练数据拼 (弱)

**验证结果** (L-04 排查 14:07):
- `Skill(skill: "react-best-practices")` → ❌ Unknown (R6.1+R6.2 都这样)
- `Skill(skill: "vercel-react-best-practices")` → ✅ Loaded with full 70 rules
- 内容验证: 8 类别 (async-/bundle-/server-/client-/rerender-/rendering-/js-/advanced-)
- 6+6+10+4+15+11+14+4 = 70 条, 匹配 skill header 声明

**Bonus 发现 (R6.3+ 候选)**:
- CandidatesPanel `isFetching` 触发整表 re-render — 应 apply **rerender-defer-reads** 规则
- Vite+React18 SPA 适用规则集中在 client-* (4) / rerender-* (15) / 部分 js-*
- server-* (10) 不适用 (没 Next.js)
- 修复: useRef 或 query select callback 让 isFetching 只触发 filter row re-render, 不触发 90 行 table

**推广 (TOOLS.md 待更新)**:
- 任何 plugin 安装后, 先读 plugin 目录下的 `SKILL.md` frontmatter `name:` 字段
- 用 `Skill(skill: "<name from frontmatter>")` 调用, 不用 plugin 名
- 如果 plugin 名和 skill 名一致 (像 frontend-design), 直接用 plugin 名也 OK
- 如果不一致, 必用 SKILL.md 里的 name (可能带前缀如 vercel-)

---

## [2026-06-15] 复杂项目方案设计第一步 = 问终点

**发生了什么：**
用户 10:39 问"能把国海的功能加到我们的系统吗"，10:44 决定"要国海全部 11 模块"。我 10:44 写了 v1 plan，把"网格管理"打成 P2 "不该做" — 理由是"跟我们长线定位冲突"。
11:09 用户澄清："这个可视化是为网格交易做准备的"。
**v1 整个方向错了。** 11 模块在网格交易准备语境下全部合理，"网格" 应该是 P0 而非 P2。

**根因：**
没问"这个 dashboard 的终点是什么"，先入为主假设 = 长线监控。**plan v1 的所有优先级排序基于错误前提。**

**正确做法：**
1. 任何方案设计前，先问"这个系统的终点/目的是什么"（end-goal question）
2. 没问到 end-goal 之前，**不要**排模块优先级、不要判断"该不该做"
3. 模糊请求（"把 X 加到 Y"）必须先解构：X 是什么 / Y 的目标 / 两者如何映射
4. **新规则：** complex project → 第一个问题 = "这个系统/项目最终要服务于什么"（决策/执行/监控/学习/其他）

**推广：**
- AGENTS.md 待加"复杂项目先问 end-goal"规则
- TOOLS.md "决策协议"章节引用此条

---

## [2026-06-15 v2] 复杂项目问"终点"不够 — 要问"end-to-end 完整流程"

**承上文：** v1 没问终点，v2 问到了"网格交易"终点（用户 11:09 澄清），但 v2 仍然不完整。

**发生了什么：**
11:09 用户说"这个可视化是为网格交易准备的" → 我把焦点放在中游（交易/网格），写了 v2 plan。
11:15 用户说"我们的系统要从选股到交易到复盘统计都有，投研系统本身就是为选股建立的" → **v2 整个焦点错了**。
v2 仍只关注"网格交易"，但用户实际想要的是**完整闭环**：选股→交易→复盘→反馈。
v2 缺了上游（选股 = 我们的强项）和闭环（反馈通道）这两段。

**根因：**
v2 我只问了"终点"（网格交易），没问**"end-to-end 完整流程"**。"终点"是 1 个点，"完整流程"是 N 段链。

**正确做法：**
1. 第一个问题 = "**这个系统/项目的 end-to-end 完整流程是什么？**"（不是"终点是什么"）
2. 第二个问题 = "每段的输入输出是什么？上下游依赖？"
3. 第三个问题 = "哪些段是强项 / 弱项 / 对齐对象 / 自建？"
4. 第四个问题 = "闭环反馈机制是什么？"（如果适用）

**对照：**
- v1: 0 个问题 → 完全错
- v2: 问了"终点" → 部分对
- v3: 问"end-to-end 完整流程" → 对

**推广：**
AGENTS.md 加规则："复杂项目方案设计：第 1 问 = end-to-end 完整流程；第 2 问 = 每段 I/O；第 3 问 = 强项/弱项/对齐；第 4 问 = 闭环反馈（如适用）"

## [2026-06-15] Claude Code 会话预算纪律（Round 1.1 复盘立）

**教训：** 投研项目小改动走 CC = 浪费会话预算
- 实测：Round 1.1 (4 步共 ~30 行改动) 用 CC = 10+ 分钟 + 2 次 1m+ compaction
- 净效果：CC 只写了 SQL 文件，**实际 ALTER 是我手动跑的**，CC 完全 overhead
- 触发："注意 Claude Code的会话上限"（用户 15:29 GMT+8）

**铁律：**
- ✅ **≤10 行 / 1 文件 / 改动明确** → **Arc 直执行**（py_compile/build 验证）
- ✅ **≥40 行 / 跨文件 / 设计决策** → CC + `--print --permission-mode bypassPermissions`
- ✅ **需要"读 + 报告" 不改文件** → CC audit 模式
- ❌ **不要**为用 CC 而用 CC（"分工"不是教条）
- ❌ **不要**在 CC session cwd 错时硬塞（先 cd /home/claw/invest-infra 再发）
- ❌ **不要**让 CC 自己"comprehend 后再决定"（要明示路径/文件/期望产出）

**反例（2026-06-15 Round 1.1）：**
- 4 个原子步骤都 ≤10 行，本应 Arc 直做 5min 完事
- 走 CC 路径：supervisor timeout + tmux send-keys + 1m+ compaction × 2
- 浪费 ~10min session budget + 0 净产出

**正确流程（修订）：**
1. 读 task_plan.md 估改动量
2. 改动 ≤10 行 → Arc edit tool + py_compile/build 验证
3. 改动 ≥40 行 → 1 个 atomic prompt 给 CC（明示 cwd + 文件 + 期望输出）
4. 1 个 prompt 跑 60s 无首行输出 → kill，Arc 接手

## [2026-06-15] skill_workshop apply 流程坑

**坑:** apply 拒绝覆盖目标文件（即使文件已存在）
- 错误: `Target support file already exists: .../status.sh`
- 原因: skill_workshop 设计为"clean install"，不是"sync update"

**正确流程:**
1. `mv <target>/scripts /tmp/<skill>-scripts.bak` 暂存现有脚本
2. `skill_workshop apply <id>` (SKILL.md + 脚本全量复制)
3. 从 backup 恢复比 PROPOSAL 新的脚本（如 cwd_fix.sh 16:10 更新版）
4. `chmod +x scripts/*.sh`（apply 会丢失执行位 → 600）
5. 验证 `bash scripts/health.sh` 能跑

**反例:** 直接 apply → 失败 → 改用 trash（未装）→ 失败 → 改用 mv 成功

## [2026-06-15] 修订 CC 预算规则（用户 16:34 反馈）

**教训:** Round 1.3 我用"省 CC 预算"借口越界，150+ 行 PreMarketPanel.tsx 全 Arc 直做。
**后果:** clean-code 自检出 MessageCard 30 行 + PreMarketPanel 95 行超 20 行上限 — 用户 16:34 提醒"代码还会审计"。

**修订规则:**

| 改动量 | 路径 | 原因 |
|--------|------|------|
| ≤10 行 / 1 文件 | Arc 直做 + py_compile/build 验证 | 0 双检成本 |
| 11-40 行 / 1 文件 | **CC audit 模式**（读 + 报告 + 改建议） | 双检成本低 |
| ≥40 行 / 跨文件 | **CC 实施 + 强制 clean-code 自检** | 实施 + 双检 |

**反例（2026-06-15 Round 1.3）:**
- PreMarketPanel.tsx 157 行 → 应该 CC 实施或至少 CC audit
- 我直做了 → 2 处违规（MessageCard 30 / PreMarketPanel 95）→ 用户指出

**修正:** 任意代码改动前先估算行数。>10 行必走 CC 路径。

## [2026-06-16] Smoke test 必须用真实 cron 数据（不能 mock）

**事件:** Phase 1.5 v1.5-d D.1.1 commit `91d54ef` 跑通 smoke test（mock 5 行：510300/510500/159618/159819/512690），用户拍板通过。但 D.6 commit `25053d7` 跑真实 cron 验证时**才发现**：FK `etf_candidate_pool.code → etf_portfolio.code` 阻塞真 cron 输出的 `159033`（不在 14 fixed portfolio 里）。FK 反向的设计错位隐藏 9 小时（06-15 22:38 D.1.1 → 06-16 07:04 D.6 跑真 cron 才发现）。

**根因:** Smoke test 用 mock 数据，**全在** 14 fixed portfolio 里。FK 引用方向"候选池 code 必须先在持仓"看似合理（mock 都满足），但真 cron 输出 14 fixed 之外的 ETF 时 FK 必然失败。

**正确做法:**
- Smoke test 至少 1 case 包含**预生产 / 历史 cron 真实输出** 1-2 行（包含持仓外 code）
- 数据 schema 改动（D.1.1 / D.2 / D.3）后，**第一次跑 DDL 必跑真 cron 验证**（不是 mock UPSERT）
- 任何 FK / CHECK / UNIQUE 约束，验证 case 必须包含**"会触发约束的边界数据"**——不是 happy path

**推广 (P0 铁律立):**
- 复杂项目 DDL 验证 = mock 1 次 + 真实 cron 输出 1 次（双轨）
- 任何"先有数据才能约束"的设计 → 业务流必须支持"先有数据"——FK 方向不能反
- smoke test 通过 ≠ 生产环境 OK（业务边界外数据才能暴露设计错位）

**D.6 抓到的额外 bug:** FK 反向（候选池→持仓），v1.5-d 业务主轴是候选池（cron 21:00 输出）→ 用户手动 join → 持仓。修复: `ALTER TABLE etf_candidate_pool DROP CONSTRAINT etf_candidate_pool_code_fkey;` (commit `d518fc9`)

**D.6.x watchdog gap:** `etf_candidate_pool_freshness` watchdog 条目是声明式，但 watchdog 实际读 `/tmp/cron_exec_status.json`（cron_dispatcher 写）。cron_dispatcher 没写对应 key，watchdog 运行时不会真监控。修复（**D.8.x 后续做**）：watchdog 改 PG 直读 etf_candidate_pool 表（解耦 + 准确）。

## [2026-06-16] 复杂项目方案 v1.5-a → c2 → d 演进：业务主轴先于技术设计

**事件:** v1.5-d 决策 00:44 之前 1.5 演进 3 个版本（a → c2 → d），均 0 持久。

- **v1.5-a (22:30)**：「信号 → 候选池」联动。CC 调研发现 14 portfolio ETF 跟 3 天 9 数据源 0/14 覆盖 → 撤销。
- **v1.5-c2 (23:32)**：「持仓 → 报告」反向联动。CC 实施前 RAA BLOCKING F-1: 90 天 + 9 字段 union = 仍 0 命中。
- **v1.5-d (00:44, 现行)**：「候选池链路打通」= 候选池 (cron 输出) → 用户手动 join → 持仓 → 监控。**用户 00:39 业务逻辑澄清**：「候选池通过汇报模块得出标的股，然后通过用户加入到持仓监控，进行进一步分析以及一个长时间监控」。

**根因（a + c2 同源）:**
- 我先入为主假设"v3 决策 0 闭环需要自动化联动"——技术上对，但**业务主轴**反了
- 业务上"持仓"是用户决策固化，"候选池"是投研 cron 输出——两者是松耦合单向关系（候选池 → 持仓），不是双向同步
- 自动化联动（v1.5-a 信号→池 / v1.5-c2 池→持仓）破坏"用户手动 join"的业务语义

**正确做法（业务主轴先于技术设计）:**
1. 复杂项目方案设计**第一步** = 复述业务主轴给用户确认（"我理解是 A → B → C，对吗？"）
2. 任何"联动 / 同步 / 自动"设计，**先**问：业务上"手动"还是"自动"是用户期望？
3. 调研数据源**优先于**技术方案（v1.5-a 调研发现 0/14 覆盖 → 撤销；v1.5-c2 RAA 0 命中 → 撤销）
4. 用户主动澄清业务主轴 = 立即停技术实施，重做方向（v1.5-d 是 00:39 业务澄清后 5 分钟内拍板）

**v1.5-c2 浪费的 4 commit + 2 doc:** P0 教训学费——但 4 commit (R1.5.1 SQL / R1.5.2 /content 路由 / Bug-A 修 _extract_auction_candidates / Bug-B 回填 3 天 strongest) 都是 P0 修复（不动）。2 doc 标"⚠️ 已被 v1.5-d 取代" + 教训保留。

**推广 (P0 铁律立):**
- AGENTS.md 决策协议加规则："联动设计前必先确认业务主轴方向"
- 任何"自动同步"的设计诱惑 → 停下来问"用户期望手动还是自动？"
- 调研数据源覆盖度（0/N 命中）→ 优先于实施

**v1.5-d 决策 (00:44):** 候选池（cron 21:00 真写 top 20，D.1.1）→ 用户手动 join (D.5 按钮) → 持仓（D.4 source='candidate_pool' 标记）→ 监控（Review Dashboard 4 卡片 R2.1 已有）→ 复盘 → 反馈。**8 commit 全部到位**: D.1.1 + D.2 + D.3 + D.4 + D.5 + D.6 + D.6.x FK fix + D.7。

## [2026-06-16] CC commit 阶段处理 pre-existing M 文件：用文件级别 stage，不要 git checkout HEAD --

**事件:** D.7 commit 阶段，git status 显示 8 个 pre-existing M 文件（来自 Phase 1 选股 Dashboard 收尾未 commit）。CC 走 3 步绕路：
1. CC 自报 D.7 改动 +153 行超 ≤40 budget
2. CC 看到 8 M 文件后，误用 `git checkout HEAD -- 3 files` 试图"清空 worktree 重做"——**把 CandidatesPanel.tsx D.7 改动丢了**
3. 后续恢复 `/tmp/hooks.preserve.ts` + `/tmp/etfApi.preserve.ts` 备份，重新写 CandidatesPanel.tsx D.7，拆 2 commit（A=R2.1 frontend 收尾 13 文件 / B=D.7 3 文件）完成
4. 总耗时 ~2h，比预期 30 min 多 3 倍

**根因:**
- CC 在 commit 阶段遇到"git status 多个 M 文件"时倾向于"全 revert 再 apply"——但 revert 会丢失刚改的代码
- 我（Arc）给 CC 的"拆 2 commit"指令是文件级别（"CandidatesPanel 进 D.7，其他进 R2.1"），CC 误解为"行级别 patch stage"，跑去 revert
- `/tmp/` 备份只覆盖 2 文件，没覆盖 CandidatesPanel.tsx（CC 自报 D.7 only clean 时没备份）

**正确做法（CC commit 阶段铁律）:**
1. **不要** `git checkout HEAD -- <files>`——会丢失当前 worktree 改动
2. **不要** `git stash` 整个 worktree 再 apply——粒度太粗
3. **用** `git add <files>` 文件级别 stage + 拆多 commit（每个 commit 1 个 feature）
4. 如果必须 revert 部分行 → 用 `git restore --staged <file>` + manual edit + 重新 add，**不**用 checkout HEAD
5. 备份到 `/tmp/` 之前必须 `cp <file> /tmp/<file>.preserve.<feature>` 全备份（含所有相关文件，**不**只 2 个）

**Arc 给 CC 指令的措辞（修订）:**
- ❌ 错："用 patch stage 把 D.7 hunks 拆出来"（CC 误解为 git checkout HEAD）
- ✅ 对："git add 这 3 个文件进 D.7 commit，其他 6 文件进 R2.1 commit，文件级别拆就够，不需要 patch stage"
- ✅ 强调："**不要** git checkout HEAD / git stash / patch stage，文件级别 stage 即可"

**推广 (P0 铁律立):**
- AGENTS.md 加规则："CC commit 阶段处理 pre-existing M 文件 = 文件级别 add + 拆多 commit，禁止 git checkout HEAD / git stash / patch stage"
- 任何"清空 worktree 重做"的 CC 倾向 → 立即 STOP 并给文件级别指令
- `/tmp/` 备份要全，**不**只 2 文件（missing 1 个 = 1h 浪费）

**D.7 实际收尾（commit 链 03c8e89 + dffadd4）:**
- `03c8e89` fix(frontend): R2.1 frontend 收尾 · Review tab + 4 chart + 2 common helper (13 files)
- `dffadd4` feat(frontend): CandidatesPanel cron 新鲜度条 (Phase 1.5 v1.5-d D.7) (3 files, 144 lines)
- CandidatesPanel.tsx +30 / useEtfQueries.ts +13 / etfApi.ts +9 = 52 lines 净增（含 R2.1 hooks/fetches 共享）
- cron-status 端点验证: top_count=20, hours_since=0.06, status=ok → 绿色 success 档

## [2026-06-16] v1.5-d 闭环落地：上游+中游+入口+监控+反馈

**业务价值复盘（v1.5-d 8 commit）:**
```
候选池 (cron 21:00 真写 top 20, D.1.1)              ← 上游（投研 cron）
   ↓ 用户手动 join (D.5 按钮 + 二次确认)            ← 中游（用户决策）
持仓 (D.3 source 字段 + D.4 自动 source 标记)      ← 入口（D.4 source='candidate_pool'）
   ↓ Review Dashboard 4 卡片 (R2.1 已有)            ← 监控（已就绪）
复盘 (D.8+ 后续)                                    ← 下游（v1.5-d 不做）
   ↓ 反馈 (Phase 1.6, 不在本 Phase)                 ← 反馈（闭环通道）
```

**闭环主轴命中:**
- v3 决策 0 「完整闭环」= 选股（投研）→ 交易（网格）→ 复盘（KPI/净值/风险）→ 反馈（调权重）
- v1.5-d 落地了**上游 + 中游 + 入口**——网格（中游执行）和复盘（下游）和反馈（P1）都是后续 Phase
- D.1.1 cron 真 UPSERT + D.5 按钮 + D.4 source 标记 = **核心数据流贯通**

**未做 (D.8 留作 v1.5-d.1 后续):**
- D.4 savePortfolio camelCase/snake_case type 不一致 (costPrice vs cost_price)
- D.6.x watchdog 声明式 gap (改 PG 直读)
- D.8 收尾（progress.md 更新 + commit）

**8 commit 时间线 (06-15 22:38 → 06-16 07:30, ~9h):**
- 22:38 v1.5 启动 → 23:32 v1.5-c2 反转 → 23:59 RAA BLOCKING F-1 → 00:39 业务主轴澄清 → 00:44 v1.5-d 决策
- 01:09 D.1.1 + 01:14 阈值修订 (RAA 方案 A) → 01:48 D.3 + D.4
- 06:42 D.2 → 06:48 D.5 → 07:07 D.6 + D.6.x FK fix → 07:30 D.7 + R2.1 收尾

**业务闭环完成度:** 60-70%（上游 + 中游 + 入口 + 监控就绪，**交易执行 + 复盘 + 反馈** 待 Phase 1.6+）

