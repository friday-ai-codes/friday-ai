# Phase 101: 完工沉淀闭环（公共回写 + 自动提炼 + Skill 种子） - Context

**Gathered:** 2026-07-15
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous — 推荐值自动采纳）

<domain>
## Phase Boundary

任一链路（工作流 / Chat / MCP）编码完成后业务侧一致可见、经验自动沉淀：飞书回写抽为公共 service 三链路统一接入；编码成功完成自动提炼 learning case 入统一知识库（走 Phase 100 已交付的入图通路）；平台内置 `pre_coding_research` / `post_coding_capture` 两个多步 Skill；PR 后可选轻量 review 沉淀。需求：LOOP-01~05。**锚点一律挂"MR 结果已知"之后，不挂容器回调 `_handle_completed`（INGEST-02 前科，锁定）。回写与沉淀 best-effort fail-soft，绝不阻断主流程。**

</domain>

<decisions>
## Implementation Decisions

### LOOP-01 公共回写服务
- 新建 `server/delivery/services/coding_completion.py` `CompletionWritebackService`：入参中性化——work_item 三元组（`feishu_project_key`/`work_item_type`/`work_item_id`）+ 每仓结果列表（repo/status/branch/commit/mr_url/error）+ 可选 doc append（`feishu_document_id` + markdown）+ `initiated_by_user_id`。
- 评论与文档格式沿用 `_write_results_back` 现有模板（`_execution_results_markdown` 表 + "Friday 已更新执行结果" 评论），格式渲染逻辑随迁公共层。
- MCP `_write_results_back` 改薄包装：`write_back` 开关语义、`retry_state`（PARTIAL 翻转、`failed_stage="execution_writeback"`、成功不动 retry_state）、返回 `(document_update, comment)` 外形**全部零回归**——MCP 专属的 plan 模型状态翻转留在 MCP 层，不进公共 service。
- 回写失败记 `writeback_failed` 结构化事件后跳过（不重试轰炸飞书 API）；无三元组记 `writeback_skipped`。事件带 `category=caller`、`component`、`initiated_by_user_id`（无则 `system`）。

### LOOP-02 工作流 / Chat 锚点接线
- workflow：`AICodingNode._finalize_and_notify` 在 MR 创建与 cross-reference 之后调公共回写；三元组经 `plan_data.plan_version_id → ArtifactVersion → artifact.work_item → delivery.WorkItem`（与 `pr_cross_reference.render_traceability_section` 同链）反查；fallback：trigger payload / dispatch metadata 的 `work_item_id`。
- 节点配置：`AICodingNode.config_schema` 新增 `write_back`（boolean，模板默认 `True`）+ 前端 `web/src/types/workflow/schemas.ts` `aiCodingConfigSchema` 同步。
- **存量 fallback 守门（P3 锁定）**：config 无 `write_back` 键时——能反查到绑定 work_item 三元组才回写，反查不到静默跳过（零行为变化用例 + 升级说明必须有）。
- chat：`server/orchestration/coding_graph.py` `create_pr_or_skip_node` 建 PR 成功后接公共回写；三元组经 `CodingSession.coding_plan → delivery Artifact → WorkItem` 反查（反查链任一环缺失 no-op fail-soft）。skip-PR 分支不回写。
- Chat 侧不加会话级开关（能反查到 work_item 即回写，反查不到自然跳过——避免新配置面）。

### LOOP-03 自动提炼 learning case
- 锚点：与回写同点位（三链路"MR 已知"处），公共入口 `server/mcp_tools/learning_case_extraction.py`（或 delivery/services 下，planner 定）`aextract_learning_case(...)` best-effort 调度（经 `run_in_background`/直接 async task，不阻塞主流程）。
- LLM 提炼镜像 `initiatives/services/memory_distill.py` 全套模式：`use_call_source("learning_case_extraction")` + `build_chat_model`（streaming=False、max_output_tokens 限额）+ `arecord_llm_usage` + `redact_secrets_in_text` + 缺凭证/异常返回 None。
- 输入料：TaskResult（text_output/branch/pr_url/modified_files）+ plan 摘要（如有）+ 任务需求文本；产出结构化 problem/root_cause/solution/outcome。
- **幂等键 = `session.session_id`**（TaskResult 无 UUID PK，实事求是）：`McpLearningCase` 新增 `source_session_id` 字段（unique，null=True）或以其为查重键——同一 session 重入只产一条。
- FK 放松：migration 将 `McpLearningCase.run` 改 null=True（自动提炼无 InteractionRun；technical_plan 已可空）。
- 质量门槛全套与功能同 PR：失败/取消任务不提炼（status 门）；LLM 产物最小信息量校验（problem/solution 非空且非模板废话——长度 + 去模板断言）；不过门走显式 REJECT 路径记 `learning_case_rejected` 结构化事件并计数（不入库）。
- 系统级开关：`SettingKeys.LEARNING_CASE_AUTO_EXTRACT = "learning_case.auto_extract_enabled"`，`aget_bool_setting(default=True)`——默认开、可秒关。
- 入库走既有 `McpLearningCase.acreate` + `aschedule_ingestion("learning_case", ...)`（Phase 100 通路），带 `initiated_by_user_id`（无则 `system`）。

### LOOP-04 平台 Skill 种子
- 新 migration（tools app）种两个 `RemoteTool(source=Source.SKILL)`：
  - `pre_coding_research`：steps = route_repositories → search_rag_chunks → search_delivery_knowledge → search_learning_cases
  - `post_coding_capture`：steps = summarize_branch → create_learning_case → report_project_knowledge
