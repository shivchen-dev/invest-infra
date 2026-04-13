# memory/glossary/arc-terms.md

## Arc 核心术语

### Arc
- 正式名，技术负责人 Agent
- 小A：用户对 Arc 的称呼
- 来源：Architecture（结构、路径、连接点）
- 上线：2026-04-13

### 热缓存（Hot Cache）
- 定义：MEMORY.md，~50 行结构化表格
- 用途：每轮会话快速加载，解码身份和上下文
- 覆盖：90% 日常场景

### 深度存储（Deep Storage）
- 定义：memory/ 目录，分层分类
- 子目录：people/ projects/ glossary/ knowledge/ daily/ context/
- 用途：完整历史、细节检索

### 确定性查找（Path A）
- 已知实体逐层定位：热缓存 → 术语表 → 档案目录
- 特点：快、确定、零外部依赖

### 语义搜索（Path B）
- embedding 模糊回忆
- 特点：跨文件关联，支持措辞变化
- 适用：复杂/模糊查询

### 程序职员（Clerk）
- 定期扫描日志，提取知识生成提案
- 人工审核后才写入记忆
- 质量优先于便利

### 原子事实链（Atomic Fact Chain）
- 实体历史追踪：新事实 supersedes 旧事实
- 不删除，只标记
- 效果：时序知识图谱，小规模简化实现

### 自动晋升/降级
- 晋升条件：同一条目一周内使用 ≥3 次
- 降级条件：30 天未使用
- 结果：热缓存保持精简

## 外部术语

### OpenClaw Memory Architecture
- 来源：github.com/blessonism/openclaw-memory-architecture
- 描述：双层记忆系统方案，解决 Agent 跨 session 失忆
- 用户意图：2026-04-13 决定采用此方案
