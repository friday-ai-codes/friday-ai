---
phase: 125-community-summary
verified: 2026-08-09T20:44:51Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
re_verification: false
gaps: []
deferred: []
---

# Phase 125: 社区检测 + 模块摘要 Verification Report

**Phase Goal:** 每仓代码自动聚成模块并有 LLM 生成的模块摘要，喂给 RepoRouter 与技术方案生成——回答「这段代码属于哪个模块、这个仓有哪些职责」
**Verified:** 2026-08-09T20:44:51Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

Roadmap Success Criteria (SC1–4) + CONTEXT D-01…D-16 / MOD-01…04. SUMMARY claims were not trusted; evidence is from source + scoped tests.

| # | Truth | Status | Evidence |
| --- | ------- | ---------- | -------------- |
| 1 | SC1 / MOD-01: Louvain（固定 seed + 节点排序）→ 独立模型软引用落库；增量索引后 durable 刷新；Symbol 无 community_id | ✓ VERIFIED | `LOUVAIN_SEED=42` + `_to_undirected_sorted` → `louvain_communities`; `SymbolCommunity` JSON `members`/`member_keys` soft refs; migration `0011` CreateModel only; hooks enqueue only (`graph_builder` / `code_relations/tasks` → `enqueue_community_rebuild`); worker `run_community_rebuild` → `get_graph_service().get_graph` + `rebuild_communities`; model test asserts no `community_id` on Symbol |
| 2 | SC2 / MOD-02: 指纹/Jaccard≥0.8 跳过；rebuild×2 LLM=0；空 summary 可重试 | ✓ VERIFIED | `_apply_summary_reconcile` fingerprint short-circuit + greedy Jaccard; `test_rebuild_twice_zero_llm` / `test_fingerprint_jaccard_skip` / `test_empty_summary_retries` green; WR-02 `member_keys` persisted (cap 50k) separate from truncated `members` |
| 3 | SC3 / MOD-03: LLM 模块摘要（关键文件/入口/职责）+ `call_source=module_summary` 双登记 | ✓ VERIFIED | LOGGING-SPEC §4.1 + `CallSource.MODULE_SUMMARY`; guardian `len==45`; `agenerate_module_summary` uses `use_call_source`; durable wires `summary_fn=agenerate_module_summary`; `test_module_summary.py` green |
| 4 | SC4 / MOD-04: 三点 adapter 注入 + 相关度/预算截断；⛔ `repo_router_v2` / `mcp/` 零改动 | ✓ VERIFIED | evidence `module_summaries` in `blueprint_route`; `aapply_module_summary_signal` in relevance + MCP views; `render_module_summaries_section` budget truncate; `blended_score == router_score`; git log `--grep=125` touches neither frozen path; `test_frozen_surface_125` + prompt/signal/breakdown tests green |

**Score:** 4/4 truths verified

### CONTEXT Decisions (D-01…D-16) Spot Map

| Decision | Status | Notes |
| --- | --- | --- |
| D-01 SymbolCommunity ADD TABLE | ✓ | `0011_symbolcommunity.py` CreateModel; `0012` AddField `member_keys` (review fix) |
| D-02 Soft refs, no Symbol FK | ✓ | JSON members; `symbol_id` strings |
| D-03 QUEUE_GRAPH enqueue, not inline | ✓ | hooks → `enqueue_community_rebuild`; `idempotency_key=community:{repo}:{branch}` |
| D-04 Louvain + seed + sort; size&lt;5 unclustered | ✓ | `MIN_COMMUNITY_SIZE=5`; unclustered skips LLM |
| D-05 member_fingerprint | ✓ | `hash(sorted keys)` via `member_fingerprint()` |
| D-06 Jaccard 0.8 greedy | ✓ | `JACCARD_THRESHOLD = 0.8` |
| D-07 rebuild×2 LLM=0 | ✓ | Automated acceptance test |
| D-08 empty summary retry | ✓ | `test_empty_summary_retries` |
| D-09 call_source dual-register | ✓ | SPEC + enum + 45-value guardian |
| D-10 key_files / entry_points / responsibility | ✓ | JSON normalize in `module_summary.py` |
| D-11 serial LLM; small skip | ✓ | reconcile loop serial; size guard |
| D-12 community.py + module_summary.py | ✓ | under `services/code_graph/` |
| D-13 freeze repo_router_v2 / mcp | ✓ | no 125 commits; import guard tests |
| D-14 evidence only, no 4th score component | ✓ | `_COMPONENT_KEYS` still 3; breakdown tests |
| D-15 signal fail-soft, no score change | ✓ | `ModuleSummarySignalItem.blended_score` |
| D-16 research prompt sort + budget | ✓ | max_chars=2000 / max_items=5; empty-section guard |

