---
phase: 33-hist-diff-bitemporal
verified: 2026-06-15T13:21:00Z
status: passed
score: 11/11 must-haves verified
overrides_applied: 0
deferred:
  - truth: "真实大 MR / 真实 master 演进的端到端验收（需真实 GitLab）"
    addressed_in: "human-UAT"
    evidence: "33-CONTEXT.md <deferred>：真实大 MR / 真实 master 演进的端到端人工验收 —— human-UAT（需真实 GitLab）；本 phase 用 seam fake 全覆盖可程序化验证的观察真理"
---

# Phase 33: 历史 diff 冻结 + bi-temporal 失效 Verification Report

**Phase Goal:** 把历史 MR diff 冻结为 commit 锚定快照（用 MR `target_branch` + `merge_commit_sha`，不假设 master）；master 演进后重索引对账把过期 `MODIFIES_CHUNK` 边置 `invalid_at`；查询按 as-of 区分历史/当前（HDIFF-01、HDIFF-02、PF-08）。
**Verified:** 2026-06-15T13:21:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| R1 | 历史 MR diff 冻结为 commit 锚定快照（target_branch + merge_commit_sha，不假设 master） | ✓ VERIFIED | `ingest_orchestrator.py:253-254` `commit_sha=anchor.merge_commit_sha` / `base_branch=anchor.target_branch`；测试 `test_ingest_orchestrator.py` 断言真实 sha + `release/v1`（非 master） |
| R2 | master 演进后重索引对账把过期 MODIFIES_CHUNK 边置 invalid_at | ✓ VERIFIED | `modifies_chunk.py:85-162` `areconcile_modifies_chunk_edges` 双信号判过期 → `invalidate_edge`；`TestReconcile` 删除/内容取代两类均置位（边行保留） |
| R3 | 查询按 as-of 区分历史/当前（历史边不污染当前视图） | ✓ VERIFIED | `modifies_chunk.py:39-82` `amodifies_chunk_edges` + `graph_store.bitemporal_as_of_q`；`TestAsOfQuery` 断言历史 as_of 见、当前视图不见、naive 拒绝 |
| P1-1 | MR diff 归档锚定真实 merge_commit_sha + target_branch | ✓ VERIFIED | 同 R1；`aresolve_mr_commit_anchor` (`diff_archive.py:545`) 拉真实元数据 |
| P1-2 | MODIFIES_CHUNK 边 valid_at 锚定 merge commit 业务时间（merged_at） | ✓ VERIFIED | `ingest_orchestrator.py` `event_time = anchor.merged_at`；测试断言边 valid_at == merged_at |
| P1-3 | 不再用合成 mr-{iid}；取不到 merge_commit_sha 如实 skipped | ✓ VERIFIED | `ingest_orchestrator.py:238-247` anchor None → `StepResult(status="skipped")` + return；测试断言无合成归档 |
| P1-4 | MODIFIES_CHUNK 边 metadata 含 chunk_content_hash 快照 | ✓ VERIFIED | `diff_archive.py:476-487` 批量回填；`_chunk_edge_spec` 占位键；`test_modifies_chunk.py` 三路径断言 == ChunkRegistry.content_hash |
| P2-1 | 过期边置 invalid_at（置位不删，保留历史） | ✓ VERIFIED | 同 R2；唯一经 `graph_store.invalidate_edge`，acount 不变（边行保留） |
| P2-2 | as-of：历史见当年边 / 当前视图只见未失效边 | ✓ VERIFIED | 同 R3 |
| P2-3 | 对账挂既有 reindex 钩子，best-effort 失败仅 warning 不阻断 | ✓ VERIFIED | `indexer.py:3469-3490` `_run_modifies_chunk_reconcile` 整段 try/except；`:3837` 挂在 `if not branch:` base 路径；`TestReconcileHookFailSafe` 验吞异常 |
| P2-4 | invalid_at 恒晚于 valid_at；逐边降级不掀翻批次 | ✓ VERIFIED | `modifies_chunk.py:144-154` 逐边 try/except（IntegrityError/DoesNotExist 仅 warning）；测试断言 invalid_at > valid_at + 异常边降级 |

