---
phase: 143
slug: eval
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-28
---

# Phase 143 — Validation Strategy

> 价值评估与中高入图的 Nyquist 合同。PLAN 尚未落地；下表 Task ID 为 Wave 0 / 规划占位，执行时须把每条 `<automated>` 抄进对应 PLAN。`EVAL-03` 的「既有摄取入口」以 RESEARCH 为准：worker `await ingest()`，**禁止**本路径 `aschedule_ingestion` / `background_runner`。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x + pytest-django + pytest-asyncio（`asyncio_mode=auto`） |
| **Config file** | `server/pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `cd server && uv run pytest tests/initiatives/test_session_capture_eval.py tests/initiatives/test_capture_inv6_guard.py tests/knowledge/test_session_capture_source.py tests/test_model_usage_call_source.py::TestCallSourceEnum -q --tb=short` |
| **Full suite command** | `cd server && uv run pytest tests/initiatives/test_session_capture_eval.py tests/initiatives/test_session_capture_eval_tasks.py tests/initiatives/test_capture_service.py tests/initiatives/test_capture_inv6_guard.py tests/initiatives/test_capture_observability.py tests/knowledge/test_session_capture_source.py tests/mcp_tools/test_report_session_knowledge.py tests/mcp_tools/test_report_project_knowledge.py tests/initiatives/test_memory_inv6_guard.py tests/test_model_usage_call_source.py tests/durable/test_charter_draft_task.py -q --tb=short` |
| **Estimated runtime** | quick ~40s；full ~120s |

默认 `addopts` 含 `--disable-socket` 与 `-m 'not postgres_queue'`。durable 双后端用 in-process handler 路径验收；Procrastinate 真队列不作为本阶段门禁。LLM / Qdrant / embedding 一律 mock。

---

## Sampling Rate

- **After every task commit:** Run `{quick run command}` 或该任务表内 `<automated>`（取更窄者）
- **After every plan wave:** Run `{full suite command}`（含 Capture/MCP/Memory 回归）
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 40 seconds（quick）；wave 门禁允许 ~120s

---

## Per-Task Verification Map

PLAN 未生成前，Plan 列固定为 `01`、Wave 为 `0`。后续 `/gsd-plan-phase` 可拆 wave，但不得删掉这些 automated 命令或把行为改成仅人工。

威胁编号来自 RESEARCH Security Domain（队列泄密、伪造档、重复 ingest、写项目记忆、未授权边）。

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 143-01-01 | 01 | 0 | EVAL-01 | T-143-02 | 参数化 high/medium/low 写入 `value_tier` + 非空 `distilled_essence`；writer 仅 CaptureService | unit | `cd server && uv run pytest tests/initiatives/test_session_capture_eval.py::test_eval_writes_high_medium_low_and_essence -x` | ❌ W0 | ⬜ pending |
| 143-01-02 | 01 | 0 | EVAL-01 | T-143-02 | 非法 JSON / 非法或缺失 tier **失败、不默认 low**；Capture 行仍在 | unit | `cd server && uv run pytest tests/initiatives/test_session_capture_eval.py::test_invalid_json_or_tier_is_failure_not_low -x` | ❌ W0 | ⬜ pending |
| 143-01-03 | 01 | 0 | EVAL-01 | T-143-02 | 空 question/answer 在模型调用前失败；`ainvoke` 未调用 | unit | `cd server && uv run pytest tests/initiatives/test_session_capture_eval.py::test_empty_input_skips_llm_and_fails -x` | ❌ W0 | ⬜ pending |
| 143-01-04 | 01 | 0 | EVAL-01 / EVAL-02 | T-143-02 | 缺 Friday default_model 失败、不猜模型；factory/`ainvoke` 未调用 | unit | `cd server && uv run pytest tests/initiatives/test_session_capture_eval.py::test_missing_default_model_fails_without_guessing -x` | ❌ W0 | ⬜ pending |
| 143-01-05 | 01 | 0 | EVAL-01 | T-143-01 | 评估失败保留 Capture；`last_error` 经 `redact_secrets_in_text` | unit | `cd server && uv run pytest tests/initiatives/test_session_capture_eval.py::test_eval_failure_keeps_capture_and_redacts_error -x` | ❌ W0 | ⬜ pending |
| 143-01-06 | 01 | 0 | EVAL-02 | T-143-02 | `use_call_source(session_capture_eval)`；成功记 token/TTFT，失败记 upstream status | unit | `cd server && uv run pytest tests/initiatives/test_session_capture_eval.py::test_eval_records_usage_with_session_capture_eval -x` | ❌ W0 | ⬜ pending |
| 143-01-07 | 01 | 0 | EVAL-02 | T-143-02 | evaluator 不得 import 质量门 / `llm_grader` / repo confidence | static | `cd server && uv run pytest tests/initiatives/test_session_capture_eval.py::test_eval_module_does_not_import_quality_gates -x` | ❌ W0 | ⬜ pending |
| 143-01-08 | 01 | 0 | EVAL-02 | — | `CallSource` 闭集含 `session_capture_eval` + 既有 `initiative_profile`；与测试期望集相等 | unit | `cd server && uv run pytest tests/test_model_usage_call_source.py::TestCallSourceEnum -x` | ✅ 需改期望集 | ⬜ pending |
| 143-01-09 | 01 | 0 | EVAL-01 / EVAL-04 | T-143-03 | 合法/非法 CAS：`pending_eval\|eval_failed→evaluating`、`evaluating→evaluated_low\|ingest_pending`、ingest claim/fail/ingested；竞争仅一赢家；终态 CAS=0 no-op | unit | `cd server && uv run pytest tests/initiatives/test_capture_service.py -k "claim or record_eval or record_ingest or cas or retry" -x` | ✅ 需扩展 | ⬜ pending |
| 143-01-10 | 01 | 0 | EVAL-04 | T-143-03 | `QUEUE_KNOWLEDGE in ALL_QUEUES`；eval/ingest 两 adapter 均 `**payload` 调共用任务体 | unit | `cd server && uv run pytest tests/initiatives/test_session_capture_eval_tasks.py::test_queue_knowledge_in_all_queues tests/initiatives/test_session_capture_eval_tasks.py::test_inprocess_adapters_splat_payload -x` | ❌ W0 | ⬜ pending |
| 143-01-11 | 01 | 0 | EVAL-04 | T-143-01 | durable payload 仅 `capture_id`/`attempt`/`initiated_by_user_id`；无 question/answer/essence/transcript | unit | `cd server && uv run pytest tests/initiatives/test_session_capture_eval_tasks.py::test_payload_has_only_scalar_keys -x` | ❌ W0 | ⬜ pending |
| 143-01-12 | 01 | 0 | EVAL-04 | T-143-03 | 非 claimable 状态重放不二次 LLM；已 ingested 重放 no-op | unit | `cd server && uv run pytest tests/initiatives/test_session_capture_eval_tasks.py::test_replay_skips_llm_when_not_claimable tests/initiatives/test_session_capture_eval_tasks.py::test_ingested_replay_is_noop -x` | ❌ W0 | ⬜ pending |
| 143-01-13 | 01 | 0 | EVAL-04 | T-143-03 | ingest 重放不调用 evaluator；ingest 失败不退回 `pending_eval` | unit | `cd server && uv run pytest tests/initiatives/test_session_capture_eval_tasks.py::test_ingest_replay_does_not_call_evaluator tests/initiatives/test_session_capture_eval_tasks.py::test_ingest_failure_does_not_reenter_eval -x` | ❌ W0 | ⬜ pending |
| 143-01-14 | 01 | 0 | EVAL-03 / EVAL-04 | T-143-03 | medium/high 成功后 defer ingest；low 不 defer、不 await ingest/embedding | unit | `cd server && uv run pytest tests/initiatives/test_session_capture_eval_tasks.py::test_medium_high_defers_ingest tests/initiatives/test_session_capture_eval_tasks.py::test_low_skips_ingest -x` | ❌ W0 | ⬜ pending |
| 143-01-15 | 01 | 0 | EVAL-04 | T-143-03 | 有界 backoff：`attempt`/`run_at`/稳定 key `capture-eval:{id}` 与 `capture-ingest:{id}` + lock | unit | `cd server && uv run pytest tests/initiatives/test_session_capture_eval_tasks.py::test_backoff_attempt_run_at_and_stable_keys -x` | ❌ W0 | ⬜ pending |
| 143-01-16 | 01 | 0 | EVAL-04 | T-143-03 | 重启语义：due 且无 active job 的 pending/failed 重派；active、fresh、终态跳过；单条失败隔离 | unit | `cd server && uv run pytest tests/initiatives/test_session_capture_eval_tasks.py::test_recovery_redefers_pending_eval tests/initiatives/test_session_capture_eval_tasks.py::test_recovery_skips_active_fresh_and_terminal tests/initiatives/test_session_capture_eval_tasks.py::test_recovery_isolates_single_failure -x` | ❌ W0 | ⬜ pending |
| 143-01-17 | 01 | 0 | EVAL-04 | T-143-03 | MCP persist 后 durable eval 入队；重复终态不二次入队；enqueue 异常仍 200/`accepted=true` | unit | `cd server && uv run pytest tests/mcp_tools/test_report_session_knowledge.py::test_accepted_enqueues_durable_eval tests/mcp_tools/test_report_session_knowledge.py::test_terminal_capture_does_not_reenqueue tests/mcp_tools/test_report_session_knowledge.py::test_enqueue_failure_still_accepted -x` | ✅ 需扩展 | ⬜ pending |
| 143-01-18 | 01 | 0 | EVAL-03 | T-143-01 / T-143-05 | `kind=DOCUMENT`、`source_kind=session_capture`、稳定 `source_id`；content 仅为精华 | unit | `cd server && uv run pytest tests/knowledge/test_session_capture_source.py::test_document_session_capture_event tests/knowledge/test_session_capture_source.py::test_content_is_essence_not_qa -x` | ❌ W0 | ⬜ pending |
| 143-01-19 | 01 | 0 | EVAL-03 | T-143-01 | payload 仅标量 provenance；sentinel Q/A 不在 content/payload | unit | `cd server && uv run pytest tests/knowledge/test_session_capture_source.py::test_payload_contains_only_scalar_provenance -x` | ❌ W0 | ⬜ pending |
| 143-01-20 | 01 | 0 | EVAL-03 | T-143-03 | low / 缺失 capture 返回空事件，不调 embedding | unit | `cd server && uv run pytest tests/knowledge/test_session_capture_source.py::test_low_returns_empty tests/knowledge/test_session_capture_source.py::test_missing_returns_empty -x` | ❌ W0 | ⬜ pending |
| 143-01-21 | 01 | 0 | EVAL-03 | T-143-05 | 无项目 medium 仍产事件且 `edges=()`；有项目才 REFERENCES + space；`repository_id` 透传 | unit | `cd server && uv run pytest tests/knowledge/test_session_capture_source.py::test_unanchored_medium_still_emits_event_without_edges tests/knowledge/test_session_capture_source.py::test_project_capture_adds_references_edge_and_space tests/knowledge/test_session_capture_source.py::test_repository_id_propagates -x` | ❌ W0 | ⬜ pending |
| 143-01-22 | 01 | 0 | EVAL-03 | T-143-01 | essence 内密钥再脱敏 | unit | `cd server && uv run pytest tests/knowledge/test_session_capture_source.py::test_secret_redacted_from_essence -x` | ❌ W0 | ⬜ pending |
| 143-01-23 | 01 | 0 | EVAL-05 | T-143-04 | eval 路径零 `ProjectMemory` 写入 | unit | `cd server && uv run pytest tests/initiatives/test_session_capture_eval.py::test_eval_does_not_write_project_memory -x` | ❌ W0 | ⬜ pending |
| 143-01-24 | 01 | 0 | EVAL-05 / EVAL-04 | T-143-04 | INV-6：仅 CaptureService 写 Capture；eval/enqueue/worker/normalizer 禁止 `SessionCapture.objects.*` 写、`MemoryService`、`record_hook_writeback`、`aschedule_ingestion`、`background_runner` | static | `cd server && uv run pytest tests/initiatives/test_capture_inv6_guard.py -x` | ✅ 需扩展 | ⬜ pending |
| 143-01-25 | 01 | 0 | OBS-04 | — | worker `bind_task_context` 真实 user；缺失绑定 `system` | unit | `cd server && uv run pytest tests/initiatives/test_session_capture_eval_tasks.py::test_worker_rebinds_initiated_by_user_id -x` | ❌ W0 | ⬜ pending |
| 143-01-26 | 01 | 0 | OBS-04 / OBS-01 | T-143-01 | sampling started/completed/failed：`category=sampling`、`component=knowledge`、含 user/`duration_ms`；序列化日志无 Q/A/essence/token；logger 失败不改状态 | unit | `cd server && uv run pytest tests/initiatives/test_capture_observability.py -x` | ✅ 需替换 Phase 141 `test_no_eval_sampling_events` | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/initiatives/test_session_capture_eval.py` — EVAL-01/02/05 RED：
  - `test_eval_writes_high_medium_low_and_essence`
  - `test_invalid_json_or_tier_is_failure_not_low`
  - `test_empty_input_skips_llm_and_fails`
  - `test_missing_default_model_fails_without_guessing`
  - `test_eval_failure_keeps_capture_and_redacts_error`
  - `test_eval_records_usage_with_session_capture_eval`
  - `test_eval_module_does_not_import_quality_gates`
  - `test_eval_does_not_write_project_memory`
