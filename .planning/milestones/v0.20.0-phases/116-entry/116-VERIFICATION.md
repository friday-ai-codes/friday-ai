---
phase: 116-entry
status: passed
score: 121/121
verified: 2026-08-01T14:00:30Z
overrides_applied: 0
deferred:
  - truth: "四个 per-entry 开关键的默认值翻成 `technical_blueprint`（旧 process 退役收口）"
    addressed_in: "同步点 2 之后的收尾 plan（v0.19.0 Phase 109/110 合并之后）"
    evidence: "ROADMAP SC-1 当前文本逐字把「默认切换与旧 process 退役收口」划在本相位之外（「**本相位已交付旧链残余流量的可观测性**……**默认切换与旧 process 退役收口顺延同步点 2 后的收尾 plan**」）；REQUIREMENTS.md:139 的 GATE-01 行同样是 ✅ 已交付 / ⏭ 仍缺两段式；STATE.md Pending Todos 第 2 条登记为「⛔ 不属于任何已完成 plan」。**语义理由（不只是纪律理由）**：蓝图 `DONE` 的语义是「等人审」，而 `plan_research._map_terminal` 把 `DONE` 映射成 completed 并喂给下游 `ai_coding` ⇒ 今天翻默认 = 让编码代理拿未经人审的蓝图去建分支写代码，正面违反 RELY-01。实证：`DEFAULT_ENTRY_SWITCH` 四键全 `technical_plan`（`blueprint_entry_switch.py:66-71`），`_map_terminal`（`plan_research.py:626`）本相位一行未改"
  - truth: "`plan_research._map_terminal` 的 `DONE→completed` 改成人审 HITL 挂起（`pending_review → waiting_event`）"
    addressed_in: "同步点 2 之后的收尾 plan（与默认切换同批）"
    evidence: "ROADMAP SC-1 括注「其时为改一个设置默认值 + 三处触点升级 + workflow 节点终态映射改 HITL 挂起」。`plan_research.py:620-625` 有整段行内说明记录该顺延与理由。⭐ 四件事必须同批做，任何一件单独做都造成回退"
  - truth: "TechPlanCard / NodeDataTab / ArtifactTimeline 三处触点升级"
    addressed_in: "同步点 2 之后的收尾 plan（硬依赖 v0.19.0 Phase 109/110 的 execution 投影与事件时间线契约）"
    evidence: "ROADMAP Phase 116 的 **Depends on** 行逐字「**硬依赖同步点 2**（v0.19.0 Phase 109/110 合并：execution 投影与事件时间线契约就位后，才做 TechPlanCard/工作流节点触点升级与默认入口切换）」"
