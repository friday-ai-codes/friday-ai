---
phase: 143-eval
verified: 2026-08-28T11:20:14Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 0
re_verification: false
---

# Phase 143: 价值评估与中高入图 Verification Report

**Phase Goal:** Friday 在 Capture 持久化之后可靠评估知识价值，仅把可复用的中高价值精华加入统一 RAG
**Verified:** 2026-08-28T11:20:14Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

Goal-backward check starts from ROADMAP Success Criteria and EVAL-01..05 / OBS-04. SUMMARY.md and VALIDATION.md pass counts were not treated as evidence; this pass re-read production modules and re-ran the phase-owned pytest suite.

### Observable Truths

| # | Truth | Status | Evidence |
| --- | ------- | ---------- | -------------- |
| 1 | EVAL-01：每条已落库 Capture 异步得到闭集 `high`/`medium`/`low` 与非空 `distilled_essence`；非法 JSON/档位/缺默认模型失败且不降 `low`；失败保留 Capture 可重试 | ✓ VERIFIED | `SessionCaptureEvaluator.evaluate` 只接受字段恰好为 `value_tier`+`distilled_essence` 的 JSON；档位闭集 `_VALID_TIERS`；空精华/脱敏后空均 `SessionCaptureEvaluationError`。`CaptureService.record_evaluation` 仅闭集档位+非空精华才落库，`low`→`evaluated_low`，中高→`ingest_pending`。`record_eval_failure` 写 `eval_failed` 不删行。MCP persist 之后才 `enqueue_session_capture_eval`。本轮 `test_session_capture_eval.py` 全绿。 |
| 2 | EVAL-02：价值档不复用写回质量门或仓库路由 confidence；LLM 以 `call_source=session_capture_eval` 记用量（含失败上游码） | ✓ VERIFIED | `CallSource.SESSION_CAPTURE_EVAL = "session_capture_eval"`（枚举 47 值）。评估走 `use_call_source` + `arecord_llm_usage(call_source=_CALL_SOURCE)`。模块源码不含 `evaluate_writeback_quality` / `llm_grader` / `MemoryService`。`test_eval_records_usage_with_session_capture_eval` 与 `test_eval_module_does_not_import_quality_gates` 本轮通过。LOGGING-SPEC 已登记该 call_source 与 sampling 事件。 |
| 3 | EVAL-03：`medium`/`high` 经既有 `ingest()` 六步序进入 `delivery_knowledge`（`EntityKind.DOCUMENT` + `source_kind=session_capture`），正文仅为精华；`low` 不产生事件因而不向量化，Capture 行仍在可回放 | ✓ VERIFIED | Worker `await ingest(IngestionRequest("session_capture", ...))`，**不是** `aschedule_ingestion` / `background_runner` 唯一投递。`knowledge.sources.session_capture.normalize`：仅 `medium`/`high` 且状态 ∈ ingest_pending/ingesting/ingested 才产出事件；`content` 为再次脱敏的 `distilled_essence`；payload 仅标量 provenance，禁止 question/answer。`test_session_capture_normalize_low_returns_empty` 返回 `[]`；ingest 对空事件直接 return 0、不调 `ingest_events`。无锚中高仍产无边 DOCUMENT。 |
| 4 | EVAL-04：投递 persist-first、eval/ingest 独立可重试；稳定 Procrastinate `queueing_lock` 与退避 `lock`+`run_at`（不复用稳定 idempotency key）；pending/failed 与无 active job 的 stale evaluating/ingesting 可恢复；in-flight resume 不递增 attempt | ✓ VERIFIED | View：`CaptureService.persist` 返回后再 `await enqueue_session_capture_eval`；enqueue 异常仍 200/`accepted=true`。双任务 `durable_session_capture_eval` / `_ingest`，ingest 体不含 evaluator。首次/recovery：`idempotency_key=lock=capture-eval:{id}`（ingest 同构）。Worker 退避 `DurableTaskService.defer(..., lock=..., run_at=...)` **省略** `idempotency_key`，避免 Procrastinate `queueing_lock` 吞掉延迟新 job。`claim_*`：pending/failed CAS 递增 attempt；已是 processing 则 resume 不 `F()+1`。Recovery：`has_active_by_key` 跳过在途；stale processing 10 分钟；终态 evaluated_low/ingested/legacy evaluated 不在可恢复查询。周期任务 `recover_stranded_session_captures`。 |
| 5 | EVAL-05：评估与入图不写 `ProjectMemory`，不调用 `MemoryService.append` / `record_hook_writeback` | ✓ VERIFIED | INV-6 守卫扫描 eval/enqueue/`tasks_impl`/normalizer：禁止上述符号、`aschedule_ingestion`、`background_runner`、旁路 `SessionCapture.objects.*` 写。`test_eval_does_not_write_project_memory` 计数不变。Capture 原文不进 RAG content（见 #3）。 |
| 6 | OBS-04：eval/ingest worker 从 payload re-bind `initiated_by_user_id`；缺失记 `system` | ✓ VERIFIED | `DurableTaskService.defer` 把非空 actor 写入 payload。`run_session_capture_eval` / `_ingest`：`actor = initiated_by_user_id or "system"` + `bind_task_context(user_id=..., source="durable", component="knowledge")`。Recovery 缺用户时传 `"system"`。`test_worker_rebinds_initiated_by_user_id` 本轮通过。 |

