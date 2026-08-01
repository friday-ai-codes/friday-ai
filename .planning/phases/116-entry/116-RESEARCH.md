---
phase: 116
slug: entry
kind: research
researched: 2026-08-01
domain: "入口收编（engine 分派 + 蓝图 intake + per-entry 开关）/ MCP 异步澄清协议 / 飞书导出与未确认标注 / 知识图谱物化与反查"
confidence: HIGH
evidence: "全部结论来自本 worktree（.claude/worktrees/v0.20-blueprint，分支 milestone/v0.20.0-blueprint）源码逐行核对，附 file:line；`validate_blueprint` 的最小骨架结论为 .venv 实跑验证（见 §A.2）；零外部依赖查询、零新增运行时依赖"
upstream:
  - .planning/phases/116-entry/116-CONTEXT.md
  - .planning/ROADMAP.md（Phase 116 SC-1~SC-4）
  - .planning/REQUIREMENTS.md（GATE-01, VIEW-05, VIEW-04, VIEW-02）
  - .planning/STATE.md（§13.2 并行纪律 / Pending Todos 顶部五条）
  - .planning/technical-blueprint/DESIGN.md §7 / §9 / §10 / §11
  - .planning/phases/115-ui/115-01-SUMMARY.md（五端点契约表）
  - .planning/phases/114-ai/114-05-SUMMARY.md（七端点契约表 + 提醒收件人口径）
requirements: [GATE-01, VIEW-05, VIEW-04, VIEW-02]
scope: "只覆盖『四条 SC 的实现机制怎么落 + 会静默假通过的地方在哪』。不覆盖 plan 切分、模块内部函数命名、markdown 版式（CONTEXT 已划归 Discretion）"
corrections: 4  # 本次核验推翻/修正了 CONTEXT 的四条判断，见 §0
---

# Phase 116: 入口收编与导出 - Research

**Researched:** 2026-08-01
**Domain:** `server/services/process_runtime/` 入口层 + `server/mcp_tools/` + `server/delivery/artifacts|api/` 导出面 + `server/knowledge/` 图谱链
**Confidence:** HIGH（判据全部实读，`validate_blueprint` 一节为实跑；唯一 MEDIUM 项是飞书 `create_document` 的 markdown 表达力上界，见 §C.4）

## Summary

CONTEXT 关于「本相位起点」的四条实测判断，本次逐条复核：**三条完全成立、一条需要重写**。更要紧的是核出**四处 CONTEXT 没看到、且会让某条 SC 表面通过而实际为零**的硬伤，其中两处足以单独让 SC-4 与 SC-3 的验收变成假绿：

1. **⭐ SC-4 的反查在现状下恒为空，且与图谱边质量无关。** `knowledge/related.py:18-22` 的 `_DEFAULT_RELATIONS` 是 `[HAS_PLAN, IMPLEMENTED_BY, RELATES_TO]`——**不含 `REFERENCES`**；而 `KnowledgeRelatedView`（`knowledge/api/views.py:150-176`）只接 `as_of` / `direction` / `max_hops` 三个 query 参数，**没有 `relations` 入参**，中间的 `DeliveryKnowledgeSearchService.get_related`（`knowledge/retrieval.py:135-146`）签名里也没有它。⇒ CONTEXT 写的「反查零新端点，只补一个换算键」**不成立**：哪怕 REFERENCES 边全部正确物化，`?direction=in&relations=REFERENCES` 里的 `relations` 会被静默丢弃，遍历只走三条默认关系，返回空数组。这是本相位最典型的「断言全绿而功能为零」——端点 200、边在库里、页面空白。修法是三处**纯追加**（view 参数白名单 → service 形参 → 前端 `getRelated` 参数），见 §D.5。

2. **⭐ 用错 engine 工厂不是「静默直通落空蓝图」，而是跨链污染 + 误导性失败。** 两个工厂的 deps 名单**有两个同名属性**：`research` 与 `merge`（`entrypoint.py:128-137` vs `:173-181`）。用 `build_orchestration_engine()` 驱蓝图会话，`_h_bp_repo_research` 拿到的是**旧链的** `ResearchDispatchAdapter`、`_h_bp_merge` 拿到的是 `ArchitectMergeAdapter`。逐 stage 推演（§A.3）的真实结局是：在 `reroute` 撞 `AttributeError: 'ResearchDispatchAdapter' object has no attribute 'aadvance_reroute'` → engine 通用 except（`engine.py:94-101`）落 `fail` 终态。**「一路 DONE 落空蓝图」不可能发生**——唯一通向 `STAGE_DONE` 的出边是 `ai_review.review_passed`，而 `deps.review` 缺失时 `_h_bp_ai_review` 走的是 `needs_clarification`（`builtin_processes.py:809-814`）。但真实形态**在一个方向上更糟**：若会话已推进到 `merge`，`ArchitectMergeAdapter.merge` 会经 `ArtifactService.create` 落一份 **v0 形状的 `technical_plan` content**（`architect_merge_adapter.py:252-259`），把蓝图会话的产物指针钉到一份非 `blueprint/v1` 的版本上。变异用例的**期望断言要按这个真实形态写**，照 CONTEXT 的「断言 DONE」会写出一条恒绿的假用例。

3. **⭐ 续驱点是八个不是四个。** 全仓非测试的 `build_orchestration_engine()` 调用点实测有 8 处（§A.4 表）。CONTEXT 点名的四处里，`subagent/api/callbacks.py:447` 经核实**对蓝图会话不可达**（它按 `last_output.source == "plan_research"` 路由且读 `plan_session_id`，而蓝图容器写的是 `blueprint_research` / `blueprint_session_id`，`blueprint_research_adapter.py:471-484`）；而 CONTEXT 没点名的 `answer_resume.py:102`、`feishu/callbacks/plan_clarify_callback.py:242`、`plan_deepen_service.py:99`、`feature_solution_service.py:222` 里，**前两个是真续驱点**。同一段代码里还藏着 chat 入口的**第二条断链**：`_schedule_chat_plan_resume` 除了续驱还负责 **barrier 回灌**（`callbacks.py:482`），而蓝图 barrier（`callbacks.py:2150-2177`）只续驱**不回灌** ⇒ chat 入口切蓝图后，对话侧的 blocking task 永远等不到结果（§A.5）。

4. **⭐ renderer 注册契约拿不到 `blueprint_status`。** `ContentRenderer = Callable[[dict], str]`（`delivery/artifacts/registry.py:16`），`render_markdown(artifact_type, content)`（`:65-70`）只透传 content，而「未确认」判据的唯一事实源 `Artifact.blueprint_status` **不在 content 里**。CONTEXT 设计的 `render_blueprint_markdown(content, *, blueprint_status)` 与注册表签名不兼容。解法在 §C.2：把 `blueprint_status` 做成**必填 keyword-only**，注册分支传 `""`（`"" ∉ {confirmed, implementing, implemented}` ⇒ 标注照出，fail-safe 方向正确），两个权威面（导出端点 + `ArtifactTimelineSerializer`）传真实状态——**关键不变量是「没有任何取值能关掉标注」，而不是「只有一个调用点」**。

CONTEXT 成立的三条起点：`_h_bp_intake` / `_h_bp_decompose` 确为零副作用（`builtin_processes.py:320-330`，后者 docstring 逐字写着「功能点拆分在 116 入口切换时接线」）；`blueprint_spec_gate.run` 无 `session.current_artifact_version_id` 即判 `needs_clarification` + warning（`:135-149`）且全仓无任何代码建蓝图初始 Artifact；`AIPlanResearchNode._map_terminal` 把 `DONE` 无条件映射成 `completed` 并把 `plan` 喂下游（`plan_research.py:544-570`），与 `review_passed → STAGE_DONE`（`builtin_processes.py:949`）+ `pending_review ∈ _HUMAN_OWNED_STATUSES`（`blueprint_resume.py:78-87`）合起来正面违反 RELY-01。

**Primary recommendation:** SC-1 先落**蓝图 intake + `build_engine_for_session`**两件事，其余四个入口的实现路径各自薄接（真正的工作量在 intake，不在入口）；`build_engine_for_session` 必须**同时**改 `blueprint_resume` 的反向守卫为双向（现只挡「蓝图工厂驱旧会话」，不挡「旧工厂驱蓝图会话」，`blueprint_resume.py:132-143`）——把两个方向都做成 LOUD 是本相位唯一能物理杜绝 §0.2 那类污染的手段。SC-2/SC-3/SC-4 三条互不依赖、可并行；**SC-4 的第一个 task 必须是把 `relations` 参数打通**（否则后面所有边的工作都无法被验收），SC-3 的第一个决策是 renderer 签名（§C.2）。

---

## User Constraints (from CONTEXT.md)

### Locked Decisions

**同步点 2 拆分（SC 逐条）**：SC-1 本相位只交付「蓝图 intake + `build_engine_for_session` + 四入口各自的蓝图实现路径 + per-entry 开关（默认全 `technical_plan`）+ feature list 的 `feature_segments → feature_points` 映射 + 旧链残余流量可观测」；**默认值翻成 blueprint、旧 process 退役收口、`TechPlanCard`/`NodeDataTab`/`ArtifactTimeline` 触点升级、workflow 节点终态 `pending_review → waiting_event` 挂起**一律顺延同步点 2 后的收尾 plan。SC-2 / SC-3 / SC-4 **全部**本相位交付。

**必须同步改的文本（plan 阶段一次改完，⛔ 不许只写在 PLAN 里）**：`ROADMAP.md` Phase 116 SC-1 替换文案；`REQUIREMENTS.md` GATE-01 标 `PARTIAL`（比照 VIEW-04 @115 写法，Traceability 的 Phase 列写「Phase 116（实现路径 + 开关）+ 同步点 2 后收尾（默认切换）」）；`REQUIREMENTS.md` VIEW-04 由 PARTIAL 转 Complete；若代码预览源码正文读面被顺延，**必须改写 VIEW-02 里那句「顺延 Phase 116」**。

**SC-1**：切换粒度 = per-entry 运行时开关 `SettingKeys.BLUEPRINT_ENTRY_SWITCH`（JSON 四键 `workflow`/`chat`/`mcp`/`feature_list`，值域 `technical_plan | technical_blueprint`，默认四键全 `technical_plan`），读取复用 `aget_json_setting` + 畸形回默认；⛔ 不做 shadow 双跑。engine 工厂按 `process_type` 分派（`build_engine_for_session(session)` 放 `entrypoint.py`），全部续驱点改成它，必须有一条「换回 `build_orchestration_engine()` ⇒ 用例转红」的变异用例。蓝图 intake 纯追加 `start_blueprint_orchestration(...)`；`_h_bp_intake` 建 `Artifact(blueprint_status=researching)` + 落 `blueprint/v1` 骨架；`_h_bp_decompose` 落实功能点拆分（复用 `call_source = blueprint_decompose`，⛔ 不新增枚举值；有 `feature_segments` 时直接采用不走 LLM）。⭐ `meta.project_id` 必须从入口权威上下文推导，**推不出就拒绝发起**。旧 process 退役观察 = 打 `technical_plan_entry_used` caller 事件 + 注册项上方加注释；⛔ 不注销注册、⛔ 不动六个冻结文件。

