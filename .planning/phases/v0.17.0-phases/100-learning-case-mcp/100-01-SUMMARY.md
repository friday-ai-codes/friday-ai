---
phase: 100-learning-case-mcp
plan: 01
status: complete
date: 2026-07-15
---

# Phase 100 Plan 01: EntityKind 扩展 + natural key 规则表 + vector_recall 吞参修复 Summary

**一句话**：`EntityKind.LEARNING_CASE` 枚举 + migration 0008 三段式约束重建 + natural key 规则表 4 新行定版 + `vector_recall.py` 显式 entity_kinds 严格过滤（交集空 = 空结果零查询，不回退全量）。

## What Was Built

### Task 1: natural key 规则表扩表 + EntityKind.LEARNING_CASE + migration 0008

- `server/knowledge/models.py`
  - `EntityKind` 新增 `LEARNING_CASE = "learning_case", "经验案例"`（字面值 13 字符，`max_length=20` 不改字段），带 v0.17.0 Phase 100（KNOW-01）中文注释（参照 Phase 79 PROJECT/REPOSITORY/SPACE 注释风格）。
  - `generate_entity_id` docstring 规则表新增 4 行：`learning_case`（kind=learning_case）、`mcp_coding_plan`（kind=tech_plan）、`mcp_repository_analysis`（kind=document）、`mcp_execution_trace`（kind=code_change）。
  - 规则表下方存档 locked decision：Chat `coding_plan` 与 MCP `mcp_coding_plan` 保持不同实体 + 边显式关联（RELATES_TO / 共享 work_item 锚），不做硬去重；work_item 锚一律沿用 `feishu_work_item` + `{project_key}:{work_item_type_key}:{work_item_id}` 既有行。
- `server/knowledge/migrations/0008_extend_entity_kind_learning_case.py`
  - 结构与 0007 先例一致：`RemoveConstraint(kentity_kind_valid)` → `AlterField(kind, choices 含 learning_case)` → `AddConstraint(kentity_kind_valid, kind__in 含 learning_case)`。
  - origin 枚举未动（makemigrations 未生成 origin 操作，符合预期——MCP origin 已存在）。
- `server/knowledge/sources/__init__.py`
  - `_NORMALIZERS` 一次性预注册 4 个 Phase 100 条目（`learning_case` / `mcp_coding_plan` / `mcp_repository_analysis` / `mcp_execution_trace`），沿用 13-02 先例（模块落地前 `get_normalizer` 触发 ImportError 响亮失败），避免 100-02/03 并行改同一注册表。
- `server/tests/knowledge/test_models.py` 新增 3 用例：learning_case natural key 同参确定性；`kind=learning_case` 落库过 CHECK 约束；非法 kind 仍被 `kentity_kind_valid` 拒绝（回归）。既有参数化用例 `test_entity_four_kinds_create_and_readback` 自动覆盖新枚举值。

### Task 2: vector_recall kind 过滤修复（吞参 bug）

- `server/knowledge/vector_recall.py`
  - `_DEMAND_KINDS` 纳入 `EntityKind.LEARNING_CASE`（WORK_ITEM/TECH_PLAN/LEARNING_CASE），注释标注 Phase 100 KNOW-02。
  - 吞参修复：显式传入 `entity_kinds` 时各分路取「传入 kinds ∩ 分路白名单」严格过滤——交集为空则该分路不发 Qdrant 查询；两分路皆空直接返回 `[]`，且短路在 embedding 生成之前（省一次远程调用）。删除 `or demand_allowed` / `or list(_CODE_KINDS)` 回退写法。`entity_kinds=None` 保持既有 demand/code 分路口径零回归。
  - `knowledge_vector_recall_completed` 结构化事件追加 `entity_kinds` 字段（维持单条 completed 事件，不新增 INFO 刷屏点）。
