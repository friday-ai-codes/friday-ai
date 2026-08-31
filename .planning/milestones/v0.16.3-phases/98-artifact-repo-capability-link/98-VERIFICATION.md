---
phase: 98-artifact-repo-capability-link
verified: 2026-07-01T11:58:15Z
status: human_needed
score: 3/3 观察真相功能就位（KDEP-07/08/09）；两处测试完整性缺口已闭合，仅余 deferred live-env 召回质量待真机验证
re_verification:
  previous_status: none
  previous_score: n/a
gaps:

  - truth: "KDEP-08 verified RepoAssociation 同步为图谱边（功能就位，确定性红测已修复）"
    status: resolved
    reason: >-
      98-02 提交（74370358）在 knowledge_graph.py:328 的 sync_relations_from_operational
      docstring 里写了字面量 `RepoAssociation(status=verified)`，被 INV-6 源码扫描守护
      test_repo_association_inv6_guard.py::test_inv6_no_bypass 的正则
      `\b(?:RepoAssociation|RepoVerifyTask)\s*\(` 命中，判为"旁路写表"。这是误报——
      实际代码只 `.filter(...).select_related(...)`（只读），INV-6 唯一写入口不变。
      已改写该行 docstring 为"status == verified 的 ``RepoAssociation`` 行"，去除调用形
      字面量，正则不再命中；未触碰生产行为与守护测试本身。test_inv6_no_bypass 恢复绿
      （2 passed）。
    resolution:
      commit: "728411fb"
      change: "knowledge_graph.py:328 docstring 去调用形字面量；guard 测试 2 passed"
    artifacts:

      - path: "server/initiatives/services/knowledge_graph.py"
        issue: "第 328 行 docstring 含字面量 `RepoAssociation(status=verified)`，触发 INV-6 守护正则误报（已修复）"

  - truth: "KDEP-07 边 metadata 幂等 upsert 测试稳定通过（flaky 已修复）"
    status: resolved
    reason: >-
      test_edge_metadata_upsert.py::test_update_edge_metadata_invalidated_edge_is_noop
      间歇失败。实测复现定位真因：并非共享状态/顺序依赖，而是测试自身时序 flaky——
      `edge_factory(valid_at=timezone.now(), invalid_at=timezone.now())` 两次
      timezone.now() 可能落在同一微秒 tick，使 invalid_at == valid_at，违反
      `kedge_valid_range`(invalid_at > valid_at) 约束，抛 IntegrityError（CHECK
      constraint failed: kedge_valid_range）。生产 update_edge_metadata 正确。
      已改为 `valid = timezone.now(); invalid_at = valid + timedelta(seconds=1)`，
      确定性满足约束。整文件普通顺序连续运行 8/8 稳定 7 passed。
    resolution:
      commit: "728411fb"
      change: "invalid_at 显式落在 valid_at 之后；整文件连续 8 次运行全绿（7 passed×8）"
    artifacts:

      - path: "server/tests/knowledge/test_edge_metadata_upsert.py"
        issue: "invalid_at/valid_at 同微秒 tick 违反 kedge_valid_range 约束致时序 flaky（已修复）"
human_verification:

  - test: "真机·真实 provider·真实 Qdrant 下 RepoRouterV2 对工件正文的召回质量"
    expected: "ragable 工件正文经 RepoRouterV2.route 命中合理仓库 + matched_node_paths，落 RELATES_TO 边 metadata（score/node_paths/keywords）符合预期；无匹配时仅保留 project 边（fail-soft）"
    why_human: "路由召回质量依赖真实 LLM + 向量库 + 能力树数据，无法在单测 mock 下验证；CONTEXT.md/research §4 已标注需实测（deferred）"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 98: 工件↔仓库/能力/关键词关联 Verification Report

