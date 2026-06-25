# Phase 77: 项目聚合根 + 身份映射 + 成员协作 - Context

**Gathered:** 2026-06-25
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，elegant defaults 自动采纳，未提问；决策基于 MILESTONE-PROPOSAL §1/§5 + 既有代码模式）

<domain>
## Phase Boundary

立起 v0.15.0 的领域地基：新建 `Project` 聚合根（隶属 `Space`、关联一个飞书"项目跟踪"看板、含状态机），打通飞书人员↔Friday `User` 身份映射，建项目成员（多对多 + 身份角色），提供 CRUD/权限/实时推送。

**In scope（PROJ-01~05, IDENT-01, MEMBER-01~03）:**
- `Project` 聚合根模型 + `ProjectService` 单一写入入口（INV-6）+ 状态机 + 审计
- `FeishuUserBinding` 身份映射 + `resolve_feishu_user` 单一解析入口
- `ProjectMember` 成员模型（角色枚举，主R 唯一可转移）
- 项目/成员 CRUD REST API（按 Space 成员权限 fail-closed + 审计）+ WebSocket 实时推送
- 项目↔项目轻量关联（PROJ-04）
- **最小前端**：项目手动创建能力（PROJ-05），复用 `web/src/pages/spaces/` 范式

**Out of scope（留后续 Phase）:**
- 飞书看板枚举 / 事件触发建项目 / `create_project` 节点 / WorkItem 组合 → Phase 78
- 工件 / 知识图谱关联（KnowledgeEdge 富建模）→ Phase 79
- 记忆 / MR / 召回 → Phase 80
- **完整项目工作台前端**（列表筛选/详情多 Tab/工件查看/记忆编辑）→ Phase 81（UI-01~03）。本期前端仅交付"创建项目"闭环，不重复实现工作台。
</domain>

<decisions>
## Implementation Decisions

### 模型落点与边界（bounded context）
- **新建 Django app `server/initiatives/`** 承载聚合根 `Project` + `ProjectMember` + 项目↔项目关联 + `ProjectService` + REST API（遵循"Django app = bounded context"约定，与 `Space`(在 `projects` app) 清晰分离，避免与 `SpaceMembership` 混淆）。app label `initiatives`，模型类对外/代码名为 `Project`。
  - 注册顺序在 `projects`/`accounts`/`permissions`/`delivery` 之后；FK 用字符串引用 `"projects.Space"`/`"accounts.User"` 避循环导入。
  - plan-phase 研究若发现新 app 引发不成比例的迁移/路由复杂度，可回退到"放入既有 `projects` app"（但模型类名仍为 `Project`，与 `Space` 并存）——默认取新 app。
- **`FeishuUserBinding` 落 `feishu` app**（飞书域身份），`resolve_feishu_user` 作为单一解析 service（`server/feishu/services/identity.py` 或 `server/services/`，plan-phase 定）；与可观测"谁触发"同源，供 Phase 78/81 复用。

### 项目聚合根（PROJ-01~04）
- `Project` 字段：`id`(UUID) / `space`(FK→projects.Space, on_delete=CASCADE) / `name` / `description` / `status` / `feishu_project_key`(对齐飞书语义，复用现有命名) / 看板引用（如 `feishu_board_url`/`feishu_board_id`，plan-phase 定具体字段）/ `created_by`(FK→User, SET_NULL) / `created_at` / `updated_at`。
- **`ProjectService` 单一写入入口（INV-6）**：所有 create/update/archive/terminate/成员变更收口于此；模型层无业务 create/save 方法（守 INV-6，参照 `delivery`/`AuditService` 范式）。INV-6 grep 守护测试。
- **状态机**：`ProjectStatus` TextChoices = developing(开发中)/archived(归档)/terminated(终止)，可扩展。合法流转表显式定义；**非法流转 fail-loud raise**（如 terminated→developing 拒绝）。状态变更经 `AuditService.aemit`（category=caller, component=initiatives, action=project.status_changed, before/after 脱敏, initiated_by_user_id）。
- **项目↔项目关联（PROJ-04）**：本期用 `Project` 自引用 M2M（through `ProjectRelation`，`symmetrical=False`，可带 relation 备注），用于"历史迭代/相关项目"回看。**KnowledgeEdge 富建模留 Phase 79（KLINK-02）**——本期最小可用关联表，不提前耦合知识图谱。
- 幂等键：`(space, feishu_project_key)` —— `feishu_project_key` 非空时唯一约束 + `get_or_create` 幂等（PROJ-05）；无飞书 key 的手动项目允许（key 为空，靠 id 区分）。

### 身份映射（IDENT-01）
- `FeishuUserBinding`：`feishu_user_key` / `open_id` ↔ `User`（多对多——一个飞书人可对多 Friday 账号、反之亦然，但常态一对一）+ `source`(manual/jit) + 时间戳；`(feishu_user_key, user)` 唯一。
- **`resolve_feishu_user(feishu_user_key|open_id) -> User|None`** 单一入口：手动绑定优先，飞书事件 JIT 自动建绑定（source=jit）；**未映射 fail-soft 返回 None 并保留原始 id**（不抛、不阻断），可后补绑定。绝不把飞书凭证写日志（脱敏规范）。

