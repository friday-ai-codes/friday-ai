---
phase: 98-artifact-repo-capability-link
reviewed: 2026-07-01T20:15:00Z
depth: deep
files_reviewed: 8
files_reviewed_list:
  - server/knowledge/graph_store.py
  - server/knowledge/ingestion.py
  - server/knowledge/sources/artifact.py
  - server/knowledge/artifact_associations.py
  - server/knowledge/api/artifact_associations.py
  - server/knowledge/api/urls.py
  - server/initiatives/services/knowledge_graph.py
  - server/initiatives/services/repo_association_service.py
findings:
  blocker: 0
  high: 0
  medium: 2
  low: 2
  info: 1
  total: 5
status: clean
resolved: true
resolved_at: 2026-07-01T20:30:00Z
resolution_note: 全部 5 项已修复（MED-01/MED-02/LOW-01/LOW-02/INF-01）；tests/knowledge 相关用例绿、ruff 通过。
---

# Phase 98: Code Review Report — 工件↔仓库/能力/关键词关联 (v0.16.3)

**Reviewed:** 2026-07-01T20:15:00Z
**Depth:** deep (cross-file: ingestion ↔ graph_store ↔ knowledge_graph ↔ repo_association ↔ query service ↔ API)
**Files Reviewed:** 8 source files (KDEP-07/08/09；commits `9a44663a` `74370358` `fceba900` `728411fb`)
**Status:** clean（无 BLOCKER / HIGH；2 MEDIUM + 2 LOW + 1 INFO）

## Summary

对 Phase 98 三个交付切片做对抗式审查，逐条核对 review 要点：

- **边幂等（KDEP-07）✅**：`apply_edge_specs` 与 `_add_edge_idempotent` 均先 `neighbors` 命中同 target 活跃边，命中即 `update_edge_metadata` 覆盖、不新建；`update_edge_metadata` 只对 `invalid_at IS NULL AND expired_at IS NULL` 就地 `aupdate`，不碰时间戳、0 行区分不存在(raise)/非活跃(warning)。重跑同一工件对**同一 target** 无重复边。
- **路由 hook best-effort（KDEP-07）✅**：`_route_artifact_body_edges` 全体（含延迟 import / route / ensure_repository_node / spec 构造）包在 try/except，异常吞掉返回 `()`，绝不反噬摄取；`content` 空/无仓库提前返回。
- **RepoAssociation 单向派生（KDEP-08）✅**：`record_verdict`(fit→verified 派生 / mismatch→失效)、`accept_mismatch`(→verified 派生)、`reopen_candidates`(离开→失效) 三入口都挂 `_sync_association_graph` 单一 hook；hook 整体 try/except best-effort；`unlink_repository` 对 project→repo 活跃 RELATES_TO 出边逐条失效置位；RepoAssociation 只读、不双写真相源。
- **双向查询（KDEP-09）✅**：正向 `neighbors(out)` + `metadata.source=="artifact"` 过滤；反向 `neighbors(in)`；repo_association 派生边（source="repo_association"）被正确排除。
- **Security ✅（主路径）**：正向 `get_artifact_associations` 对 `entity.space_id ∈ resolve_allowed_project_ids(user)` fail-closed（`get_user_projects` 返回 `Space`，与 `space_id` 同维——membership 路径一致）；不可见→`None`→端点 404；反向双维过滤（`resolve_allowed_repository_ids` + `_hydrate_artifacts` 二次 space 过滤）。端点 `IsAuthenticated`→401，`<uuid:>` 转换器挡非法 id。`call_source` 复用 `AUX_REPO_ROUTER` 无新增基数；路由正文不入日志。INV-6 未被绕过（图谱边全经 EdgeSpec/graph_store，RepoAssociation 仍是唯一写者）。

发现集中在两点非阻断问题：查询服务异常文本**未脱敏**（与强制日志规范及本 Phase 其余文件不一致），以及工件→仓库路由边**无失效路径导致重摄取后陈旧边累积**。

---

## Medium

### MED-01: 查询服务异常文本未经 `redact_secrets_in_text` 脱敏（违反强制脱敏规范）

> ✅ **已修复**：`artifact_associations.py` 顶部引入 `redact_secrets_in_text`，正向/反向两处 `error=redact_secrets_in_text(str(exc))`。

**File:** `server/knowledge/artifact_associations.py:137` 与 `:221`
**Issue:** 两处 `except` 分支直接 `error=str(exc)` 落日志，未做脱敏：

```python
# :131-140 forward
logger.warning("artifact_associations_query_failed", ..., error=str(exc), ...)
# :216-225 reverse_repository
logger.warning("artifact_associations_query_failed", ..., error=str(exc), ...)
```

