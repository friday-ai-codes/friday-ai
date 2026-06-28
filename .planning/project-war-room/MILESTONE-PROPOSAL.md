# 里程碑方案：项目作战室 / 工作区大盘（Dashboard 化 + 关系星图 + 内嵌项目 AI 会话）

**定稿：** 2026-06-27
**状态：** Proposal（立项草案，供 `gsd-plan-phase` 拆解 plan 使用）
**跟踪：** 本文为唯一跟踪源；阶段进度见 §11 进度表，落地后同步 `.planning/ROADMAP.md` 与 `.planning/STATE.md`。

> 在 v0.16.0「项目工作区」（飞书文档双向同步 + IDE 上下文闭环 + feature list 流水线，已 shipped）之上，把"项目详情页"从**左导航 + 资料陈列**升级为**单页平铺的项目作战大盘**：所有交付信息分区铺开、可被项目成员就地修改/补充、用一张**关系星图**展示 feature 与知识/仓库/依赖的关联，并在右侧常驻一个**可收起/展开/放大的项目 AI 会话栏**（个人会话 / 项目个人会话 / 项目共享会话）。

---

## 0. 一句话目标

进入项目 = 进入作战室：**一屏看全交付现状（不靠点击切 tab）+ 一张星图看清关联 + 右侧随时问懂这个项目的 AI**，且大盘上的信息项目成员能直接改、能补充。

---

## 1. 与既有能力的关系（复用 / 增强 / 净新）

v0.15.0 / v0.16.0 已落地领域地基，本期**严禁重复造**：

- **直接复用（零或极少后端）**：
  - 项目域：`projectsApi`（get / members / work-items / graph(KLINK)）、`projectWorkspaceApi`（listDocs / getDocContent / **updateHumanBlocks**(人工区可写) / feature-list(四态灯) / listWorkItems(含状态) / **state-apis CRUD** / search / rebuild）、`mergeRequestsApi.list`、`projectMemoryApi`(条目式可写)。
  - 会话域：`Conversation.bound_project`（绑定即自动加载项目上下文，context packer + RetrievalTrace + fail-closed）、`forkConversationForMessage`（clone 底座）、chat 组件全家桶（`ChatMessageArea`/`ChatInput`/`ChatMessageBubble`/…）、`prefilled_query`。
  - 星图域：`/codegraph/galaxy/`（galaxy.ts，节点/边/详情/搜索）、`3d-force-graph`、`/projects/{id}/graph/`（KnowledgeEdge 关联）。
- **增强/改设**：
  - 项目页布局：**废弃 `WorkbenchShell` 左导航单列模式**，改为**单页平铺 Dashboard + 右侧 AI 会话栏**（响应式）。
  - 大盘可写：各分区接已有写端点（human-blocks / state-apis / memories），统一成"成员就地编辑/补充"。
  - 星图：从"代码级 galaxy"和"知识 KLINK"升级为**项目级统一关系图**（feature ↔ work item ↔ 仓库 ↔ 依赖 ↔ 知识 ↔ 文档）。
- **净新增**：
  - `Conversation.visibility`（personal / shared）+ 共享会话只读 + clone-to-contribute 权限模型。
  - 会话/消息序列化暴露**贡献者头像+名字**、**相对时间(+精确 tooltip)**、**每会话执行时长**。
  - **项目级统一关系图端点**（聚合 feature/work-item/repo/dependency/knowledge/doc）。
  - 内嵌**可实例化对话容器**（与全局 `chatStore` 解耦的项目作用域实例）。

---

## 2. 第一性原理 / 设计立场

