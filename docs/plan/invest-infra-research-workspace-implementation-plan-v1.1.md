# invest-infra Research Cockpit 实施计划补充版 v1.1

> 状态：Plan supplement
>
> 本文件补充并修订 `invest-infra Research Workspace 实施计划方案`，不替代原计划。原计划中的 Evidence-first、Research API、Research Case、Evidence Pack 和前端只读原则继续有效。

## 1. 本次补充的结论

Research Workspace 不另起独立系统，也不把 OneBench 作为运行时依赖。

采用以下关系：

```text
OneBench
  ├── 借鉴视觉语言
  ├── 借鉴 Widget / Module / Workspace 组织方式
  ├── 参考 dnd-kit 布局实现
  ├── 参考图标、卡片和响应式设计
  └── 参考设计验收方法
          ↓ 移植与改造
invest-infra Research Cockpit
  ├── 保留 React + TypeScript + Vite
  ├── 保留 React Query + OpenAPI Client
  ├── 只消费 Research API
  ├── 由 invest-infra 控制 Evidence 和 Research 数据
  └── 面向投研语义实现专属 Widget
```

最终产品名称和定位统一为：

> invest-infra Research Cockpit：Evidence-first AI 投研驾驶舱。

## 2. OneBench 参考和复用边界

参考项目：<https://github.com/diyiwuyan/onebench>

OneBench 当前为 React 19 + Vite 项目，使用 `@dnd-kit`、Phosphor Icons、CSS 设计 Token、Module Registry 和 `workspace.json` 布局协议，仓库许可证为 MIT。

### 2.1 可以直接参考或移植

| 范围 | 处理方式 | 目标位置 |
|---|---|---|
| 色彩、字体、间距、圆角、边框、阴影 | 参考后重新定义为投研 Token | `apps/web/src/styles.css` 或 `styles/tokens.css` |
| 侧边栏、主工作区、顶部工具栏 | 适配现有 AppShell | `apps/web/src/components/AppShell.tsx` |
| 卡片、指标卡、状态 Badge、空状态 | 作为通用展示基础 | `apps/web/src/components/` |
| 12 列 Widget 网格 | 参考实现，使用 TypeScript 重写 | `apps/web/src/research-workspace/runtime/` |
| Widget 拖拽排序 | 仅在布局能力需要时引入 `@dnd-kit` | `runtime/layout/` |
| Phosphor 图标体系 | 可作为统一图标库 | `apps/web/src/components/icons/` |
| 设计验收和截图证据 | 纳入 UI 验收流程 | `docs/` 与 PR 验收记录 |

### 2.2 不直接复用

- OneBench 的 `workspace.json` 作为投研事实数据模型；
- OneBench 的生活、职业、学习、日历、天气、RSS 和新闻模块；
- OneBench 的本地连接器、GitHub 同步和个人数据同步；
- OneBench 的整套 `App.jsx` 作为应用入口；
- OneBench 的业务数据、模板数据和示例文案；
- 浏览器直接保存 Evidence、Research Result 或 AI 判断；
- 将 OneBench 作为 Git 子模块、npm 运行时依赖或独立后端。

### 2.3 许可证要求

如果移植 OneBench 的具体代码，必须：

- 保留 MIT License 和原作者版权声明；
- 记录被移植的文件、提交或代码范围；
- 检查被移植代码的第三方依赖许可证；
- 优先移植通用 UI 实现，不移植业务数据和连接器逻辑。

默认策略是“参考设计、重写投研组件”；只有经过复用审查的通用代码才允许移植。

## 3. 目标架构

```text
用户
 ↓
Research Cockpit UI
 ├── App Shell
 ├── Widget Runtime
 ├── Research Pages
 └── OpenAPI Client + React Query
 ↓
Research Read API
 ├── Dashboard Read Model
 ├── Case Workspace Read Model
 └── Research lifecycle GET endpoints
 ↓
Application Query Service
 ↓
Research / Analytics / Core repositories
 ↓
Evidence Foundation + PostgreSQL
```

约束：

- 浏览器不得直接访问数据库；
- 浏览器不得直接调用 LLM；
- Widget 不自行拼接多个底层接口，不自行推导投资结论；
- Evidence、Research Result、AI 判断不进入布局或用户偏好存储；
- 所有展示数据必须来自 Research API 或现有明确的 Read API。

## 4. 前端目录和模块边界

