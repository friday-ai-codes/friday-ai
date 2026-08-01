---
phase: 116
slug: entry
kind: patterns
mapped: 2026-08-01
worktree: .claude/worktrees/v0.20-blueprint
branch: milestone/v0.20.0-blueprint
upstream:
  - .planning/phases/116-entry/116-RESEARCH.md
  - .planning/phases/116-entry/116-CONTEXT.md
  - .planning/ROADMAP.md（Phase 116 SC-1~SC-4）
  - .planning/REQUIREMENTS.md（GATE-01 / VIEW-05 / VIEW-04 / VIEW-02）
  - .planning/STATE.md（§13.2 并行纪律 / Pending Todos 顶部五条）
  - .planning/phases/115-ui/115-PATTERNS.md（house style）
new_files: 20          # 后端生产 9（含 2 个可顺延）+ 后端测试 11（含 1 个可顺延）
append_points: 36      # 后端 29 + 前端 6 + 守卫清单 1
analogs_found: 13
no_analog: 7
valid_until: "111–115 模块与 web/src 既有件在 rebase / 同步点 2 合并中改动即需重核行号"
---

# Phase 116: 入口收编与导出 - Pattern Map

**Mapped:** 2026-08-01
**Files analyzed:** 20 类新建文件 + 36 处追加/改造点
**Analogs found:** 13 / 20（7 项无近似先例，见 No Analog Found）

> 与 `116-RESEARCH.md` 的分工：RESEARCH 回答「**能不能做、会不会假绿**」（§0 的四条核验 + 16 条 Pitfalls + 可复用件速查表 + 给 PLAN 的八条硬要求），本文件回答「**照着哪个文件写、抄它的哪一段、哪里必须不一样、还要在哪儿登记一行**」。凡 RESEARCH 已实读的契约（八个续驱点清单、`apply_edge_specs` 四条行为、renderer 签名冲突、`relations` 三层断链、最小骨架 11 键…）本文件**不复述结论**，只在对应文件的「必须 DIFFER」栏引用其编号（P-1 … P-16 / §A.x–§E.x）。

---

## §0 边界纪律（先读这一节，否则 analog 抄对了边界也会破）

### 0.1 ⭐ 本文件新发现的一条硬伤：`session.entrypoint` 分不出 MCP 与 workflow

RESEARCH §A.8 建议把 `technical_plan_entry_used` 落在 `start_orchestration` 内部并带 `entrypoint`（「函数已有形参」）。**实读发现该形参在 MCP 入口传的是 `"workflow"`**，且这是文件自己写明的既有行为：

```171:178:server/mcp_tools/orchestration_delegate.py
        session = await start_orchestration(
            entrypoint="workflow",
            requirement_text=requirement_text,
            work_item=work_item,
            created_by=created_by,
            include_repos=include_repos,
            extra_evidence=extra_evidence,
        )
```

`orchestration_delegate.py:4` 与 `:131` 的 docstring 逐字写着「建 `PlanSession`（entrypoint=workflow）」——不是笔误，是既有约定。四个入口的实际取值：workflow 节点 `"workflow"`（`plan_research.py:297`）、chat `"chat"`（`plan_research_tools.py:124`）、**MCP `"workflow"`**、feature list 由调用方传参（`feature_solution_service.py:143`）。

**两处连带后果，PLAN 必须各出一条对策：**

| 面 | 后果 | 对策 |
|---|---|---|
| `technical_plan_entry_used` 的 `entrypoint` 字段 | MCP 流量被计进 workflow 桶 ⇒ 「还有谁在走旧链」的 SQL 聚合从第一天起就是错的，且**永远不会报错** | 给 `start_orchestration` 加一个**独立**的 keyword-only 形参（如 `entry_key: str = ""`，取值 `workflow\|chat\|mcp\|feature_list`），事件记 `entry_key` 而**不是** `entrypoint`；⛔ 不要改 `entrypoint` 的既有取值（它进 `ConvergenceSession` 表且有既有消费方） |
| per-entry 开关的键选择 | 若实现成 `switch[session.entrypoint]`，**打开 workflow 键会连带把 MCP 一起切走**——这正是 CONTEXT「per-entry 让 MCP 与 feature list 能先切、workflow/chat 留在旧链」要避免的相反面 | 开关**由调用方在建会话之前**按自己的静态身份查（`aresolve_entry_process_type("mcp")`），⛔ **绝不从 session 反推**。四个调用点各传一个字面量常量，值域用模块级 `Literal`/常量集合约束 |

⭐ 建议 PLAN 配一条结构断言：源码扫描 `services/process_runtime/` 与四个入口文件，**`aresolve_entry_process_type` 的实参必须是字面量**（`ast` 判 `ast.Constant`），杜绝「传 `session.entrypoint` 进来」这类回归。

### 0.2 §13.2 冻结面与「注册不注销」纪律

| 面 | 状态 | 本相位的撞车点 |
|---|---|---|
| 六个 `technical_plan` 冻结文件（`decompose_segments.py` / `research_adapter.py` / `architect_merge_adapter.py` / `merged_plan.py` / `clarify_adapter.py` / `render.py`，STATE:67） | **只读** | SC-3 的 renderer ⛔ 不改 `render.py`；SC-1 的退役观察 ⛔ 不往这六个文件加 deprecation 日志 |
| `builtin_processes.py` 的 `technical_plan` 注册项（`:963-970`） | 只加注释 | ⛔ 绝不注销注册（在途会话续驱会崩）；退役观察注释加在 `:963` 上方，形状照 `:981-983` 蓝图注册项那三行注释 |
| MCP 公共 handler 工厂（`timeout=60.0`、配额计数、无回调） | Phase 113 冻结 | 两个新工具 ⛔ 不动工厂；配额按 113 的定夺**在 dispatch 处**处理 |
| `_DEFAULT_RELATIONS`（`knowledge/related.py:18-22`） | 只读 | SC-4 ⛔ 不加 `REFERENCES` 进去（会让 `pages/knowledge/entities/[id].vue` 等既有面突然多出一批邻居，行为回归）——只透传 `relations` 入参 |
| `BLUEPRINT_EVENTS`（`event_taxonomy.py:185-208`） | `len == 21` 双断言锁死 | 导出留痕事件 ⛔ 不进（P-9） |
| `apply_edge_specs`（`knowledge/ingestion.py:356+`） | 公共函数 | 丢弃计数落 normalizer 内，⛔ 不改它 |
| 0.19 归属的三个触点（`TechPlanCard` / `NodeDataTab` / `ArtifactTimeline.vue`） | 同步点 2 后 | SC-3 只修**后端** `current_version_markdown`，⛔ 不碰 `ArtifactTimeline.vue` |

### 0.3 三条会静默让绿测转红 / 漏了会静默的守卫

| 守卫 | 扫描面 | 本相位的动作 | 顺序约束 |
|---|---|---|---|
| 脱敏守卫 `_SCANNED_MODULES`（`tests/delivery/test_blueprint_log_redaction_guard.py:27-40`） | 逐模块 `read_text()` | **追加 5 条**：`blueprint_intake.py` / `blueprint_render.py` / `blueprint_notify.py` / `blueprint_export_views.py` / `knowledge/sources/blueprint.py` | ⭐ **`_violations` 用 `(_SERVER_DIR / rel).read_text()` 且不兜 `FileNotFoundError`（`:70`）** ⇒ 追加的路径若模块尚未落地，该参数化用例**立刻 red 且是 `FileNotFoundError` 不是断言失败**。⇒ 清单追加**必须与模块创建同一个 commit**，⛔ 不许先占位 |
| INV-6 守卫 `test_blueprint_inv6_guard.py` | 整个 `server/`（除 writer/tests/migrations），三条正则连裸实例化都逮 | intake 建 `Artifact` 后置 `blueprint_status` **必须经 `BlueprintLifecycleService.transition`**；MCP 作答 ⛔ 不直写 `BlueprintThread` | `_ALLOWED_WRITER` ⛔ **不加**任何新模块（P-14）——唯一 writer 保持 `blueprint_lifecycle_service.py` |
| normalizer 注册表 `get_normalizer`（`knowledge/sources/__init__.py:45-53`） | 未知 kind **直接 raise KeyError** | 加 `"blueprint": "knowledge.sources.blueprint"` | 注册行与模块同 commit（该文件 `:36-37` 自己写了「先注册、落地前响亮 ImportError」的先例，但本相位没有理由制造一个红窗口） |

### 0.4 追加点穷举（36 处，PLAN 逐条登记；删除行应为 0 的用 ✅ 标）