**SC-2**：`create_feishu_technical_plan` 工具名与既有响应键**一个都不改**，仅**追加** `blueprint_artifact_id` / `blueprint_status` / `pending_clarifications[]` 并把 `status` 落 `partial`。新增 `get_technical_blueprint`（按 `artifact_id`）与 `answer_blueprint_clarification`（按 `thread_id`），⛔ 不建第三个 list 工具。寻址键一律 `artifact_id`。作答走 114 的 `blueprint_review_action` / `BlueprintLifecycleService`，⛔ 绝不在 MCP 层直写 `BlueprintThread`、⛔ 不进程内自调 REST。「立即返回 + 轮询取件」，⛔ 不做长轮询/推送。assumptions 三档（`strict`/`balanced` 默认/`assume_more`）只管「问不问」不管「等不等」，⭐ `assume_more` 绝不等于 `skip_clarification`。澄清同时推飞书卡片，收件人 = `BlueprintReviewer` ∪ 会话发起人（反查会话**必须带 `process_type="technical_blueprint"` 过滤**），整段 best-effort，封装成**一个** `blueprint_notify.py`。

**SC-3**：新建 `services/process_runtime/blueprint_render.py`，在 `builtin_types.py` 加 `schema_version` 判别分支（与 111 的 validator 分支同处同形），⛔ 绝不改冻结的 `render.py`。⭐「未经确认」标注生成在 renderer 内部、单一判据、**导出器没有关掉它的入参**（⛔ 不给 `include_watermark`）；前端 `BlueprintViewerHeader` 用同一判据并配变异用例。新增 `POST artifacts/<uuid>/blueprint/export-feishu/` 与 `GET .../export-feishu/availability/`，**两个都挂 `_aassert_project_scope`**；导出留痕落事件 + Interaction Ledger，⛔ **绝不写进 `ArtifactVersion.content`**；上游失败如实回错（400/502 + 中性 detail），异常文本过 `redact_secrets_in_text`，⛔ 不回显上游 body、⛔ 不静默 200 空结构。导出内容 = 六段全量 + `requirement_spec` + `must_haves` + 决策记录附录 + 引用脚注；**批注一律不导出**。

**SC-4**：触发点唯一 = `ArtifactService.add_version` 内按 `content.schema_version == "blueprint/v1"` 门控投递 `aschedule_ingestion(IngestionRequest("blueprint", str(artifact_id), "blueprint_version_created"))`。实体 id = `generate_entity_id("tech_plan", "blueprint", str(artifact_id))`，⛔ 不新建 `EntityKind`；`space_id` 由 `meta.project_id → Project.space_id` 反查，**反查不到就不产事件并 warning**。边一律走 `EdgeSpec` + `apply_edge_specs`，⛔ 不裸调 `graph_store`：`citations → REFERENCES`（`exclusive=False`、append-only、**同目标多条 citation 聚合进一条边的 metadata**）；`meta.project_id → RELATES_TO`（`exclusive=True`）。⭐ **目标实体不存在的 spec 必须先过滤掉**并把丢弃计数记进 `sampling` 事件。反查复用既有 `knowledge-related`；蓝图侧在 `GET .../blueprint/` 响应里**纯追加** `knowledge_entity_id`，⛔ 不让前端复制 uuid5 规则。前端在 `BlueprintAssociationsSection.vue` 补两块，那条 `toHaveBeenCalledTimes(0)` 用例**改判据不删用例**。

**顺带闭掉的缺口**：`blueprint-gate/` 补项目范围闸，⭐ 用「读不到 `meta.project_id` 回中性 404」的更严变体；`confirm/` 的 409 补 `blocked_reason` 键；111-MN-12「权限口径」结案并在 STATE 划掉。

### Claude's Discretion

各新模块的内部函数切分、`blueprint_render` 的 markdown 版式细节（heading 层级 / 表格列序 / 脚注编号）、两个新 MCP 工具的入参命名细节与 `TOOL_SCHEMA_SNAPSHOT` 条目文案、normalizer 的 `content` 提炼文本形状、导出留痕的事件字段名、测试组织与 `data-testid` 命名。plan 切分自行决定，但需满足两条：①「代码预览源码正文读面」必须是**最后一个可独立顺延**的 plan；② 与同步点 2 相关的默认切换**不得**混进任何主干 plan。

### Deferred Ideas (OUT OF SCOPE)

默认入口切换 + 旧 process 收口 + 三处触点升级 + workflow 节点终态 HITL 挂起的下游消费形态（→ 同步点 2 后）；115-MN-03 的存在性预言机整体契约改版；`redact_secrets_in_text` 不覆盖数据库连接串 + 全仓 `error=str(exc)` 未脱敏（→ 独立清理相位）；澄清提醒的站内 / Web Push 通道；蓝图正文 block 编辑器前端面（`edit-blocks/`）；`content.execution_plan` 段的前端呈现；`ConvergenceSessionService.areopen_stage` 的新事件；蓝图列表语义搜索 / 母子蓝图 / 段级权限 / golden set 扩样 / charter 自动调参 / 强制换模型交叉实验；图谱边的「引用被删除即失效」语义（本相位定为 append-only）。

---

## Phase Requirements

| ID | 描述 | 本次调研支撑 |
|----|------|-------------|
| **GATE-01** | 四入口统一走蓝图编排 + MCP 不再 skip_clarification | §A（intake 骨架实跑验证 / 八个续驱点清单 / 工厂分派与 LOUD 化设计 / chat 断链两条）+ §B（MCP 两工具的落点四处 + 作答三道闸 + 档位机制的真实可配面）。GATE-01 标 **PARTIAL**：默认切换顺延 |
| **VIEW-05** | 飞书导出含六段全量 + 决策附录；未确认版本界面与导出物均带标注 | §C（renderer 注册契约的签名冲突与解法 / 十段 + 附录的数据来源逐段核对 / availability 三判据 / 留痕不进 content 的两条落点 / 事件常量的 `len == 21` 锁） |
| **VIEW-04** | 蓝图关联双向可查（本相位由 PARTIAL 转 Complete） | §D（`add_version` 单一 choke point 的**一处例外** / natural key 与 space 反查 / 边的四类目标可用性与 FK 过滤 / ⭐ 反查 relations 断链与三处纯追加修法） |
| **VIEW-02** | 引用预览可达（代码预览源码正文读面） | §E.3（全仓确无 path+行区间读正文的 SPA 面；MCP 侧逻辑全部内联在 View 方法里、不可直接 import ⇒ 需先抽服务层，成本据此评估） |

---

## §0 CONTEXT 四条判断的核验结论（先看这个）

| # | CONTEXT 原判 | 核验 | 证据 |
|---|-------------|------|------|
| 0.1 | `_h_bp_intake` / `_h_bp_decompose` 零副作用；全仓无代码建蓝图初始 Artifact | ✅ **成立** | `builtin_processes.py:320-322` / `:325-330`（后者 docstring 逐字「功能点拆分在 116 入口切换时接线」）；`blueprint_spec_gate.py:135-149` 无版本即 `needs_clarification`；全仓 `ArtifactService.create` 的调用者只有 `architect_merge_adapter.py:252`（旧链）与 `builtin_processes.py:285`（echo 测试链），**蓝图链零调用** |
| 0.2 | 四个续驱点硬编码 `build_orchestration_engine()`；用错工厂 ⇒ 全 stage 直通、一路 DONE、落空蓝图、日志无痕 | ⚠️ **需重写**：调用点是 **8 个**且 CONTEXT 点的 `callbacks.py:447` 对蓝图不可达；失败形态是**跨链污染 + 在 `reroute` 落 FAILED**，silent-DONE 结构上不可能 | 见 §A.3 / §A.4 |
| 0.3 | 蓝图 `DONE` = 待人审；`_map_terminal` 把 DONE 映射成 completed 喂下游 ⇒ 现在翻默认违反 RELY-01 | ✅ **成立且更强** | `builtin_processes.py:949-950`（`review_passed`/`review_exhausted` 双出边都到 `STAGE_DONE`）+ `blueprint_resume.py:78-87` + `plan_research.py:544-570`。**更强的一条**：`_map_terminal:559` 还会调 `render_merged_plan_markdown(av.content)` 产 `plan_markdown` —— 对蓝图 content 那是个**结构性空壳**，`human_approval(plan_feishu)` 落的审批文档会近乎空白（不只是「未经人审」，是「未经人审 + 看不见内容」） |
| 0.4 | 反查零新端点，只补 `knowledge_entity_id` 换算键 | ❌ **不成立** | `related.py:18-22` 默认关系不含 `REFERENCES`；`knowledge/api/views.py:150-176` 无 `relations` 参数；`retrieval.py:135-146` 形参也没有。见 §D.5 |

---

## Part A —— SC-1 入口收编

### A.1 蓝图 intake 到底要建什么

`technical_blueprint` 注册（`builtin_processes.py:984-991`）：`artifact_type="technical_plan"`、`initial_stage="intake"`。会话由 `ConvergenceSessionService.create_session` 建，`start_orchestration`（`entrypoint.py:32-86`）把 `"technical_plan"` **写死在 :78**——所以 `start_blueprint_orchestration` 是纯追加的第二个函数（签名对齐，`process_type="technical_blueprint"`），⛔ 不要给 `start_orchestration` 加 `process_type` 形参（那会让旧链四个入口共享一个可传错的开关）。

**intake 必须产出的三样东西**（缺任一，下一个 stage 就废）：

| 产出 | 谁读它 | 缺了会怎样 |
|------|--------|-----------|
| `Artifact(artifact_type="technical_plan", blueprint_status=researching)` | 全部 20 个蓝图端点、`_abp_load_artifact`（`builtin_processes.py:453-463`）、`blueprint_resume._aload_artifact`（`:280-289`） | 没有挂载点 |
| 一份过得了 `validate_blueprint` 的 `blueprint/v1` v1 版本 | `blueprint_spec_gate._aload_current_version`（`:516-523`） | 规格门恒判 `needs_clarification` + `blueprint_spec_gate_no_artifact_version` warning（`:138-143`），会话卡死在 spec_gate |
| `session.current_artifact_version` **指针** | 上面两个 helper 全靠 `getattr(session, "current_artifact_version_id")` | 同上；且 `_amap_blueprint_status` / `_ahas_open_blocking_blueprint_threads` 全部读到 None 并**静默**降级 |

⚠️ 第三样有个契约细节：`StageOutcome.current_artifact_version` **只在非 None 时才透传**给 transition（`engine.py:108-119` 有整段注释解释为什么——无条件透传会把每次不产版本的转移都把指针抹成 NULL）。所以 intake 的 `StageOutcome` 必须显式带 `current_artifact_version=artifact.current_version_id`。

**`blueprint_status` 的第一跳**：状态机入口边只有 `"" → researching`（`blueprint_resume.py:333-341` 与 `_abp_mark_drafting`（`builtin_processes.py:477-490`）两处都在做这一跳）。intake 直接建成 `researching` 可以省掉这一跳，但**必须经 `BlueprintLifecycleService.transition`**（INV-6），⛔ 不裸写字段——`test_blueprint_inv6_guard.py` 的三条正则会逮到。

### A.2 最小合法骨架（实跑验证）

`blueprint/v1` 顶层 11 个必填键（`blueprint_schema.py:123-135`）。用 `.venv/bin/python` 直接加载 `blueprint_schema.py`（纯 stdlib + jsonschema，不需要 Django）实跑：