```text
apps/web/src/
├── app/
│   ├── App.tsx
│   ├── router.tsx
│   └── AppShell.tsx
├── api/
│   ├── client.ts
│   ├── generated.ts
│   └── research.ts
├── components/
│   ├── MetricCard.tsx
│   ├── StatusBadge.tsx
│   ├── EmptyState.tsx
│   └── ErrorState.tsx
├── features/
│   ├── dashboard/
│   ├── research/
│   │   ├── cases/
│   │   ├── evidence/
│   │   ├── factors/
│   │   ├── runs/
│   │   ├── risks/
│   │   └── reports/
│   ├── candidatePool/
│   └── operations/
└── research-workspace/
    ├── runtime/
    │   ├── registry.ts
    │   ├── types.ts
    │   ├── layout.ts
    │   └── WidgetFrame.tsx
    ├── widgets/
    └── pages/
```

`research-workspace/runtime` 只负责 Widget 的注册、布局、显示状态和渲染外壳；投研业务语义放在 `features/research`，避免形成一个业务逻辑薄、配置复杂的通用平台。

## 5. 路由和页面契约

现有 Web 以 `/dashboard` 为主 Dashboard 路由。本计划统一使用以下路径：

| 页面 | 路径 | 说明 |
|---|---|---|
| Research Dashboard | `/dashboard` | 市场状态、研究摘要、Evidence 质量、最近运行 |
| Research Case | `/research/:caseId` | Case、Evidence、Factors、Result、Risk、Report |
| Research History | `/research/history` | Research Case 和 Research Run 历史 |
| ETF Detail | `/etf/:instrumentId` | 保留现有 ETF 详情页 |
| Operations | `/operations` | 保留 Pipeline Operations 页面 |

根路径 `/` 继续重定向到 `/dashboard`，不再同时定义两套 Dashboard 语义。

## 6. Widget Registry 契约

Widget Registry 只描述展示能力，不持有业务事实：

```ts
type ResearchWidgetDefinition = {
  key: string;
  title: string;
  description: string;
  defaultSize: "small" | "medium" | "wide";
  supportedPages: Array<"dashboard" | "research-case">;
  requiredData: string[];
  render: React.ComponentType<ResearchWidgetProps>;
};
```

第一批 Widget：

1. `market-status`
2. `research-summary`
3. `evidence-pack`
4. `factor-snapshot`
5. `research-run-timeline`
6. `risk-monitor`
7. `report-viewer`

Widget 必须具备：

- loading 状态；
- error 状态；
- empty 状态；
- 数据时间和质量提示；
- 可访问名称；
- 不通过颜色单独表达状态；
- 不在前端计算投资结论。

## 7. 投研 Widget 数据规则

### 7.1 Research Summary

展示：

- instrument / ETF；
- research case；
- stance；
- confidence；
- horizon；
- result status；
- result updated time。

规则：

- `stance`、`confidence`、`horizon` 只能来自已持久化或已发布的 Research Result；
- 前端不得根据因子自行推导 stance；
- 没有 Research Result 时显示“尚无研究结论”，不得显示默认买卖意见；
- 禁止出现 Buy、Sell、Position 操作按钮。

### 7.2 Evidence Pack Viewer

展示：

- schema version；
- content hash；
- quality status；
- freshness status；
- as-of date；
- evidence items；
- provider / dataset / revision provenance；
- evidence item ID。

规则：

- Evidence Pack 只读；
- 内容不可由前端修改；
- hash、质量和新鲜度由 API 返回；
- 不能把 layout 或 preference 数据混入 Evidence Pack。

### 7.3 Factor Snapshot

展示：

- return；
- trend；
- volatility；
- drawdown；
- observation date；
- algorithm version；
- parameter version；
- data quality；
- referenced evidence ID。

规则：

- 因子由 Analytics 计算，前端只展示；
- 缺失因子必须明确显示缺失原因；
- 因子展示不转换为买卖建议。

### 7.4 Research Run Timeline

展示实际 API 状态，不在前端硬编码状态机：

- Created；
- Evidence Ready；
- Running；
- Completed；
- Failed。

如果后端枚举名称不同，前端通过明确的 display mapping 展示，不能自行创造新的业务状态。

### 7.5 Risk Monitor

展示：

- 风险因素；
- 风险来源；
- 观察时间；
- 失效条件；
- 当前状态；
- 关联 Evidence ID。

风险解释属于 Research / AI 结果，前端不重新解释原始因子。

### 7.6 Report Viewer

