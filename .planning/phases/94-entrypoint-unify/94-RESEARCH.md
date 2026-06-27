# Phase 94: 入口统一 (entrypoint-unify) - Research

**Researched:** 2026-06-27
**Domain:** 工作流/对话/MCP 三入口方案生成归一到 `plan_orchestration`（既有 Django/Vue 代码内重构，无新外部依赖）
**Confidence:** HIGH（全部基于本仓真实源码核对，无外部 npm/pip 依赖引入）

## Summary

Phase 94 是**纯内部重构 / 收口**里程碑收官 phase（v0.16.1 UNIFY-01~06），不引入任何外部包、不新建后端表/迁移。三入口（工作流节点 `ai_plan_research`、对话 `start_plan_research`、MCP `create_feishu_technical_plan` / `create_coding_plan`）的方案生成全部归一到既有 `plan_orchestration` 编排底座，产出 canonical `MergedPlan` / `PlanVersion`；废弃旧 LangChain 单 agent `ai_plan_generation`（节点库移除 + 代码标 deprecated，**不删**、向后兼容既有实例）。

底座已就绪（Phase 41-44 + 90/91）：`start_orchestration` / `build_orchestration_engine` 两入口共用 engine 工厂、`adrive_plan_session_to_pause_or_terminal` 共享续驱、`aanswer_round_and_resume` 共享回流、`delivery.Clarification` + `PlanSession` 单一来源澄清模型。Phase 94 的工作是**把三入口接到这些已有 helper 上 + 保留外形兼容**，而非新造能力。

**Primary recommendation:** 复用既有 helper 收口，绝不另起炉灶；MCP 两端用「delegate `start_orchestration` → 续驱到 DONE → 取 canonical `PlanVersion.content` → 映射回旧响应字段」的适配器模式，旧 `McpWorkItemTechnicalPlan` / `McpCodingPlan` 落库保留；模板切换只改模板定义 + 同步 `test_template_loader` 断言，既有已实例化工作流不动；done 推群复用 `ai_plan_generation._render_plan_markdown` 的渲染范式（`•` 项目符号 + markdown 组件）但适配 `MergedPlan` schema。

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UNIFY-01 | `technical_plan_generation.json` 模板 `ai_plan_generation`→`ai_plan_research`，既有实例不破坏 | `code_generation.json` 已是切换样板（节点 `ai_plan_research` + `requirement_text` config + `{{nodes.generate_plan.plan.title}}` 引用）；`loader.py` 仅改模板定义不动既有实例；`test_template_loader.py` 断言路径已知（§Pitfall 1） |
| UNIFY-02 | 旧 `ai_plan_generation` 标 deprecated + 从 NodePalette 移除 | `NodePalette.vue:88` 硬编码裸项；节点保留 `@register_node` 注册（向后兼容）；deprecated 标注方式（docstring/ClassVar）见 §Architecture Patterns |
| UNIFY-03 | MCP `create_feishu_technical_plan` delegate `plan_orchestration`，保留响应外形 | `technical_plan_service.build_work_item_technical_plan` 现为独立 seam；`CreateFeishuTechnicalPlanView`（views.py:1412）响应字段集已知，需映射 canonical→旧字段；`McpWorkItemTechnicalPlan` 落库保留 |
| UNIFY-04 | MCP `create_coding_plan` 口径对齐 `plan_orchestration`，保留响应 + 落库 | `planning_service.build_coding_plan`（确定性 seam）；`CreateCodingPlanView`（views.py:1807）；`McpCodingPlan` / `McpCodingPlanVersion` 落库保留 |
| UNIFY-05 | 对话澄清双挂起收敛单一来源 `delivery.Clarification` | 91-04 已建 `pending_plan_clarification` runtime + 专路由；`start_plan_research._maybe_suspend` 现复用 chat `CLARIFICATION_PENDING_MARKER`——需消除与 chat 单题 `ask_clarification` marker 的二义（§Pitfall 4） |
| UNIFY-06 | `ai_plan_research` done 出口接 `notify_feishu_im` 干净结构化 markdown | `_render_plan_markdown`（plan_generation.py:465）渲染范式可复用；`notify_feishu_im._build_card` 用 markdown 组件；need 在 `_map_terminal` 加 `plan_markdown` 字段 + schema 声明 |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 模板节点切换（UNIFY-01） | Backend / 模板定义 JSON | Test（断言同步） | 模板是 DB-seed 定义；既有实例已落 DB 不受模板改动影响 |
| 节点 deprecated + 隐藏（UNIFY-02） | Backend（节点注册/标注） + Frontend（NodePalette） | — | 节点注册在后端、节点库展示在前端硬编码，两侧都要改 |
| MCP delegate 编排（UNIFY-03/04） | API / Backend（MCP View + service seam） | Database（旧 Mcp* 落库兼容） | MCP View 是入口，service seam 替换为 delegate；落库为兼容层 |
| 澄清单一来源收敛（UNIFY-05） | Backend（chat 工具/graph 标记语义） | Frontend（已由 91-05 渲染 plan 卡） | 挂起/续推状态权威在 delivery；marker 仅前端渲染信号 |
| done 推群渲染（UNIFY-06） | Backend（节点 `_map_terminal` 渲染 + 模板接线） | — | 渲染是节点输出职责，飞书卡片渲染已在 `notify_feishu_im` |

## Standard Stack

**无新增依赖。** 本 phase 全部复用既有栈与既有 helper。

### 复用的既有底座（不重复造）

