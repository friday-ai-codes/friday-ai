# Phase 85: 项目上下文可读 + 分支绑定 - Context

**Gathered:** 2026-06-26
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous) — 用户逐 Wave 选定

<domain>
## Phase Boundary

让项目全部上下文可被任意来源 RAG/grep/file-read（前端 AI 对话 / MCP / skills），项目（5 文件/记忆/工件）沉淀进交付知识图谱可索引 + 关联扩充；建立分支↔项目多绑定（`ProjectBranch`）+ 分支名反查项目。

交付需求：CTX-01/02, BIND-01/02。
</domain>

<decisions>
## Implementation Decisions

### 上下文物化存储
- **独立「项目上下文」collection**：项目 5 文件/记忆/工件物化进**专属 collection**（与代码 RAG collection 分离），scope/visibility 隔离（随项目 visibility 决定可召回范围）。
- 不复用代码 RAG collection 作虚拟仓库（避免与排除规则/仓库权限口径串味）。

### 物化/索引触发
- **写时增量物化 + 兜底定时全量重建**：5 文件/记忆变更时增量更新向量；定时（或归档/手动）全量重建兜底防漂移。
- 写时增量经 durable 任务，带 `initiated_by_user_id`；失败 fail-soft 不阻断业务。

### 知识图谱沉淀（CTX-02）
- 项目（5 文件/记忆/工件）沉淀进交付知识图谱（复用 `KnowledgeEntity`/`KnowledgeEdge`），可索引 + 关联扩充。
- 全局+RAG 搜索能定位上下文所属仓库/项目。
- 新增召回写 `RetrievalTrace` + 条数/分层耗时/score（MCP + AI 对话两条链都覆盖）。

### 分支绑定（BIND-01/02）
- 新增 `ProjectBranch`（project FK + repository FK + branch_name + source(manual/plan/coding) + 时间戳，唯一(project,repository,branch_name)）——一项目多分支、前端可绑。
- 分支↔看板结合。
- 扩展 `lookup_project_by_branch` 支持显式多绑定，多/无命中 fail-soft 返回候选列表，不抛、不阻断编码。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/services/` context packer（grep+RAG+token 预算+fail-closed+RetrievalTrace）：召回基础设施复用。
- `server/knowledge/`（Entity/Edge/ingestion/sources）：知识图谱沉淀 + KLINK 关联。
- `server/mcp_tools/`：`lookup_project_by_branch`/`report_project_knowledge` MCP 工具（本期扩多分支）。
- `server/initiatives/models`（Phase 82/83 产出）：5 文件/记忆/工件作物化源。
- `qdrant-client` + `fastembed` + `llama-index`：独立 collection 创建。

### Established Patterns
- RAG 单一 chokepoint（search_rag）每 repo/scope fail-closed 过滤。
- 知识实体 uuid5(ns, source) 确定性 ID；append-only 边 + as_of 视图。
- 召回写 RetrievalTrace、新增召回点埋分层耗时/score。

### Integration Points
- Phase 84 前端 RAG 搜索 → 本 phase 项目上下文召回端点。
- Phase 86 IDE hooks 读路径 → MCP `lookup_project_by_branch`（多分支扩展）。

</code_context>

<specifics>
## Specific Ideas

- 明确独立 collection（非复用代码 collection），隔离 scope/visibility，避免权限口径串味。

</specifics>

<deferred>
## Deferred Ideas

- 结构化记忆 + 时效降权 + 矛盾消解（PROJX-02，v2）。

</deferred>

<canonical_refs>
## Canonical References

- `.planning/project-workspace/MILESTONE-PROPOSAL.md` — §6 数据模型（ProjectBranch）、§7 IDE 闭环（读路径）、§12 观测强制项
- `.planning/REQUIREMENTS.md` — CTX-01/02, BIND-01/02
- `.planning/ROADMAP.md` — Phase 85 Success Criteria
- `.cursor/rules/observability-logging.mdc` — RetrievalTrace/召回埋点强制项

</canonical_refs>