**Score:** 6/6 truths verified

REQUIREMENTS.md EVAL-03 仍写「经既有 `aschedule_ingestion`」。实现合同（ROADMAP SC3「既有摄取入口」、PLAN R-01、本阶段 INV-6）是 durable worker **`await ingest()`**。这与「禁止 aschedule-only / background_runner 当唯一投递」一致，不构成目标失败。

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | ----------- | ------ | ------- |
| `server/initiatives/services/session_capture_eval.py` | 严格三档 evaluator | ✓ VERIFIED | 253 行；导出 `SessionCaptureEvaluator` / `SessionCaptureEvalResult`；无 ORM 写 |
| `server/initiatives/services/session_capture_enqueue.py` | 标量 durable 投递与 stranded recovery | ✓ VERIFIED | payload 仅 `capture_id`/`attempt`（actor 由 service 注入）；稳定 key；`has_active_by_key` |
| `server/initiatives/services/capture_service.py` | INV-6 CAS 唯一 writer | ✓ VERIFIED | `claim_*` / `record_*` 全部 `filter(...).update` CAS |
| `server/initiatives/migrations/0016_session_capture_evaluation.py` | additive 状态/档位/attempt 字段 | ✓ VERIFIED | nullable/default-safe；status choices 含 legacy `evaluated`；未改存量列语义 |
| `server/initiatives/models/session_capture.py` | 状态机与价值闭集 | ✓ VERIFIED | `SessionCaptureStatus` / `SessionCaptureValueTier` |
| `server/knowledge/sources/session_capture.py` | DOCUMENT/essence-only normalizer | ✓ VERIFIED | 已登记于 `knowledge/sources/__init__.py` `_NORMALIZERS["session_capture"]` |
| `server/durable/tasks_impl.py` | 独立 eval/ingest 任务体 | ✓ VERIFIED | keyword-only 形参；ingest `await ingest`；退避省略稳定 key |
| `server/durable/tasks.py` | Postgres wrappers + 周期恢复 | ✓ VERIFIED | `@app.task` 两任务 + `recover_stranded_session_captures` cron |
| `server/durable/handlers.py` | in-process `**payload` adapter | ✓ VERIFIED | 与 Procrastinate 同任务名 |
| `server/durable/queues.py` | `QUEUE_KNOWLEDGE in ALL_QUEUES` | ✓ VERIFIED | worker 未 pin queues 时仍会消费 |
| `server/mcp_tools/views.py` | persist-first fail-soft enqueue | ✓ VERIFIED | 仅 `pending_eval`/`eval_failed` 入队 |
| `server/agents/call_source.py` | `SESSION_CAPTURE_EVAL` | ✓ VERIFIED | 字符串 `session_capture_eval` |
| `.planning/observability/LOGGING-SPEC.md` | 47 值 + sampling 目录 | ✓ VERIFIED | 已列 `session_capture_eval_*` |
| 测试契约 11 文件 | Nyquist 门禁 | ✓ VERIFIED | 本轮 **183 passed**（见 Behavioral Spot-Checks） |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| `ReportSessionKnowledgeView.post` | `enqueue_session_capture_eval` | persist 已提交后 `await` | WIRED | `mcp_tools/views.py` persist → 可恢复状态守卫 → enqueue；异常吞掉 |
| `enqueue_session_capture_eval` | `DurableTaskService.defer` | 稳定 key + `QUEUE_KNOWLEDGE` | WIRED | `durable_session_capture_eval` |
| `durable/handlers.py` / `durable/tasks.py` | `run_session_capture_eval` | `**payload` / 显式 kwargs | WIRED | 双后端同任务体 |
| `run_session_capture_eval` | `SessionCaptureEvaluator` | `evaluate_session_capture` | WIRED | 成功后 `record_evaluation`；中高再 `enqueue_session_capture_ingest` |
| `run_session_capture_eval` | `bind_task_context` | worker 入口 | WIRED | user 或 `system` |
| `run_session_capture_ingest` | `knowledge.ingestion.ingest` | `await ingest` | WIRED | 失败 `record_ingest_failure`，不回 `pending_eval` |
| `ingest` | `session_capture.normalize` | `get_normalizer("session_capture")` | WIRED | 注册表惰性 import |
| `session_capture.normalize` | `IngestionEvent` DOCUMENT | `source_kind="session_capture"` | WIRED | 有项目才 `EdgeRelation.REFERENCES` |
| `session_capture_eval.py` | `arecord_llm_usage` | 成功/失败 | WIRED | best-effort `except: pass` |
| `CaptureService` | `SessionCapture` | `status__in` CAS update | WIRED | 无模块级 `objects.create` 旁路（INV-6 测试） |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| MCP view | `accepted` / `capture_id` | `CaptureService.persist` 返回的 ORM 行 | 是（账本行先提交） | ✓ FLOWING |
| Eval worker | `value_tier` / `distilled_essence` | Friday default model JSON → `_parse_result` | 生产为 LLM；测试 mock `ainvoke` 仍走同一解析器 | ✓ FLOWING |
| Capture row | `status` / attempts | CAS `update` 条件命中 | 是 | ✓ FLOWING |
| Normalizer | `event.content` | `capture.distilled_essence` 再脱敏 | 是；Q/A 不进入 | ✓ FLOWING |
| Ingest worker | `event_count` | `ingest()` → `ingest_events` | medium/high 非空事件才成功；low 根本不入队 | ✓ FLOWING |
| Durable payload | `capture_id`/`attempt`/`initiated_by_user_id` | enqueue/defer 注入 | 无 Q/A/essence | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Phase 143 Nyquist 11 文件 | `cd server && uv run pytest tests/initiatives/test_session_capture_eval.py tests/initiatives/test_session_capture_eval_tasks.py tests/initiatives/test_capture_service.py tests/initiatives/test_capture_inv6_guard.py tests/initiatives/test_capture_observability.py tests/knowledge/test_session_capture_source.py tests/mcp_tools/test_report_session_knowledge.py tests/mcp_tools/test_report_project_knowledge.py tests/initiatives/test_memory_inv6_guard.py tests/test_model_usage_call_source.py tests/durable/test_charter_draft_task.py -q --tb=short` | **183 passed**, 47 warnings, 213.04s | ✓ PASS |
| 生产文件 ruff | `uv run ruff check` 对 PLAN 07 所列 11 个生产路径 | All checks passed | ✓ PASS |

