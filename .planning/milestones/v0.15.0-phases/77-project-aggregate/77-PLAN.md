---
phase: 77
title: 项目聚合根 + 身份映射 + 成员协作
milestone: v0.15.0
status: in_progress
created: 2026-06-25
requirements: [PROJ-01, PROJ-02, PROJ-03, PROJ-04, PROJ-05, IDENT-01, MEMBER-01, MEMBER-02, MEMBER-03]
---

# Phase 77 PLAN — 项目聚合根 + 身份映射 + 成员协作

> 依据 `77-CONTEXT.md` LOCKED 决策 + `MILESTONE-PROPOSAL.md` §5/§6 + 既有代码范式
> （`projects`/`delivery`/`audit`/`permissions`/`notifications`/`feishu`）。

## 落点决策（默认取新 app）

- 新建 Django app **`server/initiatives/`** 承载聚合根 `Project` + `ProjectMember` +
  `ProjectRelation` + `ProjectService` + REST + WS。app label `initiatives`，模型类名 `Project`。
  注册进 `INSTALLED_APPS`（在 `projects`/`accounts`/`permissions`/`delivery`/`feishu` 之后）。
  FK 用字符串引用 `"projects.Space"` / `settings.AUTH_USER_MODEL`，避循环导入。
- `FeishuUserBinding` 落 `feishu` app；`resolve_feishu_user` / `bind_feishu_user` 单一解析
  service 落 `server/feishu/services/identity.py`。

## Waves（顺序执行，原子提交）

### Wave 1 — 模型 + 迁移（PROJ-01/04, MEMBER-01）
- `initiatives/models/project.py`：`ProjectStatus` TextChoices(developing/archived/terminated)；
  `Project`(UUID pk, space FK CASCADE, name, description, status, feishu_project_key,
  feishu_board_url, feishu_board_id, created_by FK SET_NULL, related_projects M2M(self,
  through=ProjectRelation, symmetrical=False), 时间戳)。
  唯一约束：`(space, feishu_project_key)` 仅 `feishu_project_key` 非空时生效（partial UniqueConstraint）。
- `initiatives/models/member.py`：`ProjectRole`(owner/pm/frontend/backend/qa)；`ProjectMember`
  (project FK, user FK, role, created_at, unique_together(project,user))；owner 唯一 = partial
  UniqueConstraint(project, role=owner)。
- `initiatives/models/relation.py`：`ProjectRelation`(source FK, target FK, relation note,
  created_at, unique_together(source,target))。
- 模型层**无业务 create/save**（守 INV-6）。`makemigrations initiatives` → `0001_initial`。
- commit `feat(77): initiatives app + Project/ProjectMember/ProjectRelation 模型`

### Wave 2 — ProjectService 单一写入 + 状态机 + 审计 + 实时推送（PROJ-01/02, MEMBER-03）
- `audit/services/taxonomy.py`：新增 `project.created/updated/status_changed`、
  `project.member_added/member_removed/member_role_changed/owner_transferred`、`feishu_user.bound`。
- `initiatives/services/realtime.py`：`project_group_name(id)` + `apush_project_event` best-effort。
- `initiatives/services/project_service.py`：`ProjectService`（INV-6 唯一写入）：
  `create`(幂等 (space,feishu_project_key) 非空时 get_or_create) / `update` / `change_status`
  (合法流转表 + 非法 fail-loud `ProjectTransitionError`) / `archive` / `terminate`。
  状态/写入经 `AuditService.aemit`(category=caller, component=initiatives, before/after,
  initiated_by_user_id)，写库后 best-effort WS push。
- commit `feat(77): ProjectService 单一写入 + 状态机 + 审计 + 实时推送`

### Wave 3 — 身份映射（IDENT-01）
- `feishu/models.py`：`FeishuBindingSource`(manual/jit) + `FeishuUserBinding`
  (feishu_user_key, open_id, user FK, source, 时间戳；unique(feishu_user_key,user))。
- `feishu/services/identity.py`：`resolve_feishu_user(feishu_user_key=None, open_id=None)->User|None`
  （manual 优先；未映射 fail-soft 返回 None，不抛/不阻断；绝不 log 凭证）+ `bind_feishu_user`
  (manual/jit, get_or_create 幂等)。`feishu` migration。