**Score:** 11/11 truths verified

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | 真实大 MR / 真实 master 演进端到端验收 | human-UAT | 33-CONTEXT.md `<deferred>`：需真实 GitLab；本 phase 以 seam fake（FakeGitPlatformClient）覆盖全部可程序化真理 |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `services/git_platform/models.py` | `MRMetadataResult` 值对象 | ✓ VERIFIED | `class MRMetadataResult` 字段齐全（success/merge_commit_sha/target_branch/source_branch/merged_at/error） |
| `services/git_platform/base.py` | `get_merge_request_metadata` 抽象方法 | ✓ VERIFIED | `:118` 抽象方法定义 |
| `services/git_platform/{gitlab,github}_client.py` | 双客户端实现 | ✓ VERIFIED | 各 `:262` 实现，naive merged_at 归一 aware，失败 success=False 不上抛 |
| `knowledge/diff_archive.py` | `aresolve_mr_commit_anchor` + chunk 指纹戳记 | ✓ VERIFIED | `:545` helper（四分支降级）+ `:476-487` 批量回填 |
| `knowledge/modifies_chunk.py` | as-of helper + 对账函数 | ✓ VERIFIED | `amodifies_chunk_edges` + `areconcile_modifies_chunk_edges`，substantive |
| `knowledge/graph_store.py` | `bitemporal_as_of_q` + `chunk_in_edges(as_of=)` | ✓ VERIFIED | `:94` 公开谓词；`:264-283` as_of 可选参数（默认 None 零回归） |
| `services/indexer.py` | `_run_modifies_chunk_reconcile` 钩子 | ✓ VERIFIED | `:3469` 函数 + `:3837` base 路径挂载 |
| `delivery/services/ingest_orchestrator.py` | `_ingest_mr_diff` 真实 commit 锚 | ✓ VERIFIED | `:238-302` 真实 anchor + payload target_branch |

### Key Link Verification

| From | To | Via | Status |
|------|----|----|--------|
| `ingest_orchestrator._ingest_mr_diff` | `diff_archive.aresolve_mr_commit_anchor` | archive 前解析真实 commit 锚 | ✓ WIRED (`:229,:238`) |
| `diff_archive.aresolve_mr_commit_anchor` | `git_platform.get_merge_request_metadata` | client 拉 MR 元数据 | ✓ WIRED (`:572`) |
| `indexer.clone_and_index_repository` | `knowledge.modifies_chunk.areconcile_modifies_chunk_edges` | base 路径 best-effort 钩子 | ✓ WIRED (`:3483,:3837`) |
| `modifies_chunk.areconcile` | `graph_store.invalidate_edge` | 过期边逐条置位 | ✓ WIRED (`:145`) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 全部 phase 测试 | `pytest test_modifies_chunk_reconcile.py test_diff_archive.py test_modifies_chunk.py test_ingest_orchestrator.py -q` | 54 passed | ✓ PASS |
| 无新增 model 字段/migration | `manage.py makemigrations --check --dry-run` | No changes detected (EXIT=0) | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| HDIFF-01 | 33-01 | 历史 MR diff 冻结为 commit 锚定快照（target_branch + merge_commit_sha） | ✓ SATISFIED | R1/P1-* 全绿；REQUIREMENTS.md 标 Complete |
| HDIFF-02 | 33-02 | master 演进后重索引对账置 invalid_at + as-of 区分历史/当前（PF-08） | ✓ SATISFIED | R2/R3/P2-* 全绿；PF-08 根因（旧边不失效）已修 |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | 无 TBD/FIXME/XXX/PLACEHOLDER（phase-33 修改文件） | — | 无 |

`chunk_content_hash=""` 为 registry 缺行弱引用 chunk 的有意占位（reconcile 缺指纹时保守按存在性判定），非未接线 stub。

### Gaps Summary

无阻断 gap。Phase goal 三条 Success Criteria 与两 Plan 共 11 条 must-have truths 全部在代码中验证为已实现且接线（exists + substantive + wired + data-flow）；54 条 phase 测试全绿；`makemigrations --check` 干净，确认本 phase 无新增 model 字段/migration（复用 `CodeChangeArchive.commit_sha`/`base_branch` + `KnowledgeEdge.metadata`/bi-temporal 字段）。唯一未覆盖项为真实 GitLab 大 MR / master 演进端到端验收，已在 CONTEXT 显式 deferred 至 human-UAT，不构成本 phase gap。

---

_Verified: 2026-06-15T13:21:00Z_
_Verifier: Claude (gsd-verifier)_