### Probe Execution

| Probe | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| — | — | PLAN/VALIDATION 未声明 `scripts/*/tests/probe-*.sh` | SKIPPED |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| EVAL-01 | 01,03,04,06,07 | 异步三档+精华；失败保留 | ✓ SATISFIED | evaluator + CAS + durable eval |
| EVAL-02 | 01,04,07 | 独立判断 + `session_capture_eval` 用量 | ✓ SATISFIED | CallSource + arecord_llm_usage + 隔离测试 |
| EVAL-03 | 01,05,06,07 | 中高 DOCUMENT/session_capture；low 无向量 | ✓ SATISFIED | `await ingest` + essence-only normalizer（非 aschedule 包装） |
| EVAL-04 | 02,03,06,07 | persist-first durable 可重试 | ✓ SATISFIED | MCP 接线 + 双任务 + recovery + Procrastinate key/lock |
| EVAL-05 | 01–07 | 不写 ProjectMemory | ✓ SATISFIED | INV-6 + 行为计数 |
| OBS-04 | 02,06,07 | worker re-bind / system | ✓ SATISFIED | bind_task_context |

Orphaned REQUIREMENTS mapped to Phase 143 but missing from plans: none. RECALL/SKILL/OBS-03 belong to later phases.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| — | — | TBD/FIXME/XXX in Phase 143 生产路径 | 无 | 扫描 `session_capture_eval.py` / enqueue / capture_service / normalizer / tasks_impl / views 无未引用债务标记 |
| `knowledge/ingestion.py` | docstring | `ingest()` 仍提及 `background_runner` 失败兜底 | ℹ️ Info | 历史摄取入口文案；Session Capture 路径不调用 `aschedule_ingestion`/`background_runner` |
| `test_session_capture_eval_tasks.py` | backoff 用例 | 部分幂等/退避断言是源码字符串检查 | ℹ️ Info | 本验证已对照 `tasks_impl`/`backends.py` 真实 `defer(configure(queueing_lock=..., lock=..., schedule_at=...))` |

### Human Verification Required

None required to close the phase contract. Postgres + 真 Procrastinate worker 消费 `QUEUE_KNOWLEDGE`、真 Provider、真 Qdrant 在 `143-VALIDATION.md` 中明确为 **manual-only、不阻塞 Nyquist**；自动化已覆盖双后端 adapter、`ALL_QUEUES`、lock/queueing_lock 正交语义与 CAS 恢复。不写入 `human_verification` frontmatter。

### Gaps Summary

No blocking gaps. Phase goal is observably true in the codebase: persist-first durable eval, strict Friday LLM tiers and distilled essence with `session_capture_eval` usage, medium/high essence-only DOCUMENT ingestion via `ingest()`, low never vectorized, independent ingest retries, in-flight stale recovery without attempt inflation, Procrastinate stable-key vs backoff-without-queueing_lock, actor/system rebind, and zero ProjectMemory / aschedule-only delivery.

Confirmation-bias notes (do not fail the goal): (1) REQUIREMENTS.md EVAL-03 字面 `aschedule_ingestion` 与实现 `await ingest()` 不一致，以 ROADMAP/PLAN/INV-6 为准；(2) 真集群 crash 后 Procrastinate `doing` 心跳仍依赖既有 `retry_stalled`，Session Capture recovery 只在「无 active queueing_lock + stale 行」时补投。

---

_Verified: 2026-08-28T11:20:14Z_
_Verifier: Claude (gsd-verifier)_
