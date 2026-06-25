# Requirements: Friday AI

**Defined:** 2026-06-25
**Core Value:** 让团队"开箱即用、安全地"把需求自动变成代码——并把"需求→代码"全链路上下文统一收口到一个**在线协作的「项目」聚合根**，让每次对话、Cursor 编码、Agent 调用都能加载该项目的全部历史关联、依赖工件、记忆与召回，并把沉淀写回。里程碑 v0.15.0 在 **6 个 Phase（76–81）** 内交付"项目（交付上下文聚合根）"。

> 完整设计与调研基线见 `.planning/project-aggregate/MILESTONE-PROPOSAL.md`；阶段拆分见 `.planning/ROADMAP.md`（Phases 76–81）。

## v1 Requirements

Milestone v0.15.0 项目（交付上下文聚合根）。每条映射到一个 Phase（见 Traceability）。

### 命名腾挪（RENAME）

- [ ] **RENAME-01**: 后端 `projects.Project` 模型重命名为 `Space`（类名/`related_name`/全栈引用更新），`Project` 名称腾出给新聚合根；既有数据零丢失（`db_table` 保持或一次性迁移），既有"空间"功能（飞书凭证 / Provider 默认 / 仓库 M2M / 成员权限）行为零回归
- [ ] **RENAME-02**: 全栈 `project→space` 内部引用一致更新（serializers/views/permissions/agent tools `space_tools` / workflow 节点 `fetch_space_info` / 各 FK），对外仍称"空间 Space"不变；后端 ~520 + 前端 ~130 测试基线零回归

### 项目聚合根（PROJ）

- [ ] **PROJ-01**: 新建 `Project` 聚合根模型（隶属 `Space`，显式关联一个飞书"项目跟踪"看板，含名称/描述/状态/创建者），经单一写入入口 `ProjectService`（INV-6）
- [ ] **PROJ-02**: 项目状态机（开发中/归档/终止，可扩展），非法流转 fail-loud，状态变更接入统一审计 `AuditEvent`
- [ ] **PROJ-03**: 项目 CRUD REST API（创建/读取/更新/归档/终止），按所属 Space 成员权限 fail-closed
- [ ] **PROJ-04**: 项目可关联其他项目（多对多，用于"历史迭代/相关项目"回看），关系经 `KnowledgeEdge` 或轻量关联表统一建模
- [ ] **PROJ-05**: 用户可在前端手动创建项目（指定 Space + 飞书"项目跟踪"看板 + 名称），以 `(space, feishu_project_key)` 幂等

### 身份映射（IDENT）

- [ ] **IDENT-01**: 飞书人员（`user_key`/`open_id`）↔ Friday `User` 多对多映射（手动绑定 + 飞书事件 JIT 自动绑定），经单一解析入口 `resolve_feishu_user`；未映射时 fail-soft 保留原始 id 可后补绑定

### 成员协作（MEMBER）

- [ ] **MEMBER-01**: 项目成员模型（项目 ↔ 用户 多对多 + 身份角色：主R/产品经理/前端/后端/测试，可扩展），一个用户可属多个项目、一个项目可有多个成员
- [ ] **MEMBER-02**: 主R（owner）唯一且可转移；成员增删改 REST API + 审计；项目对全部成员可见可参与
- [ ] **MEMBER-03**: 项目成员/状态变更经 WebSocket 实时推送，协作者即时可见

### 飞书触发与工作项组合（FSPROJ / COMPOSE）

- [ ] **FSPROJ-01**: 封装飞书"项目跟踪"看板枚举能力——读取该看板下的子关联项（story/缺陷）与人员（带角色），无整板 API 时经子项关联字段派生逐项收集，失败 fail-soft 降级
- [ ] **FSPROJ-02**: 飞书事件触发自动建项目——"项目跟踪"拖到指定节点/状态时，幂等创建同名项目并拉入看板人员（经身份映射带身份），重复事件不重复建
- [ ] **FSPROJ-03**: 工作流"创建项目"节点（`create_project`）——以看板名建项目 + 枚举并拉入人员（身份映射，带角色）+ 关联子项 workitem
- [ ] **COMPOSE-01**: 项目组合多个 WorkItem——story 复用 `delivery.WorkItem` 经关系边挂入项目，支持手动并入/移除
- [ ] **COMPOSE-02**: 缺陷（飞书看板类型=缺陷）作为 `WorkItem` 经关系边挂入项目，不重复建模为工件

