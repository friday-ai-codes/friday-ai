---
phase: 113-2
status: passed
score: 54/54
verified: 2026-07-30
---

# Phase 113: 分仓方案与融合（阶段 2/3）+ Blueprint Context Bus — Verification Report

**Phase Goal:** 确认后的每个仓产出结构化分仓方案，跨仓动态依赖靠会话级上下文总线协商；主 agent 融合装配出六段齐全、引用完备、跨仓 API 对账闭环的完整蓝图。
**Verified:** 2026-07-30
**Status:** passed（1 项 WARNING，非 BLOCKER）
**Re-verification:** No — initial verification
**Baseline for diff:** `0d37cba3`（Phase 112 末尾 commit）

Must-haves 口径 = 5 条 ROADMAP Success Criteria + 6 份 PLAN frontmatter 的 49 条 truths（7+7+8+7+9+11），合计 54。SUMMARY 自述一律不作证据，全部另行 grep / 跑测试复核。

## Observable Truths — 5 条 Success Criteria 逐条判定

| # | Success Criterion | 判定 | 证据 |
|---|---|---|---|
| SC-1 | direct 仓产出 RepoPlan（change_type/涉及文件/提供与消费 API/局部影响/风险），indirect 仓产出能力引用清单；可抛澄清、可发起单仓定向补调研 | ✓ PASS | `blueprint_repo_plan.py:503 _adispatch_direct_plan` / `:544 _asynthesize_indirect_plan`（不起容器）/ `:710 aopen_clarification(return_stage="repo_plan")` / `:660 arequest_targeted_research` 内走 `dispatch(force_deep_repository_ids={rid})`。schema 十一字段落 `blueprint_repo_plan_schema.py:BLUEPRINT_REPO_PLAN_SCHEMA`；`change_type` 枚举 `create/modify/remove/indirect_refine` 与 `blueprint_schema.py` 同源（`test_change_type_enum_matches_blueprint_schema` 直接读 `BLUEPRINT_JSON_SCHEMA` 比对）。`test_blueprint_repo_plan_schema.py` 12 例、`test_blueprint_repo_plan_stage.py` 全绿 |
| SC-2 | 容器凭 token 实时读写总线；「A 等 B 接口契约」三条路径跑通（短等待命中 / 长等待退出重派 / 互等环抛澄清） | ✓ PASS | **三条路径均有能证伪的断言**：① 短等待 `task/tests/test_blueprint_context_wait.py::test_hit_returns_immediately_and_stops_polling` + `test_since_seq_advances_with_returned_max_seq`（注入 `_now/_sleep`，零真实 sleep 断言轮询次数与增量口径）；超时走 `test_timeout_returns_normal_result_without_is_error` + `test_mcp_handler_wrapper_keeps_timeout_non_error`（返回体不含 `is_error`）。② 长等待 `server/tests/mcp_tools/test_blueprint_context_redispatch.py::test_report_endpoint_redispatches_waiting_repo_with_partial_reference` —— **真打 `POST /api/mcp/tools/report_blueprint_context/`**（`_REPORT_URL` 常量，非绕过口调 service），另有 `test_redispatch_failure_never_breaks_report_response` / `test_report_without_waiter_reports_zero_redispatch`。③ 互等环 `test_blueprint_context_wait_redispatch.py::test_mutual_wait_cycle_opens_blocking_clarification_without_dispatch` 断言 `first["cycle_detected"] is False` → `second["cycle_detected"] is True` 且**不 dispatch**（非恒真） |
| SC-3 | 蓝图过 schema 且六段齐全；实现项逐项 change_type 并映射功能↔模块↔仓库；交互流程完整叙事；API 段含数据来源与可用性 | ✓ PASS | 六段在 `blueprint_merge.py:1633-1638` 一处装配齐全（`repo_associations` / `current_state_analysis` / `implementation_overview` / `api_contracts` / `impact_analysis` / `interaction_flows`）。**确定性投影可断言不经 LLM**：`test_projection_sections_are_complete_without_any_drafted_content`（mock 掉全部 LLM 后两段仍完整）+ `test_projection_pure_functions_need_no_session_or_synthesizer`（纯函数无 session/synthesizer 亦可产出）。过门断言 `test_assembled_blueprint_passes_validate_and_has_no_raw_path_citations`；字段形状 `test_schema_03_04_05_field_shapes` |
| SC-4 | 引用覆盖率达基线（golden set 可量测）；consumed 无 provider 标 needs_support 且支持仓出现在仓库关联；跨仓矛盾抛澄清而非静默拍板 | ✓ PASS | 覆盖率门真生效：`blueprint_merge.py:1696 coverage = citation_coverage(assembled)` → `:1701 gate_gaps = coverage_gaps(assembled)`；阈值 `aget_json_setting(SettingKeys.BLUEPRINT_MERGE_CONFIG)`（`test_threshold_is_read_from_system_setting` + `test_malformed_config_falls_back_to_module_constants`）。**needs_support 落位正确（B4）**：全仓 grep 顶层 `availability` **零残留**，写入侧只有 `blueprint_merge.py:1251/1492 data_source["availability"]`；无 `available`/`unknown` 枚举变体（`:2429` 的 `"unknown"` 是 session id 兜底字符串，非枚举）；`test_unprovided_consumed_gets_needs_support_under_data_source_only` + `test_missing_support_repo_opens_clarification`。矛盾抛澄清：`test_method_conflict_opens_blocking_clarification_and_lands_no_version`。golden 可量测：`test_merged_blueprint_is_golden_measurable` 跑 `evaluate_blueprint_golden` 拿到 `citation_coverage`，门槛抬到 1.01 则 `CommandError` 且 `passed is False`（证明断言非恒真） |
| SC-5 | 有价值的总线条目经 distill 产项目记忆草案（人工 confirm 生效） | ✓ PASS | `blueprint_merge.py:2049 MemoryDistiller().distill_to_draft(proposed_by=user)`，**只调 distill_to_draft**，未出现 `MemoryService.append` / `confirm_draft` / `record_hook_writeback`。`test_blueprint_distill.py::test_valuable_entries_produce_draft_and_never_touch_active`（草案 pending，绝不动 active）+ `test_missing_session_user_skips_distill_without_faking_actor`（不伪造 actor）+ `test_distill_failure_does_not_break_merge`（best-effort 不反噬） |