1. **大盘优先于导航。** 第一屏直接平铺交付现状，不用左导航逐个点开；信息密但分区清晰（卡片化 + 视觉层级靠 size/spacing/contrast，不靠颜色单独承载）。
2. **能看也能改。** 大盘不是只读陈列；凡是已有写端点的分区（文档人工区 / API 清单 / 记忆 / 备注）都允许项目成员就地编辑、补充，写仅成员、脱敏不松。
3. **会话即记录，贡献靠克隆。** 项目共享会话**全员只读可见**；要发言就 **clone 成自己的"项目个人会话"**（天然继承项目上下文）——从机制上消灭多人写同一会话的并发冲突。
4. **风格不另起炉灶。** 视觉沿用现有 Tailwind/reka-ui design token（语义色 `--color-*`、card/badge 组件、明暗双模）；仅采纳通用布局/UX 规范，不引入新配色/字体。
5. **观测/脱敏不可绕过。** 新增端点 started/completed/failed + `duration_ms` + `category`/`component` + 触发用户；新增召回写 `RetrievalTrace`；异常/上游文本脱敏；观测 best-effort 不反噬主流程。

---

## 3. 已锁定决策（用户确认 2026-06-27）

| # | 决策 | 结论 |
|---|---|---|
| 1 | 会话类型与贡献方式 | 三类：**个人会话**(不绑项目) / **项目个人会话**(绑项目+仅本人) / **项目共享会话**(绑项目+全员只读可见)。共享会话**他人发言 = clone 到自己的项目个人会话**；项目个人会话人人可在自己副本里自由发言。三类均可归档、可 fork（目标可选三类之一）。 |
| 2 | 共享可见范围 | = **项目级**（"空间会话"即项目级项目会话；范围 = 项目成员）。 |
| 3 | 并发 | 单会话同一时刻仅一轮 AI 运行（因共享只读+clone，多写并发天然不存在；个人副本各自串行）。 |
| 4 | 归档/删除 | 共享会话**删除限创建者 + 项目管理员**；其余成员仅"从我的视图隐藏"；归档任意成员可。 |
| 5 | 默认类型与互转 | 项目页默认新建**项目个人会话**；可手动设为共享；个人↔共享可互转，**互转带二次确认**（共享→个人仅创建者可操作）。 |
| 6 | 布局 | **去左导航，全平铺成 Dashboard 大盘**；feature list / 外部依赖等全部铺开；含**关系星图**；AI 对话为**右侧可收起/展开/放大侧边栏**。 |
| 7 | 会话 UI | 展示贡献者**头像+名字**；消息显示**相对时间**(x 分钟前) + hover tooltip **精确时分秒**；每会话展示**执行时长**。 |
| 8 | 本期不做 | **迭代/Sprint** 全部不做。 |

---

## 4. 信息架构（大盘 Dashboard 形态）

整页 = `主区(大盘) + 右侧 AI 会话栏`，无左导航。主区为响应式网格，分区卡片自上而下、宽屏多列、窄屏单列：

```
Project War Room
├── Header（项目名/状态徽标/所属空间 · 飞书看板 · 重建工作区 · 状态流转）
├── 大盘主区（平铺网格，分区卡片，凡有写端点者可就地编辑/补充）
│   ├── 健康总览        feature 计数(todo/in_progress/testing/done) · 待合并 MR 数 · docs 同步态 · 下一步建议(规则版)
│   ├── 关系星图 ★      feature↔work item↔仓库↔依赖↔知识↔文档；点击节点看详情/跳转；可聚焦某 feature 看其关联
│   ├── Feature 清单    "按状态 / 按模块"视图切换（复用 feature-list 四态灯）
│   ├── 工作项          work items 含状态
│   ├── 文档(5 文件)    渲染 + 人工区就地编辑(human-blocks)
│   ├── 外部依赖        DependenciesSection 复用 + 可补充
│   ├── API 清单        state-apis CRUD（成员可改）
│   ├── 项目记忆        ProjectMemory 条目式（成员可补充）
│   ├── 合并请求        MR open/merged/closed 列表
│   └── 人员            成员 + 身份
└── 右侧 AI 会话栏（收起▸ / 展开 / 放大全屏）
    ├── 会话切换器      分组：项目共享(只读) · 我的项目个人 · 我的个人
    ├── 消息区          头像+名字 · 相对时间(+精确 tooltip) · 工具调用卡片(复用)
    ├── 输入区          复用 ChatInput；共享会话只读态显示"克隆到我的会话以发言"
    └── 会话元信息      执行时长 · 类型徽标 · fork/归档/删除/个人↔共享互转
```

