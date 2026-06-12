---
phase: 15
slug: retr
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-12
updated: 2026-06-12
---

# Phase 15 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=9.0.2 + pytest-django + pytest-asyncio（`asyncio_mode=auto`）+ pytest-socket |
| **Config file** | `server/pyproject.toml [tool.pytest.ini_options]` |
| **Quick run command** | `cd server && uv run pytest tests/knowledge/ -x` |
| **Full suite command** | `cd server && uv run pytest tests/knowledge/ -x` |
| **Estimated runtime** | quick ~25s / full ~60s |

---

## Sampling Rate

- **After every task commit:** `cd server && uv run pytest tests/knowledge/ -x`
- **After every plan wave:** wave 对应 `-k` 前缀组（见下表）+ 全量 knowledge 套件
- **Before `/gsd-verify-work`:** knowledge 全绿 + `manage.py check` + eval fixture ≥20 条 smoke
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 15-01 Task 1 | 15-01 | 1 | RETR-07 | T-15-01 | fail-closed scope；caller project_ids 只能收窄 | unit | `cd server && uv run pytest tests/knowledge/test_access_scope.py -x` | ❌ 本任务创建 | ⬜ pending |
| 15-01 Task 2 | 15-01 | 1 | RETR-05 | — | 90d 半衰期；naive datetime 拒绝（P2） | unit | `cd server && uv run pytest tests/knowledge/test_recency.py -x` | ❌ 本任务创建 | ⬜ pending |
| 15-01 Task 3 | 15-01 | 1 | RETR-02 | T-15-03 | direction=both 多跳；失效边不可见（P2） | unit | `cd server && uv run pytest tests/knowledge/test_graph_store.py -k both -x` | ✅ 扩展 | ⬜ pending |
| 15-02 Task 1 | 15-02 | 2 | RETR-01, RETR-04, RETR-07 | T-15-04, T-15-05 | is_latest filter 不可 bypass（P1）；分路 RRF（P5）；allowed 空零查询（P6） | unit | `cd server && uv run pytest tests/knowledge/test_vector_recall.py -x` | ❌ 本任务创建 | ⬜ pending |
| 15-02 Task 2 | 15-02 | 2 | RETR-06, RETR-04 | — | metadata 出处字段；superseded_hint | unit | `cd server && uv run pytest tests/knowledge/test_vector_recall.py -k "hydrate or superseded" -x` | ✅ Task 1 创建 | ⬜ pending |
| 15-03 Task 1 | 15-03 | 2 | RETR-03 | T-15-09 | timeline 零 Qdrant（P10）；越权空 | unit | `cd server && uv run pytest tests/knowledge/test_timeline.py -x` | ❌ 本任务创建 | ⬜ pending |
| 15-03 Task 2 | 15-03 | 2 | RETR-02 | T-15-07, T-15-08 | 双向 2 跳；as_of 过滤失效边（P2） | unit | `cd server && uv run pytest tests/knowledge/test_related.py -x` | ❌ 本任务创建 | ⬜ pending |
| 15-04 Task 1 | 15-04 | 3 | RETR-05 | — | 图 enrich 1-2 跳 dedupe | unit | `cd server && uv run pytest tests/knowledge/test_hybrid_search.py -k enrich -x` | ❌ 本任务创建 | ⬜ pending |
| 15-04 Task 2 | 15-04 | 3 | RETR-01, RETR-05 | T-15-10 | search_similar 融合；as_of 透传 recency+GraphStore（P2） | unit | `cd server && uv run pytest tests/knowledge/test_hybrid_search.py -k "search_similar or fusion" -x` | ✅ Task 1 创建 | ⬜ pending |
| 15-05 Task 1 | 15-05 | 4 | ENH-02 | T-15-15 | LLM 分级；失败降级 | unit | `cd server && uv run pytest tests/knowledge/test_llm_grader.py -x` | ❌ 本任务创建 | ⬜ pending |
| 15-05 Task 2 | 15-05 | 4 | RETR-06, RETR-07 | T-15-13 | 端到端 + 越权 A→B；eval fixture smoke | integration | `cd server && uv run pytest tests/knowledge/test_delivery_search.py -x` | ❌ 本任务创建 | ⬜ pending |
| 15-05 Task 3 | 15-05 | 4 | RETR-07 | T-15-14 | REST JWT + service 委托 | api | `cd server && uv run pytest tests/knowledge/test_delivery_search.py -k api -x && uv run python manage.py check` | ❌ 本任务创建 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**防线固化测试：**
- P1：`test_vector_recall.py` 断言 filter must 含 is_latest=true
- P2：`test_recency.py` naive 拒绝；`test_related.py` as_of 边界
- P5：`test_vector_recall.py` 分路 quota 断言
- P6：`test_access_scope.py` + `test_delivery_search.py` 越权
- P10：`test_timeline.py` mock Qdrant 零调用 + grep timeline/related 无 Qdrant import

---

## Wave 0 Requirements

> 测试随实现 task 同 plan 交付（Phase 13 同款）。eval fixture 在 15-05 Task 2 创建。

- [ ] `test_access_scope.py` — 15-01 Task 1
- [ ] `test_recency.py` — 15-01 Task 2
- [ ] `test_graph_store.py` both 组扩展 — 15-01 Task 3
- [ ] `test_vector_recall.py` — 15-02 Task 1/2
- [ ] `test_timeline.py` / `test_related.py` — 15-03
- [ ] `test_hybrid_search.py` — 15-04
- [ ] `test_llm_grader.py` / `test_delivery_search.py` / `fixtures/retr_eval_queries.json` — 15-05

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实 Qdrant hybrid 召回 + is_latest filter | RETR-01/04 | 单测 mock client | compose 启 qdrant，预置 delivery_knowledge 点后 curl 内部 REST search |
| LLM 分级中文理由质量 | ENH-02 | mock 不测文案 | dev 配 provider 后手工 query，检查 duplicate/related 理由可读 |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies（12/12）
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 120s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