| # | 文件 | 追加/改造内容 | 零删除？ |
|---|---|---|---|
| 1 | `services/process_runtime/entrypoint.py` | `start_blueprint_orchestration` + `build_engine_for_session` + `__all__ +=` + `start_orchestration` 加 `entry_key` 形参与退役事件 | ⚠️ 否（`start_orchestration` 体内改） |
| 2 | `services/process_runtime/builtin_processes.py` | `_h_bp_intake` / `_h_bp_decompose` 落实 + `technical_plan` 注册项上方注释 | ⚠️ 否 |
| 3 | `services/process_runtime/resume.py` | 顶部对称 process_type 守卫 | ✅ |
| 4 | `services/process_runtime/blueprint_ambiguity_score.py` | `aload_spec_gate_config(tier=...)` + 返回值加 `max_rounds` | ⚠️ 否 |
| 5 | `services/process_runtime/blueprint_spec_gate.py` | `_MAX_SPEC_GATE_ROUNDS` 两处改读配置（`:175` / `:183`）+ `_ambiguity_report` 记档位 | ⚠️ 否 |
| 6 | `system/models.py` | `SettingKeys` 两键（`BLUEPRINT_ENTRY_SWITCH` / `BLUEPRINT_ASSUMPTIONS_TIERS`） | ✅ |
| 7–12 | 六个续驱点 | `plan_research.py:361` / `plan_research_tools.py:134` / `orchestration_delegate.py:179` / `answer_resume.py:102-103`（连 driver）/ `plan_clarify_callback.py:242` / `feature_solution_service.py:222` | ⚠️ 否 |
| 13 | `agents/tools/plan_research_tools.py` | 蓝图版 `_maybe_suspend` / `_map_terminal` 分支（§A.5 断链二） | ⚠️ 否 |
| 14 | `subagent/api/callbacks.py` | 两个蓝图 barrier 补 `entrypoint == CHAT` 回灌（`:2150-2177` / `:2377-2396`）；⛔ 不改 `:447` | ✅ |
| 15 | `workflows/nodes/ai/plan_research.py` | `_create_session` 分派 + `meta.project_id` 推导 | ⚠️ 否 |
| 16 | `mcp_tools/views.py` | +2 个 `McpToolView` 子类 | ✅ |
| 17 | `mcp_tools/urls.py` | +2 条 `path` | ✅ |
| 18 | `mcp_tools/serializers.py` | +2 请求 serializer + `TOOL_SCHEMA_SNAPSHOT` 两条新条目 + `create_feishu_technical_plan` 条目 **response 追加三键** | ⚠️ 否（第三项） |
| 19 | `mcp_tools/technical_plan_service.py` | 响应追加 `blueprint_artifact_id` / `blueprint_status` / `pending_clarifications[]` + `status="partial"` | ⚠️ 否 |
| 20 | `delivery/artifacts/builtin_types.py` | `_render_technical_plan` 加 `schema_version` 分支 | ⚠️ 否 |
| 21 | `delivery/api/artifact_serializers.py` | `current_version_markdown` 蓝图特判（`:117-127`） | ⚠️ 否 |
| 22 | `delivery/urls.py` | +2 条导出路由 + 分组注释 | ✅ |
| 23 | `delivery/services/artifact_service.py` | `add_version` / `create` 两处门控 | ✅ |
| 24 | `delivery/api/blueprint_doc_views.py` | `GET blueprint/` 响应纯追加 `knowledge_entity_id` | ✅ |
| 25 | `delivery/api/blueprint_gate_views.py` | 薄范围闸 helper + 7 个 View 挂闸 + 两处 409 补 `blocked_reason` | ⚠️ 否 |
| 26 | `delivery/api/blueprint_review_views.py` | `BlueprintReviewThreadAnswerView.post` 体改为调用抽出的 service（§B2） | ⚠️ 否 |
| 27 | `knowledge/sources/__init__.py` | `_NORMALIZERS` +1 行 | ✅ |
| 28 | `knowledge/api/views.py` | `KnowledgeRelatedView.get` 解析 `?relations=` | ✅ |
| 29 | `knowledge/retrieval.py` | `get_related` 加 `relations` 形参并透传 | ✅ |
| 30 | `knowledge/models.py` | `generate_entity_id` docstring natural key 规则表 +1 行 `blueprint` | ✅ |
| 31 | `tests/delivery/test_blueprint_log_redaction_guard.py` | `_SCANNED_MODULES` +5 | ✅ |
| 32 | `web/src/api/knowledge.ts` | `getRelated` options 加 `relations?: string[]` | ✅ |
| 33 | `web/src/api/blueprints.ts` | 导出 + availability 两个函数 | ✅ |
| 34 | `web/src/components/blueprint/BlueprintAssociationsSection.vue` | 补两块（被引用 / 关联知识） | ⚠️ 否 |
| 35 | `web/src/components/blueprint/BlueprintViewerHeader.vue` | 「未经确认」判据与后端逐字对齐 | ⚠️ 否 |
| 36 | `web/src/components/blueprint/__tests__/sections.spec.ts:587-596` | ⭐ **拆两条**（`getRelated` 转真实断言，`getArtifactAssociations` 保持 0），⛔ 不整条翻转（§D.5） | ⚠️ 否 |

⚠️ **P-15**：前端 plan 跑完门后 `git status` 检查并 `git checkout -- web/pnpm-workspace.yaml`。

---

## File Classification

### A. SC-1 入口收编

| # | 新建/改造 | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|---|
| A1 | `services/process_runtime/blueprint_intake.py`（新） | service | CRUD（建 artifact + seed 版本） | `services/process_runtime/blueprint_reflow.py`（模块级 async 函数 + `ArtifactService` 落版本的 `blueprint_*` service 形态） | partial（**骨架 seed 本体零先例**，No Analog #1） |
| A2 | `services/process_runtime/blueprint_entry_switch.py`（新） | config reader | transform | `blueprint_ambiguity_score.aload_spec_gate_config`（`:239-268`，「settings → 逐字段强转 + clamp + 兜底」唯一先例） | exact |
| A3 | `entrypoint.start_blueprint_orchestration` | factory helper | — | 同文件 `start_orchestration`（`:32-86`） | exact（**纯追加第二个函数**） |
| A4 | `entrypoint.build_engine_for_session` | dispatcher | — | **零先例**（No Analog #2）；最近模板 = 同文件两个工厂 `:89` / `:144` | none |
| A5 | `resume.py` 对称守卫 | guard | — | `blueprint_resume.py:132-143`（逐字对称的反方向） | exact |
| A6 | `SettingKeys` 两键 | config table | — | `system/models.py:173-200`（四个蓝图键的「常量 + JSON 形状注释」，无 migration） | exact |
| A7 | 六个续驱点改造 | wiring | — | 各自现状调用行 | exact |
| A8 | chat 蓝图版 `_maybe_suspend` / `_map_terminal` | tool adapter | request-response | `plan_research_tools.py:209-297` 的旧链两函数（**判据必须全换**，No Analog #7） | partial |
| A9 | 蓝图 barrier 回灌 | callback | event-driven | `subagent/api/callbacks.py:468-488`（`_schedule_chat_plan_resume` 的 (f)(g) 两步） | exact |

### B. SC-2 MCP 异步澄清协议

| # | 新建/改造 | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|---|
| B1 | `GetTechnicalBlueprintView`（`mcp_tools/views.py` 追加） | mcp view | request-response | 同文件 `ReadBlueprintContextView`（`:4231-4324`，113-02 范式） | exact |
| B2 | `AnswerBlueprintClarificationView`（追加） | mcp view | request-response（写） | 同上（外形）+ `blueprint_review_views.BlueprintReviewThreadAnswerView`（`:607-716`，三道闸顺序） | role-match |
| B3 | `delivery/services/blueprint_answer_action.py`（新，抽服务层） | service | CRUD（事务 + 回灌） | `delivery/services/blueprint_comment_action.py`（115-A4，「View 零 ORM 写 + 恒定键返回 dict」） | exact |
| B4 | `mcp_tools/serializers.py` 两条 snapshot | contract table | — | 同文件 `:1224-1241` 两条蓝图条目 | exact |
| B5 | `services/process_runtime/blueprint_notify.py`（新） | notifier | event-driven（best-effort） | `plan_research._send_clarify_card`（`:434-491`）+ `_acollect_round_questions`（`:493-518`） | exact |
| B6 | assumptions 三档（`blueprint_ambiguity_score` + `blueprint_spec_gate`） | config | transform | 同 A2 | role-match（**`max_rounds` 是真实新增**，P-11） |

### C. SC-3 飞书导出与「未经确认」标注

| # | 新建/改造 | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|---|
| C1 | `services/process_runtime/blueprint_render.py`（新） | renderer | transform | `feishu/coding_plan_exporter.py:184-244`（「拼一篇大 markdown + `_md_escape` + 缺字段降级 `—`」） | role-match（**标注不可关闭的契约零先例**，No Analog #3） |
| C2 | `builtin_types._render_technical_plan` 分支 | registry wiring | — | **同文件 `_validate_technical_plan`（`:19-32`）逐字同构** | exact |
| C3 | `delivery/api/blueprint_export_views.py`（新，2 端点） | view (adrf) | request-response | `delivery/api/blueprint_doc_views.py`（115-01，import 复用范围闸 + `_log` 五件套） | exact |
| C4 | availability 三判据 | probe | — | `chat/views.py:1740-1781` `FeishuExportAvailabilityView` | role-match（**space 来源必须换**） |
| C5 | 导出执行体 | exporter | request-response（上游） | `feishu/coding_plan_exporter.export_coding_plan_to_feishu`（`:59-123`） | exact |
| C6 | `artifact_serializers.current_version_markdown` 特判 | serializer | — | 该方法自身（`:117-127`） | exact |
| C7 | `BlueprintViewerHeader.vue` 同源判据 | component | — | 该组件自身（115 自建） | self |

### D. SC-4 图谱物化与反查

| # | 新建/改造 | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|---|
| D1 | `knowledge/sources/blueprint.py`（新） | normalizer | transform（event-driven 消费） | `knowledge/sources/workflow_plan.py`（202 行，双事件 + `EdgeSpec(exclusive=True)` + `generate_entity_id` 唯一入口） | exact |
| D2 | `_NORMALIZERS` +1 行 | registry | — | `knowledge/sources/__init__.py:19-42` | exact |
| D3 | `artifact_service` 两处门控 | wiring | event-driven 投递 | 全仓 `aschedule_ingestion` 的 5 个既有调用点（`ingestion.py:118` 内部吞异常，调用方不用包 try） | role-match |
| D4 | `relations` 三处纯追加 | api param | — | 同文件既有 `direction` 校验（`knowledge/api/views.py:157-162`） | exact |
| D5 | `knowledge_entity_id` 换算键 | api field | — | `blueprint_doc_views.py:266-274` 的 payload 装配 | exact |
| D6 | `BlueprintAssociationsSection.vue` 两块 | component | request-response | 该组件自身既有两块 + `components/knowledge/EntityAssociationsCard.vue` | role-match |

### E. 顺带闭掉的既有缺口

| # | 新建/改造 | Role | Closest Analog | Match |
|---|---|---|---|---|
| E1 | `blueprint_gate_views` 薄范围闸 + 7 View 挂闸 | authz helper | `blueprint_review_views._aassert_project_scope`（`:254-281`）**的结构**，零件复用同文件 `_ablueprint_project_id`（`:511-522`）+ review 的 `_ais_project_member`（`:244-251`） | role-match（⭐ **400 分支必须换成中性 404**） |
| E2 | `confirm/` 两处 409 补 `blocked_reason` | api field | 同文件两处 409（`:239-240` / `:247-254`） | exact（**前端零改动**） |
| E3 | `services/repo_file_read.py`（新，可顺延） | service | `mcp_tools/views.GetRepositoryFileView`（`:978-1090+`）的**方法体下沉** | partial（No Analog #6） |
| E4 | `repositories/repo_file_views.py`（新，可顺延） | view (adrf) | `repositories/chunk_at_views.py`（61 行，中性 200 空 fail-closed 口径） | exact |

### F. 测试

| # | 新建测试 | 对应 analog |
|---|---|---|
| F1 | `tests/services/process_runtime/test_blueprint_intake.py` | `tests/services/process_runtime/test_blueprint_spec_gate.py` |
| F2 | `tests/services/process_runtime/test_engine_dispatch.py`（⭐ 变异用例） | `tests/services/process_runtime/test_blueprint_process_graph.py` |
| F3 | `tests/services/process_runtime/test_blueprint_entry_switch.py` | `tests/test_blueprint_settings.py` |
| F4 | `tests/services/process_runtime/test_blueprint_render.py` | `tests/test_coding_plan_exporter.py` |
| F5 | `tests/services/process_runtime/test_blueprint_notify.py` | `tests/test_blueprint_pending_reminder.py` |
| F6 | `tests/delivery/test_blueprint_export_views.py` | `tests/delivery/test_blueprint_doc_views.py` |
| F7 | `tests/delivery/test_blueprint_gate_scope.py` | `tests/delivery/test_blueprint_review_views.py`（范围闸工厂 `_make_project`） |
| F8 | `tests/mcp_tools/test_blueprint_clarification_tools.py` | `tests/mcp_tools/test_schema_snapshot.py` + 113-02 的工具测试 |
| F9 | `tests/knowledge/test_blueprint_normalizer.py` | `tests/knowledge/test_feishu_document_normalizer.py` |
| F10 | `tests/knowledge/test_related_relations_param.py` | `tests/knowledge/test_artifact_associations_api.py` |
| F11 | `tests/repositories/test_repo_file_read_views.py`（可顺延） | 既有 `chunk-at` 端点测试 |