human_verification:
  # ⚠️ 以下三项**均不阻塞任何 SC**（status 仍为 passed）：SC 的可判定内核已由自动化证据
  # 结论性覆盖 —— 缺的是「本机无飞书凭证 / 交互回调等同步点 1」这两类**环境**条件，属 UAT 范畴。
  #
  # ⭐ 2026-08-02 复核：Phase 115 的四项 `human_verification` 被判定为**可自动化**（其 why_human
  # 全是 happy-dom 的能力缺口，换 Chromium 即消解）并已实跑。同一轮复核逐条看了本相位这三项，
  # 结论**相反：三项都真的不可自动化**，逐条 `not_automatable` 记在下面。
  #
  # 判据是一致的：拦路的若是**测试宿主的能力缺口**（无版面引擎 / 无媒体查询 / 组件被 stub），
  # 换个宿主就能测 ⇒ 可自动化；拦路的若是**被测物本身在环境里不存在**（没有飞书租户凭证、
  # 没有真实 LLM 与容器），那么把它 mock 掉就等于把被测物换成了 mock 自己 ——
  # ⛔ 这正是本里程碑连出四次静默假通过的成因，绝不为了勾一个 tick 再造一次。
  - test: "对一份 `pending_review` 状态的真实蓝图点「导出飞书文档」，打开生成的飞书文档"
    expected: "文档首行是「> ⚠️ 未经确认 —— 本方案尚未经人工终审（当前状态：pending_review · 版本 vN）」；六段全量 + 决策记录附录 + 引用脚注均可读；heading / 表格 / 列表版式无结构性丢失"
    why_human: "本机与 CI 均无飞书凭证 ⇒ `create_document` 无法实跑。⭐ **可自动化的两侧都已结论性验证**：markdown 生成侧由 `test_blueprint_render.py` 逐段覆盖（含 `inspect.signature` 参数名恰为 `{content, blueprint_status}`、白名单三态、空串与未知串都出标注、`decision_log` 缺键渲染「—」），端点侧由 `test_blueprint_export_views.py` 覆盖（availability 三 reason / 上游失败 400·502 中性 detail / 导出前后 `ArtifactVersion` 计数不变）。**未验的只有 `markdown_to_blocks` 的转换侧**（`services/feishu_doc.py:1232`，本相位零改动的既有件）—— 116-05 的 PLAN 已把版式定保守（heading ≤3 级、表格不嵌套、脚注用普通列表而非 `[^n]`）以规避该风险面"
    blocking: false
    not_automatable: confirmed
    reviewed: 2026-08-02
    why_not_automatable: |
      **缺的是飞书租户凭证，不是测试宿主能力。** 被测物是「真实飞书文档里的最终版式」——
      它由飞书**服务端**对 `markdown_to_blocks` 产出的 block 树的解释决定，本地没有任何东西
      可以替代那一步。mock 掉 `create_document` 之后剩下的只是「我们发出了什么」，而那一侧
      （markdown 生成 + 端点行为）**已经被 `test_blueprint_render.py` 与
      `test_blueprint_export_views.py` 结论性覆盖**，再包一层 e2e 只是把同一批断言换个地方跑。
      唯一未验的 `markdown_to_blocks` 转换侧（`services/feishu_doc.py:1232`，本相位零改动的
      既有件）恰恰只有真实租户能证伪。
      ⇒ 属 v0.19 报告 §7 归的「需要真实飞书 / Git 平台 / Runner」那一类，与 Phase 115 的
      happy-dom 能力缺口**不同类**。解除条件：一套可用的飞书应用凭证 + 一个测试知识空间。
  - test: "在飞书群里收到蓝图澄清卡片后，点击卡片上的作答按钮"
    expected: "（当前预期）卡片是**通知形态**，点击不产生副作用、不 5xx；作答请走查看器 / REST 人审端点 / MCP `answer_blueprint_clarification` 三条已实装通道"
    why_human: "`action=\"blueprint_clarify_answer\"` 未注册 handler 是**有意设计**（`CardCallbackView` 无匹配即优雅返回，⛔ 不抢占既有路由也不 5xx）；接交互回调等同步点 1（换 107 的送达设施是同一批改动，届时仍只改 `blueprint_notify.py` 一个文件）。送达链本身的每一步早退都已有 `blueprint_clarification_card_skipped` 留痕（MN-03 修复），题面过 `redact_secrets_in_text`，但**真实飞书群里的卡片长什么样**无法自动化"
    blocking: false
    not_automatable: confirmed
    reviewed: 2026-08-02
    why_not_automatable: |
      **两重环境依赖，都不是宿主能力问题。** ① 被测物是「真实飞书群里渲染出来的卡片」——
      同样要租户凭证，且卡片的最终外观由飞书客户端渲染，本地无从取证。② 「点击作答按钮」
      这一交互本身**当前有意不存在**：`action="blueprint_clarify_answer"` 未注册 handler 是
      设计决定（`CardCallbackView` 无匹配即优雅返回），接交互回调**等同步点 1**。
      对一个尚未实装的交互写自动化，只能测出「确实没有副作用」，而那一条已由既有用例覆盖。
      送达链每一步早退的 `blueprint_clarification_card_skipped` 留痕（MN-03 修复）同样已覆盖。
      ⇒ 解除条件：飞书凭证 + 同步点 1 落地交互回调。届时可自动化的部分是**回调端点的行为**，
      「卡片长什么样」仍然归人。
  - test: "把某个入口的开关翻到 `technical_blueprint`，在真实环境跑一条端到端需求"
    expected: "会话建成 `technical_blueprint`、intake 落 v1 骨架、spec_gate 按 assumptions 档位开澄清、作答后续驱推进"
    why_human: "自动化已覆盖到「开关翻转后蓝图路径可达 + 六个续驱点两把锁一起换 + intake 三条硬断言 + chat 三条断链」；剩下的是真实 LLM / 真实容器参与的端到端体感，属 UAT。⚠️ **默认仍是 `technical_plan`，本项不是上线前置**"
    blocking: false
    not_automatable: confirmed
    reviewed: 2026-08-02
    why_not_automatable: |
      **被测物是「真实 LLM 与真实容器参与下这条链跑不跑得通」，mock 掉就没有被测物了。**
      期望里的每一环都取决于模型的实际产出：intake 能不能落出合规 v1 骨架、spec_gate 按
      assumptions 档位开出的澄清题**问得对不对**、作答之后续驱**推不推得动**。
      给这些环节喂固定响应，剩下的就只是「我们的状态机会不会按脚本走」——而那一层
      （开关翻转后蓝图路径可达 + 六个续驱点两把锁一起换 + intake 三条硬断言 + chat 三条断链）
      **已经被自动化结论性覆盖**。
      ⇒ 属 v0.19 报告 §7 归的「需要生产实例 / 真实 Runner」那一类。解除条件：一套配好 AI 供应商
      与 runner 的真实环境，且默认开关翻到 `technical_blueprint`（当前仍是 `technical_plan`，
      本项**不是上线前置**）。
---

# Phase 116: 入口收编与导出（全入口统一 + MCP 协议 + 飞书导出 + 图谱物化）— Verification Report

**Phase Goal:** 全入口统一走蓝图编排、MCP 支持异步澄清、飞书导出升级、引用物化进知识图谱——蓝图成为技术方案的唯一产出形态。
**Verified:** 2026-08-01T14:00:30Z
**Status:** passed（3 项 deferred，均由 ROADMAP / REQUIREMENTS / STATE 三处显式登记；3 项 UAT，非阻塞）
**Re-verification:** No — initial verification
**Worktree/Branch:** `.claude/worktrees/v0.20-blueprint` @ `milestone/v0.20.0-blueprint`，HEAD `58499728`
**相位规模:** `git diff 29abbc8a..HEAD -- server/ web/` = **82 files, +14104, −415**

Must-haves 口径 = **4 条 ROADMAP Success Criteria**（按**当前**文本，SC-1 已在 planning 阶段按同步点 2 重写）+ **7 份 PLAN frontmatter 的 117 条 truths**（16 + 15 + 15 + 20 + 19 + 20 + 12），合计 **121**。

