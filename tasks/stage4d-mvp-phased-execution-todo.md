# Stage 4D MVP 分阶段执行 Todo

> 计划：`docs/plan/invest-infra-stage4d-mvp-phased-execution-plan-v1.0.md`
> 状态规则：`[ ]` 未开始，`[~]` 进行中，`[x]` 完成，`[!]` 阻塞。
> 当前状态：Stage 3.4 Research Case 创建/关联已完成；JiuwenSwarm 联动尚未开始。

## 阶段 0：合同与现场前置验证

- [ ] 0.1 冻结治理边界和 ADR
- [ ] 0.2 冻结 Candidate Intake → ExternalObservation 准入合同
- [ ] 0.3 验收真实 WorkBuddy 2.0.0 样本
- [ ] 0.4 验收真实 legacy 1.1.x 三件套样本
- [ ] 0.5 验证 Windows/Linux 路径、权限和原子写入

### Gate 0

- [ ] 合同和 ADR 冻结
- [ ] 真实样本与共享目录验收有可复现记录
- [ ] 阶段 1 输入/输出合同无开放歧义
- [ ] 用户批准进入阶段 1

## 阶段 1：外部候选准入闭环

- [x] 1.1 ExternalWorkflow/Artifact/Observation Domain
- [x] 1.2 Repository、UoW、SQLAlchemy Model 和 Migration（ORM、migration、三类 Repository/UoW 接入及 mock 回归测试已完成）
- [x] 1.3 Artifact Bridge 与安全导入（归档路径约束、manifest/hash 校验、稳定 UUID、幂等导入和异常拒绝已完成）
- [x] 1.4 SharedDirectoryWorkBuddyGateway 与输入适配（ready claim、归档/失败移动、2.0.0/legacy 识别和异常隔离已完成）
- [x] 1.5 Candidate Intake → PostgreSQL 外部准入投影（合法候选、symbol 状态、findings 已投影至 ExternalObservation；WorkBuddy 不进入内部 CandidatePool 计算）
- [x] 1.6 Fake WorkBuddy E2E（ready package → claim → archive → Bridge → Repository 全链路测试已完成）
- [ ] 1.7 真实 WorkBuddy 导入演示

### Gate 1：外部候选准入闭环

- [ ] 正常、partial、failed、坏批次和坏项可诊断
- [ ] 重复导入幂等且失败后可恢复
- [ ] run ID/hash 可串联原始归档、Artifact 和数据库对象
- [ ] focused tests 与现有相关测试通过
- [ ] 用户批准进入阶段 2

## 阶段 2：只读工作台 MVP

- [x] 2.1 External Workflow Query API（runs、artifacts、observations 只读查询及分页已完成）
- [x] 2.2 Opportunity Radar API（Observation 最近查询、admission 状态筛选和只读雷达接口已完成）
- [x] 2.3 Integration Health 与 Artifact Preview API（运行状态统计、逻辑 URI/hash 预览和宿主路径隔离已完成）
- [x] 2.4 OpenAPI Client 同步（OpenAPI 导出、`openapi-typescript` 生成和过期检查已完成）
- [x] 2.5 Dashboard 集成状态（健康状态、producer/intake 统计和自动刷新已接入 Dashboard）
- [x] 2.6 Opportunity Radar 页面（状态筛选、分页查询、来源/日期/观察状态只读展示已完成）
- [x] 2.7 Automation Center 页面（外部运行、producer/intake 状态和 Artifact 数量只读观测已完成）
- [x] 2.8 API/Web focused tests 与构建（现有 API focused tests、Web tests 和 production build 已通过）

### Gate 2

- [ ] run、候选、来源、artifact 和诊断可只读查看
- [ ] 状态分区和事实/外部评分视觉分层正确
- [ ] 浏览器不访问共享目录或宿主机绝对路径
- [ ] Fake WorkBuddy 页面演示通过
- [ ] 用户批准进入阶段 3

## 阶段 3：正式验证与研究闭环

- [x] 3.1 Observation Admission Domain/Application Service（验证规则、状态决策、审计元数据和持久化转换已完成）
- [x] 3.2 Admission Command API 与审计（默认关闭 feature flag、幂等键、服务端校验、状态审计已完成）
- [x] 3.3 admitted Observation → Evidence Item（新增不可变 provenance-bound EvidenceItem；仅 admitted 可转换，保留 artifact hash、准入审计和原始 payload）
- [x] 3.4 Research Case 创建/关联（支持指定 Case 关联和从 admitted Observation 自动创建 Case；包含 Case/Observation/Artifact 校验、幂等持久化和事务提交）
- [ ] 3.5 复用 JiuwenSwarm Research 路径（首个受控交接切片已完成：
  `ExternalResearchHandoffService` 仅允许“已准入外部证据 + 已持久化完整
  `EvidencePack`”创建 `jiuwenswarm-runner-v1` 的 queued `ResearchRun`，并复用
  现有 `ResearchOrchestrationService` 执行；Fake runner 后端 E2E 已通过，
  真实 runner 组合根、只入队 API 和 queued ResearchRun 后台执行器已完成；
  真实环境验收仍待完成）
- [ ] 3.6 Research Workspace External Discovery/Admission Widgets
- [ ] 3.7 Integration Timeline 与 Artifact Viewer
- [ ] 3.8 Fake Jiuwen E2E
- [ ] 3.9 真实 WorkBuddy + JiuwenSwarm 完整验收演示

### Gate 3：Stage 4D MVP

- [ ] 主链路端到端通过
- [ ] 异常矩阵全部有测试或手工证据
- [ ] 真实环境验收通过
- [ ] 全量测试无回归
- [ ] 文档、运行手册和生成客户端同步
- [ ] Stage 4D MVP 验收签字

## 独立阶段 4：受控任务发起（D6）

- [ ] WorkBuddy 外部触发能力已现场确认
- [ ] 身份、feature flag、幂等、CSRF/会话策略已冻结
- [ ] 用户单独批准 D6
- [ ] 创建任务 Command API
- [ ] 取消任务 Command API
- [ ] 参数预览、状态追踪和 WorkBuddy 深链接
- [ ] 安全、幂等和恢复测试

## 明确不在本 Todo

- Stage 4E：Investment Case / Proposal / Risk / Approval
- Stage 4F：Portfolio / OMS / Fill / Position / 实盘
- Stage 4G：T+5/T+20 / Review / 质量闭环
