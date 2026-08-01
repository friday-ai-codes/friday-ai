---
phase: 107-layered-presentation
verified: 2026-07-30T02:05:00Z
status: human_needed
score: 87/89 must-haves verified
overrides_applied: 0
re_verification: null
evidence:
  backend_tests: "2897 passed, 21 skipped, 3 deselected（tests/codegraph + tests/delivery + tests/services + tests/agents + tests/workflows + tests/chat + tests/test_metric_sampling.py，161.83s）"
  frontend_tests: "328 passed / 40 files（web vitest src/components/chat + src/stores）；vue-tsc --noEmit 退出码 0"
  golden_gate: "32 passed（test_repo_router_golden.py + test_repo_router_replay.py，0.14s）—— phase106-v2 baseline 零漂移"
  migrations: "makemigrations --check --dry-run → No changes detected（退出码 0）"
  property_probe: "verifier 独立穷举 clamp_llm_permutation（n<=6、k=0..3、全部子集 × 全排列）9460 组：后置条件违规 0、集合不等 0"
  debt_markers: "26 个改动源文件零 TBD / FIXME / XXX / TODO / HACK / PLACEHOLDER"
human_verification:
  - test: "对话路由面板视觉核对：两组分区、跨组 Badge 与常驻说明句、迟滞置顶提示、降级横幅与徽标灰化、折叠态降级徽标"
    expected: "与 107-UI-SPEC 一致；无新色板 / 新字号 / 新组件"
    why_human: "视觉观感与「逐像素一致」无法程序化断言（结构层已由 328 条前端用例覆盖）"
    requirement: ROUTE-01, ROUTE-02, RELY-03
  - test: "面板上勾选 / 取消一个候选后观察降级横幅与两组分区"
    expected: "横幅与分区仍在（override 继承 4 个 trace 级字段）"
    why_human: "需真实交互；store 层已有 5 条自动化用例，此项确认端到端"
    requirement: RELY-03
  - test: "真实会话触发澄清，确认飞书卡片送达且可作答；再断开配置制造 no_chat_id 确认留痕与 clarification.delivery_failed 事件"
    expected: "卡片送达且可作答；失败路径留痕并触发立即出口"
    why_human: "SC-4 前半句「澄清一定送达用户且可作答」依赖真实 IM 环境，本地无法验证"
    requirement: RELY-02
  - test: "生产先跑 `python manage.py expire_pending_clarifications --dry-run`，确认影响面后再启用 job"
    expected: "dry-run 列出存量卡死会话且零写库；影响面可接受"
    why_human: "需生产存量数据（A9：存量会话可能已被人工绕道处理，批量推进可能产生重复产出）"
    requirement: RELY-02
  - test: "生产执行 `python manage.py measure_stage1_latency --days 7 --json`（Postgres 走 percentile_cont），回填 107-MEASUREMENTS.md 的 p50/p90/p99 与采样率"
    expected: "拿到真实分位数字并回填文档；据此再议 per-call 90s 是否下调（A5）"
    why_human: "需生产数据；O-6 生产数字本 phase 已按计划 deferred 且文档已如实标注"
    requirement: RELY-05
  - test: "触发一轮澄清后在会话内确认 pending 态可见（ChatStatusBar / ClarificationCard / HumanTaskInbox 三处任一）"
    expected: "pending 态对用户可见"
    why_human: "确认既有实现仍有效；本 phase 不新增前端面，缺失则作为独立缺陷进 backlog"
    requirement: RELY-02
deviations:
  - id: MJ-02
    plan: 107-03
    original_assumption: "`auto_selected` 只由全局最高分候选驱动，与 α / block_order 无关"
    actual: "α 确实参与 auto_selected 判定（扁平列表首位按凸组合 score_ranked 排序）。评审后取「保留现状 + 订正注释 + 补护栏 + 加观测」方案"
    accepted_because: "影响方向单调安全（α 只能把 auto_selected 由 True 变 False，绝不凭空造出 high 误开自动推进）；组别本身仍不进决策路径，SC-2 的字面要求不受影响。已由 α ∈ {0, 0.35, 0.9, 1.0} 参数化护栏用例锁定单调性，抑制经 `auto_selected_suppressed_by_alpha` 上报"
    severity: warning
  - id: IN-02
    plan: 107-08
    original_assumption: "迁移文件名应与内容一致"
    actual: "`0032_repositoryroutingtrace_degrade_reason.py` 实含 degrade_reason 与 block_order 两个 AddField"
    accepted_because: "迁移已 applied，改名会让已部署实例的 django_migrations 与文件名不一致；内容 additive、无 RunPython、可逆。评审已标 deferred"
    severity: info
scope_boundaries:
  - "D-5：chat 单题澄清（ConversationIntentTrace + LangGraph interrupt）只纳入观测，不纳入出口——出口机制只覆盖 delivery.Clarification"
  - "D-6：「未澄清假设」只写 stage_state.clarification_exit，本 phase 无前端渲染面（产出正文渲染受 v0.20.0 DEPTH 冻结约束）"
  - "A3：出口不新增 ConvergenceSessionStatus 枚举值——「超时放行」在看板/投影层与「正常运行」暂无视觉区分"
  - "K 预算语义：base rank 为「被 LLM 返回子集」内的 Stage 0 相对位次；作用对象是 clamped_order 而非最终扁平列表（最终列表相对 Stage 0 的位移上界是 2K）。「丢弃式提升」不受 K 约束，靠 llm_returned_count / stage0_window_count 两键事后可识别"
  - "α=0.35 未经离线校准（离线 harness 结构上不跑 Stage 1，α 恒 0）"
  - "A5：Stage 1 per-call 超时保持 90s 未下调，待 O-6 生产数字回填后另议"
  - "T-107-01（accept）：放开候选范围硬过滤后结果含项目外仓名与其能力树节点路径 / sub_project / LLM reasoning；沿用 MCP/REST 两个已上线全库入口的既有判断，不新增可见性面（MN-09 已把透出面如实写进注释）"
  - "UI-SPEC unresolved 3：编排链（ConvergenceSession.routing / EVENT_REPO_ROUTING）前端呈现 → Phase 110"
  - "UI-SPEC unresolved 4：降级原因的排障下钻（脱敏后原始异常文本）只入事件 payload / SystemLogEntry，不做前端展开区"
