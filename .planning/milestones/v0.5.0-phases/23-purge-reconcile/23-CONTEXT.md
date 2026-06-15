# Phase 23: 清理对账（普通/敏感两模式） - Context

**Gathered:** 2026-06-14
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous, auto-accepted recommendations)

<domain>
## Phase Boundary

本阶段在 Phase 22（排除配置单一源 + 读取面 fail-closed）之上，提供**存量派生数据的清理与对账**，区分**普通排除清理**与**敏感清理**两种模式（DOMAIN §9.2），并提供对账 UI（EXCL-06）。同时收口前置修复 PF-03（统一 `purge_file`）、PF-05（overlay 删除）。

本阶段做：
- 统一 `purge_file(repo_id, path)` 抽象（PF-03）：覆盖 Qdrant 主 + overlay（PF-05）、FileIndex、ChunkRegistry/ChunkEdge、codegraph（Symbol/Edge/Endpoint）、repo_summaries/index_nodes。三条索引删除路径与排除清理共用此入口。
- **普通排除清理**：删净派生索引面（§9.3 普通列），删后无残留。
- **敏感清理**：在普通基础上额外清理操作记录数据面（message parts、agent trace/ActionLog、TaskResult、CodeChangeArchive diff、knowledge content、prompt snapshot、错误日志可控范围）。
- **对账（EXCL-06）**：对比"当前排除规则 vs 已索引内容"，列出差异（已索引但现命中排除的文件），提示并支持一键清理。
- 清理操作审计埋点（结构化事件，可控范围）。

本阶段**不做**：
- 排除配置/读取面过滤本身（Phase 22 已完成）。
- AI 敏感文件识别建议名单（Phase 24）。
- git object 物理抹除（Out of Scope；§9.1 安全边界——靠工具层 denylist + 重建/重克隆兜底，不承诺物理消失）。
- 备份层强保证（基础设施层，文档化 caveat）。

</domain>

<decisions>
## Implementation Decisions

### D-01 统一 `purge_file` 抽象（PF-03 + PF-05）
- 新增/抽出 `purge_file(repository_id, rel_path, *, mode)`（service 层，如 `services/purge.py` 或并入 indexer），单一删除入口：
  - Qdrant 主 collection（复用 `delete_by_file_path`）**+ overlay collections**（PF-05：遍历该 repo 的 branch overlay collections 逐一删 file_path 命中 point）。
  - FileIndex 行、ChunkRegistry/ChunkEdge（含 pre_delete 清边）。
  - codegraph（复用 `adelete_for_files`）。
- PF-03：`run_incremental_index` 的删除路径改调 `purge_file`，与 git_diff 路径、排除清理三者共用，消除"只删 Qdrant 不删 FileIndex/ChunkRegistry"的孤儿残留。
- 幂等：重复 purge 同一文件不报错、无副作用。

### D-02 两模式（不混一个按钮，§9.2）
- **普通排除清理**（`mode=normal`）：仅派生索引面——Qdrant 主+overlay、ChunkRegistry/ChunkEdge、codegraph、repo_summaries/index_nodes。
- **敏感清理**（`mode=sensitive`）：普通 **+** 操作记录可控清理——message parts、ActionLog/agent trace、TaskResult、CodeChangeArchive diff（file 级 scrub）、knowledge content、prompt snapshot、错误日志可控范围。
- 两模式在 service 与 API、UI 上**显式区分**（不同入口/确认），敏感清理需更强确认（措辞提示不可逆 + 不承诺 git/备份物理消失）。
- 敏感清理对"可能含正文"的数据面尽力而为；对应用层不强保证的面（备份）只文档化 caveat，不假装清除。

### D-03 对账（EXCL-06）
- 对账计算：枚举已索引内容（FileIndex / ChunkRegistry 的 file_path 集合）∩ 当前生效排除规则（复用 Phase 22 `build_matcher_for_repo`/`is_excluded`）→ 得出"已索引但现应排除"的差异清单。
- API 暴露对账结果（按 repo），含命中文件数/列表与建议模式。
- UI：在仓库设置/排除规则面板旁展示差异提示，支持"一键清理（普通）"与显式"敏感清理"入口；清理进度/结果回显。

### D-04 安全边界与审计
- 措辞如实（§9.1）：清理承诺"Friday 派生数据/检索/工具不可见"，**不承诺** git object 或备份物理消失。
- 清理操作埋审计点（结构化事件：purge.started/completed、mode、repo、命中数），供后续审计里程碑复用。
- 敏感清理走异步/后台执行（数据面多、可能耗时），复用既有 `background_runner`/任务机制；进度可查询。

### Claude's Discretion
- `purge_file` 落点（新建 `services/purge.py` vs 并入 `indexer.py`）、API 路由命名、对账查询的精确实现（DB 聚合 vs 遍历）、前端组件落点与异步进度展示形式，由 planner/executor 依据既有约定决定。
- 操作记录数据面（ActionLog/TaskResult/CodeChangeArchive/message parts/prompt snapshot）的精确模型与 file 级关联方式，由 planner 研究既有模型后确定；无法精确按 file 关联的面采用 repo 级可控清理 + 文档化范围。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets（待 planner 核实精确路径）
- `server/services/qdrant_service.py` — `delete_by_file_path`（主 collection，需扩 overlay）。
- `server/services/indexer.py` — `run_incremental_index` 删除路径（PF-03 改调 purge_file）、`run_full_index`、overlay/branch 索引。
- ChunkRegistry/ChunkEdge 模型与 pre_delete 清边逻辑。
- codegraph `adelete_for_files`。
- 操作记录模型：`CodeChangeArchive`（diff_archive）、TaskResult、ActionLog/trace、chat message parts、prompt snapshot（位置待 planner 研究 `server/knowledge/`、`server/chat/`、`server/agents/`、`server/subagent/`）。
- Phase 22：`services/exclusion.py` `build_matcher_for_repo`/`is_excluded`（对账复用）；`RepoExclusionRule`。
- `server/services/background_runner.py` — 异步后台执行。

### Established Patterns
- service 层无状态域逻辑；异步 ORM 经 `sync_to_async`；Django app 各拥 models/api/urls。
- 前端 `web/src/api/` 类型化 client + Pinia/TanStack Query + reka-ui + vue-i18n（默认中文）。

### Integration Points
- 对账 + 清理 API 注册进既有 `/api/repositories/<id>/...`。
- 前端清理/对账入口挂在 Phase 22 的排除规则面板（`ExclusionRulesPanel.vue`）旁。
</code_context>

<specifics>
## Specific Ideas

- 清理需"删后无残留"守护测试：对一个已索引文件执行 purge_file，断言 Qdrant 主+overlay、FileIndex、ChunkRegistry、codegraph 四面均无该 file_path 残留。
- 敏感清理守护测试：断言额外覆盖的操作记录面（至少 CodeChangeArchive diff、TaskResult、trace）被清。
- 对账守护测试：构造"已索引但新增排除规则命中"的文件，断言对账差异列出该文件，一键清理后对账归零。
- 敏感清理 UI 强确认 + 不可逆/不承诺物理消失措辞。
</specifics>

<deferred>
## Deferred Ideas

- git object 物理抹除 / filter-repo 强清 → backlog（Out of Scope）。
- 全量操作审计 → v0.10（本阶段仅埋清理操作审计点）。
- AI 敏感文件识别建议名单 → Phase 24。
</deferred>

---
*Phase: 23-purge-reconcile*
*Context gathered: 2026-06-14 via smart discuss (autonomous)*
