# 82-05 Summary — 工作区 REST 写/读入口 + 空间改归 + visibility 翻转

**Status:** Done
**Wave:** 3
**Requirements:** WS-03, DOC-02

## What shipped

- `ProjectService.update` 白名单加入 `visibility`（可经 PATCH 翻转）；`feishu_folder_token`
  维持**不在**白名单（仅后台 `set_folder_token` 可写，Pitfall 3）。
- 新增 `ProjectService.rehome_space`（专用方法，换 `Project.space` FK）：目标空间不存在
  fail-loud（`ProjectRehomeError`）、同空间幂等（不审计）、审计 `project.space_rehomed`。
- `ProjectDocService.rebuild_workspace` 派发前审计 `project.workspace_rebuilt`（caller，归因
  触发用户）。复用 82-02 既有 `rebuild_workspace`/`upsert_state_api`/`remove_state_api`，未重写。
- taxonomy 登记 `ACTION_PROJECT_SPACE_REHOMED` / `ACTION_PROJECT_WORKSPACE_REBUILT`（__all__/
  定义/ALL_ACTIONS 三处）。
- REST 端点（adrf，IsAuthenticated + 所属 Space 权限闸）：
  - `GET workspace/docs/`（读权限 viewer+/成员）列出 5 文件容器。
  - `POST workspace/rebuild/`（写权限 admin+）调 `ProjectDocService.rebuild_workspace`，202。
  - `POST rehome/`（写权限 admin+）改归空间，目标空间不存在 404、非 admin 403。
  - `GET/POST workspace/state-apis/` + `DELETE workspace/state-apis/<id>/`（读/写权限）写经
    `ProjectDocService`（INV-6 不旁路），(method,path) 幂等。
- 新增 serializers：`ProjectDocSerializer` / `ProjectRehomeSerializer` /
  `ProjectStateApiSerializer` / `ProjectStateApiCreateSerializer`；`ProjectSerializer` 增
  `visibility`/`feishu_folder_token`；`ProjectUpdateSerializer` 增 `visibility`。

## 去重（vs 82-02 / 82-03）

- 飞书 provision 编排（建文件夹 + 5 文件 + 互链 + 看板「📁 项目工作区」描述追加）、
  `upsert_state_api`/`remove_state_api`/`rebuild_workspace` service 半 **已由 82-02 落地**——
  本 plan 仅新增 REST 接线 + audit 一行，未重写。
- 召回 visibility 感知（packer + access_scope）**已由 82-03 落地**——未触碰。
- 写路径成员闸（MemoryService / `_aget_project_for_write` 等）**一字未动**。

## Files

- `server/audit/services/taxonomy.py` — 两个新 action 常量（三处登记）
- `server/initiatives/services/project_service.py` — update 白名单 +visibility；rehome_space + ProjectRehomeError
- `server/initiatives/services/__init__.py` — 导出 ProjectRehomeError
- `server/initiatives/services/project_doc_service.py` — rebuild_workspace 审计 workspace_rebuilt
- `server/initiatives/serializers.py` — visibility/folder_token + 4 新 serializer
- `server/initiatives/views.py` — 5 个工作区视图
- `server/initiatives/urls.py` — workspace docs/rebuild/state-apis + rehome 路由
- `server/tests/initiatives/test_project_workspace_rest.py` — 新增 REST + service 守护测试

## Verification

- `tests/initiatives/test_project_workspace_rest.py` + `test_project_doc_inv6_guard.py` 全绿（17）。
- `tests/audit/test_audit_taxonomy.py` + `tests/initiatives/test_project_service.py` 全绿（11）。
- `tests/initiatives/ -k "member or inv6"` 零回归（24 passed）。
- `manage.py makemigrations --check --dry-run` 干净（无模型变更）。
- ruff 触碰文件全绿。