**SC 小计：5/5 PASS。** PLAN frontmatter 49 条 truths 逐条经下方 Artifacts / Key Links / 测试结果覆盖，无 FAILED、无 UNCERTAIN。**合计 54/54。**

## Artifacts — 三级检查（存在 / 非 stub / 已接线）

32 个 must_haves.artifacts 全部 **存在 + 非 stub + 有非测试调用方**。

| Artifact | 行数 | `contains` 关键符号 | 状态 |
|---|---|---|---|
| `delivery/models/blueprint_context_entry.py` | 109 | `uq_blueprint_context_session_seq` ✓（`test_unique_constraint_declared` 运行时断言，非 grep） | ✓ VERIFIED |
| `delivery/migrations/0032_blueprint_context_entry.py` | 99 | 依赖 `0031_blueprint_models` ✓ | ✓ VERIFIED |
| `delivery/services/blueprint_context_service.py` | 746 | `_redact_json`（递归叶子调 `redact_secrets_in_text`）✓ | ✓ VERIFIED |
| `mcp_tools/views.py`（+385） | — | `_aresolve_blueprint_session` ✓ + `aredispatch_waiting_repos` ✓ | ✓ VERIFIED |
| `mcp_tools/urls.py`（+13） | — | `mcp-tool-read-blueprint-context` ✓ | ✓ VERIFIED |
| `task/core/knowledge_tools.py`（+171，零删除） | 611 | `read_/report_/await_blueprint_context` ✓ | ✓ VERIFIED |
| `process_runtime/blueprint_repo_plan_schema.py` | 340 | `def validate_repo_plan` ✓ | ✓ VERIFIED |
| `process_runtime/blueprint_repo_plan.py` | 1118 | `BLUEPRINT_REPO_PLAN_SOURCE` ✓ | ✓ VERIFIED |
| `subagent/api/callbacks.py`（+319，零删除） | 2574 | `_is_blueprint_repo_plan` ✓ + `waiting_context` ✓ | ✓ VERIFIED |
| `task/core/blueprint_context_wait.py` | 187 | `deadline` ✓ | ✓ VERIFIED |
| `process_runtime/blueprint_repo_waves.py` | 201 | `def build_api_waves` ✓ | ✓ VERIFIED |
| `process_runtime/blueprint_reconcile.py` | 333 | `needs_support` ✓ + `def coverage_gaps`（:118）✓ | ✓ VERIFIED |
| `process_runtime/blueprint_merge.py` | 2437 | `def derive_must_haves` ✓ | ✓ VERIFIED |
| `process_runtime/builtin_processes.py` | 850 | `_h_bp_merge`（:666）✓ | ✓ VERIFIED |
| `system/models.py`（+5） | — | `blueprint.merge.config` ✓ | ✓ VERIFIED |
| `process_runtime/blueprint_resume.py`（+42/-4） | 323 | `_STAGE_BLUEPRINT_STATUS`（:65）✓ | ✓ VERIFIED |
| 16 个测试文件 | 232–936 | `contains` 全部命中 | ✓ VERIFIED |

