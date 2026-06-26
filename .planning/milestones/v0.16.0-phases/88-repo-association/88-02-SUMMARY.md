# 88-02 SUMMARY — RepoAssociationService.propose/refine（COMBINED 选仓 + 观测 + INV-6）

**Plan:** 88-02 (REPO-01) · **Wave:** 2 · **Status:** ✅ DONE
**Requirement:** REPO-01（选仓智能 + 观测一半）

## 交付内容

### 新增文件

- `server/initiatives/services/repo_association_service.py` —— `RepoAssociationService`
  单一编排收口（INV-6）。方法：
  - `propose(*, space, feature_list=None, features_flat=None, project=None, initiated_by_user_id=None) -> dict`
  - `refine(*, space, project, feature_list/features_flat, extra_instruction, initiated_by_user_id, round_no=2) -> dict`
  - 内部：`_route_and_persist`（propose/refine 共用核心）、`_record_routing_trace`、
    `_resolve_repository_ids` / `_space_repository_ids`、`_normalize_features`、
    `_build_query`、`_candidate_dict`、`_persist_candidates` / `_awrite_candidates`（**唯一**
    RepoAssociation 写入口）、`_aresolve_project`。
- `server/tests/initiatives/test_repo_association_service.py` —— RepoRouterV2 seam
  （monkeypatch `RepoRouterV2.route`）：范围限定、call_source 作用域、RetrievalTrace、
  落 proposed、空 features / 空 Space 仓不全库 route、refine 含 extra_instruction。
- `server/tests/initiatives/test_repo_association_inv6_guard.py` —— grep 守护，allowed
  writer = `repo_association_service.py`，覆盖 `RepoAssociation` + `RepoVerifyTask`
  （镜像 `test_research_inv6_guard.py`，含 writer-actually-writes 正向断言）。

## 锁定决策落地

- **COMBINED 选仓复用 `RepoRouterV2.route`**（语义 hybrid + 活跃度 facet 降权 + LLM 树推理
  三合一，D-01/D-04）——**未自写打分**；query 由 `features_flat` 的 module/name/description
  拼成（D-06，去重 + 4000 字符截断防 DOS）。
- **候选范围限定 `Space.repositories`**（`_resolve_repository_ids`）——空仓 / 空 query 时
  **绝不全库 route**，直接返回 `router_version="skipped"` 空提案（Pitfall 6）。
- **多轮 refine = 重 route**：`extra_instruction` 作筛选/澄清约束并进 query 头部（V5 输入
  校验，不构造执行指令），复用 propose 的 route + 观测 + 落库；每轮各写一条 RetrievalTrace。
- **候选落 `RepoAssociation(status=proposed)`**：`update_or_create` on `(project, repository)`
  幂等，写 score/confidence/routed_reason/matched_node_paths/source="router_v2"/
  initiated_by_user_id；**唯一**写入口（INV-6，grep 守护固化）。
- **fail-soft**：RepoRouterV2 自带降级链；`arecord_retrieval_trace` best-effort（try/except
  吞，失败记 `repo_association_route_observability_failed` sampling/debug）；单候选落库失败
  隔离 continue；无 project 仅 warning 跳过落库（候选仍返回）。

## 观测（强制）

- **call_source**：route 调用包 `use_call_source(CallSource.AUX_REPO_ROUTER)`（枚举**预存**，
  本期首次启用）。**未新增** call_source 枚举 → baseline **保持 27**（88-01 已含
  `repo_association` / `repo_verify_container`）。
- **RetrievalTrace**：route 后 `arecord_retrieval_trace(kind="routing", payload={query,
  candidates, router_version}, source="repo_association")`；payload 入库经 ledger 内部
  `redact_for_ledger`；多轮每轮一条（覆盖 AI 对话召回链）。
- **结构化事件**：`repo_association_proposed` / `repo_association_refined`（caller，
  component=`repo_association`，+duration_ms / candidate_count / router_version /
  round / query_len / scoped_repo_count / initiated_by_user_id）；日志仅记长度/计数，
  **不回显** feature 正文；异常经 `redact_secrets_in_text`。

## 测试结果

- `pytest tests/initiatives/test_repo_association_service.py tests/initiatives/test_repo_association_inv6_guard.py -q` → **8 passed**
- `pytest tests/test_model_usage_call_source.py tests/initiatives/test_repo_association_models.py -q` → **32 passed**（call_source baseline = 27 不变）
- `pytest tests/initiatives -q` → **309 passed**（无回归）

## 给 88-03/88-04 的输出契约（output shape）

`propose` / `refine` 返回：

```python
{
  "candidates": [
    {"repo_id": str, "repo_name": str, "score": float,
     "confidence": "high"|"medium"|"low", "reason": str, "matched_node_paths": [str]}
  ],
  "router_version": "v2" | "v2_stage0_only" | "v1_fallback" | "skipped",
  "auto_selected": bool,   # high confidence 首位自动选定
  "query_len": int,
}
```

落库：每候选一行 `RepoAssociation(project, repository, status=proposed, score,
confidence, routed_reason, matched_node_paths, source="router_v2", initiated_by_user_id)`，
`(project, repository)` 唯一幂等。88-03（per-repo 容器深验 dispatch）从 proposed/confirmed
关联读 `RepoVerifyTask`（写入仍只经本 service，INV-6 守护已覆盖 RepoVerifyTask）；
88-04（候选卡片）直接消费 `candidates` 列表（reason/confidence/score 展示）。

## Blockers

- 无。88-03 将让 service 新增 `RepoVerifyTask` 写入 + per-repo explore 容器 dispatch（复刻
  `ResearchDispatchAdapter`）；INV-6 守护已对 `RepoVerifyTask` 一并生效，届时落写入即可。