| 资产 | 位置 | 用途（Phase 94） |
|------|------|------------------|
| `start_orchestration` | `services/plan_orchestration/entrypoint.py:28` | MCP delegate 建 `PlanSession`（entrypoint=workflow/chat） |
| `build_orchestration_engine` | `services/plan_orchestration/entrypoint.py:58` | 注入真实 adapters 构造 engine（两入口同源） |
| `adrive_plan_session_to_pause_or_terminal` | `services/plan_orchestration/resume.py:24` | MCP delegate 续驱到 DONE/FAILED/挂起 |
| `aanswer_round_and_resume` | `services/plan_orchestration/answer_resume.py:42` | 澄清作答 + 续推（已被 91-03/91-04 同源调用） |
| `validate_merged_plan` / `MERGED_PLAN_FIELDS` | `services/plan_orchestration/merged_plan.py` | canonical content §7 schema |
| `_render_plan_markdown` 范式 | `workflows/nodes/ai/plan_generation.py:465` | UNIFY-06 渲染参照（`•` + 标题分段，不 dump 原文） |
| `ClarificationService` (`ahas_pending`/`create_round`/`answer_round`) | `delivery/services/clarification_service.py` | 单一来源澄清写入/谓词 |

### Installation

无。`makemigrations --check` 应保持干净（本 phase 不新建模型/字段；若 UNIFY-06 给 `ai_plan_research` 加 `plan_markdown` 输出字段，仅改节点 schema 声明，非 DB 迁移）。

## Package Legitimacy Audit

不适用——本 phase 不安装任何外部包（npm/PyPI/crates）。所有改动在既有源码内完成。

## Architecture Patterns

### System Architecture Diagram

```text
                         ┌─────────────────────────────────────────────┐
   工作流入口            │              plan_orchestration               │
   ai_plan_research ────►│  start_orchestration → PlanSession            │
   (节点 execute)        │       │                                       │
                         │  build_orchestration_engine (真实 adapters)   │
   对话入口              │       │   router/recall/clarify/research/merge │
   start_plan_research ─►│       ▼                                       │
   (chat tool)           │  adrive_plan_session_to_pause_or_terminal     │
                         │       │  ┌── CLARIFYING → delivery.Clarification│
   MCP 入口              │       │  │   (单一来源, 91/90)                  │
   create_feishu_technical_plan ─┤  └── RESEARCHING → 容器 fan-out        │
   create_coding_plan ──►│       ▼                                       │
   (★ Phase 94 新接)     │  DONE → PlanVersion.content (§7 MergedPlan)    │
                         └───────┬───────────────────────┬───────────────┘
                                 │                       │
                  ┌──────────────▼──────┐   ┌────────────▼────────────────┐
                  │ canonical 产物口径   │   │ MCP 响应映射 (★ Phase 94)    │
                  │ (审批/编码下游消费)  │   │ canonical→旧字段 + 落库兼容  │
                  └─────────────────────┘   │ McpWorkItemTechnicalPlan/    │
                                            │ McpCodingPlan (保留)         │
   UNIFY-06: DONE → _map_terminal 渲染       └─────────────────────────────┘
   plan_markdown → notify_feishu_im 推群 (干净结构化 markdown, 不 dump 原文)
```

### Pattern 1: MCP delegate 适配器（UNIFY-03 / UNIFY-04，核心模式）

**What:** MCP View 不再调独立确定性 seam（`build_work_item_technical_plan` / `build_coding_plan`），改为 delegate `plan_orchestration`：建 session → 续驱到终态 → 取 canonical `PlanVersion.content` → **映射回旧响应字段**，并继续落 `McpWorkItemTechnicalPlan` / `McpCodingPlan` 保兼容。

**When to use:** UNIFY-03（`CreateFeishuTechnicalPlanView`）+ UNIFY-04（`CreateCodingPlanView`）。

**Example（delegate 骨架，参照工作流节点 `_map_terminal` 与 chat 工具 `_map_terminal`）:**

```python
# 参照: server/workflows/nodes/ai/plan_research.py:501 _map_terminal
#       server/agents/tools/plan_research_tools.py:113 start_orchestration 调用
session = await start_orchestration(
    entrypoint="workflow",            # MCP 视作非 chat（work_item 锚）→ workflow
    requirement_text=requirement,
    work_item=work_item,              # create_feishu_technical_plan 有 McpWorkItemContext 锚
    created_by=actor,
    include_repos=repository_ids,
)
engine = build_orchestration_engine()   # MCP 无 node_execution_id（同 chat 入口形态）
session = await adrive_plan_session_to_pause_or_terminal(engine, session)

# 取 canonical content（§7 MergedPlan）
pv = await PlanVersion.objects.filter(id=session.current_plan_version).afirst()
content = pv.content if pv and isinstance(pv.content, dict) else {}

# ★ 映射回旧 MCP 响应字段（外形兼容，调用方不破坏）
output = {
    "technical_plan_id": str(artifact.id),   # 仍落 McpWorkItemTechnicalPlan
    "plan": content,                          # canonical 替代旧 plan_body
    "markdown": render_markdown(content),     # 复用渲染范式
    "status": ...,                            # 映射 session 终态 → 旧 Status 枚举
    "run_id": str(run.run_id),
    # ... 其余字段从 content 派生
}
```

**关键约束:** MCP 是**同步/单次返回**契约（`Response(output, 200)`），但编排可能挂起在 CLARIFYING / RESEARCHING。MCP 调用方无 resume 通路（无 node_execution、无 chat barrier）。**必须明确挂起态的 MCP 语义**（见 §Open Questions Q1）——`adrive` 会在挂起点短路返回未终态 session，MCP 不能把它当 DONE。

