---
phase: 77
title: 项目聚合根 + 身份映射 + 成员协作
milestone: v0.15.0
status: passed
verified: 2026-06-25
requirements: [PROJ-01, PROJ-02, PROJ-03, PROJ-04, PROJ-05, IDENT-01, MEMBER-01, MEMBER-02, MEMBER-03]
---

# Phase 77 VERIFICATION

**Verdict: `passed`** — 5 条 Success Criteria 全部为 TRUE；新增测试全绿；零新增回归；
`makemigrations --check` 干净；`vue-tsc` 绿。

## Success Criteria → 证据

### 1. Project 聚合根落库 + ProjectService(INV-6) + 状态非法 fail-loud + AuditEvent ✅
- 模型 `initiatives/models/project.py`（space FK + feishu_project_key/board + status + created_by）；
  迁移 `initiatives/migrations/0001_initial.py`。
- 单一写入 `initiatives/services/project_service.py`；INV-6 grep 守护
  `tests/initiatives/test_project_inv6_guard.py`（通过）。
- 状态机合法表 + 非法 fail-loud `ProjectTransitionError`：`test_project_service.py::
  test_status_machine_illegal_transition_fail_loud` + API `test_project_api.py::
  test_illegal_status_transition_returns_400`（400）。
- AuditEvent：`test_status_machine_legal_transition_audited` / `test_create_emits_audit_and_pushes_ws`
  断言 `AuditEvent` 落库（action=project.created/status_changed, component=initiatives）。

### 2. resolve_feishu_user（manual/jit/未映射 fail-soft）✅
- `feishu/services/identity.py` + `feishu.FeishuUserBinding`（迁移 0007）。
- `tests/feishu/test_feishu_identity.py`：unmapped 返回 None 不抛、manual/jit 解析、manual 优先、
  bind 幂等、缺标识 ValueError —— 6 用例全过。

### 3. ProjectMember(多对多+角色) + 主R 唯一可转移 ✅
- `initiatives/models/member.py`：unique(project,user) + partial unique(project, role=owner)。
- `tests/initiatives/test_project_members.py`：add 幂等、owner 角色拒绝、单 owner 强制、
  转移角色互换且仍单 owner、非成员转移拒绝、owner 不可直接移除 —— 7 用例全过。

### 4. CRUD/成员 REST fail-closed + 审计 + WS 推送 ✅
- `initiatives/views.py` + `permissions.py`（复用 `PermissionService`，fail-closed）。
- `tests/initiatives/test_project_api.py`：非 Space 成员/viewer 创建 403、admin 创建 201、
  outsider retrieve 403、viewer retrieve 200、成员添加 201 —— 全过。
- WS：`ProjectConsumer` + `apush_project_event`；`test_create_emits_audit_and_pushes_ws` 以
  AsyncMock 断言写库后推送被 await。
- 审计：每个写操作经 `AuditService.aemit`（initiated_by_user_id 绑定）。

### 5. 前端手动建项目 + (space,feishu_project_key) 幂等 ✅
- `web/src/api/projects.ts` + `web/src/components/project/CreateProjectModal.vue`（vue-tsc 绿）。
- 幂等：`test_project_service.py::test_create_is_idempotent_on_space_feishu_key` + API
  `test_admin_creates_project_and_idempotent`（第二次 200 返回既有 id，DB 仅 1 行）。

## 测试 / 门禁
- 后端全量：6294 passed / 38 failed（== baseline，零新增回归）/ 1 error（既有 ordering 污染，
  非 Phase 77 回归，详见 SUMMARY）/ 61 skipped / 8 xfailed。
- 新增 28 用例全绿。
- `uv run python manage.py makemigrations --check --dry-run` → No changes detected。
- `pnpm vue-tsc --noEmit` → 0 错误。

## 备注（非阻断）
- 全量套件 1 个 ERROR（`tests/workflows/test_engine_trigger_data::test_dispatcher_writes_source_key`）
  为既有跨套件 async 事件循环泄漏污染（源自 baseline 内 flaky 的 `test_execution_concurrency`），
  单跑/单目录/与新测试同跑均通过，Phase 77 代码不涉 workflows/并发路径。
- 真机层面（真实飞书 user_key/open_id 绑定回流、浏览器端 WS 实时刷新观感）留里程碑级人工验收。
