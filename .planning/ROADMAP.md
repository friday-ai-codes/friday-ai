# Roadmap: Friday AI

## Milestones

- 🚧 **v0.15.0 项目（交付上下文聚合根）** — Phases 76–81 (feature-complete 2026-06-26 — 6/6 phases, 38/38 需求)
- ✅ **v0.14.0 可观测性与日志治理** — Phases 71–75 (shipped 2026-06-24) — 里程碑审计 passed（34/34 需求满足 / integration_ok）见 [audit](./milestones/v0.14.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.14.0-ROADMAP.md)
- ✅ **v0.13.0 并发治理与索引体验** — Phases 65–70 (shipped 2026-06-23) — 里程碑审计 tech_debt（11/11 需求满足、integration_ok；遗留既有前端测试失败 + URL 拆段拼接 UI + 真机人工验收）见 [audit](./milestones/v0.13.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.13.0-ROADMAP.md)
- ✅ **v0.12.0 弹性任务底座（durable 任务队列与多副本就绪）** — Phases 60–64 (shipped 2026-06-20) — 里程碑审计 tech_debt（16/16 需求满足、integration_ok；遗留真机/真实平台运行期人工验收）见 [audit](./milestones/v0.12.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.12.0-ROADMAP.md)
- ✅ **v0.11.0 开放与协作** — Phases 56–59 (shipped 2026-06-17) — 里程碑审计 PASS（6/6 需求、INV-5/INV-6 成立）见 [audit](./milestones/v0.11.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.11.0-ROADMAP.md)
- ✅ **v0.10.0 操作审计治理** — Phases 53–55 (shipped 2026-06-17) — [archive](./milestones/v0.10.0-ROADMAP.md)
- ✅ **v0.9.0 SDD / OpenSpec 支持（重型）** — Phases 48–52 (shipped 2026-06-17) — [archive](./milestones/v0.9.0-ROADMAP.md)
- ✅ **v0.8.0 多仓串行编码 → 融合 PR** — Phases 43–47 (shipped 2026-06-17) — [archive](./milestones/v0.8.0-ROADMAP.md)
- ✅ **v0.7.0 方案编排（需求 → 主方案）** — Phases 36–42 (shipped 2026-06-16) — [archive](./milestones/v0.7.0-ROADMAP.md)
- ✅ **v0.6.0 领域脊柱 + 知识图谱补全** — Phases 27–35 (shipped 2026-06-15) — [archive](./milestones/v0.6.0-ROADMAP.md)
- ✅ **v0.5.0 索引检索地基与排除文件** — Phases 22–26 (shipped 2026-06-15) — [archive](./milestones/v0.5.0-ROADMAP.md)
- ✅ **v0.4.0 工作流系统契约重构** — Phases 17–21 (shipped 2026-06-13) — [archive](./milestones/v0.4.0-ROADMAP.md)
- ✅ **v0.3.0 交付知识图谱** — Phases 12–16 (shipped 2026-06-12) — [archive](./milestones/v0.3.0-ROADMAP.md)
- ✅ **v0.2.0 用户身份令牌与 Agent 工具打通** — Phases 6–11 (shipped 2026-06-10) — [archive](./milestones/v0.2.0-ROADMAP.md)
- ✅ **v0.1.0 首启初始化向导** — Phases 1–5 (shipped 2026-06-09) — [archive](./milestones/v0.1.0-ROADMAP.md)

> 历史里程碑详情归档在 `.planning/milestones/`，要点见 `MILESTONES.md`。

## Phases

### 🚧 v0.15.0 项目（交付上下文聚合根）(Phases 76–81 — PLANNING)

**Milestone Goal:** 把"需求 → 代码"全链路上下文统一收口到一个**在线协作的「项目」聚合根**——每个飞书"项目跟踪"看板对应一个项目，项目聚合需求/工件依赖/工作项(story·缺陷)/记忆/关联知识/仓库/分支/PR；项目对成员共享可参与，飞书人员经身份映射关联到 Friday 用户并带身份（主R/PM/前端/后端/测试）；任何对话、Cursor 编码、Agent 调用都能从项目加载完整上下文并把沉淀写回。前置：把现有 `projects.Project`（前端"空间"）重命名为 `Space`，腾出 `Project` 名给新聚合根。

