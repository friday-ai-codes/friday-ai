# Phase 50: spec 状态机 + 变更记录 + 评审状态 + 前端展示 - Context

**Gathered:** 2026-06-17
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — 灰区由设计文档 + 实地读码自动决策，未向用户提问)

<domain>
## Phase Boundary

让 Phase 49 落的 `SddSpec` 具备完整可治理生命周期：状态机流转（单一 service 入口、非法流转被拒）、不可篡改评审记录（评审驱动状态）、前端 spec 列表/详情/状态/评审可见可操作。

**In scope:**
- `SddSpec` 状态机流转（SPECST-01）：`draft → in_review → approved → implemented → archived`，经单一 service 入口，非法流转拒绝
- `SddSpecReview` 不可篡改评审记录（SPECST-02）：reviewer / decision(approve|reject) / comment / time，审批驱动状态
- 前端 spec 列表 + 详情（含正文/状态/评审历史）+ 状态流转操作（提交评审/批准/驳回）（SPECST-03）

**Out of scope（本 phase）:**
- 编码前置 gate 消费 `approved`（Phase 51）
- spec↔实现 PR 关联 + 交付验收视图（Phase 52）；`implemented` 由 Phase 51/52 编码/PR 触发，本 phase 仅提供 `mark_implemented` service 方法 + 手动入口
- 评审接入统一 `AuditEvent`（v0.10）；本 phase 评审记录自持久化即审计留痕
</domain>

<decisions>
## Implementation Decisions（smart discuss 自动决策）

### D-50-1 状态机：合法流转表 + 单一 service 入口（INV-6）
扩 `SddSpecService`（Phase 49 已建 `create_draft`）加状态流转方法，**合法流转表**：
- `submit_for_review`: `draft → in_review`
- `approve`: `in_review → approved`（建 approve 评审记录驱动）
- `reject`: `in_review → draft`（建 reject 评审记录驱动，退回修订）
- `mark_implemented`: `approved → implemented`（本 phase 提供方法 + 手动入口；Phase 51/52 编码/PR 触发）
- `archive`: 任意非 archived → `archived`（手动归档）
非法流转（如 `draft → approved`、`archived → *`）抛 `SddSpecTransitionError`（fail-loud），前端/API 转 400。状态变更经条件 `.filter(status=from).update(status=to)` + 影响行数判定（幂等 + 防并发双推进，复用 RepoCodingTaskService 范式）。

### D-50-2 `SddSpecReview` 不可篡改评审记录
新建 `server/delivery/models/sdd_spec_review.py`：`spec` FK(→SddSpec, CASCADE)、`reviewer` FK(→ accounts User, SET_NULL null)、`decision` choices `approve/reject`、`comment` TextField(blank)、`created_at`。**append-only**：模型层无 edit/delete 业务方法（守 INV-6 + 不可篡改），评审历史即审计留痕。`approve`/`reject` 经 `SddSpecService` 在**单一事务**内建评审记录 + 驱动状态流转（原子，不留「记录建了状态没变」或反之）。

### D-50-3 评审权限：approve/reject 限 superuser；submit/view 限认证用户
对齐既有「系统管理员=superuser，不新建角色」决策（v0.2.0 admin 会话后台范式）：
- `submit_for_review` / 查看 spec 列表详情：任意认证用户（`IsAuthenticated`）
- `approve` / `reject` / `archive` / `mark_implemented`：`IsSuperUser`
- `reviewer` 记 `request.user`（不可篡改留痕）。更细 RBAC（空间 admin 评审）留 follow-up。

### D-50-4 REST API：独立 spec 端点（对齐既有 idiom）
新建 spec REST（adrf，对齐 Phase 24 exclusions / Phase 25 chunk-at idiom）：
- `GET /api/specs/`（list，支持 `?status=` / `?repository_id=` 过滤，默认全部）
- `GET /api/specs/<uuid:spec_id>/`（detail：spec + 当前 Document 正文 + 评审历史 + 关联 work_item/plan_version/repository 摘要）
- `POST /api/specs/<uuid:spec_id>/transition/`（body `{action, comment?}`：submit_for_review/approve/reject/mark_implemented/archive；权限按 D-50-3 分流；非法流转 400）
序列化器全字段 read_only（状态仅经 transition action 改，禁直接 PATCH，对齐 Phase 24 范式）。spec 不存在 404；被排除/无权限不泄漏。

