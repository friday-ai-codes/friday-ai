# Phase 33: 历史 diff 冻结 + bi-temporal 失效 - Context

**Gathered:** 2026-06-15
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — recommendations auto-accepted)

<domain>
## Phase Boundary

把历史 MR diff 冻结为 **commit 锚定快照**（用 MR `target_branch` + `merge_commit_sha`，不假设 master）；master/目标分支演进后，重索引对账把过期 `MODIFIES_CHUNK` 边置 `invalid_at`；查询按 **as-of** 区分历史/当前关联（历史"当年成立"的边不污染当前视图）。修 PF-08。

覆盖需求：HDIFF-01（commit 锚定冻结）、HDIFF-02（重索引对账置 invalid_at + as-of 查询）。
依赖：既有 `CodeChangeArchive` / diff 归档（相对独立，可较晚做，不强依赖前序 delivery phase）。
不变量：INV-3（knowledge 投影 bi-temporal）。
范围：本 phase 是 knowledge 侧 diff 边的时效治理——不改 delivery 脊柱，不改检索 UI。
</domain>

<decisions>
## Implementation Decisions

### commit 锚定冻结（Grey Area 1，HDIFF-01）
- 历史 MR diff 归档/对齐**锚定真实 commit**：用 MR 的 `merge_commit_sha`（已合并）+ `target_branch`，**绝不假设 master**（DOMAIN §1.5 实测 GitLab MR target_branch 非 master）。
- `CodeChangeArchive` 现有字段：`commit_sha`/`base_branch`/`mr_url`/`mr_id`。决策：MR ingest 路径 `commit_sha` = `merge_commit_sha`、`base_branch` = MR `target_branch`（语义对齐 target_branch）；若需独立保真，可加 `merge_commit_sha`/`target_branch` 字段（Claude's Discretion，能用既有 commit_sha/base_branch 表达则不新增）。
- `MODIFIES_CHUNK` 边的 **`valid_at` 锚定到该 commit 的业务时间**（merge commit 时间 / event_time），表达"这条 diff→chunk 关联在该 commit 当年成立"。冻结后 diff 原文（已 zlib 压缩存 `CodeChangeArchive`）不变——快照即 commit 锚定的归档行。
- 修正 Phase 32 遗留（WR-02）：一键摄取 MR diff 步若用了合成 `commit_sha`，本 phase 让其改用真实 `merge_commit_sha`（commit 锚定后陈旧 diff 由对账失效，不再静默沿用）。

### bi-temporal 失效对账（Grey Area 2，HDIFF-02）
- 复用既有 `KnowledgeEdge` 的 bi-temporal 字段 `valid_at`/`invalid_at`（已存在 + 约束 `invalid_at__gt valid_at`）——**不新建时间模型**。
- 重索引对账：当目标分支演进、文件在更新 commit 被重索引导致 chunk 版本变化时，对账把指向**已过期 chunk 版本**的 `MODIFIES_CHUNK` 边 `invalid_at` 置位（业务时间线失效，**不删除**——保留历史可追溯，对齐 knowledge "invalid_at 置位不删" 范式）。
- 对账触发点：挂在既有重索引/对账路径（reindex / 文件重索引完成后），best-effort，失败 warning 不阻断索引（沿用既有降级范式）。
- 失效判定：边的目标 chunk（`target_chunk_id` 弱引用）在当前索引中已不存在/已被新版本取代 → 该边对当前视图过期 → 置 invalid_at（= 重索引/对账时刻或新 commit 业务时间）。

### as-of 查询（Grey Area 3，HDIFF-02 成功标准 3）
- 提供 as-of 查询 helper/谓词：给定 `as_of` 时间，筛选 `valid_at <= as_of AND (invalid_at IS NULL OR as_of < invalid_at)` 的 `MODIFIES_CHUNK` 边——历史 as-of 看到"当年成立"的边，当前视图（as_of=now / invalid_at IS NULL）只看未失效的边。
- 当前视图默认排除已 `invalid_at` 的边（历史边不污染当前关联）；历史回溯按显式 as_of 取当年快照。
- 暴露面：knowledge 内部查询 helper + 既有图查询/检索面按需接入（最小，不新建对外检索 UI；as-of 作为查询参数/默认 now）。

### 范围守护（Grey Area 4）
- 本 phase 聚焦 `MODIFIES_CHUNK` 边的 commit 锚定 + 时效失效 + as-of；不改 delivery 脊柱、不改前端、不新建检索 UI。
- 不做全量历史回填重算（除非既有重索引天然覆盖）——对账作用于"重索引发生时"的增量失效。

