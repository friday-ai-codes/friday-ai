# Phase 109: 双脊柱合流（编排产出直连执行流 + 移除徒手创作路径） - Research

**Researched:** 2026-07-30
**Domain:** Django 领域模型投影 / LLM 工具 schema 收窄 / Vue 3 执行流入口 / 幂等与追溯
**Confidence:** HIGH（全部结论来自本仓源码 grep + 逐文件阅读；无外部依赖、无新包）

> 本文档所有事实性结论均标注 `[VERIFIED: 文件:行]`（本会话内实读代码）。推断性内容标 `[ASSUMED]` 并汇总在 §Assumptions Log。

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**编排产出直连执行流（SPINE-01）**
- **衔接方式取「投影」而非改写执行流**：把编排方案版本投影成执行侧对象（chat `CodingPlan`），复用 `create_coding_plan` 既有的执行半边（选仓 / 分支 / 确认编码 / 飞书导出）。理由：执行半边是 SPA 唯一编码入口且 MCP 执行链依赖其桥接行为，重写风险远高于投影。
- **投影时机取惰性**：用户在方案页显式点「进入编码」时投影，不在编排完成时预建（避免为未被采纳的方案批量建对象）。
- **幂等键绑定方案版本**（`plan_version_id` 或等价标识，researcher 确认实际字段）：同版本重复投影返回既有对象、不新建；方案版本更新后允许新建投影且**旧投影保留**（历史可查）。
- 执行流入口接**现行 §7 `execution_plan`**：v0.20.0 蓝图的 `derive_execution` 保证同 schema，合并后执行流无缝换源，深度由 v0.20.0 提供。本 phase 不等蓝图。

**移除徒手创作路径（SPINE-02，仅在 SPINE-01 成立后执行）**
- **拆分而非删除**：砍掉「由对话模型徒手编写方案正文」的创作半边，**保留**选仓 / 分支 / 确认编码 / 导出的执行半边。`create_coding_plan` 不整体删除（REQUIREMENTS 的 Out of Scope 已明确：实证它是 SPA 唯一编码入口，MCP 执行链亦依赖其桥接）。
- **MCP 桥接零回归**：MCP 执行链依赖 `create_coding_plan` 创建 chat `CodingPlan` 做桥接的行为**必须零回归**，须有端到端守护测试。
- **移除方式在 schema 层而非 prompt 层**：从工具 schema 移除创作入参/能力，使模型在结构上再也无法只凭对话生成方案正文；仅靠 prompt 约束不算达成 SPINE-02。
- **回归护栏先行**：SPA 与 MCP 两条编码链路的端到端守护测试**先绿再动刀**（这是 SPINE-01 → SPINE-02 顺序约束的具体落法）。

**草稿标注（RELY-01）**
- 草稿**保留但显式标注**「未经代码调研」，不静默移除（保留应急路径）；标注必须同时出现在**界面与飞书导出物**两侧。
- 标注载体是**数据层来源标志**（如 `provenance: orchestrated | draft`，命名 planner 定），界面与导出据此渲染，不靠文案硬编码——避免新增产出路径时漏标。
- **送编码防护**：草稿默认**不可**直接送编码；确需送出必须显式确认，且编码上下文携带「未经调研」标志（下游可据此判断）。

**幂等与追溯（SC-4）**
- 幂等用 **DB 唯一约束**（方案版本 → 编码计划）+ `get_or_create` 语义，并发安全；不靠应用层查重（并发下会重复）。
- 追溯链保留完整 `WorkItem → PlanVersion → CodingPlan → MR`（复用既有追溯基建），投影时写入关联。
- 方案版本更新后允许新建投影，旧投影保留（历史可查，不覆盖）。

### Claude's Discretion
- 投影 service 的落点与命名、唯一约束的具体字段组合、`provenance` 枚举的取值命名与迁移形态由 planner/executor 按代码库惯例定。
- 观测埋点按 LOGGING-SPEC 补齐（投影动作、草稿送编码的显式确认、schema 层移除后的调用尝试均需留痕）。
- 前端「进入编码」入口与草稿标注的具体位置由 UI-SPEC 定稿。

### Deferred Ideas (OUT OF SCOPE)
- 阶段流式输出、容器日志可见、阶段时间线 → Phase 110（复用 107 事件源）。
- 方案结构深度（DEPTH-01~05）→ 已移交 v0.20.0；`process_runtime` prompt/schema 冻结。
- 两套 CodingPlan 合表为 canonical → Future（REQUIREMENTS 已列）。
- 用追溯链自动生成弱标签把 golden set 推到 200+ → Future。
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SPINE-01 | 编排产出的技术方案可直接进入选目标仓 → 配置分支 → 确认编码流程，无需用户重新走一遍方案生成 | §4「执行流四步现状」证明四步全部挂在 chat `CodingPlan.id` 上；§3 给出可用幂等键 `ArtifactVersion.id`；§Pattern 1 给出投影 service 形状；§6 指出「进入编码」入口需新建（现无任何编排产出的可操作前端面） |
| SPINE-02 | 系统不再存在「由对话模型徒手编写方案正文」的产出路径 | §1 完整解剖 chat `@tool create_coding_plan` 的创作半边（`tech_plan` + `affected_files` 两个必填入参）与执行半边边界；§8 列全 schema 收窄的 11 处影响面（含两份重复的工具白名单）；**§1 纠正 CONTEXT 一处事实误判**：MCP 执行链并不调用该 chat 工具 |
| RELY-01 | 用户拿到的技术方案一定来自完整编排链路；仍提供草稿须显式标注「未经代码调研」 | §9 定位 `provenance` 唯一合理落点为 chat `CodingPlan`（界面与导出的共同瓶颈点）；§5 给出导出渲染函数精确落点；§9 给出既有 TextChoices 来源枚举先例 |
</phase_requirements>

---

## Summary

本 phase 的技术难度**远低于**其风险面，因为两件关键设施都已存在：其一，把「编排 canonical 产物 → 单仓编码方案」映射的先例已经在 `mcp_tools/orchestration_delegate.py::map_canonical_to_coding_plan` 落地并有六项守护测试；其二，SPA 执行流四步（选仓 / 配分支 / 确认编码 / 飞书导出）全部只依赖 chat `CodingPlan.id` 一个锚点，投影出一条 `CodingPlan` 记录即同时点亮四步。真正的工作量集中在三处：**（a）投影 service 与 DB 唯一约束**（现行去重是应用层 sha256 全表扫描，并发不安全，是净新增工作）；**（b）新建前端「进入编码」入口**（编排产出目前在 SPA 里没有任何可操作呈现面）；**（c）SPINE-02 的 schema 收窄影响面**（11 处，含两份彼此重复的工具白名单和 5 个断言 prompt 文案的测试文件）。

调研过程纠正了 CONTEXT 与用户任务书中的**三处事实误判**，planner 必须以本文档为准：（1）代码库里存在**两个同名但完全无关**的 `create_coding_plan`——chat `@tool`（SPA，SPINE-02 的靶子）与 MCP HTTP 端点（**早在 Phase 94 就已 delegate 到统一编排**）；（2）MCP 执行链的 chat `CodingPlan` 桥接由 `mcp_tools/execution_service.py::_create_bridge_session` 用裸 ORM 自建，**从不调用那个 chat 工具**——因此 SPINE-02 对 MCP 的耦合面是零，"MCP 桥接零回归"要保的是 `CodingPlan`/`CodingSession` 两个模型的字段形状不变，而非工具行为不变；（3）`TechnicalPlan` / `PlanVersion` 两个模型**已不存在**，Chassis v2 把它们泛化成了 `delivery.Artifact` / `delivery.ArtifactVersion`，幂等键应取 `ArtifactVersion.id`（辅以 `content_hash`）。

第三个必须提前知晓的约束：chat `CodingPlan.conversation` 是 **NOT NULL 外键**。chat 入口的编排会话带 `conversation_id` 软引用可直接复用；但 workflow / MCP 入口的编排会话没有 conversation，投影时必须建合成会话（`_create_bridge_session` 已有此先例）。这直接决定投影 service 的签名与 wave 划分。

**Primary recommendation:** 新建 `server/chat/plan_projection_service.py`（或 `delivery/services/plan_projection.py`），以 `ArtifactVersion.id` 为幂等键、经 `CodingPlan` 上新增的 `source_artifact_version_id` 列 + 局部唯一约束 + `aget_or_create` 落地投影；`tech_plan` 正文用 `render_merged_plan_markdown(content)`、`affected_files` 从 §7 `execution_plan[].files[]` 全仓聚合、`recommended_repository_ids` 从 `execution_plan[].repository_id` 去重取；同一迁移里给 `CodingPlan` 加 `provenance` TextChoices 字段（默认 `draft` 以兼容存量），界面与飞书导出各读一处。SPINE-02 只改 chat `@tool` 的 `parameters` schema + 函数签名，MCP 侧一行不碰。

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 编排产物 → 执行侧对象投影 | API / Backend（service 层） | Database（唯一约束保幂等） | 幂等语义必须由 DB 约束兜底（CONTEXT 明确否决应用层查重）；service 层做映射与关联写入 |
| 幂等键与并发安全 | Database | — | `UniqueConstraint` + `aget_or_create` 的 `IntegrityError` 分支；应用层 `filter().afirst()` 在并发下必然重复 |
| §7 `execution_plan` → `tech_plan`/`affected_files` 映射 | API / Backend（纯函数） | — | 纯映射无 IO，可单测；`map_canonical_to_coding_plan` 已是单仓版先例 |
| 「进入编码」入口 | Frontend（Vue 组件 + store action） | API（新投影端点） | 惰性投影 = 前端点击触发后端 POST；前端不得自行拼 `CodingPlan` |
| 执行流四步（选仓/分支/确认/导出） | API / Backend（既有端点，零改动） | Frontend（`TechPlanCard.vue` 复用） | 四步端点已全部挂 `CodingPlan.id`，投影后天然可用 |
| 草稿来源标志（provenance） | Database（字段） | Frontend + Backend 渲染器（各读一处） | 数据层单一真源，界面与导出各自消费，避免文案硬编码漏标 |
| 送编码防护（草稿需显式确认） | API / Backend（fan-out 端点校验） | Frontend（确认弹层） | fail-closed 必须在服务端；前端确认只是 UX，绕过前端也不能送出 |
| LLM 工具能力收窄 | API / Backend（`@tool` parameters schema） | — | schema 是 LLM 可见能力的唯一定义处；prompt 只是软约束（CONTEXT 明确否决 prompt 层方案） |

---

## Standard Stack

### Core（全部已在仓内，本 phase 零新增依赖）

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `django` | >=5.1 | `UniqueConstraint` / `aget_or_create` / additive migration | 项目既有栈 `[VERIFIED: server/pyproject.toml]` |
| `asgiref` (`sync_to_async`) | 随 Django | async 上下文访问 ORM 的桥 | 项目 ARCHITECTURE 明文约束：async 里访问 ORM 必须过 `sync_to_async` |
| `structlog` | 既有 | 结构化 kv 日志 | `.cursor/rules/observability-logging.mdc` 强制 |
| `jsonschema` | 既有 | §7 `execution_plan` 校验 | `workflows/schemas/technical_plan.py` 已用 `[VERIFIED: server/workflows/schemas/technical_plan.py:10,219]` |
| `vue` | ^3.5.26 | 「进入编码」入口组件 | 既有前端栈 |
| `@tanstack/vue-query` | 既有 | 投影端点调用与缓存失效 | `ArtifactTimeline.vue` 已用同模式 `[VERIFIED: web/src/components/delivery/ArtifactTimeline.vue:6,41]` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `CodingPlan` 上加 `source_artifact_version_id` 列 + 唯一约束 | 独立映射表 `PlanProjection(artifact_version, coding_plan)` | 独立表更"干净"但要多一次 join 才能从 plan 反查来源，且 `CodingPlan` 的界面/导出/runtime 三处消费者都得改查询；加列方案 additive、消费者零改动。**推荐加列** |
| 复用 `render_merged_plan_markdown` 产 `tech_plan` | 新写一个 GFM 版渲染器 | 既有函数是 lark_md 方言（用 `•` 而非 `- ` 列表，`[VERIFIED: server/services/process_runtime/render.py:16-18]`），而 `TechPlanCard` 用 markdown-it 渲染。`•` 在 GFM 下会显示为普通字符（可读但不成列表）。**先复用，若 UI-SPEC 要求真列表则加一个 `flavor` 参数，不要 fork 出第二个渲染器** |
| `provenance` 加在 chat `CodingPlan` | 加在 `delivery.Artifact` | 草稿路径（徒手/应急）根本不产 `Artifact`，加在 `Artifact` 上无法标注草稿。**必须加在 `CodingPlan`** |

**Installation:** 无新增包。

## Package Legitimacy Audit

**本 phase 不安装任何外部包** —— 全部改动落在既有 Django app / Vue 组件与一次 additive 迁移上。

| Package | Registry | 结论 |
|---------|----------|------|
| （无） | — | 无需 slopcheck / 注册表校验 |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

---

## 1. `create_coding_plan` 完整解剖（调查点 1）

### 1.1 ⚠️ 名称碰撞：仓内存在两个无关的 `create_coding_plan`

这是本次调研最重要的纠正。CONTEXT 与任务书把两者混为一谈，planner 若按混淆版理解会把 SPINE-02 的爆炸半径估大数倍。

| # | 实体 | 位置 | 面向 | 产物 | 与编排的关系 |
|---|------|------|------|------|--------------|
| **A** | chat `@tool create_coding_plan` | `server/agents/tools/coding_tools.py:35-292` `[VERIFIED]` | 对话 LLM（SPA） | chat `CodingPlan` | **无**——正文由 LLM 徒手写入 `tech_plan` 入参 |
| **B** | MCP HTTP 端点 `POST /api/mcp/tools/create_coding_plan/` | `server/mcp_tools/views.py:1842-1997`（`CreateCodingPlanView`）`[VERIFIED]` | 外部 MCP 客户端（Cursor 等） | `McpCodingPlan` + `McpCodingPlanVersion` | **已 delegate 到统一编排**（Phase 94 UNIFY-04）`[VERIFIED: views.py:1905 delegate_process_runtime(...)]` |

**SPINE-02 的靶子只有 A。** B 已经是"编排产出直连"的既成事实，且它就是 SPINE-01 该照抄的先例。

### 1.2 实体 A：chat `@tool create_coding_plan` 逐项解剖

**注册方式**：`@tool` 装饰器 + **裸 dict JSON Schema**（不是 pydantic）`[VERIFIED: coding_tools.py:35-111 的 parameters={...}；base.py:90-96 tool() 签名，parameters: dict[str, Any] | None]`。
> ⚠️ CONTEXT 的 "工具 schema 用 pydantic" 只对部分工具成立（`agents/tools/schemas/` 下有 5 个 pydantic input 模型，`[VERIFIED: ls server/agents/tools/schemas/ → api_tools.py, delivery_knowledge.py, find_related_code.py, repository_relevance.py, search_repository_code.py]`），`create_coding_plan` **不在其中**。收窄它只需改一个 dict + 一个函数签名，比 pydantic 路径更简单。

**入参 schema（5 个）`[VERIFIED: coding_tools.py:51-110]`：**

| 入参 | required | 归属半边 | 说明 |
|------|----------|----------|------|
| `space_id` | ✅ | 中立 | chat_runner 自动注入 |
| `conversation_id` | ✅ | 中立 | chat_runner 自动注入 |
| **`tech_plan`** | ✅ | **🔴 创作** | "Markdown 格式的技术方案，包含影响文件列表和分步实现步骤" |
| **`affected_files`** | ✅ | **🔴 创作** | `[{file_path, change_type: add\|modify\|delete}]` |
| `repository_id` | ❌ | 🟢 执行（弱） | 仅合并进 `recommended_repository_ids` 置顶，**不再建 session** |
| `recommended_repository_ids` | ❌ | 🟢 执行 | 不传则从最近一条 `RepositoryRoutingTrace` 取 `selected_by_user_final=True` |

