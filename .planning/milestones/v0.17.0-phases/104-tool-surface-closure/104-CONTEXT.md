# Phase 104: 工具面收口（improve/analyze 收敛 + 确定性缝退役 + 端到端验收） - Context

**Gathered:** 2026-07-15
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous — 推荐值自动采纳）

<domain>
## Phase Boundary

MCP 工具面收口到统一编排：`improve_coding_plan` / `analyze_repository` 收敛到 `delegate_process_runtime`；`mcp_tools/planning_service.py` 确定性缝退役、`services/plan_orchestration/` 空壳删除、全仓残留引用清零；完成"四处检索同一 learning case"的里程碑端到端验收。需求：UNIFY-01/02/03。依赖 Phase 102（编排召回扩容已就位——收敛后 improve/analyze 的工具质量不降级）。

</domain>

<decisions>
## Implementation Decisions

### UNIFY-01 improve_coding_plan 收敛（对外契约为首个 task 定版）
- **契约定版（同步 vs 会话式）**：跟随 `create_coding_plan` 既有先例——HTTP 请求内**同步 await 至 pause/terminal**；`DONE→completed`、`FAILED→failed`、research/clarify 在途**立即短路返回 `partial` + `session_id`**（不阻塞等容器，Cursor 不挂起不超时）。契约写进 serializer schema 描述（改版语义 = 携带 feedback 的编排重跑产新 version；partial 时可经 `get_coding_execution`/后续调用跟进）。
- feedback 表达：编排重跑的 `requirement_text` = 原需求 + 结构化 feedback 块（含最新 `McpCodingPlanVersion` 方案摘要 + 用户 feedback 文本）；`delegate_process_runtime` 不加 feedback 专用参数（保持签名中性）。
- 产物映射：编排 canonical 产物经随迁的 `map_canonical_to_coding_plan` 映射，写 `McpCodingPlanVersion(version=current_version+1)` 并回写 `plan.current_version`（既有递增语义不变）。
- Response 键集：新增 `session_id` / `status` 两键（trace 中可见编排 session）；`TOOL_SCHEMA_SNAPSHOT` 同步更新，**同时修复 create_coding_plan 的既有漂移**（运行时已返回 session_id/status 但 snapshot 未收录）。request 键集不变。
- 确定性 `improve_coding_plan()`（planning_service L388–451，"往 steps 追加一行"式假改版）退役删除。

### UNIFY-02 analyze_repository 收敛 + 证据消费
- 分析生成逻辑（`build_repository_analysis` L143–218，确定性证据采集：模块分组/入口/测试路径）**随迁**独立模块 `mcp_tools/repository_analysis_service.py`（非 LLM 生成，本质是证据采集器，保留确定性实现合理）；view 改引用随迁模块，response 契约不变。
- **编排消费接线（消除空转）**：`delegate_process_runtime` 增可选 `extra_evidence: list[dict] | None` 参数 → 写入 `start_orchestration` 的 `stage_state`（如 `decomposition.extra_evidence`），recall/merge 阶段实际消费（merge prompt 组装时纳入证据，trace 事件可见 evidence 条数）；`CreateCodingPlanView` / `ImproveCodingPlanView` 带 `analysis_id` 时读取 `McpRepositoryAnalysis.summary` 注入。
- `map_canonical_to_coding_plan`（仍被 views + 1 测引用）随迁至 `orchestration_delegate.py`；`normalize_context_chunks` 若仅存量内部使用则随 view 需要迁移或删除；`build_coding_plan`（已 DEPRECATED、无生产调用方）直接删除。
- 测试迁移不失覆盖：`test_planning_tools.py` 的 improve/analyze 用例改 patch `mcp_tools.views.delegate_process_runtime`（fake delegate，防真实编排时长爆炸）；`test_create_coding_plan_delegate.py:283` 的 import 路径更新；`test_mcp_artifact_sources.py` 的 improve ingestion 触发用例同步适配。

### UNIFY-03 残留清零
- **首个 task：`rg planning_service` / `rg plan_orchestration` 全仓引用清单**（排除 .planning 与 .claude/worktrees 旧副本），逐项处置。
- 删除 `server/mcp_tools/planning_service.py`；删除 `services/plan_orchestration/` 空目录。
- 文档残留：`docs/workflows/ai-plan-generation-deprecation.md:10` 的 `plan_orchestration` 文案更新为 `process_runtime`。
- stale patch target 防线：新增测试断言所有 `mock.patch("mcp_tools...")` / 涉及本次迁移的 patch target 字符串可 import（`importlib` + `getattr` 逐段解析）；顺手核查 Phase 26 前科面（test_batch_pr.py 当前 target 已对齐，仅断言不改动）。