### 异步 / 测试（Claude's Discretion 范围内）
- async-first；ORM `sync_to_async`；对账挂既有 reindex 后台路径。
- 测试：pytest-django + factory-boy + pytest-socket（diff 归档既有测试范式，参考 tests/knowledge/test_modifies_chunk.py / test_diff_archive.py）。守护：① MR diff 锚定 merge_commit_sha + target_branch（非 master），valid_at 锚定 commit 时间（HDIFF-01）；② chunk 变更后重索引对账把过期 MODIFIES_CHUNK 边置 invalid_at（不删，HDIFF-02）；③ as-of 查询：历史 as_of 见旧边、当前视图只见未失效边；④ 对账失败降级不阻断索引；⑤ 时间次序约束（invalid_at > valid_at）。

### Claude's Discretion
- 是否给 CodeChangeArchive 加 merge_commit_sha/target_branch 显式字段 vs 复用 commit_sha/base_branch、对账挂载的确切 reindex 钩子、as-of helper 的放置（selector vs graph query）、当前视图默认过滤的实现层 —— 由实现按既有约定决定。
- 失效判定的精确"chunk 过期"信号来源（ChunkRegistry 行号回填 / chunk 版本 / 重索引 diff）—— 取既有重索引能可靠提供者。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/knowledge/models.py KnowledgeEdge`：已有 bi-temporal `valid_at`/`invalid_at` + 约束（`invalid_at__gt valid_at`、`invalid_at IS NULL` 当前视图索引）——直接复用，不新建时间模型。
- `server/knowledge/models.py CodeChangeArchive`：`commit_sha`/`branch_name`/`base_branch`/`mr_url`/`mr_id`/`event_time` + 幂等锚 `(source_kind, source_id, commit_sha)`。
- `server/knowledge/diff_archive.py`：`build_modifies_chunk_edge_spec`（MODIFIES_CHUNK EdgeSpec）、`resolve_modified_chunks`（ENH-01 符号对齐阶梯）、`archive_code_change`（DiffArchiver 编排）、`apply_edge_specs`（边写入收口，设 valid_at）。
- `EdgeRelation.MODIFIES_CHUNK`（枚举已定义）；`target_chunk_id` 弱引用字段。
- 既有重索引 / 对账路径（indexer / ChunkRegistry 行号回填，v0.5 已交付）—— 对账挂载点。
- 既有测试 `tests/knowledge/test_modifies_chunk.py` / `test_diff_archive.py` / `test_vector_recall.py` —— 范式参考。

### Established Patterns
- knowledge bi-temporal：`invalid_at` 置位不删（保留历史可追溯）；`valid_at`/`invalid_at` 业务时间线 vs `created_at`/`expired_at` 系统时间线。
- 边只产 EdgeSpec，写入经 `apply_edge_specs` 单一收口（幂等可重入）。
- 重索引 best-effort 降级 + warning，不阻断 success（v0.5 范式）。
- ruff line 100；中文 docstring；structlog；async + sync_to_async。

### Integration Points
- `server/knowledge/diff_archive.py`（commit 锚定 + 对账失效）；`server/knowledge/models.py`（如需加字段 + migration）。
- 既有 reindex / 索引完成钩子（对账触发）。
- as-of 查询 helper（knowledge 查询面）。
- 修 Phase 32 一键摄取 MR diff 的合成 commit_sha（WR-02 deferred-to-33）。
</code_context>

<specifics>
## Specific Ideas

- PF-08：`CodeChangeArchive` 无 bi-temporal invalid_at（指 MODIFIES_CHUNK 边的失效未落地），master 演进后旧边不失效 → 本 phase 落地失效对账 + as-of。
- DOMAIN §1.5 实测：GitLab MR `target_branch` 非 master + 有 `merge_commit_sha` → 冻结锚定用 target_branch + merge_commit_sha，不假设 master。
- 失效 = `invalid_at` 置位不删（保留历史）；as-of 查询 `valid_at <= as_of < invalid_at`。
- 衔接 Phase 32 WR-02：一键摄取 MR diff 合成 commit_sha → 改真实 merge_commit_sha（commit 锚定）。
</specifics>

<deferred>
## Deferred Ideas

- 全量历史 diff 回填重算 —— 非本 phase（对账作用于重索引增量失效）。
- 对外 as-of 时间旅行检索 UI —— 非本 phase（仅内部查询 helper + 既有检索按需接入）。
- 评论入图 / 片段→需求反查 —— Phase 34。
- 真实大 MR / 真实 master 演进的端到端人工验收 —— human-UAT（需真实 GitLab）。
</deferred>

---

*Phase: 33-hist-diff-bitemporal*
*Context gathered: 2026-06-15 via smart discuss (autonomous)*