**创作/执行边界结论**：创作半边 = `tech_plan` + `affected_files` 两个必填入参；这两个删掉，LLM 结构上再无法产出方案正文。执行半边在本工具内其实**只剩推荐仓库解析**——真正的选仓/分支/确认/导出全在 HTTP 端点里（见 §4），不在工具内。这是个好消息：SPINE-02 的 schema 收窄不会连带破坏执行流。

**内部做的 6 件事 `[VERIFIED: coding_tools.py:138-292]`：**
1. `Space.objects.aget(space_id)` — 不存在返回失败（:149-155）
2. `repository_id` 若传：校验存在 + 属于该 space（:157-172）
3. `Conversation.objects.aget(conversation_id)` — 不存在返回失败（:174-180）
4. `_normalize_affected_files` — 旧 `path` 键迁移到 `file_path`，缺 `change_type` 回退 `modify`（:16-32, :183）
5. 解析 `recommended_repository_ids`：`explicit` / `trace_inferred` / `empty` / `primary_repo` 四种来源（:185-248）
6. `CodingPlan.aget_or_create_for_conversation(...)` + 覆盖写 `recommended_repository_ids`（:251-262）

**创建的 DB 对象**：**仅 chat `CodingPlan` 一条**。明确**不创建** `CodingSession` `[VERIFIED: coding_tools.py:121-124 docstring + tests/test_coding_tools.py:68-84 断言调用前后 CodingSession 计数不变]`；也**不再**投影 delivery `TechnicalPlan`（Chassis v2 P2 已删该 eager 投影，`[VERIFIED: coding_tools.py:264-266 注释]`）。

**返回 payload（10 键）`[VERIFIED: coding_tools.py:276-292]`：**
`coding_plan_id` / `coding_session_id`(恒 None) / `session_id`(恒 None，兼容 alias) / `repository_id` / `repository_name` / `status`(恒 `"plan_only"`) / `branch_name`(恒 `""`) / `recommended_repository_ids` / `recommended_repositories` / `recommended_source` / `message`

**副作用**：`aget_or_create_for_conversation` 内部调 `knowledge.ingestion.aschedule_ingestion("coding_plan", ...)` 入统一知识库 `[VERIFIED: chat/models.py:317-321]`。投影新建 `CodingPlan` 时会走同一路径——planner 需注意投影会产生知识库摄取（这是**期望行为**，不必抑制）。

### 1.3 实体 A 的调用方全量清单

| # | 调用方 | 位置 | 依赖它的哪部分能力 | SPINE-02 影响 |
|---|--------|------|---------------------|---------------|
| 1 | **chat LLM 工具白名单（运行时）** | `server/agents/chat_runner.py:105`（`_INDEXED_TOOL_NAMES`）`[VERIFIED]` | 挂载工具让 LLM 可调 | schema 收窄后仍挂载（执行半边保留） |
| 2 | **chat 工具白名单（另一份！）** | `server/chat/conversation_service.py:430`（`_get_tool_names` 的 `full_tools`）`[VERIFIED: :414-442]` | 同上 | ⚠️ **两份白名单并存且内容不同**，改动需同步核对 |
| 3 | **system prompt `_CODING_GUIDANCE`** | `server/chat/conversation_service.py:216-247`（:219/:222/:223/:225/:229/:233/:236/:241/:244 共 9 处提名）`[VERIFIED]` | 教 LLM 何时调、怎么调 | 必须改文案（"生成结构化技术方案" → "从编排产物投影"） |
| 4 | **编码请求硬 gate hint** | `server/chat/conversation_service.py:405-410`（:409 "上述步骤完成前不允许调 create_coding_plan"）`[VERIFIED]` | 前置约束提示 | 需同步改 |
| 5 | **意图路由文案** | `server/agents/intent_router.py:188` `[VERIFIED]` | 描述 high 置信场景用途 | 文案更新 |
| 6 | **`analyze_repository_relevance` 工具描述** | `server/agents/tools/repository_relevance.py:50` `[VERIFIED]` | 描述下游衔接 | 文案更新 |
| 7 | **`deep_analysis` 工具描述** | `server/agents/tools/chat_tools.py:930` `[VERIFIED]` | 描述 metadata 复用 | 文案更新 |
| 8 | **项目上下文行** | `server/chat/config.py:73` `[VERIFIED]` | "单个零散需求 → create_coding_plan" | 文案更新 |
| 9 | **飞书 bot 卡片工具名映射** | `server/feishu/cards/bot_cards.py:15`（`"create_coding_plan": "📝 生成编码方案"`）`[VERIFIED]` | 卡片上展示中文工具名 | 标签可能需改 |
| 10 | **前端工具标签/分组/卡片** | `web/src/composables/useToolDisplay.ts:47,164`；`web/src/components/chat/ChatMessageBubble.vue:499,754,758-856,1139-1151` `[VERIFIED]` | `TechPlanCard` 的渲染触发 + `codingPlanData` 解析 | 若工具不再返回 `tech_plan`，`codingPlanData.techPlan` 需改从 runtime 取 |
| 11 | **skills / MCP 包 / 文档** | `skills/skills/friday-code/SKILL.md`、`task/assets/skills/friday-code/SKILL.md`、`mcp/src/tools.ts`、`mcp/README.md`、`docs/integrations/mcp.md`、`docs/guide/friday-codebase-agent.md` `[VERIFIED: rg 命中]` | 文档与 MCP npm 包工具清单 | ⚠️ `mcp/src/tools.ts` 指的是**实体 B**（不改）；SKILL.md 需核对指哪个 |

**❗ 关键否定结论**：`server/mcp_tools/` 下**没有任何代码 import 或调用** `agents.tools.coding_tools.create_coding_plan` `[VERIFIED: rg -n "create_coding_plan" server --glob '!server/tests/**' 全量结果中，mcp_tools 仅 views.py:1843 tool_name 字符串、urls.py:51 路由、serializers.py:209/757 契约，无一处 import agents.tools.coding_tools]`。

### 1.4 实体 B：MCP HTTP 端点（SPINE-01 的现成先例）

**这条链已经完整实现了「编排产出 → 编码方案」，值得逐行照抄：**

```
POST /api/mcp/tools/create_coding_plan/  (views.py:1842)
  ├─ 解析 repository_id / branch / requirement / analysis_id
  ├─ actor 解析（request.user，非真实用户 → None，召回 fail-closed）  :1880-1887
  ├─ delegate_process_runtime(requirement_text, work_item=None,
  │      include_repos=[repository_id], created_by=actor,
  │      extra_evidence=[...])                                        :1905-1911
  │    └─ orchestration_delegate.py:120
  │         start_orchestration(entrypoint="workflow", ...)
  │         build_orchestration_engine(skip_clarification=True)
  │         adrive_convergence_session_to_pause_or_terminal(...)
  │         → DelegateResult{session, status: completed|partial|failed,
  │                          content(§7 MergedPlan), plan_version_id, markdown}
  ├─ map_canonical_to_coding_plan(content, repository, branch, requirement)  :1919
  │    └─ orchestration_delegate.py:250-324（纯函数，见 §3.3）
  ├─ McpCodingPlan.objects.acreate(...) + McpCodingPlanVersion.objects.acreate(
  │      plan_body = content or plan_payload)                        :1932-1953
  └─ 响应 10 键（旧键全保留 + session_id + status）                     :1964-1975
```

`[VERIFIED: server/mcp_tools/views.py:1842-1997 + server/mcp_tools/orchestration_delegate.py 全文]`

**守护测试已就位**：`server/tests/mcp_tools/test_create_coding_plan_delegate.py`（6 组守护：单仓约束+actor 透传 / canonical 字段映射 / 响应键 snapshot / 落库兼容 / partial 挂起 / 空 content 降级）`[VERIFIED: 全文 371 行]`。

---

## 2. chat `CodingPlan` 模型与 MCP 桥接点（调查点 2）

### 2.1 字段全表 `[VERIFIED: server/chat/models.py:212-338]`

| 字段 | 类型 | 备注 |
|------|------|------|
| `id` | UUID PK | |
| `conversation` | FK → `chat.Conversation`, CASCADE, **NOT NULL** | ⚠️ 投影必须有 conversation |
| `title` | CharField(200), blank, default `""` | 工具恒传 `""`（:255） |
| `tech_plan` | TextField | 方案正文 Markdown |
| `affected_files` | JSONField(list) | `[{file_path, change_type}]` |
| `feishu_doc_token` | CharField(64), blank | 导出后回填 |
| `feishu_doc_url` | CharField(500), blank | 导出后回填 |
| `recommended_repository_ids` | JSONField(list), blank | `[str(UUID), ...]`，fan-out 用 |
| `created_at` / `updated_at` | auto | |

**Meta `[VERIFIED: :268-275]`**：`db_table="coding_plans"`，`ordering=["-created_at"]`，`indexes=[Index(["conversation", "-created_at"])]`。
**❗ 没有任何 `UniqueConstraint`。** SC-4 要求的 DB 唯一约束是净新增。

**方法（模型层唯二业务方法）：**
- `aget_or_create_for_conversation(conversation, tech_plan, affected_files, title="")` `[VERIFIED: :281-322]` — **应用层去重**：`async for existing in cls.objects.filter(conversation=conversation).aiterator()` 逐条 Python 里算 `sha256(existing.tech_plan)` 比对。O(n) 全扫 + n 次哈希，且**无锁、并发下必然重复插入**——正是 CONTEXT 点名要淘汰的模式。
- `aupdate_plan(tech_plan, affected_files)` `[VERIFIED: :324-338]` — 原子更新两字段 + 重新摄取知识库。

### 2.2 迁移历史（与 `CodingPlan` 相关）`[VERIFIED: ls server/chat/migrations/]`

| 迁移 | 内容 |
|------|------|
| `0012_codingplan_and_session_fk.py` | 建 `CodingPlan` + `CodingSession.coding_plan` FK（nullable 过渡） |
| `0013_codingsession_unique_active_plan_repo.py` | `CodingSession` 的**条件唯一约束**（见 §10.2，直接可抄的先例） |
| `0015_codingplan_recommended_repos.py` | 加 `recommended_repository_ids` |
| `0022_codingplan_canonical_plan_id.py` | 曾加 `canonical_plan_id` 软链 |
| `0031_remove_codingplan_canonical_plan_id.py` | **又删掉了**（Chassis v2 P2 解耦 chat↔delivery） |
| 最新 | `0032_repositoryroutingtrace_degrade_reason.py`（Phase 107 落的） |

> ⚠️ **`0022` → `0031` 是一条重要的历史教训**：曾经有过一个把 chat `CodingPlan` 软链到 delivery 方案产物的字段，被显式删除以解耦两条脊柱。本 phase 要重新加回一个 `source_artifact_version_id` 软引用，planner 应在迁移与代码注释里**说明与 `canonical_plan_id` 的差异**（此次是"投影来源留痕 + 幂等键"，不是"双向耦合的 canonical 软链"），否则未来会被当成重复的历史包袱再删一次。

### 2.3 与 `mcp_tools.McpCodingPlan` 的关系与桥接点

两者**没有任何外键或字段级关联** `[VERIFIED: server/mcp_tools/models.py:59-160 无 chat 相关 FK]`。桥接发生在**执行时**，且方式是裸 ORM：

```python
# server/mcp_tools/execution_service.py:86-127  [VERIFIED]
async def _create_bridge_session(*, project, plan: McpCodingPlan,
                                 version: McpCodingPlanVersion,
                                 branch_name, created_by=None):
    tech_plan = _plan_body_to_markdown(version)      # McpCodingPlanVersion.plan_body → md
    affected_files = _affected_files_for_chat(version)
    @sync_to_async
    def _create():
        with transaction.atomic():
            conversation = Conversation.objects.create(     # ← 合成会话
                space=project, title=f"MCP execution: {plan.title}"[:200],
                status=Conversation.Status.RUNNING, created_by=created_by)
            chat_plan = CodingPlan.objects.create(          # ← 裸 ORM，不走工具
                conversation=conversation, title=plan.title[:200],
                tech_plan=tech_plan, affected_files=affected_files,
                recommended_repository_ids=[str(plan.repository_id)])
            coding_session = CodingSession.objects.create(
                conversation=conversation, coding_plan=chat_plan,
                repository=plan.repository, tech_plan=tech_plan,
                affected_files=affected_files, branch_name=branch_name,
                status=CodingSession.Status.DRAFT)
            return conversation, chat_plan, coding_session
    return await _create()
```

**MCP 执行链具体依赖 chat 侧的是什么（这才是"零回归"要保的东西）：**
1. `Conversation(space, title, status, created_by)` 可构造 `[VERIFIED: :103-107]`
2. `CodingPlan(conversation, title, tech_plan, affected_files, recommended_repository_ids)` 可构造 `[VERIFIED: :109-115]`
3. `CodingSession(conversation, coding_plan, repository, tech_plan, affected_files, branch_name, status)` 可构造 `[VERIFIED: :116-124]`
4. `chat.coding_session_service.dispatch_coding_task` 与 `chat.branch_service.{generate_default_branch_name, validate_branch_name}` 可 import `[VERIFIED: execution_service.py:14-16]`
5. 反向读：`CodingSession.diff_summary` / `.status` / `.error_message` / `.subagent_session_id` 用于刷新 trace `[VERIFIED: :268-312]`

⇒ **SPINE-02 只要不改这 5 项，MCP 桥接就是零回归。** 若给 `CodingPlan` 加 `provenance` 字段，**必须给 default 值**（否则 `_create_bridge_session` 的裸 `objects.create()` 会因缺必填字段而崩）——这是最容易踩的一脚。

---

## 3. 编排方案版本的标识与 §7 `execution_plan`（调查点 3）

### 3.1 ⚠️ `TechnicalPlan` / `PlanVersion` 模型已不存在

`[VERIFIED: cat server/delivery/models/__init__.py 全量导出清单中无 TechnicalPlan / PlanVersion]`

Chassis v2 · P1/P2 把方案专属模型泛化为 type 化的通用交付物 `[VERIFIED: server/delivery/models/artifact.py:1-17 docstring "把'演进中的交付物'从方案专用（TechnicalPlan/PlanVersion）泛化为 type 化的一等对象"]`：

| 旧名（文档/CONTEXT 里的说法） | 实际模型 | db_table |
|------------------------------|----------|----------|
| `TechnicalPlan` | `delivery.Artifact`（`artifact_type="technical_plan"`） | `delivery_artifact` |
| `PlanVersion` | `delivery.ArtifactVersion` | `delivery_artifact_version` |
| `PlanSession` | `delivery.ConvergenceSession` | `delivery_convergence_session` |

### 3.2 四者的实际关系

```
delivery.WorkItem  (nullable — chat 自然语言需求 work_item=None，INV-2)
   │ SET_NULL
   ├──────────────────────────────┐
   ▼                              ▼
ConvergenceSession           Artifact  (artifact_type="technical_plan", status=draft)
  process_type="technical_plan"   │ current_version (FK, nullable, 循环 FK)
  entrypoint=workflow|chat|mcp|…  ▼
  status=created|running|          ArtifactVersion
    waiting_clarification|            version_no          (unique_together(artifact, version_no))
    waiting_event|done|failed         content   ← §7 MergedPlan 真身
  current_stage (stage graph key)     content_hash (sha256 of canonical json)
  stage_state (JSON 袋)               supersedes (self FK)
  conversation_id (UUID 软引用)       produced_by_session_id  (CharField 软引用 → ConvergenceSession.id)
  node_execution_id (UUID 软引用)     produced_by_ref  ("technical_plan.merge.completed")
  current_artifact_version ──────────▶ approval_status
      (FK → ArtifactVersion, SET_NULL)
```
`[VERIFIED: server/delivery/models/convergence_session.py:51-152 + server/delivery/models/artifact.py:45-145]`

### 3.3 可用作幂等键的字段 — 推荐结论