**七份 SUMMARY 的自述一律不作证据。** 本报告每一条判定都另行读源码 / grep / 实跑测试复核。本里程碑在 112 / 113 / 114 / 115 各出过静默假通过，116 自身评审又抓到三条 MAJOR（其中两条正是「写了没人读」的断链：assumptions 三档在生产里没有写入方、`DelegateResult.error_detail` 没有消费方）—— 因此对本相位声称交付的每一件事，都定位到**生产调用路径**而不是只看测试。

---

## Observable Truths — 4 条 Success Criteria 逐条判定

| # | Success Criterion（当前 ROADMAP 文本） | 判定 | 证据 |
|---|---|---|---|
| SC-1 | 四入口**全部具备走 `technical_blueprint` process 的可执行路径**（蓝图 intake 与功能点拆分接线完成、所有续驱点按 `process_type` 选 adapter），并由 per-entry 运行时开关控制；开关默认仍为 `technical_plan`。已交付旧链残余流量可观测性；默认切换与旧 process 退役顺延同步点 2 | ✓ PASS | 见下方「SC-1 专项复核」四小节。**四条蓝图路径全部可达**、**默认四键全旧链**、**六个续驱点两把锁一起换**、**退役观察按 `entry_key` 分桶** |
| SC-2 | MCP 入口不再 skip_clarification：立即返回会话与 pending 状态，澄清经新工具可作答、结果可续取；澄清同时推飞书卡片，交互密度按 assumptions 档位可配 | ✓ PASS | **不再 skip**：`_amaybe_start_blueprint_session`（`orchestration_delegate.py:124-170`）走 `start_blueprint_orchestration` 且 ⛔ 不传 `skip_clarification`；分派器对蓝图分支**丢弃**该 flag 并落 `blueprint_engine_ignored_legacy_flag`（`entrypoint.py:276-292`）⇒ 蓝图链**物理上没有** `clarify` dep 可跳。**立即返回 pending**：`technical_plan_service.py:479` 把 `delegate.status == "partial"` 落成 `status=partial`，响应追加 `blueprint_artifact_id` / `blueprint_status` / `pending_clarifications[]`（`:94-96`），三键**同步进** `TOOL_SCHEMA_SNAPSHOT`。**可作答**：`answer_blueprint_clarification`（`mcp_tools/urls.py:150`）调**共享 service** `blueprint_answer_action.aanswer_thread`，⛔ 不直写 `BlueprintThread`、⛔ 不自调 REST。**可续取**：`get_technical_blueprint`（`urls.py:145`）内联 pending 清单，⛔ 无第三个 list 工具，寻址键是 `artifact_id`。**飞书卡片**：`blueprint_notify.py` 一个文件收敛送达（收件人反查带 `process_type=BLUEPRINT_PROCESS_TYPE` 过滤 `:135`，题面过 `redact_secrets_in_text` `:77,80`，五条早退各有留痕）。**assumptions 三档**：`DEFAULT_ASSUMPTIONS_TIERS` 三档各带 `{threshold, max_rounds}`（`blueprint_ambiguity_score.py:71-79`），⭐ 生产写入方是 `start_blueprint_orchestration(assumptions_tier=...)`（MJ-02 修复，见下方专项） |
| SC-3 | 导出飞书文档包含六段全量 + 决策记录附录；未确认版本在界面与导出物上均带「未经确认」显式标注（对齐 RELY-01 语义） | ✓ PASS | **十段全量 + 附录**：`render_blueprint_markdown` 逐段调用（`blueprint_render.py:534-543`，含 `_section_decision_log` 与 `_section_citation_pool`）。⭐ **标注不可关闭（三条不变量全部成立）**：① 签名**恰为** `(content: dict, *, blueprint_status: str)`（`:504`，keyword-only 无默认值，`inspect.signature` 断言背书）；② 抑制集是**闭合白名单** `frozenset({confirmed, implementing, implemented})`（`:50-56`），`status not in` 即渲染 ⇒ **空串与未知串都出标注**；③ ⛔ **零布尔开关参数**。**标注是 `parts[0]`**（`:524-526`）。**两个权威面绕过注册表传真实状态**：导出端点 `blueprint_export_views.py:298-299` 与 `artifact_serializers.py:138-139` 各调 `blueprint_status_of(artifact)`；注册表分支只能传 `""`（`builtin_types.py:50`）—— 方向恰好 fail-safe。**界面侧**：`BlueprintViewerHeader.vue:103-108` 的 `CONFIRMED_STATUSES` 与后端白名单**逐字对齐**，横幅 ⛔ 无 dismiss / 无 localStorage / 无开关（`data-testid="blueprint-unconfirmed-banner"` `:166`）。**MCP 面同样带标注**：`views.py:4634` 传 `current_status` 真实值 |
| SC-4 | 蓝图 citations 物化为 REFERENCES 边、项目关联物化为 RELATES_TO 边；知识库反查「本蓝图被哪些方案/知识引用」可用 | ✓ PASS | **边**：`knowledge/sources/blueprint.py` 产 `REFERENCES`（`:243-245`，`exclusive=False` append-only、同目标聚合成一条）+ `RELATES_TO`（`:373-375`，`exclusive=True`，目标经 `ProjectKnowledgeGraphService().ensure_project_node` 幂等取得 ⇒ ⛔ 不进存在性过滤器、⛔ 不会「测试夹具恒绿」）。normalizer 注册与模块**同 commit**（`sources/__init__.py:44`）。**投递门控挂两处**：`artifact_service.py:135`（`create`，v1 骨架走它）与 `:195`（`add_version`），判据 `content.get("schema_version") != BLUEPRINT_SCHEMA_VERSION`（懒 import 常量，⛔ 不复制字面量）。⭐ **反查经真实端点端到端可用**：`?relations=` 的三层断点已纯追加打通（view `_parse_relations_param` `knowledge/api/views.py:52` → `retrieval.get_related(relations=)` `:142` → 最底层既有形参），`_DEFAULT_RELATIONS` **一字未改**；用例 `test_reverse_lookup_returns_referrer_end_to_end`（`test_related_relations_param.py:67`）从**被引方**打 `?direction=in&relations=REFERENCES&max_hops=1` 查回引用方，⛔ 不是止于 DB 的断言。**前端**：`BlueprintAssociationsSection.vue:109-127` 两块各显式传 `direction` / `relations:['REFERENCES']` / `maxHops:1`，实参是后端纯追加的第 8 键 `knowledge_entity_id`（⛔ 前端不复制 uuid5 规则） |

