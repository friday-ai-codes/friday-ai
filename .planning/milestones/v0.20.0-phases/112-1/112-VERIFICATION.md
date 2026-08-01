---
phase: 112-1
status: gaps_found
score: 16/17
verified: 2026-07-30
re_verification:
  previous_status: none
  note: "本相位曾有两轮 plan-checker BLOCKER（孤儿续驱函数 / charter_service 改动），本次为首次相位级 goal-backward 校验"
gaps:
  - truth: "unsuitable 仓被排除后由主 agent 补候选重调研（ROADMAP SC-3 前半 / CONTEXT「reroute 上界 ≤2 轮：unsuitable 仓排除后由主 agent 补候选重调研」）"
    status: partial
    severity: WARNING
    reason: "reroute 轮次记账、上界、超限升门全部为真且有测试；但『排除 + 补候选』这一步无实现——`stage_state[\"reroute\"][\"excluded\"]` 是只写键，全仓无生产读取方；`reroute_needed` 回边把 session 送回 repo_research 后，dispatch 的候选来源仍只有 `routing.candidates ∪ confirmation.pending_research`，既不剔除 unsuitable 仓、也不补入新候选。结果：两轮 reroute 是空转（已完成 task 不重派、无新 task），必然走到 escalate 升确认门。安全性质（有界、绝不静默失败）成立，重调研语义不成立。"
    artifacts:
      - path: "server/services/process_runtime/blueprint_research_adapter.py"
        issue: ":828 写入 `excluded`，:1049 decide_reroute 返回 unsuitable_repository_ids，两者均无消费方（rg 全仓仅命中写入侧）"
      - path: "server/services/process_runtime/builtin_processes.py"
        issue: "_h_bp_repo_research 的 dispatch 调用不传 excluded/补候选入参，reroute 回边后与首轮判据完全相同"
    missing:
      - "dispatch 侧读 `stage_state[\"reroute\"][\"excluded\"]` 并从候选集剔除 unsuitable 仓（否则它们仍留在确认门快照里当有效候选）"
      - "reroute 轮内补候选的来源：或复用 blueprint_charter_match.acollect_charter_candidates（排除已试仓）再进 repo_research，或把 reroute_needed 指回 route stage 让 BlueprintRouteAdapter 带 exclude 重跑"
      - "机制级断言：第 1 轮 reroute 后 dispatcher.await_count > 0（当前 test_blueprint_reroute.py 只断言计数与 escalate 出边，不断言『真的补了新仓』——这正是空转能通过测试的原因）"
deferred: []
---

# Phase 112-1: 规格门与双面路由调研（阶段 1） 验证报告

**Phase Goal:** 需求进来先锁规格再定仓——歧义超阈值必澄清、feature_point 带意图分类；路由融合章程/历史落点/能力树三路证据且分数可解释；逐仓容器调研产出 fitness 判定与职责建议；不合适仓有界重路由；出口硬确认门锁定仓库集与职责并回灌章程。

**Verified:** 2026-07-30
**Status:** gaps_found（1 条 WARNING，无 BLOCKER）
**Score:** 16/17 truths verified
**Re-verification:** No —— 首次相位级校验（前两轮 BLOCKER 发生在 plan-checker 阶段）
**Test baseline:** `pytest tests/services/process_runtime/ tests/delivery/ tests/repositories/ tests/subagent/ -q` → **1268 passed, 0 failed**（134s；用户提示的 skills submodule failure 位于 `tests/mcp_tools/`，不在本次范围内）

---

## Observable Truths 判定表

