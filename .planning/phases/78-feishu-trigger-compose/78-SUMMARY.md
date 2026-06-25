---
phase: 78
title: 飞书触发建项目 + 看板枚举 + 工作项组合
milestone: v0.15.0
status: complete
completed: 2026-06-25
requirements: [FSPROJ-01, FSPROJ-02, FSPROJ-03, COMPOSE-01, COMPOSE-02]
---

# Phase 78 SUMMARY — 飞书触发建项目 + 看板枚举 + 工作项组合

## 飞书枚举能力盘点（CRITICAL FIRST STEP 结论）

盘点 `server/services/feishu.py` / `feishu_parsing.py` / `server/feishu/client.py` 现有端点：

- **整板 listing API：不存在**。飞书项目（Meegle）无"一次列出看板下所有子项/成员"的接口。
- 可用端点：`get_work_item`（`POST .../work_item/{type}/query`，硬路径 `strict_response_json`
  fail-loud）、`get_work_item_relations`（`safe_response_json` fail-soft，PF-10 实测常降级 `[]`，不可靠）。
- **结论：枚举只能经"项目跟踪"工作项的 fields 派生**——子项经关联多选字段
  （`work_item_related_multi_select`，复用 Phase 27 `derive_relations_from_fields`/`extract_related_ids`），
  人员经用户类字段（`field_type_key in {user, multi_user, role,...}`）。
- **降级需要 = 是**：硬路径（读看板工作项本身）非 JSON → fail-loud；调用方捕获后**降级半自动**
  （仍幂等建项目，子项/成员留待后续 webhook 逐个并入）。软路径（从 fields 派生）缺料 → 部分结果 +
  warning + `degraded=True`，绝不抛。
- **字段 key 不确定性（needs live-Feishu）**：真实看板的子项关联字段 key / 人员字段 key / 角色标签
  尚未经真实飞书 payload 校验，故采用集中映射表 + 关键字推断 + 保守默认（角色默认 `backend`、子项
  类型默认 `story`、缺陷由 `缺陷/bug/issue/defect` 关键字推断为 `issue`）。逻辑不变，真实 key 经
  live UAT 后补登记即可。测试用 respx mock 飞书响应，不依赖真实凭证。

## 新增/改动

### 服务（service）
- **`server/services/feishu_project_board.py`（新）**：看板枚举（FSPROJ-01）。`enumerate_board(client, *,
  feishu_project_key, board_work_item_id, board_work_item_type)` → `BoardEnumeration(work_items, people,
  warnings, degraded)`。集中角色映射表 `ROLE_LABEL_TO_PROJECT_ROLE`（→ ProjectRole，保守默认 backend）
  + `map_role` + 子项类型推断 + 纯函数派生。硬/软路径分治；观测 `board_enumeration_started/completed`
  + duration_ms。不依赖 Django、不新引 SDK。
- **`server/initiatives/services/project_board_sync.py`（新）**：`ProjectBoardSyncService.sync_from_board`
  ——飞书事件 handler 与 `create_project` 节点**同源入口**（FSPROJ-02/03）：① `ProjectService.create`
  幂等建项目 → ② `enumerate_board`（fail-soft：抛错/缺凭证 → 降级半自动仍建项目）→ ③ 拉人带身份
  （`resolve_feishu_user` JIT，owner 角色经 add_member+transfer_owner，未映射跳过）→ ④ 组合子项
  （`WorkItemService.upsert(fetch=False)` 落 canonical + `attach_work_item(board_derived)`）。幂等：重复
  事件不重复建、成员/链接 get_or_create 只补齐。观测带 `initiated_by_user_id`、`component=initiatives`、
  `category=caller`。

### 模型（model + migration）
- **`server/initiatives/models/work_item_link.py`（新）**：`ProjectWorkItemLink`（through）
  `project` FK + `work_item` FK→`delivery.WorkItem` + `provenance`(board_derived/manual) + 时间戳，
  `unique_together(project, work_item)`；`Project.work_items` M2M（through）。story 与缺陷统一复用
  `delivery.WorkItem`（COMPOSE-01/02），缺陷不重复建模。
- 迁移：**`initiatives/migrations/0002_projectworkitemlink_project_work_items_and_more.py`**
  （CreateModel ProjectWorkItemLink + AddField Project.work_items + 2 索引 + 1 唯一约束）。

### ProjectService（INV-6 单一写入扩展）
- `attach_work_item`（get_or_create 幂等，board_derived 自动并入 + manual 手动并入）/
  `detach_work_item`（幂等移除）。审计 `project.work_item_attached/detached`（taxonomy +2 action）+ WS 推送。