- 步级 trace 补齐：`tools/sources/skill.py` 执行每步时记结构化事件 + 每步写 ToolCallRecord（或等价 ledger 明细，planner 按 `arecord_tool_call` 复用成本定），保证 `/api/tools/execute/` 调用后步级可查。
- Skill steps 的参数模板支持从上一步输出取值的既有机制沿用（如无该机制，最小实现：steps 接受静态 arguments + 顶层输入透传，文档写明）。

### LOOP-05 PR 后可选 review 沉淀
- 开关：`SettingKeys.PR_REVIEW_CAPTURE = "learning_case.pr_review_enabled"`，默认**关**。
- 触发点：PR 创建成功锚点（chat + workflow），开启时 best-effort：拉 diff 摘要（复用 summarize_branch service）→ LLM review（复用 `code_review.py` 的 `REVIEW_SYSTEM_PROMPT` 残留常量为基底，`call_source="pr_review_capture"`）→ 结论沉淀为一条 learning case（复用 LOOP-03 入库路径，标记 source_links 指向 PR）。
- 范围锁定"能跑通 + 沉淀"：不做评审 UI、不做规则引擎、不回写 review 意见到 PR。

### 观测（P8 内嵌验收）
- 新增 2 个 `call_source`：`learning_case_extraction` / `pr_review_capture`——**先登记** `server/agents/call_source.py` `CallSource` 枚举 + `.planning/observability/LOGGING-SPEC.md` §4.1 **再写代码**；顺手补登已漂移的 `feature_list_parse`。
- `ModelUsageRecord` 可按新 source 聚合（arecord_llm_usage 自动覆盖）。
- 回写/沉淀全部事件带 `initiated_by_user_id`；workflow 链用 `triggered_by_id`，chat 链用 conversation user，MCP 链用 run user。

### Claude's Discretion
- 提炼 prompt 具体措辞（含泛化性引导：要求"可复用经验"而非"任务日志"，research 参考 cosine>0.92 去重后置不做）
- 公共回写 service 的内部方法拆分
- Skill steps 的参数拼装细节
- 测试文件组织

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/mcp_tools/work_item_execution_service.py` L434–535 `_execution_results_markdown` + `_write_results_back`（抽取源；write_back 语义 L538–590、retry_state L511–522）
- `server/workflows/nodes/ai/coding.py` L1180–1322 `_finalize_and_notify`（workflow 锚点；MR 结果 L1195–1211、task_result ingestion L1251–1279）；config_schema L131–162
- `server/orchestration/coding_graph.py` L561–656 `create_pr_or_skip_node`（chat 锚点）
- `server/workflows/services/pr_cross_reference.py` L62–111 `render_traceability_section`（plan_version_id→WorkItem 反查链范本）
- `server/initiatives/services/memory_distill.py`（LLM 提炼全套范式：call_source/usage/脱敏/fail-soft）
- `server/agents/llm_factory.py` L64–75 `build_chat_model`
- `server/agents/call_source.py` `CallSource` 枚举（33 值；缺 learning_case_extraction）
- `server/system/settings_service.py` `aget_bool_setting`（开关范式，示例 `ALERT_EMAIL_ENABLED`）
- `server/tools/sources/skill.py`（steps 顺序执行）+ `tools/migrations/0002_seed_builtin_tools.py`（种子 migration 范本）+ `POST /api/tools/execute/`（views.py L32–80）
- `server/mcp_tools/merge_request_service.py` L74+ `summarize_branch`
- `server/workflows/nodes/ai/code_review.py` L12–51 `REVIEW_SYSTEM_PROMPT`（残留常量，LOOP-05 基底）
- `server/subagent/api/callbacks.py` L818–911 `_handle_completed`、L1195–1226 `_resolve_initiated_user`

### Established Patterns / 关键事实
- `McpLearningCase` FK：`run` NOT NULL（需放松）、`context/technical_plan/tool_call` 已 null=True
- `TaskResult` 无 UUID PK——幂等键用 `session.session_id`
- `CodingSession` 无 work_item 三元组字段——chat 反查走 coding_plan→artifact→WorkItem
- Skill 步级 ledger 现状缺失（仅顶层一次 arecord_tool_call + logger.info）——需补
- `web/src/types/workflow/schemas.ts` L290–295 `aiCodingConfigSchema`（前端同步点）；node-definitions.json 无 ai_coding 条目
- 飞书客户端：`services.feishu.create_feishu_client_for_project`（评论）/ `agents.tools.feishu_doc_tools.create_feishu_doc_client_for_project`（文档）

</code_context>

<specifics>
## Specific Ideas

- 核心思路"优雅好用"：公共 service 只做一件事（回写），MCP 专属语义不上提；chat 侧不新增配置面，能反查即回写。
- 质量门槛与提炼功能必须同 PR 落地（mem0 97.8% 垃圾率前车之鉴），绝不"先跑通后补"。

</specifics>

<deferred>
## Deferred Ideas

- 提炼去重阈值（cosine>0.92 相似 case 合并）——先靠幂等键 + 质量门，噪音实测后再做
- review 产品化（评审 UI / 规则引擎 / PR 回评）——Out of Scope 锁定
- Skill steps 步间数据流 DSL 化——最小实现先行

</deferred>