**孤儿代码扫描：零命中。** 8 个新模块全部有非测试调用方 —— `blueprint_context_service`→4 个（views / repo_plan / merge / callbacks）；`blueprint_repo_plan_schema`→3；`blueprint_repo_plan`→7；`blueprint_repo_waves`→3；`blueprint_reconcile`→1（merge）；`blueprint_merge`→3（call_source / entrypoint / system.models）；`blueprint_context_wait`→2；`blueprint_context_entry`→3。

## Key Links — 本相位重点（两轮 BLOCKER 的焦点）

| # | 链路 | 状态 | 证据 |
|---|---|---|---|
| 1 | `AgentSession.user` 在**两个 mode** 的派发处都被赋值（B1） | ✓ WIRED | `blueprint_research_adapter.py:465 AgentSession.objects.acreate(..., user=dispatch_user)` —— 该文件只有**一处** `AgentSession.objects.acreate`，`mode` 只影响其上方 `:459 prefix` 与 `:460 source_value`，故两个 mode **共享同一赋值点**，结构性不可漏。`dispatch_user = await self._resolve_dispatch_user(session)`（:463），为 None 时字段留空（`null=True`），未伪造 system 用户 |
| 2 | 02 的归属校验读 `sub.main_session.user_id` | ✓ WIRED | `views.py:4105 owner_id = getattr(sub.main_session, "user_id", None)`，`:4023 select_related("main_session")` 避免 async 跨表；**fail-closed 已复核**：`if owner_id is None or request_user_id is None or str(owner_id) != str(request_user_id): return None, sub, "session_not_owned"` —— 空值判拒不放行。链路 1↔2 数据来源闭合 |
| 3 | `aredispatch_waiting_repos` 在 `report_blueprint_context` 写入侧、`satisfy_waiters` **之后** | ✓ WIRED | 顺序 grep 确认：`views.py:4310 satisfy_waiters(...)` → `:4319 if redispatch:` → `:4326 BlueprintRepoPlanAdapter().aredispatch_waiting_repos(...)`，全部落在 `ReportBlueprintContextView`（`:4240`）内。置位与重派同事务顺序正确（反了会重复重派烧额度）；`:4329 except Exception` best-effort，不反噬 200/`applied` 语义 |
| 4 | needs_support 只写 `data_source.availability` / `data_source.support_repository_id`，顶层 `availability` **零残留** | ✓ WIRED | 全仓 grep：写入侧仅 `blueprint_merge.py:1251` 与 `:1492` 两处，均为 `data_source["availability"] = ...`；`:1258 data_source["support_repository_id"]`。**无任何** `contract["availability"]` / `item["availability"]` 顶层赋值；`available`/`unknown` 枚举变体零命中 |
| 5 | `blueprint_resume` 的 stage→status 表被 `_amap_blueprint_status` 消费，前七 stage 仍映射 researching | ✓ WIRED | `_STAGE_BLUEPRINT_STATUS = {"repo_plan": "drafting", "merge": "drafting"}`（:65-68）→ `_resolve_stage_status` 单点解析（`:82 .get(stage, BlueprintStatus.RESEARCHING)`，前七 stage 与空串全部回落 researching）→ `_amap_blueprint_status:294 stage_status = _resolve_stage_status(session)`，`target`（:306）与 `return_status`（:313）**两处取值都走它**。`:301` 残留的 `RESEARCHING` 是状态机入口边 `"" → researching` 的 bootstrap（非目标态硬编码），SUMMARY 偏差 4 已如实登记 |
| 6 | `technical_blueprint` 九个 stage 全注册（前七 + repo_plan + merge），`_TECHNICAL_PLAN_STAGES` 零改动 | ✓ WIRED | `rg -c '^async def _h_bp_'` = **9**（:319/324/332/347/367/386/408 + `:591 _h_bp_repo_plan` + `:666 _h_bp_merge`）；`register_process_type` 调用 = **3**（:822/831/843，另 4 处为 import/`__all__`/def）。`_TECHNICAL_PLAN_STAGES` 的 `"exhausted": STAGE_FAILED`（:249）**原样保留**；`builtin_processes.py` 全部删除行仅 3 行且全是 L511 接续点（`"confirmed": STAGE_DONE` + 其 2 行 113 接续点注释） |
| 7 | 容器 MCP 新工具在客户端白名单与服务端 view 两侧都存在且对应 | ✓ WIRED | 客户端 `KNOWLEDGE_TOOL_SCHEMAS` = **10** 项（既有 7 + `read_blueprint_context` :241 / `report_blueprint_context` :272 / `await_blueprint_context` :307）；服务端 `ReadBlueprintContextView`（views:4144）+ `ReportBlueprintContextView`（:4240）+ urls 两条 path 一一对应。`await_blueprint_context` **按设计无服务端 path**（容器侧包装，复用工厂造出的 read handler 作数据源，`knowledge_tools.py:488-515` 注释已写明），`test_await_tool_handler_is_not_the_factory_handler` 断言这层包装真的生效 |
| 8 | `_next_seq` 接缝存在且被确定性冲突用例 monkeypatch | ✓ WIRED | `blueprint_context_service.py:263 def _next_seq`（独立方法即打桩接缝），`:306` 在 `transaction.atomic()` + `ConvergenceSession.objects.select_for_update()`（:297）内被调用；`test_blueprint_context_seq.py:113 monkeypatch.setattr(BlueprintContextService, "_next_seq", _stale_first)` → 断言桩被调 ≥2 次（走了重试分支）+ `entry.seq == 2` + seq 无重复无空洞。**这条是可证伪性的主承担者，不依赖真并发调度** |