- 只读展示 Markdown 或服务端渲染结果；
- 报告中的 Evidence ID 可跳转到 Evidence Pack；
- 禁止前端编辑并回写 Research Result；
- 对不可信 Markdown 内容进行安全渲染，禁止任意脚本执行。

## 8. API 契约调整

原计划中的两个 Read Model 保留，但必须与现有 Research API 计划统一：

```text
GET /api/v1/research-dashboard
GET /api/v1/research-cases/{case_id}/workspace
```

两个聚合接口用于页面首屏；资源级 GET 接口用于详情、分页和局部刷新。不得让 Widget 直接访问数据库或绕过 Application Query Service。

聚合响应至少需要明确：

- `schema_version`；
- `generated_at`；
- `as_of_date`；
- `data_quality`；
- `freshness`；
- `items` / `sections`；
- 关联资源 ID；
- 缺失关联资源的表达方式。

API 设计必须满足：

- OpenAPI 可生成 TypeScript 类型；
- 列表排序确定；
- 分页参数有上限；
- 404、500 错误不泄漏 SQLAlchemy 或内部存储信息；
- 不新增写入、重试、取消和自动交易接口。

## 9. 技术方案调整

保留：

- React；
- TypeScript；
- Vite；
- React Query；
- OpenAPI TypeScript Client；
- 现有 AppShell、loading/error/empty 状态和测试模式。

新增或评估：

- `@dnd-kit/core`、`@dnd-kit/sortable`：仅在真实需要拖拽布局时引入；
- `@phosphor-icons/react`：用于统一图标体系；
- Zustand：暂不作为必选依赖。第一版布局状态可以使用局部 React state；只有需要跨页面持久化时再引入。

不引入：

- OneBench 的完整依赖树；
- OneBench 的 `workspace.json` 运行时；
- 前端 LLM SDK；
- 浏览器数据库作为 Evidence 存储。

## 10. 实施阶段和 PR 拆分

### Phase A：Cockpit UI Foundation

#### PR-W01：Research Cockpit visual foundation

范围：

- AppShell 视觉适配；
- Research 页面路由骨架；
- 投研颜色、间距、卡片和状态 Token；
- WidgetFrame、MetricCard、StatusBadge；
- loading/error/empty 状态统一化；
- 引入 OneBench 复用记录和许可证说明。

验收：

- `/dashboard`、`/research/:caseId`、`/research/history` 可达；
- 无业务数据时页面仍可渲染；
- 390px 移动视口无横向溢出；
- 不破坏现有 Candidate Pool、ETF Detail 和 Operations 页面。

#### PR-W02：Widget Registry and layout runtime

范围：

- Registry 类型和注册机制；
- 固定布局和 Widget 尺寸；
- Widget 显示/隐藏状态；
- 可选的拖拽排序；
- 仅保存 layout / preference。

验收：

- Widget 可以注册、显示、排序和隐藏；
- 布局数据不包含 Evidence、Research Result 或 AI 判断；
- 刷新后 layout 行为符合定义；
- 拖拽失败不会影响业务数据。

### Phase B：Research Read Model and Core Widgets

#### PR-W03：Research Dashboard Read Model

范围：

- `GET /api/v1/research-dashboard`；
- Dashboard query service；
- OpenAPI schema；
- Web API client 和 React Query hooks。

验收：

- API 返回市场状态、研究摘要、Evidence 状态和最近运行；
- 响应包含时间、质量和 schema version；
- API 只读，无 LLM 和数据库暴露；
- API、Storage、Ruff、architecture check 通过。

#### PR-W04：Research Dashboard Widgets

范围：

- Market Status；
- Research Summary；
- Evidence Pack；
- Factor Snapshot；
- Research Run Timeline；
- Risk Monitor。

验收：

- Widget 只消费 API 数据；
- 缺失、过期、失败和空数据均有明确状态；
- 因子展示包含 provenance；
- 不出现买卖和仓位操作入口；
- 关键 Widget 有组件测试。

### Phase C：Research Case Experience

#### PR-W05：Research Case workspace API and page

范围：

- `GET /api/v1/research-cases/{case_id}/workspace`；
- Research Case 页面；
- ETF Profile、Evidence、Factors、Result、Risk、Run 分区；
- Evidence ID 关联跳转。

验收：

- Case → Evidence → Factor → Result 链路可追溯；
- 缺失关联数据可解释；
- 所有展示内容可回到 API 资源 ID；
- 页面不修改 Research 生命周期。