### Pattern 2: deprecated 节点（保留注册 + 节点库隐藏，UNIFY-02）

**What:** `ai_plan_generation` 节点保留 `@register_node`（既有实例可运行、向后兼容），但：
1. 代码标 deprecated（推荐：类级 `deprecated: ClassVar[bool] = True` + docstring 顶部「DEPRECATED: 改用 ai_plan_research，见迁移指引」+ `__init__` 一次性 `logger.warning("deprecated_node_instantiated", node_type="ai_plan_generation")`）。
2. 前端 `NodePalette.vue` 移除该裸项（`NodePalette.vue:88` 删行），新建路径不再暴露。

**When to use:** UNIFY-02。

**Anti-pattern:** 删除 `ai_plan_generation` 节点类或注销 `@register_node`——会让既有已实例化工作流（DB 中 `node_type="ai_plan_generation"` 的 WorkflowNode）在 registry 查找时崩溃。**绝不删代码、绝不注销注册**（CONTEXT 锁定 + 历史里程碑「向后兼容不回退」约束）。

### Pattern 3: 模板切换（只改定义，UNIFY-01）

**What:** `technical_plan_generation.json` 把 `generate_plan` 节点 `type` 从 `ai_plan_generation` 切到 `ai_plan_research`，config 从 `user_prompt` 改 `requirement_text`，引用从 `{{nodes.generate_plan.plan_markdown}}` 改为新输出字段（见 UNIFY-06）。参照 `code_generation.json` 已切样板。

**When to use:** UNIFY-01。

**关键:** 模板是**新建工作流的种子**，改模板**不触碰已实例化工作流**（既有实例的 node_type/config 已落 DB）。`loader.py:_validate_template_graph` 会在 acreate 前用 `WorkflowGraphValidator` 校验——切换后的模板必须过校验（端口/字段引用合法），否则 `test_template_loader::test_acreate_accepts_valid_templates` 红（§Pitfall 1）。

### Pattern 4: done 渲染干净 markdown（UNIFY-06）

**What:** `ai_plan_research._map_terminal` 的 DONE 分支在内联 `plan` content 之外，新增渲染好的 `plan_markdown` 字段（reuse `_render_plan_markdown` 范式，适配 `MergedPlan` schema：`title`/`summary`/`execution_plan[]`/`compat_risks`/`api_contracts` 等），并在 `outputs` 的 `default` 端口 schema 声明 `plan_markdown`（否则模板引用 `{{nodes.generate_plan.plan_markdown}}` 触发 validator `field_not_found`，见 §Pitfall 1）。模板 `notify_plan` 节点 `content = {{nodes.generate_plan.plan_markdown}}`。

**渲染要点（复用本轮渲染修复）:** lark_md 不支持列表语法 → 用 `•` 字面项目符号；飞书卡片正文走 `markdown` 组件（`notify_feishu_im._build_card` 已是 `{"tag": "markdown"}`）；**不 dump LLM 原始文本**（原文若需排障放 `raw_*` 字段）。

### Anti-Patterns to Avoid

- **重写编排逻辑:** MCP delegate 绝不在 MCP 层重新实现拆分/路由/调研——只调 `start_orchestration` + `adrive`（CONTEXT「最大化复用，严禁重复造」）。
- **删 deprecated 节点代码 / 注销注册:** 破坏既有实例（见 Pattern 2）。
- **改既有已实例化工作流:** UNIFY-01 只改模板定义，不写数据迁移去改 DB 里的 WorkflowNode（除非明确需求，本 phase 无此项）。
- **MCP 把挂起态当 DONE 返回:** 见 Open Questions Q1。
- **澄清造第三套挂起:** UNIFY-05 收敛到 `delivery.Clarification`，不再新增挂起表示。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 建 PlanSession + 构造 engine | MCP 层自己 new engine / 拼 adapters | `start_orchestration` + `build_orchestration_engine` | 两入口同源单一工厂（ENTRY-02 / SC-1），手拼会漂移 |
| 续驱 advance 循环 | MCP/节点内再写 while advance | `adrive_plan_session_to_pause_or_terminal` | 已收口 clarifying/researching 短路 + max_steps fail-soft（43-02/43-04） |
| 澄清作答 + 续推 | 各入口自写 answer + advance | `aanswer_round_and_resume` | 91-01 已建，飞书回调 + 会话端同源调用 |
| pending 澄清判定 | `.filter(answered_at__isnull=True)` 各处散写 | `ClarificationService.ahas_pending` | 兼容旧单题行 + 新结构化子题（WR-03，T-90-03-04） |
| MergedPlan content 校验 | 自写 jsonschema | `validate_merged_plan` | 复用 technical_plan schema，与 `TechnicalPlanService.create_from` 同口径 |
| 方案 markdown 渲染 | 新写渲染器 | 抽 `_render_plan_markdown` 范式为共享 helper | 已处理 lark_md 列表限制（`•`）+ 跨客户端稳定 |

**Key insight:** Phase 94 几乎不写新逻辑——核心工作量是「**接线 + 字段映射 + 删/标注 + 同步测试断言**」。任何「新写编排/续驱/澄清」的冲动都是反模式。

## Runtime State Inventory