**Phase Goal:** 为外部依赖工件建立与代码仓库、业务能力、关键词的结构化关联，并把已确认的项目仓库关联同步进知识图谱，使关联可查询。
**Verified:** 2026-07-01T11:58:15Z
**Status:** human_needed（两处测试完整性缺口已闭合于 728411fb；仅余 deferred live-env 召回质量待真机验证）
**Re-verification:** No — initial verification

## Goal Achievement

三条成功标准（KDEP-07/08/09）在**生产代码层全部功能就位**，各自的专项测试通过；但本阶段
引入了 1 个**确定性红测**（INV-6 守护误报，docstring 措辞所致）和 1 个 **flaky 测试**
（edge_metadata 顺序依赖）。功能目标达成，缺口集中在**测试完整性/CI 绿**层面，修复量小。

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | KDEP-07：ragable 文字工件摄取/更新时经 RepoRouterV2 路由正文 → 落 artifact→repo `KnowledgeEdge(RELATES_TO)` + metadata{source,artifact_id,node_paths,keywords,score}；单一写入入口、call_source 观测、幂等 upsert、fail-soft、非 ragable 跳过 | ✓ VERIFIED | `sources/artifact.py:78-169`（`_route_artifact_body_edges`：`if not content: return ()`、`use_call_source(CallSource.AUX_REPO_ROUTER)`、命中构造 `EdgeSpec(RELATES_TO,…metadata=…)`、整体 `try/except # noqa: BLE001` 返回空 tuple、`artifact_repo_route_started/completed/failed`）；`artifact.py:362-370` 仅 `vectorize and content` 触发；写入收口 `ingestion.py:apply_edge_specs:415-421` 命中活跃边 + `spec.metadata is not None` → `update_edge_metadata` 覆盖，否则跳过（零回归）；`graph_store.py:281-307` `update_edge_metadata` 仅动活跃边、不碰四时间戳。测试：`test_artifact_repo_routing.py` 5 passed、`test_edge_metadata_upsert.py` 7 passed（`-v` 整文件）。 |
| 2 | KDEP-08：verified `RepoAssociation` 同步为项目↔仓库派生边（link/unlink/sync 收口），RepoAssociation 唯一真相源、边单向派生、幂等、离开 verified 失效 | ✓ VERIFIED（功能）/ ⚠ 引入红测 | `repo_association_service.py:554-619` `_sync_association_graph`（verified→`link_repository(metadata=…)`／else→`unlink_repository`，`try/except` best-effort）；三收口挂单一 hook：`record_verdict:621-641`（fit→verified/mismatch→失效）、`accept_mismatch:758-771`、`reopen_candidates:802-816`；`knowledge_graph.py:227-256` `link_repository(metadata)`、`258-293` `unlink_repository`（`invalidate_edge` 失效派生边）、`321-384` `sync_relations_from_operational`（`RepoAssociation.filter(status=VERIFIED)` **只读** 派生，唯一真相源不双写）、`_add_edge_idempotent:129-169`（幂等 upsert）。测试：`test_repo_association_graph_sync.py` 9 passed（隔离/组合）。**但**：见 Gap 1（docstring 触发 INV-6 守护误报，确定性红测）。 |
| 3 | KDEP-09：关联可查询（正向 artifact→仓库/能力/关键词；反向 仓库/能力/关键词→工件）走 graph_store 收口 + access_scope；只读端点 `GET /api/knowledge/artifacts/{id}/associations/`（authz + 404/401） | ✓ VERIFIED | `artifact_associations.py:62-312`（`get_artifact_associations` 正向 + `find_artifacts_by_repository/capability/keyword` 反向，全走 `graph_store.neighbors`；`resolve_allowed_project_ids/repository_ids` fail-closed 双维；异常 best-effort 返空 + `artifact_associations_query_failed`）；端点 `api/artifact_associations.py:30-56`（`IsAuthenticated`、薄委托、None→404）；`api/urls.py:21-23` 注册 `knowledge-artifact-associations`。测试：`test_artifact_associations_service.py` 10 passed + `test_artifact_associations_api.py` 4 passed（含越权 404 / 缺失 404 / 未认证 401）。 |