| 候选 | 类型 | 唯一性 | 评价 |
|------|------|--------|------|
| **`ArtifactVersion.id`** | UUID PK | 绝对唯一 | ✅ **推荐**。天然稳定、语义就是"这一版方案"；`ConvergenceSession.current_artifact_version_id` 一步可取；`start_plan_research` 已把它作为 `artifact_version_id` 返回给 LLM `[VERIFIED: plan_research_tools.py:283-289]` |
| `ArtifactVersion.content_hash` | CharField(64), indexed | 跨 artifact 不唯一 | 🟡 辅助用：可做"内容真的变了吗"的二次判据，不宜单独作键 |
| `(Artifact.id, version_no)` | 复合 | `unique_together` `[VERIFIED: artifact.py:138]` | 🟡 等价于 `ArtifactVersion.id` 但要两列，无收益 |
| `ConvergenceSession.id` | UUID PK | 唯一 | ❌ **不可用作幂等键**：一个 session 可产多版（improve 重跑），"同版本重复投影返回既有对象"的语义会失效 |

**⚠️ 一个反直觉的实现细节**：`ArchitectMergeAdapter._handle_pass` 每次融合通过都调 `ArtifactService().create(...)` 而**不是** `add_version(...)` `[VERIFIED: server/services/process_runtime/architect_merge_adapter.py:252-259]`。意味着**每次编排跑完都新建一个 `Artifact` + 首版 `v1`**，`version_no` 恒为 1，版本链（`supersedes`）在 technical_plan 这条流程上实际未被使用。这对本 phase 是**好事**（`ArtifactVersion.id` 每次都变 ⇒ "方案版本更新后允许新建投影且旧投影保留"天然成立），但 planner 不要在计划里写"取 artifact 的最新 version_no"这类假设。

### 3.4 §7 `execution_plan` 的实际 schema

**定义处**：`server/services/process_runtime/merged_plan.py:31-59` 声明 §7 MergedPlan 形状，`execution_plan` 子结构**复用** `workflows.schemas.technical_plan.validate_technical_plan` `[VERIFIED]`。

**MergedPlan 顶层 9 字段 `[VERIFIED: merged_plan.py:31-41]`：**
`title`(必填) / `summary`(必填) / `api_contracts[]` / `dependency_dag{}` / `data_migrations[]` / `compat_risks[]` / `release_order[]` / `rollback_plan{}` / `execution_plan[]`(必填非空)

**`execution_plan[]` 单项 schema `[VERIFIED: server/workflows/schemas/technical_plan.py:96-178]`：**

| 键 | 类型 | required |
|----|------|----------|
| `id` | string | ✅ |
| `name` | string | ✅ |
| `repository_id` | string | ✅ |
| `repository_name` | string | ✅ |
| `branch_strategy` | enum `feature\|hotfix\|release` | ✅ |
| `description` | string | ❌ |
| `coding_instruction` | string | ❌ |
| **`files[]`** | `[{path, action: create\|modify\|delete, description?}]` | ❌（`path`/`action` 在项内必填） |
| `dependencies[]` | string[] (task ids) | ❌ |
| `estimated_hours` | number ≥0 | ❌ |
| `priority` | integer ≥1 | ❌ |

**产出位置**：`ArchitectMergeAdapter` 融合通过时经 `ArtifactService.create(ARTIFACT_TYPE_TECHNICAL_PLAN, merged, ...)` 落成 `ArtifactVersion.content` `[VERIFIED: architect_merge_adapter.py:239-286]`；随后发 `technical_plan.merge.completed` 事件并把 `artifact_version_id` 塞进 payload `[VERIFIED: :269-271 + event_taxonomy.py:64]`。

**⚠️ 映射时的 schema 落差（`affected_files` 键名不一致）**：

| §7 `execution_plan[].files[]` | chat `CodingPlan.affected_files[]` |
|-------------------------------|-------------------------------------|
| `path` | `file_path` |
| `action`: `create` / `modify` / `delete` | `change_type`: **`add`** / `modify` / `delete` |

⇒ 投影映射必须做 `path→file_path` 与 **`create→add`** 两处转换。既有 `_normalize_affected_files` 只做前者、不做后者 `[VERIFIED: coding_tools.py:16-32]`；而 `TechPlanCard` 只是原样显示 `change_type` `[VERIFIED: TechPlanCard.vue:404]`，所以漏转不会崩、只会显示成 `create`——**是个静默漂移，测试必须显式断言**。

**已有的可复用渲染/映射 helper：**
- `render_merged_plan_markdown(content) -> str` `[VERIFIED: server/services/process_runtime/render.py:28]` — §7 → lark_md 正文；纯函数、fail-safe（非 dict 返 `""`）；只读结构化字段不 dump LLM 原文（脱敏纵深）。**注意是 lark_md 方言，用 `•` 而非 `- `**（:16-18）。
- `map_canonical_to_coding_plan(content, repository, branch, requirement) -> dict` `[VERIFIED: orchestration_delegate.py:250-324]` — **单仓**版映射：从 `execution_plan` 里筛 `repository_id` 匹配的首个 task，产 `{title, repository_id, repository_name, branch, requirement, affected_files(str[]), steps, test_plan, risks}`。注意它的 `affected_files` 是**字符串数组**（不是 chat 的 dict 数组），不能直接喂 chat `CodingPlan`。多仓投影需新写聚合映射（可参考其防御性风格）。

---

## 4. 执行流四步现状（调查点 4）

**结论：四步全部只依赖 chat `CodingPlan.id`，投影出一条记录即四步全通。**

| 步骤 | 前端入口 | 后端端点 | 挂在 `CodingPlan` 上？ |
|------|----------|----------|------------------------|
| ① 选目标仓 | `TechPlanCard.vue` 内嵌 `RepoMultiSelector`（创建态）/ 追加 Dialog `[VERIFIED: TechPlanCard.vue:472-513, 655-701]` | — （纯前端选择） | ✅ 依赖 `codingPlanId` prop（:101-103 `showInlineSelector`） |
| ② 配置分支 | `branch-template-input` + `target-branch-input`（默认 `develop`）`[VERIFIED: TechPlanCard.vue:477-499]` | — | ✅ 随 ① 一起提交 |
| ③ 确认编码 | `handleMultiConfirm` → `chatStore.submitRepoMultiSelector` `[VERIFIED: TechPlanCard.vue:135-165; web/src/stores/chat.ts:2559]` | `POST /api/chat/coding-plans/{plan_id}/sessions/` → `CodingPlanSessionsBatchCreateView` → `create_sessions_for_plan` `[VERIFIED: server/chat/urls.py:167-169; views.py:2573-2668; coding_session_service.py]` | ✅ **URL 路径参数就是 plan_id** |
| ③b 单仓 legacy 确认 | `handleConfirm` emit `confirm` （`codingPlanId` 未提供时）`[VERIFIED: TechPlanCard.vue:294-297, 516-579]` | `POST /api/chat/coding-sessions/{id}/confirm/` → `CodingSessionConfirmView` `[VERIFIED: views.py:1919]` | 经 `CodingSession.coding_plan` |
| ④ 飞书导出 | `ExportConfirmDialog mode="coding_plan"` `[VERIFIED: TechPlanCard.vue:704-713; ExportConfirmDialog.vue:27,56]` | `POST /api/chat/coding-plans/{coding_plan_id}/export-to-feishu/` → `ExportCodingPlanToFeishuView` `[VERIFIED: urls.py:173-175; views.py:1820-1911]` | ✅ **URL 路径参数就是 plan_id** |

**权限门（四处一致的 owner gate 模式）`[VERIFIED: views.py:2560-2567, 2617-2642, 1850-1860]`：**
经 `plan.conversation.created_by_id != user.id` → **404**（不是 403，不泄漏存在性）；用 `created_by_id` 标量避免 async 惰性 FK；**无 superuser bypass**。投影端点必须照抄这个门。

**投影后能否直接复用？** ✅ 能，前提是三件事：
1. `CodingPlan.conversation` 有值（NOT NULL）；
2. `recommended_repository_ids` 填了（否则 `RepoMultiSelector` 的推荐高亮为空，用户得从全空间仓库里手挑，体验退化）；
3. 前端能拿到 `codingPlanId`。**这一点目前有一条现成通路**：`activeCodingPlan` 来自 conversation runtime 的 `runtime.coding_plan` `[VERIFIED: web/src/stores/chat.ts:1156]`，其后端序列化器 `ConversationRuntimeCodingPlanSerializer` 的 docstring 明确是"对话内**最近** CodingPlan + 每仓 session 状态" `[VERIFIED: server/chat/serializers.py:420-425]`。⇒ **在 chat 会话内投影出的 `CodingPlan` 会自动成为 `activeCodingPlan`，无需新 API 就能被前端拿到。** 但渲染 `TechPlanCard` 的**触发条件**目前绑在 `create_coding_plan` 工具 part 上（见 §6），这才是要新建的部分。

---

## 5. 飞书导出路径（调查点 5 — 草稿标注第二出口）

**两条独立的导出链，只有第二条与本 phase 相关：**

| 链 | 端点 | 实现 | 数据源 |
|----|------|------|--------|
| 会话导出 | `POST /api/chat/conversations/{id}/export-to-feishu/` `[VERIFIED: urls.py:108-110]` | `ExportToFeishuView` `[VERIFIED: views.py:1655]` | 选中的 Message | ✗ 不相关 |
| **方案导出** | `POST /api/chat/coding-plans/{coding_plan_id}/export-to-feishu/` `[VERIFIED: urls.py:173-175]` | `ExportCodingPlanToFeishuView` `[VERIFIED: views.py:1820-1911]` → `feishu.coding_plan_exporter.export_coding_plan_to_feishu` | chat `CodingPlan` + 关联 sessions | ✅ **RELY-01 第二出口** |

**渲染实现精确落点 `[VERIFIED: server/feishu/coding_plan_exporter.py]`：**

```
export_coding_plan_to_feishu(coding_plan, folder_token, title)      :59
  ├─ _aget_project_for_plan(coding_plan)                            :131
  ├─ _aload_coding_sessions(coding_plan)                            :143
  ├─ markdown = _compose_plan_markdown(coding_plan, sessions)       :184   ← 🎯 标注插入点
  │     ├─ parts.append(coding_plan.tech_plan)                      :191-193
  │     ├─ _build_affected_files_table(coding_plan.affected_files)  :197 / :206
  │     └─ _build_repo_status_table(sessions)                       :220
  └─ FeishuDocClient.create_document(content=markdown)              :106
        （内部已有 markdown_to_blocks，不重造 md→block 转换）
```

**结论**：草稿标注在导出侧的唯一插入点是 `_compose_plan_markdown`（`server/feishu/coding_plan_exporter.py:184`），加一段读 `coding_plan.provenance` 的显式告示块即可。函数是纯同步、易单测（既有 `server/tests/test_coding_plan_exporter.py` 覆盖）。

**⚠️ 已存在的第三条导出面（planner 需决定是否覆盖）**：编排产物还会被镜像进项目 RESEARCH 文档——`ArchitectMergeAdapter._maybe_bind_plan_to_project` 用 `render_merged_plan_markdown` + `ProjectDocService.append_research_note` `[VERIFIED: architect_merge_adapter.py:288-334]`。但这条链只走**编排产物**（永远是 `orchestrated`，不会是草稿），所以 RELY-01 的"双侧标注"覆盖它没有必要。建议在计划里显式写明"不覆盖此出口及理由"，避免后续审计判为遗漏。

---

## 6. 前端方案页与「进入编码」入口（调查点 6）

### 6.1 ❗ 编排产出在 SPA 里目前没有任何可操作呈现面

`[VERIFIED: web/src/composables/useToolDisplay.ts:23-62 TOOL_LABELS 与 :65-82 TOOL_ICONS 均无 start_plan_research / start_feature_solution 条目；:291-386 toolAction 的 switch 无对应 case，落到 default 分支产生泛化摘要]`

`start_plan_research` 成功时返回 `{session_id, artifact_version_id, status:"done", message}` `[VERIFIED: plan_research_tools.py:280-293]`——这些字段**前端一个都不消费**。用户在 chat 里能看到的只是一个未翻译的工具 pill。

**唯一展示编排产出的前端组件是只读的**：`ArtifactTimeline.vue`（交付物版本轨），挂在项目工作台资料面板 `ProjectMaterialsPanel.vue` 里以 `artifact-type="technical_plan"` 调用 `[VERIFIED: web/src/components/project/warroom/ProjectMaterialsPanel.vue + web/src/components/delivery/ArtifactTimeline.vue:14-25 docstring "只读呈现"]`。它展示：当前版本徽标 + `current_version_markdown`（可折叠 `<pre>`）+ 版本时间线（`produced_by_ref` / `supersedes` 链）+ 下游引用（`RepoCodingTask` / `SddSpec` / `ArchitectMerge`）。

**API 面 `[VERIFIED: web/src/api/deliveryArtifacts.ts]`：**
- `GET /delivery/artifacts/?work_item_id&artifact_type&space_id` → `ArtifactSummary[]`
- `GET /delivery/artifacts/{id}/` → `ArtifactTimeline`（含 `versions[]` + `current_version_markdown`）
- `GET /delivery/artifact-versions/{id}/downstream/` → 下游引用聚合

⇒ **「进入编码」入口必须新建**，有两个可选落点（planner/UI-SPEC 定）：

| 落点 | 优点 | 代价 |
|------|------|------|
| **A. chat 内新增编排产出卡片** | 与生产事故场景同面（用户就在 chat 里）；投影后 `activeCodingPlan` 自动可用（§4.3）；可复用 `TechPlanCard` | 需新增一个 part 渲染分支 + `useToolDisplay` 三处登记（label/icon/action） |
| **B. `ArtifactTimeline.vue` 加操作按钮** | 组件已存在、已有 space/type 过滤；一处覆盖所有入口（含 workflow 编排） | 该组件当前**纯只读**，加写操作要引入 mutation + toast；且工作台不在 chat 上下文里，投影需建合成会话 |

**A 与 B 不互斥**，且 A 覆盖 SC-1 的用户故事更直接。建议 **A 为主、B 可选**。

### 6.2 SPA 现有编码入口的具体组件与调用链

```
ChatMessageBubble.vue
  ├─ UNGROUPABLE_TOOLS = {deep_analysis, create_coding_plan, update_coding_plan}   :499
  ├─ isCodingPlanTool(name) = bare ∈ {create_coding_plan, update_coding_plan}      :754
  ├─ codingPlanData = computed(解析 tool result JSON → planId/techPlan/
  │     affectedFiles/sessionId/status/targetRepositories)                         :758-828
  │     ⚠️ planId 来自 parsed.coding_plan_id（:803）；techPlan 来自 tool **input**
  ├─ <TechPlanCard v-if="isCodingPlanTool(item.name) && item.status==='done'
  │                    && codingPlanData" ... />                                   :1139-1151
  └─ TechPlanCard.vue（见 §4 四步）
        └─ chatStore（useChatStore）
              ├─ activeCodingPlan ← runtime.coding_plan                            chat.ts:1156
              ├─ submitRepoMultiSelector(repoIds, branchTemplate, targetBranch)     chat.ts:2559
              └─ retrySingleRepository(planId, repositoryId)                        chat.ts:2621
```
`[VERIFIED: web/src/components/chat/ChatMessageBubble.vue + TechPlanCard.vue + web/src/stores/chat.ts]`

**⚠️ SPINE-02 对前端的连带影响**：`codingPlanData.techPlan` 目前从 `create_coding_plan` 的**工具 input**（即 LLM 写的 `tech_plan`）里取。schema 收窄后该入参不存在 ⇒ 前端必须改从 `runtime.coding_plan`（或投影端点返回体）取正文。`web/src/components/chat/__tests__/TechPlanCard.spec.ts` 与 `chatMessageBubble.parts.spec.ts` 会因此变红——这是**期望的**，是契约升级信号。

---

## 7. 追溯链现状（调查点 7）

**逐段核对 CONTEXT 声称的 `WorkItem → PlanVersion → CodingPlan → MR`：**

