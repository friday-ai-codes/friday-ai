---
phase: 37-canonical-technicalplan-technicalplanservice
title: canonical TechnicalPlan + TechnicalPlanService + 旧路径软链/迁移
verified: 2026-06-16
status: passed
requirements: [PLAN-01, PLAN-02, PLAN-03]
plans_executed: [37-01, 37-02, 37-03]
method: goal-backward
---

# Phase 37 Verification

> 方法：goal-backward —— 从 phase 4 项成功标准倒推，逐项核验代码是否真正交付（非「任务做完」），附可复现证据。

## 结论

**status: passed** —— 4 项成功标准全部 TRUE，证据见下。Phase 37 专项测试 26 项全绿，delivery + chat(coding_tools/coding_plan) + mcp_tools 回归 379 项全绿，`makemigrations --check` 全项目干净，INV-6 grep 守护无旁路写，archive 不级联删旧表。

---

## 成功标准 1（PLAN-01）：canonical TechnicalPlan/PlanVersion 落库 + 可追溯 WorkItem（INV-2）

**判定：✅ TRUE**

- **三模型落库**：`delivery/models/technical_plan.py` —— `TechnicalPlan`（UUID pk + `origin`(chat|mcp|workflow|orchestration) + `status`(draft|under_review|approved|superseded|archived，默认 draft) + `current_version` 循环 FK 经字符串前向引用 SET_NULL related_name="+"）、`PlanVersion`（`version` + `supersedes` self FK + `content` JSONField(§7 MergedPlan) + `content_hash` + `unique_together(plan, version)`）、`PlanExternalRef`（external_ref unique + canonical FK CASCADE）。
- **INV-2 可追溯 + chat null**：`TechnicalPlan.work_item = FK(delivery.WorkItem, null=True, blank=True, on_delete=SET_NULL)`；删 WorkItem 不删 plan（SET_NULL）。守护测试断言 `create(origin="chat")` work_item=None 合法、status 默认 draft、删 WorkItem 后 plan 存活且 work_item_id 置 None。
- **migration**：单 migration `delivery/migrations/0010_technicalplan_planversion_planexternalref.py` 建 3 表（循环 FK 经 AddField 编排）；随测试 DB 成功 apply。
- **证据**：`pytest tests/delivery/test_technical_plan_models.py` → 6 passed（INV-2 / SET_NULL / 版本链 unique_together / PlanExternalRef unique+CASCADE / 软链字段 UUIDField 非 relation）。

## 成功标准 2（PLAN-02）：所有方案创建/版本/关联只经 TechnicalPlanService（INV-6）

**判定：✅ TRUE**

- **唯一写入入口**：`delivery/services/technical_plan_service.py` —— `create_from`（校验 content → 建 plan+v1+置 current_version）/ `add_version`（hash 相等复用不翻版本、不等建 supersedes 链推进 current）/ `archive` / `resolve` / `link`（service:128/169/197/209/269）。`create_from` content 经 `workflows.schemas.technical_plan.validate_technical_plan` 校验（PF-02 对齐 execution_plan），非法 raise `PlanContentInvalid` 不落库。
- **content_hash 本地计算**：`_content_hash` = 本地 `sha256(canonical JSON sort_keys)`，**不 import knowledge**（INV-3 边界）；hash 相等绝不产生新版本（v0.3/v0.6 铁律）。
- **INV-6 grep 守护**：`test_technical_plan_inv6_guard.py` 扫描 `server/` 源码，断言除 `delivery/services/technical_plan_service.py` 外无 `TechnicalPlan/PlanVersion` 旁路写（实例化 / `.objects.create` / `.save()`），排除 tests/migrations/models；并加「守护有效性」反测确认 writer 真写表。同名 dataclass `workflows/schemas/technical_plan.py` 文件白名单豁免（LLM 输出 schema，非 model）。
- **证据**：`pytest tests/delivery/test_technical_plan_service.py tests/delivery/test_technical_plan_inv6_guard.py` → service 行为 + INV-6 守护全绿。

## 成功标准 3（PLAN-03）：3 路径 eager 投影软链 + read-time lazy 迁移（不全量双写）

**判定：✅ TRUE**