---

# Phase 107: 分层呈现与链路韧性 — 验证报告

**Phase Goal:** 用户看到的路由结果分组可信、降级有明确标注，编排在澄清环节与上游抖动下不再无声卡死。
**Verified:** 2026-07-30T02:05:00Z
**Status:** human_needed
**Re-verification:** 否 —— 首次验证
**验证仓:** `/Users/zaneliu/Projects/open-source/friday-clean/.claude/worktrees/v0.19-plan-trust`（worktree），分支 `milestone/v0.19.0-plan-trust`

> 本报告不采信 SUMMARY.md 的自述。所有结论来自实读源码 + 实跑测试 + verifier 独立复算。

---

## 结论摘要

| 维度 | 结果 |
|---|---|
| 5 条 Success Criteria | 4 条 VERIFIED、1 条（SC-4）机制层 VERIFIED / 真机送达待人工 |
| 9 份 PLAN 的 77 条 truths | 77 VERIFIED |
| 107-09 的 7 条 backstops | 6 VERIFIED、1 条（历史 trace「逐像素一致」）结构层 VERIFIED / 像素级待人工 |
| 5 个需求 ID | ROUTE-01 / ROUTE-02 / RELY-03 / RELY-05 SATISFIED；RELY-02 机制 SATISFIED、真机送达待人工 |
| 两个 BLOCKER 修复 | BL-01 / BL-02 均**独立复核为真实修复**（非文档层面声称） |
| 反模式 | 26 个改动源文件零债务标记 |

**未判 passed 的唯一原因**：存在 6 项必须人工确认的验收项（视觉观感、真机 IM 送达、生产存量 dry-run、O-6 生产分位回填、pending 态可见性）。自动化侧全绿、无 gap。

---

## 一、Success Criteria 逐条判定（goal-backward）

### SC-1（ROUTE-01/02）：两组分区 + 组内同一套分数排序 + 跨组标注真的到达用户

**判定：✓ VERIFIED**

| 检查点 | 证据 |
|---|---|
| 分组标注为纯函数、不含分数 | `repo_router_ranking.annotate_groups` 返回 `dict[str, tuple[str, str]]`，结构上无法返回 float（`repo_router_ranking.py:124-146`） |
| 组内同一套排序 | `_rank_value` 是「`score_ranked` 缺失回退 `score`」的唯一实现（`repo_router_v2.py:396`），组内截断 / 并集全局排序 / 取两组首位三处全部调它；MN-02 修复后无分组上下文的早退分支也走 `sorted(..., key=_rank_sort_key)`（`:444`） |
| 后端契约 | 有项目上下文时 `block_order` 恒长度 2、无上下文时 `['global']`（`decide_block_order` 五分支覆盖两组皆空/单组为空） |
| 前端分区 | `groupedBlocks` 按 `blockOrder` 产出分区、区内才排序；全局 `b.score - a.score` 重排已删除（`RoutingDecisionPanel.vue:117-147`） |

**BL-02 独立复核（实时链路 vs 刷新链路一致性）——重点核查项：**

评审原判「工具输出无四个结果级字段 → 实时对话链路降级提示与分组呈现恒不生效」。逐项复核修复：

1. **出参契约已补齐**：`RepositoryRelevanceOutput` 新增 `router_version` / `degraded` / `degrade_reason` / `block_order` 四个带默认值字段（`schemas/repository_relevance.py:56-68`）。
2. **值真的被带出来**：`_analyze_relevance_core` 返回 `RepositoryRelevanceAnalysis` dataclass 携带四件套（`repository_relevance.py:98-113`），`analyze_repository_relevance` 逐字填进 Output（`:541-544`）。
3. **两条路径共用同一派生点**：`degraded` 三处（会话 detail / manual override / 工具实时输出）全部走 `chat.models.derive_routing_degraded`（`models.py:737-751`）；`chat/views.py:77-86` 的 `_derive_degraded` 只是它的别名。**不存在两套版本字面判定**，这是「对话当场与刷新后降级状态不一致」的机制级排除。
4. **实测一致性有真实路径守护**：`test_tool_output_block_order_matches_persisted_trace`（`test_repository_relevance_tool.py:1035`）走真实 `analyze_repository_relevance`，断言出参 `block_order` / `degrade_reason` / `router_version` **与落库 trace 同值**。
5. **假阳性守护已闭合**：前端 `routing.test.ts` 不再手写 payload，改为从**后端 schema 快照** `server/tests/agents/fixtures/repository_relevance_output_schema.json` 取键名构造（`routing.test.ts:20-49`），后端一旦删字段两端同时打红。
6. **前端判据已收紧**：`groupingEnabled` 只看 `block_order?.length === 2`（`RoutingDecisionPanel.vue:117`），删掉了「`some(c => c.group === 'in_project')`」这条在 in_project 组为空时恰好失效的兜底——正是 gk-008/gk-009 那类最需要分组的场景。