| 段 | 实际实现 | 强度 | 备注 |
|----|----------|------|------|
| `WorkItem → Artifact` | `Artifact.work_item` FK, SET_NULL, nullable `[VERIFIED: artifact.py:55-61]` | 🟢 真 FK | chat 自然语言需求恒 `None`（INV-2） |
| `WorkItem → ConvergenceSession` | `ConvergenceSession.work_item` FK, SET_NULL, nullable `[VERIFIED: convergence_session.py:62-68]` | 🟢 真 FK | |
| `Artifact ↔ ArtifactVersion` | `versions` 反向 + `current_version` FK（循环 FK）`[VERIFIED: artifact.py:72-78, 104-108]` | 🟢 真 FK | |
| `ConvergenceSession → ArtifactVersion` | `current_artifact_version` FK, SET_NULL `[VERIFIED: convergence_session.py:86-92]` | 🟢 真 FK | |
| `ArtifactVersion → ConvergenceSession` | `produced_by_session_id` **CharField(64) 软引用** `[VERIFIED: artifact.py:122]` | 🟡 软引用 | 模型 docstring 说 P2 会升级为 FK，**至今未升级** |
| `ArtifactVersion → RepoCodingTask` | `RepoCodingTask.artifact_version` FK, CASCADE, nullable `[VERIFIED: repo_coding_task.py:46-52]` | 🟢 真 FK | 这是 delivery 侧的编码子任务（workflow wave 编码），**不是** chat `CodingSession` |
| **`ArtifactVersion → chat CodingPlan`** | **不存在** `[VERIFIED: chat/models.py:212-275 无任何 delivery 引用；0031 迁移删掉了曾有的 canonical_plan_id]` | 🔴 **断链** | ⇐ **本 phase 要建的就是这一段** |
| `CodingPlan → CodingSession` | `CodingSession.coding_plan` FK, CASCADE, nullable `[VERIFIED: chat/models.py:365-375]` | 🟢 真 FK | |
| **`CodingSession → MergeRequest`** | **无 FK**。只有 `CodingSession.pr_url` (URLField) `[VERIFIED: chat/models.py:425]`；`MergeRequest` 侧只有 `project` / `repository` / `work_item` 三个 FK + `source_branch` 字符串 `[VERIFIED: server/initiatives/models/merge_request.py:41-76]` | 🔴 **弱链** | 只能靠 `(repository, source_branch)` 或 `work_item` 间接对齐 |

**⇒ 给 planner 的结论：**
1. CONTEXT 说的"复用既有追溯基建"在 `WorkItem → ArtifactVersion` 这半边成立，在 `CodingPlan → MR` 这半边**不成立**（`MergeRequest` 从未与 chat 编码域建过外键）。SC-4 的验收若被解读为"端到端 FK 可 join"会**超出本 phase 的合理边界**——建议计划里明确：本 phase 只补 `ArtifactVersion → CodingPlan` 这一段断链，`CodingPlan → MR` 沿用既有 `pr_url` + `(repository, source_branch)` 弱对齐并在文档中如实记录。
2. 投影时应写入的关联（最小完备集）：
   - `CodingPlan.source_artifact_version_id`（新列，兼幂等键）
   - `CodingPlan.recommended_repository_ids` ← `execution_plan[].repository_id` 去重
   - `CodingPlan.provenance = orchestrated`
   - `conversation` ← `ConvergenceSession.conversation_id`（chat 入口）或新建合成会话（其他入口）
   - `WorkItem` 的关联**不需要**在 `CodingPlan` 上再写一遍：经 `source_artifact_version_id → ArtifactVersion.artifact → Artifact.work_item` 两跳可达（去范式化会引入不一致风险）。

---

## 8. 工具 schema 移除的影响面（调查点 8）

### 8.1 改动本体（极小）

```python
# server/agents/tools/coding_tools.py
# ① parameters dict：删 tech_plan / affected_files 两个 property + 从 required 移除     :70-91, :104-109
# ② 函数签名：删 tech_plan / affected_files 两个参数                                   :112-119
# ③ 内部：不再调 _normalize_affected_files；改为按新入参（如 source_artifact_version_id）
#    走投影 service 或直接拒绝无来源调用                                                :183, :251-256
# ④ description：改写为「从已有编排方案版本创建/关联编码方案」                          :37-49
```

### 8.2 影响面清单（11 类，逐条给出处置）

| # | 面 | 位置 | 会不会红 | 处置 |
|---|----|------|----------|------|
| 1 | LLM 工具描述与入参（本体） | `coding_tools.py:35-119` | — | 改 |
| 2 | **两份工具白名单** | `chat_runner.py:105` + `conversation_service.py:430` `[VERIFIED]` | 不红 | 仅需核对同步；⚠️ 两份内容不同，别只改一处 |
| 3 | system prompt `_CODING_GUIDANCE`（9 处提名） | `conversation_service.py:216-247` | — | 改文案 |
| 4 | prompt 片段断言测试 | `server/tests/test_conversation_service_fragment_extraction.py:72-73`（断言 `_CODING_GUIDANCE` 含 `create_coding_plan` / `update_coding_plan`）`[VERIFIED]` | 🔴 **会红** | 改断言（契约升级） |
| 5 | prompt 组装断言测试 | `server/tests/test_conversation_service_prompt_fragments.py:102, 173`（`:173` 断言"调 create_coding_plan 之前必须有 analyze_repository_relevance"逐字文案）`[VERIFIED]` | 🔴 **会红** | 改断言 |
| 6 | 项目上下文行断言测试 | `server/tests/test_project_context_line.py:23`（断言 `create_coding_plan` in line）`[VERIFIED]` | 🔴 可能红 | 视 `chat/config.py:73` 文案改动 |
| 7 | 工具单测 | `server/tests/test_coding_tools.py`（`TestCreateCodingPlan` 8 个用例全传 `tech_plan=` / `affected_files=`）`[VERIFIED: :46-196]` | 🔴 **全红** | 重写为新签名 |
| 8 | **前端类型与解析** | `web/src/composables/useToolDisplay.ts:47,164`；`ChatMessageBubble.vue:758-856`（`techPlan` 从 tool input 取）`[VERIFIED]` | 🟡 静默降级（不报错但 `techPlan` 为空） | 改为从 runtime / 端点响应取 |
| 9 | 前端测试 | `web/src/components/chat/__tests__/TechPlanCard.spec.ts`、`chatMessageBubble.parts.spec.ts`、`partsApiIntegration.spec.ts`、`useToolDisplay.spec.ts` `[VERIFIED: rg 命中 create_coding_plan]` | 🔴 部分红 | 随 #8 更新 |
| 10 | skills / 文档 | `skills/skills/friday-code/SKILL.md`、`task/assets/skills/friday-code/SKILL.md`、`docs/guide/friday-codebase-agent.md`、`docs/integrations/mcp.md`、`mcp/README.md` `[VERIFIED]` | 不红 | 核对每处指 A 还是 B，只改指 A 的 |
| 11 | 飞书 bot 卡片工具名 | `server/feishu/cards/bot_cards.py:15` `[VERIFIED]` | 不红 | 标签文案可选改 |

### 8.3 schema 漂移守护测试：现状与缺口

| 守护 | 覆盖对象 | 覆盖 `create_coding_plan`（实体 A）？ |
|------|----------|--------------------------------------|
| `server/tests/agents/test_tool_contracts.py` + `fixtures/*.json` `[VERIFIED: 全文 + ls fixtures/]` | `search_repository_code`、`find_related_code`、`find_api_handler`、`find_api_callers`、`list_endpoints`、`repository_relevance` 的**函数签名 + pydantic input schema** 字节级 diff | ❌ **未覆盖** |
| `server/tests/mcp_tools/test_schema_snapshot.py` `[VERIFIED: :28-49, :52-210]` | ① `urls.py` 路由 ↔ `TOOL_SCHEMA_SNAPSHOT` 键集合一致；② 每个 MCP 工具的 request/response 键列表逐字 snapshot | ✅ 但只覆盖**实体 B**（`:90-93`） |
| `server/tests/mcp_tools/test_mcp_package_alignment.py` `[VERIFIED: rg 命中]` | npm MCP 包 `mcp/src/tools.ts` 与后端工具清单对齐 | ✅ 实体 B |

**⇒ 缺口与建议**：实体 A 的 schema **没有任何漂移守护**。SPINE-02 的核心验收是"结构上再也无法徒手编方案"，这个性质**必须有测试锁住**，否则未来一次"顺手加回 tech_plan 入参"就能悄悄回退。建议按 `test_tool_contracts.py` 的既有范式（`inspect.unwrap` + `inspect.signature` 序列化 + fixture 字节 diff，含 `_generate_contract_fixtures.py` 的显式再生成流程）给 `create_coding_plan` 补一份 signature snapshot，并**额外加一条正向断言**：`"tech_plan" not in tool.parameters["properties"]`（`server/tests/agents/test_start_plan_research_tool.py:215` 已有 `t.parameters["properties"]` 的读法先例 `[VERIFIED]`）。

---

## 9. `provenance` 标志的落点（调查点 9）

### 9.1 落点必须是 chat `CodingPlan`

| 候选 | 可行性 |
|------|--------|
| **chat `CodingPlan`** | ✅ **唯一正确落点**。界面（`TechPlanCard`）与飞书导出（`_compose_plan_markdown`）**都**只读这一个对象 —— 是 RELY-01"双侧标注"的天然瓶颈点；且草稿路径本身就只产 `CodingPlan` |
| `delivery.Artifact` / `ArtifactVersion` | ❌ 草稿（徒手/应急路径）根本不产 `Artifact`，无处可标 |
| `ConvergenceSession` | ❌ 同上，且草稿无 session |

### 9.2 既有"来源枚举"先例（命名与形态可直接照抄）

| 先例 | 位置 | 形态 |
|------|------|------|
| `WorkItemOrigin` | `server/delivery/models/work_item.py:19-29` `[VERIFIED]` | `models.TextChoices`：`feishu_webhook` / `manual` / `bitable_import` / `mr_reverse`，值为 snake_case、label 为中文 |
| `DocumentSourceKind` | `server/delivery/models/document.py:34-38` `[VERIFIED]` | `external_feishu` / `internal_generated` |
| `ContentStorage` | `server/delivery/models/document.py:41-46` `[VERIFIED]` | `snapshot` / `reference` / `both` |

**⇒ 建议形态**（planner 定名，但形状照抄先例）：
```python
class CodingPlanProvenance(models.TextChoices):
    ORCHESTRATED = "orchestrated", "编排产出"
    DRAFT = "draft", "未经代码调研的草稿"
```
字段：`provenance = models.CharField(max_length=16, choices=..., default=DRAFT, db_index=True)`。

### 9.3 ⚠️ 迁移形态的两个硬约束

1. **必须有 `default`。** `mcp_tools/execution_service.py:109` 与多处测试用裸 `CodingPlan.objects.create(...)` 不传该字段 `[VERIFIED]`；无 default 会让 MCP 桥接直接崩 —— 这正是"MCP 零回归"最容易失守的一点。
2. **default 取 `draft` 而非 `orchestrated`。** 存量 `coding_plans` 行全部是徒手创作产物（SPINE-02 之前的唯一路径），标成 `orchestrated` 等于把历史数据谎报为可信。additive 加列 + `default="draft"` 一步到位，无需 data migration。

### 9.4 消费点（各一处，共 3 处）

| 消费者 | 位置 | 消费方式 |
|--------|------|----------|
| 前端卡片 | `TechPlanCard.vue`（新增 prop + 告示条）；数据经 `ConversationRuntimeCodingPlanSerializer` / `CodingPlanSerializer` 透出 `[VERIFIED: server/chat/serializers.py:420-425, 560-588]` | 渲染「未经代码调研」横幅 |
| 飞书导出 | `server/feishu/coding_plan_exporter.py:184 _compose_plan_markdown` | 正文顶部插告示块 |
| 送编码防护 | `CodingPlanSessionsBatchCreateView` / `create_sessions_for_plan` `[VERIFIED: views.py:2573-2668]` | `provenance == draft` 且请求未带显式确认标志 → 拒绝（fail-closed 必须在服务端） |

**下游携带**：CONTEXT 要求"编码上下文携带「未经调研」标志"。落点是 `CodingExecutionSpec`（`server/chat/coding_session_service.py:63-88`，dispatch 给 Runner/容器的结构化执行契约）`[VERIFIED]` —— 加一个布尔/枚举字段即可，容器侧消费与否由 planner 定（本 phase 至少要让它出现在 dispatch payload 里）。

---

## 10. 幂等唯一约束的可行性（调查点 10）

### 10.1 目标表现有唯一约束：无

`CodingPlan.Meta` 只有 1 个索引、**0 个约束** `[VERIFIED: chat/models.py:268-275]`。现行去重完全在应用层（§2.1），CONTEXT 判断"并发下会重复"**成立**：`aget_or_create_for_conversation` 是"先全表 async 迭代比 hash，未命中才 `acreate`"，两个并发请求会各自 miss 然后各插一条。

### 10.2 可直接照抄的条件唯一约束先例（同一文件内！）

```python
# server/chat/models.py:515-528  CodingSession.Meta  [VERIFIED]
constraints = [
    models.UniqueConstraint(
        fields=["coding_plan", "repository"],
        condition=Q(status__in=["draft", "confirmed", "running", "awaiting_confirmation"]),
        name="unique_active_plan_repo",   # migration 0013
    ),
]
```
配套：`server/chat/coding_session_service.py:37-47` 把 active 状态集合抽成 `ACTIVE_STATUSES` 常量并注明"与 `Meta.constraints.unique_active_plan_repo` **字面一致**"，且 import 了 `IntegrityError` 做碰撞降级 `[VERIFIED: coding_session_service.py:24, 37-47]`。

**⇒ 推荐约束形态（已订正，见下方 ⚠️）：**
```python
models.UniqueConstraint(
    fields=["source_artifact_version_id"],
    name="uniq_codingplan_source_artifact_version",
)
```

> ⚠️ **本节初稿的建议是错的，已订正 —— 不要用 `condition=Q(source_artifact_version_id__isnull=False)`。**
>
> 初稿理由（「若用无条件唯一约束，SQLite 允许多 NULL 但 PostgreSQL 与 MySQL 的 NULL 语义/索引行为不一致，不要赌」）方向是**反的**：PostgreSQL / MySQL / SQLite 的唯一索引**都**遵循「NULL 互不相等」，多条 NULL 行在无条件唯一约束下同样可共存。无条件形态无需赌任何 NULL 语义。
>
> 而带 `condition` 才是真正的赌，且赌输时**静默**：`django/db/backends/mysql/features.py:48` 是 `supports_partial_indexes = False`，`django/db/backends/base/schema.py:1792-1793` 的 `_unique_supported()` 在 `condition` 非空且后端不支持 partial index 时返回 `False` ⇒ **`AddConstraint` 被跳过，不报错也不告警**。本仓 `server/friday/settings.py:447-458` 明文支持 `mysql://` 与 MariaDB，因此 MySQL 部署上带 `condition` 的约束根本不存在，`aget_or_create` + `except IntegrityError` 的幂等三件套只剩两件。
>
> 因此 §10.2 的先例 `unique_active_plan_repo`（`condition=Q(status__in=...)`）**只可照抄"约束 + 常量字面一致 + IntegrityError 降级"这套纪律，不可照抄 `condition` 用法** —— 那条约束在 MySQL 上同样是静默失效的既有技术债，不是要复制的范式。
>
> 配套要求：必须有一条读 `connection.introspection.get_constraints` 的测试断言约束在当前后端**确实存在**，否则「约束被静默跳过」与「约束正常」在测试上表现完全一致（多 NULL 共存在无约束时同样通过；幂等用例是顺序调用；并发用例若靠 monkeypatch 强制抛异常则绕过了真实约束）。落点：`109-02` Task 1。

**是否要把 `conversation` 纳入约束？** 不要。同一 `ArtifactVersion` 在两个 conversation 里各投影一份 = 重复编码方案，正是要防的；单列约束更严格也更简单。

### 10.3 并发路径

| 路径 | 是否会并发投影同一版本 |
|------|------------------------|
| SPA 用户在方案页连点两次「进入编码」 | ✅ 最现实的并发源 |
| SPA + 另一浏览器标签/另一成员同时点 | ✅ |
| MCP 侧 | ❌ 低风险 —— MCP 有自己的 `McpCodingPlan` 链，不会去投影 `ArtifactVersion`（除非 planner 主动新增，不建议本 phase 做） |

