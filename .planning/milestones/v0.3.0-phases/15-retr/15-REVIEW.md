---
phase: 15-retr
reviewed: 2026-06-12T12:00:00Z
depth: deep
files_reviewed: 13
files_reviewed_list:
  - server/knowledge/retrieval_types.py
  - server/knowledge/access_scope.py
  - server/knowledge/recency.py
  - server/knowledge/vector_recall.py
  - server/knowledge/metadata_hydrate.py
  - server/knowledge/timeline.py
  - server/knowledge/related.py
  - server/knowledge/graph_enrichment.py
  - server/knowledge/retrieval.py
  - server/knowledge/llm_grader.py
  - server/knowledge/api/views.py
  - server/knowledge/api/urls.py
  - server/knowledge/graph_store.py
findings:
  critical: 3
  warning: 7
  info: 2
  total: 12
status: issues_found
---

# Phase 15: Code Review Report

**Reviewed:** 2026-06-12T12:00:00Z  
**Depth:** deep  
**Files Reviewed:** 13  
**Status:** issues_found

## Summary

Phase 15 交付了完整的检索栈：权限 scope、向量分路召回、图扩散 enrich、时间衰减重排、PG 轨迹/关联查询、LLM 分级与内部 REST 测试面。整体架构与 Phase 15 CONTEXT 契约一致，fail-closed 权限与 GraphStore 收口模式运用得当。

**主要风险集中在向量召回的 `repository_id` 过滤语义**：摄取层对无仓库实体写空串 `""`（`vector_ops.py:71-96`），但召回层强制 `MatchAny(allowed_repository_ids)` 且 `allowed_repository_ids` 为空时直接短路返回，导致飞书 `work_item`（`repository_id=None`）等核心召回路径在实际部署中可能系统性漏召回。图扩散 enrich 也未透传 `repository_ids` 收窄，caller 指定仓库范围时关联实体可能越界。

---

## Critical Issues

### CR-01: 向量召回 mandatory repository filter 排除无仓库实体

**File:** `server/knowledge/vector_recall.py:64-70,178-179`  
**Issue:** `_build_knowledge_must_filter` 在 `allowed_repository_ids` 非空时追加 `repository_id MatchAny`。摄取契约中 `repository_id=None` 写为 `""`（`vector_ops.py:95-96`），飞书 work_item 摄取显式 `repository_id=None`（`sources/feishu_work_item.py:245`）。Qdrant 的 `MatchAny` 不会匹配空串，导致 **work_item / 无 repo 的 tech_plan 在 demand 分路永远召回不到**，直接违背 RETR-01「相似需求召回」核心场景。  
**Fix:**
```python
def _build_knowledge_must_filter(
    *,
    allowed_project_ids: list[str],
    allowed_repository_ids: list[str],
    entity_kinds: list[str] | None,
    include_superseded: bool,
    require_repository: bool = True,
) -> models.Filter:
    must: list[models.Condition] = [...]
    if require_repository and allowed_repository_ids:
        repo_values = list(allowed_repository_ids)
        # 无仓库实体 payload 为 ""，demand 分路需 OR 匹配
        if not require_repository:
            repo_values.append("")
        must.append(
            models.FieldCondition(
                key="repository_id",
                match=models.MatchAny(any=repo_values),
            )
        )
    ...

# recall_similar_chunks 内 demand_filter 传 require_repository=False
demand_filter = _build_knowledge_must_filter(..., require_repository=False)
code_filter = _build_knowledge_must_filter(..., require_repository=True)
```

---

### CR-02: allowed_repository_ids 为空时全链路零召回

**File:** `server/knowledge/vector_recall.py:178-179`  
**Issue:** `if not allowed_project_ids or not allowed_repository_ids: return []` 在 project 可见但 M2M 未关联任何仓库（`project_without_repo` fixture 场景）时直接返回空，**零 Qdrant 调用**。此时 project 内仍可能有 `repository_id=""` 的 work_item/tech_plan 应可召回。与 access_scope 的 fail-closed 意图一致，但与 RETR-01 业务语义冲突。  
**Fix:**
```python
if not allowed_project_ids:
    return []
# 仅 code 分路需要 repo；demand 分路可在 allowed_repository_ids 为空时仍执行
if not allowed_repository_ids:
    code_limit = 0  # 跳过 code 分路
else:
    code_limit = max(1, math.ceil(top_k * 0.3))
```

---

### CR-03: 图扩散 enrich 未执行 repository 维度收窄

**File:** `server/knowledge/graph_enrichment.py:25-70`, `server/knowledge/retrieval.py:63-67`  
**Issue:** P6 双维权限要求 project + repository 联合过滤。`search_similar` 解析了 `allowed_repos` 并传入向量召回，但 `enrich_vector_hits` 只接收 `allowed_project_ids`。当 caller 传入 `repository_ids=[repo1]` 收窄时，图遍历仍返回同 project 下 **其他 repo 的 code_change**（仅校验 `str(entity.project_id) in allowed`）。这是 caller 收窄被图路径绕过的数据范围泄漏。  
**Fix:**
```python
async def enrich_vector_hits(
    hits: list[VectorHit],
    *,
    allowed_project_ids: list[str],
    allowed_repository_ids: list[str] | None = None,
    ...
):
    allowed_repos = set(allowed_repository_ids or [])
    ...
    if allowed_repos:
        repo = str(entity.repository_id) if entity.repository_id else ""
        if repo and repo not in allowed_repos:
            continue
        if not repo and entity.kind in _CODE_KINDS:
            continue  # code_change 必须有 repo
```

`retrieval.py` 调用处传入 `allowed_repository_ids=allowed_repos`。

---

## Warnings

### WR-01: timeline 每个版本节点重复挂接相同 code_changes