> 完整设计与调研基线见 `.planning/project-aggregate/MILESTONE-PROPOSAL.md`；需求 38 条见 `.planning/REQUIREMENTS.md`。**不做迭代实体**（另一迭代 = 新项目；历史迭代经项目↔项目关联回看）；记忆为自由文本 + 人工为主/LLM 提议；UI 稿仅存元数据不强行 RAG 正文。

- [x] **Phase 76: 命名腾挪（Project→Space 重构前置）** - 后端 `projects.Project` 重命名为 `Space`，全栈 `project→space` 引用一致更新，腾出 `Project` 名；数据零丢失、行为/测试零回归 — RENAME-01, RENAME-02 — completed 2026-06-25（6266 passed / 新增回归 0 / makemigrations 干净 / 11 元数据级迁移）
- [x] **Phase 77: 项目聚合根 + 身份映射 + 成员协作** - 新建 `Project` 聚合根（隶属 Space + 关联飞书项目跟踪 + 状态机）+ 飞书人员↔Friday 用户映射 + 项目成员(多对多 + 身份角色) + CRUD/权限/实时推送 — PROJ-01~05, IDENT-01, MEMBER-01~03 — completed 2026-06-25（新 app `initiatives`；6294 passed / 新增 28 用例全绿 / 38 failed == baseline 零新增回归 / makemigrations 干净 / vue-tsc 绿）
- [x] **Phase 78: 飞书触发建项目 + 看板枚举 + 工作项组合** - 飞书项目跟踪枚举子项/成员封装 + 事件触发幂等建项目(拉人带身份) + `create_project` 工作流节点 + WorkItem(story/缺陷)关系边挂入 — FSPROJ-01~03, COMPOSE-01/02 — completed 2026-06-25（看板枚举 service + ProjectWorkItemLink + 同源 sync_from_board + create_project 节点；6315 passed / 新增 27 用例全绿 / 38 failed == baseline 零新增回归 / makemigrations 干净 / 飞书无整板 API 经字段派生 fail-soft 降级）
- [x] **Phase 79: 工件/依赖项（可配置类型 + 实例 + RAG）+ 知识关联** - `ArtifactType` 可配置注册表(内置 8 类 seed，后台增删禁用/双删保护) + `Artifact` 实例(多载体，INV-6) + 在线查看后端 API + 文字载体 RAG/UI 稿仅元数据 + 项目纳入知识图谱(EntityKind +project/repository/space)经 KnowledgeEdge 统一 KLINK 关联可查询 — ARTIFACT-01~05, KLINK-01/02 — completed 2026-06-26（6352 passed / 新增 39 用例全绿 / 38 failed == baseline 零新增回归 + 1 flaky cross-suite ordering（prompt 明示，单跑通过）/ makemigrations 干净 / 3 迁移含 seed）
- [x] **Phase 80: 项目记忆 + MR 实体 + 上下文召回接入 Web 会话** - 项目记忆(自由文本 + 贡献者/时效，人工为主 + LLM 提议确认) + `MergeRequest` 实体 + 入站 webhook 状态同步 + context packer(grep+RAG) + 接入 chat runner — MEM-01~04, RECALL-01~03, MR-01/02 — completed 2026-06-26（MemoryService/MemoryDistiller(call_source=memory_distill)/MergeRequestService(INV-6) + 受保护 git webhook(HMAC/token fail-closed + redact + 幂等) + context packer(fail-closed + token 预算降级 + RetrievalTrace) + Conversation.bound_project + chat 白名单接入；6390 passed / 新增 39+1 用例全绿 / 38 failed == baseline 零新增回归 / makemigrations 干净 / 2 迁移）
- [x] **Phase 81: Cursor 回流 + 前端项目工作台** - MCP 分支→项目反查召回 + Cursor rules 模板 + 沉淀上报写回 memory(归因/脱敏/质量门槛) + 项目列表/详情工作台/记忆编辑/工件类型管理页 — CURSOR-01~03, UI-01~03 — completed 2026-06-26（MCP `lookup_project_by_branch`(召回写 RetrievalTrace 补齐 MCP 链)/`report_project_knowledge`(归因+脱敏+质量门槛→draft) + cursor_rules API + 工作项 REST/列表筛选 + 前端工作台(列表+6 Tab 详情+记忆草稿确认+工件类型管理页) + zh-CN 全量；后端 6421 passed/新增 30 用例全绿/39 failed==baseline 38+1 已知 flaky 零新增回归/makemigrations 干净/无新迁移；前端 vue-tsc 绿/新增 12 用例全绿/1109 passed(2 failed 为既有 ProviderCredentialForm，零新增回归)）