### 成员协作（MEMBER-01~03）
- `ProjectMember`：`project`(FK) + `user`(FK) + `role` + `created_at`；`unique_together(project, user)`（一人一项目一行）。
- `ProjectRole` TextChoices = owner(主R)/pm(产品经理)/frontend(前端)/backend(后端)/qa(测试)，可扩展。
- **主R 唯一且可转移**：每项目至多一个 owner；转移 = 经 `ProjectService` 原子改两行（旧 owner 降级/卸任 + 新 owner 升级），DB 层约束 + service 守护。
- 项目对**全部成员可见可参与**（无细粒度行内权限，本期）。
- 成员增删改 REST + 审计（AuditEvent）。

### 权限（PROJ-03 / MEMBER-02 fail-closed）
- 项目 CRUD + 成员操作**按所属 Space 成员权限 fail-closed**——复用 `server/permissions/services.py` 既有 Space 三角色权限判定（重命名后为 space 语义）；非 Space 成员一律拒绝（PermissionDenied）。
- 读：项目对其 Space 成员/项目成员可见；写（create/update/member）：按 Space 角色 + 项目 owner 规则 fail-closed。具体矩阵 plan-phase 细化，缺省从严。

### 实时推送（MEMBER-03）
- 复用既有 channels 消费者范式（参照 `workflows/consumers.py`/`runners/routing.py`）：per-project group（如 `project_{id}`），成员/状态变更经 `ProjectService` 写库后 `async_to_sync(channel_layer.group_send)` 推送事件，前端订阅即时可见。best-effort（推送失败不反噬主写入）。

### 前端（PROJ-05，最小闭环）
- 复用 `web/src/pages/spaces/` + `web/src/api/` 范式：新增 `projects` API 模块 + 一个"创建项目"入口（选 Space + 飞书看板 + 名称），TanStack Query + 既有表单（vee-validate+zod）+ reka-ui 组件 + i18n zh-CN。
- **不**在本期做完整工作台（列表筛选/详情多 Tab）——留 Phase 81，避免返工与竞态。对外仍称"项目/Project"。

### 观测与异步（强制规范）
- 新增 REST 入口纳入 QPS/错误率/时长（走统一中间件自动注入 user_id/request_id）。
- `ProjectService`/成员/状态变更经 `AuditService`（category=caller, component=initiatives, 绑定触发用户；后台/事件路径带 `initiated_by_user_id`，系统行为标 `system`）。
- 本期无新增 LLM 调用 / 召回（不触发 call_source/RetrievalTrace 义务）。
- async 视图走 adrf；ORM 在 async 经 `sync_to_async`；脱敏 `redact_*` 不可绕过。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/projects/`（=Space）：模型/serializers/views/permissions 范式，飞书凭证/Provider 默认/仓库 M2M/三角色成员。
- `server/permissions/services.py`：Space 成员权限判定（fail-closed 复用）。
- `server/audit/`（`AuditService.aemit` 单一写入 + 脱敏 + fail-soft，Phase 53）：状态/成员变更埋点直接复用。
- `server/delivery/`：单一写入 service（INV-6）+ append-only 事件 + 状态机范式（`WorkItem`/`status_event`）可直接照搬。
- `server/workflows/consumers.py` / `server/runners/routing.py`：channels WS 推送范式。
- `server/accounts/` + `server/feishu/`：User、飞书 client/webhook（身份映射落点）。
- `web/src/pages/spaces/`、`web/src/api/`、`web/src/stores/`：前端范式。

### Established Patterns
- Django app 即 bounded context；模型 `<app>/models/`；FK 字符串引用；UUID 主键；adrf 异步视图；async ORM 走 `sync_to_async`。
- 单一写入 service + INV-6 grep 守护测试（`test_*_inv6_guard.py`）是本仓固定范式。
- TextChoices 闭集枚举；状态机非法流转 fail-loud。

### Integration Points
- `Project.space` → `projects.Space`；`created_by`/`ProjectMember.user` → `accounts.User`。
- `resolve_feishu_user` 供 Phase 78（飞书拉人带身份）、Phase 81（Cursor 上报归因）复用。
- WS channel layer（dev in-memory / prod redis）已配置。
</code_context>

<specifics>
## Specific Ideas

- `feishu_project_key` 命名与现有 `Space.feishu_project_key`/`delivery.WorkItem.feishu_project_key` 语义一致复用，不另造命名。
- 项目↔项目关联本期走轻量自引用 M2M；Phase 79 再决定是否迁/补 KnowledgeEdge 统一建模（避免现在双写）。
- 主R 转移作为显式 service 操作（非裸 PATCH role），保证原子与审计。
</specifics>

<deferred>
## Deferred Ideas

- 项目↔知识 KnowledgeEdge 富建模、项目↔仓库/空间统一关系图 → Phase 79（KLINK-01/02）。
- 完整项目工作台前端（列表/详情/工件/记忆 UI）→ Phase 81（UI-01~03）。
- 飞书事件/节点/看板枚举建项目 → Phase 78。
- 细粒度行内成员权限（超出"全成员可见可参与"）→ 未来。
</deferred>