**Score:** 3/3 目标真相功能就位；2 项测试完整性缺口（1 确定性 + 1 flaky）待收口。

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `server/knowledge/graph_store.py` | `update_edge_metadata` 活跃边就地覆盖原语 | ✓ VERIFIED | 定义于 281-307，Protocol 声明 155；仅动活跃边，命中 0 行区分不存在（raise）/已失效（warning noop） |
| `server/knowledge/ingestion.py` | `apply_edge_specs` 携带 metadata + 幂等 upsert | ✓ VERIFIED | 400/433 建边补 `metadata=spec.metadata`；415-421 活跃边命中且 metadata 非空 → `update_edge_metadata` 覆盖 |
| `server/knowledge/sources/artifact.py` | 正文路由 RELATES_TO + fail-soft + call_source | ✓ VERIFIED | `_route_artifact_body_edges` 78-169；`vectorize and content` 门控 362-370 |
| `server/initiatives/services/knowledge_graph.py` | link/unlink/sync 派生边 + 单向 | ✓ VERIFIED（功能） | link 227-256 / unlink 258-293 / sync 321-384 / `_association_edge_metadata` 386-395；docstring 328 触发守护误报（Gap 1） |
| `server/initiatives/services/repo_association_service.py` | 单一同步 hook + 三收口 | ✓ VERIFIED | `_sync_association_graph` 554-619 + record_verdict/accept_mismatch/reopen 挂点 |
| `server/knowledge/artifact_associations.py` | 双向查询服务 graph_store 收口 + access_scope | ✓ VERIFIED | `ArtifactAssociationService` 59-312 |
| `server/knowledge/api/artifact_associations.py` | 只读端点 JWT + 404 | ✓ VERIFIED | `ArtifactAssociationsView` 30-56 |
| `server/knowledge/api/urls.py` | 路由注册 | ✓ VERIFIED | 21-23 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| artifact ingestion | RELATES_TO 边 | `_route_artifact_body_edges` → `EdgeSpec` → `apply_edge_specs` → `graph_store` | ✓ WIRED | 单一写入入口，无裸 SQL；`artifact.py:364` 调用挂在 ingestion 完成路径 |
| RepoAssociation verified 状态流转 | project→repo 派生边 | `record_verdict/accept_mismatch/reopen_candidates` → `_sync_association_graph` → `link/unlink_repository` | ✓ WIRED | 单一 hook 收口三处流转 |
| 只读端点 | 查询服务 | `ArtifactAssociationsView.get` → `ArtifactAssociationService.get_artifact_associations` → `graph_store.neighbors` | ✓ WIRED | 薄委托，access_scope fail-closed |

### Behavioral Spot-Checks / Probe Execution

无项目级 probe 声明；以专项 pytest 覆盖替代（见下）。

### Test Results (re-run by verifier)