```python
{
  "schema_version": "blueprint/v1",
  "meta": {"title": <非空>, "project_id": <非空>},           # required: title, project_id
  "requirement_spec": {"goal": [], "feature_points": []},     # required: goal, feature_points
  "repo_associations": [],
  "current_state_analysis": [],
  "implementation_overview": {"requirement_narrative": [], "items": []},
  "api_contracts": [],
  "impact_analysis": {"business_impact": [], "affected_features": []},
  "interaction_flows": [],
  "must_haves": {"truths": [], "artifacts": [], "key_links": []},
  "citations": {}
}
```

实跑结果（`validate_blueprint` 返回值逐字）：

| 变体 | 结果 |
|------|------|
| A. 上面的最小骨架 | **`(True, None)`** ✅ |
| B. 骨架 + `goal` 一个 paragraph block + 一条 `feature_point{id,title,intent}` | **`(True, None)`** ✅ |
| C. `meta.project_id = ""` | `(False, "$.meta.project_id: '' should be non-empty")` |
| D. 缺 `must_haves` | `(False, "$: 'must_haves' is a required property")` |
| E. 缺 `meta` | `(False, "$: 'meta' is a required property")` |
| F. block 引用了不在引用池里的 citation | `(False, '引用 cit_missing 不存在于文档级引用池')` |
| G. `feature_points` 出现重复 id | `(False, "requirement_spec.feature_points 存在重复 id 'fp_1'")` |
| **H. 整份 content 去掉 `schema_version`** | **`(True, None)`** ⚠️ 见 P-2 |

另实测 `iter_blocks(最小骨架) == []`（零 block 合法），变体 B 产出 `[('requirement_spec.goal', 'bp_goal_1')]`。

⇒ **骨架的自由度比想象大**：六段全部允许空数组/空对象，`meta.title` + `meta.project_id` 是仅有的两个必须有真实值的字段。建议 intake 落的形状是「最小骨架 + `requirement_spec.goal` 装一个承载需求原文的 paragraph block」——因为规格门的四维打分正是读 `_goal_text(content)`（`blueprint_spec_gate.py:632`）/ `_feature_points` / `_constraints`，`goal` 空串会让第一轮打分拿不到任何输入而 fail-closed 到满歧义。

### A.3 用错工厂的真实形态（变异用例的期望值按这个写）

两个工厂的 deps 名单（`entrypoint.py:128-137` / `:173-181`）：

| | orchestration | blueprint |
|---|---|---|
| 独有 | `router` `recall` `clarify` `classify` | `spec_gate` `route` `confirm_gate` `repo_plan` `review` |
| **同名** | **`research` = `ResearchDispatchAdapter`** | **`research` = `BlueprintResearchAdapter`** |
| **同名** | **`merge` = `ArchitectMergeAdapter`** | **`merge` = `BlueprintMergeAdapter`** |

十个 `_h_bp_*` handler 一律 `getattr(getattr(engine, "deps", None), "<name>", None)`。用 `build_orchestration_engine()` 从 `intake` 驱一条蓝图会话，逐 stage 推演：

| stage | 取到的 dep | 行为 | 出边 |
|-------|-----------|------|------|
| `intake` / `decompose` | — | 无副作用 | → `spec_gate` |
| `spec_gate` | `None`（无 `spec_gate`） | pass-through | `spec_locked` → `route` |
| `route` | `None`（旧链叫 `router` 不叫 `route`） | pass-through，**不写 `routing` 键** | `routed` → `repo_research` |
| `repo_research` | ⚠️ **`ResearchDispatchAdapter`** | `dispatch(session)`：`session.routing` 为空 ⇒ 返回 `{"skipped": "no_candidates"}`（`research_adapter.py:69-71`），**不抛异常**；`aall_research_tasks_terminal` 零 task 返 **True**（`research_aggregation.py:67-69`） | `research_complete` → `reroute` |
| `reroute` | ⚠️ **`ResearchDispatchAdapter`** | `adapter.aadvance_reroute(session)` → **`AttributeError`**（该方法只在 `blueprint_research_adapter.py:1049`） | engine 通用 except（`engine.py:94-101`）→ `transition(session, "fail")`，`error = {"stage":"reroute","exception":"AttributeError","message":"…"}` |

⇒ **终局是 FAILED，不是 DONE**。且 `STAGE_DONE` 唯一入口是 `ai_review.review_passed` / `review_exhausted`（`builtin_processes.py:949-950`），而 `deps.review` 缺失时 `_h_bp_ai_review` 走 `_abp_ensure_blocking_clarification` + `needs_clarification`（`:809-814`）——**silent-DONE 在结构上不可能**。

⚠️ **但「更糟的那个方向」真实存在**：若一条已推进到 `merge` 的蓝图会话被错工厂续驱，`_h_bp_merge` 会调 `ArchitectMergeAdapter.merge(session)`（`architect_merge_adapter.py:195`）。它的 `_handle_pass` 经 `ArtifactService.create(ARTIFACT_TYPE_TECHNICAL_PLAN, merged, …)`（`:252-259`）落一份**v0 形状**的 content，并把 `artifact_version_id` 回传，`_h_bp_merge` 据此设 `current_artifact_version` → 蓝图会话的产物指针指向一份非 `blueprint/v1` 的版本。**这一条才是要写进变异用例的最坏形态**。

**同样重要的第二把锁**：旧续驱器 `resume.adrive_convergence_session_to_pause_or_terminal` 的 `waiting_clarification` 短路判据是 `ClarificationService().ahas_pending(session.id)`（`resume.py:53-57`）——蓝图用的是 `BlueprintThread`，这个判据对蓝图会话**恒 False** ⇒ 蓝图的三个 pausable stage 一个都短路不了，self-loop 会被推到 `max_steps` 然后落 `advance_step_limit` FAILED。**所以「用错工厂」在实践中往往表现为「用错工厂 + 用错 driver」两个错误叠加**，PLAN 的分派设计必须把 engine 与 driver 一起换。

**怎么让它 LOUD**：`blueprint_resume.py:132-143` 已有一半守卫（蓝图 driver 拒非蓝图会话，warning + no-op）。缺的是**反方向**。推荐两道：

1. `resume.adrive_convergence_session_to_pause_or_terminal` 顶部加一条对称守卫：`session.process_type == BLUEPRINT_PROCESS_TYPE` ⇒ 记 `caller` 级 `wrong_driver_for_blueprint_session` 并**拒绝驱动**（no-op 返回）。理由与既有那条守卫逐字同源：「调用方传错会话是 bug，不是该会话该失败」。
2. `build_engine_for_session(session)` 内部：`process_type` 不在 `{technical_plan, technical_blueprint, echo}` ⇒ 落 caller 事件；并给 `_h_bp_*` 组一条**共享的 deps 自检**——蓝图 stage 取到的 `research`/`merge` 若不是蓝图 adapter 实例（`isinstance` 检查），直接 `_abp_ensure_blocking_clarification` + `needs_clarification`，而不是把旧链 adapter 跑起来。这一条是唯一能挡住 §A.3 那份 v0 content 的手段。

### A.4 八个 `build_orchestration_engine()` 调用点（实测，非测试）

| # | 位置 | 性质 | 蓝图会话可达？ | 本相位处置 |
|---|------|------|---------------|-----------|
| 1 | `workflows/nodes/ai/plan_research.py:361`（`_build_engine`） | workflow 入口 + 节点重入续驱 | ✅ 是（开关开启后） | **必改** → `build_engine_for_session` |
| 2 | `agents/tools/plan_research_tools.py:134` | chat 入口首驱 | ✅ 是 | **必改** |
| 3 | `mcp_tools/orchestration_delegate.py:179`（`skip_clarification=True`） | MCP 入口首驱 | ✅ 是 | **必改**；⚠️ `skip_clarification` 对蓝图链**无意义**（蓝图工厂没有 `clarify` dep），分派时不得把它当参数传下去 |
| 4 | `services/process_runtime/answer_resume.py:102` | **澄清作答后的通用续驱**（飞书回调 91-03 + 会话端点 91-04 共用） | ✅ 是（缺省 engine 分支） | **必改**（CONTEXT 未点名）。它同时硬编码了 `resume.adrive_…`（`:103`），两处一起换 |
| 5 | `feishu/callbacks/plan_clarify_callback.py:242` | 飞书澄清卡回调续驱（带 `node_execution_id`） | ✅ 是（workflow 蓝图会话的澄清卡走这条） | **必改**（CONTEXT 未点名） |
| 6 | `initiatives/services/feature_solution_service.py:222`（`force_confirm=True`） | feature list 入口 | ✅ 是 | **必改**；⚠️ `force_confirm` 注入的是旧链 `ClarifyAdapter` 的题目组装器，蓝图链无对应面 —— feature list 切蓝图后「强制确认关联仓」由蓝图自己的 `repo_confirmation` 硬门承担，**不要试图把 `force_confirm` 移植过去** |
| 7 | `initiatives/services/plan_deepen_service.py:99` | plan deepen（独立业务，非蓝图入口） | ❌ 否（自己建 session，恒 technical_plan） | 不改（可改成分派以求一致，属 Discretion） |
| 8 | `subagent/api/callbacks.py:447`（`_schedule_chat_plan_resume`） | chat 容器回调续驱 + barrier 回灌 | ❌ **不可达** | **不改**；但见 §A.5 —— 这里有另一个必须补的洞 |

**#8 为什么不可达**（三重）：分支条件是 `last_output["source"] == "plan_research"`（`callbacks.py:128`），而蓝图容器写 `"blueprint_research"` / `"blueprint_repo_plan"`（`callbacks.py:2003` / `:2287`，派发侧 `blueprint_research_adapter.py:471,483`）；函数体读 `lo.get("plan_session_id")`（`:422`），蓝图写的是 `blueprint_session_id`；再加 `entrypoint == CHAT` 守门（`:430`）。三条任一都拦得住。

### A.5 chat 入口的两条断链（本相位必须一起补，否则「chat 具备可执行路径」是假的）

**断链一：barrier 永不回灌。** `_schedule_chat_plan_resume` 干两件事——(d/e) 续驱 engine、(f/g) 用 `BarrierManager.task_completed(str(plan_session.id), result)` 把结果回灌 chat 会话（`callbacks.py:468-488`）。蓝图侧的 `_trigger_blueprint_research_barrier`（`:2150-2177`）与 `_trigger_blueprint_repo_plan_barrier`（`:2377-2396`）**只做续驱、不回灌**。而 chat 工具在挂起时确实注册了 blocking task：`register_blocking_task(conversation_id, {"task_id": str(session.id), "task_type": "plan_research", …})`（`plan_research_tools.py:246-256`）。⇒ chat 入口切蓝图后，对话会永远停在「深入调研容器运行中…」。

**断链二：健康的挂起被报成失败。** `plan_research_tools._maybe_suspend`（`:209-270`）两个分支都是旧链判据：`ClarificationService().ahas_pending` 对蓝图恒 False；`aall_research_tasks_terminal` 在蓝图卡在 `spec_gate` 时（零 RepoResearchTask）返 True。⇒ 一条正在等 `BlueprintThread` 澄清的健康会话会穿过 `_maybe_suspend` 返回 None，落到 `_map_terminal(session)`（`:274-297`）——`status != DONE` ⇒ 返回 `ToolResult(success=False, error="plan session failed")`。**用户看到「方案编排失败」，其实系统在等他回答问题。**