### 10.4 async `get_or_create` 的正确用法（本仓先例）

**仓内已有 8+ 处 `aget_or_create` / `aupdate_or_create` 用法** `[VERIFIED: server/projects/views.py:144,762; server/services/indexer.py:795,1163,...; server/notifications/services/announcement_service.py:148]`，典型：

```python
link, created = await SpaceRepository.objects.aget_or_create(
    space=space, repository=repo, defaults={...}
)
```

**⚠️ 但 `aget_or_create` 单独不够。** Django 的 `get_or_create` 在两个并发请求同时 miss 时**双方都会尝试 INSERT**，靠 DB 唯一约束抛 `IntegrityError`，Django 内部会 catch 并重新 `get()` —— 前提是**约束存在**。所以正确组合是：

> **DB `UniqueConstraint`（真正的并发安全来源） + `aget_or_create`（便利 API） + 外层显式 `IntegrityError` 兜底**（照抄 `coding_session_service.py` 的 `IntegrityError` import 与降级模式）。

`aget_or_create` 单独用不安全、`UniqueConstraint` 单独用会给用户抛 500，两者必须同时存在。这一点 planner 必须在任务描述里写清，否则容易只做一半。

**另一个 async 陷阱**：`aget_or_create` 的 `defaults` 里若含 FK 对象，必须传已 await 到手的实例（不能传 lazy FK）。本仓的通用纪律是"用 `*_id` 标量 / `.values()` / `afirst` / `aget`，绝不裸访问同步 lazy-FK" `[VERIFIED: plan_research_tools.py:14-16 模块 docstring；orchestration_delegate.py:13-14]`。

---

## 11. 回归护栏现状（调查点 11 — SPINE-02 动刀前必须先绿的东西）

### 11.1 SPA 编码链路

| 测试文件 | 覆盖 | 缺口 |
|----------|------|------|
| `server/tests/test_coding_tools.py` `[VERIFIED: 全文]` | 工具级：产 plan 不产 session、affected_files 归一化、space/repo 校验、`recommended_repository_ids` 四种来源、dual-id 响应 | SPINE-02 后**全部要重写** |
| `server/tests/test_coding_plan_api.py` | `CodingPlan` list/detail API | |
| `server/tests/test_coding_plans_sessions_api.py` `[VERIFIED: :1-40]` | fan-out 端点 6 类场景（3 仓全成功 / 部分成功 / 全失败 / 403 / 404 / 400） | 🟢 **质量好，可作为③的守护基线** |
| `server/tests/test_coding_plan_export_api.py` + `test_coding_plan_exporter.py` | ④飞书导出端点 + markdown 拼接 | 🟢 可作为④基线 |
| `server/tests/test_coding_plan_model.py` | 模型层（含去重语义） | |
| `server/tests/test_coding_session_graph_e2e.py` / `test_coding_session_graph.py` / `test_coding_session_service.py` | ③确认编码后的 graph 驱动 | |
| `web/.../TechPlanCard.spec.ts`、`CodingSessionStatusRow.spec.ts`、`RepoMultiSelector.spec.ts`、`chatMessageBubble.feishuExport.spec.ts` `[VERIFIED: ls]` | 前端①②④ | |

**🔴 缺口**：**没有一条测试从"工具产 plan"一路走到"fan-out 建 session"再到"导出"**。四步各有独立测试，但没有把"这四步都还挂在同一个 `CodingPlan.id` 上"这条不变量锁住的端到端用例。CONTEXT 明确要求"SPA 与 MCP 两条编码链路的端到端守护测试**先绿再动刀**" ⇒ **这条端到端守护测试需要新写**，并且它必须在 SPINE-02 的任何 schema 改动之前存在且通过。这是 wave 划分的硬依据。

### 11.2 MCP 编码链路

| 测试文件 | 覆盖 | 评价 |
|----------|------|------|
| `server/tests/mcp_tools/test_create_coding_plan_delegate.py` `[VERIFIED: 全文 371 行]` | 实体 B 的 6 组守护（delegate 被调 + 单仓约束 + actor 透传 / canonical 映射 / 响应键 snapshot / `McpCodingPlan`+Version 落库 / partial 携 session / 空 content 降级） | 🟢 **很完整** |
| `server/tests/mcp_tools/test_execution_tools.py` `[VERIFIED: :1-40]` | `create_coding_plan` → `execute_coding_plan` 全链；**import 了 `chat.models.CodingSession`** ⇒ 已实际覆盖桥接建 `CodingSession` | 🟢 **这就是 MCP 桥接的既有端到端护栏** |
| `server/tests/mcp_tools/test_schema_snapshot.py` | 实体 B 的 request/response 键 snapshot | 🟢 |
| `server/tests/mcp_tools/test_mr_tools.py` / `test_work_item_execution.py` | MR 创建 / work item 批量执行 | |

**🟡 缺口**：`test_execution_tools.py` 断言了 `CodingSession` 被建，但**未显式断言 chat `CodingPlan` 被建且字段正确**。给 `CodingPlan` 加 `provenance` 字段时，若忘了 default，这条测试**可能仍然绿**（取决于是否走到那行）—— 建议补一条针对 `_create_bridge_session` 的直接单测，显式断言三个对象（`Conversation` / `CodingPlan` / `CodingSession`）全部建成且 `provenance` 有值。这是"MCP 零回归"最直接的锁。

---

## Architecture Patterns

### System Architecture Diagram

```
┌─ 需求入口 ─────────────────────────────────────────────────────────────┐
│  SPA chat 用户消息          workflow 节点         MCP HTTP 客户端        │
└──────┬────────────────────────────┬──────────────────────┬────────────┘
       │ LLM 调 start_plan_research │ ai_plan_research 节点 │ POST create_coding_plan
       ▼                            ▼                      ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  process_runtime 统一编排（唯一方案产出脊柱）                    │
   │  start_orchestration(entrypoint=chat|workflow|mcp)             │
   │  → build_orchestration_engine()                                │
   │  → decompose → route → recall → clarify → research → merge     │
   │  ConvergenceSession{status, current_stage, stage_state,         │
   │                     conversation_id, current_artifact_version}  │
   └──────────────────────────┬────────────────────────────────────┘
                              │ merge 通过（ArchitectMergeAdapter._handle_pass）
                              ▼  ArtifactService.create("technical_plan", merged)
                    ┌──────────────────────────────────┐
                    │ Artifact + ArtifactVersion(v1)    │
                    │   content = §7 MergedPlan         │
                    │     ├─ title / summary            │
                    │     ├─ execution_plan[]           │  ← 执行流的数据来源
                    │     │    {repository_id,           │
                    │     │     coding_instruction,      │
                    │     │     files[{path, action}]}   │
                    │     └─ compat_risks / risks / …    │
                    │   content_hash (sha256)           │
                    └──────────┬───────────────────────┘
                               │
        【SPINE-01 新增：惰性投影，用户点「进入编码」时触发】
                               │  幂等键 = ArtifactVersion.id
                               │  DB UniqueConstraint + aget_or_create
                               ▼
                ┌────────────────────────────────────────┐
                │ chat CodingPlan  ← 执行流唯一锚点        │
                │   conversation (NOT NULL)               │
                │   tech_plan       ← render_merged_plan_ │
                │                      markdown(content)  │
                │   affected_files  ← 全仓聚合 files[]    │
                │                      path→file_path,    │
                │                      create→add         │
                │   recommended_repository_ids            │
                │                   ← execution_plan[]    │
                │                     .repository_id 去重  │
                │   source_artifact_version_id  (新列)     │
                │   provenance = orchestrated   (新列)     │
                └──┬─────────────┬───────────┬───────────┘
                   │             │           │
    ①②选仓+配分支  │  ③确认编码  │  ④飞书导出 │
    TechPlanCard   │  POST       │  POST      │
    (前端选择)      │  /coding-   │  /coding-  │
                   │  plans/{id}/│  plans/{id}│
                   │  sessions/  │  /export-  │
                   ▼             ▼  to-feishu/▼
              CodingSession   dispatch    _compose_plan_
              (per repo,      _coding_    markdown
               DRAFT)          task       (读 provenance
                   │           → Runner    → 加告示)
                   ▼           → 容器
              pr_url (弱链 → MergeRequest)

┌─ 徒手草稿路径（SPINE-02 后仅剩应急，provenance=draft）───────────┐
│  chat LLM 调 create_coding_plan  ⇒ schema 已无 tech_plan /       │
│  affected_files ⇒ 结构上无法产出正文                             │
│  存量/应急草稿 provenance=draft ⇒ 界面 + 导出双侧标注            │
│                              ⇒ 送编码需服务端显式确认（fail-closed）│
└──────────────────────────────────────────────────────────────────┘

┌─ MCP 执行链（与上面完全并行，SPINE-02 零耦合）──────────────────┐
│  McpCodingPlan → McpCodingPlanVersion                          │
│    → execution_service._create_bridge_session （裸 ORM）        │
│    → 合成 Conversation + chat CodingPlan + CodingSession        │
│    → dispatch_coding_task                                       │
│  ⇒ 不经过 chat @tool create_coding_plan（关键纠正）              │
└─────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure（新增/改动文件预估）

```
server/
├── chat/
│   ├── models.py                          # 改：CodingPlan 加 2 列 + 1 约束（+ Provenance TextChoices）
│   ├── migrations/00XX_codingplan_provenance_and_source.py   # 新：additive
│   ├── plan_projection_service.py         # 新：投影 service（唯一写入入口）
│   ├── views.py                           # 改：新增投影端点 + fan-out 加草稿 gate
│   ├── urls.py                            # 改：注册投影端点
│   ├── serializers.py                     # 改：CodingPlanSerializer / runtime 序列化器透出 provenance
│   └── coding_session_service.py          # 改：CodingExecutionSpec 携带未经调研标志
├── agents/tools/
│   └── coding_tools.py                    # 改（SPINE-02）：收窄 create_coding_plan schema
├── chat/conversation_service.py           # 改：_CODING_GUIDANCE / hint 文案
├── feishu/coding_plan_exporter.py         # 改：_compose_plan_markdown 加草稿告示
└── tests/
    ├── test_plan_projection_service.py    # 新：投影映射 + 幂等 + 并发
    ├── test_spa_coding_chain_e2e.py       # 新：SPA ①→②→③→④ 端到端护栏（SPINE-02 前必绿）
    ├── mcp_tools/test_bridge_session.py   # 新：_create_bridge_session 三对象断言（零回归锁）
    └── agents/
        ├── test_tool_contracts.py         # 改：加 create_coding_plan signature snapshot
        └── fixtures/create_coding_plan_signature.json   # 新
web/src/
├── components/chat/
│   ├── TechPlanCard.vue                   # 改：provenance 横幅 + techPlan 改从 runtime 取
│   └── OrchestratedPlanCard.vue（或等价）  # 新：编排产出卡片 + 「进入编码」按钮
├── composables/useToolDisplay.ts          # 改：登记 start_plan_research（label/icon/action）
├── stores/chat.ts                         # 改：projectPlanToCodingPlan action
└── api/chat.ts                            # 改：投影端点客户端
```

### Pattern 1: 投影 service（幂等 + 追溯 + 观测）

**What:** 单一写入入口，把 `ArtifactVersion` 投影成 chat `CodingPlan`。
**When to use:** 用户点「进入编码」时（惰性）。

```python
# server/chat/plan_projection_service.py（形状示意，非逐字实现）
import time
import structlog
from asgiref.sync import sync_to_async
from django.db import IntegrityError

logger = structlog.get_logger(__name__)


class PlanProjectionService:
    """编排方案版本 → chat CodingPlan 的唯一投影入口（幂等 + 追溯）。"""

    async def aproject(
        self,
        *,
        artifact_version_id: str,
        conversation_id: str | None = None,
        # ⚠️ 已订正：这个带默认值的形态只适用于 109-03（唯一调用方是端点，
        # 归属由视图 owner gate 保证）。109-05 让 chat @tool 成为第二个调用方后，
        # 该参数改为 **必填** 的 actor_user_id，且归属判定下移进 service
        # （不匹配抛 PlanProjectionError(code="artifact_version_forbidden")）。
        # 带默认值 = 漏传即以 "system" 身份放行，正是要避免的形状。
        initiated_by_user_id: str = "system",
    ) -> tuple["CodingPlan", bool]:
        from chat.models import CodingPlan, CodingPlanProvenance
        from delivery.models import ArtifactVersion

        started = time.perf_counter()
        logger.info(
            "plan_projection_started",
            category="caller",              # 用户可归因的一次调用
            component="chat",               # §5 组件清单
            artifact_version_id=artifact_version_id,
            initiated_by_user_id=initiated_by_user_id,
        )

        av = await ArtifactVersion.objects.filter(id=artifact_version_id).afirst()
        if av is None or not isinstance(av.content, dict):
            # fail-closed：无来源不投影（这正是 SPINE-02 想堵的口）
            raise PlanProjectionError("方案版本不存在或内容非法")

        payload = map_merged_plan_to_coding_plan(av.content)   # 纯函数，见 Pattern 2
        conversation = await self._aresolve_conversation(av, conversation_id)

        try:
            plan, created = await CodingPlan.objects.aget_or_create(
                source_artifact_version_id=str(av.id),         # ← 幂等键（DB 唯一约束兜底）
                defaults={
                    "conversation": conversation,
                    "title": payload["title"][:200],
                    "tech_plan": payload["tech_plan"],
                    "affected_files": payload["affected_files"],
                    "recommended_repository_ids": payload["recommended_repository_ids"],
                    "provenance": CodingPlanProvenance.ORCHESTRATED,
                },
            )
        except IntegrityError:
            # 并发下双方同时 miss → 一方 INSERT 失败 → 重新 get（照抄
            # coding_session_service 的 IntegrityError 降级模式）
            plan = await CodingPlan.objects.aget(source_artifact_version_id=str(av.id))
            created = False

        logger.info(
            "plan_projection_completed",
            category="caller",
            component="chat",
            duration_ms=max(int((time.perf_counter() - started) * 1000), 0),
            artifact_version_id=str(av.id),
            coding_plan_id=str(plan.id),
            created=created,
            repo_count=len(payload["recommended_repository_ids"]),
        )
        return plan, created
```

### Pattern 2: §7 → chat CodingPlan 纯函数映射（多仓聚合）

**What:** 无 IO 的映射函数，可穷举单测。
**Why 独立成纯函数:** `map_canonical_to_coding_plan` 已证明这个形状好测（6 组守护测试都靠它）。

```python
def map_merged_plan_to_coding_plan(content: dict) -> dict:
    """§7 MergedPlan → chat CodingPlan 字段（多仓聚合，半可信输入 fail-safe 不抛）。"""
    from services.process_runtime.render import render_merged_plan_markdown

    if not isinstance(content, dict):
        content = {}
    raw = content.get("execution_plan")
    tasks = [t for t in raw if isinstance(t, dict)] if isinstance(raw, list) else []

    # affected_files：全仓聚合 + 键名/枚举转换 + 去重保序
    _ACTION_TO_CHANGE_TYPE = {"create": "add", "modify": "modify", "delete": "delete"}
    affected: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for task in tasks:
        files = task.get("files")
        for f in files if isinstance(files, list) else []:
            if not isinstance(f, dict):
                continue
            path = str(f.get("path") or "")
            if not path:
                continue
            change_type = _ACTION_TO_CHANGE_TYPE.get(str(f.get("action") or ""), "modify")
            if (path, change_type) in seen:
                continue
            seen.add((path, change_type))
            affected.append({"file_path": path, "change_type": change_type})

    # recommended_repository_ids：去重保序（保 execution_plan 的顺序 = 保 release_order 意图）
    repo_ids: list[str] = []
    for task in tasks:
        rid = str(task.get("repository_id") or "")
        if rid and rid not in repo_ids:
            repo_ids.append(rid)

    return {
        "title": str(content.get("title") or ""),
        "tech_plan": render_merged_plan_markdown(content),
        "affected_files": affected,
        "recommended_repository_ids": repo_ids,
    }