#### PR-W06：Report Viewer and history

范围：

- Markdown Report Viewer；
- Research History；
- Run 详情和失败状态；
- 安全 Markdown 渲染。

验收：

- 报告中的 Evidence ID 可定位到 Evidence；
- 不执行不可信脚本；
- 历史排序和分页确定；
- 报告缺失时有明确空状态。

### Phase D：Personal Workspace Preferences

#### PR-W07：Personal layout and watchlist

范围：

- 用户布局保存；
- Widget 显示偏好；
- Watchlist；
- 首页配置。

验收：

- 只保存用户偏好和布局；
- 不保存 Evidence、Research Result、AI 判断；
- 布局版本可迁移；
- 偏好数据损坏时可以回退默认布局。

## 11. 依赖顺序

```text
现有 Research API / Domain
          ↓
PR-W01 视觉基础
          ↓
PR-W02 Widget Runtime
          ↓
PR-W03 Dashboard Read Model
          ↓
PR-W04 Dashboard Widgets
          ↓
PR-W05 Research Case
          ↓
PR-W06 Report / History
          ↓
PR-W07 Personal Preferences
```

API 契约必须先冻结，再并行开发 API 和前端 Widget。数据库迁移、领域模型和 Research 生命周期变更不能作为前端 Workspace 的隐式依赖。

## 12. 全局 Definition of Done

- Research Cockpit 使用现有 invest-infra Web 技术栈；
- OneBench 的 UI/布局参考已记录，具体代码复用有许可证记录；
- Widget Registry 和 WidgetFrame 可测试；
- Dashboard、Research Case、Research History 页面完成；
- Evidence Pack、Factor、Run、Risk、Report 可视化；
- API Read Model 和 OpenAPI 类型保持一致；
- 所有展示数据有时间、质量或 provenance 信息；
- 前端不直连数据库、不调用 LLM、不保存 Evidence；
- 不出现买卖、仓位、自动交易入口；
- 旧 Dashboard、Candidate Pool、ETF Detail、Operations 功能不回归；
- TypeScript、Web tests、API tests、Ruff、architecture check、OpenAPI freshness 和 `git diff --check` 通过；
- 390px 移动视口和桌面视口均无阻断性布局问题；
- 关键页面完成浏览器视觉验收并保留截图证据。

## 13. 风险和处理

| 风险 | 影响 | 处理 |
|---|---|---|
| 直接复制 OneBench 整套 App | 高 | 只移植视觉、布局和通用 UI，保留 invest-infra 应用入口 |
| Research Result 字段未冻结 | 高 | 先冻结 API schema 和 provenance 字段，再实现 Widget |
| 前端自行推导投资结论 | 高 | Stance、Confidence、Risk 只来自后端 Research Result |
| Widget Runtime 过度通用化 | 中 | 第一版只支持注册、固定布局、可选排序 |
| dnd-kit/Zustand 提前引入 | 中 | 以真实用户需求为准，不作为 Phase A 的硬依赖 |
| OneBench 上游变化 | 中 | 不建立运行时依赖，不使用 Git submodule |
| API 和文档模型漂移 | 高 | 以 OpenAPI、领域模型和实际仓储实现为准，增加契约测试 |
| 图形误导投研判断 | 高 | 展示观察日期、数据质量、版本和 Evidence ID，禁止无来源图形 |

## 14. 仍需在实施前确认的事项

- Research Dashboard 的主入口是否继续使用 `/dashboard`；本计划默认保留现有路由；
- Research Result 的公开字段和 stance 枚举；
- Factor Snapshot 的 API 来源及当前已落地的字段版本；
- 第一版是否需要真正的拖拽布局；本计划默认先支持注册和固定布局；
- Watchlist 是否属于 Research 领域，还是继续归入个人偏好；
- AI Report 的 Markdown 存储和安全渲染契约。

## 15. 参考文件

- OneBench：<https://github.com/diyiwuyan/onebench>
- OneBench README：<https://github.com/diyiwuyan/onebench/blob/main/README.md>
- OneBench styles：<https://github.com/diyiwuyan/onebench/blob/main/src/styles.css>
- OneBench design QA：<https://github.com/diyiwuyan/onebench/blob/main/design-qa.md>
- invest-infra 架构治理：`docs/ARCHITECTURE-GOVERNANCE.md`
- invest-infra Research API 计划：`tasks/pr7-research-api-plan.md`
- invest-infra Web 工作台：`apps/web/`
