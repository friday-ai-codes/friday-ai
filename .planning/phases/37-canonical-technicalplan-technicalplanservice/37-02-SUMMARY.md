---
phase: 37-canonical-technicalplan-technicalplanservice
plan: 02
subsystem: delivery / canonical plan service
tags: [service, INV-6, resolve, lazy-migration, content-hash]
requires: [delivery.TechnicalPlan, delivery.PlanVersion, delivery.PlanExternalRef, workflows.schemas.technical_plan]
provides:
  - delivery.services.TechnicalPlanService
  - delivery.services.PlanRef
  - delivery.services.PlanContentInvalid
  - delivery.services.PlanNotFound
affects: [37-03, Phase 40, Phase 41]
tech-stack:
  added: []
  patterns: [single write entry (INV-6), sync_to_async ORM bridge, local sha256 content_hash, lazy import 防循环]
key-files:
  created:
    - server/delivery/services/technical_plan_service.py
    - server/tests/delivery/test_technical_plan_service.py
    - server/tests/delivery/test_technical_plan_inv6_guard.py
  modified:
    - server/delivery/services/__init__.py
decisions:
  - PlanRef dataclass(origin + source_key) + for_chat/for_mcp/for_workflow 便捷构造
  - content_hash 本地 sha256(canonical JSON sort_keys)，不 import knowledge（INV-3）
  - content 校验复用 workflows.schemas.validate_technical_plan（PF-02）
  - hash 相等复用 current 不翻版本（v0.3/v0.6 铁律）
  - INV-6 guard 豁免同名 dataclass workflows/schemas/technical_plan.py（名字撞车，非 model 写）
metrics:
  duration: ~15m
  completed: 2026-06-16
---

# Phase 37 Plan 02: TechnicalPlanService 唯一写入入口 Summary

落 canonical 方案解析/创建/关联/版本/归档的唯一写入入口（INV-6），grep 守护无旁路写 TechnicalPlan/PlanVersion；create_from eager 投影 + resolve §5.4 三优先级 + link 三路径软链回填。

## What Was Built

- **`TechnicalPlanService`**：`create_from`（校验 content → 建 plan+v1+current）/ `add_version`（hash 相等复用、不等建 supersedes 链并推进 current）/ `archive`（仅置 status，不级联）/ `resolve`（§5.4：软链命中读 canonical / lazy 建+回填 / 找不到 raise PlanNotFound）/ `link`（chat/mcp 写 canonical_plan_id、workflow 经 PlanExternalRef update_or_create 幂等）。
- **`PlanRef`** dataclass + `for_chat`/`for_mcp`/`for_workflow` 构造；异常 `PlanContentInvalid` / `PlanNotFound`。
- **本地 `_content_hash`**：sha256(canonical JSON sort_keys)，不 import knowledge（INV-3）。
- **测试**：service 行为 10 用例 + INV-6 grep 守护 2 用例，共 12 全绿。

## Deviations from Plan

**1. [Rule 1 - Bug] INV-6 guard 名字撞车豁免**
- **Found during:** Task 3（守护首跑 fail）
- **Issue:** `workflows/schemas/technical_plan.py` 定义同名 **dataclass** `TechnicalPlan`（LLM 输出 schema，非 Django model），其 `dict_to_technical_plan` 的 `return TechnicalPlan(...)` 被 `\bTechnicalPlan\(` 误判为旁路写。
- **Fix:** 守护加 `_NAME_COLLISION_EXEMPT = {"workflows/schemas/technical_plan.py"}` 文件白名单豁免（无法仅凭名字区分 dataclass vs model），附 zh-CN 注释说明。
- **Files modified:** server/tests/delivery/test_technical_plan_inv6_guard.py
- **Commit:** test(37-02) 提交内

## Verification

- `pytest test_technical_plan_service.py test_technical_plan_inv6_guard.py` → 12 passed。
- `makemigrations --check --dry-run` → No changes detected。
- `ruff format --check` → 通过。

## Self-Check: PASSED

- FOUND: server/delivery/services/technical_plan_service.py
- FOUND: server/tests/delivery/test_technical_plan_service.py
- FOUND: server/tests/delivery/test_technical_plan_inv6_guard.py
