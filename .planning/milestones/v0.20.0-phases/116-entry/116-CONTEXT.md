# Phase 116: 入口收编与导出（全入口统一 + MCP 协议 + 飞书导出 + 图谱物化） - Context

**Gathered:** 2026-08-01
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，全部采用推荐项，用户预授权「用 smart discuss 结果，不要提问」）

<domain>
## Phase Boundary

蓝图从「有能力」变成「唯一产出形态」：四个入口都具备走 `technical_blueprint` 的**真实可执行路径**（含此前完全缺失的蓝图 intake）、MCP 以异步澄清协议对外（不再 skip_clarification）、蓝图可导出飞书文档且未确认版本带不可绕过的「未经确认」标注、citations/项目关联物化进知识图谱使「被谁引用」反查可用。

**⚠️ 本相位的起点（实测，决定了范围形状）：**

1. **蓝图链没有任何生产入口**。`builtin_processes._h_bp_intake` / `_h_bp_decompose` 目前是**零副作用 pass-through**（后者 docstring 逐字写着「功能点拆分在 116 入口切换时接线」），而 `blueprint_spec_gate.run` 要求 `session.current_artifact_version` 已存在、取不到就判 `needs_clarification` + warning ⇒ **全仓没有任何代码会创建蓝图的初始 `Artifact` + `blueprint/v1` 骨架版本**，蓝图链至今只在测试里被预置产物驱动过。SC-1 的主体工作量在这里，不在「改一行 process_type」。
2. **蓝图 markdown 渲染器不存在**。`delivery/artifacts/builtin_types.py` 的 renderer 对蓝图 content 调的是 v0 的 `render_merged_plan_markdown`（读 `title`/`summary`/`execution_plan` 顶层键）⇒ 蓝图的导出物与 `ArtifactTimelineView.current_version_markdown` 现在都是**结构性空壳**；该文件 docstring 逐字写着「renderer 分支归 115/116」。
3. **蓝图完全不在知识图谱里**。`knowledge/sources/__init__._NORMALIZERS` 无 `blueprint` 条目，全仓无任何 `aschedule_ingestion` 投递蓝图 ⇒ SC-4 是从零建一条摄取链，不是「补两块前端」。
4. **蓝图链零飞书集成**（`rg feishu server/**/blueprint_*.py` 只命中 `discard` / `feishu_doc` 枚举字面量）。澄清送达在 114-05 只落到「记事件 + 写周期锚点」，用户收不到任何通知。

**只做入口 / 协议 / 导出 / 图谱四件事**：不做蓝图正文编辑器（`edit-blocks/` 前端面，115 已登记归 116+ 但本相位不做，见 deferred）、不做母子蓝图 / 段级权限 / 语义搜索、不做 `redact_secrets_in_text` 的平台级修补。

权威设计输入：`.planning/technical-blueprint/DESIGN.md` §7（引用与知识图谱物化）/§8.4（既有触点升级与飞书导出）/§9（入口收编与兼容表）/§10（观测）/§13.2–13.3（并行纪律与同步点）；契约输入：115 各 SUMMARY（尤其 `115-05` SC-4 收窄证据链、`115-07` gate 契约表）、`114-05-SUMMARY.md` 七端点契约表、`.planning/STATE.md` 的 Pending Todos 顶部五条。

</domain>

<decisions>
## Implementation Decisions

### ⭐ 同步点 2 拆分与 SC / REQUIREMENTS 对账（planner 必须落实，⛔ 不得静默收窄）

**同步点 2**（v0.19.0 Phase 109 execution 投影 + Phase 110 事件时间线契约合并主干）**尚未发生**。STATE 明文：「116 的入口切换在同步点 2 前不可执行（可先做 MCP 协议与导出的后端部分）」。逐条 SC 拆分如下：

| SC | 现在可建（本相位交付） | 同步点 2 阻塞（顺延收尾 plan） |
|----|------------------------|-------------------------------|
| **SC-1** 全入口切 blueprint | 蓝图 intake（建 artifact + seed `blueprint/v1` 骨架 + 功能点拆分接线）；`build_engine_for_session` 按 process_type 分派；四个入口**各自的蓝图实现路径 + per-entry 开关**（默认仍 `technical_plan`）；feature list 的 `feature_segments → feature_points` 映射；旧链残余流量可观测 | **把默认值翻成 blueprint**（workflow / chat 两个入口尤甚）；旧 `technical_plan` 「不再是任何入口默认」的收口；`TechPlanCard` / `NodeDataTab` / `ArtifactTimeline` 触点升级 |
| **SC-2** MCP 异步澄清 | **全部**（新工具对 + pending 返回 + 续取 + 作答 + assumptions 档位）。飞书卡片推送用**现有**澄清卡通道兜底（同步点 1 也未合并，112 已定此兜底口径），封装成一个 adapter 模块以便同步点 1 后单文件替换 | 无（仅「同步点 1 后换成 107 的送达设施」属机械 rebase） |
| **SC-3** 飞书导出 + 未确认标注 | **全部**（`blueprint_render.py` + renderer 判别分支 + 导出端点 + availability 探测 + 界面横幅）。落点全在 0.20 自建面 | 无 |
| **SC-4** 图谱物化 + 反查 | **全部**（normalizer + `add_version` 单一 choke point 投递 + REFERENCES/RELATES_TO 边 + 反查复用既有 `getRelated`）。前端补两块落在 115 自建的 `BlueprintAssociationsSection.vue` | 无 |