> 本 phase 含 deprecated（`ai_plan_generation` 废弃）+ 三入口口径收口（refactor），故执行运行态盘点。

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| **Stored data（已实例化工作流）** | DB 中已存在 `node_type="ai_plan_generation"` 的 `WorkflowNode`（既有 `technical_plan_generation` 模板实例化的工作流） | **保留运行能力**（节点不删、注册不注销）；UNIFY-01 只改模板定义，不迁移既有实例。验证：deprecated 节点仍能 `NodeRegistry` 查到并 execute |
| **Stored data（MCP 落库）** | `McpWorkItemTechnicalPlan` / `McpCodingPlan` / `McpCodingPlanVersion`（历史 MCP 调用产物） | **保留落库**（UNIFY-03/04 继续 acreate 这些表，兼容旧调用方/旧 artifact 查询）；旧表下线已 deferred（CONTEXT Deferred） |
| **Stored data（canonical）** | `PlanSession` / `PlanVersion`（编排 canonical 产物）；`Clarification` / `ClarificationQuestion`（90/91 结构化澄清） | 新增使用方（MCP delegate 会建 PlanSession/PlanVersion），无 schema 变更 |
| **Live service config（飞书）** | 内置模板 `technical_plan_generation` 推群依赖项目飞书群（`notify_feishu_im` / `ensure_chat`） | 无新配置；UNIFY-06 渲染改的是 content 字段引用，不改飞书 App 配置 |
| **Secrets/env vars** | `PROMPT_CENTER_DISABLED_KEYS`（`ai_plan_generation` 的 prompt center 开关，plan_generation.py:544） | deprecated 后 prompt 仍可被既有实例用，**不删该 env 处理**（向后兼容） |
| **Build artifacts / 前端定义** | `web/src/types/workflow/node-definitions/node-definitions.json`（节点 schema fixture，含 `node_type` dump）；`NodePalette.vue` 硬编码项；node-sync 漂移守护测试 | UNIFY-02 删 palette 项；若 `ai_plan_research` 加 `plan_markdown` 输出字段需重生成 fixture（node-sync 红线）；`ai_plan_generation` 是否仍在 fixture 取决于是否 dump deprecated 节点（见 §Pitfall 2） |

**核对结论:** 本 phase **无数据迁移**（既有实例保留可运行 = 不动 DB；MCP 旧表保留 = 不动）。运行态影响集中在「① 既有 ai_plan_generation 实例必须仍可 execute ② 前端 fixture / palette 同步 ③ MCP 响应字段外形不破坏」三条兼容红线。

## Common Pitfalls

### Pitfall 1: 模板切换后 `field_not_found` / 端口校验红（UNIFY-01/06）

**What goes wrong:** 切到 `ai_plan_research` 后，模板若仍引用 `{{nodes.generate_plan.plan_markdown}}`，而 `ai_plan_research` 的 `default` 输出 schema 未声明 `plan_markdown` → `WorkflowGraphValidator` 报 `field_not_found` → `test_template_loader::test_template_validates_with_zero_errors[technical_plan_generation]` 与 `test_acreate_accepts_valid_templates` 红。**这正是当前 STATE 记录的既有失败**（"template_loader 2 technical_plan_generation 模板 generate_plan 缺 plan_markdown 字段 field_not_found"，war-room 未提交在制品）。

**Why it happens:** `ai_plan_generation` 的 `map_output` 产 `plan_markdown` 字段，但其 `default` 输出 schema（plan_generation.py:229）只声明 `plan`/`final_answer`/`usage`——`plan_markdown` 从来不在 schema 里，靠的是字段引用宽松。切到 `ai_plan_research`（输出 schema 声明 `plan_version_id`/`session_id`/`status`/`plan`）后字段集变了。

**How to avoid:** UNIFY-06 在 `ai_plan_research.outputs` 的 `default` 端口 schema 显式声明 `plan_markdown`（type string），`_map_terminal` 填充渲染结果；或模板改引用 `{{nodes.generate_plan.plan.summary}}`（code_generation.json 的做法，但仅 summary 不够「结构化」）。**推荐前者**（满足 UNIFY-06「干净结构化 markdown」）。

**Warning signs:** `pytest server/tests/workflows/test_template_loader.py -k technical_plan` 红 + reason `field_not_found`。注意：`ai_plan_research.outputs.default.schema.plan` 是 `{"type":"object"}` 无子属性 → `plan.title`/`plan.summary` 这类下钻引用 validator 放行（code_generation 已验证），但顶层 `plan_markdown` 必须声明。

### Pitfall 2: 前端 node-sync 漂移守护 + fixture（UNIFY-02）

**What goes wrong:** 删 `NodePalette.vue` 的 `ai_plan_generation` 项后，node-sync 守护测试（`palette ⊆ fixture` / orphan 检测）可能红，或反之——若节点仍 dump 进 `node-definitions.json` fixture 而 palette 不含，是允许的（palette 是 fixture 子集）；但若 fixture 重生成把 deprecated 节点排除了，旧引用会 orphan。STATE 记录 fixture node_count 当前为 **42**（92-03 落地）。

**How to avoid:** 删 palette 项是安全的（palette ⊆ fixture 单向约束）。若 UNIFY-06 给 `ai_plan_research` 加输出字段 → 需 `dump_node_fixture` 重生成 fixture（node_count 不变但 ai_plan_research schema 变），跑 `node-sync.test.ts` 确认绿。**不要**为隐藏 deprecated 节点而从 fixture 删 `ai_plan_generation`（既有实例反查节点定义会断）。

**Warning signs:** `pnpm vitest node-sync` 红；`web/src/types/workflow/node-definitions/node-definitions.json` 与后端 `get_all_schemas()` 不一致。

### Pitfall 3: MCP 响应外形破坏（UNIFY-03/04，契约硬约束）