**File:** `server/knowledge/timeline.py:68-71`  
**Issue:** `_code_change_keys_for_version(entity_id)` 在 `for ver in versions` 循环内调用，但函数只按 `entity_id` 查 IMPLEMENTED_BY 边，**不区分 version**。多版本 tech_plan 的每个节点都会挂接全量 code_change，无法表达「方案 vN 对应哪次编码」。  
**Fix:** 将 `_code_change_keys_for_version` 移到循环外调用一次；若边模型支持 version 维度，按 `valid_at`/`as_of` 过滤到对应版本区间。

---

### WR-02: resolve_allowed_repository_ids 忽略 caller project_ids 收窄

**File:** `server/knowledge/access_scope.py:61`, `server/knowledge/retrieval.py:45-46`  
**Issue:** `resolve_allowed_repository_ids(user, repository_ids)` 内部调用 `resolve_allowed_project_ids(user)` **未传入** `retrieval.py` 已解析的 `project_ids`。caller 仅传 `project_ids=[P1]` 时，repo 集合仍来自用户全部可见 project，可能导致 repo 解析与 project 收窄不一致（虽向量 project filter 兜底，但语义混乱且影响 superuser 窄 repo 场景）。  
**Fix:** 为 `resolve_allowed_repository_ids` 增加 `project_ids: list[str] | None = None` 参数并透传。

---

### WR-03: LLM grader snippet 未含摘要内容

**File:** `server/knowledge/llm_grader.py:44-50`  
**Issue:** ENH-02 要求「每候选 title+摘要 ≤500 字」，但 `snippet` 字段重复使用了 `r.entity.title`，`EntityMetadata` 也无 content 字段。LLM 分级缺乏语义输入，duplicate/unrelated 判定质量严重降级。  
**Fix:** hydrate 阶段补充 `summary`/`content` 字段（截断 500 字），grader 使用 `snippet: _truncate(meta.summary or meta.title)`。

---

### WR-04: REST 测试端点 query 参数 int 解析无校验

**File:** `server/knowledge/api/views.py:27,74`  
**Issue:** `int(request.query_params.get("top_k", 10))` / `max_hops` 在非法输入时抛 `ValueError`，async DRF view 返回 500 而非 400。  
**Fix:**
```python
try:
    top_k = int(request.query_params.get("top_k", 10))
except ValueError:
    return Response({"detail": "top_k must be integer"}, status=400)
```

---

### WR-05: graph_enrichment 硬编码 RELATES_TO 关系类型

**File:** `server/knowledge/graph_enrichment.py:64`  
**Issue:** 所有 enrich 出来的关联实体 `relation=EdgeRelation.RELATES_TO`，丢失 HAS_PLAN / IMPLEMENTED_BY 真实边类型，RETR-02 关联语义不准确。  
**Fix:** 对 1-hop 调用 `graph_store.neighbors` 建立 `relation_by_target` 映射（参照 `related.py:58-66`）。

---

### WR-06: related 多跳关系标签 fallback 误导

**File:** `server/knowledge/related.py:84`  
**Issue:** 多跳遍历结果用 `relation_by_target.get(item.entity_id, rels[0])` 回退到 `_DEFAULT_RELATIONS[0]`（HAS_PLAN），2-hop 的 code_change 可能被标为 HAS_PLAN。  
**Fix:** 多跳时使用 `"RELATED"` 占位或从 traverse 路径重建 relation；至少 fallback 为 `EdgeRelation.RELATES_TO` 而非 `rels[0]`。

---

### WR-07: timeline 节点 provenance 未填充

**File:** `server/knowledge/timeline.py:99-110`  
**Issue:** `TimelineNodeDTO` 含 `provenance` 字段（RETR-06），但 `build_entity_timeline` 构造节点时未调用 `_build_provenance`，输出缺少 feishu_url/mr_url/session_link。  
**Fix:** 在节点构造前 `provenance = await sync_to_async(_build_provenance)(entity, ver)` 并传入 `TimelineNodeDTO`。

---

## Info

### IN-01: hydrate_many 循环内逐条 sync_to_async

**File:** `server/knowledge/metadata_hydrate.py:149`  
**Issue:** 批量 hydrate 在 for 循环内对每个 key 单独 `await sync_to_async(_build_one)()`，`_build_provenance` 含 CodeChangeArchive 查询，N+1 严重。  
**Fix:** 将 `_build_one` 改为纯 sync 批量函数，单次 `sync_to_async` 处理全部 keys；或 prefetch archives。

---

### IN-02: timeline 循环内重复图边查询

**File:** `server/knowledge/timeline.py:71`  
**Issue:** `_code_change_keys_for_version` 在每个 version 迭代中重复执行相同 DB 查询，纯浪费（见 WR-01）。  
**Fix:**  hoist 到循环外。

---

## Potential Fix Priority

| ID | Severity | Suggested action |
|----|----------|------------------|
| CR-01 | BLOCKER | 必须修复 — demand 分路 OR 跳过 repository filter |
| CR-02 | BLOCKER | 必须修复 — 允许无 repo project 的 demand 召回 |
| CR-03 | BLOCKER | 必须修复 — enrich 透传 allowed_repository_ids |
| WR-01 | MEDIUM | 应修复 — timeline 语义正确性 |
| WR-02 | MEDIUM | 应修复 — scope 解析一致性 |
| WR-03 | MEDIUM | 应修复 — LLM 分级有效输入 |
| WR-04 | MEDIUM | 应修复 — API 健壮性 |
| WR-05–07 | MEDIUM | 建议修复 — 契约完整性与 UX |
| IN-01–02 | LOW | 可选 — 性能优化 |

---

_Reviewed: 2026-06-12T12:00:00Z_  
_Reviewer: Claude (gsd-code-reviewer)_  
_Depth: deep_
