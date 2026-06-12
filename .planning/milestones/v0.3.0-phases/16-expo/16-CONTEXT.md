# Phase 16: 多入口暴露与前端时间线 - Context

**Gathered:** 2026-06-12
**Status:** Ready for planning
**Mode:** Smart discuss — autonomous auto-accept

<domain>
## Phase Boundary

同一知识检索 service 经四个程序化入口 + 前端只读页全部可达，方案生成自动消费历史形成飞轮，每个入口 fail-closed。

本阶段交付（EXPO-01..04, ENH-03, ENH-04）：
- MCP HTTP 工具：`search_delivery_knowledge` / `get_entity_timeline` / `get_related_entities`（PAT 认证 + interactions 审计）
- workflow 检索节点：方案生成前自动检索相似历史并注入上下文；`ai_plan_generation` 消费历史
- chat agent tools + npm Friday skill 暴露同一 `DeliveryKnowledgeSearchService`
- 前端只读实体详情页 + 关联时间线（列表/树形态）
- as-of 历史时点查询作为工具参数（ENH-04）

不在本阶段：新摄取触发点、检索算法变更（Phase 15 已交付）。

</domain>

<decisions>
## Implementation Decisions

### MCP 入口（EXPO-01）
- 三个新 endpoint 挂入 `server/mcp_tools/views.py` + `urls.py`，复用 `McpToolView` / PAT `AccessTokenAuthentication` + `begin_interaction_run` 审计链
- 请求/响应 serializer 对齐 Phase 15 DTO；越权测试：A 用户 PAT 查 B 项目 → 空结果
- 工具名与 OpenAPI schema 与既有 19 工具同体系注册

### Workflow 节点（EXPO-02）
- 新增 `delivery_knowledge_search` 控制/AI 类节点（或扩展现有 `ai_plan_generation` 前置 hook）：调用 `DeliveryKnowledgeSearchService.search_similar`，将 top-K 摘要注入 plan generation prompt
- 节点配置：top_k、project scope、可选 as_of；失败降级为空上下文不阻塞工作流

### Chat tools + npm skill（EXPO-03）
- `agents/tools/` 新增 delivery knowledge tools（search / timeline / related），会话 owner 作为 user principal
- `skills/skills/` 新增或扩展 `friday-knowledge` skill，HTTP fallback 文档对齐 `friday-code` 模式
- 工具描述中文，返回带 provenance metadata

### 前端只读页（ENH-03）
- 新路由 `/knowledge/entities/:id`（或 `/delivery-knowledge/:id`）：只读详情 + 版本历史 + 关联时间线
- 列表/树形态展示 需求→方案→代码变更；复用 reka-ui + Tailwind 4 + vue-i18n
- TanStack Query 调 Phase 15 REST API（`server/knowledge/api/`）；无编辑能力

### as-of 参数（ENH-04）
- 所有四入口透传 `as_of` ISO8601 可选参数到 service 层（Phase 15 已实现）
- 前端详情页提供「历史时点」日期选择器（可选，默认当前）

### Claude's Discretion
- 节点注册 JSON、前端组件拆分、skill 目录命名由 planner 按既有范式决定
- UI 视觉遵循项目 Tailwind/reka-ui 惯例，不引入新设计系统

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/knowledge/retrieval.py`：`DeliveryKnowledgeSearchService`（search_similar / get_timeline / get_related）
- `server/knowledge/api/views.py`：内部 REST 测试面（JWT）
- `server/mcp_tools/views.py`：MCP 工具范式（PAT + interactions 审计）
- `server/workflows/nodes/ai/plan_generation.py`：`ai_plan_generation` 挂点
- `server/agents/tools/`：chat tools 注册模式
- `skills/skills/friday-code/`：npm skill HTTP fallback 范式
- `web/src/pages/`：路由驱动页面；`web/src/api/` barrel export

### Established Patterns
- MCP：serializer → service → ledger 审计；fail-closed 认证
- Workflow 节点：BaseNode 子类 + node-definitions.json UI schema
- 前端：Pinia + vue-query + i18n 中文默认

### Integration Points
- `friday/urls.py` 注册 knowledge API（若尚未对外）
- `web/src/router` 新页面 + 导航入口（侧边栏「交付知识」或嵌入实体链接）

</code_context>

<specifics>
## Specific Ideas

- 方案生成飞轮：检索结果格式化为 markdown 段落注入 `ai_plan_generation` system/context
- 越权用例必须进 CI（mcp_tools test 套件扩展）

</specifics>

<deferred>
## Deferred Ideas

None — final phase of v0.3.0 milestone.

</deferred>