## Phase Details

### Phase 76: 命名腾挪（Project→Space 重构前置）

**Goal**: 把现有 `projects.Project`（前端已称"空间 Space"，历史命名债）重命名为 `Space`，腾出 `Project` 名给新聚合根，全栈引用一致更新，数据零丢失、行为与测试基线零回归
**Depends on**: Nothing（纯重构前置，与新功能解耦；必须先完成且全绿再推进 77）
**Requirements**: RENAME-01, RENAME-02
**Success Criteria** (what must be TRUE):

  1. 后端 `projects.Project` 模型类重命名为 `Space`，`db_table` 保持或一次性迁移使既有数据零丢失；既有"空间"功能（飞书凭证 / Provider 默认 / 仓库 M2M / 三角色成员权限）行为零回归
  2. 全栈 `project→space` 内部引用一致更新——serializers/views/permissions/`space_tools`/workflow `fetch_space_info`/各 FK `related_name`（`WorkItem.project`/`Conversation.project`/`Workflow.project`/`ProjectRepository`/`ProjectMembership`/`Repository` M2M）
  3. 对外（前端 / API / i18n）继续称"空间 Space"不变，无用户可见行为变化
  4. 后端 ~520 + 前端 ~130 测试基线全绿；`makemigrations --check` 干净

**Plans**: TBD（plan-phase 拆分）

### Phase 77: 项目聚合根 + 身份映射 + 成员协作

**Goal**: 立起 `Project` 聚合根（隶属 Space、关联飞书"项目跟踪"看板、状态机），打通飞书人员↔Friday 用户映射地基，建项目成员多对多 + 身份角色，提供 CRUD/权限/实时推送
**Depends on**: Phase 76（`Project` 名已腾出）
**Requirements**: PROJ-01~05, IDENT-01, MEMBER-01~03
**Success Criteria** (what must be TRUE):

  1. `Project` 聚合根落库（隶属 `Space` + `feishu_project_key`/看板引用 + 状态 developing/archived/terminated + 创建者），经单一写入入口 `ProjectService`（INV-6）；状态非法流转 fail-loud + 接入 `AuditEvent`
  2. 飞书人员（`user_key`/`open_id`）↔ Friday `User` 多对多映射，单一解析入口 `resolve_feishu_user`（手动绑定 + 飞书事件 JIT），未映射 fail-soft 保留原始 id
  3. 项目成员模型（项目↔用户 多对多 + 身份角色 主R/PM/前端/后端/测试）；主R 唯一可转移；一个用户可属多项目、一个项目可多成员
  4. 项目 CRUD + 成员增删改 REST API 按 Space 成员权限 fail-closed + 审计；项目对全部成员可见可参与；成员/状态变更经 WebSocket 实时推送
  5. 用户可在前端手动创建项目（Space + 飞书看板 + 名称），以 `(space, feishu_project_key)` 幂等

**Plans**: TBD（plan-phase 拆分）

**UI hint**: yes

### Phase 78: 飞书触发建项目 + 看板枚举 + 工作项组合

**Goal**: 把"项目跟踪拖到节点"自动转成项目——封装飞书看板枚举（子项 story/缺陷 + 人员带角色）、事件幂等建项目并拉人、提供 `create_project` 工作流节点，并把 WorkItem 经关系边组合进项目
**Depends on**: Phase 77（聚合根 + 身份映射 + 成员）
**Requirements**: FSPROJ-01~03, COMPOSE-01/02
**Success Criteria** (what must be TRUE):

  1. 飞书"项目跟踪"看板枚举能力封装——读取子关联项（story/缺陷）与人员（带角色），无整板 API 时经子项关联字段派生逐项收集，失败 fail-soft 降级
  2. 飞书事件触发（项目跟踪拖到指定节点/状态）幂等创建同名项目 + 经身份映射拉入看板人员（带身份），重复事件不重复建
  3. 工作流 `create_project` 节点——以看板名建项目 + 枚举拉人（身份映射带角色）+ 关联子项 workitem，自动注册可在画布使用
  4. 项目组合多个 WorkItem——story 复用 `delivery.WorkItem` 经关系边挂入、支持手动并入/移除；缺陷（看板类型=缺陷）同样经关系边挂入，不重复建模

**Plans**: TBD（plan-phase 拆分）

### Phase 79: 工件/依赖项（可配置类型 + 实例 + RAG）+ 知识关联