其余 PLAN 声明的 key_links 一并复核通过：`redact_secrets_in_text`（service :81）/ `select_for_update`（:297、:565、:633）/ `open_thread`（:690）/ `mode="plan"`（adapter :226/491/494）/ `record_partial` / `validate_repo_plan` / `register_waiter` / `repository_ids` / `validate_blueprint` / `add_version` / `reconcile_cross_repo_apis` / `BLUEPRINT_MERGE_CONFIG`（merge :1997）/ `distill_to_draft`（:2049）/ `repo_plan=`（entrypoint :176-177 与 handler `getattr(deps, "repo_plan")` :607、`"merge"` :693 **逐字一致**，另有 `test_blueprint_engine_deps_match_handler_getattr_names` 与 `test_blueprint_deps_roster_matches_the_factory_docstring` 双重守卫，杜绝 P-9 静默 pass-through）。

## 测试结果

**server（`tests/services/process_runtime/ tests/delivery/ tests/mcp_tools/ tests/subagent/ tests/repositories/`）——跑了两遍：**

| 轮次 | 结果 | 失败项 |
|---|---|---|
| 第 1 遍 | 1747 passed, 2 failed, 2 skipped（507s） | `test_skills_snapshot_guard.py::test_skill_files_discovered`（已登记排除）+ `test_blueprint_context_seq.py::test_threaded_concurrent_appends_have_no_duplicate_or_gap` |
| 第 2 遍 | **1748 passed, 1 failed**, 2 skipped（1355s） | 仅 `test_skill_files_discovered` |