**为什么 workflow / chat 的默认切换必须等（不是保守，是语义不成立）**：蓝图 stage graph 的 `ai_review.review_passed → STAGE_DONE`，此时 `blueprint_status = pending_review`（`blueprint_resume._HUMAN_OWNED_STATUSES` 明令该态不由续驱推进）。即**蓝图会话的 `DONE` 语义是「等人审」而不是「方案可用」**，而 `AIPlanResearchNode._map_terminal` 把 `DONE` 无条件映射成 `completed` 并把 `plan` 喂给下游 `human_approval(plan_feishu)` / `ai_coding`。现在就翻默认 = 让下游拿着**未经人审的蓝图**去建分支写代码，正面违反 RELY-01。正解（属被阻塞的那一半）：blueprint 模式下节点终态映射改为「`confirmed` → completed / `pending_review` → `waiting_event` 人审 HITL 挂起」，而这条挂起的下游消费形态（execution 投影）归 v0.19.0 Phase 109。

**必须同步改的文本（planner 在 plan 阶段一次改完，⛔ 不许只写在 PLAN 里）**：

- `ROADMAP.md` Phase 116 **SC-1 替换文案**：
  > 1. workflow `ai_plan_research` 节点、chat `start_plan_research`、MCP `create_feishu_technical_plan`、feature list 链路**全部具备走 `technical_blueprint` process 的可执行路径**（蓝图 intake 与功能点拆分接线完成、所有续驱点按 `process_type` 选 adapter），并由 per-entry 运行时开关控制；开关默认仍为 `technical_plan`，**默认切换与旧 process 退役观察顺延同步点 2 后的收尾 plan**（其时为改一个设置默认值 + 触点升级，无新增编排逻辑）。
- `REQUIREMENTS.md` **GATE-01 标 PARTIAL**，比照 VIEW-04 @115 的写法登记「✅ 本相位交付 / ⏭ 顺延同步点 2」两段；Traceability 表 GATE-01 行的 Status 改 `PARTIAL`，Phase 列写 `Phase 116（实现路径 + 开关）+ 同步点 2 后收尾（默认切换）`。
- `REQUIREMENTS.md` **VIEW-04 由 PARTIAL 转 Complete**（SC-4 交付反向「被谁引用」与图谱边，115 登记的顺延项在本相位闭环）。
- `REQUIREMENTS.md` **VIEW-02 的 Phase 115 范围说明**：若代码预览源码正文读面（本相位最后一个可独立顺延 plan，见下）真的被顺延，**必须在此处改写顺延目标**，⛔ 不得让「顺延 Phase 116」这句话在 116 结束后仍然挂着。

### 入口收编的切换机制与回滚（SC-1）