**Goal**: 把"需求文档/feature list/研发 Spec/UI 稿/UI 评审/埋点文档/埋点评审/复盘"等外部依赖统一抽象为可配置类型的工件，挂到项目、可在线查看、文字载体进 RAG，并把项目纳入交付知识图谱的关联
**Depends on**: Phase 77（项目聚合根）
**Requirements**: ARTIFACT-01~05, KLINK-01/02
**Success Criteria** (what must be TRUE):

  1. `ArtifactType` 可配置注册表——内置默认 8 类（需求文档/feature list/研发 Spec/UI 稿/UI 评审/埋点文档/埋点评审/复盘），后台可新增/禁用/删除；禁用类型不可新建实例、既有实例只读保留
  2. `Artifact` 实例模型挂到项目，记类型/载体（飞书文档/飞书表格/外链/md/仓库文件）/链接/标题/版本/贡献者；飞书文档·表格可在线查看渲染、外链跳转、md/内部工件可编辑
  3. 工件 RAG 摄取——文字载体（飞书文档/表格/md/研发 Spec）全文进 `delivery_knowledge` 可召回；图形外链（UI 稿 figma/mastergo）仅存元数据不强行 RAG 正文
  4. 项目 ↔ 知识实体（`KnowledgeEntity`）多对多关联（一个知识可属多项目、一个项目关联多知识）；项目可关联仓库/空间/知识/其他项目，经 `KnowledgeEdge` 统一建模、可查询可视

**Plans**: TBD（plan-phase 拆分）

**UI hint**: yes

### Phase 80: 项目记忆 + MR 实体 + 上下文召回接入 Web 会话

**Goal**: 给项目装上可变共享的记忆、把 PR/MR 升级为实体并入站同步状态、做出项目上下文打包器并接入 Web 对话，让对话能自动加载项目完整上下文
**Depends on**: Phase 79（工件/知识关联齐备，召回面完整）
**Requirements**: MEM-01~04, RECALL-01~03, MR-01/02
**Success Criteria** (what must be TRUE):

  1. 项目记忆（自由文本条目 append/edit + 每条时间戳/贡献者）对全部成员共享；贡献仅限成员、私聊/非成员会话不纳入；可人工编辑覆盖且保留可追溯
  2. LLM 从成员会话提炼记忆草稿 → 人工确认后入库（不自动直接写）；入库前脱敏不可绕过（`redact_*`）
  3. `MergeRequest` 实体（关联项目/仓库/分支/工作项 + url + 源·目标分支 + 状态 + review）经单一入口 `MergeRequestService`；入站 webhook 同步 GitHub/GitLab 状态（脱敏原始 payload 落库），项目内可见
  4. 项目上下文打包器（context packer）——聚合需求/工件/记忆/关联知识/历史，经 grep(SQL) + RAG(语义) 召回 + 排序 + 压缩，token 预算可降级
  5. Web 对话可绑定项目自动加载上下文，`search_delivery_knowledge` 等接入 chat runner 工具白名单；召回按项目 scope + 用户权限 fail-closed + 写 `RetrievalTrace`

**Plans**: TBD（plan-phase 拆分）

**UI hint**: yes

### Phase 81: Cursor 回流 + 前端项目工作台

**Goal**: 打通 Cursor↔Friday 双向闭环（分支反查召回 + rules 强制 + 沉淀上报写回），并交付项目工作台前端，让团队在 Friday 上看到/参与项目全部上下文
**Depends on**: Phase 80（记忆/召回/MR 就绪）
**Requirements**: CURSOR-01~03, UI-01~03
**Success Criteria** (what must be TRUE):

  1. MCP 分支→项目反查 + 召回——Cursor 经 MCP 用当前分支名（含 `m{work_item_id}`/项目标识）反查项目，召回需求/工件/记忆上下文
  2. Cursor rules 模板——强制"先关联本分支项目、召回上下文再编码"（随项目下发或文档化）
  3. Cursor 沉淀上报写回——处理完成后经 MCP/API 上报知识，由 Friday 写入项目 memory/知识；带认证 + 归因（身份映射）+ 脱敏 + 质量门槛防噪音
  4. 前端项目工作台——项目列表（按 Space/状态/成员筛选）+ 创建入口；项目详情（概览/成员带身份/工作项/工件在线查看/记忆编辑/关联知识·仓库·项目·PR）
  5. 项目记忆编辑 + LLM 提议确认 UI；工件类型后台管理页（增删禁用）