- `test_skill_files_discovered`：`git submodule status` 显示 `skills` 前缀 `-`（未 checkout），`skills/skills` 目录不存在 → `len(SKILL_FILES) == 0`。该文件本相位**零改动**（`git diff 0d37cba3..HEAD` 空），先于本相位存在，属**已登记的环境性排除项**。
- `test_threaded_concurrent_appends_have_no_duplicate_or_gap`：**第 2 遍通过**；单跑通过（32s）；单跑 `tests/delivery/` 全绿（620 passed）。详见下方 WARNING-1。

**task（`cd task && uv run pytest -q`）：263 passed, 3 skipped（8s）——全绿。**

**旧 technical_plan 链回归（针对两处执行期缺陷修复）：**

| 断言 | 结果 |
|---|---|
| `test_technical_plan_stage_graph_is_frozen` | ✓ PASS |
| `test_technical_plan_definition_still_registered` | ✓ PASS |
| `test_old_chain_merge_exhausted_still_lands_failed` | ✓ PASS |
| `test_two_chains_do_not_pollute_each_other` | ✓ PASS |
| `test_blueprint_chain_has_no_failed_edge_but_old_chain_still_does` | ✓ PASS |
| `test_transition_without_a_new_version_keeps_the_artifact_pointer`（engine 修复正向） | ✓ PASS |
| `test_transition_with_a_new_version_advances_the_artifact_pointer`（engine 修复反向，证明不是把功能关掉） | ✓ PASS |
| `tests/delivery/test_blueprint_gate_api.py` confirm E2E（21 例） | ✓ PASS |

## Requirements Coverage

| Requirement | 判定 | 证据 |
|---|---|---|
| **FLOW-05** 阶段 2 按锁定职责逐仓拟 RepoPlan，可多轮澄清、可单仓定向补调研 | ✓ SATISFIED | `acollect_locked_repos`（取确认门锁定产物，非路由候选）+ `aopen_clarification(return_stage="repo_plan")` 有界重试 ≤2 轮后开阻塞线程 + `arequest_targeted_research` 走 `force_deep_repository_ids`（不新建机制）。`test_blueprint_repo_plan_stage.py` P-1（fitness 段未被 read-merge-write 吃掉，`acollect_fitness` 逐键断言）/ P-4（source 互斥，`_is_blueprint_research` 对 plan session 为 False） |
| **FLOW-06** 阶段 3 融合六段 + 跨仓 API 对账，needs_support 或抛澄清，绝不静默拍板 | ✓ SATISFIED | `reconcile_cross_repo_apis` 纯函数恒定三键 `gaps/conflicts/missing_support_repos`（`blueprint_reconcile.py` 顶层零 ORM/LLM import），`test_blueprint_reconcile.py` 三条断言（needs_support / 缺 support_repository_id / 字段不一致）；`test_method_conflict_opens_blocking_clarification_and_lands_no_version` 证明矛盾时**不落版本** |
| **SCHEMA-02** 关键结论携引用证据，可溯源 | ✓ SATISFIED | 投影同时填 `rationale.citations`（P-8 唯一防线，`blueprint_merge.py:425` 注释与 `test_citation_coverage_is_positive_after_projection`）；引用池先建后填、裸文件路径归一成 `cit_` id（`test_assembled_blueprint_passes_validate_and_has_no_raw_path_citations`）；`build_citation_pool` 跳过已归一值以保幂等（SUMMARY 偏差 3） |
| **SCHEMA-03** 实现项逐项 change_type + 功能↔模块↔仓库映射 + 依赖波次 | ✓ SATISFIED | RepoPlan 侧 `impl_items[].change_type/files_touched/depends_on`（schema 强制），融合侧 `implementation_overview.items[].change_type/depends_on/wave`；`test_schema_03_04_05_field_shapes` |
| **SCHEMA-04** 交互流程完整叙事（页面→接口→参数→数据→流向→行为路径） | ✓ SATISFIED | `interaction_flows` 分节起草 + `_link_api_refs` 把 `steps[].api_ref` 从接口名换算成真实契约 id（SUMMARY 偏差 4，补强而非降级）；`test_schema_03_04_05_field_shapes` |
| **SCHEMA-05** API 段含描述 / 请求响应示例 / 数据来源说明 | ✓ SATISFIED | `api_contracts[].data_source`（`from_service` / `availability` / `support_repository_id`）+ 请求响应示例；`test_unprovided_consumed_gets_needs_support_under_data_source_only` |
| **BUS-01** 容器凭 token 绑「会话→项目」作用域，实时读写、写入即可见 | ✓ SATISFIED | 三道会话校验（归属 fail-closed / `process_type == "technical_blueprint"` / 条目同会话由两 view 结构性兜住，请求体不提供会话入参面）+ 项目成员闸含 `public_org`；`test_blueprint_context_tools.py` 597 行含三道负向各一条 + 脱敏结构保真 + **全路径非 5xx**；`test_incremental_poll_sees_only_new_entry_after_report` 证明写入即对同会话可见 |
| **BUS-02** 短等待保活轮询带超时降级 / 长等待携 partial 退出后自动重派 / 互等环检测抛澄清 | ✓ SATISFIED | 见 SC-2 三条路径。补充：波次预排 `build_api_waves` 纯函数零 ORM（`test_dispatch_plans_only_dispatches_current_wave` / `test_no_api_info_keeps_full_parallel_dispatch` / `test_wave_cycle_opens_clarification_with_return_stage`）；环检测在 `register_waiter` **登记时**判定，非定时扫描或超时兜底 |
| **BUS-03** 有沉淀价值条目经 distill 进项目记忆（人工 confirm） | ✓ SATISFIED | 见 SC-5。`kind ∈ {decision, contract, api_surface}` 且 `status=active` 才入选（`test_conversation_text_only_carries_valuable_kinds` / `test_superseded_entries_are_excluded`）；`test_exhausted_exit_also_distills` + `test_retry_exit_does_not_distill` 划清触发边界 |

