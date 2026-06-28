---
phase: 94
slug: entrypoint-unify
nyquist_compliant: true
test_stack: pytest + pytest-asyncio + pytest-django (server) / vitest + @vue/test-utils + happy-dom (web)
created: 2026-06-27
---

# Phase 94 — Nyquist Validation Map（三入口归一·entrypoint-unify）

每个 plan 的每个 task 至少有一个 `<automated>` 测试入口。后端测试栈 `pytest>=9.0.2` + `pytest-asyncio` + `pytest-django`（`cd server && uv run pytest`，config `server/pyproject.toml`）；前端测试栈 `vitest@^4` + `@vue/test-utils` + `happy-dom`（`cd web && pnpm vitest run`，config `web/vitest.config.ts`）。本 phase 为纯内部重构/收口（无新外部依赖、无 DB 迁移），守护重心在「三入口产同一 canonical + 既有兼容不回退 + 单一来源澄清」。RESEARCH §Validation Architecture 列出的 5 项 Wave 0 缺口逐条映射到下表对应 task（见 §Wave 0 缺口覆盖）。

## Per-task test map

| Plan | Task | 自动化测试 | 覆盖断言 |
|------|------|-----------|---------|
| 94-01 | T1 共享渲染 helper（UNIFY-06 基础，tdd） | `cd server && uv run pytest tests/workflows/test_plan_research_node.py -k "render_merged_plan or plan_markdown" -x` | render_merged_plan_markdown：title 粗体/summary/execution_plan 逐项+截断/compat_risks 用 `•` 字面项目符号；非 dict/空→空串不抛；不含 LLM 原文（UNIFY-06「不 dump 原文」）；barrel 导出可 import |
| 94-01 | T2 ai_plan_research done 产 plan_markdown + schema 声明（UNIFY-06，tdd） | `cd server && uv run pytest tests/workflows/test_plan_research_node.py -x` | DONE→output 含非空 plan_markdown + 既有 plan_version_id/session_id/status/plan 零回归；content 缺失→plan_markdown 空串、plan={}；get_schema default 端口 schema.properties 含 plan_markdown(string)；failed 分支零回归 |
| 94-01 | T3 technical_plan_generation 切 ai_plan_research + loader 断言（UNIFY-01） | `cd server && uv run pytest tests/workflows/test_template_loader.py -k "technical_plan or validates_with_zero_errors or accepts_valid" -x` | 模板 generate_plan=ai_plan_research + requirement_text config + 删 notify_clarify/need_clarification 边；`test_template_validates_with_zero_errors[technical_plan_generation]` + `test_acreate_accepts_valid_templates` 转绿（**消除既有 field_not_found 失败**）；node_types 含 ai_plan_research、不含 ai_plan_generation |
| 94-02 | T1 ai_plan_generation 标 deprecated（保留注册）+ 迁移指引（UNIFY-02） | `cd server && uv run pytest tests/workflows/test_node_schema.py -k "deprecated or registr or plan_generation" -x` | `NodeRegistry.get("ai_plan_generation")` 非空且 `deprecated is True`；`ai_plan_research.deprecated is False`（对照未误标）；节点类代码/端口/map_output 逐字保留（仅加 ClassVar+docstring+warning）；迁移指引文档存在 |
| 94-02 | T2 NodePalette 移除 ai_plan_generation + 暴露 ai_plan_research + node-sync 守护（UNIFY-02） | `cd web && pnpm vitest run node-sync` | palette ⊆ fixture；`ai_plan_generation ∉ palette ∧ ∈ fixture`（后端仍注册未从 fixture 删）；**`ai_plan_research ∈ palette ∧ ∈ fixture`（WARNING 1：UNIFY-02 第二半暴露 ai_plan_research）**；幽灵守护零回归 |
| 94-03 | T1 engine skip_clarification + 共享 MCP delegate 核心（UNIFY-03） | `cd server && uv run pytest tests/mcp_tools/test_create_feishu_technical_plan_delegate.py -k "delegate" -x` | build_orchestration_engine(skip_clarification=True) 注入 no-clarify policy、默认 False 零回归；delegate_plan_orchestration 三态映射（DONE→completed+content+render markdown / RESEARCHING→partial+session_id / FAILED→failed）；编排不在 MCP 层重写（仅调 start_orchestration+adrive） |
| 94-03 | T2 create_feishu_technical_plan delegate 接线 + 响应/落库 + **同步达 DONE 契约（WARNING 2）** | `cd server && uv run pytest tests/mcp_tools/test_create_feishu_technical_plan_delegate.py -x` | 响应键集合 snapshot（旧键全在 + 新增 session_id 不缩减）；McpWorkItemTechnicalPlan 落库（plan_body=canonical/markdown/status 映射）；delegate 被调（不再走 _build_repo_task_matrix）；缺 actor 降级不崩；**MCP 同步达 DONE 契约用例（真实 start_orchestration+engine+adrive、research 同步解析 stub、空 node_execution_id→status=completed+非空 markdown）+ PARTIAL 调用方契约文档化** |
| 94-04 | T1 create_coding_plan delegate（单仓约束 + canonical 映射）+ 落库（UNIFY-04） | `cd server && uv run pytest tests/mcp_tools/test_create_coding_plan_delegate.py -x` | delegate 被调且 `include_repos=[repository_id]`（单仓约束）；canonical execution_plan 该仓 task→affected_files/steps/test_plan 映射；响应键集合 snapshot（旧键全在 + session_id/status）；McpCodingPlan/McpCodingPlanVersion 落库；partial 挂起态 output 携 session_id 不崩（复用 94-03 delegate 契约）；缺 actor 降级 |
| 94-05 | T1 plan 澄清改用独立渲染 marker（UNIFY-05） | `cd server && uv run pytest tests/agents/test_start_plan_research_tool.py -x` | _maybe_suspend CLARIFYING 输出 marker=="plan_clarification"（独立常量）携 session_id+clarification_id；不再 import/复用 chat 的 CLARIFICATION_PENDING_MARKER；RESEARCHING 分支逐字零回归 |
| 94-05 | T2 二义消除守护测试（UNIFY-05 Wave 0） | `cd server && uv run pytest tests/agents/test_start_plan_research_tool.py tests/test_ask_clarification_tool.py -x` | plan marker 独立性（携 session_id+clarification_id）；`_extract_pending_clarification` 对 plan ToolResult 返回 None（不写 ConversationIntentTrace）；chat 单题 ask_clarification 仍被捕获（对照零回归，name+marker 双 ask_clarification） |
| 94-05 | T3 前端零回归——plan 卡不依赖 marker 字面值（**WARNING 3**） | `cd web && pnpm vitest run chat.clarification` | plan 澄清卡由 `pending_plan_clarification` runtime（session_id/clarification_id）驱动、断言不读 marker 字面值（marker 改名零影响）；chat 单题路径仍仅认 `marker==='ask_clarification'`（携 plan_clarification marker 不被误认单题卡、对照 ask_clarification 仍认） |