### Review Fixes (CR-01 / WR-01…04)

| Finding | Status | Evidence |
| --- | --- | --- |
| CR-01 atomic persist | ✓ FIXED | `transaction.atomic()` + `_unique_community_key` in `_persist_communities` (`f64d203c`) |
| WR-01 branch_name passthrough | ✓ FIXED | `normalized_branch or ""` / `branch_name or ""` at both hooks (`eca014bf`) |
| WR-02 member_keys for Jaccard | ✓ FIXED | model field + migration 0012 + load prefers stored keys (`35941053`) |
| WR-03 summary_model / generated_at | ✓ FIXED | set in `agenerate_module_summary` + reconcile backfill (`b0bdd1ec`) |
| WR-04 redact on adapter failures | ✓ FIXED | `redact_secrets_in_text` + category/component (`deea8871`) |

Info findings IN-01 (degree metadata) / IN-02 (enqueue started event) remain out of fix scope — not roadmap blockers.

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | ------- | ------ | ------- |
| `server/codegraph/models.py` | SymbolCommunity | ✓ VERIFIED | Soft-ref model + member_keys |
| `server/codegraph/migrations/0011_symbolcommunity.py` | ADD TABLE | ✓ VERIFIED | CreateModel only |
| `server/codegraph/migrations/0012_symbolcommunity_member_keys.py` | member_keys | ✓ VERIFIED | Review fix WR-02 |
| `server/services/code_graph/community.py` | Louvain + reconcile + persist | ✓ VERIFIED | 601 lines; substantive |
| `server/services/code_graph/module_summary.py` | LLM + call_source | ✓ VERIFIED | 323 lines; wired from durable |
| `server/services/community_enqueue.py` | QUEUE_GRAPH defer | ✓ VERIFIED | Wired from dual hooks |
| `server/services/module_summary_signal.py` | adapter signal | ✓ VERIFIED | Wired relevance + MCP |
| `server/durable/tasks.py` + `tasks_impl.py` | durable_community_rebuild | ✓ VERIFIED | Handler registered |
| `.planning/observability/LOGGING-SPEC.md` | module_summary | ✓ VERIFIED | §4.1 row + 45 values |
| `server/agents/call_source.py` | MODULE_SUMMARY | ✓ VERIFIED | Enum member |
| Frozen surface tests | D-13 guard | ✓ VERIFIED | Import + git path guards |

`gsd-tools query verify.artifacts` on 125-04 flagged `blueprint_research_adapter.py` “Missing pattern” — **false negative**: file contains `_summarize_module_summaries` / `module_summaries` and calls `render_module_summaries_section`. Manual L1–L3: VERIFIED.

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| graph_builder / code_relations | enqueue_community_rebuild | post-invalidate best-effort | ✓ WIRED | branch_name passed (WR-01) |
| durable_community_rebuild | rebuild_communities | run_community_rebuild + get_graph | ✓ WIRED | summary_fn=agenerate_module_summary |
| rebuild_communities | agenerate_module_summary | summary_fn only for need_llm | ✓ WIRED | skip path avoids calls |
| repository_relevance / RouteRepositoriesView | aapply_module_summary_signal | charter-旁路 | ✓ WIRED | both call sites |
| blueprint_route evidence | SymbolCommunity | aload_module_summaries_for_repos | ✓ WIRED | fail-soft + redact |
| research adapter | render_module_summaries_section | evidence.module_summaries | ✓ WIRED | budget truncate |

