# Phase 50 — Deferred / Out-of-Scope Items

执行 Phase 50 期间发现、但**不属于本 phase 范围**的问题（SCOPE BOUNDARY，仅记录不修）。

## Pre-existing test failure（Phase 49 遗留）

- **Test:** `server/tests/delivery/test_plan_session_event.py::test_all_events_equals_v07_orchestration_set`
- **现象:** `ALL_EVENTS` 含 `'spec.drafted'`，但该用例断言的 v0.7 orchestration 集合未含此事件 → `AssertionError`（Extra item `spec.drafted`）。
- **根因:** Phase 49 commit `f468dfd18 feat(49-03): add EVENT_SPEC_DRAFTED to event taxonomy` 向 `event_taxonomy.py` 加了 `spec.drafted`，但未同步更新该 v0.7 集合断言。
- **判定:** 本 Phase 50 未触碰 `event_taxonomy.py` / `test_plan_session_event.py`，属 Phase 49 测试债，与 spec 状态机/评审/前端无关。**不在本 phase 修复。**
- **建议:** 由维护 event taxonomy 的后续 phase 更新该断言（把 `spec.drafted` 纳入预期集合，或将该测试改为不强约束新增事件）。

## Pre-existing ruff lint（migrations import 排序）

- **现象:** `ruff check delivery/` 报 `I001`（import 未排序）覆盖全部 `delivery/migrations/0008..0019`。
- **根因:** Django `makemigrations` 自动生成的 import 顺序与 ruff isort 不一致；仓库既有 9 个 migration（0008–0018）均以该形态提交，团队约定不对自动生成 migration 跑 ruff --fix。
- **判定:** 新增 `0019_sddspecreview.py` 与既有 9 个同形态；plan 50-01 明确「不得手写 migration 文件内容，必须由 makemigrations 生成」，故不手改其 import 排序以保持一致。源码（models/services/api）均 ruff 干净。
- **建议:** 若需统一，应在 ruff 配置中对 `*/migrations/*` 加 per-file-ignore（`I001`），而非逐个手改。