---

## Pattern Assignments

### A1. 蓝图 intake → `services/process_runtime/blueprint_intake.py`（新）

**Analog（模块形态）:** `server/services/process_runtime/blueprint_reflow.py`（模块级 async 函数 + `ArtifactService` 落版本 + `REFLOW_KINDS` 模块常量 fail-closed），**不是** adapter 类——intake 在 `build_blueprint_engine` 的 deps 名单里**没有对应属性**（`:173-181` 只有七个），凭空加一个 dep 会破坏「名单与 handler `getattr` 逐字一致」的纪律。

**为什么不直接写进 `_h_bp_intake`：** 该 handler 组的三条自述纪律里第 ② 条是「handler 只返回 `StageOutcome`，落库由 engine 承担」；把「建 Artifact + 落版本 + 状态跳转」塞进 handler 会让 `builtin_processes.py`（991 行、已在两张守卫清单上）再长一大段。⇒ **handler 内 lazy import 本模块的一个函数**，形状照 `_abp_mark_drafting` 的写法（`builtin_processes.py:466+`，同样是「handler 之外的落库 helper」）。

**结构要点（逐条照抄）：**

- 建 artifact 走 `ArtifactService.create`（**不是 `add_version`**）——它自己建 Artifact + v1 + 置 `current_version`：

```105:115:server/delivery/services/artifact_service.py
            v1 = ArtifactVersion.objects.create(
                artifact=artifact,
                version_no=1,
                content=content,
                content_hash=_content_hash(content),
                produced_by_session_id=produced_by_session_id or "",
                produced_by_ref=produced_by_ref or "",
            )
            artifact.current_version = v1
            artifact.save(update_fields=["current_version", "updated_at"])
            return artifact
```

- `artifact_type` 传 `ARTIFACT_TYPE_TECHNICAL_PLAN`（蓝图复用同一 type，`builtin_processes.py:987` 与 `builtin_types.py:16` 两处都是这个口径）。
- 状态跳转走 `BlueprintLifecycleService.transition(artifact, BlueprintStatus.RESEARCHING, ...)`，形状逐字照 `_abp_mark_drafting` 里的那一跳（入口边只有 `"" → researching`）。
- 日志五件套见 §S1；正文类实参只记长度。

**必须 DIFFER（五条，全部来自 RESEARCH，漏一条即静默假通过）：**

1. ⭐ **content 必须显式带 `"schema_version": "blueprint/v1"`**（P-2）。`validate_blueprint` 对缺该键的 content **返回 `(True, None)`**（§A.2 变体 H），而 `builtin_types._validate_technical_plan:20` 的判别式是 `if content.get("schema_version")` ⇒ 漏写会同时让**校验器走 v0 / renderer 走 v0 空壳 / SC-4 门控永不触发**三条链静默降级。用例断言**落库版本的 `content["schema_version"]`**，⛔ 不能只断言 `validate_blueprint` 通过。
2. ⭐ **`StageOutcome` 必须显式带 `current_artifact_version=artifact.current_version_id`**——`engine.py:108-119` 有整段注释说明「只在非 None 时才透传」，不传则 `session.current_artifact_version_id` 恒 None，`blueprint_spec_gate` 与两个 `_aload_artifact` helper 全部静默降级（§A.1 第三样）。
3. ⭐ **`meta.project_id` 必须是 `initiatives.Project.id`**（P-8）。MCP 入口拿到的 `McpWorkItemContext.space` 是 `projects.Space` FK ⇒ **必须过 `board_split_review._aresolve_project(space)`**（`:58-69`，`plan_research._send_clarify_card:470` 已是这个用法）。透传 space_id ⇒ 20 个端点恒 400 + 图谱恒不入 + 导出恒不可用，且三条都「安静地什么都没发生」。用例断言 `meta.project_id` 能被 `ProjectMember` 查中。
4. **推不出 project_id ⇒ ⛔ 不建 session、⛔ 不建 artifact、如实回错**。四个入口各自的错误出口有现成范式：workflow `NodeResult(status="failed", next_handle="error")`（`plan_research.py:194-199`）、chat `ToolResult(success=False, error=…)`（`plan_research_tools.py:96-99`）、MCP `error_response(code, detail)`。
5. **骨架形状 = 最小 11 键 + `requirement_spec.goal` 装一个承载需求原文的 paragraph block**（§A.2）。空 `goal` 会让规格门四维打分（`_goal_text` / `_feature_points` / `_constraints`）拿不到输入而 fail-closed 到满歧义 ⇒ 第一轮必然开一堆无意义澄清线程。

**避免：** 裸写 `artifact.blueprint_status = ...`（INV-6 三条正则连裸实例化都逮）；把 seed 写成 `add_version`（此时 artifact 还不存在）；在 `start_orchestration` 上加 `process_type` 形参（会让旧链四入口共享一个可传错的开关，§A.1）。

---

### A2. per-entry 开关 → `services/process_runtime/blueprint_entry_switch.py`（新）

**Analog:** `server/services/process_runtime/blueprint_ambiguity_score.py:239-268`（`aload_spec_gate_config`，全仓「settings JSON → 逐字段强转 + clamp + 兜底」的唯一先例）。

```239:250:server/services/process_runtime/blueprint_ambiguity_score.py
async def aload_spec_gate_config() -> dict[str, Any]:
    """读运行时阈值与四维权重（``blueprint.spec_gate.config``），逐字段强转 + 兜底。

    任何异常/畸形一律回 :data:`DEFAULT_SPEC_GATE_CONFIG`（绝不外抛、绝不 eval，
    T-112-07）：``threshold`` 经 ``float()`` + clamp ``[0,1]``，``weights`` 非 dict
    回默认、逐维 ``float()`` 且负值取 0。
    """
    fallback = copy.deepcopy(DEFAULT_SPEC_GATE_CONFIG)
    try:
        from system.models import SettingKeys
        from system.settings_service import aget_json_setting
```

**沿用：** 模块级 `DEFAULT_ENTRY_SWITCH` 常量（四键全 `technical_plan`）+ `copy.deepcopy` 兜底 + 整段 `try/except` 回默认 + `from system.models import SettingKeys` 函数内懒 import（避免 process_runtime → system 的模块级依赖）。

**必须 DIFFER：**

- ⚠️ **`aget_json_setting` 只保证外层是 dict**（`settings_service.py:139-153` 签名 `-> dict`，「非 JSON / 非 dict 回默认」三重兜底，**不走 60s 缓存** ⇒ 改设置立即生效，符合「回滚是改一个设置值」）。**内层不校验** ⇒ 逐键 `str(raw.get(key) or "")` 并对非法值回落 `technical_plan`，形状照 `aload_spec_gate_config` 的逐维强转。
- ⭐ **函数签名收 `entry: str` 字面量，⛔ 不收 session**（§0.1）。建议 `async def aresolve_entry_process_type(entry: str) -> str`，值域外的 `entry` 也回 `technical_plan` 并记一条 warning。
- 键位声明抄 `system/models.py:173-200` 的形状——「常量 + JSON 形状注释 + 消费方文件名」，**无 migration**：

```181:187:server/system/models.py
    BLUEPRINT_SPEC_GATE_CONFIG = "blueprint.spec_gate.config"
    # value 为 JSON：{"<intent>": {"router_base": float, "charter_match": float,
    # "history_match": float}}，intent ∈ greenfield|brownfield|fix。未配置时默认
    # greenfield 重章程与历史落点（0.40/0.35/0.25）、brownfield 重能力树
    # （0.60/0.20/0.20）、fix 最重能力树（0.70/0.15/0.15）。
    # 消费方：services/process_runtime/blueprint_route.py（112-03）。
    BLUEPRINT_ROUTE_WEIGHTS = "blueprint.route.weights"
```

---

### A3/A4. `entrypoint.py` 追加两个函数

**Analog（A3 起会话）:** 同文件 `start_orchestration`（`:32-86`）。

```77:86:server/services/process_runtime/entrypoint.py
    return await ConvergenceSessionService().create_session(
        "technical_plan",
        entrypoint,
        work_item=work_item,
        stage_state={"decomposition": decomposition},
        created_by=created_by,
        conversation_id=conversation_id,
        node_execution_id=node_execution_id,
        initiated_by_user_id=initiated_by_user_id,
    )
```

**沿用：** 签名逐字对齐（含 `mode` / `feature_segments` / `feature_meta` 三个 feature list 专用参数）；⭐ **「非空才写键」纪律**（`:68-75` 的五个 `if`）——不提供时会话形态与既有入口逐字一致；`__all__ +=` 追加导出（`:188-189` 的先例逐字写着「纯追加纪律（既有 `__all__` 行一字不动）」）。

**必须 DIFFER：** `create_session` 第一实参改 `"technical_blueprint"`；feature list 的 `feature_segments` 在蓝图链要额外映射成 `feature_points`（CONTEXT 定的 `feature_segments → feature_points`，有它时 decompose 直接采用不走 LLM）。

**A4 `build_engine_for_session(session)` —— 零先例（No Analog #2）。** 最近模板是同文件两个工厂的返回形态。⭐ **三条必须自己发明的约束：**

| 约束 | 形态 | 为什么 |
|---|---|---|
| ①**engine 与 driver 一起换** | 返回 `(engine, driver)` 二元组，或再加一个 `aresolve_driver(session)` | 旧续驱器 `resume.adrive_…` 的 `waiting_clarification` 短路判据是 `ClarificationService().ahas_pending`（`resume.py:53-57`），对蓝图会话**恒 False** ⇒ 三个 pausable stage 一个都短路不了，self-loop 被推到 `max_steps` 落 `advance_step_limit` FAILED（§A.3 第二把锁）。只换 engine 不换 driver 仍然坏 |
| ②**未知 process_type LOUD** | 不在 `{technical_plan, technical_blueprint, echo}` ⇒ 落 caller 事件 | §A.3 |
| ③**deps `isinstance` 自检** | 蓝图 stage 取到的 `research`/`merge` 若不是蓝图 adapter 实例 ⇒ `_abp_ensure_blocking_clarification` + `needs_clarification` | **两个工厂的 deps 有两个同名属性**（`research` / `merge`），这是唯一能挡住 `ArchitectMergeAdapter` 往蓝图会话落一份 v0 content 的手段（§A.3） |

⛔ **不要把 `skip_clarification` / `force_confirm` 透传进蓝图工厂**——`build_blueprint_engine` 只接 `session_service` / `node_execution_id` 两个参数（`:144-146`），蓝图链根本没有 `clarify` dep。

---

### A5. 反方向守卫 → `resume.py` 顶部