**SC 小计：4/4 PASS。** 7 份 PLAN frontmatter 的 117 条 truths 逐条经下方各节覆盖，无 FAILED、无 UNCERTAIN。**合计 121/121。**

---

## SC-1 专项复核（本相位的主体，也是最容易「写了没人走」的一条）

### ① 四个入口各自的蓝图路径都真的可达

⭐ **不是「有一个开关模块」就算数** —— 逐个定位到生产分支：

| 入口 | 开关查询（**字面量实参**） | 蓝图分支落点 | project_id 推导 |
|---|---|---|---|
| workflow | `plan_research.py:304` `aresolve_entry_process_type("workflow")` | `_acreate_blueprint_session` → `start_blueprint_orchestration(entry_key="workflow")` `:370-378` | `_resolve_space(context)` → `aresolve_project_id(entry="workflow", space=…)` `:353-355` |
| chat | `plan_research_tools.py:122` `("chat")` | `start_blueprint_orchestration(entry_key="chat")` `:205-213` | 会话 space 经同一收口 |
| mcp | `orchestration_delegate.py:156` + `technical_plan_service.py:71`，均为 `("mcp")` | `_amaybe_start_blueprint_session` → `start_blueprint_orchestration(entry_key="mcp")` `:160-170` | ⭐ `aresolve_project_id(entry="mcp", work_item_context=…)` `:159` —— ⛔ **不透传 `context.space_id`**（`test_entry_dispatch_wiring.py:191` 有源码断言） |
| feature_list | `feature_solution_service.py:265` `("feature_list")` | `_acreate_blueprint_session` → `start_blueprint_orchestration(entry_key="feature_list")` `:342-353` | `feature_meta.project_id`（仍校验存在性） |

⭐ **「开关没人读」这个 MJ-02 形状已被结构性排除**：四处调用是生产代码路径上的 `if`，蓝图分支各自 return 一条真实会话。**推不出 `project_id` 即拒绝发起**且**发生在建会话之前**（`entrypoint.py:371-380`，`BlueprintIntakeRejected` 抛出时 `ConvergenceSession` / `Artifact` 计数与调用前相等），四个入口各自映射成自己的错误出口（workflow 走 `NodeResult(next_handle="error")` `plan_research.py:363-368`）。

### ② 默认确实是旧链

`DEFAULT_ENTRY_SWITCH` 四键全 `PROCESS_TECHNICAL_PLAN`（`blueprint_entry_switch.py:66-71`）。三层 fail-soft 全部回落旧链：未知 `entry`（`:96-103`）/ 读设置异常（`:114-122`）/ 内层值非法（`:126-134`）。`aget_json_setting` 只保证外层 dict ⇒ 逐键 `str(raw.get(entry) or "")` 强转后白名单校验。⭐ **该模块内零 `error=` 实参**（刻意不进脱敏守卫扫描面，代价是异常文本一律不进日志，只记 `entry` / `reason` / `value` 三个标量）。

### ③ 六个续驱点**两把锁一起换**

`build_engine_for_session` 返回 `tuple[ProcessEngine, Any]`（`entrypoint.py:230-237`），蓝图分支返 `(build_blueprint_engine(...), adrive_blueprint_session_to_pause_or_terminal)`（`:289-292`）。逐个核对调用点：

| # | 续驱点 | 形态 | driver 来源 |
|---|---|---|---|
| ① | `plan_research.py:448` | `return build_engine_for_session(...)` | `execute:202,209` 解成 `engine, adrive` 并 `await adrive(engine, session, max_steps=…)` ✓ |
| ② | `plan_research_tools.py:145` / `:224` | `engine, adrive = …` ✓ | 分派器 ✓ |
| ③ | `orchestration_delegate.py:263-264` | `engine, adrive = …` ✓ | 分派器 ✓ |
| ④ | `answer_resume.py:110-112` | `dispatched_engine, adrive = …`；`engine = engine or dispatched_engine` | ⭐ **driver 恒取分派出的那个**（调用方传了 engine 也不沿用旧 driver）✓ |
| ⑤ | `plan_clarify_callback.py:262` | `engine, _adrive = …` 后传 `aanswer_round_and_resume(engine=engine)` | ⭐ **driver 由 ④ 内部再分派一次** —— 形态刻意，行内注释逐字说明；不是漏改 ✓ |
| ⑥ | `feature_solution_service.py:228` | `_build_engine` 返二元组，`_adrive:233` 解成 `engine, adrive` ✓ | 分派器 ✓ |

⭐ **④ 与 ⑤ 是 CONTEXT 未点名的真续驱点**（漏改任一条 ⇒ 蓝图会话作答后无人续驱、卡在 `waiting_clarification` **零异常**），两条都已改。源码扫描守卫 `test_entry_dispatch_wiring.py:106-120` 断言六个文件各至少一次 `build_engine_for_session` 调用。