⇒ PLAN 必须为 chat 入口提供蓝图版的 `_maybe_suspend` / `_map_terminal`（判据换成 `BlueprintThread` open+blocking 与 `blueprint_status`），并在蓝图 barrier 里补一条**与 `entrypoint == CHAT` 对称的**回灌分支。这两条不做，SC-1 的「chat 具备真实可执行路径」验收不成立。

### A.6 per-entry 开关的落点

`SettingKeys` 的蓝图块在 `system/models.py:173-200`（四个键，全部「常量 + JSON 形状注释」，无 migration）。新键**逐字照抄这个形状**追加。读取用 `aget_json_setting(key, default)`（`system/settings_service.py:139-153`）——它已经做了「空值/非 JSON/非 dict 一律回默认」的三重兜底，且**不走 60s 缓存**（改设置立即生效，符合「回滚是改一个设置值」）。

⚠️ **返回类型只有 `dict`**（`:139` 签名 `-> dict`）。四键 JSON 正好合适，但逐键取值时仍要 `str(raw.get("workflow") or "")` 并对非法值回落 `technical_plan`——`aget_json_setting` 只保证外层是 dict，**不校验内层**（`BLUEPRINT_SPEC_GATE_CONFIG` 的消费者 `aload_spec_gate_config:257-268` 就是逐字段强转的先例）。

### A.7 `meta.project_id` 的四条推导链（含一个陷阱）

| 入口 | 权威上下文 | 推导 |
|------|-----------|------|
| workflow | `context.workflow_execution.space`（`_resolve_space`，`board_split_review.py:50-55`） | Space → Project：**复用 `_aresolve_project(space)`**（`board_split_review.py:58-69`，优先 `feishu_project_key` 命中、否则首个），`plan_research._send_clarify_card:470` 已是这个用法 |
| chat | `Conversation.created_by` / 会话所属 space | 同上（chat 侧已有 space 上下文） |
| **MCP** | `McpWorkItemContext.space` | ⚠️ **陷阱**：该字段是 `projects.Space` 的 FK（`mcp_tools/models.py:276-282`），而 `technical_plan_service.py:488` 把它当成 `"project_id"` 键回给调用方。**`meta.project_id` 要的是 `initiatives.Project.id`**（范围闸 `_ais_project_member` 查 `ProjectMember.filter(project_id=…)`，`blueprint_review_views.py:244-251`）。直接把 `context.space_id` 塞进 `meta.project_id` ⇒ 该蓝图**全部 20 个端点恒 400、图谱恒不入、导出恒不可用**。必须过 `_aresolve_project` |
| feature list | `feature_meta.project_id` | 已经是 Project id，直接用 |

「推不出就拒绝发起」的形态：⛔ 不建 session、⛔ 不建 artifact、如实回错。四个入口各自的错误出口已有先例——workflow 走 `NodeResult(status="failed", error=…, next_handle="error")`（`plan_research.py:194-199` 的 `missing_requirement` 范式）、chat 走 `ToolResult(success=False, error=…)`（`plan_research_tools.py:96-99`）、MCP 走 `error_response(code, detail)`。

### A.8 旧链退役观察

`technical_plan_entry_used` 事件的落点：**`start_orchestration` 内部**（`entrypoint.py:77`）是唯一能覆盖全部四个入口且不碰冻结文件的地方——四个入口全部经它建会话。字段：`entrypoint`（函数已有形参）、`initiated_by_user_id`（已有形参）、`category="caller"`、`component="process_runtime"`。⛔ 不要在四个入口各打一条（会漏 `plan_deepen` 那类非入口调用方，也会四份漂移）。

---

## Part B —— SC-2 MCP 异步澄清协议

### B.1 新工具的四处落点（113-02 范式，逐处实读）

| 落点 | 位置 | 要加什么 |
|------|------|---------|
| View | `mcp_tools/views.py` | `class XxxView(McpToolView)` + `tool_name`；`post` 三段式 `_begin` → `_validate` → `_record`（基类 `:238-325`）。`_begin` 已处理 `bind_source(MCP)` + `request.auth is None → 401`；`_record` 已顺带落 `RequestMetric(route=f"mcp:{tool_name}")`（`:300-308`）⇒ **观测规范里「新增请求入口纳入 QPS/错误率/时长」自动满足，无需另写** |
| 路由 | `mcp_tools/urls.py`（现 35 条 `path`） | `path("tools/<name>/", XxxView.as_view(), name="mcp-tool-<kebab>")` |
| 序列化器 | `mcp_tools/serializers.py` | 请求 serializer + `TOOL_SCHEMA_SNAPSHOT`（`:830`）条目（`{"request": [...], "response": [...]}`，键名逐字） |
| 双守门 | `tests/mcp_tools/test_schema_snapshot.py` + `test_skills_snapshot_guard.py` | ⚠️ 后者在本 worktree **恒红**（`skills/` 是空目录，STATE Pending Todos 已登记为环境项），别把它的红当成本相位引入 |

`create_feishu_technical_plan` 的既有契约（`serializers.py:1092-1116`）：request 9 键、response 以 `technical_plan_id` / `context_id` / `project_id` / `plan` / `markdown` / `repository_tasks` / `evidence` / `feishu_document` / `comment` / `status` 开头。**追加三键即可**，`status` 的 `partial` 是既有三态之一（`technical_plan_service.py:41-43` 映射到 `McpWorkItemTechnicalPlan.Status`，`:411-413` 已有 `partial` + `orchestration_pending` 的 retry_state 形态）——调用方零破坏这条成立。

### B.2 作答复用 114 通道：三道闸逐条落实

`answer_blueprint_clarification` 应内部走 `BlueprintReviewThreadAnswerView`（`blueprint_review_views.py:607-652`）**同一套 service 调用序**（⛔ 不进程内自调 REST）。那条序列的三道闸逐字是：

1. **`_aload_action_context`**（含 `_aassert_project_scope`）→ `:643-645`。PAT 认证下 `request.user` 就是 token owner，`_ais_project_member` 照常成立。
2. **`is_blueprint_editable(artifact)` 在 `record_answer` 之前** → `:648-649`，越界 400 且 DB 一字未动（114-MJ-04）。
3. **`kind == ai_review_finding` 一律 400** → `:623-628` 的双重堵：端点分流 + 回灌链 `REFLOW_KINDS = (ThreadKind.AI_CLARIFICATION,)`（`blueprint_reflow.py`）自身 fail-closed。

⇒ MCP 工具**必须复刻这三道的顺序**（尤其闸 2 在写之前）。CONTEXT specifics 第 6 条要求的变异用例「对 finding 线程调 MCP 作答 ⇒ 400 且线程状态一字未变」正是在验闸 3 + 闸 2 的先后。

⚠️ 一条容易漏的：该 View 在 `record_answer` 之后**同一请求内**调 `aapply_thread_answers` 回灌产新版本，且「回灌失败绝不回滚、绝不改响应码，结果原样放进 `reflow` 键」（`:615-617`）。MCP 工具的响应也应带这个 `reflow` 结构（否则调用方无法区分「答案记下了但正文没更新」）。

### B.3 assumptions 档位：可配面比 CONTEXT 设想的窄一半

| 旋钮 | 现状 | 能否按档位覆盖 |
|------|------|---------------|
| `threshold` | `aload_spec_gate_config()` 读 `SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG`，`_to_score` + clamp[0,1]（`blueprint_ambiguity_score.py:239-268`），默认 `0.20` | ✅ 可以。但 **`aload_spec_gate_config()` 目前无形参**，且在 `blueprint_spec_gate.py` 被调**两次**（`:211` 与 `_lock_spec` 内 `:359`）——两处都要能拿到档位，否则 `ambiguity_report` 里记的阈值与实际判定用的对不上 |
| `max_rounds` | ⚠️ **`_MAX_SPEC_GATE_ROUNDS = 3` 是模块级常量**（`blueprint_spec_gate.py:73`），在 `:175`（判定）与 `:183`（日志）两处使用。`DEFAULT_SPEC_GATE_CONFIG` 只有 `{threshold, weights}`（`:47-50`），**配置里根本没有 max_rounds 这个键** | ❌ 需要新增：`aload_spec_gate_config` 返回值加 `max_rounds`（强转 int + 下界 1）+ `:175` 改读配置。**这不是「零新机制」，是一处真实改动**，PLAN 要单列 |

档位写入点：CONTEXT 定的 `stage_state.decomposition.assumptions_tier`。⚠️ 注意 `_current_round` 读的是 `stage_state["spec_gate"]["round"]`（`:621-627`）——档位放 `decomposition` 下不冲突，但 `aload_spec_gate_config` 现在**不接 session**，要拿到档位就得改签名（传 session 或传 tier 字符串）。建议传 tier 字符串（保持该函数无 ORM 依赖，它现在是纯配置读取）。

留痕：`_ambiguity_report(...)` 是 `ambiguity_report` 的唯一装配点，档位加一个键即可（该 dict 已经带 `capped` / `release_reason` / `scorer_unavailable` 等元信息）。

⭐ **`assume_more` 与 `skip_clarification` 的物理隔离**：蓝图链**根本没有** `clarify` dep，`skip_clarification` 参数在 `build_orchestration_engine` 内只影响 `ClarifyAdapter` 的 policy（`entrypoint.py:120-127`），蓝图工厂不接这个参数。所以「档位复活 skip_clarification」在结构上做不到——只要 PLAN 不把档位实现成「跳过 spec_gate stage」。变异用例应断言：`assume_more` 档下四维打分**仍然执行**、超阈值**仍然开线程**（只是阈值更高）。

### B.4 飞书卡片送达（`blueprint_notify.py`）

现成范式在 `plan_research._send_clarify_card`（`plan_research.py:434-491`）：`build_clarification_card(questions, …)` → `_resolve_space` → `_aresolve_project(space)` → `ProjectService().resolve_or_create_group(project, member_ids, initiated_by_user_id)` → `FeishuIMService.create(space)` → `send_card(receive_id=chat_id, receive_id_type="chat_id", card=card)`，整段 `try/except` 只 log（`:490-491`）。

收件人口径直接抄 114-05 已实装的那份（`blueprint_review_action.aremind_clarification_threads`，`:700`）：`BlueprintReviewer` 名单 ∪ 蓝图会话 `created_by_id`，去重升序，**反查会话带 `process_type="technical_blueprint"` 过滤**。

⚠️ 正文脱敏：`_acollect_round_questions`（`plan_research.py:493-518`）对每条 question 过 `redact_secrets_in_text`。蓝图澄清题来自 LLM（`scores["questions"]`），同属半可信文本，**照样要过**。

---

## Part C —— SC-3 飞书导出与「未经确认」标注

### C.1 判别分支的落点（与 111 同处同形）

`delivery/artifacts/builtin_types.py` 全文只有 45 行。validator 分支在 `:19-32`（`content.get("schema_version") == BLUEPRINT_SCHEMA_VERSION` ⇒ `validate_blueprint`，判别常量**懒 import 自 schema 模块**，MN-10 明令不复制字面量）；renderer 在 `:35-38`，目前无条件 `render_merged_plan_markdown(content)`。⇒ 新分支就是把 `_render_technical_plan` 改成与 `_validate_technical_plan` **逐字同构**的形状（同一个懒 import、同一个判别式）。