**What goes wrong:** delegate 后直接把 canonical `MergedPlan` 当响应返回，删/改了旧字段（`technical_plan_id`/`plan`/`markdown`/`repository_tasks`/`status`/`feishu_document`/`comment` 等，见 views.py:512 output 结构），MCP 调用方（Codex agent / 外部）解析失败。

**Why it happens:** canonical content 字段名（`execution_plan`/`api_contracts`...）≠ 旧 seam 字段名（`repository_task_matrix`/`repository_tasks`...）。

**How to avoid:** 显式字段映射层——canonical → 旧响应字段（`repository_task_matrix` ← `execution_plan` 映射等）。保留 `McpWorkItemTechnicalPlan` 所有持久化字段（`plan_body`/`markdown`/`repository_tasks`/`evidence`/...）。映射的精确对应表由 plan-phase 定（CONTEXT Claude's Discretion）。建议用 schema snapshot 测试守护响应键集合不漂移。

**Warning signs:** `tests/mcp_tools/` 响应结构断言红；`McpWorkItemTechnicalPlan` 字段缺失。

### Pitfall 4: 澄清 marker 二义（UNIFY-05，核心收口点）

**What goes wrong:** `start_plan_research._maybe_suspend`（plan_research_tools.py:223）在 CLARIFYING 时返回 `ToolResult` 携 `marker=CLARIFICATION_PENDING_MARKER`（="ask_clarification"，复用 chat 单题 marker）。但 chat orchestration graph 的 `_extract_pending_clarification`（graph.py:539）只匹配 `tc["name"]=="ask_clarification"`——`start_plan_research` 的工具名是 `start_plan_research`，**不会**被该 helper 捕获进 `wait_clarification_node` 的 chat-graph interrupt 路径。

真正的 plan 澄清出口面是 91-04 建的：runtime `pending_plan_clarification`（读 `delivery.Clarification`）+ 专路由 `POST /conversations/{id}/plan-clarification/answer/` → `aanswer_round_and_resume`。

**二义本质:** 同一次 plan 澄清挂起有两种「表示」——(a) `start_plan_research` ToolResult 里复用的 `ask_clarification` marker（语义上像 chat 单题澄清，但不被 graph 单题路径消费）；(b) canonical `delivery.Clarification` + `PlanSession`（91-04 出口面真正用的）。marker 复用造成「这是 chat 单题澄清还是 plan 编排澄清」的歧义，且若未来 graph 改判定条件可能误入 chat 单题答复路径（写 `ConversationIntentTrace`，**不会**续推 PlanSession）。

**How to avoid（UNIFY-05 目标态）:** 让 marker **仅作前端渲染信号**，挂起/续推状态**唯一以 `delivery.Clarification` + `PlanSession` 为准**：
- 核对 `start_plan_research._maybe_suspend` 的 CLARIFYING 返回——明确它产出的 marker 不进入 chat 单题 `wait_clarification` 答复链（即不写 `ConversationIntentTrace`、不靠 chat graph interrupt 收答）。
- 收答唯一经 91-04 专路由 → `aanswer_round_and_resume` → `delivery.Clarification.answer_round` + 续推 `PlanSession`。
- 建议给 plan 编排澄清用**独立的渲染 marker 标识**（区别于 chat 单题 `ask_clarification`），或在 ToolResult 里显式携 `session_id` + `clarification_id` 让前端走 plan 卡而非单题卡，消除「marker 等于 chat 单题挂起」的语义偷渡。

**Warning signs:** 用户在对话里答 plan 澄清后 PlanSession 不续推（答到了 `ConversationIntentTrace` 而非 `Clarification`）；或同一挂起既弹 chat 单题卡又弹 plan 多题卡。`test_chat_graph_clarification_interrupt.py` / `test_conversation_facade_waiting_clarification.py` 是相关守护。

### Pitfall 5: MCP 挂起态语义（UNIFY-03/04）

**What goes wrong:** MCP 是单次同步响应、无 resume 通路。delegate 编排若挂起在 CLARIFYING（需澄清）或 RESEARCHING（容器在途），`adrive` 短路返回**非终态** session，MCP 不能假装 DONE。

**How to avoid:** 见 Open Questions Q1——需明确决策（建议：MCP 返回 `status=PARTIAL/pending` + 携 `session_id` 让调用方后续查询，或对 MCP 入口禁用澄清挂起走「带现有信息继续」）。

## Code Examples

### 既有切换样板（UNIFY-01 参照）

```json
// Source: server/workflows/templates/code_generation.json (已切 ai_plan_research)
{
  "id": "generate_plan",
  "type": "ai_plan_research",
  "config": {
    "requirement_text": "## 需求\n\n**{{input.title}}**\n\n{{input.description}}",
    "include_repos": [],
    "work_item_id": ""
  }
}
// 引用: "{{nodes.generate_plan.plan.title}}" / "{{nodes.generate_plan.plan.summary}}"
```

### done 渲染范式（UNIFY-06 参照，适配 MergedPlan）