**9/9 SATISFIED，无 ORPHANED。** REQUIREMENTS.md 映射到 Phase 113 的 ID 集合与 6 份 PLAN 的 `requirements` 并集完全一致。

## Anti-Patterns

**1. 冻结面复核（vs `0d37cba3`）—— 11 项全部零改动**

`git diff --stat 0d37cba3..HEAD` 对下列文件**零输出**：`repo_router_v2.py` / `decompose_segments.py` / `research_adapter.py` / `architect_merge_adapter.py` / `merged_plan.py` / `clarify_adapter.py` / `render.py` / `resume.py` / `charter_service.py` / `blueprint_schema.py` / `blueprint_quality.py`。

**2. `task/core/knowledge_tools.py` 公共 handler 工厂零改动**

`git diff` 该文件**删除行为 0**（`+171/-0`，纯追加）。`_make_knowledge_handler`（:364）保留 `timeout=60.0`（:409）、`quota_counter` 计数逻辑（:383/388/396）原样，**未加 callback 参数**（`rg callback` 仅命中禁令注释）。运行时守卫：`test_knowledge_handler_factory_signature_unchanged` + `test_whitelist_is_ten_and_allowed_tools_match`。

**3. `blueprint_resume.py` 受限扩展在预算内**

删除行 = **4 行 ≤ 8**，全部落在 `_amap_blueprint_status` 内：2 行 docstring（旧「阶段 0/1 全程 researching」措辞）+ `target = ... else BlueprintStatus.RESEARCHING`（换成 `stage_status`）+ `return_status=BlueprintStatus.RESEARCHING if blocked else None`（换成 `stage_status if blocked else None`）。`aresume_blueprint_session` 既有分支语义、`_aload_artifact`、函数签名、best-effort 吞异常纪律全部未动。

**4. 债务标记扫描：零命中**

44 个改动 py 文件全量 `rg "TBD|FIXME|XXX"` 与 `rg "\bTODO\b|\bHACK\b|PLACEHOLDER|not yet implemented|coming soon"` **均零命中**，无不可审计的遗留债务。

**5. 孤儿代码：零命中**（见 Artifacts 段）

**6. 唯一 WARNING**

| # | 项 | Severity | 说明 |
|---|---|---|---|
| WARNING-1 | `test_threaded_concurrent_appends_have_no_duplicate_or_gap` 满套件下**偶发**失败 | ⚠️ WARNING（非 BLOCKER） | 见 Gaps 段 |

## Deviations 审查（六份 SUMMARY 共 36 处）

逐条对照 `113-CONTEXT.md` 锁定决策与 orchestrator 对 B1/B3/B4 的三项定夺 —— **无一处偏离锁定决策**。