### 里程碑端到端验收（四处检索同一 learning case）
- 服务端集成测试（新文件，如 `server/tests/test_milestone_e2e_learning_case.py`）：种一条 learning case（经 create → ingestion → 向量入库，用既有内存 Qdrant + 确定性 embedding 测试设施），断言同一条 case 在：
  1. Chat 工具 `search_learning_cases`（agents/tools 薄封装，Phase 102 产物）
  2. 编排召回 `DeliveryKnowledgeRecallAdapter.recall`（kinds 含 learning_case，Phase 102 产物）
  3. MCP `search_learning_cases` view（向量版，Phase 100 产物）
  4. 容器知识 MCP 链：task 侧 handler 契约测试（task/tests 既有 mock 端点模式）+ 服务端 view 同 URL 契约——组合覆盖，测试注释写明组合逻辑
  四处均可召回且排序来自同一 `DeliveryKnowledgeSearchService`（统一排序断言：MCP 与 Chat 返回的 top-1 entity_id 一致）。

### 观测
- improve 收敛后走编排链路，编排既有事件/trace 覆盖；`ImproveCodingPlanView` 保持 `McpToolView._record`（RequestMetric + run 关联）不变。
- 无新增 LLM 调用点（编排内既有 call_source 覆盖），无新增召回面。

### Claude's Discretion
- `extra_evidence` 的 stage_state 键名与 merge 消费的具体拼装
- feedback 块的 prompt 措辞
- 测试文件组织与 fake delegate 的构造

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/mcp_tools/planning_service.py` 符号清单：PROMPT 常量 L19–22、PlanningResult L25–29、normalize_context_chunks L52–71、build_repository_analysis L143–218（随迁）、build_coding_plan L221–308（DEPRECATED 直删）、map_canonical_to_coding_plan L311–385（随迁）、improve_coding_plan L388–451（退役）
- 引用面（全仓 rg 已核）：`views.py` L76–80 import 三符号 + L1772/L1890/L2003 调用；`test_create_coding_plan_delegate.py:283`；旧 worktree 副本不在主树
- `server/mcp_tools/orchestration_delegate.py` L119–173 `delegate_process_runtime`（同步 await、DONE/FAILED/partial 三态映射、research 在途短路返回 session）
- `server/mcp_tools/views.py`：AnalyzeRepositoryView L1745–1824、CreateCodingPlanView L1827–1966（delegate 先例 + analysis_id 仅挂 FK L1851–1863）、ImproveCodingPlanView L1969–2069（current_version+1 递增 L2011–2027）
- `server/services/process_runtime/`：stage 图 decompose→route→recall→clarify→research→merge→DONE（builtin_processes.py L151–191）；`entrypoint.start_orchestration` L32–64（stage_state 注入点）
- `McpCodingPlanVersion` models.py L113–160（uniq (plan, version)）
- snapshot：serializers.py L641–651（improve/analyze 现键集）；**create 已有 session_id/status 漂移待修**
- 测试：`test_planning_tools.py`（improve/analyze 零 mock 走真实确定性实现——删缝后必须改）；`test_create_coding_plan_delegate.py`（patch "mcp_tools.views.delegate_process_runtime" ×5）
- `services/plan_orchestration/` 已是完全空目录；docs 残留仅 `docs/workflows/ai-plan-generation-deprecation.md:10`

### 关键风险
- improve/analyze 现有测试零 mock；删缝后不改测试会打真实编排（时长爆炸）或 ImportError——测试迁移与删缝同 task 闭环
- create 的 snapshot 漂移说明"运行时返回键 ⊄ snapshot"是已发生事故——本 phase 的集合守卫（Phase 102 产物）+ 本次补键一起兜住

</code_context>

<specifics>
## Specific Ideas

- 核心思路"优雅好用"：improve 契约跟 create 完全同型（用户学一次就会）；不留无人消费的空转参数与工具。
- 收口顺序：引用清单 → 契约定版 → 收敛 → 删缝 → E2E，一步不跳。

</specifics>

<deferred>
## Deferred Ideas

- `chat.CodingPlan` 与 `McpCodingPlan` 合表（Out of Scope 锁定）
- improve 的会话式增量交互（多轮 refine）——单独立项
- LOOP-05 review 沉淀已在 Phase 101 交付，本 phase 不再扩

</deferred>