### C.2 ⭐ renderer 签名冲突与解法（本 SC 的第一个必须定的决策）

`ContentRenderer = Callable[[dict], str]`（`registry.py:16`）、`render_markdown(artifact_type, content)`（`:65-70`）——**注册表只给 content**。而判据源 `Artifact.blueprint_status`（`delivery/models/artifact.py:45-63` 的 11 态 TextChoices）不在 content 里。

两个消费面对状态的可得性**不同**：

| 消费面 | 位置 | 拿得到 `blueprint_status` 吗 |
|--------|------|---------------------------|
| `ArtifactTimelineSerializer.current_version_markdown` | `delivery/api/artifact_serializers.py:117-127`，`SerializerMethodField(obj: Artifact)` | ✅ 拿得到（`obj` 就是 Artifact），但它现在调的是 `render_markdown(obj.artifact_type, current.content)`，**在注册表这层被截断** |
| 新导出端点 | 自建 | ✅ 拿得到 |

**推荐解法**（满足 CONTEXT「没有关掉它的入参」这条不变量）：

```
render_blueprint_markdown(content: dict, *, blueprint_status: str) -> str
```
- `blueprint_status` **必填 keyword-only**，无默认值 ⇒ 调用方无法省略。
- 抑制集合是**闭合白名单** `{CONFIRMED, IMPLEMENTING, IMPLEMENTED}`；**其余一切取值（含 `""`、含未知字符串）都渲染标注** ⇒ 无论传什么都关不掉，只有真状态能关。
- `builtin_types._render_technical_plan(content)` 的蓝图分支传 `blueprint_status=""` —— 注册表路径拿不到状态，fail-safe 方向是「当作未确认」。
- 两个权威面（导出端点 + `ArtifactTimelineSerializer` 的蓝图特判）**直接调 `render_blueprint_markdown` 并传真实状态**，绕过注册表。

⚠️ 变异用例按 CONTEXT specifics 第 3 条：把白名单改一个值 ⇒ 用例转红。**再加一条**：断言 `render_blueprint_markdown` 的签名里**不存在**任何布尔开关参数（`inspect.signature` 断言，参数名集合恰为 `{content, blueprint_status}`）——这是「物理删掉开关」唯一能被机器验的形式。

前端同源判据在 `BlueprintViewerHeader.vue`（115 自建，0.20 归属可改）；三个状态字面量与后端逐字对齐，并按同款变异用例背书。

### C.3 十段 + 附录的数据来源（逐段核对 schema）

| 导出小节 | content 路径 | 形状要点 |
|---------|-------------|---------|
| 需求规格 | `requirement_spec.goal` / `.background` / `.feature_points[]` / `.boundaries` / `.constraints` / `.ambiguity_report` | `goal`/`background` 是 block_list；`feature_points[]` 必有 `id/title/intent`，可选 `description`(block_list) / `acceptance_criteria[str]` / `test_cases` |
| 六段之 1 仓库关联 | `repo_associations[]` | 必有 `repository_id/repository_name/role`；`rationale.text` / `responsibility` / `fitness.reasons` / `planned_change_summary` / `support_needed` 全是 block_list |
| 六段之 2 现状分析 | `current_state_analysis[]` | 必有 `repository_id/findings`；`findings[]` 必有 `id/text(block_list)/kind/citations` |
| 六段之 3 实现概述 | `implementation_overview` | 必有 `requirement_narrative`(block_list) / `items[]`；可选 `modules[]` |
| 六段之 4 API 契约 | `api_contracts[]` | 必有 `id/name/kind/direction` |
| 六段之 5 影响范围 | `impact_analysis` | 必有 `business_impact`(block_list) / `affected_features[]`（每项必有 `feature/kind`） |
| 六段之 6 交互流程 | `interaction_flows[]` | 必有 `id/name/steps[]`，`steps[]` 必有 `seq/actor/action` |
| 验收锚点 | `must_haves` | 必有 `truths[str]` / `artifacts[]` / `key_links[]`（后两者**零 items 约束**） |
| 决策记录附录 | `decision_log` | ⚠️ **零约束裸 array**（`blueprint_schema.py:733-736`），不在顶层 required、不在 `iter_blocks`。114-04 写入的 `{thread_id, question, answer, decision, decided_by, decided_at, applied_in_version}` 是**约定不是契约** ⇒ 逐项 `.get` 防御，缺键渲染「—」 |
| 引用脚注 | `citations`（`{citation_id: Citation}`） | Citation 必有 `citation_id/source_type`（9 值枚举），`source_id`/`locator`/`quote`/`title` 全可选 ⇒ 取不到链接就落 `title`/`quote` 快照，⛔ 不留白 |

**block 取文本口径必须与后端同源**：`blueprint_anchor._block_text` 按 **`text` → `code.source` → `rows`** 的**字段优先级**取，**完全不看 `block.type`**（115-RESEARCH P-13 已实读并立为纪律）。renderer 若按 type 分派，会和锚点坐标系分叉。

**批注不导出**：`BlueprintThread` 本就不在 content 里（DESIGN §6.2），renderer 只读 content ⇒ 天然满足，无需额外过滤。

### C.4 导出端点、availability 与留痕

**exporter 范式**：`feishu/coding_plan_exporter.export_coding_plan_to_feishu`（`:59-123`）—— 拼一篇大 markdown → `create_feishu_doc_client_for_project(project)` → `doc_client.create_document(title, folder_token, content)`（`services/feishu_doc.py:335-...`，内部先建空文档再 `markdown_to_blocks` 写块）→ 取 `document_id` / `url`。**失败一律 `FeishuDocAPIError` 上抛**（`:108-110` 只 log 不吞）—— 这正好符合 CONTEXT 的「如实回错，不静默 200」。

`[MEDIUM]` `markdown_to_blocks` 的表达力上界（支持到几级 heading、嵌套列表如何降级）未逐行核到，`create_document` 的 docstring 只说「content in Markdown format」。⇒ **PLAN 应把 markdown 版式定得保守**（heading ≤3 级、表格不嵌套、脚注用普通列表而非 `[^n]` 语法），并在执行期用一次真实导出验证；退化不影响正确性，只影响观感。

**availability 三判据**（镜像 `chat/views.py:1740-1781`）：① 无 space → `no_space`；② `space.feishu_doc_folder_token` 空 → `no_folder_token`；③ space 级 `feishu_app_id + feishu_app_secret_encrypted` 或系统级 `_aget_system_feishu_credentials_for_doc()` 任一可得 → `available: true`，都没有 → `no_credentials`。⚠️ 蓝图侧的 space 要从 `meta.project_id → Project.space` 反查（不像 chat 那样有 `?space_id=`），且**两个端点都要挂 `_aassert_project_scope`**。

**留痕的两个禁区**：
1. ⛔ **不写 `ArtifactVersion.content`**。`_content_hash` 是对整份 content 的 canonical JSON sha256（`artifact_service.py:43-47`），`_add_version_sync` 在 hash 相等时**复用 current 不翻版本**（`:148-149`）——把 `exported_at` 时间戳写进 content 会让每次导出都产生新 hash ⇒ 每次导出翻一个版本，版本历史被刷成噪声（114-04 已立此纪律）。
2. ⚠️ **不要把导出事件加进 `BLUEPRINT_EVENTS`**。该 frozenset 21 个常量（`event_taxonomy.py:185-208`）被**两条断言**锁死：`test_blueprint_event_taxonomy_112.py:111` 的 `len(BLUEPRINT_EVENTS) == 21` 和 `:119` 的 `len(declared) == len(set(declared)) == 21`。它同时也是 115 那个 `blueprint/events/` 端点的过滤集合——加一个导出事件进去，既让两条断言转红，又会让导出记录混进「阶段进展时间线」。导出留痕的正确落点是 **Interaction Ledger（`InteractionRun` / `ToolCallRecord`）+ 独立的 structlog caller 事件**，不进 `ConvergenceSessionEvent`。

---

## Part D —— SC-4 图谱物化与反查

### D.1 `add_version` 是 choke point，但有一处例外

实读七条产版本路径，全部经 `ArtifactService.add_version`：`blueprint_merge.py:2108-2123`（`_aadd_version`）、`blueprint_spec_gate.py:385`（`_lock_spec`）、`blueprint_confirm_gate.py:582`、`blueprint_reflow.py`（两处）、`blueprint_block_edit.py:328`、`blueprint_review_action.py:313`。✅ CONTEXT 成立。

⚠️ **例外**：`add_version` 只处理「已有 artifact 加版本」。**intake 建的 v1 骨架必然走 `ArtifactService.create`**（`:53-84`，它自己建 Artifact + v1 + 置 current_version），**不经 `add_version`**。⇒ 只在 `add_version` 挂门控的话，**v1 骨架永远不入图**，直到第一次真正的版本更新才补上。两个选择：

- (a) `create` 里加同一条门控（对称，且 `create` 的调用面只有旧链 merge 与 echo，加 `schema_version` 判别对它们零影响）——**推荐**；
- (b) 只在 `add_version` 挂，接受「v1 骨架不入图」（intake 阶段的骨架 citations 为空、内容为空，图谱价值确实为零）。

⇒ 建议 (a)，理由是「唯一 choke point」这条纪律的价值在于**不需要逐点接线**；留一个例外就等于留一处将来会漂移的记忆负担。

⚠️ **第二个细节**：`_add_version_sync` 在 `content_hash` 相等时 `return current`（`:148-149`），**版本没翻**。门控应放在 `add_version` 的 async 外层且**判断返回的 version 是否真的是新版本**（比对 `version.id` 与调用前的 `artifact.current_version_id`，或比对 `version_no`），否则每次无变化的重复写入都会投一次摄取（`ingest` 内部有 content_hash 预短路会 skip，但白跑一次 normalizer + 一次后台任务）。

### D.2 实体身份与 space 反查

`generate_entity_id(kind, source_kind, source_id)` = `uuid5(KNOWLEDGE_NAMESPACE, f"{kind}:{source_kind}:{source_id}")`（`knowledge/models.py:96-137`），docstring 明令它是唯一入口。`EntityKind.TECH_PLAN = "tech_plan"`（`:42`）已存在；`source_kind` 区分子类是 Phase 100 已定的惯例（`mcp_coding_plan` / `mcp_technical_plan` 都复用 `tech_plan`）。⇒ `generate_entity_id("tech_plan", "blueprint", str(artifact_id))` ✅ 无需新 `EntityKind`、无需动 `kentity_kind_valid` 约束。

`_NORMALIZERS`（`knowledge/sources/__init__.py:20-43`）加一行 `"blueprint": "knowledge.sources.blueprint"`。⚠️ `get_normalizer` 对未知 kind **直接 raise KeyError**（`:48-56`，「响亮——触发点接错线必须立刻暴露」）⇒ 注册与模块必须同一个 commit 落地。

**`space_id` 的语义**：`IngestionEvent.space_id` 实际存的是 **`projects.Space.id`**（`workflow_plan.py:105` 逐字：`project_id = str(execution.space_id)`，赋给 `space_id=project_id`；本地变量名 `project` 指的是 `execution.space`，是历史命名噪声）。⇒ 蓝图的链路是 `meta.project_id`（Project id）→ `initiatives.Project.space_id`（`initiatives/models/project.py:51` 的 FK）→ `IngestionEvent.space_id`。