**分类分布：** Rule 1 前提不成立/真缺陷 13 处 · Rule 2 缺失关键功能 3 处 · Rule 3 守护测试冲突/PLAN 内部矛盾/签名不足 14 处 · 范围外未修 6 处。

**四项 CONTEXT 硬红线逐条复核（全部守住）：**

| 红线 | 结论 |
|---|---|
| B1 `AgentSession.user` 派发时写入 | ✓ 两 mode 共享单一赋值点（Key Link 1），02 的 fail-closed 校验数据来源闭合 |
| B3 `return_stage` 必传 + stage→status 表 | ✓ `blueprint_repo_plan.py:384/738` 与两个新 handler 全传 `return_stage`；映射表被三处取值单点消费（Key Link 5）；113-06 SUMMARY 偏差 4 如实登记「入口边那处 RESEARCHING 保持原样」，非隐瞒 |
| B4 needs_support 落 `data_source` 下 | ✓ 顶层 `availability` 全仓零残留（Key Link 4）。113-05 偏差 8「两处代码改写以满足『读写只走 `data_source.*`』的可 grep 性」是**加强**可审计性，非规避 |
| 不新增 CallSource 枚举 / 不复用 ProjectMemory 承载总线 / waiter 不落 stage_state | ✓ `call_source.py` 只被引用未扩枚举；新表 `BlueprintContextEntry` 独立承载；waiter 落 `kind=dependency_claim` 行（113-04 偏差 4 明确「`aplan_waves` 不直接写 `stage_state`」，正是守这条） |

**两处执行期真缺陷修复（重点核对是否破坏旧 technical_plan 链）：**

| 修复 | 是否越界 | 旧链影响 | 回归证据 |
|---|---|---|---|
| **engine artifact 指针**（113-06 偏差 1）：`ProcessEngine.advance` 把 `StageOutcome.current_artifact_version`（默认 None）无条件透传，service 的 `_UNSET` 哨兵把显式 None 当「清指针」⇒ 每次不产版本的转移都把 `session.current_artifact_version` 抹成 NULL。改为条件透传（`engine.py:117-119`） | `engine.py` **不在**任何 plan 的 prohibitions、**不在** §13.2 冻结清单 —— 未越界 | **只会变好**：核查旧链两处写指针点（`builtin_processes.py:188` / `:292`）与 `spec_generation.py:125`，**无任何调用方依赖「显式置 None 清指针」**这一语义（`_UNSET` 哨兵的存在本身就说明「不传 = 不改」才是设计意图）。修复前旧链指针同样每步被抹 | 正反双断言 `test_transition_without_a_new_version_keeps_the_artifact_pointer` / `test_transition_with_a_new_version_advances_the_artifact_pointer` 均 PASS；旧链 5 条冻结/隔离断言全 PASS；`test_blueprint_gate_api.py` confirm E2E 21 例 PASS |
| **self-loop 出口**（113-06 偏差 2）：`needs_clarification` 是 self-loop 出边，续驱只在「有 open+blocking 线程」时短路 ⇒ handler 返回 `needs_clarification` 却没线程 = 一路 advance 到 `max_steps` 落 `advance_step_limit` FAILED。新增 `_abp_ensure_blocking_clarification`（幂等、带 `return_stage`、问题文本只含 stage 名与枚举 reason，不夹带方案正文） | 纯追加于 `builtin_processes.py` 的**蓝图链**私有 helper，`_TECHNICAL_PLAN_STAGES` 零触碰 | 旧链**零接触**：新 helper 只被 `_h_bp_merge` 与 `_h_bp_repo_plan` 调用；`_abp_repo_plan_is_stuck` 只作活性探测，完成判据仍是 `aall_repo_plans_ready`（未复用 `aall_research_tasks_terminal` 作判据，守住 113-03 禁令） | `test_merge_handler_without_deps_stops_for_clarification` / `test_repo_plan_handler_passes_through_without_deps` / `test_two_chains_do_not_pollute_each_other` 全 PASS |

**结论：两处修复均落在共享面但未越界，且旧 technical_plan 链有 5 条专项冻结/隔离断言 + confirm E2E 全绿佐证，无回归。**