- INV-6 grep 守护（`tests/initiatives/test_project_inv6_guard.py`）扩 `ProjectWorkItemLink`。

### 工作流节点
- **`server/workflows/nodes/integrations/create_project.py`（新）**：`CreateProjectNode`（`@register_node`
  自动注册 `create_project`，`NodeCategory.INTEGRATION`，`execution_mode=server_local`），全中文 config_schema、
  inputs=[default]、outputs=[default, error]。execute：render 看板引用 → 解析 Space（显式标识 → 工作流绑定
  空间 → 按 feishu_project_key 查）→ 调 `sync_from_board`；缺看板引用 → failed+error；枚举降级仍 completed
  （输出 degraded/warnings）。节点不直接写表（INV-6）。

### 飞书事件接线
- `server/feishu/views.py`：`is_project_tracking_event(payload)`（据 work_item_type_key 命中
  `PROJECT_TRACKING_WORK_ITEM_TYPE_KEYS={"project"}`，普通工作项一律 False → 零回归）+
  `_maybe_schedule_project_board_sync`（gated，后台 `run_in_background(sync_from_board, initiated_by_user_id=
  <解析触发人或 system>)`，worker 入口 re-bind；只投三元组标量，绝不二次落原始 payload）。接入
  `_handle_workflow_node_status`（拖到节点）与 `_handle_workitem_status`（拖到状态），best-effort 不阻断主流程。

## 文件改动清单（10 文件）
- 新增：`server/services/feishu_project_board.py`、`server/initiatives/models/work_item_link.py`、
  `server/initiatives/services/project_board_sync.py`、`server/workflows/nodes/integrations/create_project.py`、
  `server/initiatives/migrations/0002_projectworkitemlink_project_work_items_and_more.py` + 4 测试文件。
- 改动：`server/initiatives/models/__init__.py`、`server/initiatives/models/project.py`、
  `server/initiatives/services/project_service.py`、`server/initiatives/services/__init__.py`、
  `server/audit/services/taxonomy.py`、`server/feishu/views.py`、`server/tests/initiatives/test_project_inv6_guard.py`。

## 测试结果
- **新增 27 用例全绿**：
  - `tests/services/test_feishu_project_board.py`（枚举 happy/无子项·无人员 degraded/硬路径非 JSON fail-loud/
    角色映射表+保守默认/story vs 缺陷类型推断，6）
  - `tests/initiatives/test_project_work_item_link.py`（attach 幂等/board_derived+manual 并存/detach 幂等/
    story 与缺陷同表挂入不重复建模，4）
  - `tests/initiatives/test_project_board_sync.py`（幂等建项目 dup 补齐/拉人身份映射+未映射跳过/枚举 fail-soft
    降级仍建项目/initiated_by 审计绑定/结果只含标量不泄漏 payload，5）
  - `tests/workflows/test_create_project_node.py`（自动注册/happy/缺 ref→failed/invalid id/Space 未找到/
    枚举降级仍 completed/事件识别 gate，8）
  - `tests/initiatives/test_project_inv6_guard.py`（扩展 ProjectWorkItemLink，2）+ `tests/audit/test_audit_taxonomy.py`（2）。
- **全量后端**：**6315 passed / 38 failed / 61 skipped / 8 xfailed**（411s）。
- **38 failed == Phase-76 baseline**（`/tmp/phase76_baseline_failures.txt` 经 `diff` 逐条一致：
  `IDENTICAL — ZERO NEW REGRESSIONS`）。本轮未出现 77-SUMMARY 记录的"1 跨套件 ordering error"
  （既有 flaky，本轮顺序未触发，非回归）。
- `makemigrations --check --dry-run` 干净（`No changes detected`）。

## 偏差 / 降级 caveats
- **真实飞书字段 key / 事件类型 key 待 live UAT**：子项关联字段 key、人员字段 key、角色标签、"项目跟踪"
  工作项 `work_item_type_key`（默认识别 `"project"`）均按保守约定实现，真实飞书 payload 下的端到端
  枚举/事件触发人工验收为里程碑级 deferred（需真实飞书应用）——见 VERIFICATION `human_needed` 项。
- owner 角色看板人员经"add_member(backend)+transfer_owner"落主R（add_member 禁直设 owner，Phase 77 约束）。
- 飞书无整板 API → 枚举为"读单工作项 fields 派生"，拿不到即 fail-soft 降级半自动（webhook 逐个并入）。
