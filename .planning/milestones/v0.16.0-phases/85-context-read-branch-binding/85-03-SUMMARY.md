# Phase 85 Plan 03 — Summary（BIND-01：分支↔项目多绑定 + 写收口 + 绑定 REST）

**Status:** ✅ 完成
**Requirements:** BIND-01
**Date:** 2026-06-27

## 交付内容

`ProjectBranch` 多绑定模型（一项目多分支，唯一 `(project, repository, branch_name)`）+
迁移 0008 + `ProjectBranchService` 写收口（INV-6）+ 审计 action + 前端绑定 REST（写仅成员）+
branch↔board 字段。Wave 0 测试（模型/service/INV-6 grep/API）全绿。

## 文件清单

### 新增
- `server/initiatives/models/project_branch.py` — `ProjectBranch` 模型 + `BranchSource` 枚举（manual/plan/coding）。UUID PK；`db_table=initiative_project_branches`；`UniqueConstraint(project, repository, branch_name)`；索引 `branch_name` / `(repository, branch_name)`；`feishu_board_id` 冗余看板字段（branch↔board）；模型层无业务 create/save 方法（INV-6）。
- `server/initiatives/migrations/0008_project_branch.py` — 纯 `CreateModel`（dependencies：`0007_doc_sync_engine` + `repositories.0039_repository_git_instance_credential` + `AUTH_USER_MODEL`）。
- `server/initiatives/services/project_branch_service.py` — `ProjectBranchService.bind / unbind / list_for_project`（分支绑定唯一写入入口）。bind 幂等 `get_or_create` + source 漂移/feishu_board_id 按需回填；写仅成员 fail-closed（`ProjectBranchPermissionError`）；bind/unbind 审计 emit + `initiated_by_user_id` 归因；结构化日志 `project_branch_bound`/`project_branch_unbound`（category=caller, component=initiatives, duration_ms）；async ORM 全经 `sync_to_async`。
- `server/tests/initiatives/test_project_branch_model.py` — 唯一约束 IntegrityError、同项目不同仓/分支并存、source 默认 manual。
- `server/tests/initiatives/test_project_branch_service.py` — bind 幂等、unbind 不存在返回 False、非成员 fail-closed、bind/unbind 审计 emit + 归因、source 漂移回填。
- `server/tests/initiatives/test_project_branch_inv6_guard.py` — INV-6 旁路写表 grep 守护 + writer-actually-writes 正向断言。
- `server/tests/initiatives/test_project_branch_api.py` — 成员 POST 201 / GET 200 / DELETE 204、非成员 403、缺参 400、重复绑定幂等（不 500）。

### 修改
- `server/initiatives/models/__init__.py` — 导出 `ProjectBranch` + `BranchSource`（含 `__all__`）。
- `server/initiatives/services/__init__.py` — 导出 `ProjectBranchService` / `ProjectBranchError` / `ProjectBranchPermissionError`。
- `server/audit/services/taxonomy.py` — 新增 `ACTION_PROJECT_BRANCH_BOUND` (`project.branch_bound`) / `ACTION_PROJECT_BRANCH_UNBOUND` (`project.branch_unbound`)，并入 `ALL_ACTIONS` + `__all__`。
- `server/initiatives/serializers.py` — `ProjectBranchSerializer`（响应）+ `ProjectBranchBindRequestSerializer`（请求，校验 repository_id/branch_name/source/feishu_board_id）。
- `server/initiatives/views.py` — `ProjectBranchListCreateView`（GET 读权限列出 / POST 成员绑定）+ `ProjectBranchDetailView`（DELETE 成员解绑）。写全经 `ProjectBranchService`，无 view 内 ORM 写。
- `server/initiatives/urls.py` — 注册 `projects/<project_id>/branches/`（list/create）+ `projects/<project_id>/branches/<branch_id>/`（delete）。

## 迁移
`server/initiatives/migrations/0008_project_branch.py`（CreateModel only，`makemigrations --check` 干净）。

## 测试结果
- `pytest tests/initiatives/test_project_branch_*.py -q` → **17 passed**。
- `pytest tests/initiatives tests/audit -q` → **330 passed**（无回归；taxonomy 守护通过）。
- `makemigrations initiatives --check --dry-run` → 干净（No changes detected）。
- `ruff check`（本 plan 全部新增/修改文件）→ All checks passed。

## 可观测性
- bind/unbind 经 `AuditService.aemit`（`project.branch_bound`/`project.branch_unbound`，target_type=`project_branch`，metadata 含 component=initiatives / category=caller / initiated_by_user_id，无则 system）。
- 结构化日志 `project_branch_bound` / `project_branch_unbound`（kv + duration_ms + category=caller + component=initiatives）。
- 新增 REST 入口经统一中间件自动纳入 QPS/错误率/时长指标；无 LLM 调用（不涉及 §4.1 call_source）。

## Deferred / Handoff（Phase 89）
- **source=coding 自动绑定**：git push 触发的自动绑定（现 git webhook 仅 MR、无 push 事件）留 Phase 89 调用 `ProjectBranchService.bind(source=coding, _skip_member_check=True)` seam。
- **source=plan 绑定**：方案流水线写入留 Phase 89。
- 本 plan 仅落地手动 REST 绑定（source=manual）+ service 写收口 seam。

## Blockers
无。
