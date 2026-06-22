---
phase: 32-one-click-ingest
plan: 02
subsystem: delivery
tags: [ingest, orchestration, rest, knowledge, best-effort]
requires:
  - delivery.models.IngestRun（+ default_steps，32-01）
  - delivery.services.ingest_parsing（parse_board_url / aresolve_repo_and_mr，32-01）
  - delivery.services.work_item_service（WorkItemService.upsert + _redact_secrets，P28）
  - knowledge.ingestion（ingest / ingest_events / IngestionRequest / IngestionEvent，P13）
  - knowledge.sources.feishu_document（normalizer：work_item+document+REFERENCES，P30）
  - knowledge.diff_archive.archive_code_change（既有 MR diff RAG，P14）
  - services.background_runner.run_in_background
provides:
  - delivery.services.ingest_orchestrator.ingest_from_urls（三步编排，best-effort 降级）
  - delivery.services.StepResult
  - REST：POST /delivery/ingest/（202 + run_id）、GET /delivery/ingest/{run_id}/（状态回流）
  - knowledge.diff_archive.aarchive_exists（归档存在性只读 helper）
affects:
  - 32-03（前端：消费 dispatch/status REST，派发→2s 轮询 IngestRun）
tech-stack:
  added: []
  patterns:
    - best-effort 步级隔离（每步独立 try/except，逐步落 IngestRun.steps，不整体回滚 §1.4）
    - 编排既有能力（PURE ORCHESTRATION，绝不新建底层摄取/检索机制）
    - 派发→轮询（run_in_background 脱离请求生命周期 + 202 + 状态端点回流，Phase 23 范式）
    - INV-3 守护：delivery 不引用 knowledge 模型，读访问收口为 knowledge.diff_archive.aarchive_exists
    - 错误脱敏复用 work_item_service._redact_secrets（步级/编排级 error 落库前抹凭证）
key-files:
  created:
    - server/delivery/services/ingest_orchestrator.py
    - server/tests/delivery/test_ingest_orchestrator.py
    - server/tests/delivery/test_ingest_api.py
    - server/tests/delivery/conftest.py
  modified:
    - server/delivery/services/__init__.py
    - server/delivery/api/serializers.py
    - server/delivery/api/views.py
    - server/delivery/urls.py
    - server/knowledge/diff_archive.py
decisions:
  - "code_change IngestionEvent 的 kind/origin 用字面值 'code_change'/'workflow'（无 EntityOrigin.MR_REVERSE 枚举，且避免 delivery 引用 knowledge 模型，守 INV-3）"
  - "MR natural key 合成稳定值：commit_sha=mr-{iid} / source_id={repo.id}:{iid}（不新建底层 MR 元数据拉取，保持编排既有能力边界）"
  - "archive_code_change 返回 None 经 aarchive_exists 区分重复幂等(ok) vs 凭证缺失/拉取失败(failed)"
  - "文档步直接 await ingest（非 aschedule_ingestion）以同步拿成败落 steps"
  - "dispatch 解析 board_url 留痕 IngestRun.project（解析不出/未配置 → None，不阻断派发）"
metrics:
  duration: ~40m
  completed: 2026-06-15
---

# Phase 32 Plan 02: 一键摄取编排 + dispatch/status REST Summary

实装 ING-01 核心交付——`ingest_from_urls(run_id, board_url, mr_url)` 把 (看板URL, MR URL) 串成三步**既有能力**摄取（工作项 upsert / 文档+REFERENCES / MR diff 归档入图），每步 best-effort 独立降级、结构化结果逐步落 `IngestRun`；配 dispatch（202 + run_id 后台执行）与 status（回流真实步骤）两个受认证 REST 端点。本 plan 是 PURE ORCHESTRATION，复用 P28 upsert / P30 normalizer / 既有 diff RAG，绝不新建底层摄取/检索机制。

## What Was Built

