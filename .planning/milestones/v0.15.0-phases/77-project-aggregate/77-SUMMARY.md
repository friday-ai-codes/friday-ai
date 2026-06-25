---
phase: 77
title: 项目聚合根 + 身份映射 + 成员协作
milestone: v0.15.0
status: complete
completed: 2026-06-25
requirements: [PROJ-01, PROJ-02, PROJ-03, PROJ-04, PROJ-05, IDENT-01, MEMBER-01, MEMBER-02, MEMBER-03]
---

# Phase 77 SUMMARY — 项目聚合根 + 身份映射 + 成员协作

## 落点决策
- **新 app `server/initiatives/`**（默认决策，未回退到 `projects`）：迁移/路由复杂度可控，
  无循环导入，`Project` 聚合根与 `Space`（`projects` app）清晰分离。app label `initiatives`，
  模型类名 `Project`。FK 走字符串引用 `"projects.Space"` / `settings.AUTH_USER_MODEL`。
- `FeishuUserBinding` 落 `feishu` app；`resolve_feishu_user`/`bind_feishu_user` 落
  `server/feishu/services/identity.py`。

## 新增模型（migrations）
| 模型 | 表 | 说明 |
|---|---|---|
| `initiatives.Project` | `initiative_projects` | 聚合根：space FK + status(developing/archived/terminated) + feishu_project_key/board + created_by + related_projects M2M(self) |
| `initiatives.ProjectMember` | `initiative_project_members` | 成员：project+user+role(owner/pm/frontend/backend/qa)；unique(project,user) + partial unique(project, role=owner) |
| `initiatives.ProjectRelation` | `initiative_project_relations` | 项目↔项目 through（symmetrical=False） |
| `feishu.FeishuUserBinding` | `feishu_user_bindings` | feishu_user_key/open_id ↔ User + source(manual/jit) |

- 迁移：`initiatives/migrations/0001_initial.py`、`feishu/migrations/0007_feishuuserbinding.py`。
- `Project` 幂等键：partial UniqueConstraint `(space, feishu_project_key)`（key 非空时）。

## 服务 / 入口
- **`ProjectService`（INV-6 单一写入）** `initiatives/services/project_service.py`：
  `create`（幂等）/`update`/`change_status`+`archive`+`terminate`（状态机，非法 fail-loud
  `ProjectTransitionError`）/`add_member`/`change_member_role`/`remove_member`/`transfer_owner`
  （`ProjectMemberError`）。所有写入经 `AuditService.aemit`（category=caller, component=initiatives,
  before/after 入口强制脱敏, initiated_by_user_id）+ 写库后 best-effort WS 推送。
- **状态机**：合法表 `developing⇄archived`、`{developing,archived}→terminated`，`terminated` 终态；
  同态幂等不审计。
- **身份解析** `feishu/services/identity.py`：`resolve_feishu_user`（manual 优先 → 任意来源；
  未映射 fail-soft 返回 None，不抛/不阻断；不 log 凭证）+ `bind_feishu_user`（get_or_create 幂等）。
- **实时推送** `initiatives/services/realtime.py`：`project_group_name` + `apush_project_event`
  （best-effort，失败不反噬）。
- **审计词表** `audit/services/taxonomy.py`：+8 个 action（`project.created/updated/status_changed/
  member_added/member_removed/member_role_changed/owner_transferred`、`feishu_user.bound`）。

## REST API（adrf，`/api/projects/`）
- `GET/POST /api/projects/`（list 按可见性过滤；create 幂等，201/200）
- `GET/PATCH /api/projects/{id}/`
- `POST /api/projects/{id}/transition/`（非法流转 → 400）
- `GET/POST /api/projects/{id}/members/` + `PATCH/DELETE /api/projects/{id}/members/{user_id}/`
- `POST /api/projects/{id}/transfer-owner/`
- 权限 fail-closed（`initiatives/permissions.py` 复用 `PermissionService`）：读=Space viewer+ 或
  项目成员；写=Space admin+ 或 superuser。非 Space 成员一律 403。

## WebSocket
- `initiatives/consumers.py` `ProjectConsumer`（JWT cookie 鉴权复用 `notifications.middleware`，
  fail-closed 校验 Space/项目成员，加入 `project_{id}` 组）+ `routing.py` + `friday/asgi.py` 接线。

## 前端（最小创建闭环）
- `web/src/api/projects.ts`（+ barrel）；`web/src/components/project/CreateProjectModal.vue`
  （选 Space + 飞书看板 URL/Key + 名称，复用 ui 组件 + i18n zh-CN）。未做完整工作台（留 Phase 81）。

## 测试
- 新增 28 用例全绿：
  - `tests/initiatives/test_project_inv6_guard.py`（INV-6 grep 守护 ×2）
  - `tests/initiatives/test_project_service.py`（CRUD/幂等/状态机合法+非法/审计/WS push mock ×6）
  - `tests/initiatives/test_project_members.py`（成员 CRUD/owner 唯一/转移互换/非成员转移拒绝 ×7）
  - `tests/initiatives/test_project_api.py`（权限 fail-closed/幂等/状态 400/成员 ×7）
  - `tests/feishu/test_feishu_identity.py`（manual/jit/未映射 fail-soft/manual 优先/幂等 ×6）

## 测试结果
- 全量后端：**6294 passed / 38 failed / 61 skipped / 8 xfailed / 1 error**（584s）。
- **38 failed == Phase-76 baseline**（`/tmp/phase76_baseline_failures.txt` 逐条一致，零新增回归）。
- **新增 28 用例全部通过**；`makemigrations --check --dry-run` 干净；`pnpm vue-tsc --noEmit` 绿。
- **1 error（`tests/workflows/test_engine_trigger_data::test_dispatcher_writes_source_key`）= 既有
  跨套件 ordering 污染**，非 Phase 77 回归：该用例单跑通过、`tests/workflows` 单目录跑通过、与全部
  Phase-77 新测试同跑通过；仅在全量套件特定顺序下被既有 flaky 并发用例（baseline 内
  `test_execution_concurrency`，"coroutine never awaited" 事件循环泄漏）下游污染触发。Phase 77
  代码不触 workflows/并发/线程路径。

## 偏差
- 无 app-placement 回退（默认新 app `initiatives` 成立）。
- 写权限默认从严取 Space admin+（CONTEXT "缺省从严"），未额外开放项目 owner 写权限（留后续按需细化）。
- `transfer_owner` 采用"角色互换"语义（旧 owner 接手新 owner 转移前角色），保证转移后两人都是带角色成员。