结论：BL-02 是真实修复，不是文档层面的声称。

---

### SC-2（ROUTE-02）：迟滞置顶 + 显式提示；分数上无任何 in-project boost

**判定：✓ VERIFIED**

| 检查点 | 证据 |
|---|---|
| 迟滞比较 | `decide_block_order` 用 `(global_top - in_project_top) >= delta`（`repo_router_ranking.py:175`），非 `> 0`；阈值上下各有单测 |
| **分数无暗补偿（机制级）** | `annotate_groups` 结构上返回不了 float；`repo_router_scoring` / `repo_router_config` 内零 `in_project` 引用；`score_ranked` 全模块**唯一写入点** `repo_router_v2.py:1758`，`score` / `breakdown` 不被触碰 |
| Σbreakdown == score 三处断言 | `test_repo_router_v2_meta.py:248`（1e-9）、`:462`（1e-9）、`RoutingDecisionPanel.vue:345`（1e-6）—— 全部在位且绿 |
| 行为级断言 | `test_score_and_breakdown_identical_with_and_without_grouping`（`test_repo_router_v2_meta.py:831`）：同一候选传 / 不传 `grouping_repository_ids` 两次调用，`score` 与 `breakdown` 逐字节相同 |
| golden 机制断言 | gk-008 组间分差 0.1771 > delta 0.15（余量 +0.0271），`test_cross_group_delta_upper_bound_is_binding` 锁死上界 |
| 前端提示 | `block_order[0] === 'global'` 时渲染 `role="status"` 置顶提示；in_project 组为空时改用陈述句（IN-04 修复） |

**注意一处已接受的偏差（MJ-02）**：107-03 的 assumption 写「`auto_selected` 只由全局最高分候选驱动」，实际 α 会参与该判定。评审后取「保留现状 + 订正注释 + 补护栏 + 加观测」。SC-2 的字面要求（**组别**只进呈现与 trust 字段）不受影响 —— 变的是 α 而非 group。影响方向单调安全（只抑制、不误开），已由 `test_alpha_never_turns_auto_selected_on`（α ∈ {0, 0.35, 0.9, 1.0} 参数化）与 `auto_selected_suppressed_by_alpha` 观测字段兜住。详见 frontmatter `deviations`。

---

### SC-3（RELY-03）：降级路径下用户可见明确提示 + 粗粒度原因（6 值闭集，不回显原始串）

**判定：✓ VERIFIED**

| 检查点 | 证据 |
|---|---|
| 6 值闭集封闭 | `DEGRADE_REASONS` frozenset 6 值（`repo_router_ranking.py:31-40`）；`classify_degrade_reason` 只吃 `skipped_reason` / **异常类型名** / **数值状态码**，结构上收不到异常实例或消息 |
| 分类正确性（MJ-01 修复） | 状态码优先、类名子串兜底：429/5xx（含 529）/408/425 可重试，4xx 客户端错误归 `upstream_error` 但不重试；408/504 归 `timeout`。`is_retryable_upstream_failure` 独立成纯函数 |
| DB 形状约束 | `degrade_reason` 列 `max_length=32`（迁移 0032），装不下异常原文 |
| 脱敏 | 上游异常文本经 `redact_secrets_in_text(str(exc))[:200]`（`repo_router_v2.py:1617` 等三处），截断式处理已被替换 |
| 写入侧真的在写 | `repository_relevance.py:370-371` / `:379-380` 显式填两列；`test_trace_write_persists_degrade_reason_and_block_order`（`:773`）经真实工具路径断言两列非默认值 |
| API 边界 | detail payload 补齐 `router_version` / `degraded` / `degrade_reason` / `block_order`（`chat/views.py:570-575`）；override 继承并回传（`:2761-2765` / `:2786-2789`），两处共用 `_safe_block_order` 脏值守卫（MN-08 修复） |
| 前端不回显原始值 | `DEGRADE_REASON_LABELS` 6 值 map + `UNKNOWN_DEGRADE_REASON_LABEL` 回退（`RoutingDecisionPanel.vue:231-247`）；`test('degrade_reason 为非受控值 → 回退「未知原因」，DOM 不含原始串')` 覆盖 |
| 无障碍 | 降级横幅 `role="alert"`（`:434`）、置顶提示 `role="status"`（`:457`）、跨组 Badge 带 `aria-label`（`:521`）；全文件零 `v-html` |
| `legacy_hybrid` 不算降级 | `derive_routing_degraded` 只认 `{v2_stage0_only, v1_fallback}` → 历史 trace 不会突然出现降级横幅 |

---

### SC-4（RELY-02）：澄清必达 + 超时出口，会话不再永久停在 `waiting_clarification`

**判定：⚠️ 后半句 ✓ VERIFIED；前半句「澄清一定送达用户且可作答」→ 待人工（真机 IM）**

**BL-01 独立复核（出口是否真到终态、有无 status=running 悬挂）——重点核查项：**

评审原判「出口只改状态不重驱引擎 → 会话由 `waiting_clarification` 停成 `research`/`running`，仍无产出」。逐项复核修复：