**为什么反查不到就整体不入图**（CONTEXT 的理由已核实且更强）：`fetch_related_entities` 有**两处** `space_id is None` 短路——`:40-41` 判起点实体、`:79-80` 判每个对端实体。⇒ space 为空的实体既查不出邻居、也不会出现在别人的邻居里，是一个**双向不可见**的孤儿节点。「入了图却永远查不出来」是精确描述。

### D.3 边：`apply_edge_specs` 的四条实测行为

`knowledge/ingestion.py:356-443`，逐条：

1. **target XOR 不满足** → warning 跳过（`:377-386`）。
2. **已有指向同 target 的活跃出边** → `:412-422`：`spec.metadata is not None` 时调 `update_edge_metadata` **整体覆盖**；`metadata=None` 时跳过。
3. **`exclusive=True`** → `:423-426`：把该 relation 下**所有** target 不同的活跃出边 `invalidate_edge`。
4. **`add_edge` 抛 `IntegrityError`** → `:435-443`：吞成 `knowledge_ingest_edge_conflict` warning，**边静默消失**。

`KnowledgeEdge.target_entity` 是**真 FK**（`knowledge/models.py:305-311`，`on_delete=CASCADE`）⇒ 目标实体不存在时 `add_edge` 抛的正是 `IntegrityError`，走 4 被吞掉。⚠️ **注意它和「撞 `uniq_kedge_active`」共用同一个 except 分支**（`:333-339` 的约束）——日志里的 `knowledge_ingest_edge_conflict` 无法区分「并发已建（良性）」与「目标不存在（边丢了）」。这是 CONTEXT 说的「静默消失」的精确机制。

⇒ **必须先过滤**：`KnowledgeEntity.objects.filter(id__in=[...]).values_list("id", flat=True)` 一次批量查存在性，不存在的 spec 丢弃并计数。九种 `source_type`（`blueprint_schema.py:96-107`）到目标实体的映射与可用性：

| `source_type` | 目标实体 id | 可用性 |
|---|---|---|
| `knowledge_entity` | `source_id` 本身即 entity id | ✅ 直连（仍需存在性校验） |
| `work_item` | `generate_entity_id("work_item","feishu_work_item", f"{project_key}:{type_key}:{item_id}")` | ✅ 需从 `source_id`/`locator` 还原三元组，还原不出即丢弃 |
| `feishu_doc` | `generate_entity_id("document","feishu_document", doc_token)` | ✅ |
| `blueprint` | `generate_entity_id("tech_plan","blueprint", artifact_id)` | ✅ |
| `artifact_version` | 换算成其 artifact 的蓝图实体 id | ✅（需一次 `ArtifactVersion → artifact_id` 查询） |
| `repo_file` / `rag_chunk` / `repo_charter` | 统一落 `generate_entity_id("repository","repository", repo_id)`，`metadata` 里区分 | ⚠️ 需要 repo_id；从 `locator` 取不到就丢弃 |
| `url` | — | ⛔ 不成边 |

**聚合进一条边**：`uniq_kedge_active` 是 `(source_entity, target_entity, relation)` 唯一（`:335-339`）⇒ 指向同一目标的 N 条 citation 必须先在 normalizer 里 group 成**一个** `EdgeSpec`，`metadata = {"source": "blueprint", "citation_ids": [...], "source_types": [...]}`。

⚠️ **`first_seen_version_no` 放不进去**：由行为 2，重摄取时 `update_edge_metadata` 是**整体覆盖**，而 normalizer 只能看到当前版本的 content，拿不到既有边的 metadata ⇒ `first_seen_version_no` 每次都会被刷成当前版本号，字段名与语义直接对不上。两个选择：(a) **去掉这个键**（推荐——它的信息量已由 `KnowledgeEdge.valid_at` 与 `created_at` 承载）；(b) normalizer 先 `graph_store.neighbors(entity_id, relations=["REFERENCES"], direction="out")` 读回既有 metadata 再 merge（可行但**全仓无先例**，且 normalizer 从此不再是纯函数）。

⚠️ **`exclusive=True` 的作用域是 `(source, relation)` 不是 `(source, relation, 目标类型)`**（行为 3 的实现逐字如此）。⇒ **蓝图实体的 `RELATES_TO` 出边有且只能有项目这一条**。若将来想加「蓝图 → 仓库」的 RELATES_TO，会被项目那条 exclusive 边**互相清洗**（谁最后 apply 谁活下来），且因为清洗走的是 `invalidate_edge`（不是异常）而**完全静默**。这条要写进 normalizer 的模块 docstring。

**跨批次目标**：`ingest_events` 是「阶段 A 全部实体持久化 → 阶段 B 统一处理边」（`:282-284`），保证的只是**同一批 events 内**两端都在。citation 指向的实体来自**别的摄取批次**，必须已经在库 ⇒ 存在性过滤不可省。

### D.4 观测：丢弃计数必须可查

CONTEXT specifics 第 4 条要的断言是「不产生边 + 有一条记了 `source_type` 的 `sampling` 事件」。落点在 normalizer 内（`apply_edge_specs` 是公共函数，⛔ 不改它）。字段建议：`dropped_count` / `dropped_by_source_type`（dict）/ `kept_count` / `artifact_id` / `category="sampling"` / `component="knowledge"`。

### D.5 ⭐ 反查：三处纯追加（不做则 SC-4 表面通过）

现状链路：`GET /api/knowledge/related/<uuid:entity_id>/`（`knowledge/api/urls.py:18`）→ `KnowledgeRelatedView.get`（`knowledge/api/views.py:150-176`，只解析 `as_of` / `direction` / `max_hops`）→ `DeliveryKnowledgeSearchService.get_related`（`knowledge/retrieval.py:135-146`，**形参无 `relations`**）→ `fetch_related_entities`（`knowledge/related.py:25-47`，`rels = relations or list(_DEFAULT_RELATIONS)`）→ `_DEFAULT_RELATIONS = [HAS_PLAN, IMPLEMENTED_BY, RELATES_TO]`（`:18-22`）。

⇒ REFERENCES 边**永远不被遍历**。三处纯追加：

| # | 文件 | 改动 |
|---|------|------|
| 1 | `knowledge/api/views.py:157` 附近 | 解析 `?relations=A,B`，逐项白名单校验 `EdgeRelation.values`（非法 → 400，与既有 `direction` 校验同形），**不传时行为逐字不变** |
| 2 | `knowledge/retrieval.py:135-146` | `get_related` 加 `relations: list[str] \| None = None` 并透传（默认 None ⇒ 既有调用点零回归） |
| 3 | `web/src/api/knowledge.ts:193-202` | `getRelated` 的 options 加 `relations?: string[]`，拼进 query |

⛔ **不要改 `_DEFAULT_RELATIONS` 本身**——它是 `pages/knowledge/entities/[id].vue` 等既有面的默认遍历集，加 REFERENCES 会让所有实体详情页突然多出一批引用邻居（行为回归）。

⚠️ **`max_hops` 默认是 2**（view `:163` 与前端 `:201` 都是 2）。「被谁引用」要的是**直接引用者** ⇒ 前端调用必须显式 `maxHops: 1`，否则会把二跳实体也列进来（`RelatedEntityDTO` 有 `depth` 字段可以前端过滤，但让后端少遍历一跳更省）。

**`knowledge_entity_id` 换算键**：加在 `GET .../blueprint/` 的响应里（115-01 契约表 ①，现有 7 键 `version_id/version_no/is_current/produced_by_ref/created_at/content/quality`，**纯追加第 8 键**）。⛔ 不让前端复制 uuid5（`generate_entity_id` docstring 明令唯一入口）。

**前端两块**：`BlueprintAssociationsSection.vue`。那条 `sections.spec.ts:587-596` 的 `toHaveBeenCalledTimes(0)` 用例（同时断言 `getRelated` 与 `getArtifactAssociations` 零调用）—— ⚠️ 只有 `getRelated` 该改成真实调用断言；**`getArtifactAssociations` 那条要保留为 0**，因为 `knowledge/artifact_associations.py:75` 查的仍然是 `generate_entity_id(DOCUMENT, "artifact", …)`（`initiatives.Artifact` 投影），对 `delivery.Artifact` id 依然必然落空。CONTEXT 说「改的是判据不是删用例」是对的，但**是拆成两条**而不是整条翻转。

---

## Part E —— 顺带闭掉的既有缺口

### E.1 `blueprint-gate/` 补范围闸

实读 `blueprint_gate_views.py`：**8 个 View**，全部 `permission_classes = [IsAuthenticated]`（`:206 / :230 / :277 / :299 / :320 / :341 / :373 / :450`）；范围闸 helper `_ablueprint_project_id`（`:511`）**只在 `BlueprintRejectedToBoundaryView:385` 被调过一次** ⇒ 7 个没闸，其中 `confirm`（`:220`）/ `remove-repo`（`:270`）/ `add-repo`（`:291`）是破坏性写。✅ CONTEXT 与 STATE 的登记逐字成立。

**更严变体的具体形态**：读不到合法 `meta.project_id` → **中性 404**（不是 `blueprint_review_views` 的 400）。这样做零新增存在性暴露面的理由已实测成立：该链的 404 本就混合三种语义（门未开 / artifact 不存在 / 无蓝图会话），前端（115-07）按「非 200 只决定挂载点是否渲染、不进错误分档」实现，三种 404 行为一致且有并列用例。⇒ **不需要动前端**。

⛔ 不要 import `blueprint_review_views._aassert_project_scope`（它的 400 分支正是 115-MN-03 那条被判为设计决策、本轮不改的暴露面）。gate 链应有自己的薄 helper，复用 `_ablueprint_project_id` + `_ais_project_member`，两个失败分支都回同一个中性 404 常量。

### E.2 `confirm/` 的 409 补 `blocked_reason`

两处 409，**都要补**：`:239-240`（`blocked_reason == "pending_clarification"`，现在只回 `{"detail": …}`，service 返回值里的 key 被视图消费掉了）与 `:249-256`（`alock` 拒绝，`_LOCK_BLOCKED_MESSAGES.get(lock["reason"])`，同样只回 detail）。

前端**已经实现且已有用例**：`gatePanel.spec.ts:577`（`blocked_reason: 'pending_clarification'` ⇒ 出现「前往未决线程」并 emit `goto-unresolved`）与 `:591`（其余 `blocked_reason` ⇒ 只回显 detail）。生产环境里 `body.blocked_reason` 是 `undefined` ⇒ 恒落第二档。⇒ 后端补键即生效，**前端零改动**。第二处的键值用 `lock["reason"]` 原样（`snapshot_changed` 等），与用例 `:593` 用的值同族。

### E.3 代码预览源码正文读面（最后一个可独立顺延 plan）

**确认全仓无可用面**：`chunk_at_views.py:57-60` 只返回 `{path, line, chunks}`，`chunks` 项是 `{chunk_id, file_path, line_start, line_end, chunk_index}`（`services/chunk_lookup.py:48`）——**不带正文**；唯一带 `content` 的 `POST /repositories/<id>/search/` 是向量搜索（必须给 query）；`get_repository_file` 是 PAT 认证的 MCP 工具，SPA 的 cookie-JWT 走不通。✅ CONTEXT 成立。

