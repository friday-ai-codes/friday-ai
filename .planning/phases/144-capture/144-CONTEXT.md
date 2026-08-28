# Phase 144: 仓库召回与 Capture 回放 - Context

**Gathered:** 2026-08-28
**Status:** Ready for planning

<domain>
## Phase Boundary

让授权用户以仓库为第一作用域检索已入图的 `session_capture` 精华，可选用项目进一步收窄，并按 Capture id 只读回放独立账本中的原始结构化问答；同时修复默认分支的错误项目推断并补齐 MCP/Chat 两条召回链的 best-effort RetrievalTrace。本阶段不做价值评估、宿主采集或大型前端工作台。

</domain>

<decisions>
## Implementation Decisions

### 仓库优先的召回契约
- 会话知识检索必须以 `repository_id` 为必选主作用域；`project_id` 仅为可选的交集过滤条件，不能替代仓库或扩大仓库授权范围。
- 检索只返回 Phase 143 已入图、`EntityKind.DOCUMENT` 且 `source_kind="session_capture"` 的中高价值精华；原始 Capture 问答与 low 样本不进入向量召回。
- 在 `DeliveryKnowledgeSearchService`/底层 recall 增加显式 `source_kinds` 闭集过滤能力，调用点必须传 `["session_capture"]`；不能依靠 document kind 或标题约定间接识别。
- `pack_project_context` 与交付知识检索的允许源白名单显式加入 `session_capture`，并继续沿用现有 `resolve_allowed_repository_ids`/`resolve_allowed_project_ids` 权限收口；项目过滤只收窄，不放宽。

### Capture id 原文回放
- 提供按 Capture UUID 的只读回放入口，返回 `capture_id`、结构化 `question`/`answer`、模型/会话/分支元数据、仓库/项目挂钩、tier/status/reason 与时间戳；不返回隐藏 CoT、凭证或内部重试错误细节。
- 回放响应明确省略 `client`：`SessionCapture` 未持久化该字段，禁止为补齐客户端元数据读取 Interaction Ledger / `ToolCallRecord.input`，也不返回猜测值或恒 `null`。
- 回放正文唯一来源是 `initiatives.SessionCapture`；禁止查询、扫描或拼接 Interaction Ledger / ToolCallRecord / RetrievalTrace payload 作为正文。
- 权限 fail-closed：创建者本人可读；若 Capture 挂仓库/项目，还必须满足当前仓库可见性与项目访问约束，未授权与不存在统一返回不泄漏存在性的 404。
- 回放入口保持纯只读、无状态推进、无重新评估或入图副作用；大前端页面不是验收前提，薄 MCP/REST read endpoint 与测试足够完成本 Phase。

### 默认分支项目匹配防错
- `main`、`master`、`develop` 以及仓库配置的 `default_branch` 属于默认分支；在没有显式 `ProjectBranch` 或可解析 work item 的情况下，不得仅凭唯一 `RepoAssociation` 返回 `matched=true`。
- `LookupProjectByBranchView` 第三源在默认分支上跳过项目注入，可返回候选及明确 `binding_source`/reason 供人工确认；不得把候选上下文打包进响应。
- 显式 `ProjectBranch` 绑定与 `feat/...-m{id}-...` 工作项命名继续优先并可在默认分支上命中；修复只禁止“默认分支 + 仓关联”作为唯一证据，不破坏前两源。
- Capture 写路径继续以仓库挂钩为主，不能因 lookup 不唯一而拒收、清空仓库 FK 或退化为 `branch_unresolved`；读写解析边界需由回归测试同时锁定。

### 召回观测与双链一致性
- MCP 会话知识检索使用 `McpToolView._record(..., traces=...)` 写 RetrievalTrace；Chat 工具复用 `_record_chat_retrieval`，两链都记录 source、repository/project 过滤维度、result_count、scores/top_score、duration_ms 与 `source_kind`。
- RetrievalTrace payload 只含标量、计数、分数和标识，不含 query、精华正文、原始问答或 Ledger body；统一由现有 ledger 脱敏入口再防护。
- Trace 写入始终 best-effort；记录失败不得改变检索结果、HTTP 状态或对话 ToolResult，空结果也应保留计数为零的可观测事件。
- MCP 与 Chat 必须委托同一 `DeliveryKnowledgeSearchService` 和同一 `session_capture` 白名单/权限策略；测试需证明两链过滤和失败降级一致，禁止各写一套查询。