- `server/tests/knowledge/test_vector_recall.py` 新增 4 用例（复用既有 `recall_deps` monkeypatch 范式）：
  - `entity_kinds=["learning_case"]` → 仅 demand 分路 1 次 hybrid 调用，filter 值集合 == `{"learning_case"}`；
  - `entity_kinds=["nonexistent_kind"]` → 0 次 hybrid 调用、返回 `[]`（证伪型断言，修复前必失败）；
  - `entity_kinds=["code_change"]` → 仅 code 分路 1 次调用（demand 交集空被跳过）；
  - `entity_kinds=None` → route quota（demand 7 / code 3）零回归 + demand 白名单含 work_item/tech_plan/learning_case。

## Deviations from Plan

1. **[执行状态发现] Task 1 部分改动已在工作区**：执行开始时 `models.py`、`sources/__init__.py` 的改动与 migration 0008 文件已存在于未提交工作区（此前执行尝试遗留）。核对内容与 plan 要求逐项一致后直接采用，补齐缺失的测试用例并统一提交，未重做。
2. **[Scope boundary] 既有测试腐化 2 例，不修复只登记**：`tests/knowledge/test_triggers.py` 的 `test_workflow_plan_generation_delivers_on_success` / `test_workflow_plan_generation_survives_runner_failure` 因 `ModuleNotFoundError: workflows.nodes.ai.plan_generation`（Chassis v2 重构提交 `21116667` 删除该模块）失败，与本 plan 改动无关，已登记 `deferred-items.md`。
3. **[格式] migration 0008 保持 Django 生成原样**：`ruff format --check` 会报 reformat，但既有 0006/0007 migration 同样未格式化（仓库惯例保留 Django 生成格式），为与 0007 先例逐字一致不做格式化。`ruff check`（lint）通过。

## Verification Evidence

- Task 1 验证（makemigrations --check + test_models）：

  ```text
  No changes detected
  ======================= 30 passed, 3 warnings in 47.84s ========================
  ```

- Task 2 验证（test_vector_recall + test_delivery_search）：

  ```text
  ================== 41 passed, 11 warnings in 88.64s (0:01:28) ==================
  ```

- 整体验证（tests/knowledge/ 全量 + makemigrations --check 退出码 0）：

  ```text
  ===== 2 failed, 375 passed, 2 deselected, 32 warnings in 87.24s (0:01:27) ======
  makemigrations-check-exit=0
  ```

  2 failed 均为上述既有 test_triggers 腐化用例（与本 plan 无关）；本 plan 触及的 test_models / test_vector_recall / test_delivery_search 全绿。

- `uv run ruff check` 全部触及文件通过；`ruff format --check` 除 migration（见 Deviation 3）外全部通过。

## Commits

| Commit | 说明 |
| --- | --- |
| `59c8d5e5` | feat(knowledge): EntityKind 扩展 learning_case + natural key 规则表扩表（100-01） |
| `66af7924` | fix(knowledge): vector_recall 显式 entity_kinds 严格过滤（吞参 bug 修复，100-01） |

## Known Stubs

`_NORMALIZERS` 预注册的 4 个模块（`knowledge/sources/learning_case.py` 等）尚未存在——这是 plan 明确的「先注册、100-02/03 落地」策略（落地前 `get_normalizer` 触发 ImportError 响亮失败，非静默 stub）。

## Threat Flags

无新增安全面：T-100-01（吞参信息泄露）已按 threat model mitigate（交集空返回空，`allowed_*` fail-closed 权限闸未动）；T-100-02 migration 三段式照抄 0007 已验证先例；零新依赖。

## Self-Check: PASSED

- `server/knowledge/migrations/0008_extend_entity_kind_learning_case.py` — FOUND
- `server/knowledge/models.py` LEARNING_CASE — FOUND
- `server/knowledge/vector_recall.py` 严格过滤 — FOUND
- Commit `59c8d5e5` — FOUND
- Commit `66af7924` — FOUND