| # | Truth | 判定 | 证据 |
|---|-------|------|------|
| 1 | **SC-1** 歧义超阈值停在「需要澄清」并抛带候选选项+证据的问题；作答后规格锁定且同一问题不再重复问；每个 feature_point 带 greenfield/brownfield/fix | ✓ VERIFIED | `blueprint_spec_gate.py` 五步闭环：打分→开线程→挂起→作答→锁定；提问前经 `_acollect_prior`（:485）汇总 answered/resolved 线程与既有 `decision_log`，以 `prior_context` 回灌打分 prompt（:189）；锁定一次性落 `requirement_spec`+`ambiguity_report.resolved_thread_ids`+`decision_log`（:322-345）。`test_blueprint_spec_gate.py` 13 passed，`test_blueprint_ambiguity_score.py` 33 passed |
| 2 | **SC-2** 候选带 `charter_match` 分量且分数可拆解；greenfield 上 owned(planned) 仓能进候选（onion-learning case）；brownfield 命中禁区降权且 LLM 保留须给显式理由 | ✓ VERIFIED | `test_blueprint_route_stage.py` 20 例全绿，逐条机制级：`test_charter_planned_owner_enters_candidates_as_supplement`（:222，router_base=0.0 补入）/ `test_charter_component_fully_explains_ranking_difference`（:268，排序差异可归因章程分量）/ `test_boundary_hit_candidate_is_penalized_not_dropped`（:296）/ `test_boundary_candidates_always_carry_reason_or_flag`（:424，`boundary_override_reason` 与 `unjustified_boundary_hit` 恰有其一） |
| 3 | **SC-3** 每候选仓独立容器调研（PLAN 链接通任务 token 与知识 MCP），回传 fitness+role+职责+带 citations 的 findings；**unsuitable 触发重路由 ≤2 轮**，仍不收敛升确认门 | ⚠️ **PARTIAL** | 容器链、token/env、fitness 落盘、上界与升门**全部为真**（见下）；**「排除 unsuitable + 补候选重调研」无实现** —— `excluded` 只写不读，reroute 轮为空转。详见 Gaps #1 |
| 4 | **SC-4** 确认门展示清单/role/职责/fitness/现状/证据；移除/加仓/改判 role/改职责驱动对应重调研；确认后锁定 | ✓ VERIFIED | **经真实 REST 入口、不桩续驱**的端到端证伪线：`test_blueprint_gate_api.py:753-893` 六例（add_repo→stage 落 `repo_research` 且只为新仓起 1 个容器、已完成仓 task/PartialPlan 行数逐一不变；reclassify indirect→direct 触发、direct→indirect 不触发；remove_repo 不触发；upgrade-research 只为该仓起深容器；confirm 驱到 DONE 且 `confirmed_at_gate` 全真；续驱炸掉时标记仍持久化） |
| 5 | **SC-5** 确认/改判→owned_domains 草案、移除→boundaries 草案，人工 confirm 才生效；rejected 候选可一键沉淀禁区候选 | ✓ VERIFIED | `charter_draft_writeback.asubmit_charter_draft` 三分支落库；`test_charter_draft_writeback.py` 8 例含 `test_human_confirmed_charter_only_receives_draft_content`（:89）与 `test_human_confirmed_draft_content_merges_by_key`（:120）；一键沉淀端点 `BlueprintRejectedToBoundaryView`（views:330）已注册 URL |
| 6 | 缺 intent / 非法 intent 的 feature_point 被 `validate_blueprint` 拒 | ✓ VERIFIED | `blueprint_schema.py` required 数组加 `intent` + enum 三值（diff 仅此一处删除行）；`test_blueprint_schema.py` 43 passed |
| 7 | 两个运行时配置键未配/非法时逐项回默认且绝不抛；async float/json getter 语义同同步版 | ✓ VERIFIED | `settings_service.py` 0 删除行（既有 8 个 getter 逐字未动）；`test_blueprint_settings.py` 17 passed |
| 8 | 112 的 11 个 blueprint 事件常量在 `BLUEPRINT_EVENTS` 内且未污染 `ALL_EVENTS` | ✓ VERIFIED | `event_taxonomy.py` +52/-0；`test_blueprint_event_taxonomy_112.py` 5 passed |
| 9 | LLM 不可用/不可解析时规格门 **fail-closed**（判需澄清而非放行） | ✓ VERIFIED | `blueprint_spec_gate.py:134` scorer 不可用分支直落 `needs_clarification`；`normalize_ambiguity_scores` 对空 reason 一律落保守值 1.0 |
| 10 | `BlueprintThread` 唯一 writer = `BlueprintLifecycleService`，adapter/视图零 ORM 写 | ✓ VERIFIED | lifecycle_service +820/**-0**（纯追加）；`test_blueprint_inv6_guard.py` 全绿；`rg "BlueprintThread.objects.(create\|acreate)" services/ delivery/api/` 零命中 |
| 11 | breakdown = {router_base, charter_match, history_match} 三项加权之和逐位等于总分；router_base 作单一不可拆分量 | ✓ VERIFIED | `test_blueprint_route_breakdown.py` + `test_breakdown_total_equals_component_sum_end_to_end`（stage:205）；`blueprint_route.py:167` `"total": sum(components.values())` |
| 12 | history_match 经 delivery knowledge 单次检索 + `RetrievalTrace` 埋点；无 acting user 时显式标 unavailable 而非静默 0 | ✓ VERIFIED | `blueprint_route_history.py:107` `search_similar(entity_kinds=HISTORY_ENTITY_KINDS)`、:194-200 `arecord_retrieval_trace(kind=CHUNK)`；`test_history_unavailable_is_explicit_not_silent_zero`（stage:521） |
| 13 | 容器 metadata 注入三个 `FRIDAY_TASK_*` env 键（endpoint 由 `FRIDAY_BASE_URL` 推导）；token 在 SubAgentSession 建行之后 mint；空值不注入；dispatch 失败主动 revoke | ✓ VERIFIED | `blueprint_research_adapter.py:492-501`；日志只记 `has_user_token` 布尔（:417）；`rg friday_pat_` 源文件零命中 |
| 14 | 回调经 `record_partial` 落 fitness/role/responsibility/findings；缺 `fitness.verdict` → `mark_failed` | ✓ VERIFIED | `callbacks.py:1999-2038` `_parse_blueprint_fitness` 缺 verdict 返 None → mark_failed；`test_blueprint_research_callback.py` 全绿；callbacks +301/**-0**（纯追加，既有分支一字未动） |
| 15 | **续驱有生产调用方**（上轮 BLOCKER 焦点）：六个改状态端点在动作持久化后调 `aresume_after_gate_action`，失败只记事件、REST 仍 2xx | ✓ VERIFIED | `blueprint_gate_views.py` 227/257/279/300/321/435 六处调用点；confirm 在 `alock` 之后（:222→:227）；helper 自身整段 try/except 兜住（`blueprint_resume.py:126-152`）；`test_e2e_resume_failure_keeps_marker_for_next_trigger` 锁死 |
| 16 | 待调研判据**单一实现**：`acollect_pending_research_repos` 同被 `_h_bp_repo_confirmation` 与 `blueprint_resume` pause 短路复用 | ✓ VERIFIED | 三处消费同一模块级函数：`builtin_processes.py:423-426` / `blueprint_resume.py:76,95` / `blueprint_gate_views.py:94-99`；无第二份判据实现 |
| 17 | `technical_blueprint` 七 stage 已注册；三 pausable 的 wait_status 合法；reroute `exhausted` 指向 repo_confirmation；repo_confirmation 有 `research_required → repo_research` 回边 | ✓ VERIFIED | `builtin_processes.py` stage 表逐条核对（见下 Key Links #1）；`test_blueprint_process_graph.py` 全绿含 `STAGE_FAILED not in stages["reroute"].transitions.values()` |

---

## Artifacts 检查表

三级检查（存在 / 非 stub / 已接线）。全部 22 个 must_haves.artifacts 均存在且非 stub。

| Artifact | lines | contains 断言 | 三级判定 |
|----------|------:|---------------|----------|
| `services/process_runtime/blueprint_schema.py` | 1060 | `"greenfield"` ✓ | ✓ VERIFIED |
| `system/models.py` | 693 | `blueprint.spec_gate.config` ✓ | ✓ VERIFIED |
| `system/settings_service.py` | 153 | `async def aget_json_setting` ✓ | ✓ VERIFIED |
| `delivery/services/event_taxonomy.py` | 198 | `blueprint.route.scored` ✓ | ✓ VERIFIED |
| `tests/fixtures/blueprint_golden/gaokao_boost.json` | 637 | `"intent"` ×3 ✓ | ✓ VERIFIED |
| `delivery/services/blueprint_lifecycle_service.py` | 1150 | `async def open_thread` ✓ | ✓ VERIFIED（+820/-0 纯追加） |
| `services/process_runtime/blueprint_ambiguity_score.py` | 458 | `BLUEPRINT_SPEC_GATE` ×3 ✓ | ✓ VERIFIED |
| `services/process_runtime/blueprint_intent_classify.py` | 211 | `_VALID_INTENT` ×3 ✓ | ✓ VERIFIED |
| `services/process_runtime/blueprint_spec_gate.py` | 675 | `resolved_thread_ids` ×11 ✓ | ✓ VERIFIED |
| `services/process_runtime/blueprint_charter_match.py` | 388 | `def score_charter_match` ✓ | ✓ VERIFIED |
| `services/process_runtime/blueprint_route_history.py` | 215 | `entity_kinds` ✓ | ✓ VERIFIED |
| `services/process_runtime/blueprint_route.py` | 887 | `build_score_breakdown` ×3 ✓ | ✓ VERIFIED |
| `tests/.../test_blueprint_route_breakdown.py` | 326 | `onion-learning` **✗ 0 命中** | ⚠️ 位置偏差（见 Anti-Patterns #2） |
| `tests/.../test_blueprint_route_stage.py` | 590 | `boundary_override_reason` ×5 ✓ | ✓ VERIFIED |
| `services/process_runtime/blueprint_research_adapter.py` | 1113 | `env_FRIDAY_TASK_USER_TOKEN` ×3 ✓ | ✓ VERIFIED |
| `subagent/api/callbacks.py` | 2246 | `_is_blueprint_research` ×5 ✓ | ✓ VERIFIED（+301/-0） |
| `tests/.../test_blueprint_reroute.py` | 314 | `reroute_count` ×3 ✓ | ⚠️ 断言不覆盖「真的补了新仓」（Gaps #1） |
| `services/process_runtime/blueprint_confirm_gate.py` | 905 | `acollect_pending_research_repos` ✓ | ✓ VERIFIED |
| `delivery/api/blueprint_gate_views.py` | 508 | `IsAuthenticated` ×10 | ✓ VERIFIED（1 GET + 7 POST = 8 APIView，URL 全注册） |
| `services/process_runtime/builtin_processes.py` | 549 | `_TECHNICAL_BLUEPRINT_STAGES` ✓ | ✓ VERIFIED（+229/-1，删除行仅 docstring process 计数，属 PLAN 明许形状） |
| `services/process_runtime/blueprint_resume.py` | 259 | `aresume_after_gate_action` ×4 ✓ | ✓ VERIFIED |
| `repositories/services/charter_draft_writeback.py` | 203 | `asubmit_charter_draft` ×3 ✓ | ✓ VERIFIED |

---

## Key Links 检查表（本相位两轮 BLOCKER 焦点）

| # | From → To | Via | 判定 | 证据 |
|---|-----------|-----|------|------|
| 1 | `_TECHNICAL_BLUEPRINT_STAGES` → repo_research | `research_required` 回边 | ✓ WIRED | `builtin_processes.py` repo_confirmation.transitions 含 `"research_required": "repo_research"`；同表 reroute.transitions 含 `"exhausted": "repo_confirmation"`（**非** STAGE_FAILED），`"reroute_needed": "repo_research"` |
| 2 | 六个动作端点 → `blueprint_resume.aresume_after_gate_action` | 动作持久化后续驱 | ✓ WIRED | views:227(confirm，在 alock 后) / 257(remove) / 279(add) / 300(reclassify) / 321(edit) / 435(upgrade)。**无孤儿续驱函数** |
| 3 | `_h_bp_route` 写 `stage_state["routing"]` ↔ 112-04 dispatch 读 | 契约逐键一致 | ✓ WIRED | 写侧 8 顶层键（router_version/auto_selected/intent/weights_used/charter_supplement_count/unjustified_boundary_hit_count/candidates/citations），`_empty_result` 返同一 8 键全集；读侧 `_collect_candidates`（adapter:261-272）只取 `candidates[].repository_id/role_suggestion/confidence`，三键写侧全部存在（role_suggestion 由 :600 逐候选赋值） |
| 4 | `blueprint_confirm_gate` → `charter_draft_writeback.asubmit_charter_draft` | 确认门动作产 ai_draft | ✓ WIRED | confirm_gate:556→:589-596 `_asubmit_charter_drafts`；views:369 一键沉淀同调。**`charter_service.py` 对 111 末尾 commit `git diff` 为空** |
| 5 | callbacks barrier → `blueprint_resume.aresume_blueprint_session` | 全 task 终态后叫醒续驱 | ✓ WIRED | callbacks:2142 `getattr(blueprint_resume, "aresume_blueprint_session")` + :2144 await（112-04 的 `driver="pending_112_05"` 占位已被 112-05 接通） |
| 6 | upgrade-research 端点 → dispatch 的 `force_deep_repository_ids` | 人工升级深调研 | ✓ WIRED | views:409/435 → lifecycle_service:774 `BlueprintResearchAdapter().aupgrade_to_deep` → adapter:716 `dispatch(session, force_deep_repository_ids={repository_id})` → :124/:309 `_bucket` 无条件进 deep 桶。`test_e2e_upgrade_research_starts_deep_container_for_that_repo_only` 端到端锁死 |
| 7 | `entrypoint.build_blueprint_engine` → 四 adapter | deps 属性名与 handler getattr 逐字一致 | ✓ WIRED | entrypoint:168-173 `spec_gate/route/research/confirm_gate` 四键；handler 侧 `getattr(engine.deps, "route"/"research"/"confirm_gate"/"spec_gate")` 逐字匹配（名单漂移会静默空转，此处无漂移） |
| 8 | `blueprint_resume` pause 判据 → `ahas_open_blocking_threads` + `acollect_pending_research_repos` | 不用 ClarificationService | ✓ WIRED | blueprint_resume:76,95；`resume.py` 零改动，旧 technical_plan 零感知 |
| 9 | `stage_state["reroute"]["excluded"]` 写 → 读 | unsuitable 排除 + 补候选 | ✗ **NOT_WIRED** | 全仓 `rg` 仅命中写入侧 adapter:828。见 Gaps #1 |

---

## Requirements Coverage

| Requirement | 描述要点 | 判定 | 证据 |
|-------------|---------|------|------|
| **FLOW-01** | 歧义超阈值先抛带候选选项的澄清（规格门）+ 每 feature_point 意图分类 | ✓ SATISFIED | Truths #1/#6/#9；schema 必填枚举 + spec_gate 五步闭环 |
| **FLOW-02** | 逐仓容器调研产 fitness（suitable/partial/unsuitable + 理由 + **替代建议**）；不合适仓自动回主 agent 重路由（有界 ≤2）；过程对用户可见 | ⚠️ **PARTIAL** | fitness verdict/reasons/citations + 有界轮次 + 事件可见性全部为真；「**替代建议**」无结构化承载字段（`_parse_blueprint_fitness` 只收 verdict/reasons/citations/role_suggestion/responsibility/findings）；「自动回主 agent 重路由」= 空转（Gaps #1） |
| **FLOW-03** | 阶段 1 出口硬确认门；四类动作反馈驱动重调研；确认后锁定 | ✓ SATISFIED | Truth #4；六例真实 REST 端到端 |
| **FLOW-04** | direct/indirect 区分 + 结构化选仓理由与证据；indirect 默认轻量、可人工升级深调研 | ✓ SATISFIED | Truths #11/#13 + Key Link #6（upgrade-research 全链路） |
| **CHARTER-02** | 按 intent 分流加权；章程作 sanity check（禁区/maintenance_only 降权且保留须显式理由）；breakdown 含 charter_match 可解释 | ✓ SATISFIED | Truth #2/#11；`test_intent_recorded_from_feature_points` / `test_maintenance_only_candidate_gets_extra_penalty` |
| **CHARTER-03** | 确认/改判沉淀 owned_domains、移除沉淀 boundaries、rejected 可沉淀禁区；一律 AI 草案 + 人工 confirm | ✓ SATISFIED | Truth #5；`asubmit_charter_draft` 对 human_confirmed 只写 `draft_content` |

无 ORPHANED requirement（REQUIREMENTS.md 映射到 112 的 6 条与 5 份 PLAN 的 `requirements` 字段完全一致）。

---

## Anti-Patterns 与冻结面/孤儿代码扫描

### 冻结面复核（`git diff 94479721 HEAD --stat` 对 9 个声明冻结文件）

**输出为空 —— 九个冻结文件零改动：**
`codegraph/services/repo_router_v2.py` / `decompose_segments.py` / `research_adapter.py` / `architect_merge_adapter.py` / `merged_plan.py` / `clarify_adapter.py` / `render.py` / `resume.py` / `repositories/services/charter_service.py`

**纯追加纪律逐文件核对（删除行数）：** `blueprint_lifecycle_service.py` 0 / `event_taxonomy.py` 0 / `settings_service.py` 0 / `entrypoint.py` 0 / `callbacks.py` 0 / `builtin_processes.py` 1（docstring process 计数，PLAN 明许形状）。

`builtin_processes.py` 确为「只加注册项」：`_TECHNICAL_PLAN_STAGES` / `_ECHO_STAGES` / 既有两次 `register_process_type` 一字未动，新增 7 个 `_h_bp_*` handler + 一个 stage 字典 + 第三次注册。

### 孤儿代码扫描（上轮 BLOCKER 病灶）

**无孤儿模块** —— 11 个新模块逐个有生产调用方（排除 tests/ 与自身）：

| 模块 | 生产调用方 |
|------|-----------|
| `blueprint_ambiguity_score` | `blueprint_spec_gate` |
| `blueprint_intent_classify` | `blueprint_spec_gate` |
| `blueprint_spec_gate` | `entrypoint`（engine deps） |
| `blueprint_charter_match` | `blueprint_route`、`blueprint_research_adapter` |
| `blueprint_route_history` | `blueprint_route` |
| `blueprint_route` | `entrypoint` |
| `blueprint_research_adapter` | `entrypoint`、`builtin_processes`、`callbacks`、`blueprint_lifecycle_service`、`blueprint_confirm_gate` |
| `blueprint_confirm_gate` | `entrypoint`、`builtin_processes`、`blueprint_gate_views`、`blueprint_resume` |
| `blueprint_resume` | `blueprint_gate_views`（×6）、`callbacks`（barrier） |
| `charter_draft_writeback` | `blueprint_confirm_gate`、`blueprint_gate_views` |
| `blueprint_gate_views` | `delivery/urls.py`（8 条路由） |

**孤儿数据键 1 处**：`stage_state["reroute"]["excluded"]`（Gaps #1）—— 这是本次扫描唯一命中的「写了没人读」。

> 注：`technical_blueprint` process 目前无生产 **启动方**（无入口把新需求起成该 process）。这是 CONTEXT 明示的相位边界（「不做入口切换（116）」），不计为孤儿。

### 占位符/debt marker 扫描

新增 112 源文件对 `TODO/FIXME/XXX/TBD/HACK/PLACEHOLDER/not implemented` **零命中**。两处 grep 命中经核对为误报：
- `blueprint_quality.py` 三条 `TODO(Phase 114)` —— Phase 111 既有文件，本相位未触碰（不在 diff 内）
- `blueprint_ambiguity_score._NO_REASON_PLACEHOLDER` —— fail-closed 降级的具名兜底理由文案，有真实语义

### 其他发现

| # | 文件 | 类型 | 严重度 | 说明 |
|---|------|------|--------|------|
| 1 | `test_blueprint_reroute.py` | 断言盲区 | ⚠️ WARNING | 只断言轮次计数与 escalate 出边，不断言 reroute 轮真的派发了新仓 —— 这正是 Gaps #1 能通过测试的原因 |
| 2 | `test_blueprint_route_breakdown.py` | artifact 位置偏差 | ℹ️ INFO | PLAN 声明该文件 `contains: "onion-learning"`，实际 0 命中；高三提分 case 的三条机制断言落在 `test_blueprint_route_stage.py:222/268/478`。**能力存在、位置漂移**，不构成 gap |
| 3 | `system/models.py`(11 行) / `artifact_serializers.py`(6 行) / `test_artifact_injection.py`(6 行) / `test_wave_progression.py`(6 行) | formatter 回流 | ℹ️ INFO | 删除行经逐行核对**全部**为 `ruff format` 换行重排（`LOG_RETENTION_SIZE`、`ALERT_*` 常量、`JSONField(...)` 参数换行等），零语义变更。与 112-01 prohibition「既有键一个不改」的字面口径有摩擦，但键名/键值/行为均未变；且 112-04 对 `callbacks.py` 已按同一问题手工回滚（其 SUMMARY 偏差 #4）—— 建议后续 plan 统一「只对新增段跑 format」 |
| 4 | `test_charter_service.py` INV-6 守护 | 守护放宽 | ℹ️ INFO 可接受 | writer 从单值改 `_ALLOWED_WRITERS` 两值 frozenset。**强度保留**：仍是显式枚举白名单，正则/目录豁免均未引入；放宽有 112-05 PLAN(W2)「回灌写入必须放新文件」的明令依据 |
| 5 | `test_event_taxonomy_alignment.py` 守护 | 守护放宽 | ℹ️ INFO 可接受 | `referenced <= ALL_EVENTS \| BLUEPRINT_EVENTS`。未把蓝图事件塞进 `ALL_EVENTS`（那会改既有 taxonomy 语义），强度不变 |
| 6 | `test_model_usage_call_source.py` 35→44 | 既有红修复 | ℹ️ INFO | `CallSource` 8 蓝图值 + `feature_change_classify` 自 Phase 111-03 起即让该断言假红，与本相位改动无关；`agents/call_source.py` 本相位零改动 |
| 7 | `tests/mcp_tools/test_skills_snapshot_guard.py` | 环境问题 | ℹ️ INFO 排除 | `skills/` submodule gitlink 在 remote 不存在，worktree 无法初始化。非代码问题，按用户指示排除 |
| 8 | `open_gate` pending 门 | 语义副作用 | ℹ️ INFO | 门已开时不重算快照，容器回调带回的新 fitness 不自动回填（112-05 SUMMARY 已列 Deferred）。锁定读的是线程快照 + 用户裁决，不影响正确性；115 呈现面可按 id 自取 `PartialPlan` |

---

## Deviations 审查（5 份 SUMMARY 共 28 处）

逐条对照 `112-CONTEXT.md` 锁定决策。**判定：28/28 均未偏离锁定决策**，其中 26 处属 CONTEXT 明授的「Claude's Discretion（adapter 内部函数切分、返回形状细节、测试组织）」或按现实修正的事实性偏差；2 处为守护测试放宽（见 Anti-Patterns #4/#5，强度保留且有 PLAN 明令依据）。

| SUMMARY | 处数 | 关键偏差与判定 |
|---------|-----:|---------------|
| 112-01 | 2 | ① `validate_blueprint` 返 `(bool, str\|None)` 断言口径修正 ② docstring 条件式指令前提不成立未改 —— **均为事实修正，零功能偏差** |
| 112-02 | 6 | ①`prior_context` 参数（为「不重复提问」所必需，正落 CONTEXT「提问前查 decision_log 与 resolved 线程」）②③⑥ `session_service` 注入位 / `stage_state` 第 5 键 / 测试隔离 fixture —— Discretion 范围 ④ 降级条件放宽为「reason 空即保守」**方向更严（只多问不少问）**，与 CONTEXT fail-closed 同向 ⑤ intent 兜底测试旁路造数（112-01 必填枚举后正常路径造不出缺 intent 数据）—— **无偏离** |
| 112-03 | 4 | ① CJK 3-gram token 交集（**补了 CONTEXT「boundaries 命中判负」在中文整句规则下的真实可用性**，无此则禁区降权静默失效）② `_empty_result` 返 8 键全集（比 PLAN 字面 3 键更贴「形状恒定」意图，且 112-04/05 读非 candidates 键不 KeyError）③ `requirement_spec` 三级解析（PLAN 未指定来源）④ docstring 去掉冻结路由器字面名以过解耦断言 —— **无偏离，①属加固** |
| 112-04 | 6 | ① `force_deep_repository_ids`（**没它「人工升级深调研」会静默失效**，正落 CONTEXT「提供人工升级为深调研的入口」）②③ 签名/注入位补全 —— Discretion ④ callbacks 只跑 `ruff check` 以守纯追加（**正确的 scope 判断**）⑤ 事件守护白名单并入 `BLUEPRINT_EVENTS`（未污染 `ALL_EVENTS`，守 §13.2）⑥ 四处小口径（零候选短路改「并集为空」—— 按字面实现会让 add_repo 场景永不派发，**修正必要**）—— **无偏离** |
| 112-05 | 10 | ①`_arecord_gate_note` 代替 `record_answer`（**必须**：`record_answer` 会把线程推 answered → `ahas_open_blocking_threads` 失守 → 开出第二条确认门线程）② `citation_pool` 过滤（不过滤则 `alock` 恒 fail-closed，confirm 生产上永远失败）③ 锁定基线取 artifact 最新版本（否则覆盖掉规格门成果）④ 待调研判据取 `stage_state ∪ 活跃线程 options` 并集（**SC-4 断链的真正修复**：动作端点按 INV-6 只写线程行，紧随的续驱读不到新仓）⑤⑥⑦ 签名/键位/`confirmed` 分支补全 ⑧⑨⑩ 守护白名单 + 两处验收口径 + 两处既有红 —— **无偏离；①②③④ 均为「按字面实现会在生产上静默失效」的必要修正，且各配专门锁死测试** |

**特别核对（用户点出的高风险项）：** ⑧ `charter_service.py` 零改动已由 `git diff` 机械证实；④ 的并集判据仍是**唯一实现**（三个消费方共用同一模块级函数，无第二份漂移）。

---

## Gaps

### GAP-1 ⚠️ WARNING —— reroute 的「排除 unsuitable + 补候选重调研」无实现

**Truth:** ROADMAP SC-3 前半「unsuitable 触发重路由 ≤2 轮」/ CONTEXT「unsuitable 仓排除后由主 agent 补候选重调研」

**证据链：**
1. `decide_reroute`（adapter:1010-1053）正确返回 `unsuitable_repository_ids` 与 `next_round`
2. `aadvance_reroute`（:824-830）把它写进 `stage_state["reroute"]["excluded"]`
3. `rg '\bexcluded\b' --glob '!tests/**' services/ delivery/ subagent/` → **蓝图链仅命中写入侧 adapter:828**，无任何读取方
4. `reroute_needed` 回边把 session 送回 `repo_research`；`_h_bp_repo_research` 调 `adapter.dispatch(session)`（**不传 excluded、不传补候选**）
5. `_collect_candidates`（:247-290）候选来源恒为 `routing.candidates ∪ confirmation.pending_research` —— 与首轮完全相同，且 unsuitable 仓的 task 已是 `DONE`（不重派）

**实际行为：** 第 1 轮 reroute → 回 repo_research → 零派发 → 全 task 终态 → `research_complete` → reroute（round=1→2）→ `escalate` → 升 `repo_confirmation`。两轮 reroute 是**空转**，unsuitable 仓仍留在确认门快照里作为有效候选（只在快照里带 `unsuitable_count` 计数）。

**为什么测试没发现：** `test_blueprint_reroute.py` 断言的是 `reroute_count` 递增、上界、`exhausted` 出边指向 confirmation —— 全部为真。缺一条「第 1 轮 reroute 后 `dispatcher.await_count > 0`」的证伪断言。

**不判 BLOCKER 的理由：** 有界性与「绝不静默失败」两条安全性质成立（必然收敛到人裁决门，不烧无界容器额度）；且用户在确认门可经 `add_repo` 手动补仓（该路径已端到端验证真的会起容器），能力在人工路径上可达。SC-3 后半（升门由用户裁决）完整为真。

**建议修法（按侵入度递增）：**
1. **最小**：`_collect_candidates` 读 `stage_state["reroute"]["excluded"]` 并从候选集剔除 —— 至少让「排除」为真，确认门快照不再把 unsuitable 仓当有效候选
2. **补候选**：reroute 轮内调 `blueprint_charter_match.acollect_charter_candidates(exclude_repository_ids=已试仓 ∪ excluded)` 取补充候选，`create_tasks_for_session` 起新 task 后再回 `repo_research`
3. **最正统**：把 `reroute_needed` 指回 `route` stage，让 `BlueprintRouteAdapter.route` 带 `exclude_repository_ids` 重跑一次真实双面路由（契约已有 `repository_ids` 入参，改动面小），代价是多一次 RepoRouterV2 调用
4. 任一方案都补一条 `dispatcher.await_count > 0`（或新 task 行数 > 0）的机制级断言，把这条空转钉死

---

## Gaps Summary

相位目标基本达成：**规格门 fail-closed 闭环、双面路由三分量可拆解（含高三提分 case 的机制级复现）、逐仓容器调研（token/env/章程 prompt/fitness 落盘）、硬确认门八端点 + 五动作真实 REST 驱动重调研、章程回灌 ai_draft + 人工 confirm** 全部在生产路径上成立。上两轮 BLOCKER 的病灶（孤儿续驱函数、`charter_service.py` 被改）已彻底闭合：续驱有六个生产调用方、九个冻结文件 `git diff` 为空、11 个新模块无一孤儿。

唯一缺口是重路由的「补候选」这一步：轮次记账与升门都对，但轮内不真的重调研任何新仓——`excluded` 是本次扫描唯一的「写了没人读」的键。它不威胁安全性（有界 + 必然升人裁决门），但让 SC-3 的「重路由」在语义上只剩空转，且现有 reroute 测试的断言口径正好绕过了它。建议在 Phase 113 开工前以最小方案（候选集剔除 + 一条派发计数断言）补齐，避免这条空转被后续相位当成既有语义继承。

---

_Verified: 2026-07-30_
_Verifier: gsd-verifier（goal-backward，1268 passed 基线 + 冻结面 git diff + 孤儿扫描）_

---

## Gap Closure

| Gap | 状态 | Commits |
|-----|------|---------|
| GAP-1 ⚠️ reroute 的「排除 unsuitable + 补候选重调研」无实现（`excluded` 只写不读、回边空转） | ✅ **FIXED** | `3bd37ee9`（排除消费）/ `d6a78a43`（补候选闭环） |

### 实现要点

1. **`excluded` 有了唯一读取方**（`3bd37ee9`）：`BlueprintResearchAdapter._excluded_repository_ids`
   读 `stage_state["reroute"]["excluded"]`，`_collect_candidates` 从**两条候选来源**
   （`routing.candidates` 与确认门 `pending_research`）同时剔除。被排除仓连
   `RepoResearchTask` 行都不再新建。唯一豁免口是 `allow_repository_ids`，只由**人工显式
   动作**（`aupgrade_to_deep` 的升级深调研端点）填 —— 自动流程永不重开被排除仓。
2. **补候选复用双面路由**（`d6a78a43`）：`BlueprintRouteAdapter.route` 增加
   keyword-only 的 `exclude_repository_ids`（路由器候选与章程补入候选两条来源同时剔除，
   默认 `None` ⇒ 与首轮调用逐字同行为）；`aadvance_reroute` 判 `reroute` 时先在
   「排除集 ∪ 已试仓」之外重跑一次真实路由，新候选**追加**进 `routing.candidates` 后才回边
   —— 回边后 `dispatch` 的增量白名单只为新仓起容器，既有仓结论一行不动。
3. **补不到就升门**（不空转）：`_arefill_candidates` 返回空（无新候选 / 路由重跑异常）时
   决策就地由 `reroute` 转 `escalate`，`reason="no_new_candidates"`，带全部现状升确认门，
   轮次不递增（不白烧一轮）。「绝不静默失败」性质不变。
4. **排除集累积**：`excluded` 改为「历轮 ∪ 本轮 unsuitable」，历轮被排除仓不会因为
   「本轮无最新结论」而复活回候选。另新增 `reroute.supplemented`（本轮补入仓）与
   `escalation.excluded_repository_ids` 供确认门与 115 呈现面自取。
5. **约束零变更**：`MAX_REROUTE_ROUNDS = 2` 上界、增量派发白名单（`PENDING`/`STALE`）、
   「不收敛带全部现状升确认门」三项语义逐字未动；`builtin_processes.py`（含
   `_TECHNICAL_PLAN_STAGES` 与蓝图 stage 表）**零改动** —— handler 早已原样透传
   `stage_state_update`，闭环全部落在 adapter 层。

### 新增断言清单（8 条机制级，全部可证伪原空转实现）

`tests/services/process_runtime/test_blueprint_research_stage.py`（+3）：

| # | 断言 | 空转实现下的表现 |
|---|------|-----------------|
| 1 | `test_excluded_repo_is_never_dispatched_again`：`excluded=[A]` 时 `await_count == 1` 且只派 B，A 无 task 行 | 红（会为 A 起第 2 个容器） |
| 2 | `test_excluded_repo_skipped_even_when_confirmation_marks_pending`：确认门 `pending_research` 分支同样剔除 | 红 |
| 3 | `test_manual_upgrade_bypasses_exclusion`：人工升级仍可重开被排除仓（豁免口锁死） | — （护栏，防排除集把人工路径也堵死） |

`tests/services/process_runtime/test_blueprint_reroute.py`（+5）：

| # | 断言 | 空转实现下的表现 |
|---|------|-----------------|
| 4 | `test_second_round_dispatch_set_differs_and_excludes_unsuitable_repo`：**第 2 轮派发集合 ≠ 第 1 轮且不含 A**，并断言补候选把排除集传给了路由 | 红（第 2 轮派发集合为空） |
| 5 | `test_excluded_repo_never_reappears_in_later_rounds`：路由器两轮都把 A 原样召回，A 仍不进补入清单与派发集合；排除集累积为 {A, B} | 红 |
| 6 | `test_no_new_candidate_escalates_with_full_snapshot`：无新候选 → `exhausted` + `reason="no_new_candidates"` + 每仓 verdict/role/responsibility 快照 + 轮次不递增 | 红（原实现走满两轮空转才升门） |
| 7 | `test_refill_failure_escalates_instead_of_looping`：补候选依赖抛异常 → 按「补不到」升门，不上抛不空转 | 红 |
| 8 | `test_refill_never_exceeds_two_rounds`：每轮都补得到新仓时事件序列恒为 `[reroute_needed, reroute_needed, exhausted]`，`count ≤ MAX_REROUTE_ROUNDS`，且达上界后不再多花一次路由重跑 | — （上界回归护栏） |

另有 3 处既有断言按新语义收紧：原「reroute 回边」三例现注入路由替身并额外断言
`routing.candidates` 只追加不覆盖、`reroute.supplemented` 记录本轮补入仓。

### 回归验证

- `pytest tests/services/process_runtime/ tests/delivery/ tests/subagent/ -q` → **900 passed, 0 failed**
  （`tests/mcp_tools/` 的 skills submodule 环境问题不在本子集内）
- 改动文件仅 4 个（2 源 + 2 测试）：`blueprint_research_adapter.py` / `blueprint_route.py` /
  `test_blueprint_research_stage.py` / `test_blueprint_reroute.py`；九个冻结文件与
  `builtin_processes.py` 零命中。
- 改动文件经 `ruff format` + `ruff check --fix`，All checks passed。

**残留**：FLOW-02 的「替代建议」仍无结构化承载字段（`_parse_blueprint_fitness` 不收该键）——
属 GAP-1 之外的既有 PARTIAL 项，未在本次闭环范围内。
