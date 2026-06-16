---
phase: 37-canonical-technicalplan-technicalplanservice
status: verified
verified_at: 2026-06-16
method: goal-backward
plans_executed: [37-01, 37-02, 37-03]
result: PASS
---

# Phase 37 Verification — canonical TechnicalPlan + TechnicalPlanService + 旧路径软链/迁移

**Goal（DOMAIN §5）**：立 canonical 方案脊柱与统一写入入口，把存量 3 条 plan 路径渐进收敛（不全量双写、不爆改）——canonical 唯一事实源落库 + service 唯一入口 + 旧路径软链/lazy 迁移。

逐项 goal-backward 验证 4 条成功判据，全部 TRUE。

---

## SC-1：canonical 方案可落库 + INV-2 — ✅ TRUE

**判据**：canonical `TechnicalPlan`/`PlanVersion` 可持久化（origin/status/version/supersedes 版本链 + content=MergedPlan schema）；`TechnicalPlan.work_item` 可 null 且删 WorkItem 不删 plan（SET_NULL，INV-2）。

**证据**：
- 模型 `server/delivery/models/technical_plan.py`：`TechnicalPlan`（origin/status 枚举、current_version 循环 FK 经字符串引用）、`PlanVersion`（version + supersedes self FK + content JSONField + `unique_together(plan, version)`）、`PlanExternalRef`。
- migration `delivery/migrations/0010_technicalplan_planversion_planexternalref.py` 单 migration 建 3 表，已 `migrate` 成功（apply OK）。
- `work_item = FK(WorkItem, null=True, on_delete=SET_NULL)`。
- 测试 `test_technical_plan_models.py`：`test_inv2_nullable_work_item_and_default_status`（work_item=None 合法、status 默认 draft）、`test_work_item_set_null_on_delete`（删 WorkItem→work_item_id 置 None、plan 存活）、`test_version_chain_supersedes_and_unique_together`、`test_plan_external_ref_unique_and_cascade` —— 全绿。
- `makemigrations --check --dry-run` → No changes detected（schema 与模型一致）。

## SC-2：方案落库唯一经 TechnicalPlanService + INV-6 无旁路 — ✅ TRUE

**判据**：所有方案创建/版本/关联只经 `TechnicalPlanService`（INV-6），grep 守护无旁路写 `TechnicalPlan`/`PlanVersion`。

**证据**：
- service `server/delivery/services/technical_plan_service.py`：`create_from`（eager 建 plan+v1+current）/ `add_version`（hash 相等复用不翻版本 / 不等建 supersedes 链并推进 current）/ `archive` / `resolve` / `link`，唯一含 `TechnicalPlan.objects.create` + `PlanVersion.objects.create`。
- content 校验复用 `workflows.schemas.technical_plan.validate_technical_plan`（PF-02），非法 `raise PlanContentInvalid` 不落库。
- `content_hash` = 本地 `sha256(canonical JSON sort_keys)`，**不 import knowledge**（INV-3 边界）。
- INV-6 守护 `test_technical_plan_inv6_guard.py`：`test_inv6_no_bypass_canonical_plan_write`（全 server/ 源码扫描无旁路写）+ `test_inv6_writer_module_actually_writes_canonical`（守护有效性）—— 全绿，含 37-03 chat 入口接线后仍通过（接线调 service 非旁路）。
- service 行为 `test_technical_plan_service.py` 10 用例全绿（create_from/add_version/archive/resolve/link）。

## SC-3：旧 3 路径软链 + eager 示范 + lazy 迁移 — ✅ TRUE

**判据**：存量 3 路径首次读无 canonical → lazy 建 canonical + 回填软链（不全量双写）；至少一条旧路径 eager 投影示范挂软链。