### D-50-5 前端 spec 治理界面（SPECST-03，本里程碑最重前端）
新增页面 + API client + i18n：
- `web/src/api/specs.ts`（list/detail/transition）+ TS 类型
- spec 列表页（路由 `/specs`，按状态/仓库过滤，状态徽标复用色彩语义）
- spec 详情页（`/specs/[id]`：正文 markdown 渲染、状态徽标、评审历史时间线、关联 work_item/plan/repo 链接）
- 状态流转操作：提交评审/批准/驳回/归档按钮，按当前状态 + 用户权限（superuser 才显示 approve/reject）显隐；操作带确认 + comment 输入（评审）
- i18n zh-CN 默认中文；守护测试以真实 zh-CN.json 断言关键文案
- 复用既有设计系统（reka-ui + tailwind）、useConfirmDialog、TanStack Query 派发→invalidate 范式

### D-50-6 状态徽标组件复用
spec 状态徽标镜像 Phase 48 `SddMethodologyBadge` / 既有 `EntityKindBadge` 范式（按 status 映射色彩：draft 灰 / in_review 琥珀 / approved 绿 / implemented 蓝 / archived 中性），可被列表 + 详情共用。

### D-50-7 零回归 + INV-6 守护
- 状态流转/评审写入只经 `SddSpecService`（grep 守护扩展 test_sdd_spec_inv6_guard 含 SddSpecReview）。
- Phase 49 既有 `create_draft` 幂等/产 spec 链路零回归。
</decisions>

<code_context>
## Existing Code Insights

- **SddSpec / SddSpecStatus**（Phase 49）：`server/delivery/models/sdd_spec.py`——状态全枚举已定义（draft/in_review/approved/implemented/archived），本 phase 加流转逻辑。
- **SddSpecService**（Phase 49）：`server/delivery/services/sdd_spec_service.py`——已有 `create_draft`；本 phase 加 `submit_for_review/approve/reject/mark_implemented/archive`（单一写入入口 INV-6）。
- **条件更新防双推进范式**：`RepoCodingTaskService`（`server/delivery/services/repo_coding_task_service.py`）——`.filter(status=from).update(status=to)` + 影响行数判定，可镜像状态流转。
- **REST idiom**：Phase 24 `sensitive-suggestions`（独立 APIView + 显式 `<uuid>/action/` 路由 + 全 read_only 序列化器 + 专用 action 改状态）、Phase 25 `chunk-at`（adrf APIView + IsAuthenticated）。
- **管理员权限范式**：v0.2.0 `IsSuperUser`（admin 会话后台 `server/chat/admin_views.py`）；`common.permissions` / `server/permissions/`。
- **前端范式**：Phase 24 `SensitiveSuggestionsPanel.vue`（list + action + useConfirmDialog + invalidate + 真实 zh-CN.json 守护）、Phase 23 `ReconcilePanel.vue`（派发→轮询）、徽标 `EntityKindBadge.vue` / Phase 48 `SddMethodologyBadge.vue`；路由 file-based（`web/src/pages/`）；API client `web/src/api/`（barrel）；i18n `web/src/locales/zh-CN.json`。
- **Document 正文**：`SddSpec.document.current_version.content`（markdown）——详情页渲染（前端已有 markdown 渲染，复用 chat/knowledge 既有渲染器）。
- **accounts User**：`reviewer` FK 引用既有用户模型（`server/accounts/` 或 settings.AUTH_USER_MODEL）。
</code_context>

<specifics>
## Specific Ideas

- 新文件：`server/delivery/models/sdd_spec_review.py`（`SddSpecReview` + `ReviewDecision` 枚举）；`SddSpecService` 扩流转方法 + `SddSpecTransitionError`；spec REST views/serializers + urls；migration（SddSpecReview 表 + 可能的 SddSpec 无新字段）。
- 前端：`web/src/api/specs.ts` + TS 类型、`web/src/pages/specs/index.vue` + `[id].vue`、`SddSpecStatusBadge.vue`、i18n、导航入口。
- 守护测试：
  - 后端：合法流转逐条通过 + 非法流转 raise + 幂等（重复 approve no-op/拒绝）+ approve/reject 原子建评审记录并驱动状态 + 评审不可篡改（无 edit 方法）+ 权限（非 superuser approve 403）+ list/detail/transition API + INV-6 grep 守护（含 SddSpecReview）。
  - 前端：列表渲染 + 状态徽标 + 详情评审历史 + 操作按钮按状态/权限显隐 + transition 派发 invalidate + 真实 zh-CN.json 文案。
- 后端 ruff + pytest + makemigrations --check；前端 vue-tsc + eslint + vitest。
</specifics>

<deferred>
## Deferred Ideas

- 编码前置 gate 消费 `approved`（Phase 51）。
- spec↔实现 PR 关联 + 交付验收视图（Phase 52）；`implemented` 自动由编码/PR 触发（本 phase 仅手动 + 提供方法）。
- 评审接入统一 `AuditEvent`（v0.10）。
- 更细评审 RBAC（空间 admin 评审、多级会签）——follow-up / Out of Scope。
- spec 正文在线编辑/版本回滚 UI——暂不做（本 phase 只读展示 + 状态流转）。
</deferred>