**对称守卫**：`resume.adrive_convergence_session_to_pause_or_terminal` 顶部对蓝图会话 no-op + `wrong_driver_for_blueprint_session` 事件（`resume.py`，`test_engine_dispatch.py` 变异 C 背书）。**deps 类型自检**：`_h_bp_repo_research` / `_h_bp_merge` 的 `isinstance` 挡住 `ArchitectMergeAdapter` 往蓝图落 v0 content（`builtin_processes.py`，变异 A/B 背书，判据是「零新增 `ArtifactVersion`」而非否定式的「未到 DONE」）。

### ④ `entry_key` 在每个调用点都是字面量常量，分桶正确

⭐ **这正是 MJ-02 形状的另一半**：MCP 传给 `start_orchestration` 的 `entrypoint` 实测是 `"workflow"`（既有约定），按它聚合从第一天起就错且永不报错。

- 事件落在 `start_orchestration` **内部**（`entrypoint.py:115-123`，四入口全经它建会话 ⇒ 唯一能覆盖全部四个入口且不碰冻结文件的位置），字段是 `entry_key` **不是** `entrypoint`，两者**并列上报**。
- ⭐ **两条 `ast` 谓词守卫**（`test_blueprint_entry_switch.py:193` / `:210`）：`aresolve_entry_process_type` 首参必须是 `ast.Constant`；`start_orchestration` / `start_blueprint_orchestration` 上任何 `entry_key=` 的值也必须是 `ast.Constant`。扫描面含 `services/process_runtime/` 全目录 + 四个入口文件。
- ⭐ **「守护的守护」非平凡**（`:228-247`）：合成源码里两条反面各一行（`aresolve_entry_process_type(session.entrypoint)` / `start_orchestration(entry_key=session.entrypoint)`），断言扫描器对**两条都**报违规 ⇒ 守卫不是空扫描。
- `builtin_processes.py:1150` 的 `technical_plan` 注册项上方有退役观察注记，⛔ **未注销 `register_process_type`**（在途会话续驱会崩）。

---

## 三条 MAJOR 的「生产路径」复核（评审已修，此处独立复验而非采信 Fix Log）

| Finding | 修前形状 | 生产路径现在存在吗 | 证据 |
|---|---|---|---|
| **MJ-01** `file-lines` 走索引回退时行号错位 | 「从首个 chunk 的 `start_line` 连续数下去」⇒ chunk 重叠/空洞时把**别的行的源码**贴上被引行的行号并高亮 | ✓ | 新增 `_number_chunk_lines`（`repo_file_read.py:139-169`）：行号取自**每个 chunk 自己的 `start_line`**（`:161-163`）、重叠行 `setdefault` 去重（`:168`）、⭐ **先按区间过滤再按 `limit` 截断**（`:164-169`，顺序反了会把「区间落在大 chunk 尾部」过滤成空）。`_number_lines` 的 docstring 逐字写明它**只**能用于连续段（`:120-124`） |
| **MJ-02** assumptions 三档在生产里**没有任何写入方** | `stage_state.decomposition.assumptions_tier` 永远不存在，`SettingKeys.BLUEPRINT_ASSUMPTIONS_TIERS` 是读不到的配置键 | ✓ | ⭐ **唯一生产写入方是 `start_blueprint_orchestration(assumptions_tier=…)`**（`entrypoint.py:396-402`，照「非空且在三档内才写键」纪律），链路 `create_feishu_technical_plan` 请求键 → view → `build_work_item_technical_plan` → `delegate_process_runtime` → `_amaybe_start_blueprint_session`（`orchestration_delegate.py:169`）→ 落 `decomposition`。另有会话级留痕 `blueprint_orchestration_started(assumptions_tier=…)`（`:425`）。⭐ **`max_rounds` 是真实新增**且 `blueprint_spec_gate._MAX_SPEC_GATE_ROUNDS` 的**定义已删除**（全仓 `rg` 仅命中 `blueprint_ambiguity_score.py` 的两行**注释**，`services/` 下零定义） |
| **MJ-03** `DelegateResult.error_detail` 写了没人读 | MCP「推不出 `project_id` ⇒ 如实回错」到调用方变成「编排未产出 canonical 方案」+ `retryable: True` | ✓ | 消费方在 `technical_plan_service.py:490-493`：`rejected = bool(getattr(delegate, "error_detail", ""))`，非空 ⇒ `failed_stage="blueprint_intake"` + `retryable=False` + 回显中性 detail；`error` / `error_stage` **恒写进 `output`**（成功时空串）⇒ agent 读得到 |

**六条 MINOR** 同样各自复验存在生产落点：MN-01 `title` 过 `redact_secrets_in_text`；MN-02 入图后台任务显式带 `initiated_by_user_id`（取不到记 `system`）；MN-03 `blueprint_notify` 五条早退各落 `blueprint_clarification_card_skipped`（`:176`）；MN-04 回灌 helper 挂到作答链共同出口 `blueprint_resume.aresume_after_gate_action`；MN-05 引用预览顶层门 `!usable && !sourceUsable` 两数据源解耦（`CitationCodePreview.vue:170-171`）；MN-06 `get_technical_blueprint` 补 `schema_version` 判别（`mcp_tools/views.py:4586`），非 `blueprint/v1` 走**与「artifact 不存在」逐字相同**的 `_ARTIFACT_MISSING_DETAIL` 404（`:4597`）。

---