(`gsd-tools verify.key-links` reported “Source file not found” for multi-path `from` strings — ignored; manual wiring confirmed.)

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| SymbolCommunity rows | members / summary | detect_communities → reconcile → ORM | Graph nodes + optional LLM | ✓ FLOWING |
| blueprint evidence.module_summaries | per-repo list | aload_module_summaries_for_repos | DB SymbolCommunity.summary | ✓ FLOWING |
| research prompt section | module_section | evidence → render_module_summaries_section | Same summaries, ranked/truncated | ✓ FLOWING |
| route signal evidence | ModuleSummarySignalItem.evidence | aapply_module_summary_signal | DB summaries; score unchanged | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Scoped community/module_summary/adapter suite | `uv run pytest` (8 files listed below) | 51 passed | ✓ PASS |
| blueprint module_summaries evidence | `test_blueprint_route_breakdown.py -k module_summar` | 1 passed | ✓ PASS |
| Full suite / `-m perf` | — | Not run (per instruction) | ✓ SKIP |

Scoped command:

```bash
GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False \
  uv run pytest \
  tests/services/code_graph/test_community.py \
  tests/services/code_graph/test_module_summary.py \
  tests/services/code_graph/test_community_enqueue.py \
  tests/codegraph/test_symbol_community_model.py \
  tests/services/test_module_summary_signal.py \
  tests/services/process_runtime/test_module_summary_prompt.py \
  tests/services/code_graph/test_frozen_surface_125.py \
  tests/test_model_usage_call_source.py \
  --reuse-db
```

### Probe Execution

| Probe | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| — | — | No phase-declared or conventional probes | SKIPPED |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| MOD-01 | 125-01/02 | Louvain + soft-ref model + auto refresh | ✓ SATISFIED | SC1 artifacts + enqueue + tests |
| MOD-02 | 125-01/03 | Fingerprint/Jaccard skip; rebuild×2 LLM=0 | ✓ SATISFIED | SC2 + acceptance test |
| MOD-03 | 125-01/03 | LLM module summary + call_source | ✓ SATISFIED | SC3 + dual registration |
| MOD-04 | 125-01/04 | Adapter injection; freeze router_v2 | ✓ SATISFIED | SC4 + frozen git/import guards |

No orphaned REQUIREMENTS.md IDs for Phase 125 beyond MOD-01…04.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| — | — | No TBD/FIXME/XXX in phase production files | — | — |
| `test_frozen_surface_125.py` | git grep `125-04` only | Narrower than all `125-*` commits | ℹ️ Info | Manual check of all `--grep=125` commits still shows zero frozen-path touches |
| graph/edge hooks | enqueue call | omit `initiated_by_user_id` | ℹ️ Info | Defaults to `system` per D-03; not a goal failure |
| `_node_member` | — | no `degree` (IN-01) | ℹ️ Info | Ranking quality only; skip/LLM=0 unaffected |

### Human Verification Required

None required for phase goal closure. Automated acceptance covers MOD-02 rebuild×2 and adapter wiring. Optional live-LLM spot-check of `summary_model` metadata (WR-03 note) and production large-community Jaccard after migrate+rebuild (WR-02 note) are ops/smoke items, not blocking truths.

### Gaps Summary

No blocking gaps. Phase 125 roadmap SC1–4, MOD-01…04, CONTEXT D-01…D-16, and review fixes CR-01 / WR-01…04 are implemented and wired in the codebase; scoped tests pass (51 + 1 breakdown).

---

_Verified: 2026-08-09T20:44:51Z_
_Verifier: Claude (gsd-verifier)_