**Plans**: TBD（plan-phase 拆分）

**UI hint**: yes

<details>
<summary>✅ v0.14.0 可观测性与日志治理 (Phases 71–75) — SHIPPED 2026-06-24 — 审计 passed</summary>

- [x] Phase 71: 可观测性地基（用户上下文贯穿 + 系统日志治理） (5/5 plans) — CTX-01/02, LOG-01~08 — completed 2026-06-24
- [x] Phase 72: 调用数据采集（AI/LLM + 召回 + 请求入口） (4/4 plans) — RATE-01/02, RAG-01/02, SLA-02/03/04 — completed 2026-06-24
- [x] Phase 73: 快照·趋势·查询 API (3/3 plans) — SNAP-01~05, RATE-03, SLA-01, QUERY-01/02 — completed 2026-06-24
- [x] Phase 74: 告警引擎与通知（阈值 + 告警事件 + 邮件） (3/3 plans) — ALERT-01/02/03 — completed 2026-06-24
- [x] Phase 75: 运维大盘前端 + 规范固化 (5/5 plans) — UI-01~04, SPEC-01 — completed 2026-06-24

完整阶段详情见 [milestones/v0.14.0-ROADMAP.md](./milestones/v0.14.0-ROADMAP.md)；里程碑审计 passed（34/34 需求、integration_ok）见 [milestones/v0.14.0-MILESTONE-AUDIT.md](./milestones/v0.14.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.13.0 并发治理与索引体验 (Phases 65–70) — SHIPPED 2026-06-23 — 审计 tech_debt</summary>

- [x] Phase 65: AI 对话串流隔离修复 (1/1 plans) — STREAM-01 — completed 2026-06-23
- [x] Phase 66: 默认禁用 LSP（仅 tree-sitter） (1/1 plans) — LSP-01 — completed 2026-06-23
- [x] Phase 67: 并发治理（槽位锁池 / provider 限流 / 容器上限） (3/3 plans) — CONC-01/02/03 — completed 2026-06-23
- [x] Phase 68: 实时进度统一 + 进度条修复 (1/1 plans) — PROG-01/02 — completed 2026-06-23
- [x] Phase 69: 批量加仓 + 全部更新索引（超管） (1/1 plans) — BATCH-01/02 — completed 2026-06-23
- [x] Phase 70: access token / 密钥提供方重构（FK） (1/1 plans) — TOKEN-01/02 — completed 2026-06-23

完整阶段详情见 [milestones/v0.13.0-ROADMAP.md](./milestones/v0.13.0-ROADMAP.md)；里程碑审计 tech_debt（11/11 需求、integration_ok）见 [milestones/v0.13.0-MILESTONE-AUDIT.md](./milestones/v0.13.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.12.0 弹性任务底座（durable 任务队列与多副本就绪）(Phases 60–64) — SHIPPED 2026-06-20</summary>

- [x] Phase 60: durable 底座地基 (4/4 plans) — DURABLE-01~04 — completed 2026-06-19
- [x] Phase 61: 迁移 index/graph + 收口 ResumableTask (4/4 plans) — MIGRATE-01/02, IDEMP-01 — completed 2026-06-19
- [x] Phase 62: 爬取+入库 durable 队列 + PageIndex 接入 (3/3 plans) — CRAWL-01/02, PAGEIDX-01 — completed 2026-06-20
- [x] Phase 63: 部署硬化 + 外部副作用 fencing (3/3 plans) — DEPLOY-01~03, IDEMP-02 — completed 2026-06-20
- [x] Phase 64: runner k8s Job executor (2/2 plans) — RUNNER-01/02 — completed 2026-06-20

完整阶段详情见 [milestones/v0.12.0-ROADMAP.md](./milestones/v0.12.0-ROADMAP.md)；里程碑审计 tech_debt（16/16 需求、integration_ok）见 [milestones/v0.12.0-MILESTONE-AUDIT.md](./milestones/v0.12.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.11.0 开放与协作 (Phases 56–59) — SHIPPED 2026-06-17 — 审计 PASS</summary>

- [x] Phase 56: compat 内部工具调用 → progress/trace 事件透出 (2/2 plans) — TRACE-01, TRACE-02 — completed 2026-06-17
- [x] Phase 57: Anthropic 兼容端点 `/v1/messages` (2/2 plans) — ANTHROPIC-01, ANTHROPIC-02 — completed 2026-06-17
- [x] Phase 58: 飞书原生流式卡片（CardKit）(2/2 plans) — CARD-01 — completed 2026-06-17
- [x] Phase 59: 工作流自动建群节点 (2/2 plans) — GROUP-01 — completed 2026-06-17

里程碑审计 PASS（6/6 需求、INV-5/INV-6 成立）见 [milestones/v0.11.0-MILESTONE-AUDIT.md](./milestones/v0.11.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.10.0 操作审计治理 (Phases 53–55) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.10.0-ROADMAP.md](./milestones/v0.10.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.9.0 SDD / OpenSpec 支持（重型）(Phases 48–52) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.9.0-ROADMAP.md](./milestones/v0.9.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.8.0 多仓串行编码 → 融合 PR (Phases 43–47) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.8.0-ROADMAP.md](./milestones/v0.8.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.7.0 方案编排（需求 → 主方案）(Phases 36–42) — SHIPPED 2026-06-16</summary>

完整阶段详情见 [milestones/v0.7.0-ROADMAP.md](./milestones/v0.7.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.6.0 领域脊柱 + 知识图谱补全 (Phases 27–35) — SHIPPED 2026-06-15</summary>

完整阶段详情见 [milestones/v0.6.0-ROADMAP.md](./milestones/v0.6.0-ROADMAP.md)。

</details>

## Progress

里程碑 v0.1.0–v0.14.0（Phases 1–75）均已交付。**🚧 v0.15.0 项目（交付上下文聚合根）（Phases 76–81，6 阶段 / 38 需求）已 feature-complete（2026-06-26，6/6 phase / 38/38 需求）**，待里程碑审计后归档。

| Phase | Requirements | Status |
|-------|--------------|--------|
| 76. 命名腾挪（Project→Space 重构前置） | RENAME-01/02 | ✅ Complete |
| 77. 项目聚合根 + 身份映射 + 成员协作 | PROJ-01~05, IDENT-01, MEMBER-01~03 | ✅ Complete |
| 78. 飞书触发建项目 + 看板枚举 + 工作项组合 | FSPROJ-01~03, COMPOSE-01/02 | ✅ Complete |
| 79. 工件/依赖项（可配置类型 + 实例 + RAG）+ 知识关联 | ARTIFACT-01~05, KLINK-01/02 | ✅ Complete |
| 80. 项目记忆 + MR 实体 + 上下文召回接入 Web 会话 | MEM-01~04, RECALL-01~03, MR-01/02 | ✅ Complete |
| 81. Cursor 回流 + 前端项目工作台 | CURSOR-01~03, UI-01~03 | ✅ Complete |

**Execution order:** 76 → 77 → 78 → 79 → 80 → 81（线性）。依赖链：76（命名腾挪）是硬前置，必须全绿再推进；77（聚合根 + 身份 + 成员）立地基；78（飞书触发 + 组合）与 79（工件 + 知识关联）分别构建组合与依赖；80（记忆 + MR + 召回）把上下文接通会话；81（Cursor 回流 + 前端工作台）打通双向闭环与可视。

**UI 触面（标 UI hint）:** Phase 77（项目创建/成员）、Phase 79（工件查看/类型管理）、Phase 80（记忆编辑/召回）、Phase 81（项目工作台集中前端）。`/gsd-ui-phase` 应介入 81，可选介入 77/79/80。76/78 以后端为主。

**关键约束 / 设计底座（plan-phase 必读）:** 命名已锁定大重构（Project→Space，76 独立前置）；不做迭代实体（另一迭代=新项目）；记忆为自由文本 + 时间戳/贡献者、人工为主 + LLM 提议确认；工件文字载体可全文 RAG、UI 稿仅元数据；飞书无整板枚举 API（经子项字段派生）；身份映射是主R/协作/归因/Cursor 上报的前置；复用 `KnowledgeEntity/Edge` 做项目↔知识/项目间关联、复用 `delivery.WorkItem` 做 story/缺陷、复用 `delivery_knowledge` 召回；脱敏不可绕过 + 后台任务带 `initiated_by_user_id` + 新增 LLM/召回埋点。完整方案见 `.planning/project-aggregate/MILESTONE-PROPOSAL.md`。

各历史里程碑详情归档在 `.planning/milestones/`，要点见 `MILESTONES.md`。

---
*Previous milestones archived in .planning/milestones/*