- [ ] `server/tests/initiatives/test_session_capture_eval_tasks.py` — EVAL-03/04、OBS-04 RED：
  - `test_queue_knowledge_in_all_queues`
  - `test_inprocess_adapters_splat_payload`
  - `test_payload_has_only_scalar_keys`
  - `test_replay_skips_llm_when_not_claimable`
  - `test_ingested_replay_is_noop`
  - `test_ingest_replay_does_not_call_evaluator`
  - `test_ingest_failure_does_not_reenter_eval`
  - `test_medium_high_defers_ingest`
  - `test_low_skips_ingest`
  - `test_backoff_attempt_run_at_and_stable_keys`
  - `test_recovery_redefers_pending_eval`
  - `test_recovery_skips_active_fresh_and_terminal`
  - `test_recovery_isolates_single_failure`
  - `test_worker_rebinds_initiated_by_user_id`
- [ ] `server/tests/knowledge/test_session_capture_source.py` — EVAL-03 RED：
  - `test_document_session_capture_event`
  - `test_content_is_essence_not_qa`
  - `test_payload_contains_only_scalar_provenance`
  - `test_low_returns_empty`
  - `test_missing_returns_empty`
  - `test_unanchored_medium_still_emits_event_without_edges`
  - `test_project_capture_adds_references_edge_and_space`
  - `test_repository_id_propagates`
  - `test_secret_redacted_from_essence`