### Task 1 — `ingest_from_urls` 三步编排服务（commits `113b0f95` test / `c0a1dfb1` feat）
- `server/delivery/services/ingest_orchestrator.py`：
  - frozen dataclass `StepResult(status, identifier, link, error)`（形状对齐 `default_steps`）。
  - `async def ingest_from_urls(run_id, board_url, mr_url) -> IngestRun`：加载 `IngestRun`，三步主体包在编排级 try/except，每步独立 try/except 写回 `IngestRun.steps[*]` 并即时 `sync_to_async` 持久化（逐步可轮询）：
    1. **工作项**：`parse_board_url` → `WorkItemService().upsert(WorkItemIdentity, source="mr_reverse", fetch=True)`（INV-6 单一写入口）；解析失败 → skipped。
    2. **文档 + REFERENCES**：`await ingest(IngestionRequest("feishu_document", "{pk}:{wt}:{wid}", "one_click_ingest"))`——经 P30 normalizer 同时让 work_item + document 实体进入 knowledge 可检索面 + `REFERENCES` 边（缺段不缺实体）；board 解析失败 → skipped。
    3. **MR diff**：`aresolve_repo_and_mr`（SSRF 边界，必须命中已落库 Repository）→ `archive_code_change(source_kind="mr_ingest", source_id="{repo.id}:{iid}", commit_sha="mr-{iid}", ...)` → 组装 `code_change` `IngestionEvent`（payload 仅摘要）经 `ingest_events` 入图。返回 None 经 `aarchive_exists` 区分重复幂等(ok) vs 凭证缺失/拉取失败(failed)；解析不出/不匹配 → skipped。
  - 三步跑完（即便含步级 failed/skipped）→ `status=completed`；编排级未捕获异常 → `status=failed` + 脱敏 error（复用 `work_item_service._redact_secrets` + 截断，T-32-02）。
- `delivery/services/__init__.py` 追加 re-export `ingest_from_urls` / `StepResult`。
- `knowledge/diff_archive.py` 新增 `aarchive_exists(source_kind, source_id)` 只读 helper（让编排层区分重复 vs 失败而不必在 delivery 引用 knowledge 模型，守 INV-3）。
- 测试 `test_ingest_orchestrator.py`（8 例）+ `tests/delivery/conftest.py`（复刻 knowledge conftest 的 mock_embedding / mock_qdrant_client / mock_ensure / mock_upsert / fake_git_platform）。检索可测代理 = 断言 KnowledgeEntity(work_item/document/code_change) + REFERENCES KnowledgeEdge + CodeChangeArchive 行存在。

### Task 2 — dispatch/status REST 端点（commit `17e8c5c4` feat）
- `delivery/api/serializers.py`：`IngestDispatchRequestSerializer`（board_url/mr_url 必填 + http(s) 前缀校验 + 中文错误）、`IngestRunSerializer`（`run_id`(=id)/`status`/`steps`/`started_at`/`completed_at`，字段名严格对齐 UI-SPEC `IngestRun` 契约）。
- `delivery/api/views.py`（adrf `APIView` + `IsAuthenticated`）：`IngestDispatchView.post`（校验 → 解析 board_url 留痕 Project → `sync_to_async` 建 running `IngestRun` → `run_in_background(lambda: ingest_from_urls(run_id, board_url, mr_url), name="ingest:{run_id}")` → 202 `{run_id, dispatched}`）；`IngestRunDetailView.get`（`<uuid:run_id>`，命中回流 / 不存在 404）。
- `delivery/urls.py` 追加 `ingest/`（字面段在 `work-items/` 通配前）与 `ingest/<uuid:run_id>/`。
- 测试 `test_ingest_api.py`（7 例）：dispatch 202 + 建 running run（steps 三项 pending）+ 断言 `run_in_background` 以 (run_id, board_url, mr_url) 派发 `ingest_from_urls`；空/非 http(s) → 400 不建 run；status 回流 steps；不存在 → 404；两端点未认证 → 401/403。