**Analog:** `server/services/process_runtime/blueprint_resume.py:132-143`（逐字对称，连 docstring 的论证都可以镜像）：

```132:143:server/services/process_runtime/blueprint_resume.py
    if str(getattr(session, "process_type", "")) != BLUEPRINT_PROCESS_TYPE:
        # 蓝图 engine 的 deps 只有 spec_gate/route/research/confirm_gate；用它驱别的 process
        # 会让旧链 handler 取不到 deps.router 抛异常，engine 随后把那条无关会话落 FAILED。
        # 宁可 no-op：调用方传错会话是 bug，不是「该会话该失败」。
        logger.warning(
            "blueprint_resume_wrong_process_type",
            category="caller",
            component="process_runtime",
            session_id=str(getattr(session, "id", "")),
            process_type=str(getattr(session, "process_type", "")),
        )
        return session
```

**沿用：** 事件名换成 `wrong_driver_for_blueprint_session`，其余五个 kv 与 `return session`（no-op）逐字照抄；理由段落逐字同源。

**必须 DIFFER：** 判据反向（`== BLUEPRINT_PROCESS_TYPE` 才拒）；⭐ **`resume.py` 是旧链共享面**（`plan_deepen` 等非蓝图调用方也走它）⇒ 守卫必须是「只挡蓝图会话」的**白名单外拒绝**，不能顺手加别的 process_type 判断。

---

### A8. chat 入口两条断链 → `plan_research_tools.py` + `subagent/api/callbacks.py`

**Analog（回灌）:** `subagent/api/callbacks.py:468-488` 的 `_schedule_chat_plan_resume` 后两步：`BarrierManager.task_completed(str(plan_session.id), result)`。

**沿用：** 蓝图两个 barrier（`:2150-2177` / `:2377-2396`）里补一条**与 `entrypoint == CHAT` 对称的**回灌分支；task key 用 `str(session.id)`，与 chat 工具注册 blocking task 时用的 `{"task_id": str(session.id), "task_type": "plan_research", …}`（`plan_research_tools.py:246-256`）**逐字对齐**——key 不一致的症状是 waiter 永远等不到，且**不抛异常**。

**必须 DIFFER（No Analog #7，判据全换）：**

| 旧链判据 | 对蓝图的行为 | 蓝图版判据 |
|---|---|---|
| `ClarificationService().ahas_pending(session.id)` | **恒 False** | open + blocking 的 `BlueprintThread`（判据抄 `blueprint_resume` 的 pause 短路：`ai_clarification` 与 `repo_confirmation` 两类，**不传 `kind`**） |
| `aall_research_tasks_terminal` | 蓝图卡在 `spec_gate` 时零 task **返 True** | 与「有待调研仓」合取，抄 `blueprint_resume.adrive_…` 的 docstring 那两条短路点 |
| `_map_terminal`：`status != DONE ⇒ ToolResult(success=False, "plan session failed")` | ⭐ **健康的挂起被报成失败**——用户看到「方案编排失败」，其实系统在等他回答问题 | 按 `blueprint_status` 分档；`needs_clarification` 一律返回**挂起 marker** |

⭐ 用例（P-7）：一条 chat 蓝图会话停在 `spec_gate` 等澄清时，工具返回值必须是挂起 marker 而**不是** `success=False`。

⛔ **`callbacks.py:447` 不改**（对蓝图三重不可达：`source == "plan_research"` / `plan_session_id` 键名 / `entrypoint == CHAT` 守门）。

---

### B1/B2. 两个新 MCP 工具 → `mcp_tools/views.py` 追加

**Analog:** 同文件 `ReadBlueprintContextView`（`:4231-4324`，113-02 范式）。

```4250:4260:server/mcp_tools/views.py
    async def post(self, request: Request) -> Response:
        run, err = await self._begin(request)
        if err is not None:
            return err
        assert run is not None
        input_data, err = await self._validate(ReadBlueprintContextRequestSerializer, request)
        if err is not None:
            return err
        assert input_data is not None
        started_at = time.perf_counter()
        return await self._handle(run, request, input_data, started_at)
```

**结构要点（逐条照抄）：**

- **模块 docstring = 契约书**：端点语义 → 「N 道兜底绝不绕过」编号清单（`:4237-4245` 的形状）。
- `tool_name = "..."` 类属性；`post` 三段式 `_begin` → `_validate` → `_handle`。
- ⭐ **观测规范的「新增请求入口纳入 QPS/错误率/时长」自动满足**：基类 `_record` 已顺带落 `RequestMetric(route=f"mcp:{tool_name}")`：

```300:308:server/mcp_tools/views.py
        await arecord_request_metric(
            source=LogSource.MCP.value,
            route=f"mcp:{self.tool_name}",
            method="POST",
            status_code=200 if call_status == "ok" else 500,
            error_class="none" if call_status == "ok" else "system",
            duration_ms=duration_ms,
            labels={"call_source": self.tool_name, "run_id": str(run.run_id)},
        )
```

  ⇒ 两个新工具**无需另写指标埋点**，只要 `tool_name` 赋对。
- `_begin` 已处理 `bind_source(MCP)` + `request.auth is None → 401`（`:254-268`）⇒ ⛔ 不重复写鉴权。
- 异常兜底：**绝不 5xx**（`:4308-4324`），错误经 `redact_secrets_in_text(str(exc))[:500]` 后进日志。

**snapshot 条目形状**（`serializers.py:1224-1241`），**键名逐字**：

```1224:1227:server/mcp_tools/serializers.py
    "read_blueprint_context": {
        "request": ["key_prefix", "kind", "repository_id", "since_seq", "limit"],
        "response": ["entries", "count", "max_seq", "error", "run_id"],
    },
```

⚠️ 该文件 `:1229-1230` 自带一条教训注释：「`redispatched` 是 113-04 追加的真实响应键，漏在 snapshot 里会让容器侧 / 外部客户端按已发布契约以为它不存在（snapshot 是对外契约，不是内部注释）」⇒ **`create_feishu_technical_plan` 追加的三键必须同步进它的 snapshot 条目**，否则守门测试虽绿但契约是假的。

**必须 DIFFER：**

- ⭐ **`answer_blueprint_clarification` 必须复刻三道闸的顺序**（§B.2）：`_aload_action_context`（含范围闸）→ **`is_blueprint_editable` 在 `record_answer` 之前** → `kind == ai_review_finding` 一律 400。RESEARCH 的变异用例「对 finding 线程调 MCP 作答 ⇒ 400 且线程状态一字未变」正是在验闸 3 与闸 2 的先后。
- **响应必须带 `reflow` 结构**：analog 的 View 在 `record_answer` 之后同一请求内调 `aapply_thread_answers`，且「回灌失败绝不回滚、绝不改响应码，结果原样放进 `reflow` 键」（`blueprint_review_views.py:615-617`）。MCP 少了这个键，调用方无法区分「答案记下了但正文没更新」。
- **`pending_clarifications[]` 读失败 ⇒ 如实 503 + 中性 detail，且响应体逐字不含 `items`/`total`**（P-12）。⛔ 不包成 200 空。
- ⛔ **不建第三个 list 工具**；寻址键一律 `artifact_id`（同一 artifact 上可并存两条会话，112 的 CRITICAL 就是「按 artifact 取最近一条会话」踩出来的）。
- ⚠️ `tests/mcp_tools/test_skills_snapshot_guard.py` 在本 worktree **恒红**（P-16，`skills/` 空目录），别把它的红当成本相位引入。

---

### B3. 作答服务层抽取 → `delivery/services/blueprint_answer_action.py`（新）

**Analog:** `server/delivery/services/blueprint_comment_action.py`（115-A4，同一相位刚立的「View 零 ORM 写 + 恒定键返回 dict」范式）。

**为什么要抽（这是一个需要 PLAN 拍板的设计决策）：** MCP 工具「⛔ 绝不在 MCP 层直写 `BlueprintThread`、⛔ 绝不进程内自调 REST」这两条同时成立，就只剩「共享 service」一条路。而作答那套调用序**目前完全内联在 `BlueprintReviewThreadAnswerView.post` 里**（`:633-716`）。两个选项：

- **(a) 抽 `blueprint_answer_action.aanswer_thread(...)`，View 与 MCP 工具都调它**——推荐。代价是改一处既有 View（追加点 #26，PLAN 显式登记）。
- (b) MCP 工具里复刻一遍三道闸。⛔ 违反 fail-closed 单一实现纪律，且 114-CR-01 那条 finding 后门一旦漂移就是安全回归。

**结构要点（照抄 comment_action）：** 模块 docstring 首段声明 INV-6；`__all__` 显式列公开函数；`_COMPONENT` 常量；`_user_id`（回落 `"system"`）/ `_detail`（`redact_secrets_in_text` + 截断 500）两个共用 helper；**恒定键返回 dict**（`{status, thread_id, reflow, detail, current_status}`，`status` 是闭集，两个调用方各自做 status → HTTP 码 / MCP error_response 映射）；正文只进 `body=`，日志只记 `body_len`。

**必须 DIFFER：** analog 的开线程是**驳回的副作用**（best-effort 不上抛）；作答是**主动作** ⇒ 失败如实回错。新模块加进 `_SCANNED_MODULES`。

---

### B5. 澄清送达 → `services/process_runtime/blueprint_notify.py`（新）

**Analog:** `server/workflows/nodes/ai/plan_research.py:434-491`（`_send_clarify_card`）+ `:493-518`（`_acollect_round_questions`）。

**沿用（调用序逐字）：** `build_clarification_card(questions, …)` → `_resolve_space` → `_aresolve_project(space)` → `ProjectService().resolve_or_create_group(project, member_ids, initiated_by_user_id)` → `FeishuIMService.create(space)` → `send_card(receive_id=chat_id, receive_id_type="chat_id", card=card)`；**整段 `try/except` 只 log**（`:490-491` 的 `# noqa: BLE001 — 发卡 best-effort，绝不反噬挂起`）；每一步「取不到就 `return`」的早退形态（`:462` / `:469` / `:472` / `:480`）。

**正文脱敏逐字照抄**（`:512`）：

```510:517:server/workflows/nodes/ai/plan_research.py
            questions.append(
                {
                    "question": redact_secrets_in_text(str(q.get("question") or "")),
                    "type": q.get("qtype") or "single",
                    "options": q.get("options") or [],
                    "recommended": q.get("recommended") or [],
                }
            )
```

蓝图澄清题来自 LLM（`scores["questions"]`），同属半可信文本，**照样要过**。

**必须 DIFFER：**

- 收件人口径抄 114-05 已实装的 `blueprint_review_action.aremind_clarification_threads`（`:700`）：`BlueprintReviewer` 名单 ∪ 蓝图会话 `created_by_id`，去重升序，⭐ **反查会话必须带 `process_type="technical_blueprint"` 过滤**。
- analog 是 workflow 节点的方法（吃 `ExecutionContext`）；本模块是**独立模块级函数**（四个入口都要用）⇒ space / project 由调用方或 `meta.project_id` 反查传入，⛔ 不依赖 `ExecutionContext`。
- ⭐ **封装成一个文件**（CONTEXT）：同步点 1 之后换 107 的送达设施时只改这一个文件。模块 docstring 要把这条写进去（形状照 `useBlueprintLive.ts` 的收敛法自述）。
- 新模块加进 `_SCANNED_MODULES`。