1. **续驱真的接上了**：`_aredrive`（`expire_pending_clarifications.py:442-466`）在**事务外**经 `build_orchestration_engine` + `adrive_convergence_session_to_pause_or_terminal` 续驱，与 `answer_resume` 同源，未新造第二个 engine 工厂。
2. **续驱 helper 语义已核**：`resume.py:23-69` 反复 `advance` 直到终态 `{DONE, FAILED}`、或 `waiting_clarification`/`waiting_event` 合法短路、或 `max_steps=20` 后经 `transition(fail)` 收口 —— **不存在停在 `running` 的出路**。
3. **守护测试断言的是「不得停在中间态」而非「调用了某函数」**：`test_resume_exit_redrives_engine_out_of_intermediate_state`（`test_expire_pending_clarifications.py:180`）显式断言 `current_stage != "research"`、`status != RUNNING`、且 `status ∈ {DONE, FAILED}`。修复前必红。
4. **不会被 policy 立刻重挂**：`clarify_adapter.default_needs_clarification` 读 `stage_state["clarification_exit"]` 短路且**优先级最高**（`clarify_adapter.py:80-82`）—— 这是 `adrive_` 的 `waiting_clarification` 短路不会把会话原地弹回去的前提。
5. **续驱失败不回退状态**：`test_redrive_failure_does_not_roll_back_exit` 断言 transition 已落地、事件仍只 emit 一次、并记 `clarification_timeout_exit_redrive_failed`。
6. **落点可在生产核对**：出口日志带 `final_status` / `final_stage`（`:437-438`），`test_exit_log_reports_post_redrive_landing` 断言其值。

**残余局限（如实记录）**：守护测试用 `_FakeEngine`（一步到 DONE）替换 engine，续驱 helper 本身是真实实现。真实 stage graph 下的落点分布须由生产 dry-run + 首次上线观察确认（已列入人工验收项）。

**出口机制其余 truths：**

| 检查点 | 证据 |
|---|---|
| 幂等复用 CAS | 出口只经 `ConvergenceSessionService.transition`，`ConcurrentTransitionError` 当 no-op；`test_second_scan_is_idempotent` 断言连跑两次只推进一次、`clarification.timed_out` 只 1 行 |
| 起算时间（Pitfall 7） | 取 pending 轮 `Clarification.created_at`（`auto_now_add`），**不用** `session.updated_at`（`:248-251`） |
| 三类不动 | `test_not_expired_round_untouched` / `test_answered_round_untouched` / `test_terminal_session_not_collected` |
| 两条立即出口 | `container_status == 'delivery_failed'`、以及「workflow 已 TIMEOUT 而会话仍在等」（`_workflow_timed_out`）；各有用例 |
| 事务纪律 | `_collect` 的 `atomic + select_for_update(skip_locked=True)` 块内只同步读、只收集；`asyncio.run` 在事务外 |
| 归因 | `structlog.contextvars.bound_contextvars(initiated_by_user_id, user_id, source="scheduler")` 包住整个出口（MN-05 修复），下游模块读得到 |
| dry-run / limit | `--dry-run` 零写库零 emit（`test_dry_run_has_zero_side_effects`）、`--limit` 生效 |
| job 注册 | `runapscheduler.py:414` job + `:807-809` IntervalTrigger 注册，间隔默认 60s（MN-06 从 600s 下调，矛盾态窗口压到 1/10） |
| 积压可被快照采集 | `backlog.pending_clarifications` 进 `_GAUGE_NAMES`（`metric_sampling.py:41`）且 `sample_gauges` 块六落 `GaugeSample`（`:175`），零值也落；异常文本经 `redact_secrets_in_text`（MN-04 修复） |
| 发卡 5 条失败路径 | `no_questions` / `no_space` / `no_project` / `no_chat_id` / `send_failed` 各经 `_amark_delivery_failed` 记 warning + emit `clarification.delivery_failed` + 标 `container_status`（`plan_research.py:483-525`）；**零静默 return** |
| 事件 taxonomy 双向守护 | 两个常量入 `ALL_EVENTS`（`event_taxonomy.py:98-101`）且两个 producer 登记进 `_EVENT_PRODUCERS` / `_EMIT_FILES`（`test_event_taxonomy_alignment.py:35-54`），未削弱 `assert producer is not None` |
| D-4 单一超时口径 | 工作流订阅 `timeout_at` 读同一 `CLARIFICATION_TIMEOUT_HOURS`（`plan_research.py:412`） |

---

### SC-5（RELY-05）：Stage 1 重试与延迟硬上界 + 有界重排；O-6 结论落文档

**判定：✓ VERIFIED**（O-6 生产数字按计划 deferred，合规）