| 测试集 | 命令 | 结果 |
|--------|------|------|
| Phase 98 knowledge（组合 `-k`） | `uv run pytest tests/knowledge -q -k "edge_metadata or artifact_repo_routing or artifact_association or repo_association_graph"` | **1 failed, 25 passed, 338 deselected**（failed = edge_metadata flaky，见 Gap 2） |
| edge_metadata（隔离整文件 `-v`） | `pytest tests/knowledge/test_edge_metadata_upsert.py -v` | **7 passed**（同文件普通运行间歇 1 failed → flaky） |
| artifact_repo_routing（隔离） | `pytest tests/knowledge/test_artifact_repo_routing.py` | **5 passed** |
| artifact_associations service+api（组合内） | 同组合 | **14 passed**（service 10 + api 4） |
| initiatives repo_association（`-k`） | `uv run pytest tests/initiatives -q -k "repo_association"` | **1 failed, 29 passed**（failed = `test_inv6_no_bypass`，见 Gap 1） |
| repo_association_graph_sync（隔离） | 组合 `-k` 内 | **9 passed** |
| inv6 guard（隔离） | `pytest tests/initiatives/test_repo_association_inv6_guard.py` | **1 failed, 1 passed**（确定性；`test_inv6_no_bypass` 命中 knowledge_graph.py:328 docstring 字面量） |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| KDEP-07 | 98-01 | 工件正文路由落 RELATES_TO 边 | ✓ SATISFIED | Truth 1；routing 5/5 + edge 7/7（-v） |
| KDEP-08 | 98-02 | verified RepoAssociation 同步派生边 | ⚠ SATISFIED（功能）/ 引入红测 | Truth 2；graph_sync 9/9；INV-6 守护误报红（Gap 1） |
| KDEP-09 | 98-03 | 双向查询 + 只读端点 | ✓ SATISFIED | Truth 3；service 10 + api 4 passed |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `initiatives/services/knowledge_graph.py` | 328 | docstring 字面量 `RepoAssociation(status=verified)` 触发 INV-6 源码扫描守护正则误报 | ⚠️ Warning | 使 `test_inv6_no_bypass` 确定性变红；非真实旁路写（代码仅 `.filter`），INV-6 不变量未破，但 CI 红。修复=改写措辞 |
| `tests/knowledge/test_edge_metadata_upsert.py` | — | 顺序/共享状态依赖（graph_store 单例 / async DB 行泄漏） | ⚠️ Warning | flaky：整文件间歇 1 failed，隔离/`-v` 通过。生产代码正确 |

无 `TBD/FIXME/XXX` 未引用债务标记；无占位/空实现 stub；所有边写入经 `EdgeSpec/graph_store` 收口（无裸 SQL）。

### Human Verification Required

#### 1. RepoRouterV2 工件正文召回质量（真机·真实 provider·真实 Qdrant）

**Test:** 对若干 ragable 文字工件在真实 LLM + 向量库 + 能力树数据下触发摄取，观察 `RepoRouterV2.route` 命中仓库 / `matched_node_paths` 与落边 metadata。
**Expected:** 命中合理仓库 + 能力路径，`RELATES_TO` 边 metadata（score/node_paths/keywords）符合预期；无匹配时 fail-soft 仅保留 project 边、不打断摄取。
**Why human:** 召回质量依赖真实模型/向量库/能力树，单测 mock 无法覆盖；CONTEXT.md + research §4 标注需实测（deferred，非本阶段失败项）。

### Gaps Summary

功能目标（KDEP-07/08/09）在代码层全部达成，专项行为测试通过（routing 5、graph_sync 9、associations 14、edge_metadata 7 于 `-v`）。两处缺口均在**测试完整性**层、修复量极小：

1. **INV-6 守护确定性红测（must-fix）**——98-02 提交在 `knowledge_graph.py:328` docstring 写了字面量 `RepoAssociation(status=verified)`，被纯源码扫描守护 `test_inv6_no_bypass` 的正则误判为旁路写表。**实际不是旁路写**（该处仅 `.filter().select_related()` 只读，INV-6 唯一写入口未破），但守护测试因措辞从绿变红且确定性复现。修复：改写该行 docstring 避免 `RepoAssociation(` 字面（去括号 / 全角括号），无需改生产行为。
2. **edge_metadata flaky（should-fix）**——`test_update_edge_metadata_invalidated_edge_is_noop` 存在顺序/共享状态依赖，整文件普通运行间歇失败（隔离与 `-v` 通过）。生产 `update_edge_metadata` 正确。修复：隔离测试的图/DB 状态。

live-env 召回质量按用户指令归入 human_verification（deferred），不计失败。

---

_Verified: 2026-07-01T11:58:15Z_
_Verifier: Claude (gsd-verifier)_