## 其余重点判据（逐条对齐 verification instructions 的「再验清单」）

### 「未经确认」标注不可被任何参数值或调用方关掉

✓ **三条不变量已在 SC-3 行列出，此处补关键否定证据**：`rg "render_blueprint_markdown"` 的**全部四个非测试调用点**是 `builtin_types.py:50`（传 `""`）、`artifact_serializers.py:139`（传真实值）、`blueprint_export_views.py:299`（传真实值）、`mcp_tools/views.py:4634`（传真实值）—— **没有任何一个能传出白名单内的值来抑制标注**，因为白名单只含三个已确认态。⛔ 全仓无第二个 renderer、⛔ 无布尔开关。

### `file-lines` 无存在性预言机 + 源码不入日志

✓ **`_neutral_payload(path, line_start, line_end)`（`repo_file_views.py:63-71`）是「不可读」的唯一构造入口**，被排除 / 不存在 / 无镜像三态共用它（`:132-133`）⇒ 响应体逐字相同。⛔ 端点无任何「未找到」错误分支、⛔ 不带能区分三者的 `detail`（模块 docstring `:16-22` 把这条写成纪律，并注明「连**说明用**的错误码字面量都不能写」）。**与 MCP 分道**：MCP 面的 404 `file_excluded` 逐字保留，`TOOL_SCHEMA_SNAPSHOT` 的 `get_repository_file` 条目自 `PHASE_BASE` 起**零改动**（`git diff 29abbc8a..HEAD -- server/mcp_tools/serializers.py | rg "get_repository_file"` 空输出）。**日志**：`repository_file_lines_read` 只记 `path_len` / `line_start` / `line_end` / `line_count` / `truncated` / `usable` / `duration_ms`（`:136-149`），⛔ path 原文与正文均不入日志。**区间上界是截断不是报错**（`_MAX_LINES = 400`，`:57`）。

### 抽出的两个 service 保持行为 + finding 仍不可作答

✓ **`blueprint_answer_action.aanswer_thread` 的三道闸顺序**：范围闸由调用方前置（模块 docstring 第 1 条）→ ⭐ `is_blueprint_editable` 在 `record_answer` **之前**（`:174-178`，越界时 DB 一字未动）→ ⭐ `kind == ai_review_finding` 一律拒（`:181-185`，同样在写之前，线程状态一字未变）。**两个调用方共享同一份实现**：REST `BlueprintReviewThreadAnswerView.post:659` 与 MCP `AnswerBlueprintClarificationView:4719` 各自 import 它 ⇒ ⛔ MCP 既不直写 `BlueprintThread` 也不自调 REST。REST 对外契约由「既有 `test_blueprint_review_views.py` 全绿」核算。
✓ **`repo_file_read` 抽取保持 MCP 行为**：`GetRepositoryFileView` 改调 `services.repo_file_read`，排除判定对 requested + resolved **双复判**（`:172-178` docstring，匹配器构造异常 fail-closed 视为命中），⛔ 全仓不存在第二份排除判定。

### `blueprint-gate/` 八端点范围闸

✓ **八个 View 全覆盖**：五个改快照动作经 `_aapply_action:183` 一处挂闸，`snapshot:223` / `rejected-to-boundary:408` / `upgrade-research:491` 三个直挂。⭐ **两个失败分支回同一个中性 404 常量对象** `_GATE_NOT_OPEN_DETAIL`（`:576-580`）⇒ 零新增存在性暴露面；⛔ 刻意**不 import** review 链带 400 分支的整体闸。`confirm` 两处 409 各补 `blocked_reason`（`:259` 字面量 / `:276` 透传 `lock["reason"]`），**前端零改动**即生效。

---

## Requirements Coverage

| Requirement | Source Plan | 状态（REQUIREMENTS.md） | 判定 | 证据 |
|---|---|---|---|---|
| GATE-01 | 116-01/02/03/06 | **PARTIAL** | ✓ 与实际交付一致 | ✅ 已交付部分逐条经上方 SC-1 / SC-2 复核为真；⏭ 仍缺部分（四个默认值、`_map_terminal` HITL、三处触点升级、旧 process 退役）**实证为真的「未做」**：`DEFAULT_ENTRY_SWITCH` 四键全旧链、`plan_research.py:626` 的 `_map_terminal` 本相位一行未改。⭐ **PARTIAL 是诚实的，不是乐观的** |
| VIEW-05 | 116-05 | Complete | ✓ | SC-3 行 |
| VIEW-04 | 116-04 | Complete | ✓ | SC-4 行（含端到端反查用例，⛔ 不是止于 DB） |
| VIEW-02 | 116-07 | Complete | ✓ | `file-lines` 端点 + `CitationCodePreview` 正文/行号列/区间高亮（`:210-217` `data-citation-highlight`），失败回落 quote 快照且不关弹窗、不回显错误体 |

**PLAN frontmatter 的 `requirements` 字段与 REQUIREMENTS.md 交叉核对**：116-01/02/03/06 → GATE-01；116-04 → VIEW-04；116-05 → VIEW-05；116-07 → VIEW-02。**四个 ID 全部有归属，无孤儿**。ROADMAP Phase 116 的 Requirements 行写 `GATE-01, VIEW-05（并闭合 115 顺延的 VIEW-04、VIEW-02）`，与 plan 侧一致。

### 116-07 收口修正的 26 行陈旧 Traceability（抽查而非采信）

commit `25e4c6b5` 把 VIEW-01/03、CLAR-01、Phase 111 的 8 行、112 的 6 行、113 的 9 行共 26 行由 Pending 转 Complete。抽查其引用的相位分数**全部属实**：