```

### Anti-Patterns to Avoid

- **在应用层用 `filter().afirst()` 查重当幂等**：现行 `aget_or_create_for_conversation` 就是这样，并发下必然重复（CONTEXT 已点名否决）。
- **给 `CodingPlan` 新增字段不带 `default`**：`mcp_tools/execution_service.py:109` 的裸 `objects.create()` 会崩 ⇒ 直接破坏"MCP 零回归"。
- **改 `mcp_tools/` 下任何 `create_coding_plan` 相关代码**：那是实体 B，与 SPINE-02 无关；动它会撞 `test_schema_snapshot.py` + `test_mcp_package_alignment.py` 两道守护。
- **在 SPINE-01 落地前先改工具 schema**：CONTEXT 的顺序硬约束；SPA 会短暂失去唯一编码入口。
- **靠 prompt 文案实现 SPINE-02**：CONTEXT 明确"仅靠 prompt 约束不算达成"。
- **在前端拼 `CodingPlan` 或前端做草稿 gate**：送编码防护必须服务端 fail-closed。
- **把 `provenance` 默认设成 `orchestrated`**：会把存量徒手方案谎报为可信。
- **fork 出第二个 markdown 渲染器**：`render_merged_plan_markdown` 已是"MCP delegate 与 ai_plan_research done 出口共享"的唯一 helper（其 docstring 明写"落『不造两套』"）；需要 GFM 就给它加 flavor 参数。
- **在投影里裸访问 lazy FK**：async 上下文必须 `*_id` 标量 / `.values()` / `afirst` / `sync_to_async`。

---

## Don't Hand-Roll

| 问题 | 不要自己写 | 用这个 | 为什么 |
|------|-----------|--------|--------|
| §7 MergedPlan → markdown | 新渲染器 | `services.process_runtime.render.render_merged_plan_markdown` `[VERIFIED: render.py:28]` | 已是 MCP delegate 与 ai_plan_research 共享的唯一 helper；已做脱敏纵深（只读结构化字段、不 dump LLM 原文）与 fail-safe |
| §7 content 合法性校验 | 手写字段检查 | `services.process_runtime.merged_plan.validate_merged_plan` `[VERIFIED: merged_plan.py:44]` | 内部复用 `validate_technical_plan` jsonschema；半可信输入恒不抛 |
| 取 session 的 canonical content | 自己查 Artifact 链 | `orchestration_delegate._load_canonical` 的模式 `[VERIFIED: orchestration_delegate.py:59-76]` | 已处理 async 裸 lazy-FK + content 非 dict 回退 |
| DB 唯一约束（幂等键） | 应用层 lock / select_for_update | **无条件** `UniqueConstraint(fields=["source_artifact_version_id"])`；只抄 `unique_active_plan_repo` 的**纪律**（常量与约束字面一致 + `IntegrityError` 降级），**不抄它的 `condition`** `[VERIFIED: chat/models.py:515-528]` | 同文件先例；`condition` 会在 MySQL 上被静默跳过，见 §10.2 订正 |
| 幂等的并发兜底 | 自己写重试循环 | `aget_or_create` + `except IntegrityError` 重 `aget`，抄 `coding_session_service` `[VERIFIED: coding_session_service.py:24]` | Django 内建语义，配 DB 约束后并发安全 |
| owner 权限门 | 自己写 403 判断 | 抄 `plan.conversation.created_by_id != user.id → 404` `[VERIFIED: views.py:2560-2567]` | 四处一致；404 不泄漏存在性；无 superuser bypass |
| 工具 schema 漂移守护 | 手写断言 | `tests/agents/test_tool_contracts.py` 的 fixture 字节 diff + `_generate_contract_fixtures.py` 再生成流程 `[VERIFIED]` | 已有"契约升级 = 一次显式提交"的工作流 |
| markdown → 飞书 block | 自己转 | `FeishuDocClient.create_document`（内含 `markdown_to_blocks`）`[VERIFIED: coding_plan_exporter.py:15-16 注释]` | exporter docstring 明写"不重造" |
| 建合成 Conversation | 自己拼 | 抄 `_create_bridge_session` `[VERIFIED: execution_service.py:98-127]` | 已有 `created_by` 透传 → 任务 token mint 的正确写法 |

**Key insight:** 本 phase 几乎不需要发明任何机制——需要的每一块（编排 delegate、canonical 映射、markdown 渲染、条件唯一约束、owner 门、schema snapshot 守护、合成会话）**在仓内都已有一个明确的、有测试的先例**。风险不在"怎么做"，而在"改到了不该改的那半边"和"顺序搞反"。

---

## Common Pitfalls

### Pitfall 1: 把两个 `create_coding_plan` 当成一个
**What goes wrong:** planner 以为 SPINE-02 会牵动 MCP 执行链，于是给 MCP 侧安排大量守护/兼容任务；或反过来去改 `mcp_tools/views.py` 的 `CreateCodingPlanView`，撞坏 `test_schema_snapshot.py` 与 `test_mcp_package_alignment.py`。
**Why it happens:** 两者同名，CONTEXT 与 REQUIREMENTS 的措辞把它们合并叙述了。
**How to avoid:** 计划里每次提到 `create_coding_plan` 都标明「chat @tool」或「MCP 端点」。SPINE-02 的改动范围严格限定在 `server/agents/tools/coding_tools.py` + prompt/白名单/前端解析。
**Warning signs:** 任何任务的 files 清单里出现 `server/mcp_tools/views.py` 或 `server/mcp_tools/serializers.py`。

### Pitfall 2: 新字段无 default 打断 MCP 桥接
**What goes wrong:** `provenance` / `source_artifact_version_id` 加成必填 ⇒ `execution_service.py:109` 的裸 `CodingPlan.objects.create(...)` 缺字段 ⇒ MCP `execute_coding_plan` 全链 500。
**Why it happens:** 桥接用裸 ORM 而非 service，加字段时容易只顾着改自己的写入点。
**How to avoid:** `provenance` 给 `default=DRAFT`；`source_artifact_version_id` 给 `null=True, blank=True`。并补一条直接针对 `_create_bridge_session` 的单测断言三对象与新字段值。
**Warning signs:** `server/tests/mcp_tools/test_execution_tools.py` 变红，或"绿了但没断言 CodingPlan"。

### Pitfall 3: `create` → `add` 枚举漂移静默通过
**What goes wrong:** §7 用 `action: create`，chat 用 `change_type: add`。漏转换后 `TechPlanCard` 原样显示 `create`（`:404` 直接渲染 `file.change_type`），不报错、不崩，只是"看起来怪"；下游若有按 `add`/`modify`/`delete` 分支的逻辑会走错分支。
**Why it happens:** 既有 `_normalize_affected_files` 只做 `path→file_path`，不做枚举映射，容易被当成"已经处理好了"。
**How to avoid:** 映射纯函数里显式建 `_ACTION_TO_CHANGE_TYPE` 表；单测穷举三个 action 值 + 一个未知值（回退 `modify`）。
**Warning signs:** 测试只断言 `file_path` 不断言 `change_type`。

### Pitfall 4: 投影 chat 之外入口的编排时缺 conversation
**What goes wrong:** `CodingPlan.conversation` NOT NULL；workflow / MCP 入口的 `ConvergenceSession.conversation_id` 为空 ⇒ 投影抛 `IntegrityError` 或 `None` 传 FK 报错。
**Why it happens:** chat 入口测试全绿，容易漏掉另两个入口。
**How to avoid:** 投影 service 的 `_aresolve_conversation` 显式两分支：有 `conversation_id` 则复用；无则按 `_create_bridge_session` 模式建合成会话（`space` 从哪来需明确 —— `ConvergenceSession` 没有 `space` FK，只能经 `conversation_id` 或 `work_item` 反查，**这是一个真实的开放问题，见 Open Questions Q2**）。
**Warning signs:** 计划里投影 service 的签名只有 `artifact_version_id` 一个参数。

### Pitfall 5: 顺序搞反 —— 先收窄 schema 再建投影
**What goes wrong:** SPA 短暂失去唯一编码入口；用户无法从对话进入编码。
**Why it happens:** SPINE-02 的改动量看起来小，容易被排到前面"先扫干净"。
**How to avoid:** wave 划分必须体现 CONTEXT 的硬约束：Wave A = 端到端护栏（SPA + MCP，先绿）；Wave B = 投影 service + 迁移 + 前端入口（SPINE-01 成立）；Wave C = schema 收窄（SPINE-02）+ provenance 双侧渲染 + 送编码 gate（RELY-01）。
**Warning signs:** 任何 wave 里 `coding_tools.py` 的改动早于投影 service 的落地。

### Pitfall 6: 只在前端做草稿送编码防护
**What goes wrong:** 用户/脚本直接 `POST /api/chat/coding-plans/{id}/sessions/` 绕过确认弹层，草稿照样送编码 ⇒ RELY-01 SC-3 不成立。
**How to avoid:** gate 落在 `CodingPlanSessionsBatchCreateView` / `create_sessions_for_plan`：`provenance == draft` 且请求体无显式确认标志 → 400/403，并留痕（`category="caller"`）。前端确认只是 UX。
**Warning signs:** 验收只有前端测试，没有直接打端点的后端测试。

### Pitfall 7: 忘了第二份工具白名单
**What goes wrong:** 只改 `chat_runner.py:105`，`conversation_service.py:430` 的 `_get_tool_names` 仍按老清单挂载 ⇒ 某些路径下行为不一致，且改动看起来"生效了"（因为常走的那条路径改对了）。
**Why it happens:** 两份清单内容不同（`_get_tool_names` 短很多），不是简单重复，容易被当成不相关。
**How to avoid:** 计划任务里同时列出两个位置；可考虑加一条一致性断言测试。

### Pitfall 8: `render_merged_plan_markdown` 的 lark_md 方言
**What goes wrong:** 投影出的 `tech_plan` 在 `TechPlanCard`（markdown-it / GFM）里列表渲染成一行行的 `• xxx` 纯文本而非 `<ul>`。不算 bug 但观感差，容易在 UAT 阶段被判为"方案显示不对"。
**Why it happens:** 该函数为飞书卡片而写，docstring 里明确说明 lark_md 不支持 `- ` 语法所以用 `•`。
**How to avoid:** 提前决定：接受（省事）或给函数加 `flavor: "lark_md" | "gfm"` 参数（不 fork）。planner 应把这个决定写进任务而不是留给 executor 现场发挥。

---

## Runtime State Inventory

> 本 phase 含 schema 收窄与数据模型变更，按 rename/refactor 类别填写。

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| **Stored data** | `coding_plans` 表存量行（生产实例含徒手创作产物，其中包括事故会话 `ccd817d9` 绕道产生的那份）；`delivery_artifact_version` 存量 technical_plan 版本 | **代码改动 + 迁移 default，不需要数据迁移**：新列 `provenance default="draft"` 恰好正确描述存量（全是徒手产物）；`source_artifact_version_id` 存量为 NULL 正确（无投影来源）。⚠️ 不要写把存量刷成 `orchestrated` 的 data migration |
| **Live service config** | 无。本 phase 不改任何外部服务配置（飞书应用 / Qdrant / Runner 均不涉及） | 无 — 已核对：改动面只有 Django app + Vue 组件 + 一次迁移 |
| **OS-registered state** | 无。不新增 apscheduler job、不改 Runner 注册 | 无 — 已核对：`django-apscheduler` 的 job 注册点（Phase 107 的 `expire_pending_clarifications`）本 phase 不触及 |
| **Secrets / env vars** | 无新增。投影不调 LLM、不需新凭证 | 无 |
| **Build artifacts / installed packages** | ⚠️ **`mcp/` npm 包**：`mcp/src/tools.ts` 列的是**实体 B**（MCP 端点），本 phase 不改 ⇒ 无需重新发包。若 planner 误改实体 B，则 `test_mcp_package_alignment.py` 会红且需同步发包 | 无（前提是不动实体 B）。`skills/skills/friday-code/SKILL.md` 与 `task/assets/skills/friday-code/SKILL.md` 是**两份需保持同步的副本**，若其中提到实体 A 则两份都要改 |

**特别提示 — 前端类型契约不是"运行时状态"但同样会静默漂移**：`web/src/types/chat.ts` 的 `CodingPlanRuntime` 与后端 `ConversationRuntimeCodingPlanSerializer` 手工对齐（无代码生成）。加 `provenance` 字段要两侧都改，漏一侧 TypeScript 不会报错（字段只是读不到）。

---

## Code Examples

### 迁移形态（additive + 条件唯一约束）

```python
# server/chat/migrations/00XX_codingplan_provenance_and_source.py（示意）
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("chat", "0032_repositoryroutingtrace_degrade_reason")]

    operations = [
        migrations.AddField(
            model_name="codingplan",
            name="provenance",
            field=models.CharField(
                max_length=16,
                choices=[("orchestrated", "编排产出"), ("draft", "未经代码调研的草稿")],
                default="draft",          # ← 存量与裸 ORM 调用方都靠它（Pitfall 2）
                db_index=True,
                verbose_name="方案来源",
            ),
        ),
        migrations.AddField(
            model_name="codingplan",
            name="source_artifact_version_id",
            field=models.UUIDField(
                null=True, blank=True, db_index=True,
                verbose_name="来源方案版本",
                help_text="delivery.ArtifactVersion.id 软引用；投影幂等键。"
                          "与已删除的 canonical_plan_id（0022/0031）不同：此列只记投影来源、"
                          "不构成 chat↔delivery 双向耦合。",
            ),
        ),
        migrations.AddConstraint(
            model_name="codingplan",
            constraint=models.UniqueConstraint(
                # 无条件：三后端唯一索引均视 NULL 互不相等，草稿行天然不受约束。
                # 不得加 condition —— MySQL 的 supports_partial_indexes=False 会让
                # AddConstraint 被静默跳过（详见 §10.2 的订正说明）。
                fields=["source_artifact_version_id"],
                name="uniq_codingplan_source_artifact_version",
            ),
        ),
    ]
```

### SPINE-02 收窄后的工具 schema（示意）

```python
# server/agents/tools/coding_tools.py
@tool(
    name="create_coding_plan",
    description=(
        "把**已由编排链路产出**的技术方案版本投影为可执行的编码方案。"
        "本工具不接受方案正文——正文只能来自完整编排链路（start_plan_research / "
        "start_feature_solution / 工作流方案节点）产出的方案版本。"
        "若尚无方案版本，先调 start_plan_research 发起编排。"
    ),
    category="PROJECT",
    parameters={
        "type": "object",
        "properties": {
            "space_id": {"type": "string", "description": "空间 UUID (auto-injected)"},
            "conversation_id": {"type": "string", "description": "会话 UUID (auto-injected)"},
            "artifact_version_id": {
                "type": "string",
                "description": "编排产出的方案版本 UUID（start_plan_research 返回值）",
            },
            # tech_plan / affected_files 已移除 —— LLM 结构上无法徒手编写方案正文
        },
        "required": ["space_id", "conversation_id", "artifact_version_id"],
    },
)
async def create_coding_plan(space_id: str, conversation_id: str,
                             artifact_version_id: str) -> ToolResult:
    ...
```

### SPINE-02 的正向守护断言

```python
# server/tests/agents/test_coding_tools_schema_guard.py（新）
def test_create_coding_plan_schema_has_no_authoring_params() -> None:
    """SPINE-02 不变量：LLM 无法经工具 schema 徒手提交方案正文。

    这条断言锁的是「结构上不可能」，而非「prompt 里不建议」——未来任何把
    tech_plan / affected_files 加回入参的改动都会在此变红。
    """
    from agents.tools.base import get_tool  # 或 _tool_registry 的公开读取入口

    props = get_tool("create_coding_plan").parameters["properties"]
    required = set(get_tool("create_coding_plan").parameters.get("required") or [])

    assert "tech_plan" not in props, "SPINE-02 回退：方案正文入参被加回"
    assert "affected_files" not in props, "SPINE-02 回退：影响文件入参被加回"
    assert "artifact_version_id" in required, "投影来源必须必填（fail-closed）"