**布局/响应式规范（采纳 ui-ux-pro-max，配色字体不变）**：
- 网格：`lg` 多列 bento 式、`md` 双列、`<md` 单列；右侧会话栏宽屏常驻、`<lg` 转抽屉/底部弹层。
- 防 CLS：异步卡片预留高度 / `aspect-ratio`，骨架屏占位（>300ms）。
- 层级：统一 z-index 标度（10/20/40/100），放大态用 Dialog/Drawer 隔离 stacking context。
- 视口：`min-h-dvh`（避免移动端 100vh）；放大会话用 `dvh`。
- 动效：150–300ms、transform/opacity、`prefers-reduced-motion` 降级；放大从触发源 scale+fade。
- 可读：长文 `max-w-prose`；触控目标 ≥44px；图标统一 lucide、不用 emoji。

---

## 5. 会话子系统设计（核心）

### 5.1 数据模型（chat app）
- `Conversation` 新增 `visibility`：`personal`(默认) / `shared`；迁移后存量全部 `personal`（行为不回退）。
- 约束：`visibility=shared` 仅当 `bound_project` 非空时允许（共享 = 项目会话）。
- 索引：`(bound_project, visibility, is_deleted, is_archived)`、`(bound_project, created_by)`。
- **执行时长**：新增派生/标注 `duration_ms`（建议口径：该会话所有 `OrchestrationRun` 运行时长之和；无 run 时为 0）。serializer annotate，不存冗余真值（避免漂移）。

### 5.2 权限（在严格 owner 隔离 ISO-01~04 上开"共享只读"口子）
统一收敛为**单一会话访问判定函数**（读 / 写 / 管理三档），替换 views.py 里散落的十余处 owner gate：
- `personal`：仅 `created_by`（维持现状，隔离不破）。
- `shared`：**项目成员可读**；**非 owner 不可写**（输入区只读）；**删除限创建者 + 项目管理员**，归档任意成员可，非管理成员仅"从我的视图隐藏"。
- 贡献路径：共享会话点"克隆发言" → `fork` 出 `bound_project=同项目 + visibility=personal + created_by=我` 的副本，在副本里自由对话。
- 非项目成员访问共享会话 → 404（不泄漏 provider/上下文）。

### 5.3 API 改动
- `GET /chat/conversations/`：新增 `bound_project`、`visibility` 过滤；返回 `visibility` + 贡献者精简用户对象(id/display_name/avatar) + `duration_ms`。
- `POST /chat/conversations/`：支持 `bound_project_id` + `visibility`。
- `PATCH /chat/conversations/{id}/`：支持 `visibility` 互转（个人↔共享，带二次确认语义，见 §9-B）；`bound_project_id` 已支持。
- `fork`：扩展 `ForkConversationRequest` 支持目标 `bound_project_id` + `visibility`（clone 到三类之一）。
- 消息序列化：暴露 `user`(id/display_name/avatar) + `created_at`（供相对时间+tooltip）。
- 归档：复用 `is_archived`。

### 5.4 前端（内嵌对话栏）
- **抽出可实例化对话容器**：复用 chat 组件 + SSE，但用**项目作用域局部 store/composable**（固定 `bound_project=当前项目`），**不污染全局 `chatStore`**（其 `selectedSpaceId`/`currentConversation`/`restoreFromURL` 是整页单例假设）。
- 功能：会话切换器(三组)、新建(默认项目个人)、追问、归档、删除、fork(选目标类型)、互转、收起/展开/放大。
- 消息：头像+名字（多人共享会话区分发言人）、相对时间组件(`@vueuse` `useTimeAgo` 或等价) + `<title>`/tooltip 精确到秒、会话头部展示执行时长。

---

## 6. 关系星图设计