- **软链字段（无跨 app 硬 FK）**：`chat/models.py:229` `CodingPlan.canonical_plan_id` + `mcp_tools/models.py:381` `McpWorkItemTechnicalPlan.canonical_plan_id` 均为 `UUIDField(null, blank, db_index)`；workflow 经 `PlanExternalRef`（external_ref 映射表）。migration：chat 0022 + mcp_tools 0008。
- **read-time lazy 迁移**：`resolve(PlanRef)` 按 §5.4 三优先级——软链命中直接 `aget` canonical（**幂等不重建**）/ 无 canonical 但旧记录完整 → lazy `create_from` + `link` 回填软链 / 找不到 → `raise PlanNotFound`。忠实取材 `chat_codingplan_to_content`（recommended_repository_ids 每仓一 task + affected_files→files + change_type→action 归一化）、`mcp_plan_to_content`（plan_body.execution_plan 优先复用、否则 repository_tasks 映射 + branch_strategy 校正），产物均过 `validate_technical_plan`。
- **eager 投影示范**：chat `CodingPlan` 真实创建 chokepoint `agents/tools/coding_tools.py:create_coding_plan`（coding_tools.py:266-282）创建成功后 best-effort（lazy import + try/except 隔离，失败仅 warning，绝不阻断创建）调 `create_from(origin="chat", work_item=None)` + `link` 回填 `canonical_plan_id`。
- **证据**：`pytest tests/delivery/test_technical_plan_lazy_migration.py tests/delivery/test_chat_eager_projection.py` → lazy 三路径建+回填 / 幂等再 resolve 读不重建 / eager 回填 + best-effort 守护全绿。

## 成功标准 4：迁移期旧表只读、冲突以 canonical 为准、归档/删除不级联删旧表

**判定：✅ TRUE**

- **冲突以 canonical 为准**：resolve 软链命中分支直接读 canonical 最新 `current_version`，不被旧记录覆盖；lazy 测试覆盖「lazy 建 canonical 后 add_version 改 content 分叉 → resolve 仍读 canonical」。
- **归档不级联**：`archive(plan)` 仅 `plan.status = ARCHIVED; plan.save(update_fields=["status","updated_at"])`（service:203-204），**不**触碰旧表 / 不删 PlanVersion；测试断言归档后旧 CodingPlan 仍在、canonical_plan_id 仍指向、PlanVersion 仍在。
- **canonical 删除不影响旧表**：旧表为软引用 UUID（非 FK），canonical 删除不级联旧记录；PlanExternalRef 为 CASCADE（仅 workflow 映射随 canonical 删）。
- **证据**：`test_technical_plan_lazy_migration.py` 冲突 + 归档不级联用例；`test_technical_plan_service.py` archive 用例（预先 link 的 CodingPlan.canonical_plan_id 仍非空）。

---

## 复现命令

```bash
cd server
# Phase 37 专项测试（26 passed）
uv run pytest tests/delivery/test_technical_plan_models.py tests/delivery/test_technical_plan_service.py \
  tests/delivery/test_technical_plan_inv6_guard.py tests/delivery/test_technical_plan_lazy_migration.py \
  tests/delivery/test_chat_eager_projection.py -q
# 回归（delivery + chat + mcp，379 passed）
uv run pytest tests/delivery tests/test_coding_tools.py tests/test_coding_plan_model.py tests/mcp_tools -q
# 迁移一致性（No changes detected）
uv run python manage.py makemigrations --check --dry-run
# 格式/lint
uv run ruff format --check delivery/models/technical_plan.py delivery/services/technical_plan_service.py agents/tools/coding_tools.py
uv run ruff check delivery/models/technical_plan.py delivery/services/technical_plan_service.py agents/tools/coding_tools.py
```

## Deferred / 后续 phase 接入点（非本 phase 缺陷）

- mcp/workflow 旧入口改 eager 投影（本 phase chat eager 示范 + 三路径 lazy 兜底；mcp/workflow eager 在 40/41 接 orchestration 时顺带）。
- 架构师融合真实产 `MergedPlan` 落 canonical（Phase 40，本 phase 只立落库底座 + content schema 校验）。
- PlanValidator 完整校验（Phase 40，在已对齐的 verify_plan/validate_technical_plan 基础上扩展）。
- 旧表读写入口改为操作 canonical（DOMAIN §5.4：迁移期旧表只读历史）—— 逐步收敛，超本 phase 全量改造范围。

## Gaps

None —— 4 项成功标准全部满足，无阻断缺口。