### the agent's Discretion
- 回放入口最终命名、采用 MCP read tool 还是薄 REST detail view、serializer 内部拆分由实现者决定；必须保证按 Capture id、只读、404 防枚举与不读 Ledger。
- `source_kinds` 过滤落在 service 还是 vector recall 层由实现者按现有 Qdrant payload 决定，但必须是显式参数且对其他调用点默认零回归。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/knowledge/retrieval.py::DeliveryKnowledgeSearchService.search_similar` 已接受 `repository_ids`、`project_ids`、`entity_kinds`，并通过 `resolve_allowed_*` 做权限收口；可在此扩展显式 `source_kinds`。
- `server/mcp_tools/views.py::SearchDeliveryKnowledgeView` 已把 repository/project 过滤传给统一 service，`McpToolView._record` 会把 traces 持久化为 RetrievalTrace。
- `server/agents/tools/knowledge_read_tools.py::_record_chat_retrieval` 已实现 Chat 链 `conversation_id` 关联与 best-effort 留痕；`search_project_context` 是同一 service 的薄封装范式。
- `server/initiatives/models/session_capture.py::SessionCapture` 是原文账本真源，已具创建者、仓库、项目、问题、答案、模型、会话、分支、状态与挂钩原因字段。

### Established Patterns
- `server/mcp_tools/views.py::LookupProjectByBranchView` 已按 work item、显式 `ProjectBranch`、`RepoAssociation` 三源合并，并在单命中时调用 `pack_project_context`；第三源是本阶段的精确修复点。
- `server/tests/mcp_tools/test_lookup_project_by_branch.py` 锁定 lookup 多源语义，适合新增默认分支 + 唯一 association 不匹配用例与显式绑定零回归用例。
- `server/tests/mcp_tools/test_retrieval_trace.py` 已验证 trace payload 自动脱敏与写入失败 best-effort；`knowledge.exposure.serialize_search_results` 是 MCP/Chat 共享 DTO 出口。

### Integration Points
- `server/knowledge/vector_recall.py`/`knowledge.retrieval.py` 增加 `source_kinds=["session_capture"]` 过滤，并由 `SearchDeliveryKnowledgeView`、Chat 知识工具与 `services/project_context_packer.py` 显式消费。
- 在 `server/mcp_tools/views.py::LookupProjectByBranchView` 第三源调用前判断默认分支，保留 work_item/project binding 两源优先级。
- 新增 Capture detail serializer 与只读 MCP/REST 路由，查询只从 `initiatives.SessionCapture` 出发并复用 knowledge access scope。
- MCP 与 Chat 的 session-capture 检索调用点分别组装同口径 RetrievalTrace，不把正文或 query 放入 payload。

</code_context>

<specifics>
## Specific Ideas

- “按项目检索”是 `repository_id AND project_id`，不是 `project_id OR repository_id`；仓库始终是会话知识的主挂钩。
- 回放展示的是 Capture 表中已脱敏的原始结构化问答；Ledger 即使已有同次 MCP input，也绝不能作为正文兜底。
- `main`/`master`/`develop` 上唯一关联项目只能成为候选，不能自动注入；显式分支绑定仍是可审计的人工授权证据。

</specifics>

<deferred>
## Deferred Ideas

- Vue Capture 回放工作台、价值档位人工纠偏和批量评测界面留后续版本。
- SessionStart 自动注入近期高价值摘要与跨 Capture 聚合排序留后续版本。
- Cursor / Claude Code 自动采集与 hooks 安装延后到 Phase 145。
- 仓库 ACL 的平台级历史欠债不在本阶段重构；本阶段不得比现有代码/知识检索权限更松。

</deferred>