⚠️ **成本比 CONTEXT 估的高**：`GetRepositoryFileView`（`mcp_tools/views.py:978-1090+`）的全部逻辑——`_excluded_response` / `_read_from_mirror` / `_get_indexed_repo` / `_resolve_graph_branch` / Qdrant chunk 拼接回退——**全部是 View 的方法**，没有可 import 的服务层。新 SPA 端点要么先把这套抽成 `services/repo_file_read.py`（会改动一个 MCP 面，需回归 `TOOL_SCHEMA_SNAPSHOT` 守门），要么复制一份（⛔ 违反 fail-closed 单一实现纪律）。⇒ **推荐抽服务层**，也正是这个 plan 值得独立顺延的理由。

`is_excluded` fail-closed 的两个既有口径**不一样**，必须选一个：`chunk_at` 是「被排除与无命中统一 200 空」（`chunk_at_views.py:5-9` 的 docstring 明写不泄漏存在性）；MCP `get_repository_file` 是 **404 `file_excluded`**（`:1005-1009`，显式告知）。⇒ SPA 引用预览面应取 **`chunk_at` 的中性口径**（与 115-07 的「非 200 不进错误分档」一致，且引用预览本就有快照兜底）。

---

## Pitfalls（会静默假通过的地方）

### P-1 ⭐ 反查 relations 断链 —— SC-4 最可能的假绿
见 §D.5。症状：边全部正确入库、端点 200、页面空数组。**验收断言必须是端到端的**（造一条 blueprint→REFERENCES→knowledge_entity 边，从被引方 `?direction=in` 查回引用方），⛔ 不接受「断言 `KnowledgeEdge` 表里有那一行」这种止于 DB 的用例。

### P-2 ⭐ 骨架漏写 `schema_version` ⇒ 三条链同时静默降级
实测：`validate_blueprint` 对无 `schema_version` 的 content **返回 `(True, None)`**（§A.2 变体 H，pass-through 保 v0 零迁移）。而 `builtin_types._validate_technical_plan:20` 的判别式是 `if content.get("schema_version")` ⇒ 没有这个键就走 **v0 的 `validate_technical_plan`**。连锁后果三条，全部无异常：① 校验器走错；② SC-3 的 renderer 判别分支走 v0 空壳；③ SC-4 的 `add_version` 门控（`schema_version == "blueprint/v1"`）**永不触发**，蓝图永不入图。⇒ intake 用例必须显式断言落库版本的 `content["schema_version"] == "blueprint/v1"`，⛔ 不能只断言 `validate_blueprint` 通过（它对错的形状也返 True）。

### P-3 ⭐ 变异用例按错误的期望值写 ⇒ 恒绿
CONTEXT specifics 第 1 条要的是「换回 `build_orchestration_engine()` ⇒ 用例转红」。若期望值写成「断言会话未到 DONE」，那条用例**在正确实现下也是绿的**（正确实现里会话停在 spec_gate 等澄清，也不是 DONE）⇒ 变异不敏感。正确的期望值按 §A.3：从 `intake` 驱 ⇒ 会话落 **FAILED 且 `error["stage"] == "reroute"`**；从 `merge` 驱 ⇒ 落一份 `content.get("schema_version") != "blueprint/v1"` 的版本。二选一或都写。

### P-4 ⭐ 「未确认」标注在时间线面丢失
若 renderer 只在导出端点里传真实状态、注册表分支直接 `return render_merged_plan_markdown(content)` 保持原样，`ArtifactTimelineView.current_version_markdown` 就仍是空壳且无标注——而它是**已经上线、已经有前端消费者**（`ArtifactTimeline.vue:192-196`）的面。⇒ 用例要覆盖**两个**面，且注册表分支传 `""` 时断言标注**存在**（§C.2）。

### P-5 ⭐ 边的 metadata 被覆盖 ⇒ `first_seen_version_no` 变成谎言
见 §D.3 行为 2。表现不是报错，是这个字段的值每次重摄取都变成当前版本号。⇒ 要么去掉它，要么写一条「v1 建边 → v3 重摄取 → 断言该字段仍为 1」的用例（选 (b) 方案时）。

### P-6 ⭐ `exclusive=True` 的连坐
见 §D.3 行为 3。若 normalizer 同时产出多条 `RELATES_TO` 出边，它们会互相 `invalidate_edge`，**静默**（不是异常、不是 warning，是正常路径）。⇒ 一条「normalizer 产出的 EdgeSpec 中 `relation == RELATES_TO` 的恰好 1 条」的结构断言。

### P-7 chat 入口的健康挂起被报成失败 / barrier 永不回灌
见 §A.5。两条都不抛异常。⇒ 用例：一条 chat 蓝图会话停在 `spec_gate` 等澄清时，工具返回值必须是**挂起 marker 而不是 `success=False`**。

### P-8 MCP 的 `project_id` 其实是 Space id
见 §A.7。若直接透传，落出来的蓝图 20 个端点恒 400（`_aassert_project_scope` 的 `_ais_project_member` 查不到）、图谱恒不入（`Project.objects.get(id=space_id)` 查不到 ⇒ space 反查失败 ⇒ 不产事件）、导出恒不可用。**且这三条各自都是「安静地什么都没发生」**。⇒ intake 用例应断言 `meta.project_id` 能被 `ProjectMember` 查中。

### P-9 导出事件塞进 `BLUEPRINT_EVENTS` ⇒ 两条断言转红 + 时间线被污染
见 §C.4。`len(...) == 21` 双锁（`test_blueprint_event_taxonomy_112.py:111,119`）。

### P-10 v1 骨架不入图（`create` 不是 `add_version`）
见 §D.1。症状：新建的蓝图在图谱里查不到，直到第一次版本更新。若 PLAN 选 (b) 方案接受它，必须**显式登记**，否则「新建蓝图 → 立刻查图谱 → 空」会被当成 bug 反复排查。

### P-11 `assumptions_tier` 的 `max_rounds` 无处可配
见 §B.3。若 PLAN 照 CONTEXT 的「零新机制」写，会发现 `_MAX_SPEC_GATE_ROUNDS` 改不动，最后要么临时硬编码三个常量（档位不可运行时调，违背设计目的），要么在执行中途才发现要改 `aload_spec_gate_config` 签名。⇒ 提前列成一个 task。

### P-12 新增列表/聚合端点把读失败包成 200 空
STATE Pending Todos「116 接线必读」逐字：业务主体读失败**如实 503 + 中性 detail**，且 **503 响应体逐字不含 `items`/`total`**（塞进去前端 `items.length === 0` 会读成空态）。观测另包一层 `try/except: pass`。本相位的 `pending_clarifications[]`（MCP）与导出 availability 都吃这条。

### P-13 新增 stage 名不补前端别名表
STATE 逐字：后端 stage graph 与前端 `BLUEPRINT_STAGES` 是两套名字，换算走 `blueprintBlocks.SESSION_STAGE_ALIASES` + `PRE_TIMELINE_SESSION_STAGES`。本相位若给蓝图链加任何新 stage 名，必须同时补别名表——症状是 `indexOf` 返 `-1`、位序推断**整条静默不生效**。⛔ 不要「统一命名」。

### P-14 新蓝图模块漏加进脱敏守卫清单
`tests/delivery/test_blueprint_log_redaction_guard.py:27-38` 的 `_SCANNED_MODULES`（该文件 `:14` docstring 明写「新增蓝图模块请一并加进」）。本相位新建的 `blueprint_render.py` / `blueprint_notify.py` / `knowledge/sources/blueprint.py` / 导出端点模块都要加。⛔ 反过来，`test_blueprint_inv6_guard.py` 的 `_ALLOWED_WRITER` **不要加**——唯一 writer 必须保持是 `blueprint_lifecycle_service.py`。

### P-15 `pnpm` 会漂移 `web/pnpm-workspace.yaml`
STATE 环境项：本 worktree 跑任何 `pnpm` 命令都会向 `catalogs` 回填条目。前端 plan 跑完门后 `git status` 检查并 `git checkout -- web/pnpm-workspace.yaml`，否则会被边界核算误判为「新增依赖」。

### P-16 `test_skills_snapshot_guard.py::test_skill_files_discovered` 在本 worktree 恒红
环境产物（`skills/` 空目录），与本相位无关。基线：后端 **8609 passed / 1 failed**、前端 **1674 passed / 1 skipped**、`type-check` exit 0、`lint` 111 problems、`makemigrations --check` = `No changes detected`。

---

## 可复用件速查（全部实读确认存在）