### 6.1 后端
- 新增**项目级统一关系图端点** `GET /projects/{id}/galaxy/`（已确认：新建独立端点，不复用 `/graph/`），聚合并返回统一 nodes/edges：
  - 节点类型：`project` / `feature` / `work_item` / `repository` / `dependency` / `knowledge` / `doc`。
  - 边：feature→work_item(派生)、work_item→repository(关联)、project→repository/dependency、KnowledgeEdge(KLINK) 知识关联、feature→knowledge。
  - 数据来源复用：feature-list、work-items、repositories、dependencies、`ProjectRelation`/`KnowledgeEdge`、ProjectDoc。
- 控制规模：节点上限 + 采样 meta（仿 galaxy `GalaxyMeta`）；权限按项目成员 fail-closed；只读。

### 6.2 前端
- 复用 `3d-force-graph` / 现有 galaxy 可视化封装，嵌入大盘"关系星图"卡片，可全屏放大。
- 交互：节点 hover 高亮 1-hop；点击出详情面板（名称/类型/关联）+ 跳转（feature→Feature 清单、repo→仓库、doc→文档区）；支持"聚焦某 feature 看它关联了什么"。
- 可访问性：提供节点列表/文本摘要兜底（图非屏幕阅读器友好）；空态/加载骨架；`prefers-reduced-motion` 时禁用力导动画初始抖动。

---

## 7. 大盘可编辑（成员可改/补充）

逐区映射到**已有写端点**，无需大量新后端：
- 文档(5 文件)人工区 → `updateHumanBlocks`（仅 human 区，已有）。
- API 清单 → `state-apis` POST/PATCH/DELETE（已有）。
- 项目记忆 → `projectMemory` 条目式新增/编辑（已有，draft/confirm 流）。
- Feature/工作项 → **派生数据，本期不做直接编辑**；"补充"通过记忆/备注承载（避免动看板真相源）。
- 写权限：统一"仅项目成员可写"；非成员只读；所有写入走既有 service + 脱敏 + 观测。

---

## 8. 分阶段路线图（建议 5 Phase / 3 Wave）

**Wave 1 — 大盘骨架（前端为主，复用现有数据，可独立上线）**
- **P1 大盘布局重构**：去左导航 → 单页平铺 Dashboard + 健康总览(实数据) + Feature"按状态/按模块"切换 + 文档/依赖/工作项/MR/人员分区 + 响应式 + 右侧会话栏占位(壳)。沿用现有 design token。

**Wave 2 — 会话子系统（本期重头）**
- **P2 会话模型与权限(后端)**：`visibility` 字段 + 迁移 + 统一访问判定函数 + 列表/创建/PATCH/fork 扩展 + serializer 暴露 用户头像名/时间/duration + 全套权限测试(越权 404 / 共享只读 / 个人隔离不破 / clone 贡献)。
- **P3 内嵌 AI 会话栏(前端)**：可实例化对话容器(解耦全局 store) + 三组会话切换 + clone 贡献流 + 头像名字 + 相对时间(+tooltip) + 执行时长 + 收起/展开/放大 + 互转二次确认。

**Wave 3 — 关系星图 + 可编辑增强**
- **P4 项目级星图**：统一关系图端点(后端) + 星图可视化嵌入大盘 + 节点详情/跳转/聚焦 + 放大。
- **P5 大盘可编辑增强**：各分区接 human-blocks/state-apis/memories 就地编辑/补充 + 权限 + 观测 + 移动端核对。

依赖：P1 独立；P3 依赖 P2；P4 独立可并行；P5 依赖 P1。建议顺序 P1 → P2 → P3 → P4 → P5。

---

## 9. 已确认决策（2026-06-27 补充）

- **A. 共享会话删除权限** → **创建者 + 项目管理员**可删；其余成员仅"从我的视图隐藏"；归档任意成员可。
- **B. 互转语义** → 个人↔共享互转**均带二次确认**；个人→共享提示"历史消息将对全项目可见"；**共享→个人仅创建者**可操作。
- **C. 执行时长口径** → **单条会话的执行时长**（该会话维度，建议取所有 `OrchestrationRun` 运行时长之和；无 run 为 0），非每条消息。
- **D. 星图 endpoint** → **新建独立端点** `GET /projects/{id}/galaxy/`（不复用 `/graph/`）。