- **切换粒度 = per-entry 运行时开关，不是全局硬切**：新增 `SettingKeys.BLUEPRINT_ENTRY_SWITCH`（JSON，四键 `workflow` / `chat` / `mcp` / `feature_list`，值域 `technical_plan | technical_blueprint`，**默认四键全 `technical_plan`**），读取复用 `aget_json_setting` + 畸形回默认的既有形状（镜像 `BLUEPRINT_SPEC_GATE_CONFIG` 与 v0.19 权重外置）。理由：四个入口的下游成熟度不同（workflow/chat 的下游消费者归 0.19），per-entry 让 MCP 与 feature list 能先切、workflow/chat 留在旧链；**回滚是改一个设置值，不是回滚代码**。⛔ 不做 shadow 双跑——那会在同一项目上产出两份 artifact，直接违反「一个项目一份活跃蓝图」（§12 决策 1）。
- **⭐ engine 工厂必须按 `process_type` 分派，这是本相位最高危的静默失败面**：新增 `build_engine_for_session(session)`（放 `entrypoint.py`，维持「engine 工厂唯一集中点」的既有纪律），内部按 `session.process_type` 分派到已有的 `build_orchestration_engine` / `build_blueprint_engine`；**把全部续驱点改成它**。已实读的硬编码点：`workflows/nodes/ai/plan_research.py::_build_engine`、`agents/tools/plan_research_tools.py`、`mcp_tools/orchestration_delegate.py`、`subagent/api/callbacks.py:447`（chat 容器回调续驱，只按 `entrypoint == CHAT` 守门）。**用错工厂不会报错**：十个 `_h_bp_*` handler 一律 `getattr(engine.deps, X, None)`，缺依赖即 pass-through ⇒ 蓝图会话会**全部 stage 直通、一路 DONE、落一份空蓝图**，日志上什么都看不见。必须有一条变异用例：把某个续驱点换回 `build_orchestration_engine()` ⇒ 用例转红。
- **蓝图 intake 是本 SC 的主体**：`entrypoint.py` **纯追加** `start_blueprint_orchestration(...)`（签名对齐 `start_orchestration`，`process_type="technical_blueprint"`、`initial_stage=intake`），并把 `_h_bp_intake` 落实为「建 `Artifact(artifact_type=technical_plan, blueprint_status=researching)` + 经 `ArtifactService.add_version` 落一份过得了 `validate_blueprint` 的 `blueprint/v1` 骨架」、`_h_bp_decompose` 落实为功能点拆分（**复用 111 已注册的 `call_source = blueprint_decompose`，⛔ 不新增枚举值**；feature list 入口有 `feature_segments` 时直接采用、不走 LLM，逐字沿用 `start_orchestration` 既有的「非空才写键」纪律）。
  - ⭐ **`meta.project_id` 必须从入口权威上下文推导，推不出就拒绝发起**（workflow: `execution.space` → 该 space 下的 project；chat: `Conversation` → project；MCP: `McpWorkItemContext.space` / work_item → project；feature list: 既有 `feature_meta.project_id`）。理由：它是**全链范围闸的唯一来源**（114-MJ-03）、是 SC-4 图谱边与 space 归属的唯一来源；落一份 `project_id` 为空的蓝图 = 该蓝图的**所有** 20 个读写端点恒 400、图谱恒不入、导出恒不可用，且没有任何补救入口。**「拒绝发起并如实报错」远优于「落一份注定不可用的蓝图」。**
- **旧 process 的「退役观察」= 可观测 + 不再是默认，⛔ 不删不改冻结六文件**：① 经旧链发起时打一条 `caller` 事件 `technical_plan_entry_used`（带 `entrypoint` / `initiated_by_user_id` / `component=process_runtime`），使「还有谁在走旧链」可被 SQL 聚合；② 在 `builtin_processes.py` 的 `technical_plan` 注册项上方加退役观察注释 + STATE 登记。⛔ 绝不注销 process 注册（在途会话续驱会崩）、⛔ 绝不往六个冻结文件里加 deprecation 日志。

### MCP 异步澄清协议（SC-2）

- **工具面 = 既有工具外形不变 + 两个新工具，寻址一律用 `artifact_id`**：
  - `create_feishu_technical_plan` **工具名与既有响应键一个都不改**（`TOOL_SCHEMA_SNAPSHOT` 守门 + 该文件反复申明的外形兼容纪律）；blueprint 开关开启时仅**追加**键：`blueprint_artifact_id` / `blueprint_status` / `pending_clarifications[]`，并把 `status` 落 `partial`（既有三态之一，调用方零破坏）。
  - 新增 `get_technical_blueprint`（按 `artifact_id` 取 `blueprint_status` + 六段摘要 + markdown + `pending_clarifications[]`，终稿续取即用它）与 `answer_blueprint_clarification`（按 `thread_id` 作答）。**不建第三个 list 工具**——pending 清单内联在前者即可。
  - **寻址键是 `artifact_id` 而不是 `session_id`**：既有 20 个蓝图端点全部以 `artifact_id` 为一级键并按它挂范围闸；且同一 artifact 上可并存 `technical_plan` 与 `technical_blueprint` 两条会话（112 review 的 CRITICAL 正是「按 artifact 取最近一条会话」踩出来的）。