---

### B6. assumptions 三档 → `blueprint_ambiguity_score` + `blueprint_spec_gate`

**这不是「零新机制」**（P-11，CONTEXT 的判断需要修正）：

| 旋钮 | 现状 | 改动 |
|---|---|---|
| `threshold` | `aload_spec_gate_config()` 已读、已 clamp | ✅ 加档位覆盖即可。⚠️ 该函数在 `blueprint_spec_gate.py` 被调**两次**（`:211` 判定、`:359` `_lock_spec`），**两处都要拿到档位**，否则 `ambiguity_report` 里记的阈值与实际判定用的对不上 |
| `max_rounds` | ⚠️ `_MAX_SPEC_GATE_ROUNDS = 3` 是**模块级常量**（`blueprint_spec_gate.py:73`），在 `:175`（判定）与 `:183`（日志）两处使用；`DEFAULT_SPEC_GATE_CONFIG` 只有 `{threshold, weights}` | ❌ 真实新增：返回值加 `max_rounds`（`int()` 强转 + 下界 1）+ 两处改读配置。**单列一个 task** |

**签名建议：** `aload_spec_gate_config(tier: str = "")`——传 **tier 字符串**而不是 session，保持该函数无 ORM 依赖（它现在是纯配置读取）。档位写入点是 `stage_state.decomposition.assumptions_tier`；`_current_round` 读的是 `stage_state["spec_gate"]["round"]`（`:621-627`），放 `decomposition` 下不冲突。留痕加进 `_ambiguity_report(...)`（`ambiguity_report` 的唯一装配点，已带 `capped` / `release_reason` / `scorer_unavailable`）。

⭐ **变异用例断言 `assume_more` ≠ `skip_clarification`：** 四维打分**仍然执行**、超阈值**仍然开线程**（只是阈值更高）。物理隔离本身是成立的（蓝图链没有 `clarify` dep，`skip_clarification` 只影响 `ClarifyAdapter` 的 policy，`entrypoint.py:120-127`）——只要 PLAN **不把档位实现成「跳过 spec_gate stage」**。

---

### C1. 蓝图渲染器 → `services/process_runtime/blueprint_render.py`（新）

**Analog（组装形态）:** `server/feishu/coding_plan_exporter.py:184-244`。

```184:203:server/feishu/coding_plan_exporter.py
def _compose_plan_markdown(
    coding_plan: CodingPlan, sessions: list[CodingSession]
) -> str:
    """组装一篇 markdown 字符串供 ``create_document`` 一次性转 block 写入。"""
    parts: list[str] = []
    parts.append(f"# {coding_plan.title or '未命名方案'}\n")
    parts.append("## 技术方案\n")
    tech_plan = (coding_plan.tech_plan or "").strip()
    if tech_plan:
        parts.append(tech_plan + "\n")
    else:
        parts.append("（暂无技术方案文本）\n")
```

**沿用：** `parts: list[str]` + `"\n".join(parts)`；每个表格一个 `_build_xxx_table` 私有函数，返回 `"| 列 | 列 |\n| --- | --- |\n…"`；**零行时补一行 `| — | — |`**（`:215-217`）；`_md_escape`（`:242-244`，`|` → `\|`、换行 → 空格）逐字复制一份（analog 在 `feishu/` 包，`process_runtime` 不该反向依赖 `feishu/`）；缺字段一律降级 `"—"` ⛔ 不留白。

**⭐ 必须 DIFFER —— 签名契约（本 SC 的第一个必须定的决策，No Analog #3）：**

```
render_blueprint_markdown(content: dict, *, blueprint_status: str) -> str
```

| 约束 | 理由 |
|---|---|
| `blueprint_status` **必填 keyword-only、无默认值** | 调用方无法省略 |
| 抑制集合是**闭合白名单** `{CONFIRMED, IMPLEMENTING, IMPLEMENTED}`，其余一切取值（含 `""`、含未知字符串）**都渲染标注** | 「没有任何取值能关掉标注」，fail-safe 方向正确 |
| ⛔ **不存在任何布尔开关参数** | CONTEXT：「给了早晚有人传 False」 |

⭐ **唯一可机器验的形式**（P-4）：一条 `inspect.signature` 断言，参数名集合**恰为** `{content, blueprint_status}`。另加「把白名单改一个值 ⇒ 用例转红」的变异用例。

**其它 DIFFER：**

- ⭐ **block 取文本口径必须与后端锚点同源**：`blueprint_anchor._block_text` 按 **`text` → `code.source` → `rows`** 的**字段优先级**取，**完全不看 `block.type`**（115-RESEARCH P-13 已立为纪律）。renderer 按 type 分派会和锚点坐标系分叉。
- **`decision_log` 是零约束裸 array**（`blueprint_schema.py:733-736`，不在顶层 required、不在 `iter_blocks`）⇒ 114-04 写入的七个键是**约定不是契约**，逐项 `.get` 防御、缺键渲染「—」，特别保 `answer` 与 `applied_in_version`。
- **`citations` 取不到链接就落 `title`/`quote` 快照**，⛔ 不留白（Citation 必有 `citation_id/source_type`，其余全可选）。
- **批注不导出**：`BlueprintThread` 本就不在 content 里 ⇒ renderer 只读 content 即天然满足，⛔ 无需额外过滤代码（写了反而是死码）。
- `[MEDIUM]` **版式定保守**（§C.4 A2）：heading ≤3 级、表格不嵌套、脚注用普通列表而非 `[^n]` 语法；执行期用一次真实导出验证。
- 新模块加进 `_SCANNED_MODULES`。

---

### C2. 注册表分支 → `builtin_types._render_technical_plan`

**Analog:** **同文件的 `_validate_technical_plan`（`:19-32`），逐字同构**——同一个懒 import、同一个判别式：

```19:38:server/delivery/artifacts/builtin_types.py
def _validate_technical_plan(content: dict) -> tuple[bool, str | None]:
    if isinstance(content, dict) and content.get("schema_version"):
        # 判别常量与校验器同源懒 import（MN-10）：本模块不再复制 "blueprint/v1"
        # 字面量，避免 schema 演进时漏改一处导致新版蓝图静默走 v0 校验路径。
        from services.process_runtime.blueprint_schema import (
            BLUEPRINT_SCHEMA_VERSION,
            validate_blueprint,
        )

        if content.get("schema_version") == BLUEPRINT_SCHEMA_VERSION:
            return validate_blueprint(content)
    from workflows.schemas.technical_plan import validate_technical_plan

    return validate_technical_plan(content)


def _render_technical_plan(content: dict) -> str:
    from services.process_runtime.render import render_merged_plan_markdown

    return render_merged_plan_markdown(content)
```

**沿用：** MN-10 的懒 import 纪律逐字（⛔ 不复制 `"blueprint/v1"` 字面量）；模块 docstring `:9` 那句「renderer 分支归 115/116，本相位不做」要**同步改掉**。

**必须 DIFFER：** ⭐ 蓝图分支调 `render_blueprint_markdown(content, blueprint_status="")`——注册表签名 `ContentRenderer = Callable[[dict], str]`（`registry.py:16`）拿不到状态，**传空串即「当作未确认」**，fail-safe 方向正确。⛔ 不改 `registry.py` 的类型别名与 `render_markdown(artifact_type, content)`（`:65-70`）签名（那会波及所有 artifact_type）。

⭐ **P-4 的第二个面**：`ArtifactTimelineSerializer.current_version_markdown`（`artifact_serializers.py:117-127`，`SerializerMethodField(obj: Artifact)`）**拿得到真实状态**但现在调的是 `render_markdown(...)`、在注册表这层被截断 ⇒ 给它加一个蓝图特判**直接调 `render_blueprint_markdown` 并传真实状态**，绕过注册表。用例必须覆盖**两个**面，且注册表分支传 `""` 时断言标注**存在**。

---

### C3/C4/C5. 导出端点 → `delivery/api/blueprint_export_views.py`（新，2 端点）

**Analog（View 骨架）:** `server/delivery/api/blueprint_doc_views.py`（444 行，115-01）——同域、同前缀、同一套闸与埋点。

**结构要点（逐条照抄）：**

- ⭐ **范围闸 import 复用，绝不造第四份**（该文件 `:47-57` 就是这条纪律的说明书）：

```47:57:server/delivery/api/blueprint_doc_views.py
# ⭐ MJ-03 的四条范围闸语义**只能有一份实现**：提取共享模块要改既有文件（115 对后端同样
# 守「能不改就不改」），复制会产生可漂移的第三份副本 ⇒ 直接 import 私有符号并在此登记。
# ``_ARTIFACT_MISSING_DETAIL`` 一并 import 是硬要求：非成员的中性 404 响应体由闸内产出，
# 本模块「artifact 不存在」的 404 必须与它**逐字相同**，否则存在性仍可被枚举（T-115-02）。
from delivery.api.blueprint_review_views import (
    _ARTIFACT_MISSING_DETAIL,
    _aassert_project_scope,
    _aload_artifact,
    _aload_session,
    _thread_row,
)
```

- 基类 `from adrf.views import APIView`（**不是** `rest_framework.views.APIView`）；`permission_classes = [IsAuthenticated]` 逐 View 声明。
- 模块级常量三类：`_COMPONENT`、中性 404/400 文案 dict、上界常量。
- **埋点统一 helper**（`:206-216`）：

```206:216:server/delivery/api/blueprint_doc_views.py
def _log(event: str, request: Any, artifact_id: Any, started: float, **fields: Any) -> None:
    """端点级 caller 事件（只记标量与关联键；**任何用户正文都不进来**）。"""
    logger.info(
        event,
        category="caller",
        component=_COMPONENT,
        artifact_id=str(artifact_id),
        initiated_by_user_id=str(getattr(request.user, "id", "") or "system"),
        duration_ms=round((time.monotonic() - started) * 1000, 2),
        **fields,
    )
```

- 端点骨架（`:239-285`）：`started = time.monotonic()` 第一行 → `_aload_artifact` → 404 → `_aassert_project_scope` → 装配 → `_log` → `Response`。
- ⭐ **手写 dict 响应，零 DRF serializer**（本 View 家族全域如此）。

**availability 三判据 —— Analog:** `chat/views.py:1740-1781`：

```1758:1781:server/chat/views.py
    async def get(self, request):
        space_id = request.query_params.get("space_id") or ""
        if not space_id:
            return Response({"available": False, "reason": "no_space"})
        ...
        if not project.feishu_doc_folder_token:
            return Response({"available": False, "reason": "no_folder_token"})

        if project.feishu_app_id and project.feishu_app_secret_encrypted:
            return Response({"available": True, "reason": None})

        from agents.tools.feishu_doc_tools import (
            _aget_system_feishu_credentials_for_doc,
        )

        credentials = await _aget_system_feishu_credentials_for_doc()
        if credentials:
            return Response({"available": True, "reason": None})
        return Response({"available": False, "reason": "no_credentials"})
```

