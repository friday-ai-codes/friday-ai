# Phase 102: 知识消费面与对外契约（编排召回扩容 + Chat 工具 + snapshot/skills 对齐） - Context

**Gathered:** 2026-07-15
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous — 推荐值自动采纳）

<domain>
## Phase Boundary

统一知识库的消费面补齐：方案编排召回覆盖项目沉淀与历史经验（`document` + `learning_case`）；Chat 对话经白名单三个薄封装工具主动读知识；IDE 上报的 `ProjectStateApi` 可语义检索；对外工具契约（`TOOL_SCHEMA_SNAPSHOT` + `@friday-ai-codes/skills` 文档）与新行为完整对齐。需求：KNOW-04 / KNOW-05 / KNOW-06 / UNIFY-04。依赖 Phase 100（learning_case kind 已存在、检索已切向量版）。

</domain>

<decisions>
## Implementation Decisions

### KNOW-04 编排召回扩容
- `services/process_runtime/recall_adapter.py` 的 `RECALL_ENTITY_KINDS` 改为可配置：Django settings（env 可覆盖，如 `PROCESS_RECALL_ENTITY_KINDS`）读取，默认 `[work_item, tech_plan, code_change, document, learning_case]`（新 kinds 默认开）。
- **每 kind 限额守 token 预算**：按 kind 分组查询（或单查后按 kind 截断，planner 按 search_similar 成本定），每 kind 上限可配置（默认如 work_item/tech_plan/code_change 各 4、document/learning_case 各 3），合并后统一排序输出。
- `document` kind 召回需传 `include_document_kind=True`（vector_recall 既有 flag）。
- 召回埋点先行：adapter 内写 `RetrievalTrace`（kind=CHUNK，payload 含 query/kinds/条数/`duration_ms`/scores/top_score，对齐 `search_project_context` 的 trace 形态 views.py L3373–3384）+ 结构化事件（`category=sampling`、`component`）；best-effort 吞异常。
- 更新 `tests/services/test_recall_adapter.py` 既有断言（L155–156 锁死旧集合的用例改为断言新默认集合 + 可配置行为 + 限额行为）。

### KNOW-05 Chat 三个知识读工具
- 新模块 `server/agents/tools/knowledge_read_tools.py`（或并入既有模块，planner 定），`@tool` + `ToolResult` 模式：
  - `search_learning_cases`：薄封装 Phase 100 定版后的 `learning_case_service.search_learning_cases`（向量版），fail-closed 走 `_resolve_conversation_user` 先例（delivery_knowledge_tools.py L111–113）。挂 `_INDEXED_TOOL_NAMES`。
  - `search_project_context`：薄封装 `DeliveryKnowledgeSearchService.search_similar(include_document_kind=True)` + 项目过滤；权限复用 `project_read_tools.py` L38–86 成员/`public_org` fail-closed 校验。挂 `_PROJECT_READ_TOOL_NAMES`（需 bound_project_id）。
  - `read_project_doc`：薄封装 `DocContentService.get_doc_render`；权限同上。挂 `_PROJECT_READ_TOOL_NAMES`。
- import 侧效应注册对齐 chat_runner.py L40–43 既有模式。
- Chat 链召回写 RetrievalTrace（对齐 KNOW-04 形态，conversation_id 关联）。

### KNOW-06 ProjectStateApi 可检索（断链修复）
- 断链事实：`upsert_state_api` 只调 `schedule_doc_push`，不物化；`project_doc` normalizer 用 `last_synced_snapshot`（默认不含 API 行）。
- 修复方案（不建第二通路，INV-6）：
  1. `ProjectDocService.upsert_state_api` 成功后追加 `_schedule_materialization(DocType.STATE)`（复用既有防抖/调度机制 L638–661）。
  2. `knowledge/sources/project_doc.py` normalizer 对 **STATE 类型文档**改用 live 渲染内容（复用 `DocContentService` 的系统区渲染，含 `METHOD path — status` API 清单），其他文档类型维持 snapshot 行为不变。
- 验收：上报 `report_project_state` 后，`search_project_context` 能命中该 API 清单（集成测试：上报 → 物化 → 检索命中断言）。