| 检查点 | 证据 |
|---|---|
| 重试硬上界 1 次 | `for attempt in range(2)`（`repo_router_v2.py:1570`），写在自己的循环里；langchain `max_retries=0` 保持关闭 |
| 共享总预算 | `budget_deadline = started + total_budget_seconds` 在循环**外**取一次（`:1568`）；`remaining <= 0` 即抛 `TimeoutError("stage1_budget_exhausted")` 且不发第二次调用（`:1571-1584`） |
| per-attempt 超时 | `timeout=min(timeout_seconds, remaining)`（`:1593`）—— 不存在「首调吃满 per-call 后重试无余量」 |
| 退避受预算封顶 | `asyncio.sleep(min(backoff_base_seconds, max(0.0, budget_deadline - now)))`（`:1625-1630`） |
| 两次都失败 → 降级继续 | `degraded=True` + `router_version='v2_stage0_only'` + 6 值闭集 `degrade_reason` |
| 有界重排后置条件 | **verifier 独立穷举复算**：n≤6、k=0..3、全部子集 × 全排列共 **9460 组，后置条件违规 0、集合不等 0**。base rank 确实取「被 LLM 返回子集内的相对位次」（`repo_router_ranking.py:212-213`），兜底回退到 `base_order` 而非全量 `stage0_order`（`:237`） |
| K 预算在主路径生效 | `candidates = [by_rid[rid] for rid in clamped_order ...]`（`:1749`）把裁剪产物写回返回顺序 |
| 丢弃式提升可观测 | `stage1_meta` 带 `llm_returned_count` / `stage0_window_count` / `rank_budget_violations` / `rank_budget_k` / `alpha` / `clamped_order` |
| 凸组合只写旁路字段 | `cand.score_ranked = ranked.get(...)`（`:1758`）唯一写入点；`blend_ranked_scores` 先过滤无效 id 再算 N（IN-03 修复） |
| confidence 不回退 RELY-04 | `sorted_scores` 恒取自 `stage0_candidates`（`:1682`），`_deterministic_confidence` 吃 Stage 0 位次（`:1702`）；LLM 只降不升 |
| ModelUsageRecord 埋点 | 失败路径 `:1598-1609`（含 `failure_type` 短标签 + `upstream_status_code`）、成功路径 `:1632-1637`（含 usage metadata）；`call_source=AUX_REPO_ROUTER` |
| 配置 fail-safe | `_stage1_seconds` / `_stage1_int`（MN-07 修复）覆盖 timeout / max_candidates / hits_per_repo / cache_ttl，非数值配置不再直接抛 |
| golden 门禁不变 | 32 passed，`phase106-v2` baseline 零漂移 |
| O-6 落文档 | `107-MEASUREMENTS.md` 存在（195 行）：生产分位全部标 `deferred` 并给复测命令、α 未校准局限（D-7）、delta=0.15 依据与 0.1771 上界、A5 per-call 不下调理由、「输入哈希缓存 + 快照回放为主要收益来源」的设计取舍 —— **无任何编造数字** |

---

## 二、必需产物核对（存在 / 实质 / 接线 / 数据流四级）

| 产物 | 行数 | 存在 | 实质 | 接线 | 数据流 | 状态 |
|---|---|---|---|---|---|---|
| `codegraph/services/repo_router_ranking.py` | 374 | ✓ | ✓ 7 个纯函数、零 Django import | ✓ 被 router 导入 | ✓ | ✓ VERIFIED |
| `codegraph/services/repo_router_v2.py` | 1912 | ✓ | ✓ | ✓ | ✓ | ✓ VERIFIED |
| `codegraph/services/repo_group_scope.py` | 174 | ✓ 宽口径并集 | ✓ 半边失败降级不抛 | ✓ 两入口调用 | ✓ | ✓ VERIFIED |
| `codegraph/management/commands/measure_stage1_latency.py` | 294 | ✓ | ✓ Postgres `percentile_cont` + Python 回退 | ✓ 查 `SystemLogEntry` | n/a（运维工具） | ✓ VERIFIED |
| `delivery/management/commands/expire_pending_clarifications.py` | 511 | ✓ | ✓ | ✓ job 已注册 | ✓ 续驱真实 | ✓ VERIFIED |
| `delivery/services/event_taxonomy.py` | 135 | ✓ | ✓ 两常量入 ALL_EVENTS | ✓ producer 登记 | ✓ | ✓ VERIFIED |
| `workflows/nodes/ai/plan_research.py` | 674 | ✓ | ✓ 5 条失败路径 | ✓ | ✓ | ✓ VERIFIED |
| `services/process_runtime/clarify_adapter.py` | 269 | ✓ | ✓ 短路优先级最高 | ✓ 消费 `clarification_exit` | ✓ | ✓ VERIFIED |
| `services/process_runtime/repo_router_adapter.py` | 113 | ✓ | ✓ | ✓ 传 grouping | ✓ | ✓ VERIFIED |
| `system/metric_sampling.py` | 211 | ✓ | ✓ 块六 | ✓ 进 `_GAUGE_NAMES` | ✓ 零值也落 | ✓ VERIFIED |
| `agents/tools/repository_relevance.py` | 563 | ✓ | ✓ | ✓ | ✓ 四键真的出参 | ✓ VERIFIED |
| `agents/tools/schemas/repository_relevance.py` | 68 | ✓ | ✓ 四个结果级字段 | ✓ schema 快照守护 | ✓ | ✓ VERIFIED |
| `chat/migrations/0032_...py` | 23 | ✓ | ✓ 两 AddField 均带默认值 | ✓ additive / 无 RunPython / 可逆 | ✓ | ✓ VERIFIED |
| `chat/models.py`（`derive_routing_degraded`） | 850 | ✓ | ✓ | ✓ 三处共用唯一派生点 | ✓ | ✓ VERIFIED |
| `chat/views.py`（detail + override） | 3310 | ✓ | ✓ 9 键 | ✓ `_safe_block_order` 共用 | ✓ | ✓ VERIFIED |
| `web/src/types/routing.ts` | 93 | ✓ | ✓ 8 个 optional 新字段 | ✓ | ✓ | ✓ VERIFIED |
| `web/src/stores/routing.ts` | 108 | ✓ | ✓ override 兜底继承 | ✓ | ✓ | ✓ VERIFIED |
| `web/src/components/chat/RoutingDecisionPanel.vue` | 612 | ✓（≥380） | ✓ | ✓ 按 block_order 分区 | ✓ | ✓ VERIFIED |
| `107-MEASUREMENTS.md` | 195 | ✓ | ✓ 含 α / deferred / 上界 | n/a | n/a | ✓ VERIFIED |