### 工件 / 依赖项（ARTIFACT）

- [ ] **ARTIFACT-01**: 可配置工件类型注册表（`ArtifactType`）——内置默认类型（需求文档 / feature list / 研发 Spec / UI 稿 / UI 评审 / 埋点文档 / 埋点评审 / 复盘），后台可新增 / 禁用 / 删除类型
- [ ] **ARTIFACT-02**: 工件实例模型（`Artifact`）——挂到项目，记类型 / 载体（飞书文档 / 飞书表格 / 外链 / md / 仓库文件）/ 链接 / 标题 / 版本 / 贡献者
- [ ] **ARTIFACT-03**: 工件在线查看——飞书文档/表格读取渲染、外链跳转；md / 内部工件可在线编辑
- [ ] **ARTIFACT-04**: 工件 RAG 摄取——文字载体（飞书文档/表格/md/研发 Spec）全文摄取进 `delivery_knowledge` 可召回；图形外链（UI 稿 figma/mastergo）仅存元数据，不强行 RAG 正文
- [ ] **ARTIFACT-05**: 工件类型增删禁用即时生效——禁用类型不可新建实例、既有实例只读保留；删除类型受既有实例约束保护

### 知识关联（KLINK）

- [ ] **KLINK-01**: 项目 ↔ 知识实体（`KnowledgeEntity`）多对多关联（一个知识可属多个项目、一个项目关联多个知识）
- [ ] **KLINK-02**: 项目可关联仓库 / 空间 / 知识 / 其他项目，关系经 `KnowledgeEdge` 统一建模，可查询、前端可视

### 项目记忆（MEM）

- [ ] **MEM-01**: 项目记忆（自由文本条目，支持 append / edit，每条带时间戳 + 贡献者），对项目全部成员共享
- [ ] **MEM-02**: 记忆贡献仅限项目成员；私聊 / 非成员会话不纳入项目记忆
- [ ] **MEM-03**: 记忆可人工编辑 / 覆盖（方案推翻、需求变更时修正），编辑保留可追溯
- [ ] **MEM-04**: LLM 从成员会话提炼记忆草稿 → 人工确认后入库（不自动直接写入）；入库前脱敏不可绕过（`redact_*`）

### 召回与会话接入（RECALL）

- [ ] **RECALL-01**: 项目上下文打包器（context packer）——按项目聚合需求/工件/记忆/关联知识/历史，经 grep(SQL 精确) + RAG(语义) 召回 + 排序 + 压缩，输出可注入 LLM 的上下文，token 预算可降级
- [ ] **RECALL-02**: Web 对话接入项目上下文——会话可绑定项目，`search_delivery_knowledge` 等接入 chat runner 工具白名单，对话自动加载项目上下文
- [ ] **RECALL-03**: 召回面覆盖项目全部文字工件 / 记忆 / 工作项，按项目 scope + 用户权限 fail-closed；新增召回上报条数/分层耗时/score 并写 `RetrievalTrace`

### MR 实体（MR）

- [ ] **MR-01**: MR/PR 独立实体（`MergeRequest`）——关联项目/仓库/分支/工作项，记 url / 源·目标分支 / 状态(open/merged/closed) / review 状态 / 平台 id，经单一写入入口 `MergeRequestService`（INV-6）
- [ ] **MR-02**: 入站 webhook 同步 MR 状态（GitHub/GitLab open/merged/closed/review，脱敏原始 payload 落库），项目内可见 MR 状态

### Cursor 回流（CURSOR）

- [ ] **CURSOR-01**: MCP 分支→项目反查 + 召回——Cursor 经 MCP 用当前分支名（含 `m{work_item_id}`/项目标识）反查项目，召回需求/工件/记忆上下文
- [ ] **CURSOR-02**: Cursor rules 模板——强制"先关联本分支项目、召回上下文，再编码"（随项目下发或文档化）
- [ ] **CURSOR-03**: Cursor 沉淀上报写回——处理完成后经 MCP/API 上报知识，由 Friday 写入项目 memory/知识；带认证 + 归因（身份映射）+ 脱敏 + 质量门槛防噪音

### 前端项目工作台（UI）

- [ ] **UI-01**: 项目列表页（按 Space / 状态 / 成员筛选）+ 创建项目入口
- [ ] **UI-02**: 项目详情工作台——概览 / 成员(带身份) / 工作项 / 工件(在线查看) / 记忆(编辑) / 关联(知识·仓库·项目·PR)
- [ ] **UI-03**: 项目记忆编辑 + LLM 提议确认 UI；工件类型后台管理页（增删禁用）