- **作答不新写业务逻辑，复用同一 service + 照挂同一范围闸**：`answer_blueprint_clarification` 内部走 114 的作答通道（`blueprint_review_action` / `BlueprintLifecycleService`），因此自动继承三道闸：`REFLOW_KINDS` fail-closed（`ai_review_finding` 一律拒，114-CR-01）、`is_blueprint_editable` 白名单（已 confirmed 及其后一律 400，114-MJ-04）、`_aassert_project_scope`（PAT 的 owner 即 `request.user`，直接复用）。⛔ 绝不在 MCP 层直写 `BlueprintThread`（旁路 INV-6），⛔ 绝不进程内自调 REST。
- **「立即返回 + 轮询取件」，⛔ 不做服务端长轮询、不做推送**：与 113 对容器短等待的结论同源（`knowledge_tools.py` 的 `timeout=60.0` 写死在公共 handler 工厂，改它波及既有 7 个工具）。MCP 调用方也没有可回调地址。
- **assumptions 档位 = 规格门阈值的具名预设，只管「问不问」，⛔ 不管「问了等不等」**：新增 `blueprint.assumptions_tiers` 设置（三档 `strict` / `balanced`（默认）/ `assume_more`，各自一组 `threshold` 与 `max_rounds`），会话级选择写 `stage_state.decomposition.assumptions_tier`，由 `aload_spec_gate_config` 按档位覆盖 `threshold` 并把本次档位记进 `ambiguity_report` 留痕。理由：这是在既有可调面（`BLUEPRINT_SPEC_GATE_CONFIG.threshold` + `_MAX_SPEC_GATE_ROUNDS`）之上加一层具名预设，零新机制。⭐ **`assume_more` 档也绝不等于 `skip_clarification`**——超时语义永远是显式 pending 不自动作答（§12 决策 4，本里程碑不可动），把档位做成「跳过澄清」等于原地复活 GATE-01 要消灭的东西。
- **澄清同时推飞书卡片**：复用现有卡片通道（`feishu.cards.chat_question_card.build_clarification_card` + `ProjectService.resolve_or_create_group` + `FeishuIMService.send_card`，范式照抄 `plan_research._send_clarify_card`），收件人 = `BlueprintReviewer` ∪ 会话发起人（反查会话**必须带 `process_type="technical_blueprint"` 过滤**）。整段 best-effort、失败只记事件绝不反噬挂起；封装成**一个** `blueprint_notify.py` 模块，同步点 1 之后换 107 的送达设施时只改这一个文件（形状照抄 115 的 `useBlueprintLive` 收敛法）。这同时兑现 STATE 登记的「CLAR-04 用户可感知价值只兑现一半」的另一半。

### 飞书导出与「未经确认」标注（SC-3）

- **新建 `services/process_runtime/blueprint_render.py`，在 `builtin_types.py` 加 `schema_version` 判别分支**（与 111 已建立的 validator 判别分支**同一处、同一形状**）。⛔ 绝不改冻结的 `render.py`。收益是双份：导出物与 `ArtifactTimelineView.current_version_markdown` 共用同一渲染器，后者的空壳问题一并修掉（后端修复，⛔ 不碰 0.19 归属的 `ArtifactTimeline.vue` 组件）。
- **⭐「未经确认」标注生成在 renderer 内部、由单一判据驱动、导出器没有关掉它的入参**：`render_blueprint_markdown(content, *, blueprint_status)` 在 `blueprint_status ∉ {confirmed, implementing, implemented}` 时**无条件**把「> ⚠️ 未经确认 —— 本方案尚未经人工终审（当前状态：X · 版本 vN）」写在文档第一行。⛔ **不给 `include_watermark` 之类的参数** —— 给了早晚有人传 False。前端同源：`BlueprintViewerHeader`（115 自建，0.20 归属可改）在**同一判据**下渲染常驻横幅，判据与后端逐字对齐并配变异用例（把状态集合改一个值 ⇒ 用例转红）。这是 115 反复用过的形状：把不能丢的东西做成无条件渲染、把开关物理删掉（P-4 十段容器 / finding 不给回复框）。
- **导出端点 + availability 探测，每次新建一篇文档，留痕不进 content**：新增 `POST artifacts/<uuid>/blueprint/export-feishu/` 与 `GET .../export-feishu/availability/`，**两个都照挂 `_aassert_project_scope`**；availability 镜像 chat 的 `FeishuExportAvailabilityView`（project → space → `feishu_doc_folder_token` / 凭证任一缺失即 `{available:false, reason}`，前端据此隐藏按钮而不是点了才报错）。导出记录（`document_id` / `url` / `version_no` / `exported_by` / `exported_at`）落事件 + Interaction Ledger，⛔ **绝不写进 `ArtifactVersion.content`** —— 114-04 已立过纪律：写进 content 的时间戳会让 `content_hash` 每次变、每次翻版本，把版本历史刷成噪声。上游失败**如实回错**（400/502 + 中性 detail），异常文本过 `redact_secrets_in_text`，⛔ 不回显上游 body、⛔ 不静默返 200 空结构（115-MJ-04 的反面教材：「best-effort 只覆盖观测，不覆盖业务」）。
- **导出内容 = 六段全量 + `requirement_spec` + `must_haves` + 决策记录附录 + 引用脚注；批注一律不导出**：`decision_log` 逐条渲染「问题 / 结论 / 决策人 / 生效版本」（§3.13 的存在意义就是「文档自包含、导出不丢决策」，114-04 专门保住了 `answer` 键与 `applied_in_version`）；`citations` 以每段末尾脚注形式给出（title + 来源类型 + 可点链接，取不到链接就留 `title` / `quote` 快照，⛔ 不留白）。批注线程不进导出物（DESIGN §6.2：content 保持纯净，导出/diff 不受批注污染）。