**必须 DIFFER：** ⭐ **space 从 `meta.project_id → Project.space` 反查**（不像 chat 那样有 `?space_id=`）；⭐ **两个端点都挂 `_aassert_project_scope`**（analog 用的是 `ChatAuthPermission`，与本链无关）；`{available, reason}` 两键保持逐字一致（前端据此隐藏按钮而不是点了才报错）。

**导出执行体 —— Analog:** `feishu/coding_plan_exporter.export_coding_plan_to_feishu`（`:59-123`）：拼大 markdown → `create_feishu_doc_client_for_project(project)` → `doc_client.create_document(title, folder_token, content)` → 取 `document_id` / `url`；⭐ **失败一律 `FeishuDocAPIError` 上抛**（`:108-110` 只 log 不吞）——正合「如实回错、不静默 200」。

**导出面的必须 DIFFER（四条）：**

1. ⛔ **绝不写 `ArtifactVersion.content`**：`_content_hash` 是整份 content 的 canonical JSON sha256（`artifact_service.py:43-47`），`_add_version_sync` 在 hash 相等时复用 current 不翻版本（`:148-149`）⇒ 把 `exported_at` 写进 content 会让**每次导出翻一个版本**，版本历史被刷成噪声（114-04 纪律）。
2. ⚠️ **导出事件 ⛔ 不进 `BLUEPRINT_EVENTS`**（P-9）：`len == 21` 被 `test_blueprint_event_taxonomy_112.py:111,119` 双断言锁死，且它同时是 115 `blueprint/events/` 端点的过滤集合——加进去既转红又会把导出记录混进「阶段进展时间线」。**正确落点 = Interaction Ledger（`InteractionRun` / `ToolCallRecord`，范式见 `interactions/entry.py` 的 `begin_interaction_run`）+ 独立 structlog caller 事件**。
3. **上游失败如实回错**（400/502 + 中性 detail），异常文本过 `redact_secrets_in_text`，⛔ 不回显上游 body、⛔ 不静默 200 空结构。`[MEDIUM]` 400 vs 502 的分档依据 `FeishuDocAPIError` / `RateLimitError` / `PERMISSION_CODES` / `NOT_FOUND_CODES`（`feishu_doc.py:175-183`），**执行期逐类核一次**。
4. **路由分组注释**照 `delivery/urls.py:235-239` 的形状（几个端点 + 前缀语义 + 字面段/uuid 段顺序纪律），`name=` 全部 `reverse()` 可解析。

**新模块加进 `_SCANNED_MODULES`。**

---

### D1. 蓝图 normalizer → `knowledge/sources/blueprint.py`（新）

**Analog:** `server/knowledge/sources/workflow_plan.py`（202 行，双事件 + `EdgeSpec` 的现成范例）。

**结构要点（逐条照抄）：**

- **模块 docstring 写清「产几个实体几条边 + 缺料如何降级 + 事件顺序」**（`:1-17`）。
- `__all__ = ["normalize"]`；`async def normalize(request: IngestionRequest) -> list[IngestionEvent]`；源缺失 → `logger.warning("knowledge_normalize_source_missing", …)` + **返回空列表**（`:69-75`）。
- 事件装配（`:144-155`）与出边（`:192-200`）：

```192:200:server/knowledge/sources/workflow_plan.py
        edges=(
            EdgeSpec(
                relation=EdgeRelation.HAS_PLAN,
                target_entity_id=generate_entity_id(
                    "tech_plan", "workflow_plan", request.source_id
                ),
                exclusive=True,
            ),
        ),
```

- ⭐ **`space_id` 存的其实是 `projects.Space.id`**（`:105` 逐字：`project_id = str(execution.space_id)`，变量名是历史命名噪声）。蓝图链路是 `meta.project_id`（Project id）→ `initiatives.Project.space_id` → `IngestionEvent.space_id`。
- `generate_entity_id("tech_plan", "blueprint", str(artifact_id))`——`tech_plan` 是既有 kind、`source_kind` 区分子类是 Phase 100 惯例 ⇒ ⛔ 不新建 `EntityKind`、不动 `kentity_kind_valid` 约束。**同时在 `knowledge/models.py` 的 natural key 规则表 docstring 追加一行**（`generate_entity_id` docstring 明令它是唯一入口）。

**必须 DIFFER（四条结构约束，写进模块 docstring 并各配一条断言）：**

1. ⭐ **目标实体不存在的 spec 先过滤**：`KnowledgeEdge.target_entity` 是**真 FK**，目标不存在 → `IntegrityError` → 被 `apply_edge_specs:435-443` 吞成 `knowledge_ingest_edge_conflict` warning，**边静默消失**；而该分支与「撞 `uniq_kedge_active`（并发已建，良性）」**共用同一个 except**，日志里分不出来。⇒ 一次批量 `KnowledgeEntity.objects.filter(id__in=[...]).values_list("id", flat=True)`，丢弃计数进 `sampling` 事件（字段建议 `dropped_count` / `dropped_by_source_type` / `kept_count` / `artifact_id` / `component="knowledge"`）。
2. ⭐ **同目标多条 citation 聚合成一条 `EdgeSpec`**：`uniq_kedge_active` 是 `(source_entity, target_entity, relation)` 唯一 ⇒ 「一条 citation 一条边」从第二条起稳定撞约束。`metadata = {"source": "blueprint", "citation_ids": [...], "source_types": [...]}`。
3. ⭐ **`RELATES_TO` 出边恰好 1 条**：`exclusive=True` 的作用域是 `(source, relation)` **不是** `(source, relation, 目标类型)` ⇒ 多条会互相 `invalidate_edge`，**静默**（不是异常、不是 warning，是正常路径，P-6）。
4. **`first_seen_version_no` 建议去掉**（P-5）：重摄取时 `update_edge_metadata` 是**整体覆盖**，而 normalizer 看不到既有边 metadata ⇒ 该字段每次都被刷成当前版本号，字段名与语义直接对不上。它的信息量已由 `KnowledgeEdge.valid_at` / `created_at` 承载。若坚持保留，须走 `graph_store.neighbors` 回读再 merge（**全仓无先例**，且 normalizer 从此不再是纯函数）。

**九种 `source_type` → 目标实体换算表（No Analog #5，需自己写一个 `_resolve_target_entity_id`）：** `knowledge_entity` 直连 / `work_item` 还原 `{project_key}:{type_key}:{item_id}` 三元组 / `feishu_doc` 用 doc token / `blueprint` 同款 natural key / `artifact_version` 需一次 `ArtifactVersion → artifact_id` 查询 / `repo_file`·`rag_chunk`·`repo_charter` 统一落 `generate_entity_id("repository","repository",repo_id)` / `url` ⛔ 不成边。**还原不出即丢弃并计数。**

---

### D3. 投递门控 → `delivery/services/artifact_service.py`

**Analog:** `ingestion.py:118` `aschedule_ingestion`——`on_commit` + 后台，**内部吞异常，调用方不用包 try**。

**沿用：** `aschedule_ingestion(IngestionRequest("blueprint", str(artifact_id), "blueprint_version_created"))`；⛔ 调用方不再包一层 try（重复兜底会掩盖 normalizer 注册漏行这类应当响亮的错误）。

**必须 DIFFER（两条，RESEARCH §D.1）：**

1. ⭐ **`create` 也要挂同一条门控**（推荐方案 (a)）：intake 建的 v1 骨架走 `create` **不经 `add_version`** ⇒ 只在 `add_version` 挂的话 v1 骨架永远不入图（P-10）。`create` 的调用面只有旧链 merge 与 echo，加 `schema_version` 判别对它们零影响。若 PLAN 选 (b) 接受「骨架不入图」，**必须显式登记**，否则「新建蓝图 → 立刻查图谱 → 空」会被当 bug 反复排查。
2. ⭐ **门控放在 async 外层且判断是否真的翻了版本**：`_add_version_sync` 在 `content_hash` 相等时 `return current`（`:148-149`）——比对 `version.id` 与调用前的 `artifact.current_version_id`（或 `version_no`），否则每次无变化的重复写入都白跑一次 normalizer + 一次后台任务。

```145:150:server/delivery/services/artifact_service.py
        with transaction.atomic():
            artifact.refresh_from_db(fields=["current_version"])
            current = artifact.current_version
            if current is not None and current.content_hash == new_hash:
                return current
            next_version = (current.version_no + 1) if current is not None else 1
```

---

### D4. ⭐ `relations` 三处纯追加（不做则 SC-4 表面通过）

**Analog（参数校验）:** 同文件既有 `direction` 校验，形状逐字照抄：

```153:165:server/knowledge/api/views.py
    async def get(self, request, entity_id):
        as_of, err = _parse_as_of_param(request)
        if err is not None:
            return err
        direction = request.query_params.get("direction", "both")
        if direction not in ("both", "out", "in"):
            return Response(
                {"detail": "direction must be one of: both, out, in"},
                status=400,
            )
        max_hops = _parse_int_param(request.query_params.get("max_hops"), 2, "max_hops")
        if isinstance(max_hops, Response):
            return max_hops
```

**三处改动（全部纯追加，不传时行为逐字不变）：**

| # | 文件 | 改动 |
|---|---|---|
| 1 | `knowledge/api/views.py:157` 附近 | 解析 `?relations=A,B`，逐项白名单校验 `EdgeRelation.values`，非法 → 400（与 `direction` 同形） |
| 2 | `knowledge/retrieval.py:135-146` | `get_related` 加 `relations: list[str] \| None = None` 并透传（默认 None ⇒ 既有调用点零回归） |
| 3 | `web/src/api/knowledge.ts:193-202` | `getRelated` options 加 `relations?: string[]`，拼进 query |

⚠️ **最底层 `fetch_related_entities` 已经有这个形参**（`related.py:31` `relations: list[str] | None = None`，`:47` `rels = relations or list(_DEFAULT_RELATIONS)`）——**断的只是中间两层 + 前端**。

⛔ **不改 `_DEFAULT_RELATIONS` 本身**（§0.2）。
⚠️ **前端调用必须显式 `maxHops: 1`**——view `:163` 与前端 `:201` 默认都是 2，「被谁引用」要的是**直接引用者**。

⭐ **验收断言必须端到端**（P-1）：造一条 blueprint→REFERENCES→knowledge_entity 边，从**被引方** `?direction=in&relations=REFERENCES&max_hops=1` 查回引用方。⛔ 不接受「断言 `KnowledgeEdge` 表里有那一行」这种止于 DB 的用例。

---

### E1. gate 链补范围闸 → `blueprint_gate_views.py`