## Future Requirements

后续里程碑（v2，本里程碑不做）：

- **PROJX-01**: UI 稿多模态 / figma API 接入正文召回
- **PROJX-02**: 结构化记忆 + 时效降权 + 矛盾消解
- **PROJX-03**: 记忆全自动提炼（无人工确认）+ 质量评分门槛自适应
- **PROJX-04**: Cursor 专用插件 / hook 主动行为采集
- **PROJX-05**: 项目级看板可视 / 燃尽 / 进度统计

## Out of Scope

| Feature | Reason |
|---------|--------|
| 迭代实体 | 用户决策：另一迭代 = 新建项目；"看历史迭代" = 项目↔项目关联链回看，避免多一层粒度 |
| UI 稿正文 RAG / 多模态设计理解 | UI 稿是图形链接，纯链接 RAG 不到正文；仅存元数据，多模态/figma API 留 v2（PROJX-01） |
| 结构化记忆 + 自动矛盾消解 / 旧记忆自动降权 | 用户选自由文本 + 人工覆盖；结构化升级留 v2（PROJX-02） |
| 记忆全自动写入（无人工确认） | LLM 提炼仅产草稿，人工确认入库，避免噪音/误导污染共享记忆 |
| 每次对话全量加载项目上下文 | 受上下文窗口限制，本期召回+压缩；全量加载随窗口扩大留未来 |
| Cursor 本地 IDE 专用插件 / hook | 本期走 MCP + git + 上报 API；专用插件留 v2（PROJX-04） |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| RENAME-01 | Phase 76 | ☐ Pending |
| RENAME-02 | Phase 76 | ☐ Pending |
| PROJ-01 | Phase 77 | ✅ Complete |
| PROJ-02 | Phase 77 | ✅ Complete |
| PROJ-03 | Phase 77 | ✅ Complete |
| PROJ-04 | Phase 77 | ✅ Complete |
| PROJ-05 | Phase 77 | ✅ Complete |
| IDENT-01 | Phase 77 | ✅ Complete |
| MEMBER-01 | Phase 77 | ✅ Complete |
| MEMBER-02 | Phase 77 | ✅ Complete |
| MEMBER-03 | Phase 77 | ✅ Complete |
| FSPROJ-01 | Phase 78 | ✅ Complete |
| FSPROJ-02 | Phase 78 | ✅ Complete |
| FSPROJ-03 | Phase 78 | ✅ Complete |
| COMPOSE-01 | Phase 78 | ✅ Complete |
| COMPOSE-02 | Phase 78 | ✅ Complete |
| ARTIFACT-01 | Phase 79 | ✅ Complete |
| ARTIFACT-02 | Phase 79 | ✅ Complete |
| ARTIFACT-03 | Phase 79 | ✅ Complete |
| ARTIFACT-04 | Phase 79 | ✅ Complete |
| ARTIFACT-05 | Phase 79 | ✅ Complete |
| KLINK-01 | Phase 79 | ✅ Complete |
| KLINK-02 | Phase 79 | ✅ Complete |
| MEM-01 | Phase 80 | ☐ Pending |
| MEM-02 | Phase 80 | ☐ Pending |
| MEM-03 | Phase 80 | ☐ Pending |
| MEM-04 | Phase 80 | ☐ Pending |
| RECALL-01 | Phase 80 | ☐ Pending |
| RECALL-02 | Phase 80 | ☐ Pending |
| RECALL-03 | Phase 80 | ☐ Pending |
| MR-01 | Phase 80 | ☐ Pending |
| MR-02 | Phase 80 | ☐ Pending |
| CURSOR-01 | Phase 81 | ☐ Pending |
| CURSOR-02 | Phase 81 | ☐ Pending |
| CURSOR-03 | Phase 81 | ☐ Pending |
| UI-01 | Phase 81 | ☐ Pending |
| UI-02 | Phase 81 | ☐ Pending |
| UI-03 | Phase 81 | ☐ Pending |

**Coverage:**

- v1 requirements: 38 total
- Mapped to phases: 38
- Completed: 23（RENAME-01/02 + PROJ-01~05 + IDENT-01 + MEMBER-01~03 + FSPROJ-01~03 + COMPOSE-01/02 + ARTIFACT-01~05 + KLINK-01/02）
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-25 — milestone v0.15.0 项目（交付上下文聚合根）（6 Phase 76–81）*