| 引用 | 实测 | 一致 |
|---|---|---|
| 111 「相位 verification 24/24」 | `111-VERIFICATION.md` `status: passed` / `score: 24/24` | ✓ |
| 113 「相位 verification 54/54」 | `113-VERIFICATION.md` `status: passed` / `score: 54/54` | ✓ |
| 115 「相位 verification 107/107」 | `115-VERIFICATION.md` `status: passed` / `score: 107/107` | ✓ |
| 112 FLOW-02「16/17 + gap closure」 | `112-VERIFICATION.md` 确为 `gaps_found` / `16/17`；⭐ **gap 实测已闭** —— 该 gap 的核心是「`stage_state["reroute"]["excluded"]` 是只写键、全仓无生产读取方」，现在 `_excluded_repository_ids`（`blueprint_research_adapter.py:296`）**唯一读取方在候选筛选处**（`:332-355` 逐条 `if repository_id in excluded: continue`），另有补候选路径（`:1177-1221`） | ✓ |
| FLOW-02 「替代建议是自由文本、需求文本未要求结构化 ⇒ 判 Complete」 | ROADMAP FLOW-02 原文只要求「+ 替代建议」；STATE Pending Todos 已把「补 schema 字段」登记为里程碑之后的独立工作项，⛔ 不再指向任何已完成 plan | ✓ 判定诚实 |

⭐ **没有发现任何一行是「乐观转 Complete」**：GATE-01 这条**本可以**顺势转 Complete 却保持了 PARTIAL 并写成 ✅/⏭ 两段式，是相反方向的证据。

---

## Behavioral Spot-Checks / 门禁实跑

| 门 | 命令 | 实测 | 判定 |
|---|---|---|---|
| 后端全量 | `cd server && uv run pytest tests/ -q` | **1 failed, 8980 passed, 63 skipped, 26 deselected, 1 xfailed**（521.97s） | ✓ 与预期逐字相符 |
| ⭐ 唯一失败是否仍是那一条 | — | `FAILED tests/mcp_tools/test_skills_snapshot_guard.py::test_skill_files_discovered` —— **唯一一条**。⭐ 独立复核环境成因：本 worktree 的 `skills/` 目录 `ls -la` 为**空**（`total 0`），断言要求 `skills/skills/*/SKILL.md` ≥4 ⇒ **worktree 环境产物，非相位缺陷** | ✓ |
| ⚠️ `test_memory_mr_api` 排序 flake | — | 本次全量跑**未复现**（不在失败清单里） | ✓ 不是真实缺陷 |
| migrations | `uv run python manage.py makemigrations --check --dry-run` | `No changes detected`，退出码 **0** | ✓ |
| 前端单测 | `pnpm exec vitest run` | **215 files passed / 1 skipped；1706 passed / 1 skipped**（13.14s） | ✓ 与预期逐字相符 |
| type-check | `pnpm type-check` | 退出码 **0**（`vue-tsc --noEmit` 无输出） | ✓ |
| build | `pnpm build` | `✓ built in 6.08s`，退出码 **0** | ✓ |
| lint | `pnpm lint` | **111 problems (106 errors, 5 warnings)** —— 与仓库既有基线**逐字相等** | ✓ |
| ⭐ lint 零新增（机制级核算） | 交集比对 | 报问题的 27 个文件与本相位触及的 12 个前端文件（`git diff --name-only 29abbc8a..HEAD -- web/`）**交集为空** ⇒ ⛔ 不是「数字碰巧相等」，是**逐文件**零新增 | ✓ |
| 工作区洁净 | `git status --porcelain` | `pnpm build` 重写的 `web/src/components.d.ts` 已 `git checkout` 还原；`pnpm-workspace.yaml` 本次未漂移。最终**空输出** | ✓ |

---

## Anti-Patterns Found

| 文件 | 模式 | 严重度 | 结论 |
|---|---|---|---|
| — | `TBD` / `FIXME` / `XXX` | — | **零命中**（本相位新增/改动的 server 与 web 文件） |
| `entrypoint.py:294-301` | 未知 `process_type` 不抛、回落旧链 | ℹ️ Info | **刻意设计**且有响亮事件 `engine_dispatch_unknown_process_type`。抛异常会让「将来注册第五个 process」直接崩 |
| `blueprint_entry_switch.py` 全模块 | 三层 `except: return PROCESS_TECHNICAL_PLAN` | ℹ️ Info | 配置读取 fail-soft**回落到安全方向**（旧链），符合观测规范「绝不反噬业务」；⛔ 不是把业务失败吞成空结果 |
| `blueprint_export_views.py` | 上游失败 400 / 502 | ℹ️ Info | **正确方向**：如实回错 + 中性 detail，⛔ 不静默 200 空结构（115-MJ-04 的反面教材）。best-effort 只包住 `_arecord_export_ledger` 与埋点 |
| `orchestration_delegate.py:263` / `feature_solution_service.py:228` | 仍向分派器传 `skip_clarification=True` / `force_confirm=True` | ℹ️ Info | **不是透传进蓝图链**：分派器在蓝图分支**丢弃**并落 `blueprint_engine_ignored_legacy_flag`（`entrypoint.py:276-292`），只在旧链分支透传 ⇒ 旧链逐字不变、蓝图分支自动免疫。判据集中在一处而不是散在两个调用点，形态优于逐点判 `process_type` |