**现状（实读）：** 8 个 View 全部只有 `permission_classes = [IsAuthenticated]`（`:206 / :230 / :277 / :299 / :320 / :341 / :373 / :450`）；范围闸零件 `_ablueprint_project_id`（`:511`）**只在 `BlueprintRejectedToBoundaryView:385` 被调过一次** ⇒ 7 个没闸，其中 `confirm` / `remove-repo` / `add-repo` 是**破坏性写**。

**Analog（结构）:** `blueprint_review_views._aassert_project_scope`（`:254-281`）：

```274:281:server/delivery/api/blueprint_review_views.py
    if getattr(request.user, "is_superuser", False):
        return None
    project_id = await _ablueprint_project_id(artifact)
    if not _is_uuid(project_id):
        return Response(_SCOPE_UNRESOLVED_DETAIL, status=status.HTTP_400_BAD_REQUEST)
    if not await _ais_project_member(request.user, project_id):
        return Response(_ARTIFACT_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND)
    return None
```

**零件复用：** gate 链自己的 `_ablueprint_project_id`（`:511-522`，**已在本文件**，口径与 review 版同源）+ review 的 `_ais_project_member`（`:244-251`）。

**⭐ 必须 DIFFER（这是 CONTEXT 定的「更严变体」）：**

- ⛔ **不要 import `blueprint_review_views._aassert_project_scope`**——它的 400 分支正是 115-MN-03 判为「设计决策、本轮不改」的存在性暴露面。
- **两个失败分支都回同一个中性 404 常量**（读不到合法 `meta.project_id` → 404，非成员 → 404）。零新增暴露面的理由已实测成立：该链的 404 本就混合三种语义（门未开 / artifact 不存在 / 无蓝图会话），前端（115-07）按「非 200 只决定挂载点是否渲染、不进错误分档」实现 ⇒ **不需要动前端**。
- 挂载位置：`_aload_gate_context` 之后、任何 service 调用之前（与 `_aapply_action` 的 `error, result, session` 三元组形态对齐，View 只 `if error is not None: return error`）。

**E2. `confirm/` 两处 409 补 `blocked_reason`：**

```239:254:server/delivery/api/blueprint_gate_views.py
        if result.get("blocked_reason") == "pending_clarification":
            return Response({"detail": "存在未解决的阻塞澄清线程"}, status=status.HTTP_409_CONFLICT)
        if session is None:
            return Response(_GATE_NOT_OPEN_DETAIL, status=status.HTTP_404_NOT_FOUND)

        lock = await BlueprintConfirmGateAdapter().alock(session, acting_user=request.user)
        if lock.get("event") != "confirmed":
            # fail-closed：内容非法 / 并发未收敛时不放行、不落 failed，等下一次重试。
            return Response(
                {
                    "detail": _LOCK_BLOCKED_MESSAGES.get(
                        str(lock.get("reason") or ""), _LOCK_DEFAULT
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
```

**两处都要补**：第一处补 `"blocked_reason": "pending_clarification"`（service 返回值里的键现在被视图消费掉了）；第二处补 `"blocked_reason": str(lock.get("reason") or "")`（原样，`snapshot_changed` 等，与前端用例 `gatePanel.spec.ts:593` 用的值同族）。**前端已实现且已有用例**（`:577` / `:591`），后端补键即生效，**前端零改动**。

---

### E3/E4. 代码预览源码正文读面（最后一个可独立顺延的 plan）

**Analog（View）:** `server/repositories/chunk_at_views.py`（61 行）——**中性口径的说明书**：

```1:10:server/repositories/chunk_at_views.py
"""`file:line → chunk_id` 反查 REST 端点（Phase 25 IDX-02 后半，per 25-02 plan Task 2）。

``GET /api/repositories/<id>/chunk-at/?path=&line=``：返回覆盖 ``path:line`` 的 chunk(s)。

安全语义（复用 ``services.chunk_lookup.find_chunk_at`` 的 fail-closed）：
- ``permission_classes=[IsAuthenticated]``：未认证 401/403（T-25-06）。
- 被排除文件与「无命中」对外**不可区分**——两者统一返回 ``{"chunks": []}`` 200，
  避免存在性泄漏（T-25-05）。
- ``path``/``line`` 缺失或 ``line`` 非正整数 → 400（不触 service，T-25-07）。
"""
```

**沿用：** adrf `APIView` + `aget_object_or_404(Repository, id=…, is_deleted=False)` + 参数逐个前置 400 + service 层 fail-closed；⭐ **`is_excluded` 取 `chunk_at` 的中性口径**（被排除与无命中统一 200 空），⛔ **不取 MCP `get_repository_file` 的 404 `file_excluded` 口径**（`mcp_tools/views.py:1005-1009` 显式告知，与 115-07 的「非 200 不进错误分档」冲突，且引用预览本就有快照兜底）。

**⚠️ 成本比 CONTEXT 估的高（No Analog #6）：** `GetRepositoryFileView` 的全部逻辑——`_excluded_response` / `_read_from_mirror` / `_get_indexed_repo` / `_resolve_graph_branch` / Qdrant chunk 拼接回退——**全部是 View 的方法**（`:978-1090+`），没有可 import 的服务层：

```988:1010:server/mcp_tools/views.py
    async def _excluded_response(
        self,
        repository_id: str,
        *paths: str,
    ) -> Response | None:
        """对 requested / resolved 路径做 fail-closed 排除判定；命中 → 「已排除」错误。

        resolved_path 必须复判（防后缀解析绕过，T-22-21）。命中绝不返回任何 content。
        """
        matcher = await _exclusion_matcher(repository_id)
        for path in paths:
            if path and matcher.is_excluded(str(path)):
                log_exclusion_blocked(
                    surface="get_repository_file",
                    repository_id=repository_id,
                    rel_path=str(path),
                )
                return error_response(
                    "file_excluded",
                    "文件已被排除策略屏蔽",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
        return None
```

⇒ **推荐先抽 `services/repo_file_read.py`**（把上述方法体下沉成模块函数，返回中性结构而非 `Response`，由两个 View 各自映射成自己的错误口径），MCP View 改成调用它。这会改一个 MCP 面 ⇒ **需回归 `TOOL_SCHEMA_SNAPSHOT` 守门**。⛔ 复制一份违反 fail-closed 单一实现纪律。**这正是这个 plan 值得独立顺延的理由**——若顺延，**必须同时改 `REQUIREMENTS.md` VIEW-02 里那句「顺延 Phase 116」**。

---

### F. 测试形状

**Analog A（REST 端点）:** `server/tests/delivery/test_blueprint_review_views.py`（1102 行）——docstring「守 N 件事」编号清单（每条把可证伪断言写进条目本身）；`pytestmark = pytest.mark.django_db(transaction=True)`；范围闸工厂 `_SCOPE_PROJECT_ID` / `_OTHER_PROJECT_ID` / `_make_project(project_id, member=…)`；懒 import 的 patch 目标指向**来源模块**。

**Analog B（源码扫描守卫）:** `tests/delivery/test_blueprint_log_redaction_guard.py`——`_SERVER_DIR = Path(__file__).resolve().parents[2]` + `ast.walk` + **「守护的守护」用例**（`:94-115`，证明规则真的能逮住违规）。本相位的三条结构断言（renderer 签名、`RELATES_TO` 恰好 1 条、开关实参必须是字面量）都该照这个形态写，**并各配一条「守护的守护」**。

**本相位守护点（PLAN 逐条落）：**

| 文件 | 守护点 |
|---|---|
| `test_engine_dispatch.py` | ⭐ **变异用例期望值按 §A.3 写**：从 `intake` 用 `build_orchestration_engine()` 驱 ⇒ 落 **FAILED 且 `error["stage"] == "reroute"`**；或从 `merge` 驱 ⇒ 落一份 `content.get("schema_version") != "blueprint/v1"` 的版本。⛔ **不要写「断言未到 DONE」**（正确实现下会话停在 spec_gate 等澄清，也不是 DONE ⇒ **恒绿、变异不敏感**，P-3）。⚠️ A1 假设未解除 ⇒ **Wave 0 先跑一次探针**确认落点确实是 `reroute` |
| `test_blueprint_intake.py` | 三条硬断言（§给 PLAN 第 5 条）：`content["schema_version"] == "blueprint/v1"`；`session.current_artifact_version_id` 非空；`meta.project_id` 能被 `ProjectMember` 查中。⭐ MCP 入口单列一条「传 `McpWorkItemContext.space_id` ⇒ 用例转红」 |
| `test_blueprint_render.py` | `inspect.signature` 参数名集合恰为 `{content, blueprint_status}`；白名单三态各一条 + `""` + 未知串**都出标注**；`decision_log` 缺键渲染「—」；`blockText` 四分支优先级与后端 fixture 逐字一致 |
| `test_blueprint_export_views.py` | 两端点未认证拒；非成员中性 404 且与「不存在」逐字相同；availability 三 reason 各一例；上游抛 `FeishuDocAPIError` ⇒ 400/502 + detail 不含上游 body；⭐ **导出前后 `ArtifactVersion` 计数不变**（留痕不进 content） |
| `test_blueprint_normalizer.py` | 目标不存在 ⇒ 不产边 + 一条记了 `source_type` 的 `sampling` 事件；两条指向同一实体的 citation ⇒ 活跃边恰好 1 条且 `metadata.citation_ids` 有 2 项；`RELATES_TO` 出边恰好 1 条；`space_id` 反查不到 ⇒ **不产事件 + warning** |
| `test_related_relations_param.py` | ⭐ **端到端**：造边 → 被引方 `?direction=in&relations=REFERENCES&max_hops=1` 查回引用方；非法 relation → 400；**不传 `relations` 时行为与改动前逐字一致** |
| `test_blueprint_gate_scope.py` | 7 个 View 各一条非成员用例（参数化）；⭐ **读不到 `project_id` 与非成员回同一个中性 404 响应体** |
| `test_blueprint_clarification_tools.py` | 两工具 snapshot 条目存在；对 `ai_review_finding` 线程作答 ⇒ 400 **且线程状态一字未变**（从 DB 重读）；不可编辑状态 ⇒ 400 且 DB 未动；响应含 `reflow` |

**避免：** class 风格 `TestCase`；只断言响应体不重读 DB；async service 测试忘 `transaction=True`；把 P-16 的既有红当成本相位引入。

---

## Shared Patterns（跨文件通用）

### S1. 观测五件套（后端新增面强制）
**Source:** `blueprint_doc_views._log`（`:206-216`）、`blueprint_review_views._log`（`:284-294`）
事件名 snake_case（`xxx_started/completed/failed`）+ `category="caller"` + `component=<新常量>` + `artifact_id` + `initiated_by_user_id=… or "system"` + `duration_ms=round((time.monotonic()-started)*1000, 2)`。
⚠️ **只读 GET 也记 caller 事件**；高频内部步骤（normalizer 的丢弃计数、单次 LLM turn）走 `category="sampling"`。
⛔ **正文一律不进日志**（T-114-36）：`body` / `question` / `quote` / citation 文本只记**长度**。
✅ **MCP 工具的 QPS/错误率/时长自动满足**（基类 `_record` 已落 `RequestMetric`，见 §B1）——⛔ 不要再手写一份。