`.cursor/rules/observability-logging.mdc`「脱敏不可绕过」要求异常/上游文本手动走 `redact_secrets_in_text`。本 Phase 其余文件均已遵守（`sources/artifact.py:164/274/294`、`repo_association_service.py` 多处），此处形成不一致的潜在明文泄漏面（异常虽多来自 ORM/graph_store，但规范为强制、无豁免）。
**Fix:** 顶部 `from common.logging import redact_secrets_in_text`，两处改为：

```python
error=redact_secrets_in_text(str(exc)),
```

### MED-02: 工件→仓库 `RELATES_TO` 路由边缺失效路径，重摄取后陈旧/累积边泄入查询

> ✅ **已修复**：`sources/artifact.py` 新增 `_invalidate_stale_artifact_routing_edges`——路由命中集算出后按 target 收敛，失效该工件既有 `source=="artifact"` 活跃 `RELATES_TO` 出边中不在本轮命中集的边（复用 `graph_store.invalidate_edge`，幂等、独立 best-effort 包 try/except、失败不丢新边）。`artifact_repo_route_completed` 增 `stale_edge_count` 观测。新增 `test_reingest_invalidates_stale_repo_edge` / `test_reingest_same_matches_no_invalidation` 覆盖收敛与幂等 no-op。

**File:** `server/knowledge/sources/artifact.py:132-144`（EdgeSpec 构造）配合 `server/knowledge/ingestion.py:412-422`
**Issue:** 工件路由边为 `EdgeSpec(RELATES_TO, exclusive=False, metadata={source:"artifact",...})`。`apply_edge_specs` 对**同一 target** 幂等 upsert（无重复，符合要求），但对**不同 target** 无 exclusive/失效逻辑：工件重摄取（title/正文变更→版本翻转→路由重跑，且 `RepoRouterV2 use_llm=True` 存在非确定性）若命中仓库集合发生变化（如上轮命中 repo A、本轮命中 repo B），旧的 `artifact→A` 活跃边**不会失效**，与 `artifact→B` 一同保留。正向 `get_artifact_associations` / 反向 `find_artifacts_by_repository` 会返回已不再匹配的陈旧仓库。

范围说明：该「陈旧边」隐患本 Phase 仅对 RepoAssociation 派生边显式约束；工件路由边的 review 要求仅为「无重复边」（已满足）。故列 MEDIUM 而非阻断，但确为跨重摄取的查询正确性衰减。
**Fix:** 在 `_route_artifact_body_edges` 完成路由后，对该工件实体既有 `source=="artifact"` 的活跃 `RELATES_TO` 出边中、不在本轮命中集合的边显式失效（新增一条经 `graph_store.invalidate_edge` 的收敛步骤，仍 best-effort 包在 try/except），使派生边集与最新路由结果一致；或为工件路由边引入「按 source 分组的 exclusive-set」语义。

---

## Low

### LOW-01: `_route_artifact_body_edges` 未使用的导入 `repository_node_id`

> ✅ **已修复**：延迟导入改为 `from initiatives.services.knowledge_graph import ProjectKnowledgeGraphService`，移除死导入。

**File:** `server/knowledge/sources/artifact.py:94-98`
**Issue:** 函数内延迟导入 `repository_node_id`，但仓库节点实际经 `graph_svc.ensure_repository_node(repository)`（:127）获得，`repository_node_id` 全函数未引用——死导入。
**Fix:** 从 import 中移除 `repository_node_id`：

```python
from initiatives.services.knowledge_graph import ProjectKnowledgeGraphService
```

### LOW-02: `_route_artifact_body_edges` 未使用的形参 `project`

> ✅ **已修复**：从签名与 `normalize` 调用点删除 `project=`（`project` 变量在 `normalize` 内其余用途保留）。

**File:** `server/knowledge/sources/artifact.py:78-80`
**Issue:** 签名含 `project`（`normalize` 于 :366 传入），但函数体从未使用（仅用 `artifact`/`space`/`content`/`request`）。死参数增加噪声与误读风险。
**Fix:** 从签名与调用点删除 `project=`，或若为前瞻扩展位则加注释说明保留意图。

---

## Info

### INF-01: `artifact_associations_query_failed` 失败事件缺 `duration_ms`

> ✅ **已修复**：正向/反向两处失败 warning 追加 `duration_ms=round((time.perf_counter() - started) * 1000, 2)`。

**File:** `server/knowledge/artifact_associations.py:131-140` / `:216-225`
**Issue:** `started = time.perf_counter()` 已取，但失败分支未上报 `duration_ms`（成功分支有）。日志规范建议关键生命周期 started/completed/**failed** 均带 `duration_ms`，便于失败时延分析。
**Fix:** 两处 warning 追加 `duration_ms=round((time.perf_counter() - started) * 1000, 2)`。

---

_Reviewed: 2026-07-01T20:15:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
