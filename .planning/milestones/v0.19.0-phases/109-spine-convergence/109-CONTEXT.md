# Phase 109: 双脊柱合流（编排产出直连执行流 + 移除徒手创作路径） - Context

**Gathered:** 2026-07-30
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous — 推荐项自动采纳）

<domain>
## Phase Boundary

编排产出的技术方案可直接进入「选目标仓 → 配置分支 → 确认编码 → 飞书导出」的执行流，系统不再存在由对话模型徒手编写方案正文的产出路径，用户拿到的方案一定来自完整编排链路。

覆盖需求：SPINE-01, SPINE-02, RELY-01。

**Phase 内部顺序硬约束**：SPINE-01 **必须先于** SPINE-02——必须先有「编排产出直连执行流」的替代路径成立，才能安全砍掉当前 SPA 唯一的编码入口。计划的 wave 划分必须体现这条硬约束。

**边界内**：编排方案版本 → 执行侧对象的投影（幂等 + 追溯）、执行流入口接现行 §7 `execution_plan`、移除「对话模型徒手编写方案正文」的创作半边（保留执行半边）、草稿来源标志与「未经代码调研」双侧标注、送编码防护。
**边界外**：方案结构深度（DEPTH-01~05 已移交 v0.20.0，`process_runtime` 的 prompt/schema 冻结不做 DEPTH 向改动）；阶段流式与容器日志（Phase 110）；路由打分与分组呈现（105–107 已定版，本 phase 不改分数口径与呈现契约）。

**依赖输入（105–107 已产出）**：编排能稳定跑完并拿到可信路由结果（确定性 confidence、分组呈现、澄清超时出口、Stage 1 有界）。

</domain>

<decisions>
## Implementation Decisions

### 编排产出直连执行流（SPINE-01）
- **衔接方式取「投影」而非改写执行流**：把编排方案版本投影成执行侧对象（chat `CodingPlan`），复用 `create_coding_plan` 既有的执行半边（选仓 / 分支 / 确认编码 / 飞书导出）。理由：执行半边是 SPA 唯一编码入口且 MCP 执行链依赖其桥接行为，重写风险远高于投影。
- **投影时机取惰性**：用户在方案页显式点「进入编码」时投影，不在编排完成时预建（避免为未被采纳的方案批量建对象）。
- **幂等键 = `ArtifactVersion.id`（研究纠正 C-2）**：`TechnicalPlan` / `PlanVersion` 模型**已不存在**，Chassis v2 已泛化为 `delivery.Artifact` / `ArtifactVersion`。同版本重复投影返回既有对象、不新建；版本更新后允许新建投影且**旧投影保留**（历史可查）。
- 执行流入口接**现行 §7 `execution_plan`**：v0.20.0 蓝图的 `derive_execution` 保证同 schema，合并后执行流无缝换源，深度由 v0.20.0 提供。本 phase 不等蓝图。
- **好消息（研究结论）**：执行流四步**全部只依赖 chat `CodingPlan.id` 一个锚点**——投影出一条记录即四步全通；且 conversation runtime 返回"对话内最近 CodingPlan"，投影后前端无需新 API 即可取到。
- **坏消息（研究纠正 C-3）**：编排产出在 SPA 里**目前没有任何可操作呈现面**（`start_plan_research` 返回的 `artifact_version_id` 前端零消费，工具连中文标签都未登记，唯一展示面是项目工作台里只读的 `ArtifactTimeline.vue`）→ **「进入编码」入口必须新建**。
- **裁决 D-3（OQ-1）：本 phase 投影只做 chat 入口。** 无 conversation 的编排入口（workflow / MCP）投影时缺 `space` 来源（`ConvergenceSession` 无 space FK），反查有歧义；限定 chat 入口后 SC-1 的用户故事即完整成立，其余入口记 deferred。
- **裁决 D-4（OQ-4）：`start_plan_research` 的 chat 呈现只做最小可操作面。** 阶段流式/时间线严格留给 Phase 110，本 phase 不预建。
- **易静默失守点（研究提示，须写进验收）**：§7 用 `action: create` 而 chat 用 `change_type: add`——漏转换**不会崩、只会静默显示成 `create`**，测试必须显式断言字段映射。

