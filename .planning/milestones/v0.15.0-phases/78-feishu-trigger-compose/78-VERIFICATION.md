---
phase: 78
title: 飞书触发建项目 + 看板枚举 + 工作项组合
milestone: v0.15.0
status: passed
verified: 2026-06-25
requirements: [FSPROJ-01, FSPROJ-02, FSPROJ-03, COMPOSE-01, COMPOSE-02]
---

# Phase 78 VERIFICATION

**判定：`passed`** —— 4 条 Success Criteria 在代码层全部 TRUE + 新增 27 用例全绿 + 全量后端零新增回归
+ `makemigrations --check` 干净。真实飞书凭证下的端到端枚举/事件触发人工验收为**里程碑级 deferred**
（需真实飞书应用，见下"Deferred"），不阻断本期代码层 must-haves。

## Success Criteria → 证据

### SC-1 看板枚举封装（子项 story/缺陷 + 人员带角色，无整板 API 经子项字段派生，失败 fail-soft 降级）✅
- `server/services/feishu_project_board.py::enumerate_board`：读"项目跟踪"工作项 fields → 子项经关联多选
  字段派生（story/缺陷按字段关键字推断类型）、人员经用户类字段派生（带角色映射）。
- 硬路径非 JSON fail-loud（`test_enumerate_hard_path_non_json_fail_loud`）；软路径缺料 → 部分 + warning +
  `degraded=True`（`test_enumerate_no_children_no_people_degraded`）；happy 子项+人员+角色
  （`test_enumerate_happy_children_and_people`）；角色映射表 + 保守默认（`test_map_role_*`）。
- **无整板 listing API**已盘点确认（SUMMARY §飞书枚举能力盘点）。

### SC-2 飞书事件幂等建项目 + 经身份映射拉入看板人员（带身份），重复事件不重复建 ✅
- `initiatives/services/project_board_sync.py::sync_from_board` + `feishu/views.py`
  `is_project_tracking_event` + `_maybe_schedule_project_board_sync`（接入 node/status 事件，后台
  `run_in_background` 带 `initiated_by_user_id`，worker 入口 re-bind）。
- 幂等：`test_idempotent_create_no_duplicate_tops_up`（重复 sync → created False、链接/成员只补齐不重复）；
  拉人身份映射 + 未映射跳过：`test_pull_people_resolves_role_and_skips_unmapped`；
  initiated_by 审计绑定：`test_initiated_by_user_id_bound_in_audit`；事件识别 gate（零回归）：
  `test_is_project_tracking_event_gate`；payload 不泄漏：`test_result_carries_only_scalars_no_raw_payload`。

### SC-3 工作流 `create_project` 节点（建项目 + 拉人带角色 + 关联子项，自动注册可在画布使用）✅
- `workflows/nodes/integrations/create_project.py::CreateProjectNode`（`@register_node` 自动注册、
  INTEGRATION/server_local、default+error 双出口、全中文 config_schema），经同源 `sync_from_board` 落地。
- `test_create_project_node.py`：自动注册 / happy / 缺看板 ref→failed+error / invalid id / Space 未找到 /
  枚举降级仍 completed（8 用例全绿）。节点不直接写表（INV-6）。

### SC-4 组合多 WorkItem（story 复用 delivery.WorkItem 经关系边挂入、手动并入/移除；缺陷同样挂入不重复建模）✅
- `initiatives/models/work_item_link.py::ProjectWorkItemLink`（through + provenance）+ `Project.work_items` M2M
  + `ProjectService.attach/detach_work_item`（INV-6）。
- `test_project_work_item_link.py`：attach 幂等 / board_derived+manual 并存 / detach 幂等 / story 与缺陷
  同表挂入不重复建模（`test_story_and_defect_both_link_without_remodeling`）。INV-6 守护扩 ProjectWorkItemLink。

## 测试与回归证据
- 新增 27 用例全绿。
- 全量后端：**6315 passed / 38 failed / 61 skipped / 8 xfailed**（411s）。
- 38 failed == Phase-76 baseline（`diff` 逐条 `IDENTICAL — ZERO NEW REGRESSIONS`）。
- `makemigrations --check --dry-run`：`No changes detected`。
- 新迁移：`initiatives/migrations/0002_projectworkitemlink_project_work_items_and_more.py`。

## Deferred（里程碑级，需真实外部系统）
- 真实飞书"项目跟踪"看板的子项关联字段 key / 人员字段 key / 角色标签 / 事件 `work_item_type_key`（默认
  `"project"`）的真实 payload 校验 + 端到端枚举/事件触发人工验收 —— 需真实飞书应用（与
  MILESTONE-PROPOSAL §deferred "真实飞书凭证下的端到端枚举/事件触发人工验收 → 里程碑级"一致）。
  代码层以集中映射表 + 保守默认 + fail-soft 降级覆盖，真实 key 经 live UAT 后补登记即可，逻辑不变。