**证据**：
- 软链字段：`chat.CodingPlan.canonical_plan_id` / `mcp_tools.McpWorkItemTechnicalPlan.canonical_plan_id`（UUIDField 软链，无跨 app 硬 FK；migration chat 0022 / mcp_tools 0008 已 apply）；workflow 经 `delivery.PlanExternalRef` 映射表。
- lazy 迁移 `resolve`：忠实取材 `chat_codingplan_to_content` / `mcp_plan_to_content`，产物过 `validate_technical_plan`。
- eager 示范：`agents/tools/coding_tools.py:create_coding_plan` 创建 CodingPlan 后 best-effort `create_from`+`link` 回填 `canonical_plan_id`（lazy import 防循环、try/except 不阻断）。
- 测试 `test_technical_plan_lazy_migration.py`：`test_lazy_chat_builds_canonical_and_backfills` / `test_lazy_mcp_builds_canonical_and_backfills` / `test_lazy_workflow_link_then_resolve_hit_else_not_found`（含 PlanNotFound）+ `test_resolve_idempotent_no_rebuild`（再 resolve 读不重建）。
- 测试 `test_chat_eager_projection.py`：`test_chat_create_entry_eager_projects_canonical`（入口建 plan→canonical_plan_id 自动回填 + TechnicalPlan(origin=chat, work_item=None)）+ `test_eager_projection_best_effort_does_not_block`（投影抛错 → CodingPlan 仍创建成功）—— 全绿。

## SC-4：迁移期旧表只读历史 / 冲突以 canonical 为准 / 归档不级联 — ✅ TRUE

**判据**：迁移期旧表只读历史、冲突以 canonical 为准、归档不级联删旧表（DOMAIN §5.4）。

**证据**：
- 冲突以 canonical 为准：`resolve` 软链命中分支直接读 canonical（不被旧记录覆盖）；`test_conflict_canonical_wins`（lazy 建后 add_version 改 canonical → 再 resolve 读 canonical 最新 current_version）。
- 归档不级联：`archive` 仅置 `status=archived`，不触碰旧表 / 不删 PlanVersion；`test_archive_no_cascade_keeps_old_record_and_link`（archive 后 CodingPlan 仍在、canonical_plan_id 仍指向、PlanVersion 仍在）+ service 层 `test_archive_sets_status_no_cascade`。
- 旧表只读：本 phase 未改旧表写入入口为操作 canonical（DOMAIN §5.4 旧表只读历史；编辑入口改操作 canonical 列 deferred 至后续），lazy 兜底保证不断层。

---

## Test Evidence Summary

- Phase-37 专项测试：`test_technical_plan_models.py`(6) + `test_technical_plan_service.py`(10) + `test_technical_plan_inv6_guard.py`(2) + `test_technical_plan_lazy_migration.py`(6) + `test_chat_eager_projection.py`(2) = **26 passed**。
- 回归：`tests/delivery` + `tests/test_coding_tools.py` + `tests/test_coding_plan_model.py` + `tests/mcp_tools` = **379 passed**（无回归）。
- migrations：delivery 0010 / chat 0022 / mcp_tools 0008 已生成并 apply；`makemigrations --check --dry-run` → **No changes detected**。
- ruff format/check：新增模型/service/测试/接线文件全部通过（行宽 100）。

## Locked Decisions Honored

- ✅ canonical 落 delivery app + curated re-export + UUID pk
- ✅ work_item nullable FK SET_NULL（INV-2）
- ✅ current_version 循环 FK 经字符串前向引用单 migration
- ✅ content 经 validate_technical_plan 校验（PF-02）
- ✅ content_hash 本地 sha256 canonical JSON，不 import knowledge（INV-3）
- ✅ chat/mcp canonical_plan_id 软链（无跨 app 硬 FK）；workflow 经 PlanExternalRef
- ✅ TechnicalPlanService 唯一写入入口（INV-6）+ grep 守护
- ✅ archive 不级联；hash 相等不翻新版本

## Deferred (out of this phase, per CONTEXT)

- mcp/workflow 旧入口改 eager 投影（lazy 兜底；40/41 接 orchestration 时顺带）。
- 架构师融合真实产 MergedPlan 落 canonical（Phase 40）。
- 旧表编辑入口改为操作 canonical 列（DOMAIN §5.4 全量收敛，超本 phase 范围）。

**Verdict: PHASE 37 GOAL ACHIEVED — all 4 success criteria TRUE.**
