---
phase: 125
slug: community-summary
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-10
---

# Phase 125 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 + pytest-django + pytest-asyncio |
| **Config file** | `server/pyproject.toml`（`[tool.pytest.ini_options]`） |
| **Quick run command** | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest tests/services/code_graph/test_community.py tests/services/code_graph/test_module_summary.py tests/services/test_module_summary_signal.py tests/test_model_usage_call_source.py -q --reuse-db` |
| **Full suite command** | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest tests/services/code_graph/test_community.py tests/services/code_graph/test_module_summary.py tests/services/code_graph/test_community_enqueue.py tests/services/code_graph/test_frozen_surface_125.py tests/codegraph/test_symbol_community_model.py tests/services/test_module_summary_signal.py tests/services/process_runtime/test_module_summary_prompt.py tests/services/process_runtime/test_blueprint_route_breakdown.py tests/test_model_usage_call_source.py -q --reuse-db` |
| **Estimated runtime** | ~15–30 seconds (**quick** / task-scoped)；~60–120 seconds (**full** / wave·phase gate) |

---

## Sampling Rate

- **After every task commit (quick):** Run **Quick run command** above — target feedback **≤30s**（task-scoped / listed files only）
- **After every plan wave (full):** Run **Full suite command** above — expected **~60–120s**（phase gate，非 per-task 延迟）
- **Before `/gsd-verify-work`:** Full suite must be green; MOD-02 `test_rebuild_twice_zero_llm` must pass
- **Max feedback latency:** quick ≤30s（task）；full ≤120s（wave/phase gate）

> **Latency note:** Task-level `<automated>` 使用 scoped pytest（单文件/单节点），保持 quick 反馈；全量 suite 仅在 wave merge / phase gate 运行，不作为每 task 的 Nyquist 延迟约束。

---

## Per-Task Verification Map

> Canonical 4-plan map（⛔ 禁止 `125-05` 或任何第五 plan 行）。Wave / Requirement / Command 与 `125-01`…`125-04` frontmatter 一一对齐。

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|---------|-----------------|-----------|-------------------|-------------|--------|
| 125-01 | 01 | 0 | MOD-01..04 | — | call_source 双登记；Wave 0 桩可收集 | stubs+unit | `uv run pytest tests/test_model_usage_call_source.py::TestCallSourceEnum tests/services/code_graph/test_community.py tests/services/code_graph/test_module_summary.py tests/services/code_graph/test_community_enqueue.py tests/services/code_graph/test_frozen_surface_125.py tests/codegraph/test_symbol_community_model.py tests/services/test_module_summary_signal.py tests/services/process_runtime/test_module_summary_prompt.py --collect-only -q` | ✅ | ⬜ pending |
| 125-02 | 02 | 1 | MOD-01 | T-125-01 | 只经 get_graph 取图；enqueue 非内联 | unit+db | `uv run pytest tests/codegraph/test_symbol_community_model.py tests/services/code_graph/test_community.py::test_louvain_seed_stable tests/services/code_graph/test_community_enqueue.py -x` | ✅ W0 stubs | ⬜ pending |
| 125-03 | 03 | 2 | MOD-02+03 | T-125-02 | 空 summary 可重试；call_source；rebuild×2 LLM=0 | unit | `uv run pytest tests/services/code_graph/test_community.py::test_rebuild_twice_zero_llm tests/services/code_graph/test_module_summary.py -x` | ✅ W0 stubs | ⬜ pending |
| 125-04 | 04 | 3 | MOD-04 | T-125-01/03 | fail-soft；冻结面零改 `repo_router_v2` | unit | `uv run pytest tests/services/test_module_summary_signal.py tests/services/process_runtime/test_blueprint_route_breakdown.py tests/services/process_runtime/test_module_summary_prompt.py tests/services/code_graph/test_frozen_surface_125.py -x` | ✅ W0 stubs | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/services/code_graph/test_community.py` — Louvain 稳定 / 指纹 / Jaccard / rebuild×2 LLM=0（MOD-01/02）
- [x] `tests/services/code_graph/test_module_summary.py` — call_source + fail-soft + 规模门槛（MOD-03）
- [x] `tests/services/test_module_summary_signal.py` — adapter fail-soft（MOD-04）
- [x] `tests/services/process_runtime/test_module_summary_prompt.py` — 空段 + 预算（MOD-04）
- [x] `tests/codegraph/test_symbol_community_model.py` — 模型字段 / 无 Symbol FK（MOD-01）
- [x] `tests/services/code_graph/test_community_enqueue.py` — defer + lock 键（MOD-01）
- [x] `tests/services/code_graph/test_frozen_surface_125.py` — 冻结面守卫（MOD-04）
- [x] 扩展 `tests/test_model_usage_call_source.py`：`module_summary` → 45 值
- [ ] 扩展 `tests/services/process_runtime/test_blueprint_route_breakdown.py`：`module_summaries` 默认 `[]`
- [x] Wave 0 文档任务：LOGGING-SPEC §4.1 登记 `module_summary`（**先于**调用点代码）

*Existing infrastructure (pytest + django) covers framework; stubs above are required.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 生产图连续重建 Jaccard 分布校准 | MOD-02 | 需真实仓图数据 | 相位内跑诊断命令，写 SUMMARY；阈值可调但验收语义不变 |

*All other phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency: quick &lt; 30s（task）；full &lt; 120s（wave/phase）
- [x] Per-Task Verification Map 恰好 4 行（125-01..04），无 125-05
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