```python
# Source 范式: server/workflows/nodes/ai/plan_generation.py:465 _render_plan_markdown
# 适配 MergedPlan schema (title/summary/execution_plan[]/compat_risks/api_contracts)
def _render_merged_plan_markdown(plan: dict[str, Any]) -> str:
    parts: list[str] = []
    if (title := str(plan.get("title", "")).strip()):
        parts.append(f"**{title}**")
    if (summary := str(plan.get("summary", "")).strip()):
        parts.append(summary)
    tasks = plan.get("execution_plan") or []
    if isinstance(tasks, list) and tasks:
        parts.append(f"**📋 执行计划（共 {len(tasks)} 项）**")
        # ... 逐任务 name/repository_name/coding_instruction（截断）
    risks = plan.get("compat_risks") or []
    if isinstance(risks, list) and risks:
        # lark_md 不支持列表 → 用 • 字面项目符号（跨客户端稳定）
        bullets = "\n".join(f"• {str(r).strip()}" for r in risks if str(r).strip())
        parts.append(f"**⚠️ 兼容风险**\n{bullets}")
    return "\n\n".join(p for p in parts if p)
```

### MCP delegate（UNIFY-03/04 参照终态映射）

```python
# Source 范式: server/workflows/nodes/ai/plan_research.py:501 _map_terminal
from delivery.models import PlanSessionStatus, PlanVersion
from services.plan_orchestration import (
    start_orchestration, build_orchestration_engine,
    adrive_plan_session_to_pause_or_terminal,
)
session = await start_orchestration(entrypoint="workflow", requirement_text=req, ...)
session = await adrive_plan_session_to_pause_or_terminal(build_orchestration_engine(), session)
if session.status == PlanSessionStatus.DONE:
    pv = await PlanVersion.objects.filter(id=session.current_plan_version).afirst()
    content = pv.content if pv and isinstance(pv.content, dict) else {}
    # → 映射回旧 MCP 响应字段 + acreate McpWorkItemTechnicalPlan/McpCodingPlan
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `ai_plan_generation`（LangChain 单 agent，verify_plan/submit_technical_plan 工具循环） | `ai_plan_research`（plan_orchestration 状态机：拆分→路由→召回→澄清→并行调研→融合） | v0.16.x（41-44 落地，94 收官） | 三入口统一产物口径；废弃单 agent 路径 |
| MCP 独立确定性 seam（`build_coding_plan` 按非空行切、`build_work_item_technical_plan` 仓库矩阵） | delegate plan_orchestration → canonical MergedPlan | Phase 94 | 口径收口；MCP 不再产分叉结构 |
| 澄清双轨（ToolResult marker / PlanSession.Clarification） | 单一来源 `delivery.Clarification` + `PlanSession`，marker 仅渲染信号 | 90/91 建模型，94 收敛 | 消除挂起二义 |

**Deprecated/outdated（Phase 94 处理后）:**
- `ai_plan_generation` 节点：deprecated（保留注册/代码，节点库隐藏，迁移指引引导用 `ai_plan_research`）。
- `planning_service.build_coding_plan` / `technical_plan_service.build_work_item_technical_plan` 作为「产方案的 seam」：被 delegate 取代（函数可保留作渲染/兼容 helper，不再产分叉方案结构）。
- 旧 `Mcp*` 持久化表的物理下线：**deferred**（CONTEXT Deferred，本里程碑只收口产物口径，保留落库兼容）。

## Project Constraints (from CLAUDE.md / 观测规范)

- **观测埋点（强制）:** 新增/改动 LLM 调用点必须赋 `call_source`（枚举见 LOGGING-SPEC §4.1）并上报请求/token/TTFT/上游错误码；新增请求入口纳入 QPS/错误率/时长；新增召回写 `RetrievalTrace`。MCP delegate 接入编排后，编排内部已有埋点；MCP View 入口本身已纳入既有请求统计（参照 93-00 豁免逻辑——只读/已统计入口无需新埋点，但 delegate 改变了调用形态，需确认 MCP→编排的 call_source 链路完整）。
- **事件分类:** 新增事件设 `category`（caller/sampling）+ `component`；deprecated 节点实例化 warning 用 `component`（建议 `workflow_node`）。
- **脱敏不可绕过:** 澄清正文/方案 markdown 推群前经 `redact_secrets_in_text`（`_send_clarify_card` 已做）；done markdown 渲染不 dump 含密原文。
- **绑定触发用户:** MCP delegate 建 session 须带 `created_by`（actor）；编排后台任务带 `initiated_by_user_id`。
- **async ORM:** 全程 `*_id` 标量 / `afirst` / `aexists`，绝不裸访问 lazy-FK（CR-01 类）。
- **INV-6 写入收口:** 澄清写入只经 `ClarificationService`；canonical 经 `PlanSessionService` / `PlanVersion` service；MCP 落库只经既有 acreate 入口。
- **不为「形式上是 langgraph」重写:** plan_orchestration 是自研状态机，本 phase 不改架构（REQUIREMENTS Out of Scope）。
- **观测代码 best-effort:** 绝不反噬业务（`except: pass` / warning）。

## Validation Architecture

> nyquist_validation = true（config.json）→ 本节适用。

### Test Framework
| Property | Value |
|----------|-------|
| Framework | 后端 `pytest>=9.0.2` + `pytest-asyncio` + `pytest-django`（`server/`）；前端 `vitest@^4`（`web/`） |
| Config file | `server/pyproject.toml`（pytest/mypy/ruff）；`web/vite.config.ts`（vitest） |
| Quick run command | `cd server && uv run pytest tests/workflows/test_template_loader.py -x` |
| Full suite command | `cd server && uv run pytest tests/workflows tests/mcp_tools tests/test_plan_clarification_answer_endpoint.py`；`cd web && pnpm vitest run` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| UNIFY-01 | 模板切到 ai_plan_research + 校验零 error | unit | `uv run pytest tests/workflows/test_template_loader.py -k technical_plan -x` | ✅（断言需同步：当前 field_not_found 红） |
| UNIFY-01 | 既有 ai_plan_generation 实例仍可注册/execute | unit | `uv run pytest tests/workflows/ -k "registry or node_schema"` | ✅ test_node_schema.py（需补 deprecated 仍注册断言） |
| UNIFY-02 | 节点库不含 ai_plan_generation；ai_plan_generation 仍注册 | unit | `pnpm vitest run node-sync`；`uv run pytest -k registry` | ✅ node-sync.test.ts / ❌ deprecated 注册守护 Wave 0 |
| UNIFY-03 | create_feishu_technical_plan delegate + 响应外形 + 落库 | integration | `uv run pytest tests/mcp_tools/ -k feishu_technical_plan` | ❓ 需核对/新建（响应键集合守护 Wave 0） |
| UNIFY-04 | create_coding_plan delegate + 响应 + 落库 | integration | `uv run pytest tests/mcp_tools/ -k coding_plan` | ❓ 需核对/新建 |
| UNIFY-05 | 对话澄清单一来源（marker 仅渲染、答经专路由续推） | integration | `uv run pytest tests/test_plan_clarification_answer_endpoint.py tests/test_chat_graph_clarification_interrupt.py` | ✅（需补「plan 澄清不写 ConversationIntentTrace」守护） |
| UNIFY-06 | done 渲染 plan_markdown 干净（不 dump 原文）+ 推群接线 | unit | `uv run pytest tests/workflows/ -k plan_research` | ✅ test_plan_research_node.py（需补 plan_markdown 渲染断言） |

### Sampling Rate
- **Per task commit:** 受改子集 `uv run pytest tests/workflows/test_template_loader.py tests/workflows/test_plan_research_node.py -x`
- **Per wave merge:** `uv run pytest tests/workflows tests/mcp_tools` + `pnpm vitest run`
- **Phase gate:** 全套绿 + `makemigrations --check` 干净 + `ruff format/check` + `mypy` + `vue-tsc --noEmit`，再 `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/workflows/test_template_loader.py` — 同步 `technical_plan_generation` 断言到 ai_plan_research（修当前 field_not_found 红）；补「ai_plan_research not legacy」断言（mirror code_generation 的 `ai_plan_generation not in node_types`）
- [ ] MCP 响应外形守护（`tests/mcp_tools/`）— `create_feishu_technical_plan` / `create_coding_plan` delegate 后响应键集合 snapshot + `McpWorkItemTechnicalPlan`/`McpCodingPlan` 落库断言
- [ ] deprecated 节点守护 — `ai_plan_generation` 仍 `@register_node`（既有实例可运行）但 NodePalette 不暴露
- [ ] UNIFY-05 守护 — plan 澄清答经专路由续推 PlanSession（不误入 ConversationIntentTrace 单题路径）
- [ ] `ai_plan_research` `plan_markdown` 输出字段渲染单测（UNIFY-06）+ fixture 重生成（node-sync 绿）

## Security Domain

> security_enforcement = true, ASVS level 1 → 本节适用。本 phase 为内部重构，无新认证/会话面；威胁集中在访问控制与输入处理的**回归不破坏**。

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | 无新登录面；MCP View 走既有 `McpToolView._begin` 鉴权 |
| V3 Session Management | no | 无新会话面 |
| V4 Access Control | yes | MCP delegate 须带 `created_by` actor；澄清答复 91-04 已有 owner gate（created_by_id + has_project_access，无 superuser bypass，404 隐藏存在性）——UNIFY-05 不得绕过 |
| V5 Input Validation | yes | `requirement_text` 半可信（chat/MCP 输入）；澄清 answers question_id 越界 400；MCP serializer 既有 max_length 校验保留 |
| V6 Cryptography | no | 无新加密；凭证仍经既有 Fernet/resolver |

### Known Threat Patterns for plan_orchestration unify

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| MCP delegate 漏带 actor → 越权召回 | Elevation | `start_orchestration(created_by=actor)`；召回 stage 对 None actor fail-closed 空召回 |
| 澄清答复跨用户/跨会话续推 | Elevation | 复用 91-04 owner gate（不在 MCP/新入口重造，沿用专路由） |
| marker 二义致答复写错路径（不续推/写错 trace） | Tampering | UNIFY-05 收敛单一来源 delivery.Clarification（见 Pitfall 4） |
| 方案 markdown 推群泄漏密文/原始上游响应 | Info Disclosure | `redact_secrets_in_text` 脱敏 + 不 dump LLM 原文（UNIFY-06） |
| MCP 响应映射意外暴露 canonical 内部字段 | Info Disclosure | 显式字段映射白名单（只暴露旧契约字段，不透传全 content 内部键） |

## Open Questions

1. **MCP delegate 的挂起态语义（UNIFY-03/04 关键决策）**
   - 已知：MCP 是单次同步响应、无 resume 通路；编排可能挂起 CLARIFYING（需澄清）/ RESEARCHING（容器在途）；`adrive` 在挂起点短路返回非终态 session。
   - 不清楚：MCP 调用方对「方案未就绪」期望什么？返回 `PARTIAL` + `session_id`（调用方轮询）？还是对 MCP 入口禁用澄清/调研挂起（policy 注入「带现有信息直接产方案」）？旧 seam 是确定性同步产出（无挂起），delegate 后引入了挂起可能性。
   - 推荐：plan-phase 决策。倾向「MCP delegate 用同步友好形态——若挂起则返回 `status=PARTIAL` + canonical `session_id` + 已有部分 content，调用方可后续经会话/工作流续推」；或注入跳过澄清的 policy 保 MCP 同步语义。需与 CONTEXT「产 canonical 同一口径」权衡。

2. **`create_coding_plan` 单仓 vs 编排多仓（UNIFY-04）**
   - 已知：`build_coding_plan` 是**单仓**确定性方案（repository_id 必填）；plan_orchestration 是**多仓**编排（execution_plan[] 跨仓）。
   - 不清楚：单仓 coding plan delegate 到多仓编排后，如何映射回单仓响应（`affected_files`/`steps`/`test_plan`）？是限定 `include_repos=[repository_id]` 让编排只跑单仓，还是取 canonical execution_plan 中该仓的子集？
   - 推荐：plan-phase 定映射策略（建议 `include_repos=[repository_id]` 约束编排单仓 + 从 content 提取该仓 task 映射回旧字段）。

3. **deprecated 标注的精确形式（UNIFY-02，CONTEXT Claude's Discretion）**
   - 推荐：类级 `deprecated: ClassVar[bool] = True` + docstring 顶「DEPRECATED」标记 + 实例化 warning 日志 + 迁移指引文档落点（建议 `docs/` 或节点 description 内联「请改用 ai_plan_research」）。具体由 plan-phase 定。

## Environment Availability

> 本 phase 为纯代码/配置/模板改动，无新增外部工具/服务/运行时依赖。**SKIPPED**（已有 Python/uv、Node/pnpm 工具链即满足；编排底座、飞书 IM、Clarification 模型均为既有仓内能力）。

## Sources

### Primary (HIGH confidence) — 本仓真实源码核对
- `server/workflows/templates/technical_plan_generation.json` / `code_generation.json` — 当前模板 vs 已切样板
- `server/workflows/nodes/ai/plan_generation.py` / `plan_research.py` — 旧/新节点端口、输出 schema、_map_terminal、渲染范式
- `server/services/plan_orchestration/{entrypoint,resume,answer_resume,ask_clarification,clarify_adapter,merged_plan,__init__}.py` — 共享 helper 签名
- `server/mcp_tools/{views.py,technical_plan_service.py,planning_service.py,serializers.py}` — MCP View/seam/响应结构
- `server/agents/tools/{plan_research_tools.py,clarification.py}` — chat 入口 + chat 单题 marker
- `server/orchestration/graph.py` — chat graph 澄清 marker 消费（_extract_pending_clarification / wait_clarification_node）
- `server/workflows/nodes/integrations/feishu_im_notify.py` — 推群卡片（markdown 组件）
- `server/workflows/templates/loader.py` / `server/tests/workflows/test_template_loader.py` — 模板校验 + 既有断言
- `web/src/components/workflow/sidebar/NodePalette.vue` — 前端节点库硬编码
- `.planning/phases/91-clarification-outlets-resume/91-04-SUMMARY.md` — 澄清单一来源出口面（runtime + 专路由）
- `.planning/STATE.md` — 既有失败基线（template_loader field_not_found）、底座 Decisions、约束

### Secondary (MEDIUM confidence)
- `.planning/config.json` — nyquist/security 开关
- `.planning/REQUIREMENTS.md` — UNIFY-01~06 措辞 + Out of Scope

### Tertiary (LOW confidence)
- 无（全部经源码验证）

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 当前 `test_template_loader` technical_plan_generation 红是 `plan_markdown` field_not_found（STATE 记录的 war-room 既有失败） | Pitfall 1 | 低——若红因不同，UNIFY-01 仍需对齐字段引用；定位以实跑为准 |
| A2 | `ai_plan_research.outputs.default.schema.plan` 为 `{"type":"object"}` 故 `plan.title`/`plan.summary` 下钻引用 validator 放行（code_generation 已生产验证） | Pitfall 1 | 低——code_generation.json 在用且 `test_acreate_accepts_valid_templates` 绿，已间接验证 |
| A3 | MCP delegate 挂起态需要新决策（旧 seam 同步无挂起，delegate 引入挂起可能） | Open Q1 | 中——若编排对 MCP 入口实际不会挂起（如禁澄清），则无需处理；需 plan-phase 确认 policy |
| A4 | `start_plan_research` 的 `CLARIFICATION_PENDING_MARKER` 当前不被 chat graph `_extract_pending_clarification` 捕获（按工具名过滤） | Pitfall 4 | 中——graph.py:551 按 `tc.name=="ask_clarification"` 过滤，start_plan_research 名不同；但需确认无其它消费路径致二义 |
| A5 | 旧 Mcp* 表字段需全保留（落库兼容），无字段删除 | Runtime State Inventory | 低——CONTEXT Deferred 明确「保留落库兼容」 |

## Metadata

**Confidence breakdown:**
- 复用底座/helper 接线: HIGH — 全部 helper 签名经源码核对，91-04 已证同源调用可行
- 模板切换 + 渲染: HIGH — code_generation.json 已是切换样板，渲染范式现成
- MCP delegate: MEDIUM — 接线模式清晰，但挂起态语义 + 单仓多仓映射需 plan-phase 决策（Open Q1/Q2）
- 澄清单一来源收敛: MEDIUM — 出口面（91-04）已就绪，但 marker 二义的精确消除点需 plan-phase 核对 chat 工具/graph 现状（Pitfall 4 / A4）
- deprecated/节点库: HIGH — 改动点明确（NodePalette.vue:88 + 节点 ClassVar + 不删/不注销）

**Research date:** 2026-06-27
**Valid until:** 2026-07-27（内部重构，依赖本仓代码状态；若 war-room 未提交在制品合入可能改变 test 基线）