**观测规范自检**（`.cursor/rules/observability-logging.mdc`）：新增事件均带 `category`（`caller` / `sampling`）+ `component`；关键生命周期带 `duration_ms`；入图后台任务显式携带 `initiated_by_user_id`（MN-02）；`BLUEPRINT_EVENTS` 的 `len == 21` 双断言未被触动（导出/摄取事件刻意不进该 frozenset）；⛔ 零新增 `CallSource` 枚举；⛔ 零新增 migration。

---

## ⭐ 里程碑收尾：四条 SC 达成度与仍然顺延的清单（供 milestone audit 直接消费）

### 四条 SC 按**当前**措辞的达成度

| SC | 当前措辞下达成？ | 一句话 |
|---|---|---|
| SC-1 | ✅ **达成** | 四条蓝图路径**都可执行**、开关**默认仍旧链**、退役流量**可按 `entry_key` 聚合** —— 这三件恰好就是 SC-1 重写后要求的全部；被排除在 SC-1 之外的「默认切换 / 退役收口」逐字划给了同步点 2 |
| SC-2 | ✅ **达成** | MCP 全链闭合：不再 skip → 立即返 `partial` + pending → 两个新工具作答与续取 → 飞书卡片首次送达 → assumptions 三档有真实生产写入方 |
| SC-3 | ✅ **达成**（导出物的**转换侧**待人验） | 六段全量 + 决策附录 + 不可关闭的标注三条不变量均成立；界面与导出物两侧白名单逐字对齐。⚠️ 真实飞书文档的版式落地待 UAT（无凭证） |
| SC-4 | ✅ **达成** | 两类边 + 三层 `relations` 打通 + **经真实端点**的端到端反查用例 |

### 里程碑收尾后仍然顺延的（⛔ 都不属于任何已完成 plan）

1. ⭐ **同步点 2 的四件事同批做**：翻四个开关默认值 + `plan_research._map_terminal` 改人审 HITL 挂起 + 三处触点升级（TechPlanCard / NodeDataTab / ArtifactTimeline）+ 旧 `technical_plan` process 退役收口。**任何一件单独做都造成回退**（翻默认而不改 `_map_terminal` = 未经人审的蓝图直接喂 `ai_coding`，违反 RELY-01）。阻塞在 v0.19.0 Phase 109/110 的合并节奏。
2. **`redact_secrets_in_text` 不覆盖数据库连接串**（平台级，与「全仓二十余处 `error=str(exc)` 未脱敏」合并成独立清理相位）。116 全相位未动它，缺口在收尾时依然存在。
3. **115-MN-03 的四语义契约整体改版**（`_aassert_project_scope` 的 400 分支对 `meta.project_id` 非法的那批 artifact 构成存在性预言机）。⚠️ **116 让暴露面从 11 扩到 15 个端点**（导出 +2、MCP 工具 +2，均 import 复用同源实现而非复制第四份）—— 这是**已知代价并已登记**，不是本次新发现。116-07 的 `file-lines` 走仓库读面口径，⛔ 不再 +1。
4. **apscheduler 周期提醒接上 `blueprint_notify` + 澄清卡片的交互回调**（等同步点 1；届时仍只改 `blueprint_notify.py` 一个文件）。
5. **FLOW-02 的「替代建议」补结构化字段**（等机器消费方出现）。
6. **chat 回灌的挂载点无结构性保证**（本轮新增）：`_afeedback_chat_blueprint_barrier` 现有三个挂载点、多挂幂等安全，但「哪些路径通向终态」仍是人工清单。彻底形态是让终态转移发事件、回灌去订阅 —— 要动 §13.2 冻结的 `ConvergenceSessionEvent`，与「`areopen_stage` 未发事件」同批定夺。
7. **平台级观察**：`RepositoryPermission` 是「任意登录用户可读任意存在的仓库」而非仓库级 ACL（非 116-07 引入，每个仓库读面都是这口径），与 Phase 111 的 MN-12「权限口径」一并定夺。

### 环境项（审计时请以 `git diff` 而非工作区状态为准）

- `tests/mcp_tools/test_skills_snapshot_guard.py::test_skill_files_discovered` 在本 worktree **恒红**（`skills/` 空目录）；主检出复跑即绿。
- `pnpm` 会向 `web/pnpm-workspace.yaml` 的 `catalogs` 回填条目；`pnpm build` 会重写 `web/src/components.d.ts`。本次两者均已还原。

---

## Gaps Summary

**无 gap。** 121 条 must-have 全部 VERIFIED。

三条 deferred 项**不是缺口**：ROADMAP SC-1 的措辞在 planning 阶段已按同步点 2 重写并与 REQUIREMENTS.md（GATE-01 → PARTIAL 的 ✅/⏭ 两段式）、STATE.md（Pending Todos 第 2 条）三处对账一致；且顺延有**语义硬理由**而不只是排期纪律——蓝图 `DONE` 语义是「等人审」，今天翻默认会把未经人审的蓝图送进编码代理，正面违反 RELY-01。把这三条判成 gap 会是本报告最可能犯的假阴性，已明确排除。

三条 human_verification 均 `blocking: false`：SC-3 的**可判定内核**（不可关闭的标注 + 十段全量 + 决策附录 + 端点错误分档）已由自动化结论性覆盖，待人验的是无凭证环境下跑不了的**飞书转换侧与呈现面**；SC-2 的卡片交互回调是**有意的当前形态**（通知形态，作答走三条已实装通道），接回调等同步点 1。

---

_Verified: 2026-08-01T14:00:30Z_
_Verifier: Claude (gsd-verifier)_