**测试产物**：4 个 Wave 0 新建文件全部存在且非空（`test_repo_router_ranking.py` 486 行、`test_measure_stage1_latency.py` 153 行、`test_expire_pending_clarifications.py` 693 行、`test_repo_group_scope.py` 232 行），另加 BL-02 契约锚 `fixtures/repository_relevance_output_schema.json`（146 行）。

---

## 三、关键接线核对

| From | To | Via | 状态 |
|---|---|---|---|
| `settings.py` | `repo_router_ranking.py` | `REPO_ROUTER_GROUP_DELTA` 等 9 键外置 | ✓ WIRED（settings + `.env.example` 均齐 9 键） |
| `test_repo_router_golden.py` | `repo_router_ranking.py` | `decide_block_order` 喂 gk-008/gk-009 | ✓ WIRED |
| `repo_router_v2.py` | `repo_router_ranking.py` | 6 个纯函数参数注入 | ✓ WIRED |
| `repo_router_v2.py` | `common/logging.py` | `redact_secrets_in_text` | ✓ WIRED |
| `repo_router_v2.py` | `interactions/ledger.py` | `arecord_llm_usage(run=None, call_source=AUX_REPO_ROUTER)` | ✓ WIRED（成功 + 失败双路径） |
| `plan_research.py` | `convergence_session_service.py` | `EVENT_CLARIFICATION_DELIVERY_FAILED` | ✓ WIRED |
| `plan_research.py` | `settings.py` | `CLARIFICATION_TIMEOUT_HOURS`（D-4） | ✓ WIRED |
| `expire_pending_clarifications.py` | `convergence_session_service.py` | `transition` 唯一入口 + `ConcurrentTransitionError` | ✓ WIRED |
| `expire_pending_clarifications.py` | `services/process_runtime` | `adrive_convergence_session_to_pause_or_terminal`（BL-01） | ✓ WIRED |
| `runapscheduler.py` | `expire_pending_clarifications` | `call_command` + IntervalTrigger | ✓ WIRED |
| `clarify_adapter.py` | 出口标记 | `stage_state.clarification_exit` 短路 | ✓ WIRED |
| `metric_sampling.py` | `delivery/models/clarification.py` | `backlog.pending_clarifications` gauge | ✓ WIRED |
| `repo_router_adapter.py` | `repo_group_scope.py` | `aresolve_grouping_repo_ids` | ✓ WIRED |
| `repository_relevance.py` | `repo_router_v2.py` | `grouping_repository_ids` + `repository_ids=None` | ✓ WIRED |
| `chat/views.py` | `chat/models.py` | `derive_routing_degraded` + `_safe_block_order` | ✓ WIRED |
| `RoutingDecisionPanel.vue` | `stores/routing.ts` | 按 `block_order` 分区（全局重排已删） | ✓ WIRED |
| `stores/chat.ts` | `stores/routing.ts` | 三处 `upsertTrace` 透传新字段 | ✓ WIRED |

**D-1 影响面核对（唯一有回归风险的改动）**：全仓 `RepoRouterV2.route(...)` 调用点共 8 处，只有 `repo_router_adapter.py:48` 与 `repository_relevance.py:289` 传 `grouping_repository_ids`；其余 6 处（`skill_steps.py:76` / `route_views.py:39` / `mcp_tools/views.py:434` / `knowledge/sources/artifact.py:146` / `repo_association_service.py:165` / `space_tools.py:56`）调用行逐字未变。✓

---

## 四、行为抽查与实跑结果

| 项 | 命令 | 结果 | 状态 |
|---|---|---|---|
| 后端定向全量 | `uv run pytest tests/codegraph tests/delivery tests/services tests/agents tests/workflows tests/chat tests/test_metric_sampling.py -q` | **2897 passed, 21 skipped, 3 deselected**（161.83s） | ✓ PASS |
| 前端 | `pnpm vitest run src/components/chat src/stores` | **328 passed / 40 files** | ✓ PASS |
| 前端类型 | `pnpm exec vue-tsc --noEmit` | 退出码 0 | ✓ PASS |
| golden 门禁 + 快照回放 | `uv run pytest tests/codegraph/test_repo_router_golden.py tests/codegraph/test_repo_router_replay.py -q` | **32 passed**（0.14s），`phase106-v2` baseline 零漂移 | ✓ PASS |
| 迁移合规 | `uv run python manage.py makemigrations --check --dry-run` | `No changes detected`，退出码 0 | ✓ PASS |
| **K 预算穷举（verifier 独立复算）** | 直接调 `clamp_llm_permutation`，n≤6 / k=0..3 / 全部子集 × 全排列 | **9460 组：后置条件违规 0、集合不等 0** | ✓ PASS |
| `Σbreakdown == score` 三处断言 | grep + 实跑 | `test_..._meta.py:248`、`:462`（1e-9）、`RoutingDecisionPanel.vue:345`（1e-6）全部在位且绿 | ✓ PASS |

---

## 五、需求覆盖