## Verification Results

- `pytest tests/delivery/test_ingest_orchestrator.py -q` → **8 passed**。
- `pytest tests/delivery/test_ingest_api.py -q` → **7 passed**。
- `pytest tests/delivery -q` → **200 passed**（无回归，含 INV-6/INV-3 grep 守护 `test_inv6_guard.py` 全绿）。
- `pytest tests/knowledge/test_diff_archive.py -q` → **18 passed**（`aarchive_exists` 新增无回归）。
- `ruff check`（仅改动文件：ingest_orchestrator / diff_archive / api views/serializers / urls / 测试）→ All checks passed。
- grep 守护：`ingest_orchestrator` 内无直接 `WorkItem.objects.create`/`Document.objects.create`/`KnowledgeEntity.objects.create`——落库一律经 `WorkItemService.upsert` / `ingest` / `ingest_events` / `archive_code_change`；delivery app 不引用 knowledge 模型（INV-3 守护保持绿）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 新增 `knowledge.diff_archive.aarchive_exists` 以保 INV-3 守护**
- **Found during:** Task 1（首轮 `pytest tests/delivery` 时 `test_inv3_delivery_does_not_write_knowledge_models` 失败）。
- **Issue:** 计划要求编排返回 None 后查 `CodeChangeArchive.objects.filter(...).aexists()` 区分重复 vs 失败，但既有 INV-3 grep 守护禁止 delivery app 引用 `knowledge.models` / `KnowledgeEntity`（含注释字面串）。直接 import 模型会破坏既有守护测试。
- **Fix:** 在 knowledge 层新增 `aarchive_exists(source_kind, source_id)` 只读 helper（模型读访问收口在 knowledge），编排层改调它；`code_change` 事件 kind/origin 改用字面值 `"code_change"`/`"workflow"`（避免 import `EntityKind`/`EntityOrigin`）。
- **Files modified:** `server/knowledge/diff_archive.py`、`server/delivery/services/ingest_orchestrator.py`。
- **Commit:** `17e8c5c4`（helper 随 Task 2 一并落；编排改动随该 commit）。

## Threat Model Compliance

- **T-32-01（SSRF/Tampering）**：board 仅 `parse_board_url` 抽三元组后经项目加密凭证 client；MR 必须 `aresolve_repo_and_mr` 命中已落库 Repository 才走其 git platform client，解析不出/不匹配 → skipped，绝不 fetch 原始用户 URL（`test_unmatched_mr_url_skipped` 守护）。
- **T-32-02（信息泄露）**：步级/编排级 error 落库前一律 `_safe_error`（`_redact_secrets` 抹 Bearer/键值凭证 + 截断）；`code_change` payload 仅摘要（archive_id/commit_sha/统计），diff 原文绝不进 payload/steps（`test_orchestration_level_exception_failed_and_redacted` 守护明文 token 不落库）。
- **T-32-03（Spoofing/Elevation）**：dispatch/status 两端点 `IsAuthenticated`；status 按 run_id 只读，不旁路触发摄取（`test_*_unauthenticated_rejected` 守护）。
- **T-32-04（DoS）**：经 `run_in_background` 脱离请求生命周期，单 run 三步有界（archive 既有上限）；批量/限流非本 phase 范围（accept）。
- 无新增 npm/pip/cargo 依赖（供应链门不适用）。

## Self-Check: PASSED

- FOUND: server/delivery/services/ingest_orchestrator.py
- FOUND: server/tests/delivery/test_ingest_orchestrator.py
- FOUND: server/tests/delivery/test_ingest_api.py
- FOUND: server/tests/delivery/conftest.py
- FOUND commit: 113b0f95（test）
- FOUND commit: c0a1dfb1（feat orchestrator）
- FOUND commit: 17e8c5c4（feat REST + aarchive_exists）
