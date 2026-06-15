# Phase 25: Commit 历史索引 + 行号反查 - Context

**Gathered:** 2026-06-14
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous, auto-accepted recommendations)

<domain>
## Phase Boundary

本阶段补齐两块索引地基：
1. **commit 历史可语义检索**（IDX-01）：把 commit message / author / 变更摘要索引为可被 RAG 召回的内容。
2. **行级反查打底**（IDX-02）：索引时回填 `ChunkRegistry.line_start/line_end`，并提供 `file:line → chunk_id` 查询能力。

本阶段做：
- commit 历史摄取：遍历 git 历史，按 commit 产出 RAG 文档（message + author + 变更文件摘要），embedding 入库，经既有 `search_rag` 可检索；增量感知（只索引新 commit，不每次全量重扫）。
- `ChunkRegistry.line_start/line_end` 回填：索引/分块时写入每个 chunk 的起止行（tree-sitter 已有 span 信息）；必要时加字段 migration。
- `file:line → chunk_id` 查询 API（service + REST）：给定 repo + 文件 + 行号，返回覆盖该行的 chunk_id。
- 复用 Phase 22 排除规则：被排除文件的 diff/内容不进 commit 索引（fail-closed 一致）。

本阶段**不做**：
- 片段 → 需求反查（依赖 IDX-02，留 v0.6）。
- commit 中密钥扫描（关联 Phase 24 / backlog）。
- 多仓检索参数（Phase 26）。
- git object 物理操作。

</domain>

<decisions>
## Implementation Decisions

### D-01 commit 历史索引（IDX-01）
- 摄取单元 = 单个 commit：文档内容 = `message` + `author`(name/email) + `committed_at` + 变更文件路径摘要（不含被排除文件；大 diff 截断，复用既有截断 helper）。
- 存储：embedding 入 Qdrant，作为可检索内容；用 payload 字段标识类型（如 `kind=commit`）与 commit 元数据（sha/author/date/repo），使其与代码 chunk 在同一检索面但可区分/过滤。
- 检索：经既有 `search_rag` chokepoint 召回（与代码 chunk 统一入口），commit 文档同样受 Phase 22 排除/fail-closed 约束。
- 增量：记录"已索引到的 commit sha/边界"，后续只索引新增 commit（不每次全量）；首轮可限定 bounded 范围（最近 N 或全history，由 planner 依性能权衡，默认增量+上限）。

### D-02 行号回填（IDX-02）
- 在分块（chunking）阶段写入每个 chunk 的 `line_start`/`line_end`（tree-sitter 节点已带行 span；非 AST 切分按字符→行换算）。
- `ChunkRegistry` 若无 `line_start/line_end` 字段则加 migration（仅加字段，nullable，新索引回填；存量旧 chunk 留待重索引补全，不强制回填历史）。
- 行号语义：1-based、闭区间 [line_start, line_end]，覆盖该 chunk 对应源码行范围。

### D-03 file:line → chunk_id 查询（IDX-02）
- service：`find_chunk_at(repository_id, file_path, line) -> chunk_id(s)`，按 `repo + file_path + line_start<=line<=line_end` 命中（可能多 chunk 覆盖，返回列表或最具体一个）。
- REST API：`GET /api/repositories/<id>/chunk-at/?path=...&line=...` 返回 chunk_id 及其 line 范围（被排除文件 fail-closed 不返回，复用 Phase 22 matcher）。
- 这是"片段↔位置"反查的地基（下游 v0.6 片段→需求反查复用）。

### D-04 范围与兼容
- 不破坏既有 chunk/索引结构；行号字段 nullable 向后兼容；commit 索引为新增数据面，不影响既有代码检索。
- commit 索引与行号回填都接入既有索引流程（full/incremental），增量感知避免重复成本。
- 被排除文件全程 fail-closed（commit 变更摘要、chunk-at 查询均不暴露被排除文件）。

### Claude's Discretion
- commit 文档的精确 payload schema、是否单独 collection vs 主 collection 加 kind 标记、增量边界记录落点（FileIndex 旁 vs 新表/设置）、首轮 commit 索引的范围上限默认值，由 planner 研究既有 Qdrant/indexer 结构后定。
- `find_chunk_at` 多 chunk 命中时的返回策略（全部 vs 最小覆盖）、REST 路由命名，由 planner/executor 定。
- 行号回填对所有切分路径（tree-sitter / fallback）的精确实现细节由 executor 依既有 code_parser/chunker 决定。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets（待 planner 核实）
- `server/services/indexer.py` — full/incremental 索引流程（commit 索引 + 行号回填挂接点）。
- `ChunkRegistry` 模型（`line_start`/`line_end` 字段现状待核实——ROADMAP 称需"回填"，可能字段已存在或需加）。
- `server/services/code_parser.py` / chunker — tree-sitter 分块，节点带行 span（行号来源）。
- `server/services/qdrant_service.py` — embedding 入库 + payload schema（commit 文档复用）；`search_rag`/HybridSearchService 检索入口。
- git 历史读取：`gitpython` / 既有 mirror（`services/repo_mirror.py`）读 commit log。
- Phase 22 `services/exclusion.py` `build_matcher_for_repo`/`is_excluded`（commit 变更摘要 + chunk-at fail-closed 复用）。
- 既有 diff 截断 helper（commit 变更摘要截断复用）。

### Established Patterns
- service 层无状态域逻辑；异步 ORM 经 `sync_to_async`；payload schema 索引字段第一天定型（commit kind 字段需进既有 schema 或独立 collection）。
- 前端 `web/src/api/` 类型化 client（若需 chunk-at/commit 检索 UI，本阶段可仅后端 + API，UI 最小或留后续）。

### Integration Points
- commit 索引 + 行号回填接入 `run_full_index`/`run_incremental_index`。
- chunk-at + commit 检索 API 注册进 `/api/repositories/<id>/...`。
- 检索复用 `search_rag` chokepoint（commit 文档同受排除约束）。
</code_context>

<specifics>
## Specific Ideas

- IDX-01 守护测试：建若干 commit（含特定 message/author），索引后经 search_rag 用关键字/author 召回到对应 commit 文档；被排除文件的变更不出现在 commit 摘要。
- IDX-02 守护测试：索引一个多函数文件，断言各 chunk 的 line_start/line_end 正确；`find_chunk_at(file, line)` 命中覆盖该行的 chunk_id；被排除文件 chunk-at fail-closed 不返回。
- 增量守护：二次索引只新增新 commit，不重复既有。
</specifics>

<deferred>
## Deferred Ideas

- 片段 → 需求反查（依赖本阶段 IDX-02 行号地基）→ v0.6。
- commit 中密钥扫描 → Phase 24 关联 / backlog。
- 多仓/全仓检索参数 → Phase 26。
- commit 历史检索的前端 UI（可留后续，本阶段后端 + API 为主）。
</deferred>

---
*Phase: 25-commit-index-lineref*
*Context gathered: 2026-06-14 via smart discuss (autonomous)*