| 需求 | 来源 PLAN | 描述 | 状态 | 证据 |
|---|---|---|---|---|
| ROUTE-01 | 01, 03, 07, 08, 09 | 路由结果分两组呈现，各自排序 | ✓ SATISFIED | SC-1 全链路（纯函数 → router → trace → API → 前端分区），BL-02 已闭合实时链路 |
| ROUTE-02 | 01, 03, 07, 08, 09 | 跨组候选带明确标注 | ✓ SATISFIED | 跨组两层标注（组级常驻句 + 候选级 Badge + aria-label）、迟滞置顶提示、golden 上界锁定 |
| RELY-02 | 04, 06 | 澄清不会无人应答地永久停在澄清阶段 | ⚠️ 机制 SATISFIED / 真机送达待人工 | 超时出口 + 真实续驱（BL-01 已闭合）、5 条送达失败路径留痕、两条立即出口、积压 gauge；「一定送达且可作答」需真机 IM 确认 |
| RELY-03 | 03, 08, 09 | 降级时用户能看见明确提示 | ✓ SATISFIED | 6 值闭集 + 后端唯一派生 + detail/override/实时三路一致 + 前端横幅与徽标灰化 + 不回显原始串 |
| RELY-05 | 01, 02, 05 | 单次调用有重试与延迟上界 | ✓ SATISFIED | 1 次重试 + 共享硬预算 + per-attempt `min` + 有界重排（独立穷举 0 违规）+ ModelUsageRecord；O-6 生产数字按计划 deferred 并已文档化 |

**孤儿需求检查**：`REQUIREMENTS.md` 映射到 Phase 107 的恰为 ROUTE-01 / ROUTE-02 / RELY-02 / RELY-03 / RELY-05 五条，全部在 PLAN frontmatter 中被声明并有实现证据。**无孤儿、无遗漏**。

---

## 六、107-CONTEXT 七项裁决（D-1~D-7）遵守情况

| 裁决 | 遵守 | 证据 |
|---|---|---|
| D-1 放开硬过滤，项目关联仓改为分组依据 | ✓ | 两入口 `repository_ids=None` + `grouping_repository_ids=<项目关联仓>`；透出面已如实写进注释（MN-09） |
| D-2 「本项目关联仓」取宽口径并集 | ✓ | `repo_group_scope.py`：`Space.repositories` ∪ `RepoAssociation(status=verified)`，verified 半边失败降级不抛 |
| D-3 凸组合只写旁路字段 | ✓ | `score_ranked` 唯一写入点；三处 `Σbreakdown == score` 断言全绿 |
| D-4 工作流订阅超时与澄清超时同一配置 | ✓ | 均读 `CLARIFICATION_TIMEOUT_HOURS`；扫描间隔 600s→60s（MN-06），矛盾态窗口 ≤1 分钟（非零，如实记录） |
| D-5 chat 单题澄清只观测不出口 | ✓ | `_observe_chat_clarifications` 只 `count()` 不改行，日志 `category="sampling"`；`test_chat_unanswered_traces_are_observed_not_exited` 守护 |
| D-6 「未澄清假设」只写 `stage_state` | ✓ | 只写 `stage_state.clarification_exit`，未触碰任何 DEPTH 冻结渲染文件 |
| D-7 α=0.35 取锁定值、局限入文档 | ✓ | `107-MEASUREMENTS.md` 明确记「α 未经离线校准（离线 harness 结构上不跑 Stage 1）」 |

---

## 七、107-09 backstop 逐条判定

| # | backstop | 判定 | 依据 |
|---|---|---|---|
| 1 | 历史 trace 完全兼容（平铺、无标注、按 score 降序、不抛不 warn、**逐像素一致**） | ⚠️ 结构 VERIFIED / 像素级待人工 | `it('历史 trace（无 block_order / group / score_ranked）→ 单个平铺 ul、零新增标注')`、`it('block_order 缺失 → 平铺')` 覆盖结构；「逐像素」无法程序化断言 |
| 2 | 部分字段缺失兜底（group 缺→global、score_ranked null→回退 score、degraded 缺→false、非受控 reason→未知原因） | ✓ VERIFIED | 四条各有用例；MN-01 修复后 `c.group \|\| 'global'` 对空串也生效，并有「空串候选不得从两个分区同时消失」用例 |
| 3 | 无项目上下文入口 → 平铺、无跨组标注 | ✓ VERIFIED | `it('block_order 长度 1（无项目上下文）→ 平铺、无组标题与跨组标注')` |
| 4 | 展开态不持久化（本地 ref，trace 更新后重算） | ✓ VERIFIED | `it('用户手动展开后本地态优先；trace 变化后重算默认态')` |
| 5 | 无 `v-html` | ✓ VERIFIED | `RoutingDecisionPanel.vue` 全文件 `v-html` 出现 0 次 |
| 6 | 可访问性（`role="alert"` + `aria-live`、`role="status"`、跨组 Badge `aria-label`、原生 button） | ✓ VERIFIED | 模板 `:434` / `:457` / `:521`；`it('degraded=true → amber 告警条（role=alert / aria-live=polite）含主句')`、`it('block_order[0]===global → 出现 role=status 置顶提示')` |
| 7 | 测试扩充（既有 12 passed 零回归 + 新增 10 类用例；routing.test.ts 新增 override 用例） | ✓ VERIFIED | 既有 12 条在位；新增分组分区 11 条 / 跨组与置顶 4 条 / 降级 10 条；`routing.test.ts` 新增 override 继承 5 条 + chat store 透传 3 条 |

**abstain 说明（honest-verifier 纪律）**：backstop 1 的「逐像素一致」与整体视觉观感不做程序化断言，据此**不静默判 pass**，已升为人工验收项 1。

---

## 八、反模式扫描