其余登记为「范围外未修」的 6 处（4 条既有 migration 的 `ruff I001`、`skills/` 子模块失败 ×4、seq 并发用例 flake）均如实记录、无一处掩盖失败。

## Gaps

**无 BLOCKER。** 1 条 WARNING：

### WARNING-1 — `test_threaded_concurrent_appends_have_no_duplicate_or_gap` 满套件偶发失败

- **归属：** 113-01 must_haves truth 1（seq 并发分配）的**真并发**证据用例
- **现象：** 5 目录满套件第 1 遍失败、第 2 遍通过；单跑通过；单跑 `tests/delivery/`（620 例）通过。113-03 SUMMARY 偏差 6 已按范围纪律登记不修
- **根因（已定位，非本相位引入的回归）：** SQLite 无行锁，8 路 `ThreadPoolExecutor` 各持独立连接并发写会撞**表级写锁**抛 `OperationalError`（不是 `IntegrityError`，故不走 service 的唯一约束兜底）。测试侧自行吸收并重投，但重投上界写死 20 次（`test_blueprint_context_seq.py:166`）——满套件负载下竞争加剧会超出该上界
- **为何判 WARNING 而非 BLOCKER：**
  1. **生产代码正确性不受影响**：`_append_entry_locked` 用「锁父 `ConvergenceSession` 行 + `IntegrityError` 有界重试」双层防线（`blueprint_context_service.py:294-320`）；`OperationalError` 表锁是 SQLite 测试后端独有产物，生产 PG/MySQL 走真行锁不会出现
  2. **可证伪性的主承担者是另一条用例且稳定通过**：`test_stale_next_seq_triggers_integrity_error_retry` 通过 monkeypatch `_next_seq` 确定性触发冲突重试路径，不依赖调度
  3. seq 无重复无空洞的核心不变量断言（`:187-189`）在两轮中**从未失败**——失败的是 `:192` 那条「竞争真的发生过」的**测试自检**（其本意就是防假绿）
- **建议修法（归 113-01 归属方，可留作后续加固，不阻塞 Phase 114）：** 把 `_worker` 的重投上界从固定 20 改为「按 deadline 兜底」（如 30s 内无限重投），或对 SQLite 后端把 `:192` 的自检降级为 `pytest.xfail`/`warns` 而非硬断言 —— 让「负载导致的锁竞争加剧」不再表现为失败，同时保留其防假绿意图（PG 后端仍硬断言）。**不要**放宽 `:187-189` 三条核心不变量断言

### 已登记排除项（非本相位 gap）

- `tests/mcp_tools/test_skills_snapshot_guard.py::test_skill_files_discovered` —— `skills` git submodule 未 checkout（`git submodule status` 前缀 `-`）导致 `SKILL_FILES` 为空。该文件本相位零改动，先于本相位存在，属工作树环境问题

---

## 结论

**status: passed —— 54/54 must-haves verified，0 BLOCKER，1 WARNING。**

- 5 条 Success Criteria 全部 PASS，SC-2 三条路径均有能证伪的断言（路径 2 真打 `POST /api/mcp/tools/report_blueprint_context/`，未走绕过口）；SC-3 确定性投影部分可断言不经 LLM；SC-4 覆盖率门与 `data_source.availability` 落位均真生效且 golden 可量测；SC-5 distill 只产 pending 草案。
- 两轮 BLOCKER 焦点的 8 条 key_links 全部 WIRED，其中 B1（`AgentSession.user` 两 mode 共享单一赋值点）与 B4（顶层 `availability` 全仓零残留）为结构性闭合，不依赖调用方自觉。
- 冻结面 11 项 + `knowledge_tools.py` 公共 handler 工厂**零改动**；`blueprint_resume.py` 删除 4 行全在目标函数内；债务标记与孤儿代码零命中。
- 36 处偏差无一偏离 CONTEXT 锁定决策；两处执行期真缺陷修复落在共享面但未越界，旧 technical_plan 链经 5 条专项冻结/隔离断言 + confirm E2E 21 例全绿佐证**无回归**。
- server 1748 passed / task 263 passed；唯一稳定失败项为已登记的 `skills/` 子模块环境问题。

---

_Verified: 2026-07-30_
_Verifier: Claude (gsd-verifier)_