| 用途 | 符号 / 路径 | 关键契约 |
|------|------------|---------|
| engine 工厂（唯一集中点） | `services/process_runtime/entrypoint.py:89` / `:144` | deps 名单 `research` / `merge` **两链同名**（§A.3） |
| 蓝图续驱 | `blueprint_resume.py:112` `adrive_blueprint_session_to_pause_or_terminal` | 有 process_type 守卫（`:132`）；pause 判据是「有 open+blocking 线程 **且** 无待调研仓」合取 |
| 旧链续驱 | `resume.py:23` | ⚠️ **无 process_type 守卫**；`waiting_clarification` 短路读 `Clarification`（对蓝图恒 False） |
| 会话建立 | `entrypoint.py:32` `start_orchestration` | `"technical_plan"` 写死在 `:78`；「非空才写键」纪律见 `:68-75` |
| 产物写入 | `delivery/services/artifact_service.py:53` `create` / `:117` `add_version` | `add_version` 在 hash 相等时**返回 current 不翻版本**（`:148-149`） |
| content 校验/渲染注册 | `delivery/artifacts/builtin_types.py:19` / `:35`；`registry.py:16,65` | renderer 签名 `Callable[[dict], str]`（§C.2） |
| blueprint schema | `services/process_runtime/blueprint_schema.py:38` / `:123-135` | 11 个必填顶层键；无 `schema_version` 时 **pass-through 返 True**（P-2） |
| 规格门配置 | `blueprint_ambiguity_score.py:239` `aload_spec_gate_config` | **无形参**，只返 `{threshold, weights}`；`max_rounds` 不在里面（P-11） |
| 设置读取 | `system/settings_service.py:139` `aget_json_setting` | 非 JSON / 非 dict 回默认；**不走 60s 缓存**；只保证外层 dict |
| 设置键位 | `system/models.py:173-200` | 四个蓝图键的「常量 + JSON 形状注释」范式，无 migration |
| 项目范围闸 | `blueprint_review_views.py:254` `_aassert_project_scope` | superuser 直通 / 无 `meta.project_id` → **400** / 非成员 → 中性 404 |
| 范围闸零件 | 同上 `:233` `_ablueprint_project_id` / `:244` `_ais_project_member` | gate 链自建薄 helper 时复用这两个（§E.1） |
| 作答通道 | `blueprint_review_views.py:607` + `blueprint_review_action.py` + `blueprint_reflow.REFLOW_KINDS` | 三道闸顺序见 §B.2 |
| MCP 工具基类 | `mcp_tools/views.py:238` `McpToolView` | `_begin`（401 + `bind_source`）/ `_validate`（400 `invalid_params`）/ `_record`（ToolCall + **RequestMetric**） |
| MCP 契约快照 | `mcp_tools/serializers.py:830` `TOOL_SCHEMA_SNAPSHOT` | 新工具必须加条目；双守门测试 |
| Space → Project | `workflows/nodes/integrations/board_split_review.py:58` `_aresolve_project` | 优先 `feishu_project_key` 命中、否则首个（P-8） |
| 飞书发卡范式 | `plan_research.py:434` `_send_clarify_card` | card → `resolve_or_create_group` → `FeishuIMService.send_card`；整段 best-effort |
| 飞书导出范式 | `feishu/coding_plan_exporter.py:59` | 拼大 markdown → `create_document`；失败**上抛**不吞 |
| 导出 availability | `chat/views.py:1740` | 三判据 `no_space` / `no_folder_token` / `no_credentials` |
| 摄取投递 | `knowledge/ingestion.py:118` `aschedule_ingestion` | `on_commit` + 后台；**内部吞异常**，调用方不用包 try |
| 边写入 | 同上 `:356` `apply_edge_specs` | 四条实测行为见 §D.3；`IntegrityError` 被吞（`:435`） |
| 实体 id | `knowledge/models.py:96` `generate_entity_id` | 唯一入口；natural key 规则表在 docstring `:105-123` |
| normalizer 注册 | `knowledge/sources/__init__.py:20` | 加一行；未知 kind **KeyError 响亮失败** |
| normalizer 范例 | `knowledge/sources/workflow_plan.py` | 双事件 + `EdgeSpec(exclusive=True)`；`space_id` 存的是 **Space id**（`:105`） |
| 反查 | `knowledge/related.py:25` / `api/views.py:150` / `retrieval.py:135` | ⚠️ 三层都不透传 `relations`；默认集不含 REFERENCES（P-1） |
| 事件常量 | `delivery/services/event_taxonomy.py:185` `BLUEPRINT_EVENTS` | frozenset，`len == 21` **双断言锁死**（P-9） |
| LLM 调用来源枚举 | `agents/call_source.py:112` `CallSource.BLUEPRINT_DECOMPOSE` | 已注册；`use_call_source(...)` 范式见 `blueprint_intent_classify.py:170`；清单锁 `tests/test_model_usage_call_source.py:77` |
| 脱敏守卫 | `tests/delivery/test_blueprint_log_redaction_guard.py:27` | 新模块加进 `_SCANNED_MODULES`（P-14） |
| INV-6 守卫 | `tests/delivery/test_blueprint_inv6_guard.py` | 三条正则扫全 `server/`，连裸实例化都逮；`_ALLOWED_WRITER` **不要加** |
| 排除判定 | `services/chunk_lookup.py:44,70` / `mcp_tools/views.py:988` | 两个口径不同（中性 200 空 vs 404 `file_excluded`），§E.3 |
| 前端反查 API | `web/src/api/knowledge.ts:193` `getRelated` | 现无 `relations` 参数；`maxHops` 默认 2（应传 1） |
| 前端待改用例 | `web/src/components/blueprint/__tests__/sections.spec.ts:587-596` | **拆两条**：`getRelated` 转真实断言，`getArtifactAssociations` 保持 0（§D.5） |
| 前端已就绪暗分支 | `web/src/components/blueprint/__tests__/gatePanel.spec.ts:577,591` | `blocked_reason` 两档已实现且有用例，后端补键即生效（§E.2） |

**新增运行时依赖：零。**

---

## Confidence 与残留不确定项

| 面 | 级别 | 依据 |
|----|------|------|
| intake 最小骨架与 schema 必填集 | **HIGH** | `.venv` 实跑 8 个变体（§A.2），返回值逐字记录 |
| 八个续驱点清单与工厂分派 | **HIGH** | 全仓 rg + 逐点读上下文；两个同名 dep 与 `aadvance_reroute` 缺失均实读坐实 |
| 用错工厂的逐 stage 推演 | **HIGH**（推演）/ MEDIUM（未实跑） | 每一步的判据都实读（handler getattr / adapter 方法存在性 / `aall_research_tasks_terminal` 零 task 返 True / engine except 分支），但整条链未在测试里跑过 ⇒ **Wave 0 建议先跑一次探针确认落点确实是 `reroute`** |
| chat 两条断链 | **HIGH** | `_schedule_chat_plan_resume` 全文 + `_maybe_suspend`/`_map_terminal` 全文 + 蓝图 barrier 两处全文实读 |
| renderer 签名冲突 | **HIGH** | `registry.py` 全文 71 行 + `builtin_types.py` 全文 45 行 + serializer 消费点实读 |
| `apply_edge_specs` 四条行为 | **HIGH** | 函数全文（`:356-443`）+ `KnowledgeEdge` 约束定义实读 |
| 反查 relations 断链 | **HIGH** | view / service / related 三层签名逐层实读 |
| gate 链 7/8 无闸、confirm 两处 409 | **HIGH** | 8 个 `permission_classes` 行 + 唯一一处 `_ablueprint_project_id` 调用点 + 两个 409 分支实读 |
| `markdown_to_blocks` 的表达力上界 | **MEDIUM** `[ASSUMED]` | `create_document` 与写块调用链已读，但块转换器本身未逐行核；heading 层级/嵌套列表的降级行为为推测 |
| 飞书 `create_document` 的失败码映射（400 vs 502 怎么分） | **MEDIUM** | `FeishuDocAPIError` / `RateLimitError` / `PERMISSION_CODES` / `NOT_FOUND_CODES` 分支存在（`feishu_doc.py:175-183` 等），但未逐类核到具体 code |
| `call_source=blueprint_decompose` 已注册 | **HIGH** | `agents/call_source.py:112` `BLUEPRINT_DECOMPOSE = "blueprint_decompose"`；既有消费点 `blueprint_intent_classify.py:170` `use_call_source(...)`；枚举值有清单锁 `tests/test_model_usage_call_source.py:77` ⇒ ✅ 直接复用，⛔ 无需新增枚举值（复用即不动那份清单锁） |

**Assumptions Log（需 PLAN 或执行期确认，不得当既定事实）**

| # | 假设 | 出处 | 错了会怎样 |
|---|------|------|-----------|
| A1 | 用错工厂从 `intake` 驱的落点是 `reroute` 的 `AttributeError` | 逐 stage 推演（未实跑） | 变异用例的期望值要换（落点可能更早，如 `ResearchDispatchAdapter.dispatch` 内部对蓝图 session 的某个属性访问先炸）。**Wave 0 探针可 5 分钟证伪** |
| A2 | 飞书 `markdown_to_blocks` 支持 3 级 heading + 表格 + 代码块 | `coding_plan_exporter` 在用（含 `_md_escape` 与表格构造） ⇒ 间接佐证，非直接核对 | 导出物版式退化（不影响正确性与标注） |
| ~~A3~~ | ~~`CallSource.BLUEPRINT_DECOMPOSE` 已存在~~ | **已实读证实**（`agents/call_source.py:112`），假设解除 | —— |
| A4 | `ProjectService.resolve_or_create_group` 对蓝图场景可直接复用（无 work_item 依赖） | `plan_research._send_clarify_card` 同款调用 | 发卡链要换收件方式（不影响 best-effort 语义） |

---

## 给 PLAN 的八条硬要求（不写进去执行期必踩）

1. **SC-4 的第一个 task 是打通 `relations` 参数**（view → service → 前端三处纯追加，⛔ 不改 `_DEFAULT_RELATIONS`），并且反查的验收断言必须端到端（从被引方 `?direction=in&relations=REFERENCES&max_hops=1` 查回引用方），⛔ 不接受止于 `KnowledgeEdge` 表的用例。不先做这条，后面所有边的工作都无法被验收（P-1）。

2. **engine 分派要连 driver 一起换，且两个方向都 LOUD**：`build_engine_for_session(session)` + `resume.adrive_convergence_session_to_pause_or_terminal` 顶部补对称的 process_type 守卫（现只有蓝图侧有，`blueprint_resume.py:132`）+ 蓝图 handler 组的 deps `isinstance` 自检（挡住 `ArchitectMergeAdapter` 落 v0 content）。变异用例的期望值按 §A.3 写：**FAILED 且 `error["stage"] == "reroute"`**，或落一份 `schema_version != "blueprint/v1"` 的版本 —— ⛔ 不要写「断言未到 DONE」（那条恒绿，P-3）。

3. **续驱点改 8 处中的 6 处**（§A.4 表）：`plan_research.py:361` / `plan_research_tools.py:134` / `orchestration_delegate.py:179` / `answer_resume.py:102`（连同 `:103` 的 driver）/ `plan_clarify_callback.py:242` / `feature_solution_service.py:222`。⛔ 不改 `callbacks.py:447`（对蓝图不可达），⛔ 不要把 `skip_clarification` / `force_confirm` 透传进蓝图工厂（蓝图链没有 `clarify` dep）。

4. **chat 入口必须一并补两条断链**（§A.5）：蓝图版的 `_maybe_suspend` / `_map_terminal`（判据换 `BlueprintThread` + `blueprint_status`）+ 蓝图 barrier 里补 `entrypoint == CHAT` 的 `BarrierManager.task_completed` 回灌。不做则「chat 具备真实可执行路径」是假的，且健康挂起会被报成失败（P-7）。

5. **intake 的落库用例要断言三件事**：`content["schema_version"] == "blueprint/v1"`（P-2）、`session.current_artifact_version_id` 非空（`StageOutcome.current_artifact_version` 必须显式传，`engine.py:108-119`）、`meta.project_id` 能被 `ProjectMember` 查中（P-8，MCP 入口尤其要过 `_aresolve_project`，⛔ 不能透传 `McpWorkItemContext.space_id`）。

6. **renderer 签名先定**（§C.2）：`render_blueprint_markdown(content, *, blueprint_status: str)` 必填 keyword-only、抑制集合为闭合白名单、注册表分支传 `""`。用例覆盖**两个**面（导出物 + `current_version_markdown`），并加一条 `inspect.signature` 断言参数名集合恰为 `{content, blueprint_status}`（这是「物理删掉开关」唯一可机器验的形式，P-4）。

7. **图谱三条结构约束写进 normalizer 的模块 docstring 并各配一条断言**：① 目标实体不存在的 spec 先过滤 + 丢弃计数进 `sampling` 事件（否则 FK `IntegrityError` 被 `apply_edge_specs:435` 吞掉，边静默消失）；② 同目标多条 citation 聚合成**一条** `EdgeSpec`（`uniq_kedge_active` 是 `(source,target,relation)` 唯一）；③ `RELATES_TO` 出边**恰好 1 条**（`exclusive` 作用域是 `(source, relation)`，多条会互相静默清洗，P-6）。另定夺 `first_seen_version_no` 的去留（P-5）与 v1 骨架是否入图（P-10：推荐在 `ArtifactService.create` 里加对称门控）。

8. **三处「加了会转红/漏了会静默」的清单**：导出事件 ⛔ 不进 `BLUEPRINT_EVENTS`（`len == 21` 双断言，P-9）；新建的 4 个蓝图模块 ✅ 加进 `_SCANNED_MODULES`、⛔ 不加进 `_ALLOWED_WRITER`（P-14）；`assumptions_tier` 的 `max_rounds` 需要**改 `aload_spec_gate_config` 签名 + 把 `_MAX_SPEC_GATE_ROUNDS` 改成配置读取**，单列成 task（P-11）。此外 `sections.spec.ts:587-596` 那条用例**拆成两条**而不是整条翻转（`getArtifactAssociations` 仍必须为 0）。