### 移除徒手创作路径（SPINE-02，仅在 SPINE-01 成立后执行）
- **拆分而非删除**：砍掉「由对话模型徒手编写方案正文」的创作半边，**保留**选仓 / 分支 / 确认编码 / 导出的执行半边。不整体删除（REQUIREMENTS 的 Out of Scope 已明确）。
- **靶子是 chat `@tool`，不是 MCP 端点（研究纠正 C-1）**：仓内有**两个同名但完全无关**的 `create_coding_plan`——chat `@tool`（`agents/tools/coding_tools.py`，SPA 链，**本 phase 的唯一靶子**）与 MCP HTTP 端点（`mcp_tools/views.py:1842`，**早在 Phase 94 已 delegate 到统一编排**，是 SPINE-01 应当照抄的现成先例）。
- **MCP 桥接零回归的真实含义（研究纠正 C-1 续）**：MCP 执行链**从不调用**那个 chat 工具——桥接由 `mcp_tools/execution_service.py::_create_bridge_session` 用**裸 ORM** 自建 Conversation + CodingPlan + CodingSession。因此要保的是**两个模型的字段形状**：新增字段**必须带 default**，否则裸 `objects.create()` 会直接崩。SPINE-02 对 MCP 的工具行为耦合面实际为零。
- **裁决 D-1（OQ-2）：`update_coding_plan` 一并收窄。** 它的必填入参同样是 `tech_plan` + `affected_files`，是同一个徒手创作漏洞的**第二个门**；只收窄 create 则模型可改走 update 写正文，SPINE-02 的字面要求（"系统不再存在由对话模型徒手编写方案正文的产出路径"）不成立。两个门一起收窄。
- **裁决 D-2（研究缺口）：补 schema 漂移守护。** 该工具 schema 目前**没有任何漂移守护**，而 SPINE-02 的核心验收正是"结构上不可能"——必须补一条**正向不变量断言**（创作入参不存在于 schema），否则后人加回入参无人发现。
- **移除方式在 schema 层而非 prompt 层**：从工具 schema 移除创作入参/能力，使模型在结构上再也无法只凭对话生成方案正文；仅靠 prompt 约束不算达成 SPINE-02。
- **回归护栏先行**：SPA 与 MCP 两条编码链路的端到端守护测试**先绿再动刀**（这是 SPINE-01 → SPINE-02 顺序约束的具体落法）。
- **护栏缺口（研究结论，直接决定 wave 划分）**：MCP 侧护栏完整（6 组 delegate 守护 + 执行链 e2e）；**SPA 侧四步各有独立测试，但没有任何一条把「四步都还挂在同一个 `plan_id` 上」这条不变量锁住的端到端用例** → 该测试**必须新写且早于任何 schema 改动**。

### 草稿标注（RELY-01）
- 草稿**保留但显式标注**「未经代码调研」，不静默移除（保留应急路径）；标注必须同时出现在**界面与飞书导出物**两侧。
- 标注载体是**数据层来源标志**（如 `provenance: orchestrated | draft`，命名 planner 定），界面与导出据此渲染，不靠文案硬编码——避免新增产出路径时漏标。
- **送编码防护**：草稿默认**不可**直接送编码；确需送出必须显式确认，且编码上下文携带「未经调研」标志（下游可据此判断）。
- **裁决 D-5（OQ-3）：显式确认的载体取「请求体布尔字段」**，不新开独立端点（改动面更小、与既有执行流入口一致）。

### 幂等与追溯（SC-4）
- 幂等用 **DB 唯一约束**（方案版本 → 编码计划）+ `get_or_create` 语义，并发安全；不靠应用层查重（并发下会重复）。
- 追溯链保留完整 `WorkItem → PlanVersion → CodingPlan → MR`（复用既有追溯基建），投影时写入关联。
- 方案版本更新后允许新建投影，旧投影保留（历史可查，不覆盖）。

### Claude's Discretion
- 投影 service 的落点与命名、唯一约束的具体字段组合、`provenance` 枚举的取值命名与迁移形态由 planner/executor 按代码库惯例定。
- 观测埋点按 LOGGING-SPEC 补齐（投影动作、草稿送编码的显式确认、schema 层移除后的调用尝试均需留痕）。
- 前端「进入编码」入口与草稿标注的具体位置由 UI-SPEC 定稿。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `create_coding_plan`（chat 工具）— SPA 唯一编码入口 + MCP 执行链桥接；本 phase 拆其创作/执行两半。
- chat `CodingPlan` 与 `mcp_tools.McpCodingPlan` 两套模型（REQUIREMENTS 已把「合表为 canonical」列入 Future，本 phase 不合表）。
- 既有追溯链 `WorkItem → TechnicalPlan → PlanVersion → MergeRequest`（v0.17.0 Phase 101 建成，含 `ArtifactVersion` 反查器）。
- 飞书导出既有路径（方案导出）——草稿标注需覆盖该出口。
- 编排侧 `ConvergenceSession` / `stage_state` / `execution_plan`（§7）与 107 落的事件源。

### Established Patterns
- 服务层无状态类方法 + async ORM 走 `sync_to_async`；迁移 additive 优先。
- 工具 schema 用 pydantic（`server/agents/tools/` 与 `schemas/`），schema 变更会同时影响 LLM 可见能力与前端契约。
- 观测：structlog kv + category/component；后台任务带 `initiated_by_user_id`。

### Integration Points
- `create_coding_plan` 的调用方：SPA 前端编码入口、MCP `execute_work_item_repo_tasks` 链、可能的 workflow 节点（researcher 需列全）。
- 方案页前端（编排产出展示）→「进入编码」入口。
- 飞书导出渲染（草稿标注第二出口）。

</code_context>

<specifics>
## Specific Ideas

- 生产事故锚点：会话 `ccd817d9`——两个 `ConvergenceSession` 都停在 `clarify/waiting_clarification`，agent 等不到就**绕道 `create_coding_plan` 徒手编了一份方案**。Phase 107 的澄清超时出口断掉了「等不到」这一环，本 phase 的 SPINE-02 断掉「绕道徒手编」这一环——两者合起来才真正关闭该事故链。
- REQUIREMENTS Out of Scope 明确：不删除 `create_coding_plan`（拆分创作/执行两半而非删除）；两套 CodingPlan 不合表（Future）。

</specifics>

<deferred>
## Deferred Ideas

- 阶段流式输出、容器日志可见、阶段时间线 → Phase 110（复用 107 事件源）。
- 方案结构深度（DEPTH-01~05）→ 已移交 v0.20.0；`process_runtime` prompt/schema 冻结。
- 两套 CodingPlan 合表为 canonical → Future（REQUIREMENTS 已列）。
- 用追溯链自动生成弱标签把 golden set 推到 200+ → Future。

</deferred>