---

## 10. 观测与安全强制项

- 新增端点（会话过滤/互转/fork 扩展、项目星图、可编辑写入）：structlog started/completed/failed + `duration_ms` + `category=caller` + `component` + 绑定触发用户。
- 共享会话相关写/越权尝试：审计留痕；非成员一律 404。
- 星图/会话上下文若触发召回：写 `RetrievalTrace` + 条数/分层耗时/score（MCP 与 AI 对话两条链覆盖）。
- 互转、删除等敏感操作：审计 + 脱敏；异常文本 `redact_secrets_in_text`。
- async ORM 走 `sync_to_async`；新文案接 `vue-i18n`（默认中文）；观测 best-effort 不反噬主流程。

---

## 11. 进度跟踪

| Phase | 名称 | Wave | 技术方案 | 关键产出 | 依赖 | 状态 |
|---|---|---|---|---|---|---|
| P1 | 大盘布局重构 | 1 | `P1-PLAN-dashboard-skeleton.md` | 去左导航/平铺 Dashboard/Feature 视图切换/会话栏壳 | — | ✅ Done（前端已实现+测试通过） |
| P2 | 会话模型与权限(后端) | 2 | `P2-PLAN-conversation-model-perms.md` | visibility/统一权限/序列化(头像名·时间·duration)/测试 | — | ✅ Done（后端已实现，9 新测试+79 既有会话测试全过） |
| P3 | 内嵌 AI 会话栏(前端) | 2 | `P3-PLAN-embedded-assistant.md` | 可实例化容器/三组切换/clone 贡献/收展放/互转 | P1·P2 | ✅ Done（前端已实现，12 测试+类型检查通过） |
| P4 | 项目级关系星图 | 3 | `P4-PLAN-relationship-galaxy.md` | 统一图端点/星图可视化/详情跳转/聚焦 | — | ✅ Done（前后端已实现，6 测试通过） |
| P5 | 大盘可编辑增强 | 3 | `P5-PLAN-editable-dashboard.md` | 各分区就地编辑/补充/权限/观测 | P1 | ✅ Done（API 清单可编辑卡 + 权限闸，4 测试通过；文档/记忆复用现有编辑） |

> 落地时：每 Phase 完成后回填本表状态，并同步 `.planning/ROADMAP.md`。
> 建议执行顺序：P1 → P2 → P3 →（P4 可与 P2/P3 并行）→ P5。

---

## 12. 非目标（本期 Out of Scope）

- **迭代 / Sprint**（用户明示不做）。
- Executions 精确项目绑定、Blocker 模型、真事件流 Activity（留后续里程碑）。
- AI context 聚合大包 API（按需做"精炼 summary + 引用"，不搬全量）。
- 多人实时同写同一会话（已用 clone 模型规避，不做 OT）。
- 大规模视觉重设计 / 引入新配色字体（沿用现有 design token）。

---

## 13. 主要风险

1. **共享会话权限改写**（散落十余处 owner gate）——最易出越权漏洞，必须统一判定函数 + 测试兜底（P2 最高风险）。
2. **聊天全局状态解耦**——内嵌容器与全局 `chatStore` 隔离，避免互相污染（P3 关键）。
3. **大盘信息密度**——平铺易杂乱；靠分区/层级/留白控制，移动端单列降级。
4. **星图规模/性能**——节点过多需采样 + 力导性能预算 + reduced-motion。
5. **可编辑权限边界**——成员可写区与系统区物理隔离，复用现有 human/system 分区机制。

---
*立项：2026-06-27 — 项目作战室 / 工作区大盘（Dashboard 化 + 关系星图 + 内嵌项目 AI 会话），5 Phase / 3 Wave；本期不含迭代。*
