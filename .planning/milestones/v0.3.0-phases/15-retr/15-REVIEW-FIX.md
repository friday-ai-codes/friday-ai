---
phase: 15-retr
fixed_at: 2026-06-12T12:30:00Z
review_path: .planning/phases/15-retr/15-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
---

# Phase 15: Code Review Fix Report

**Fixed at:** 2026-06-12T12:30:00Z
**Source review:** `.planning/phases/15-retr/15-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 6
- Fixed: 6
- Skipped: 0

## Fixed Issues

### CR-01: 向量召回 mandatory repository filter 排除无仓库实体

**Files modified:** `server/knowledge/vector_recall.py`
**Commit:** 070a6f80
**Applied fix:** Added `require_repository` parameter to `_build_knowledge_must_filter`; demand branch passes `require_repository=False` and OR-matches `""` alongside allowed repo IDs.

### CR-02: allowed_repository_ids 为空时全链路零召回

**Files modified:** `server/knowledge/vector_recall.py`
**Commit:** 070a6f80
**Applied fix:** Early return only when `allowed_project_ids` is empty; skip code route (`code_limit=0`) when no repos, still execute demand route.

### CR-03: 图扩散 enrich 未执行 repository 维度收窄

**Files modified:** `server/knowledge/graph_enrichment.py`, `server/knowledge/retrieval.py`
**Commit:** c9771641
**Applied fix:** `enrich_vector_hits` accepts `allowed_repository_ids` and filters code_change entities without matching repo; retrieval passes `allowed_repos`.

### WR-01: timeline 每个版本节点重复挂接相同 code_changes

**Files modified:** `server/knowledge/timeline.py`
**Commit:** de831ade
**Applied fix:** Hoisted `_code_change_keys_for_version` call outside the version loop.

### WR-02: resolve_allowed_repository_ids 忽略 caller project_ids 收窄

**Files modified:** `server/knowledge/access_scope.py`, `server/knowledge/retrieval.py`
**Commit:** c9771641
**Applied fix:** Added `project_ids` parameter to `resolve_allowed_repository_ids`; retrieval passes resolved `allowed_projects`.

### WR-04: REST 测试端点 query 参数 int 解析无校验

**Files modified:** `server/knowledge/api/views.py`
**Commit:** 7c3c9c6c
**Applied fix:** Added `_parse_int_param` helper returning 400 on invalid `top_k` / `max_hops`.

## Test Results

```
uv run pytest tests/knowledge/ -q
255 passed, 1 deselected in 36.49s
```

---

_Fixed: 2026-06-12T12:30:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