### 知识图谱物化与反查（SC-4）

- **⭐ 触发点唯一：`ArtifactService.add_version` 内按 `content.schema_version == "blueprint/v1"` 门控投递** `aschedule_ingestion(IngestionRequest("blueprint", str(artifact_id), "blueprint_version_created"))`。实读七条产版本路径（`blueprint_merge` / `blueprint_spec_gate` / `blueprint_confirm_gate` / `blueprint_reflow` ×2 / `blueprint_block_edit` / `blueprint_review_action`）**全部**经它，是唯一 choke point；逐点接线必漏一条，漏了就是图谱静默过期。`schema_version` 门控使旧 `technical_plan` 链**逐字零变化**。
- **实体身份 = 新 natural key 行 `blueprint`，`space_id` 取不到就整体不入图**：实体 id = `generate_entity_id("tech_plan", "blueprint", str(artifact_id))`（`tech_plan` 是既有 kind，用 `source_kind` 区分是 Phase 100 已定的惯例，⛔ 不新建 `EntityKind` —— 那要动 `kentity_kind_valid` 约束 + migration 且与 DESIGN §7.2「蓝图沿用 `KnowledgeEntity(kind=tech_plan)` 入图」相悖）；`space_id` 由 `meta.project_id → initiatives.Project.space_id` 反查，**反查不到就不产事件并 warning**。理由：`fetch_related_entities` 与 `ArtifactAssociationService` **都先判 `entity.space_id is None → 直接返回空**，落一个 space 为空的实体等于入了图却永远查不出来 —— 典型的「断言全绿而功能为零」。
- **边一律走 normalizer 的 `EdgeSpec` + `apply_edge_specs`（既有幂等通路），⛔ 不裸调 `graph_store`**：
  - `citations` → `REFERENCES`，**`exclusive=False` 且 append-only**：新版本删掉某条引用**不**失效旧边（bi-temporal 语义下「v2 曾引用过它」仍是事实，而「被谁引用」本就是历史性问题）。⚠️ `uniq_kedge_active` 是 `(source, target, relation)` 唯一 ⇒ **指向同一目标的多条 citation 必须聚合进一条边的 `metadata`**（`{source:"blueprint", citation_ids:[…], source_types:[…], first_seen_version_no}`），指望「一条 citation 一条边」会从第二条起稳定撞 `IntegrityError` 并被 `apply_edge_specs` 吞成 warning。
  - `meta.project_id` → 项目节点 `RELATES_TO`，**`exclusive=True`**（一份蓝图只属一个项目，改归属时旧边应失效）。
  - ⭐ **目标实体不存在的 spec 必须先过滤掉再交给 `apply_edge_specs`**：`KnowledgeEdge.target_entity` 是**真 FK**，目标不存在 → `IntegrityError` → 被 `apply_edge_specs` 吞成一条 warning，**边静默消失**。九种 `source_type` 的映射与可用性：`knowledge_entity`（source_id 即 entity id）/ `work_item`（`feishu_work_item` 三元组）/ `feishu_doc`（doc token）/ `blueprint`·`artifact_version`（换算成对方的蓝图实体 id）四种直连；`repo_file`·`rag_chunk`·`repo_charter` 统一落到仓库节点 `generate_entity_id("repository","repository",repo_id)`（`metadata` 里区分具体来源）；`url` **不成边**。**每一类都要先 `KnowledgeEntity.objects.filter(id__in=…)` 判存在**，并把「本次丢弃了几条边、各是什么 source_type」记进 `sampling` 事件——否则「反查可用」会是表面通过。
- **反查零新端点，只补一个换算键**：反查复用既有 `GET /api/knowledge/related/<entity_id>/?direction=in&relations=REFERENCES`（`fetch_related_entities` 已支持 `direction="in"`）。蓝图侧唯一缺的是 `artifact_id → entity_id` 的确定性换算，⛔ **不让前端复制 uuid5 规则**（`generate_entity_id` 的 docstring 明令它是唯一入口）—— 在已有的 `GET .../blueprint/` 响应里**纯追加**一个 `knowledge_entity_id` 键即可。前端在 115 自建的 `BlueprintAssociationsSection.vue` 里补两块（「被哪些方案 / 知识引用」+「关联知识」），115-05 已明确「现有两块无需重构、届时补两块即可」；⚠️ 该组件现有那条 `toHaveBeenCalledTimes(0)`（断言两个必然 404 的端点零调用）的用例要同步改成真实调用断言，**改的是判据不是删用例**。

### 顺带闭掉的既有缺口（本相位一并做，理由见各条）

- **`blueprint-gate/` 八端点补项目范围闸**（115-07 登记的后端缺口）：实读 `_ablueprint_project_id` 只在 `BlueprintRejectedToBoundaryView` 里被调过一次，其余七个 View 只有 `IsAuthenticated` —— 其中 `confirm` / `remove-repo` / `add-repo` 是**破坏性写**。本相位正在给蓝图加新的写入口（MCP 作答），把新入口挂闸而让旧的破坏性写敞着说不过去。⭐ **gate 链用「更严的变体」：读不到 `meta.project_id` 时回中性 404 而不是 400** —— 该链的 404 本就混合了三种语义、前端（115-07）已按「非 200 只决定挂载点是否渲染、不进错误分档」实现 ⇒ 这样补闸**零新增存在性暴露面**，也不必去动 114/115 那条已被 4 条理由判为「设计决策」的 400 语义（见 deferred）。
- **`confirm/` 的 409 补 `blocked_reason` 键**（`blueprint_gate_views.py:240` / `:249`）：两行改动，让 115-07 已经实现的「一键跳未决线程」那一档在生产真正生效；前端已坚持按机器可读键分流、⛔ 不按中文 `detail` 分档。
- **111-MN-12「权限口径」就此结案**：115 已定夺「前端不自建权限判断、一律以后端状态码为准；项目成员即全权（§6.4）」，本相位把 gate 链补齐后，蓝图全部读写面（20 + 8 个端点）口径统一。planner 请在 STATE 里把该 Pending Todo 划掉并注明结论。

### Claude's Discretion

- 各新模块的内部函数切分、`blueprint_render` 的 markdown 版式细节（heading 层级 / 表格列序 / 脚注编号）、两个新 MCP 工具的入参命名细节与 `TOOL_SCHEMA_SNAPSHOT` 条目文案、normalizer 的 `content` 提炼文本形状（供 embedding）、导出留痕的事件字段名、测试组织与 `data-testid` 命名，均自行决定，遵循 111–115 已建立的 `blueprint_*` 模块风格与 `delivery/api/` / `mcp_tools/` 既有形状。
- plan 切分自行决定，但需满足两条：① 「代码预览源码正文读面」必须是**最后一个可独立顺延**的 plan（见 specifics）；② 与同步点 2 相关的默认切换**不得**混进任何主干 plan。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets（实读确认）

- **入口与 engine**：`services/process_runtime/entrypoint.py`（`start_orchestration` 硬编码 `"technical_plan"`；`build_blueprint_engine` 已就位、七个 deps 属性名与 handler `getattr` 逐字对齐）；`builtin_processes.py` 三个 `register_process_type` + 十个 `_h_bp_*` handler；`blueprint_resume.py`（`adrive_blueprint_session_to_pause_or_terminal` / `aresume_after_gate_action` / `_HUMAN_OWNED_STATUSES`）。
- **四个入口**：`workflows/nodes/ai/plan_research.py`（含 `_create_session` / `_build_engine` / `_map_terminal` / `_send_clarify_card` 四个改造点）、`agents/tools/plan_research_tools.py`、`mcp_tools/orchestration_delegate.py` + `technical_plan_service.py` + `views.py::CreateFeishuTechnicalPlanView`、feature list 的 `mode="feature_list"` / `feature_segments` / `feature_meta` 三参数通路。
- **MCP 新工具的完整范式**：113-02 加 `read_blueprint_context` / `report_blueprint_context` 时的四处落点 —— `mcp_tools/views.py`（`McpToolView` 子类 + `_begin` / `_validate` / `_record`）、`urls.py`、`serializers.py`（请求序列化器 + `TOOL_SCHEMA_SNAPSHOT` 条目）、`tests/mcp_tools/test_schema_snapshot.py` 与 `test_skills_snapshot_guard.py` 双守门。
- **渲染与导出**：`delivery/artifacts/builtin_types.py`（validator 已有 `schema_version` 判别分支，renderer 位待加）、`delivery/artifacts/registry.py::render_markdown`、`services/feishu_doc.py::FeishuDocClient.create_document`（内部已做 `markdown_to_blocks`，含表格/代码块/列表/heading）、`feishu/coding_plan_exporter.py`（「拼一篇大 markdown 一次性交给 client」的现成范式 + `_md_escape`）、`agents/tools/feishu_doc_tools.create_feishu_doc_client_for_project`、`chat/views.py::FeishuExportAvailabilityView`（availability 探测三条判据）。
- **图谱**：`knowledge/ingestion.py`（`IngestionRequest` / `IngestionEvent` / `EdgeSpec` / `aschedule_ingestion` / **公开且幂等**的 `apply_edge_specs`）、`knowledge/sources/__init__._NORMALIZERS`（惰性注册表，加一行即可）、`knowledge/sources/workflow_plan.py`（双事件 + `EdgeSpec` 的现成范例）、`knowledge/models.py`（`EdgeRelation` 六值 / `EntityKind` 八值 / `generate_entity_id` 唯一入口 + natural key 规则表 / `KnowledgeEdge` 的 `uniq_kedge_active`）、`knowledge/related.py::fetch_related_entities`（已支持 `direction="in"`）、`knowledge/management/commands/reconcile_delivery_knowledge.py`（兜底对账范式）。
- **闸与留痕**：`blueprint_review_views` 的 `_aassert_project_scope` / `_ARTIFACT_MISSING_DETAIL` / `_aload_artifact` / `_aload_session`（**import 复用，⛔ 不复制第三份** —— `blueprint_doc_views.py` 已是这么做的先例）、`blueprint_lifecycle_service.is_blueprint_editable` / `EDITABLE_BLUEPRINT_STATUSES` / `NOT_EDITABLE_DETAIL`、`common.logging.redact_secrets_in_text`、`interactions` 的 `InteractionRun` / `ModelUsageRecord`。
- **前端（115 自建 = 0.20 归属，可改）**：`pages/knowledge/blueprints/[id].vue`、`components/blueprint/` 的 28 个组件（含 `BlueprintViewerHeader.vue` / `BlueprintAssociationsSection.vue` / `citation/CitationCodePreview.vue`）、`api/blueprints.ts`、`composables/useBlueprintLive.ts`。

### Established Patterns

- **软取依赖 + pass-through** 是蓝图 handler 的统一形状 —— 它让「注册了但永远空转」成为**无声故障**，任何新增 deps / 新增 stage 都必须配一条能证伪的用例。
- **动作端点三段式**：`_aload_action_context`（artifact + 范围闸 + session）→ service 落库（INV-6）→ `aresume_after_gate_action` 续驱（失败隔离、REST 仍 2xx）→ 以**续驱之后**重读的 `current_status` 回传。
- **观测三件套**：`category`（`caller` 调用类 / `sampling` 高频步骤）+ `component` + `duration_ms`；正文类实参只记长度（T-114-36）；观测代码整段 `try/except: pass`，但**业务主体绝不能被包进去**（115-MJ-04）。
- **纯追加纪律**：`__all__ +=`、注册字典只加不改、`TABS.push(...)` 式追加 —— 删除行严格为 0 是可核算的验收判据。
- 前端：服务端态一律 TanStack Query（key `['blueprint', 面, artifactId, …]`、失效走前缀匹配）；`refetchInterval` **全相位只允许出现在 `composables/useBlueprintLive.ts`**（源码守卫锁死）。

### Integration Points

- 入口切换 ← `BLUEPRINT_ENTRY_SWITCH` 设置；四个入口 → `start_blueprint_orchestration` → `intake/decompose` 落骨架 → 既有十 stage 链。
- 所有续驱点（工作流节点 / chat 工具 / MCP delegate / 容器回调 / 门动作视图）→ `build_engine_for_session`。
- MCP 协议 → 复用 114 的作答 service + 115-01 的正文/线程读面；澄清送达 → `blueprint_notify.py` → 现有飞书卡片通道（同步点 1 后换 107 设施）。
- 导出 → `blueprint_render` → `FeishuDocClient.create_document`；同一 renderer 反哺 `ArtifactTimelineView.current_version_markdown`。
- 图谱 → `ArtifactService.add_version` → `aschedule_ingestion("blueprint")` → `knowledge/sources/blueprint.py` → `apply_edge_specs`；反查 → 既有 `knowledge-related` 端点 ← 前端 `BlueprintAssociationsSection.vue` ← `GET .../blueprint/` 新增的 `knowledge_entity_id` 键。

</code_context>

<specifics>
## Specific Ideas

- **本相位最容易做错、必须写成能证伪断言的六条**（建议逐条配变异验证）：
  1. **engine 选错工厂 ⇒ 全 stage 静默直通**：构造一条蓝图会话，用 `build_orchestration_engine()` 驱它 ⇒ 用例必须转红（现状是一路 DONE 落空蓝图、零报错）。
  2. **`meta.project_id` 推不出时必须拒绝发起**：断言「不落 artifact、不建 session、如实回错」，⛔ 不接受「落一份 project_id 为空的蓝图」。
  3. **「未经确认」标注不可绕过**：`render_blueprint_markdown` 没有关掉它的入参；把状态白名单改一个值 ⇒ 用例转红；导出物首行与界面横幅共用同一判据。
  4. **图谱边的目标实体不存在 ⇒ 必须被计数而不是被吞**：造一条指向不存在实体的 citation，断言「不产生边 + 有一条记了 source_type 的 `sampling` 事件」，⛔ 不接受静默 warning。
  5. **同一目标的多条 citation 聚合成一条边**：造两条指向同一 `knowledge_entity` 的 citation，断言「活跃边恰好 1 条且 `metadata.citation_ids` 有 2 项」（朴素写法会在第二条撞 `uniq_kedge_active`）。
  6. **MCP 作答不得成为 finding 的第二条后门**：对 `kind == ai_review_finding` 的线程调 `answer_blueprint_clarification` ⇒ 400，且断言线程状态**一字未变**（114-CR-01 的对称面）。
- **「代码预览源码正文读面」（115 从 SC-3 顺延过来的项）纳入本相位，但作为最后一个可独立顺延的 plan**：实测全仓**没有**按 `path + 行区间` 读源码正文的 REST 面（`chunk-at` 只给行号不给正文；唯一带 `content` 的 `POST /repositories/<id>/search/` 是向量搜索必须给 query；`get_repository_file` 是 PAT 认证的 MCP 工具，SPA 的 cookie-JWT 走不通），所以它是一个真·新增端点，且必须过 `is_excluded` fail-closed。沿用 115-07 的判例：**拆成可独立顺延的最后一个 plan，但不得默默丢掉** —— 若顺延，必须同时改 `REQUIREMENTS.md` VIEW-02 里那句「顺延 Phase 116」。
- **导出与渲染共用一个 renderer 是有意为之**：若为了赶工在导出器里就地拼 markdown，`ArtifactTimelineView.current_version_markdown` 的空壳问题就会留着，两处口径立刻分叉 —— 而那正是 115-01 建 `blueprint-document` 端点时点名过的「结构已丢」问题的近亲。
- **不要「统一」会话 stage 名与前端时间线节点名**（115-MJ-02 的实证）：两侧各有既有消费方，换算走 `blueprintBlocks.SESSION_STAGE_ALIASES` + `PRE_TIMELINE_SESSION_STAGES`；本相位若给蓝图链加任何新 stage 名，**必须同时补别名表**，否则症状是 `indexOf` 返 `-1`、位序推断整条静默不生效。
- **新增列表 / 聚合端点照 115 的分层**：业务主体读失败**如实 503 + 中性 detail**（⛔ 不回显异常原文、⛔ 响应体不含 `items`/`total`，否则前端把它读成空态），观测另包一层 `try/except: pass`。

</specifics>

<deferred>
## Deferred Ideas

- **默认入口切换 + 旧 process「不再是任何入口默认」的收口 + `TechPlanCard` / `NodeDataTab` / `ArtifactTimeline` 触点升级 + workflow 节点终态「`pending_review` → 人审 HITL 挂起」的下游消费形态** → **同步点 2 之后**的收尾 plan（§13.2 第 4 条 + STATE Blockers）。本相位交付到「开关一改即生效」为止。
- **115-MN-03 的存在性预言机整体契约改版**（`_aassert_project_scope` 的 400 分支 → 四条语义 + 前端 400 档去向 + 两族参数化 `test_*_fail_closed_*` 重写）→ 维持 115 的定夺（判为设计决策、本轮不修）。本相位给 gate 链补闸时用「读不到 project_id 回中性 404」的更严变体，**因此不扩大该暴露面**；整体改版仍是一个独立工作项。
- **`redact_secrets_in_text` 不覆盖数据库连接串 + 全仓二十余处 `error=str(exc)` 未脱敏** → 维持 STATE 的定夺：合并成一个独立清理相位。本相位新增的上游交互（飞书导出 API）一律 `redact_secrets_in_text` + ⛔ 不回显上游 body。
- **澄清提醒的站内 / Web Push 通道** → 本相位只做飞书卡片这一条通道（DESIGN §6.2 点名的两条之一）；站内通知归通知面。
- **蓝图正文 block 编辑器的前端面**（`edit-blocks/` 已有后端，115 登记「归 116+」）→ 明确**不在本相位**：它需要行内编辑器 + 脏态管理 + 并发冲突提示 + `human_edit:` 版本链呈现，与本相位四条 SC 无交集，属独立相位体量。
- **`content.execution_plan` 段的前端呈现** → 归实施链路（与 `TechPlanCard` 职责重叠），同步点 2 后一并定。
- **`ConvergenceSessionService.areopen_stage` 是否新增 `blueprint.review.session_reopened` 事件** → 同步点 2 与 0.19 的时间线契约一并定（114 review 可再议项）。
- **蓝图列表的语义搜索、母子蓝图编排拆分、段级细粒度编辑权限、golden set 弱标签扩样、章程 `charter_match` 权重自动调参、AI 审查强制换模型交叉实验** → REQUIREMENTS Future Requirements，本相位不碰。
- **图谱边的「引用被删除即失效」语义**（本相位定为 append-only）→ 若日后确需，正确形态是给 `reconcile_delivery_knowledge` 加一条蓝图检查项，⛔ 不是在每次落版本时把旧边全失效重建。

</deferred>
