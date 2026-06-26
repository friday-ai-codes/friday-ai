# 87-03 Summary — BoardSplitService（每 feature 一子看板 + 关联 + 父子降级）+ 工作流节点 + AI 工具

**Plan:** 87-03（Phase 87 看板拆分节点，milestone v0.16.0）
**Requirement:** BOARD-01
**Status:** ✅ Done

## 交付物

### 新增

- `server/initiatives/services/board_split_service.py` — `BoardSplitService`（单一编排收口）
  - `propose_split(*, space, uploaded_text, feishu_url, pasted_text, initiated_by_user_id)`：薄委托 `FeatureListExtractor`（87-02），返回 `{modules, features_flat, degraded, chunk_count}`；记 `board_split_proposed`（caller, +duration_ms/feature_count/degraded）。
  - `create_boards(*, space, proposal, work_item_type="story", parent_work_item_id=None, actor, initiated_by_user_id)`：逐 `features_flat` —
    1. `create_work_item(name=feature名, description=feature原文)`（87-01）拿飞书 work_item_id；建项失败入 `failures` + `board_split_feature_failed` 并 continue（**逐条 fail-soft**）。
    2. `add_work_item_relation(relation_type=1)` 关联项目跟踪（始终尝试，失败仅 warning）。
    3. `detect_relation_capability().parent_child` 为真才挂父子（relation_type=2），否则整体 `degraded_parent_child=True` + hint「请去飞书项目配置中心预配关系类型」（**绝不阻断建看板**）。
    4. `WorkItemService.upsert(..., fetch=False)` 落本地 `delivery.WorkItem`（INV-6）→ `ProjectService.attach_work_item(provenance=board_derived)` 落 `ProjectWorkItemLink`（INV-6，**不旁路写 link**）。
  - 生命周期事件 `board_split_create_started/_completed/_failed`（caller, +duration_ms/created_count/failed_count/degraded_parent_child）；凭证/异常文本经 `redact_secrets_in_text`；观测 best-effort 不反噬。
- `server/workflows/nodes/integrations/board_split.py` — `BoardSplitNode`（`node_type="board_split"`, category=INTEGRATION, execution_mode=server_local，**自动注册**）。config: `feature_list_url`/`feature_list_text`/`uploaded_text`/`work_item_type`（均模板变量）；端到端 `propose_split`+`create_boards`，触发用户取 `workflow_execution.triggered_by_id`（缺 system）；outputs `default`(成功)+`error`(无源/异常)。
- `server/agents/tools/board_split_tools.py` — `split_feature_list_to_boards` `@tool(category="FEISHU")`（AI 会话可调），委托**同一** `BoardSplitService`；`Space.objects.aget` 不存在 → `ToolResult(success=False)`，成功 → `output.data.{created,degraded_parent_child,hint,feature_count}`。
- `server/tests/initiatives/test_board_split_service.py`（8 tests）、`server/tests/workflows/test_board_split_node.py`（5 tests）。

### 修改

- `server/initiatives/services/__init__.py` — 导出 `BoardSplitService`。
- `server/agents/tools/__init__.py` — import + `__all__` 注册 `split_feature_list_to_boards`（与 work_item_tools 同机制收编）。

## 锁定决策落地（LOCKED）

- ✅ 每 feature 一子看板 work_item（名=feature名/描述=feature原文）；模块作分组（`features_flat[].module` 透传）。
- ✅ `relation_type=1` 关联项目跟踪。
- ✅ `ProjectWorkItemLink` 经 `ProjectService.attach_work_item`（INV-6），service 不旁路写表。
- ✅ 父子关系类型经 `detect_relation_capability` 探测，缺失降级（不挂父子 + hint），绝不阻断建看板。
- ✅ 工作流节点（自动注册）+ AI 工具双入口共用唯一 `BoardSplitService`。
- ✅ 复用 87-01（create_work_item / add_work_item_relation / detect_relation_capability）+ 87-02（FeatureListExtractor）+ 82（ProjectWorkItemLink / ProjectService）。
- ✅ 逐条 fail-soft。

## 测试结果

- `tests/initiatives/test_board_split_service.py` + `tests/workflows/test_board_split_node.py`：**13 passed**。
- INV-6 守护 `test_project_inv6_guard.py`（全 server 源码扫描）：passed（board_split_service 无旁路写 link）；新增 service 内 grep 守护亦 passed。
- 回归：`tests/initiatives` **290 passed**；`tests/agents` + `tests/workflows` **707 passed**。
- 节点/工具可发现性：`NodeRegistry.get('board_split')` ✅；`ToolRegistry.get_tool('split_feature_list_to_boards')` 为 FEISHU 类 ✅。

## 已知 / Deferred

- **2 个预存在失败**（非本 plan 引入）：`tests/workflows/test_execution_concurrency.py::{test_pending_execution_blocks_new_start, test_concurrent_starts_allow_only_one}` —— 独立运行亦失败，涉及 scheduler 的 sqlite `select_for_update` 并发行锁（本 plan 未触碰调度器/引擎代码）。
- `parent_work_item_id`（关联项目跟踪/父子的 target）解析顺序：显式入参 > `Project.feishu_board_id`（数值串）；缺失时跳过关联并 warning（看板仍建）。
- 飞书写 API 端点/请求体/关系 relation_type 取值仍为 87-01 `[ASSUMED]`（A-CREATE / A-REL / A-DEGRADE），真机验证 deferred 记 `87-UAT.md`；父子 `relation_type=2` 为假定值。