- [ ] 扩展 `server/tests/initiatives/test_capture_service.py` — 每条合法/非法状态 CAS、竞争 claim、终态不可回退、attempt/`next_retry_at`、错误脱敏
- [ ] 扩展 `server/tests/initiatives/test_capture_inv6_guard.py` — 新模块禁止 Capture ORM 写、`MemoryService`、`record_hook_writeback`、`aschedule_ingestion`、`background_runner`；`test_writer_does_not_call_deferred_sinks` 允许清单：persist 仍禁 deferred sinks；enqueue 放独立模块
- [ ] 扩展 `server/tests/mcp_tools/test_report_session_knowledge.py` — `test_accepted_enqueues_durable_eval`、`test_terminal_capture_does_not_reenqueue`、`test_enqueue_failure_still_accepted`；继续断言 ProjectMemory 零写入
- [ ] 扩展 `server/tests/test_model_usage_call_source.py` — 期望集补 `initiative_profile` + `session_capture_eval`（长度 45→47，集合相等为权威）
- [ ] 扩展 `server/tests/initiatives/test_capture_observability.py` — 用 Phase 143 lifecycle 白名单替换 `test_no_eval_sampling_events`
- [ ] Framework install: 无 — 已有 pytest / pytest-django / pytest-asyncio

既有 fixture：`server/tests/conftest.py`、`server/tests/mcp_tools/conftest.py`、`server/tests/knowledge/test_project_memory_source.py` 形态。Analog 见 `143-PATTERNS.md` Exact Test Assignments。ingestion 内核幂等（hash 预短路 / 三连发 / revector）由既有 `tests/knowledge/test_ingestion.py` 承担，Capture 任务测试只证明调用统一 `ingest`。

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Postgres + Procrastinate 真 worker 消费 `QUEUE_KNOWLEDGE` | EVAL-04 | pytest 默认排除 `postgres_queue`；compose worker 未 pin `--queues` 时靠 `ALL_QUEUES` | 人工探测：compose `run_worker` 跑通一条 medium Capture ingest；不阻塞 Nyquist 自动化门禁 |

其余行为均有 automated verify。真 LLM / 真 Qdrant 不作为门禁。

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 40s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