## Wave 0 缺口覆盖（RESEARCH §Validation Architecture → task 映射）

| Wave 0 缺口 | 覆盖 task | 测试入口 |
|-------------|----------|---------|
| ① template_loader 同步 technical_plan_generation→ai_plan_research（修 field_not_found）+「ai_plan_research not legacy」断言 | 94-01 T3 | `uv run pytest tests/workflows/test_template_loader.py -k "technical_plan or validates_with_zero_errors or accepts_valid" -x` |
| ② MCP 响应外形守护（feishu_technical_plan / coding_plan delegate 后响应键 snapshot + Mcp* 落库断言）；**MCP 同步达 DONE 契约 + PARTIAL 文档化（WARNING 2）** | 94-03 T2 / 94-04 T1 | `uv run pytest tests/mcp_tools/test_create_feishu_technical_plan_delegate.py tests/mcp_tools/test_create_coding_plan_delegate.py -x` |
| ③ deprecated 节点守护（ai_plan_generation 仍 @register_node、NodePalette 不暴露）+ **暴露 ai_plan_research（WARNING 1）** | 94-02 T1 / T2 | `uv run pytest tests/workflows/test_node_schema.py -k "deprecated or registr" -x`；`pnpm vitest run node-sync` |
| ④ UNIFY-05 守护（plan 澄清答经专路由续推、不误入 ConversationIntentTrace 单题路径）+ **前端零回归断言（WARNING 3）** | 94-05 T2（后端）/ T3（前端） | `uv run pytest tests/agents/test_start_plan_research_tool.py tests/test_ask_clarification_tool.py -x`；`pnpm vitest run chat.clarification` |
| ⑤ ai_plan_research plan_markdown 输出字段渲染单测（UNIFY-06）+ fixture 同步（node-sync 绿） | 94-01 T1/T2 + 94-02 T2 | `uv run pytest tests/workflows/test_plan_research_node.py -x`；`pnpm vitest run node-sync` |

## Sampling Rate

- **Per task commit:** 受改子集（如 `cd server && uv run pytest tests/workflows/test_template_loader.py tests/workflows/test_plan_research_node.py -x`；前端 `cd web && pnpm vitest run node-sync` / `chat.clarification`）。
- **Per wave merge:** `cd server && uv run pytest tests/workflows tests/mcp_tools tests/agents tests/test_plan_clarification_answer_endpoint.py` + `cd web && pnpm vitest run`。
- **Phase gate:** 全套绿 + `cd server && uv run python manage.py makemigrations --check` 干净（本 phase 无新迁移）+ `uv run ruff format --check . && uv run ruff check .` + `uv run mypy`（受改后端文件）+ `cd web && pnpm vue-tsc --noEmit`，再 `/gsd-verify-work`。

## Phase gate

- 后端：`cd server && uv run pytest tests/workflows tests/mcp_tools tests/agents tests/test_plan_clarification_answer_endpoint.py -x` 全绿（含 template_loader field_not_found 修复、MCP delegate 三态 + 同步达 DONE 契约、deprecated 注册守护、UNIFY-05 二义守护）。
- 前端：`cd web && pnpm vitest run` 全量绿（尤其 node-sync[ai_plan_generation 移除/ai_plan_research 暴露]、chat.clarification[plan 卡 runtime 驱动]）；`pnpm vue-tsc --noEmit` 通过。
- 兼容红线：既有 ai_plan_generation DB 实例仍可注册/execute（节点不删、注册不注销）；MCP 响应外形不缩减（snapshot 守护）+ Mcp* 落库字段全保留；既有工作流编辑器/连线/单题澄清卡零回归。
- `cd server && uv run python manage.py makemigrations --check` 无新迁移；受改后端文件 `ruff format/check` + `mypy` 干净。