| 类别 | 结果 |
|---|---|
| 债务标记（TBD / FIXME / XXX） | **0** —— 26 个改动源文件全扫描 |
| 清理标记（TODO / HACK / PLACEHOLDER） | **0** |
| 占位文案（coming soon / 待实现 / 占位） | **0** |
| 空实现兜底（`return null` / `return []` 无数据源） | 无 —— `annotate_groups` 空输入返回空 dict、`clamp_llm_permutation` 空子集返回 `([], 0)` 均为受控边界语义，非 stub |
| 未脱敏异常文本 | 无 —— MN-04 后 `metric_sampling` 与 `expire_pending_clarifications` 的 `str(exc)` 均过 `redact_secrets_in_text` |
| 计划外改动 | 3 个文件（`subagent/api/callbacks.py` +6/-3、`delivery/services/clarification_service.py` +12/-4、`delivery/models/clarification.py` +8/-2），均为 BL-02 返回类型变更与 `container_status` 语义的必要消费方适配，无范围蔓延 |

---

## 九、需要人工验收的项（status: human_needed 的成因）

自动化侧无 gap。以下 6 项按 `107-VALIDATION.md` 的 Manual-Only Verifications 与 honest-verifier 的 abstain 纪律列出：

### 1. 分组 / 跨组 / 降级三块 UI 观感（ROUTE-01/02, RELY-03）
**操作：** 对话路由面板逐项核对两组分区、跨组 Badge 与常驻说明句、迟滞置顶提示、降级横幅与徽标灰化、折叠态降级徽标。
**预期：** 与 `107-UI-SPEC.md` 一致；无新色板 / 新字号 / 新组件（已核实零新依赖、未新建 `ui/alert`）。
**为何人工：** 视觉观感与「历史 trace 逐像素一致」无法程序化断言（结构层已由 328 条前端用例覆盖）。

### 2. override 后横幅与分区不消失（RELY-03）
**操作：** 面板上勾选 / 取消一个候选。
**预期：** 降级横幅与两组分区仍在。
**为何人工：** 需真实交互；store 层已有 5 条自动化用例，此项确认端到端（Pitfall 3 的 UAT 必查项）。

### 3. 澄清必达真机链路（RELY-02，**SC-4 前半句**）
**操作：** 真实会话触发澄清确认飞书送达且可作答；再断开配置制造 `no_chat_id`。
**预期：** 卡片送达且可作答；失败路径留痕 + `clarification.delivery_failed` 事件 + 立即出口。
**为何人工：** 依赖真实 IM 环境。这是 SC-4 唯一未被自动化覆盖的半句。

### 4. 澄清超时出口首次上线影响面（RELY-02）
**操作：** 生产先跑 `python manage.py expire_pending_clarifications --dry-run`，确认影响面后再启用 job。
**预期：** dry-run 零写库、列出存量卡死会话（CONTEXT 记录会话 `ccd817d9` 有 2 条）。
**为何人工：** 需生产存量数据；A9 提示存量会话可能已被人工绕道处理，批量推进可能产生重复产出。**同时可确认真实 stage graph 下续驱的落点分布**（补上 BL-01 守护测试使用 `_FakeEngine` 的那一段真实性）。

### 5. O-6 生产延迟分位实测（RELY-05）
**操作：** 生产执行 `python manage.py measure_stage1_latency --days 7 --json`（Postgres 走 `percentile_cont`），回填 `107-MEASUREMENTS.md` 的 p50/p90/p99 与采样率。
**预期：** 拿到真实分位；据此再议 per-call 90s 是否下调（A5）。
**为何人工：** 需生产数据。本 phase 已按计划 deferred 且文档如实标注、命令与单测就位，**合规**。

### 6. 会话内 pending 状态对用户可见（RELY-02 子句）
**操作：** 触发一轮澄清后在会话内确认 pending 态可见（`ChatStatusBar` / `ClarificationCard` / `HumanTaskInbox` 三处任一）。
**预期：** pending 态对用户可见。
**为何人工：** 本 phase 不新增前端面（VALIDATION 已核查既有实现满足）；此项只确认既有呈现仍有效，缺失则作为独立缺陷进 backlog，不并入本 phase 范围。

---

## 十、结论

**Phase 107 的 5 条 Success Criteria 在代码层全部达成，两个 BLOCKER 均经独立复核确认为真实修复而非文档层面的声称：**

- **BL-01**：出口不再只换标签 —— 续驱 helper 真实接上，其循环结构上不存在停在 `running` 的出路，守护测试断言的是「不得停在中间态且落终态」而非「调用了某函数」。
- **BL-02**：四个结果级字段真的出参了，且实时链路与刷新链路共用**同一个** `derive_routing_degraded` 派生点，并有走真实工具路径的同值断言；前端假阳性守护已改为共用后端 schema 快照。

自动化证据全绿：后端 2897 passed、前端 328 passed、golden 32 passed 零漂移、`makemigrations --check` 干净、`Σbreakdown == score` 三处断言在位、K 预算穷举 9460 组零违规（verifier 独立复算）、26 个改动源文件零债务标记。

**判 `human_needed` 而非 `passed`**：SC-4 前半句「澄清一定送达用户且可作答」依赖真实 IM 环境，backstop 1 的「逐像素一致」与整体视觉观感不做程序化断言 —— 按 honest-verifier 纪律 abstain 升为人工验收，不静默 pass。另有 4 项生产/视觉验收项一并列出。**无任何 gap 需要补 plan。**

---

_Verified: 2026-07-30T02:05:00Z_
_Verifier: gsd-verifier（goal-backward，不采信 SUMMARY 自述）_