- commit `feat(77): FeishuUserBinding + resolve_feishu_user 身份映射`

### Wave 4 — 成员 + 主R 转移（MEMBER-01/02）
- `ProjectService`：`add_member` / `remove_member` / `change_member_role` /
  `transfer_owner`(原子降旧 owner + 升新 owner，审计)。全部经审计 + WS push。
- commit `feat(77): 项目成员 CRUD + 主R 唯一/转移`

### Wave 5 — 权限 fail-closed（PROJ-03, MEMBER-02）
- `initiatives/permissions.py`：`aresolve_project_access(user, project, min_role)` 复用
  `permissions.PermissionService.has_project_access`（按 project.space 的 Space 成员权限）；
  非 Space 成员一律拒绝。读 = Space viewer+ / 写(create/status/member) = Space admin+ 或 superuser。
- commit `feat(77): 项目权限 fail-closed（复用 Space 成员权限）`

### Wave 6 — REST API（adrf）+ serializers + urls（PROJ-03/05, MEMBER-01/02）
- `initiatives/serializers.py` + `initiatives/views.py`(adrf APIView)：
  - `GET/POST /api/projects/`（list 按成员/Space 可见过滤；create 幂等）
  - `GET/PATCH /api/projects/{id}/`（retrieve / update）
  - `POST /api/projects/{id}/transition/`（change_status/archive/terminate）
  - `GET/POST /api/projects/{id}/members/` + `PATCH/DELETE /api/projects/{id}/members/{user_id}/`
  - `POST /api/projects/{id}/transfer-owner/`
- `initiatives/urls.py` + `friday/urls.py` 注册 `path("projects/", include("initiatives.urls"))`。
- commit `feat(77): 项目/成员 REST API（adrf + 权限 + 审计）`

### Wave 7 — WebSocket 消费者（MEMBER-03）
- `initiatives/consumers.py`(`ProjectConsumer`：JWT cookie 鉴权 + Space/项目成员校验 + 加入
  `project_{id}` 组 + `project_event` handler) + `initiatives/routing.py`；
  `friday/asgi.py` 接入 patterns（复用 `notifications.middleware.JWTCookieAuthMiddleware`）。
- commit `feat(77): 项目实时推送 WS 消费者`

### Wave 8 — 最小前端创建闭环（PROJ-05）
- `web/src/api/projects.ts` + barrel 导出；`web/src/components/project/CreateProjectModal.vue`
  （选 Space + 飞书看板 URL/key + 名称，vee-validate 风格校验 + reka-ui + i18n zh-CN）。
  不做完整工作台（留 81）。`pnpm vue-tsc --noEmit` 绿。
- commit `feat(77): 最小项目创建前端闭环`

### Wave 9 — INV-6 守护 + 测试
- `tests/initiatives/test_project_inv6_guard.py`（镜像 delivery 范式）。
- `tests/initiatives/test_project_service.py`（CRUD + 幂等 + 状态机合法/非法 + 审计 emit + WS push mock）。
- `tests/feishu/test_feishu_identity.py`（manual/jit/unmapped fail-soft）。
- `tests/initiatives/test_project_members.py`（成员 CRUD + owner 唯一/转移）。
- `tests/initiatives/test_project_permissions.py`（非 Space 成员 fail-closed）。
- `tests/initiatives/test_project_api.py`（端到端 REST）。
- commit `test(77): 项目聚合根 / 身份 / 成员 / 权限 / WS / INV-6 测试`

## 验收（5 条 Success Criteria → 证据）
1. Project 落库 + ProjectService(INV-6) + 状态非法 fail-loud + AuditEvent → Wave 1/2 + tests
2. resolve_feishu_user(手动/jit/未映射 fail-soft) → Wave 3 + tests
3. ProjectMember(多对多+角色) + owner 唯一可转移 → Wave 1/4 + tests
4. CRUD/成员 REST fail-closed + 审计 + WS 推送 → Wave 5/6/7 + tests
5. 前端手动建项目 + (space,feishu_project_key) 幂等 → Wave 6/8 + tests

## 测试基线
Phase 76 baseline：6266 passed，~38 已知既有失败（`/tmp/phase76_baseline_failures.txt`）。
目标：零新增回归；新增测试全绿；`makemigrations --check --dry-run` 干净。