### S2. 脱敏不可绕过
**Source:** `blueprint_review_action._detail`、`mcp_tools/views.py:4313`（`redact_secrets_in_text(str(exc))[:500]`）
任何 `error=` 实参必须经 `redact_secrets_in_text` / `redact_credentials` / `_detail` / `redact_for_ledger` 之一（AST 守卫强制）。**本相位新建的 5 个模块加进 `_SCANNED_MODULES`，且与模块创建同 commit**（§0.3）。

### S3. best-effort 不反噬业务
**Source:** `plan_research._send_clarify_card:490-491`、`aschedule_ingestion` 内部吞异常、`orchestration_delegate.py:162-163`
发卡 / 摄取投递 / 观测 / 名单 upsert 一律 `except Exception` 吞 + `logger.warning` + 返回降级值。
**唯一例外三个**：范围闸 fail-closed 拒绝；导出上游失败如实回错；`get_normalizer` 未知 kind 响亮 KeyError。
⭐ **业务主体绝不能被包进 best-effort**（115-MJ-04）；列表/聚合端点读失败 **503 + 中性 detail 且响应体逐字不含 `items`/`total`**（P-12）。

### S4. async ORM 防裸 lazy-FK
**Source:** `blueprint_doc_views._collect_db_quality`（`:100-123`）、`_load_thread_details`（`:170-192`）
同步函数 + 内部 ORM 一律包 `@sync_to_async`；取 FK 对象走 `select_related` / `Prefetch` 预取；`.values_list()` / `.aexists()` / `.afirst()` / async 迭代。
⚠️ **显式 `order_by`**：`BlueprintThread.Meta` 无 `ordering`，无 ORDER BY 的窗口跨引擎不稳定（114-MN-01）。

### S5. 纯追加纪律
**Source:** `entrypoint.py:188-189`（`__all__ +=` 的自述）、`knowledge/sources/__init__.py:19-42`（注册字典只加不改）
验收判据可核算：`git diff <file> | rg "^-[^-]"` 必须为空的 18 个追加点见 §0.4 的 ✅ 列。
前端注意 `@antfu/eslint-config` 的自动重排会误伤 `api/index.ts` 既有导出顺序——追加时保持既有分组不动、新组追加在末尾。

### S6. 「一个判据、两个面」的对齐纪律
**Source:** 本相位有三对
① 「未经确认」：后端 `render_blueprint_markdown` 白名单 ↔ 前端 `BlueprintViewerHeader.vue` 三个状态字面量（各配变异用例）。
② block 取文本：后端 `blueprint_anchor._block_text` ↔ 前端 `utils/blueprintBlocks.blockText` ↔ 新 renderer（**三处同一字段优先级**）。
③ stage 名：⛔ **不要「统一」**（P-13）——后端 stage graph 与前端 `BLUEPRINT_STAGES` 是两套名字，换算走 `blueprintBlocks.SESSION_STAGE_ALIASES` + `PRE_TIMELINE_SESSION_STAGES`；本相位若加任何新 stage 名，必须同时补别名表，否则 `indexOf` 返 `-1`、位序推断**整条静默不生效**。

---

## No Analog Found

| # | 内容 | 说明与最近的结构模板 |
|---|---|---|
| 1 | **蓝图骨架 seed** | 全仓 `ArtifactService.create` 的调用者只有 `architect_merge_adapter.py:252`（旧链）与 `builtin_processes.py:285`（echo 测试链），**蓝图链零调用**；`blueprint_*` 家族里没有任何「从零建 artifact」的先例（它们全是「已有 artifact 加版本」）。**必须自己发明的**：11 键最小骨架的常量形状 + `requirement_spec.goal` 的原文承载 block + 与 `StageOutcome.current_artifact_version` 的接线。结构模板 = `blueprint_reflow.py` 的模块形态 + `artifact_service.create` 的调用形状。⭐ 建议 PLAN 把骨架常量做成模块级 `_MINIMAL_BLUEPRINT_SKELETON` 并单测「它能过 `validate_blueprint`」（§A.2 变体 A 已实跑为 `(True, None)`） |
| 2 | **`build_engine_for_session` 分派器** | 全仓无「按 process_type 选工厂」的先例——两个工厂都是调用方硬编码直选。⭐ **PLAN 必须写死三件事**：返回 engine 还是 `(engine, driver)`；deps `isinstance` 自检放 handler 组还是工厂内；未知 process_type 是 no-op 还是抛。⛔ 不让执行者临场选（§A4 表） |
| 3 | **不可关闭标注 + `Callable[[dict], str]` 注册契约** | 注册表只给 content（`registry.py:16`），而判据源 `Artifact.blueprint_status` 不在 content 里。全仓无「renderer 需要 content 之外的信息」的先例。解法见 §C1/§C2（必填 keyword-only + 闭合白名单 + 注册表传 `""` + 两个权威面绕过注册表）。**关键不变量是「没有任何取值能关掉标注」，不是「只有一个调用点」** |
| 4 | **per-entry 开关 + 安全默认** | `BLUEPRINT_*` 四个既有键都是「一份配置一个消费方」；本键是**一份配置四个消费方且各自独立**。最近模板 = `aload_spec_gate_config` 的读取形状；⭐ 自己发明的是「调用方传字面量、⛔ 不从 session 反推」这条纪律（§0.1）及其源码扫描断言 |
| 5 | **九种 `source_type` → 目标实体换算** | `workflow_plan.py` 只换算一种（work_item 三元组）。九种里有四种直连、三种统一落仓库节点、一种需要一次 DB 查询、一种不成边。**自己写一个 `_resolve_target_entity_id(citation) -> uuid \| None`** 并对九种各配一条用例（含「还原不出即丢弃」） |
| 6 | **SPA 源码正文读面** | 全仓确无按 `path + 行区间` 读正文的 REST 面；MCP 侧逻辑全部内联在 View 方法里、不可 import。见 §E3/§E4 |
| 7 | **chat 蓝图版挂起 / 终态判据** | 旧链两函数的判据对蓝图**全部失效且不抛异常**（`ahas_pending` 恒 False、`aall_research_tasks_terminal` 零 task 返 True）。结构模板 = `blueprint_resume.adrive_…` 的两条短路点判据；**自己发明的是 chat 语境下「挂起 marker」的形状**（要与 `register_blocking_task` 的 task key 对齐，§A8） |

---

## 与 CONTEXT 的口径分歧（PLAN 必须逐条定夺）

| # | CONTEXT 写的 | 实测/守卫要求的 | 建议 |
|---|---|---|---|
| 1 | 「反查零新端点，只补一个换算键」 | 三层不透传 `relations`，默认集不含 `REFERENCES`（RESEARCH §0.4 / §D.5） | 三处纯追加，**SC-4 的第一个 task** |
| 2 | 「用错工厂 ⇒ 全 stage 直通、一路 DONE、落空蓝图」 | 终局是 **FAILED**（`reroute` 的 `AttributeError`）；更糟的方向是 `merge` 落一份 v0 content（RESEARCH §A.3） | 变异用例期望值按真实形态写（P-3） |
| 3 | 「四个续驱点」 | 实测 8 处，其中 **6 处要改**，`callbacks.py:447` 不可达（RESEARCH §A.4） | 按 §A.4 表 |
| 4 | 「assumptions 档位零新机制」 | `_MAX_SPEC_GATE_ROUNDS` 是模块级常量、配置里没有这个键（P-11） | 单列一个 task 改 `aload_spec_gate_config` 签名 + 两处读配置 |
| 5 | `render_blueprint_markdown(content, *, blueprint_status)` | 与 `ContentRenderer = Callable[[dict], str]` 不兼容（RESEARCH §C.2） | 注册表分支传 `""`，两个权威面绕过注册表 |
| 6 | 事件字段 `entrypoint` 可区分四入口 | ⭐ **MCP 传的是 `"workflow"`**（本文件 §0.1，新发现） | 加独立 `entry_key` 形参；开关由调用方传字面量 |
| 7 | 「`sections.spec.ts` 那条用例改判据」 | **拆两条**：`getRelated` 转真实断言，`getArtifactAssociations` 仍必须为 0（`artifact_associations.py:75` 查的是 `initiatives.Artifact` 投影，对 `delivery.Artifact` id 依然必然落空） | 拆，不翻转 |
| 8 | 触发点唯一 = `add_version` | `create` 是一处真实例外（v1 骨架不经它，P-10） | 两处都挂门控（方案 a） |

---

## Metadata

**Analog search scope:**
- 后端：`server/services/process_runtime/`、`server/delivery/{api,services,artifacts}/`、`server/knowledge/{,api,sources}/`、`server/mcp_tools/`、`server/feishu/`、`server/chat/`、`server/repositories/`、`server/system/`、`server/tests/{delivery,services,knowledge,mcp_tools}/`
- 前端：`web/src/{api,components/blueprint}/`

**Files scanned:** 约 40 个候选路径；**精读 24 个 analog**（大文件用非重叠定向切片：`mcp_tools/views.py` 四段、`blueprint_gate_views.py` 两段、`chat/views.py` 一段、`blueprint_review_views.py` 两段）：
`entrypoint.py` / `builtin_processes.py` / `blueprint_resume.py` / `answer_resume.py` / `blueprint_ambiguity_score.py` / `blueprint_spec_gate.py` /
`delivery/artifacts/builtin_types.py` / `registry.py` / `artifact_service.py` / `blueprint_doc_views.py` / `blueprint_review_views.py` / `blueprint_gate_views.py` / `delivery/urls.py` /
`knowledge/sources/workflow_plan.py` / `knowledge/sources/__init__.py` / `knowledge/related.py` / `knowledge/retrieval.py` / `knowledge/api/views.py` / `knowledge/ingestion.py` /
`mcp_tools/views.py` / `mcp_tools/serializers.py` / `mcp_tools/urls.py` / `mcp_tools/orchestration_delegate.py` /
`feishu/coding_plan_exporter.py` / `chat/views.py` / `repositories/chunk_at_views.py` / `system/models.py` / `system/settings_service.py` / `workflows/nodes/ai/plan_research.py` / `interactions/entry.py` /
测试：`tests/delivery/test_blueprint_log_redaction_guard.py`
前端：`web/src/api/knowledge.ts` / `components/blueprint/__tests__/sections.spec.ts`

**上游输入：** `116-RESEARCH.md`（§0 四条核验 / P-1…P-16 / 可复用件速查表 / 给 PLAN 的八条硬要求，已逐条实读核对）、`116-CONTEXT.md`、`.planning/ROADMAP.md` Phase 116、`.planning/REQUIREMENTS.md`、`.planning/STATE.md` §13.2、`115-PATTERNS.md`（house style）

**新增运行时依赖：零。**

**Pattern extraction date:** 2026-08-01
**Valid until:** 111–115 后端模块、`web/src` 既有件、或同步点 2 的合并改动即需重核行号