```

### 草稿标注（飞书导出侧）

```python
# server/feishu/coding_plan_exporter.py::_compose_plan_markdown（示意插入）
_DRAFT_NOTICE = (
    "> ⚠️ **本方案未经代码调研**\n"
    ">\n"
    "> 由对话直接生成，未经过仓库路由、代码召回与并行调研环节，"
    "文件清单与实现步骤可能不准确。正式方案请经技术方案编排产出。\n"
)


def _compose_plan_markdown(coding_plan, sessions) -> str:
    parts: list[str] = []
    # 读数据层来源标志，不靠调用方传文案（避免新增产出路径时漏标）
    if coding_plan.provenance == CodingPlanProvenance.DRAFT:
        parts.append(_DRAFT_NOTICE)
    tech_plan = (coding_plan.tech_plan or "").strip()
    if tech_plan:
        parts.append(tech_plan + "\n")
    ...
```

---

## Observability（按 `.cursor/rules/observability-logging.mdc` 强制补齐）

**本 phase 新增/改动的观测点（planner 必须逐条落进任务验收）：**

| 事件名 | category | component | 关键字段 | 触发点 |
|--------|----------|-----------|----------|--------|
| `plan_projection_started` | `caller` | `chat` | `artifact_version_id`, `initiated_by_user_id` | 投影 service 入口 |
| `plan_projection_completed` | `caller` | `chat` | `duration_ms`, `coding_plan_id`, `created`, `repo_count`, `provenance` | 投影 service 出口 |
| `plan_projection_failed` | `caller` | `chat` | `duration_ms`, `reason`, `artifact_version_id` | 来源不存在 / content 非法 / conversation 不可解析 |
| `plan_projection_idempotent_hit` | `caller` | `chat` | `artifact_version_id`, `coding_plan_id` | `created=False`（含 `IntegrityError` 并发分支） |
| `draft_plan_coding_confirmed` | `caller` | `chat` | `coding_plan_id`, `user_id`, `repo_count` | 草稿经显式确认送编码（RELY-01 留痕要求） |
| `draft_plan_coding_rejected` | `caller` | `chat` | `coding_plan_id`, `reason="draft_requires_explicit_confirm"` | 服务端 gate 拒绝 |
| `coding_plan_authoring_attempt_rejected` | `caller` | `agents` | `conversation_id`, `reason` | SPINE-02 后仍尝试无来源创建（CONTEXT 明确要求"schema 层移除后的调用尝试需留痕"） |

**纪律要点 `[VERIFIED: .cursor/rules/observability-logging.mdc + LOGGING-SPEC.md §5]`：**
- `component` 取值必须在 §5 清单内：本 phase 用 `chat`（投影/执行流）与 `agents`（工具层），**不要造新 component**。
- 每条事件必须能回答"谁触发的"：投影经 HTTP 端点触发 ⇒ 统一中间件自动注入 `user_id`/`request_id`；若投影被后台任务调用则显式带 `initiated_by_user_id`（无触发用户记 `system`）。
- **best-effort 不反噬**：观测代码全部 `try/except: pass` 包裹（照抄 `orchestration_delegate.py:154-163, 214-222, 234-245` 的三段式）。
- **本 phase 不新增 LLM 调用点** ⇒ **不需要**新 `call_source` 枚举值。投影是纯映射，编排的 LLM 埋点由 `process_runtime` adapters 已承担（`orchestration_delegate.py:14-16` 明写"编排内部 LLM/召回埋点由 process_runtime adapters 承担，无需 MCP 层重复赋值"，投影层同理）。
- **新增请求入口**（投影端点、fan-out gate）自动纳入 `RequestMetric` 的 QPS/错误率/时长统计（中间件层，无需手工上报）。
- **不新增召回** ⇒ 无 `RetrievalTrace` 要求。
- 脱敏：投影不接触凭证；但 `plan_projection_failed` 的 `reason` 若来自异常文本，必须过 `redact_secrets_in_text`。

---

## Project Constraints (from `.cursor/rules/` 与 `CLAUDE.md`)

| 约束 | 出处 | 对本 phase 的具体要求 |
|------|------|----------------------|
| 可观测性与日志规范（强制） | `.cursor/rules/observability-logging.mdc` | 见上节；提交前逐条过自检清单 |
| async ORM 必须过 `sync_to_async` | `CLAUDE.md` Architectural Constraints | 投影 service 的事务块用 `@sync_to_async` + `transaction.atomic()`（抄 `_create_bridge_session`） |
| 迁移 additive 优先 | `109-CONTEXT.md` Established Patterns | 只 `AddField` + `AddConstraint`，不改既有列，不写 data migration |
| 服务层无状态类方法 | `109-CONTEXT.md` Established Patterns | `PlanProjectionService` 用类方法/实例方法，不持有状态 |
| 凭证/设置复用既有 service 层 | `CLAUDE.md` Constraints · Convention | 本 phase 不涉及凭证 |
| Python ruff format，line length 100，target py314 | `CONVENTIONS.md` / `server/pyproject.toml` | 新文件遵守 |
| 注释/docstring 用中文，解释 intent 而非 mechanics | `CONVENTIONS.md` | 新 service / 迁移的 help_text 用中文说明"为什么" |
| 文档正文中文、代码标识保留英文 | `doc-writing-zh.mdc` | 本 RESEARCH.md 与后续 PLAN/SUMMARY 遵守 |
| Commit 用简体中文 + Conventional Commits | `commit-rule.mdc` | `feat(chat): ...` / `refactor(agents): ...` |
| 前端技术选型以 `frontend-tech-stack-skill` 为准 | `fe-engineering-baseline.mdc` | 新组件只用既有栈（Vue 3 + reka-ui + Tailwind 4 + vue-query），不引新依赖 |
| GSD workflow enforcement | `CLAUDE.md` / `AGENTS.md` | 改动经 `/gsd-execute-phase` 走 |

---

## State of the Art（本仓演进史，影响本 phase 的判断）

| 旧做法 | 现做法 | 何时变的 | 对本 phase 的意义 |
|--------|--------|----------|-------------------|
| `TechnicalPlan` / `PlanVersion` 方案专属模型 | `delivery.Artifact` / `ArtifactVersion` type 化通用交付物 | Chassis v2 · P1 `[VERIFIED: artifact.py:1-17]` | 幂等键取 `ArtifactVersion.id`，不要去找 `PlanVersion` |
| `PlanSession`（8 态写死阶段） | `ConvergenceSession`（通用运行时态 + `current_stage` + `stage_state`） | Chassis v2 · P2 `[VERIFIED: convergence_session.py:1-22]` | 编排状态从 `status` + `current_stage` 两个正交维度读 |
| chat `CodingPlan.canonical_plan_id` 软链 delivery | 已删除（chat 不再耦合 delivery 产物脊柱） | 迁移 `0031` `[VERIFIED]` | 新加来源列必须在注释里区分于这段历史，否则会被误判为重复包袱 |
| `create_coding_plan` 工具顺便建 `CodingSession` | 工具只产 plan；session 由前端经 fan-out 端点建 | coding-plan workflow `[VERIFIED: coding_tools.py:121-124]` | 执行流的入口是 HTTP 端点而非工具，SPINE-02 的收窄不碰执行流 |
| MCP `create_coding_plan` 用确定性 seam 自己拼方案 | delegate 到 `process_runtime` 统一编排 | Phase 94 UNIFY-03/04 `[VERIFIED: views.py:1889-1911]` | **实体 B 已经是"编排直连"的完成态**，是 SPINE-01 的参考实现 |
| `ArchitectMergeAdapter` 用 `add_version` 递增版本 | 每次融合通过都 `ArtifactService.create` 新建 Artifact + v1 | `[VERIFIED: architect_merge_adapter.py:252]` | `version_no` 恒为 1；不要假设版本链存在 |

**Deprecated / 不要碰：**
- `CodingSession.tech_plan` / `CodingSession.affected_files` — 模型 help_text 明写"deprecated：优先使用 `coding_plan.*`；保留至 v26.1 清理" `[VERIFIED: chat/models.py:389-403]`。投影不要往这两个字段写（`_create_bridge_session` 为兼容还在写，那是它的历史包袱）。
- `create_coding_plan` 返回的 `session_id` / `coding_session_id` — 恒 `None` 的兼容 alias `[VERIFIED: coding_tools.py:280-282]`。
- `update_coding_plan` 的 `session_id` 入参 — 描述里标 "legacy 兼容路径，已 deprecated" `[VERIFIED: coding_tools.py:309-311]`。

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework（后端） | `pytest>=9.0.2` + `pytest-django>=4.8` + `pytest-asyncio`（`asyncio_mode="auto"`） |
| Config file（后端） | `server/pyproject.toml` `[tool.pytest.ini_options]` `[VERIFIED: :112-125]` |
| 后端 testpaths / addopts | `testpaths=["tests"]`；`addopts="-v --tb=short --disable-socket --allow-unix-socket -m 'not perf and not integration and not slow and not postgres_queue'"` `[VERIFIED]` |
| Quick run（后端） | `cd server && uv run pytest tests/test_plan_projection_service.py tests/test_coding_tools.py -x` |
| Full suite（后端） | `cd server && uv run pytest` |
| Framework（前端） | `vitest@^4` + `@vue/test-utils` + `happy-dom` |
| Config file（前端） | `web/vite.config.ts` / `web/package.json` scripts `[VERIFIED: :14-18]` |
| Quick run（前端） | `cd web && pnpm vitest run src/components/chat/__tests__/TechPlanCard.spec.ts` |
| Full suite（前端） | `cd web && pnpm test:unit --run` |

> ⚠️ `--disable-socket` 意味着测试内**禁止真实网络**。投影 service 无网络调用（纯 DB + 纯函数），天然合规；飞书导出测试需 mock `FeishuDocClient`（既有 `test_coding_plan_exporter.py` 已建立此模式）。

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| SPINE-01 | §7 `execution_plan` → `{tech_plan, affected_files, recommended_repository_ids}` 映射正确（含 `path→file_path`、`create→add`、多仓聚合去重保序、空/非法 content 降级不抛） | unit | `cd server && uv run pytest tests/test_plan_projection_service.py -k mapping -x` | ❌ Wave 0 |
| SPINE-01 | 投影出的 `CodingPlan` 能直接走完①②③④（同一 `plan_id` 打 fan-out 端点与导出端点均 200） | integration | `cd server && uv run pytest tests/test_spa_coding_chain_e2e.py -x` | ❌ Wave 0 |
| SPINE-01 | chat 入口复用 `ConvergenceSession.conversation_id`；无 conversation 的入口建合成会话 | unit | `cd server && uv run pytest tests/test_plan_projection_service.py -k conversation -x` | ❌ Wave 0 |
| SPINE-01 | 前端「进入编码」按钮触发投影并把返回 `plan_id` 交给 `TechPlanCard` | unit（前端） | `cd web && pnpm vitest run src/components/chat/__tests__/OrchestratedPlanCard.spec.ts` | ❌ Wave 0 |
| SPINE-02 | 工具 schema 无 `tech_plan` / `affected_files`，`artifact_version_id` 必填（正向不变量） | unit | `cd server && uv run pytest tests/agents/test_coding_tools_schema_guard.py -x` | ❌ Wave 0 |
| SPINE-02 | 工具函数签名 fixture 字节 diff（漂移即红） | unit | `cd server && uv run pytest tests/agents/test_tool_contracts.py -x` | 🟡 文件存在，需加 `create_coding_plan` fixture |
| SPINE-02 | 无来源的创建尝试被拒绝并留痕 | unit | `cd server && uv run pytest tests/test_coding_tools.py -k reject -x` | 🟡 文件存在，用例需重写 |
| SPINE-02 | **MCP 桥接零回归**：`_create_bridge_session` 建成 `Conversation`+`CodingPlan`+`CodingSession` 三对象且新字段有值 | integration | `cd server && uv run pytest tests/mcp_tools/test_bridge_session.py -x` | ❌ Wave 0 |
| SPINE-02 | MCP `create_coding_plan` → `execute_coding_plan` 全链不变 | integration | `cd server && uv run pytest tests/mcp_tools/test_execution_tools.py tests/mcp_tools/test_create_coding_plan_delegate.py -x` | ✅ 存在 |
| SPINE-02 | MCP 工具 request/response 键集合不漂移 | unit | `cd server && uv run pytest tests/mcp_tools/test_schema_snapshot.py -x` | ✅ 存在 |
| RELY-01 | `provenance=draft` 时飞书导出正文含「未经代码调研」告示 | unit | `cd server && uv run pytest tests/test_coding_plan_exporter.py -k draft -x` | 🟡 文件存在，需加用例 |
| RELY-01 | `provenance=draft` 时前端卡片渲染告示横幅 | unit（前端） | `cd web && pnpm vitest run src/components/chat/__tests__/TechPlanCard.spec.ts` | 🟡 文件存在，需加用例 |
| RELY-01 | **服务端** fail-closed：草稿未带显式确认 → fan-out 端点拒绝（直接打端点，不经前端） | integration | `cd server && uv run pytest tests/test_coding_plans_sessions_api.py -k draft_gate -x` | 🟡 文件存在，需加用例 |
| RELY-01 | 草稿经显式确认送出时 dispatch payload 携带「未经调研」标志 | unit | `cd server && uv run pytest tests/test_coding_session_service.py -k unresearched -x` | 🟡 文件存在，需加用例 |
| SC-4 | 同一 `ArtifactVersion` 重复投影返回既有 `CodingPlan`，DB 只 1 行 | integration | `cd server && uv run pytest tests/test_plan_projection_service.py -k idempotent -x` | ❌ Wave 0 |
| SC-4 | **并发**投影同一版本只产 1 行（DB 唯一约束生效 + `IntegrityError` 分支不抛给调用方） | integration | `cd server && uv run pytest tests/test_plan_projection_service.py -k concurrent -x` | ❌ Wave 0 |
| SC-4 | 新 `ArtifactVersion` 可新建投影，**旧投影保留**（DB 两行、旧行未被改写） | integration | `cd server && uv run pytest tests/test_plan_projection_service.py -k new_version_keeps_old -x` | ❌ Wave 0 |
| SC-4 | 追溯可达：`CodingPlan.source_artifact_version_id → ArtifactVersion → Artifact → WorkItem` 两跳 join 成立 | integration | `cd server && uv run pytest tests/test_plan_projection_service.py -k traceability -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `cd server && uv run pytest tests/test_plan_projection_service.py tests/test_coding_tools.py tests/mcp_tools/test_bridge_session.py -x`（目标 < 30s）
- **Per wave merge:** `cd server && uv run pytest tests/test_coding_plan*.py tests/test_coding_tools.py tests/test_coding_session*.py tests/mcp_tools/ tests/agents/ -x` + `cd web && pnpm test:unit --run`
- **Phase gate:** `cd server && uv run pytest` 全绿 + `cd web && pnpm test:unit --run` 全绿，之后才 `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `server/tests/test_plan_projection_service.py` — 覆盖 SPINE-01 映射 + SC-4 幂等/并发/多版本/追溯（**最大的一块**）
- [ ] `server/tests/test_spa_coding_chain_e2e.py` — SPA ①→②→③→④ 端到端护栏（**CONTEXT 要求"先绿再动刀"，必须在 SPINE-02 之前存在**）
- [ ] `server/tests/mcp_tools/test_bridge_session.py` — `_create_bridge_session` 三对象直接断言（MCP 零回归锁）
- [ ] `server/tests/agents/test_coding_tools_schema_guard.py` — SPINE-02 正向不变量断言
- [ ] `server/tests/agents/fixtures/create_coding_plan_signature.json` — 经 `python -m tests.agents._generate_contract_fixtures` 生成
- [ ] `web/src/components/chat/__tests__/OrchestratedPlanCard.spec.ts`（或等价新组件测试）
- [ ] 既有文件需加用例：`test_coding_plan_exporter.py`（draft 告示）、`test_coding_plans_sessions_api.py`（draft gate）、`test_coding_session_service.py`（dispatch 标志）、`TechPlanCard.spec.ts`（provenance 横幅）
- [ ] 既有文件需重写：`server/tests/test_coding_tools.py`（8 个 `TestCreateCodingPlan` 用例全部依赖旧签名）

框架安装：**无需**（pytest / vitest 均已就位）。

---

## Security Domain

> `workflow.security_enforcement = true`，`security_asvs_level = 1`，`security_block_on = "high"` `[VERIFIED: .planning/config.json]`

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | 复用既有 `OptionalJWTAuthentication` / `ChatKeyAuthentication`（照抄 `ExportCodingPlanToFeishuView:1828-1829` 与 `CodingPlanSessionsBatchCreateView:2581-2582`），不新造认证 |
| V3 Session Management | no | 无新会话机制；`ConvergenceSession` / `Conversation` 均为既有 |
| V4 Access Control | **yes（关键）** | 投影端点必须复用 owner gate：`plan.conversation.created_by_id != user.id → 404`（不是 403）；**无 superuser bypass**；另加"该 `ArtifactVersion` 的 space/project 用户是否有权限"的校验 |
| V5 Input Validation | **yes** | 投影端点入参 `artifact_version_id` 用 DRF `UUIDField` 校验；§7 `content` 是**半可信 LLM 产物**，映射函数必须 fail-safe（非 dict / 缺键 / 类型错一律降级不抛，照抄 `map_canonical_to_coding_plan` 的防御风格） |
| V6 Cryptography | no | 不涉及加密；凭证仍走既有 Fernet `ProviderCredential` |
| V7 Error Handling & Logging | yes | 异常文本入日志前过 `redact_secrets_in_text`；owner-miss 统一 404 不泄漏存在性 |

### Known Threat Patterns for Django + DRF + Vue

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| **越权投影他人会话的方案版本**（IDOR） | Elevation of Privilege | owner gate 前置于任何序列化/业务逻辑；照抄四处既有模式；`ArtifactVersion` 侧另需 space/project 归属校验（`ConvergenceSession.created_by` 或经 `conversation` 反查） |
| **绕过前端确认把草稿送编码** | Tampering / Elevation | 服务端 fail-closed gate 在 `create_sessions_for_plan`（Pitfall 6） |
| **半可信 LLM content 触发映射崩溃**（DoS） | Denial of Service | 映射纯函数全程 `isinstance` 守卫 + 缺键填空不抛（§Pattern 2）；`title[:200]` 等长度截断防超长 |
| **投影正文注入到飞书文档**（存储型注入） | Tampering | `render_merged_plan_markdown` 只读结构化字段、绝不 dump LLM 原文（既有脱敏纵深，`render.py:11-14`）；导出侧既有 `_md_escape` 防表格 `\|` 截断（`coding_plan_exporter.py:242`） |
| **`provenance` 被客户端伪造成 `orchestrated`** | Spoofing | `provenance` **只能由服务端写**：投影 service 写 `orchestrated`，其余路径恒 `draft`（DB default）；序列化器把它设为 read-only（`CodingPlanSerializer` 已是"所有字段 read-only"，`serializers.py:560-563`） |
| **枚举 `artifact_version_id` 探测存在性** | Information Disclosure | 不存在与无权限统一 404，措辞一致 |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `render_merged_plan_markdown` 产出的 lark_md（`•` 项目符号）在 `TechPlanCard` 的 markdown-it 渲染下"可读但不成列表" | §Alternatives / Pitfall 8 | 低。若实测更差（如破坏排版），需给函数加 `flavor` 参数；不影响架构决策 |
| A2 | 投影端点应新建而非复用收窄后的 `create_coding_plan` 工具 | §Pattern 1 / §Structure | 中。若 planner 选择"只经收窄后的工具投影"，则前端「进入编码」得先让 LLM 调工具（多一跳 LLM，不确定性高）。**建议 HTTP 端点 + 工具双入口共用同一 service** |
| A3 | 前端「进入编码」落点 A（chat 内新卡片）优于 B（`ArtifactTimeline` 加按钮） | §6.1 | 低。由 UI-SPEC 定稿；两者不互斥 |
| A4 | 存量 `coding_plans` 行全部是徒手创作产物（因此 `default="draft"` 正确） | §9.3 / §Runtime State | 低-中。理论上存量里有 MCP 桥接建的行（那些来自 `McpCodingPlan`，其 v0.16.1 之后的部分其实来自编排）。若要精确，可在迁移里把 `title` 以 `"MCP execution: "` 开头的行刷成 `orchestrated`——但这引入 data migration，**建议不做**、在文档中如实说明"存量一律标 draft，宁可保守" |
| A5 | 本 phase 不需要新 `call_source` 枚举值 | §Observability | 低。投影无 LLM 调用；若 planner 决定在投影时补 LLM 摘要（不建议），则需新增 |
| A6 | `_get_tool_names`（`conversation_service.py:430`）与 `_INDEXED_TOOL_NAMES`（`chat_runner.py:105`）是两条并行生效的挂载路径，都需同步 | §1.3 / Pitfall 7 | 中。若其中一条已实际失效（死代码），同步它是无害的多余工作；若两条都活而只改一条，则行为不一致难排查。**建议执行时先确认哪条在跑** |
| A7 | `MergeRequest` 与 chat 编码域确实没有可 join 的 FK，`CodingPlan → MR` 只能弱对齐 | §7 | 中。若 planner 把 SC-4 的追溯验收定为"端到端 FK join"，则需额外建 FK（超出本 phase 边界）。**建议在计划里把这段边界写明** |

---

## Open Questions (RESOLVED)

> 本节 4 个 Open Question 全部已在 `109-CONTEXT.md` 的裁决中收口，逐条指向见各项末尾的 **Resolution** 行。保留原文是为了留下「当时不清楚什么、为何这样裁」的推理链，不代表仍未定。

1. **无 conversation 的编排入口，投影时合成会话的 `space` 从哪来？**
   - 已知：`CodingPlan.conversation` NOT NULL；`Conversation.space` 是 FK（nullable，`chat/models.py:55-57`）；`ConvergenceSession` **没有** `space` FK，只有 `work_item`（nullable）+ `conversation_id`（nullable）；`_create_bridge_session` 的 `project` 参数由 `execution_service._find_project_for_repository(plan.repository_id)` 反查而来 `[VERIFIED: execution_service.py:147-149]`。
   - 不清楚：workflow 入口的编排（`work_item` 非空、无 conversation）该经 `WorkItem → ?` 还是经 `execution_plan[0].repository_id → _find_project_for_repository` 反查 space。
   - **Recommendation:** 本 phase 把投影范围**限定在 chat 入口**（`ConvergenceSession.conversation_id` 非空），workflow / MCP 入口的投影列为后续或按需；这样 SC-1 的用户故事（"用户在编排产出方案后可直接进入执行流"）完整成立，且避开 space 反查的歧义。planner 若要覆盖全入口，需先决定反查规则并在 discuss 阶段确认。
   - **Resolution → 裁决 D-3（投影只做 chat 入口）**：采纳该建议。无 conversation 的编排入口以稳定机器码 `projection_requires_chat_entrypoint` 显式拒绝，**不建合成会话、不按 repository 反查 space**。落点：`109-03` Task 2 action 第 1 条 + Task 3 的 400 分支；边界记录于 `109-VALIDATION.md §Explicit Scope Boundaries` 第 1 条。

2. **`create_coding_plan` 收窄后，`update_coding_plan` 怎么办？**
   - 已知：`update_coding_plan` 的必填入参同样是 `tech_plan` + `affected_files` `[VERIFIED: coding_tools.py:336]`——它是**同一个徒手创作漏洞的第二个门**。CONTEXT 只点名 `create_coding_plan`。
   - **Recommendation:** SPINE-02 的字面表述是"系统不再存在由对话模型徒手编写方案正文的产出路径"——`update_coding_plan` 让 LLM 能把任意正文写进既有 plan，**同样违反该表述**。建议一并收窄（或改为只接受"重新投影新版本"），并在计划里显式说明这是对 SPINE-02 语义的必要覆盖，而非范围蔓延。若 planner 决定不动它，必须在 VERIFICATION 里如实记录这个残留口子。
   - **Resolution → 裁决 D-1（两个门一起收窄）**：采纳建议，`update_coding_plan` 一并收窄，语义改为「re-bind 到新的编排方案版本」而非任意改写。落点：`109-05` Task 1 B 节（schema + `PlanProjectionService.arebind`）+ Task 2 A 节的正向不变量对两个工具各断言一次。**无残留口子**，因此 VERIFICATION 无需记录该项。

3. **草稿的"显式确认"用什么载体？**
   - 已知：`CodingSessionsBatchCreateRequestSerializer` 现有 `repository_ids` / `branch_template` / `target_branch` `[VERIFIED: views.py:2645-2649]`。
   - 不清楚：确认标志加成请求体布尔字段（如 `acknowledge_unresearched: true`）还是独立的二次确认端点。
   - **Recommendation:** 请求体布尔字段最简（一次往返、天然幂等、易测）；由 UI-SPEC 决定弹层文案。
   - **Resolution → 裁决 D-5（载体取请求体布尔字段，不新开端点）**：采纳该建议。字段名 `acknowledge_unresearched`，`default=False`，`provenance != draft` 时被忽略。落点：`109-07` Task 1（serializer + service gate + 机器码 `draft_requires_explicit_confirm`）+ `109-08` Task 2（弹层是该字段 `true` 的唯一来源）。

4. **`start_plan_research` 的 chat 呈现要做到什么程度？**
   - 已知：该工具在前端完全没有呈现（§6.1）。本 phase 的 SC-1 只要求"能进入编码"。Phase 110 才负责阶段进展与时间线。
   - **Recommendation:** 本 phase 只做**最小可操作呈现**——工具标签/图标/摘要三处登记 + 一张带「进入编码」按钮的产出卡片；阶段流式与时间线严格留给 Phase 110，不要在这里开头。
   - **Resolution → 裁决 D-4（chat 呈现只做最小可操作面）**：采纳该建议。落点：`109-04` Task 2（`OrchestratedPlanCard.vue` +「进入编码」）+ Task 3（`UNGROUPABLE_TOOLS` 与三处工具展示登记）；不渲染方案正文、无进度 UI、无阶段流式/时间线，边界记录于 `109-VALIDATION.md §Explicit Scope Boundaries` 第 2 条，阶段进展留 Phase 110（`109-08 <assumptions>` 第 4 行）。

---

## Sources

### Primary（HIGH confidence — 本会话实读的仓内源码）
- `server/agents/tools/coding_tools.py`（全文 445 行）— chat `@tool create_coding_plan` / `update_coding_plan`
- `server/agents/tools/plan_research_tools.py`（全文 302 行）— chat 编排入口
- `server/agents/tools/base.py:30-160` — `@tool` 装饰器与注册表
- `server/agents/chat_runner.py:85-150` — 工具白名单
- `server/chat/models.py:212-528` — `CodingPlan` / `CodingSession`
- `server/chat/views.py:1820-1911, 2490-2668` — 导出 / list / detail / fan-out 视图
- `server/chat/urls.py:100-180` — 端点注册
- `server/chat/conversation_service.py:205-260, 400-442` — prompt 片段与工具白名单（第二份）
- `server/chat/coding_session_service.py:1-90` — dispatch 服务与 `ACTIVE_STATUSES` / `CodingExecutionSpec`
- `server/chat/serializers.py:396-430, 560-590` — runtime / plan 序列化器
- `server/mcp_tools/views.py:1780-2050` — `CreateCodingPlanView` / `ImproveCodingPlanView`
- `server/mcp_tools/orchestration_delegate.py`（全文 325 行）— delegate + canonical 映射
- `server/mcp_tools/execution_service.py:1-320` — `_create_bridge_session` 桥接
- `server/mcp_tools/models.py:1-200` — `McpCodingPlan` / Version / ExecutionTrace
- `server/mcp_tools/serializers.py:200-260, 740-800` — 请求契约 + `TOOL_SCHEMA_SNAPSHOT`
- `server/delivery/models/__init__.py`（全文）— 导出清单（据此确认 `TechnicalPlan`/`PlanVersion` 不存在）
- `server/delivery/models/convergence_session.py`（全文 152 行）
- `server/delivery/models/artifact.py`（全文 146 行）
- `server/delivery/models/repo_coding_task.py`（全文 105 行）
- `server/delivery/models/work_item.py:19-31`、`document.py:34-46` — 来源枚举先例
- `server/delivery/services/artifact_service.py:39-170`
- `server/delivery/services/event_taxonomy.py:49-88` — 事件常量
- `server/services/process_runtime/merged_plan.py`（全文 60 行）
- `server/services/process_runtime/render.py:1-60`
- `server/services/process_runtime/entrypoint.py:32-105`
- `server/services/process_runtime/architect_merge_adapter.py:230-340`
- `server/workflows/schemas/technical_plan.py`（全文 280 行）— §7 `execution_plan` 权威 schema
- `server/initiatives/models/merge_request.py:37-137`
- `server/feishu/coding_plan_exporter.py`（结构 + 关键行）
- `server/tests/mcp_tools/test_create_coding_plan_delegate.py`（全文 371 行）
- `server/tests/mcp_tools/test_schema_snapshot.py`（全文 211 行）
- `server/tests/agents/test_tool_contracts.py:1-90`
- `server/tests/test_coding_tools.py`、`test_coding_plans_sessions_api.py:1-40`、`mcp_tools/test_execution_tools.py:1-40`
- `server/tests/initiatives/test_artifact_inv6_guard.py:1-60` — INV-6 守护范式
- `web/src/components/chat/TechPlanCard.vue`（全文 716 行）
- `web/src/components/chat/ChatMessageBubble.vue`（关键行 499/754/758-856/1139-1151）
- `web/src/composables/useToolDisplay.ts`（全文 387 行）
- `web/src/components/delivery/ArtifactTimeline.vue`（全文 287 行）
- `web/src/api/deliveryArtifacts.ts`（全文 128 行）
- `web/src/stores/chat.ts`（关键行 143/1145/1156/2466/2559/2621）
- `server/pyproject.toml:112-125`、`web/package.json:14-18` — 测试框架配置
- `.planning/config.json` — workflow 开关与安全等级
- `.planning/observability/LOGGING-SPEC.md` §4.1/§5/§9/§10
- `.cursor/rules/observability-logging.mdc`、`CLAUDE.md`、`AGENTS.md`

### Secondary（MEDIUM confidence — 规划文档，非代码）
- `.planning/phases/109-spine-convergence/109-CONTEXT.md` — 用户锁定决策（本文档纠正其 3 处代码事实误判）
- `.planning/REQUIREMENTS.md` — SPINE-01/02、RELY-01、Out of Scope
- `.planning/ROADMAP.md` Phase 109 章节 — 4 条 success criteria + 顺序硬约束
- `.planning/phases/107-layered-presentation/107-07-SUMMARY.md` — 编排/chat 两入口的分组依据改造（affects 明确列了 `109`）

### Tertiary（LOW confidence）
- 无。本 phase 未使用 WebSearch / 外部文档 —— 全部结论来自本仓源码，无外部依赖需查。

---

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** — 零新增依赖，全部机制在仓内有实读先例
- Architecture（投影 service / 幂等 / 追溯）: **HIGH** — 模型字段、约束先例、async 用法均逐行核实；唯一 MEDIUM 项是"无 conversation 入口的 space 反查"（Open Q1，已建议限定范围规避）
- 调用方与影响面清单: **HIGH** — 经全仓 `rg` 穷举，实体 A/B 的边界用"mcp_tools 无 import agents.tools.coding_tools"的否定证据锁定
- Pitfalls: **HIGH** — 每条都指向实读代码中的具体行（裸 ORM 无 default、枚举漂移、NOT NULL、双白名单、lark_md 方言）
- 测试现状与缺口: **HIGH** — 逐文件核对；"SPA 四步无端到端测试"是穷举既有 test 文件后的否定结论
- `provenance` 落点: **HIGH** — 界面与导出的共同瓶颈点由代码路径唯一确定

**Research date:** 2026-07-30
**Valid until:** 2026-08-29（30 天。仅依赖本仓代码，无外部快速变动源；但 v0.20.0 蓝图 worktree 在并行开发，若其提前合并则 §3.4 的 `execution_plan` 来源会换成 `derive_execution`——CONTEXT 已确认同 schema，故映射层不受影响）