### UNIFY-04 契约与文档对齐
- `TOOL_SCHEMA_SNAPSHOT` 补 `report_project_state`（request: project_id/branch_name/repository_id/apis；response: applied/reason/results/total_applied/run_id——对照 serializer L559–586 与 view 实际输出核实）。
- 快照测试新增**防漏守卫**：断言 `mcp_tools/urls.py` 注册工具名集合 == `TOOL_SCHEMA_SNAPSHOT.keys()`（解析 urls 或经注册表内省，planner 定实现）。
- 新增 grep 守卫测试：`skills/skills/**/SKILL.md` 中引用的 MCP 工具名 ⊆ snapshot 键集（落 `server/tests/mcp_tools/`，读仓库根 skills 文件）。
- `skills/skills/friday-memory/SKILL.md`：`search_learning_cases` 检索语义改写为统一向量检索（融合分、hints 为查询增强/提权而非 token 收窄）。
- `skills/skills/friday-code/SKILL.md`：阶段二加入 `reverse_lookup_requirements`（证据→需求反查）路由说明。
- skills 文档键集/工具名不得引入 snapshot 外的新工具名。

### Claude's Discretion
- settings 键名与默认限额数值
- 分 kind 查询 vs 单查后截断的取舍（以 search_similar 调用成本与排序一致性为准）
- 测试组织与 fixture 复用

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/services/process_runtime/recall_adapter.py` L26–33 RECALL_ENTITY_KINDS、L43–80 recall()、L39–41 top_k；`builtin_processes.py` L93–103 `_h_recall` stage；`entrypoint.py` L91 注入
- `server/agents/chat_runner.py` L78/L84–117/L123–130 三个白名单常量、L250–283 `_get_tool_names`、L40–43 import 注册
- `server/agents/tools/delivery_knowledge_tools.py` L63–141 薄封装范本（fail-closed L111–113）；`project_read_tools.py` L38–86 项目权限范本；`agents/tools/base.py` L35–66 ToolResult
- MCP 对应实现：`SearchLearningCasesView` views.py L1686–1741；`SearchProjectContextView` L3314–3393（RetrievalTrace 形态 L3373–3384）；`ReadProjectDocView` L3460–3537 + `DocContentService.get_doc_render`
- `server/initiatives/models/project_state_api.py` L35–84；`ProjectDocService.upsert_state_api` L373–432、`_schedule_materialization` L638–661；`knowledge/sources/project_doc.py` L76–96（snapshot 取值点）；`DocContentService._resolve_system_text` L195–203（live API 渲染）
- `server/mcp_tools/serializers.py` L589–724 snapshot（29 键，缺 report_project_state）；`urls.py` L38–107（30 注册）；`tests/mcp_tools/test_schema_snapshot.py`（现仅整表断言，无集合守卫）
- `skills/skills/friday-code/SKILL.md` / `friday-memory/SKILL.md`（reverse_lookup_requirements 全树 grep 为零；memory L41 检索语义为旧 token 描述）
- `tests/services/test_recall_adapter.py` L155–156（锁旧 kinds 集合，需更新）

### Established Patterns
- 薄封装工具：`@tool` 装饰器 + ToolResult + fail-closed 权限前置
- RetrievalTrace：`arecord_retrieval_trace`，payload 含 duration_ms/scores/top_score
- vector_recall `_DEMAND_KINDS` 已含 LEARNING_CASE（Phase 100）；`include_document_kind` flag 控制 document 分路

</code_context>

<specifics>
## Specific Ideas

- 核心思路"优雅好用"：可配置默认开、不加多余配置面；守卫测试让契约漂移在 CI 就死，不靠人背。
- Chat 包装必须跟 Phase 100 定版后的向量版 service——不冻结旧 token 行为。

</specifics>

<deferred>
## Deferred Ideas

- Chat `search_delivery_knowledge` 补 MCP 级 RetrievalTrace（对齐但非本 phase 验收）——若顺手可做，不作为 must-have
- 召回结果进 prompt 的 token 精确计量（先靠每 kind 限额粗控）

</deferred>
