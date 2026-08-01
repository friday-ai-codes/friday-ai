---
phase: 107
slug: layered-presentation
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-29
updated: 2026-07-30
---

# Phase 107 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x（server/，uv 管理，含 pytest-asyncio / pytest-django / pytest-socket / respx / factory-boy）+ vitest 4（web/，happy-dom） |
| **Config file** | server/pyproject.toml；前端由 web/vite.config.ts 配置 |
| **Quick run command** | `cd server && uv run pytest tests/codegraph tests/delivery -q` |
| **Full suite command** | `cd server && uv run pytest -q`；前端 `cd web && pnpm vitest run` |
| **Estimated runtime** | 快跑 ~40s；全量 ~11min；golden 门禁 0.18s |
| **既有基线** | `cd server && uv run pytest tests/codegraph tests/delivery tests/services/test_repo_router_adapter.py -q` → **839 passed / 20 skipped**（106-08 收官值）；`RoutingDecisionPanel.test.ts` → **12 passed** |

---

## Sampling Rate

- **After every task commit:** 受改模块定向跑（codegraph / delivery / services / workflows / chat / agents / system；前端 task 用 `cd web && pnpm vitest run <spec>`）
- **After every plan wave:** 受影响模块全量 + golden 门禁（分数口径不得漂移）+ 前端 `pnpm vitest run src/components/chat src/stores`
- **Before `/gsd-verify-work`:** Full suite must be green（后端 `uv run pytest -q` + 前端 `pnpm vitest run` + `ruff check` / `ruff format --check`（改动文件）+ `pnpm exec vue-tsc --noEmit`）
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| T1 参数外置（9 键） | 107-01 | 1 | ROUTE-01, ROUTE-02, RELY-05 | T-107-05 | 参数非法值 clamp / fail-safe；不进 weight_config.constants | unit | `cd server && uv run pytest tests/codegraph/test_repo_router_golden.py tests/codegraph/test_repo_router_replay.py -q` | ✅ 既有 | ⬜ pending |
| T2 ranking 六纯函数 | 107-01 | 1 | ROUTE-01, ROUTE-02, RELY-05 | T-107-02, T-107-05 | `classify_degrade_reason` 签名结构上无法接收异常消息 | unit | `cd server && uv run pytest tests/codegraph/test_repo_router_ranking.py -x -q` | ❌ W0（新建） | ⬜ pending |
| T3 golden cross_group 机制断言 | 107-01 | 1 | ROUTE-01, ROUTE-02 | — | 机制断言不锁绝对值（抗权重微调假红） | unit（离线零网络） | `cd server && uv run pytest tests/codegraph/test_repo_router_golden.py -x -q -k cross_group` | ✅ 既有文件补用例 | ⬜ pending |
| T1 measure_stage1_latency 命令 | 107-02 | 1 | RELY-05 | T-107-02, T-107-09 | 输出只含聚合量；SQL 参数化 + 表名取 `_meta.db_table` | unit | `cd server && uv run pytest tests/codegraph/test_measure_stage1_latency.py -x -q` | ❌ W0（新建） | ⬜ pending |
| T2 107-MEASUREMENTS.md | 107-02 | 1 | RELY-05 | — | 文档不含编造数字；deferred 标注 | doc check | `test -f .planning/phases/107-layered-presentation/107-MEASUREMENTS.md && rg -c 'deferred' .planning/phases/107-layered-presentation/107-MEASUREMENTS.md` | ❌ W0（新建） | ⬜ pending |
| T1 候选/结果新字段 + to_dict | 107-03 | 2 | ROUTE-01, ROUTE-02, RELY-03 | T-107-05 | `_ranking_conf` clamp 不抛 | unit | `cd server && uv run pytest tests/codegraph/test_repo_router_v2_meta.py -x -q` | ✅ 既有 | ⬜ pending |
| T2 grouping 参数 + block_order 接线 | 107-03 | 2 | ROUTE-01, ROUTE-02 | T-107-01(accept), T-107-06 | 候选范围本 plan 零变化；`cross_group_note` 只留痕 | unit + integration | `cd server && uv run pytest tests/codegraph/test_repo_router_v2_meta.py -x -q -k "group or block_order or no_project_context"` | ✅ 既有 | ⬜ pending |
| T3 降级原因分类 + 脱敏 | 107-03 | 2 | RELY-03 | T-107-02 | 异常文本经 `redact_secrets_in_text`；6 值闭集 | unit（安全） | `cd server && uv run pytest tests/codegraph/test_repo_router_v2_degraded.py -x -q -k "degrade_reason or redact"` | ✅ 既有 | ⬜ pending |
| T1 两个事件常量入 taxonomy + **producer 注册表登记** | 107-04 | 2 | RELY-02 | — | 常量 + ALL_EVENTS + `_EVENT_PRODUCERS`/`_EMIT_FILES` 登记 + 带 plan 标注的待落地豁免 四者同提交；A4 命名空间确认已自动化 | unit | `cd server && uv run pytest tests/services/test_event_taxonomy_alignment.py -x -q` | ✅ 既有 | ⬜ pending |
| T2 发卡 5 条失败路径留痕 | 107-04 | 2 | RELY-02 | T-107-02, T-107-04 | payload 只含 5 值枚举，无异常原文；不误写 `answered_at` | unit | `cd server && uv run pytest tests/workflows/test_plan_research_node.py -x -q -k delivery` | ✅ 既有 | ⬜ pending |
| T3 D-4 订阅超时统一口径 | 107-04 | 2 | RELY-02 | — | 单一配置键驱动两侧 | unit | `cd server && uv run pytest tests/workflows/test_plan_research_node.py -x -q -k "timeout or subscription"` | ✅ 既有 | ⬜ pending |
| T1 Stage 1 重试 + 共享总预算 | 107-05 | 3 | RELY-05 | T-107-07 | 重试硬上界 1 + 共享 deadline + 退避不超剩余预算 | unit（替身计数） | `cd server && uv run pytest tests/codegraph/test_repo_router_v2_degraded.py -x -q -k "retry or budget"` | ✅ 既有 | ⬜ pending |
| T2 K 裁剪 + 凸组合 score_ranked | 107-05 | 3 | RELY-05 | T-107-05, T-107-10 | LLM 编造 id 丢弃 + 位移预算裁剪（base 为子集内相对位次，含子集常态回归；断言落 `clamped_order` 而非最终列表）+ violations 留痕 + `llm_returned_count`/`stage0_window_count` 使「丢弃式提升」可观测 | unit + integration | `cd server && uv run pytest tests/codegraph/test_repo_router_v2_degraded.py tests/codegraph/test_repo_router_v2_meta.py -x -q` | ✅ 既有 | ⬜ pending |
| T3 Stage 1 ModelUsageRecord 埋点 | 107-05 | 3 | RELY-05 | T-107-02 | `failure_type` 短标签而非异常消息；不伪造 TTFT | unit | `cd server && uv run pytest tests/codegraph/test_repo_router_v2_degraded.py -x -q -k usage` | ✅ 既有 | ⬜ pending |
| T1 expire 命令核心（出口 + 幂等） | 107-06 | 3 | RELY-02 | T-107-04, T-107-11 | 出口必留痕；两段式事务（事务外重驱） | integration | `cd server && uv run pytest tests/delivery/test_expire_pending_clarifications.py -x -q -k "exit or idempotent"` | ❌ W0（新建） | ⬜ pending |
| T2 边界 + 两条立即出口 + 运维开关 | 107-06 | 3 | RELY-02 | T-107-03, T-107-08 | `--dry-run` / `--limit` 降低误操作与长事务面 | integration | `cd server && uv run pytest tests/delivery/test_expire_pending_clarifications.py -x -q -k "not_expired or answered or terminal or dry_run or limit or started_at"` | ❌ W0（新建） | ⬜ pending |
| T3 job 注册 + policy 短路 + 积压 gauge + 豁免删除 | 107-06 | 3 | RELY-02 | T-107-03 | job 无 HTTP 触发面；归因 system + 会话 initiated_by；gauge `labels` 不落用户/会话标识 | unit | `cd server && uv run pytest tests/services/test_engine_clarify.py tests/services/test_event_taxonomy_alignment.py tests/test_metric_sampling.py -x -q` | ✅ 既有 | ⬜ pending |
| T1 repo_group_scope 宽口径并集 | 107-07 | 3 | ROUTE-01, ROUTE-02 | T-107-12 | 并集半边失败降级不抛；`None` 与空集语义分离 | unit | `cd server && uv run pytest tests/codegraph/test_repo_group_scope.py -x -q` | ❌ W0（新建） | ⬜ pending |
| T2 D-1 两个入口改传分组依据 | 107-07 | 3 | ROUTE-01, ROUTE-02 | T-107-01(accept), V4 | 不新增可见性面（前提显式记录）；权限校验不改 | integration（回归） | `cd server && uv run pytest tests/services/test_repo_router_adapter.py tests/agents/test_repository_relevance_tool.py tests/initiatives/test_repo_association_service.py -x -q` | ✅ 既有 | ⬜ pending |
| T3 chat 链候选字段透传 | 107-07 | 3 | ROUTE-01, ROUTE-02 | T-107-06 | 不引入 `cross_group_note`（少一条泄漏面） | unit | `cd server && uv run pytest tests/agents/test_repository_relevance_tool.py -x -q` | ✅ 既有 | ⬜ pending |
| T1 trace 两列 + 迁移 + **写入侧接线** | 107-08 | 4 | RELY-03 | T-107-02 | `degrade_reason` 列长 32 结构上装不下异常原文；写入侧经真实工具路径断言两列非默认值 | unit + migration | `cd server && uv run python manage.py makemigrations --check --dry-run && uv run pytest tests/chat/test_repository_routing_trace_model.py tests/agents/test_repository_relevance_tool.py -x -q` | ✅ 既有 | ⬜ pending |
| T2 detail payload 补 4 键 | 107-08 | 4 | RELY-03, ROUTE-01, ROUTE-02 | T-107-02 | payload 无自由文本键；`degraded` 后端唯一派生 | integration（真实 endpoint） | `cd server && uv run pytest tests/chat -x -q -k "routing or detail"` | ✅ 既有 | ⬜ pending |
| T3 override 继承并回传 | 107-08 | 4 | RELY-03 | V4, T-107-13 | 跨用户/跨项目两条拒绝路径零回归 | integration | `cd server && uv run pytest tests/chat/test_routing_trace_manual_override_view.py -x -q` | ✅ 既有 | ⬜ pending |
| T1 类型契约 + store override 兜底 | 107-09 | 5 | ROUTE-01, ROUTE-02, RELY-03 | T-107-13 | override 不丢降级/分组事实 | store unit + typecheck | `cd web && pnpm vitest run src/stores/__tests__/routing.test.ts && pnpm exec vue-tsc --noEmit` | ✅ 既有 | ⬜ pending |
| T2 分区渲染 + 跨组 + 置顶（删全局重排） | 107-09 | 5 | ROUTE-01, ROUTE-02 | T-107-06, T-107-14 | 文案取前端常量；无 `v-html`；前端不覆盖后端顺序 | component unit | `cd web && pnpm vitest run src/components/chat/__tests__/RoutingDecisionPanel.test.ts` | ✅ 既有（12 passed） | ⬜ pending |
| T3 降级横幅 + 徽标灰化 + 文案闭集 | 107-09 | 5 | RELY-03 | T-107-02 | 非受控 `degrade_reason` 回退「未知原因」不回显原始值 | component unit（安全） | `cd web && pnpm vitest run src/components/chat/__tests__/RoutingDecisionPanel.test.ts` | ✅ 既有 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

新建测试文件（执行 plan 时随 task 一并创建，无框架安装需求——pytest / vitest / respx / factory-boy / pytest-socket 全部就位）：

- [ ] `server/tests/codegraph/test_repo_router_ranking.py` — ROUTE-01（分组/block_order/迟滞/幂等/长度 2 契约/两组皆空仍长度 2）+ RELY-05（K 裁剪后置条件「子集 × 排列」穷举——base rank 为「被 LLM 返回子集」内的 Stage 0 相对位次，含「LLM 只返回窗口末几位」的常态用例；等长全排列只是 `m==6` 那一层 / 凸组合 / N==1 / α=0）
- [ ] `server/tests/codegraph/test_measure_stage1_latency.py` — O-6 命令（分位/时间窗/零样本/输出无敏感串）
- [ ] `server/tests/delivery/test_expire_pending_clarifications.py` — RELY-02（出口 / 幂等 CAS no-op / 起算时间 Pitfall 7 / 三类不动 / 两条立即出口 / dry-run / limit）
- [ ] `server/tests/codegraph/test_repo_group_scope.py` — D-2 宽口径并集（并集去重 / 无 Project 退化 / `None` 与空集语义分离 / 半边失败降级）

已存在、仅补用例的文件：`test_repo_router_golden.py`、`test_repo_router_v2_meta.py`、`test_repo_router_v2_degraded.py`、`test_plan_research_node.py`、`test_event_taxonomy_alignment.py`、`test_engine_clarify.py`、`test_repo_router_adapter.py`、`test_repository_relevance_tool.py`、`test_repository_routing_trace_model.py`、`test_routing_trace_manual_override_view.py`、`test_metric_sampling.py`（107-06 T3 的 `backlog.pending_clarifications` 三条用例）、`RoutingDecisionPanel.test.ts`、`routing.test.ts`。

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 分组/跨组/降级三块 UI 观感 | ROUTE-01/02, RELY-03 | 视觉判断 | 对话路由面板：确认两组分区、跨组 badge 与常驻说明句、置顶提示、降级横幅与徽标灰化、折叠态降级徽标，与 107-UI-SPEC 一致 |
| override 后横幅与分区不消失 | RELY-03 | 需真实交互 | 面板上勾选/取消一个候选，确认降级横幅与两组分区仍在（Pitfall 3 的 UAT 必查项） |
| 澄清必达真机链路（IM/飞书送达） | RELY-02 | 需真实 IM 环境 | 真实会话触发澄清，确认送达 + 可作答；断开配置制造 `no_chat_id` 确认留痕与事件 |
| 澄清超时出口首次上线影响面 | RELY-02 | 需生产存量数据 | 生产先跑 `python manage.py expire_pending_clarifications --dry-run`（A9：存量卡死会话可能已被人工绕道处理，批量推进可能产生重复产出），确认影响面后再启用 job |
| O-6 生产延迟分位实测 | RELY-05 | 需生产数据 | 生产执行 `python manage.py measure_stage1_latency --days 7 --json`（Postgres 走 `percentile_cont`），回填 107-MEASUREMENTS.md 的 p50/p90/p99 与采样率 |
| 会话内 pending 状态对用户可见（RELY-02 子句） | RELY-02 | 视觉确认既有实现 | 触发一轮澄清后在会话内确认 pending 态可见（`ChatStatusBar` 状态提示 / `ClarificationCard` / `HumanTaskInbox` 待办入口三处任一即可）。**本 phase 不新增前端面**——此项只确认既有实现仍有效；缺失则作为独立缺陷进 backlog |

---

## Explicit Scope Boundaries（VERIFICATION 须如实记录）

- **D-5**：chat 单题澄清（`chat.ConversationIntentTrace` + LangGraph interrupt）**只纳入观测，不纳入出口**——出口机制只覆盖 `delivery.Clarification`（路径 A/B）。
- **D-6**：「未澄清假设」只写 `stage_state.clarification_exit`，**本 phase 无前端渲染面**；产出正文渲染受 v0.20.0 DEPTH 冻结约束。
- **RELY-02「会话内 pending 状态对用户可见」子句**：**由既有实现满足，本 phase 不新增前端面**。该子句原先被 UI-SPEC unresolved 5 与 D-6 打包 defer，但 D-6 的 DEPTH 冻结只覆盖「产出正文渲染」，不覆盖 pending 状态可见性——挂在 D-6 理由下是记录错误。核查结论：`ChatStatusBar.vue` / `ClarificationCard` / `HumanTaskInbox.vue` 三处均已消费 `waiting_clarification` 状态，pending 态在会话内已对用户可见。本 phase 因此**不为该子句新增任何前端改动**，仅在 UAT 中确认既有呈现仍然有效（见 Manual-Only Verifications 对应行）。若 UAT 发现呈现缺失，作为独立缺陷进 backlog，不并入本 phase 范围。
- **T-107-01（accept）**：放开候选范围硬过滤后结果含项目外仓名；沿用 MCP/REST 两个已上线全库入口的既有判断（仓名不敏感），本 phase **不新增可见性面**。
- **K 预算的语义边界（与 CONTEXT 原文有偏差，verify 请以此条为准）**：CONTEXT 的字面表述是 `|rank_llm - rank_stage0| <= K`。落地实现把 base rank 定义为**「被 LLM 返回子集」内的 Stage 0 相对位次**（107-01 Task 2 / 107-05 Task 2）——这是必须的：`repo_router_v2.py:1206-1256` 显示最终候选只由 `parsed` 构造，`llm_order` 常态是全量 8 元窗口的真子集，拿子集下标去减全量下标会让位移恒 > K、修复循环无法收敛，从而在最常见情形下把 LLM 重排完全丢弃。**代价有两条，都要如实记录**：
  - (1) **「丢弃式提升」不再受 K 约束**：LLM 只要少返回候选，被留下的仓在子集内的相对位次天然靠前（极端情形：只返回 Stage 0 第 8 位这一个仓，它以 `violations == 0` 被提到首位）。字面的「相对全量 Stage 0 位次的位移上界」因此被弱化为「相对被返回子集的位移上界」。**缓解而非消除**：`stage1_meta` 落 `llm_returned_count` / `stage0_window_count` 两键（107-05 Task 2），使「返回数远小于窗口数且违规为 0」这一模式事后可识别、可加告警；`rank_budget_violations` 结构上看不到它。
  - (2) **K 的作用对象是 `clamped_order` 而非最终扁平列表**：最终列表按凸组合后的 `score_ranked` 由 `_apply_presentation` 排序，凸组合会相对 `clamped_order` 再次重排，故最终列表相对 Stage 0 的位移上界是 **2K** 而非 K。测试对「位移 <= K」的断言一律落在 `stage1_meta["clamped_order"]` 上；最终列表只断言「元素集合 == LLM 返回的合法子集」，顺序断言须先把 fixture 的 Stage 0 分差钉死（107-05 Task 2 behavior）。
- **A3**：出口不新增 `ConvergenceSessionStatus` 枚举值——「超时放行」在看板/投影层与「正常运行」暂无视觉区分。
- **O-6 / α**：生产延迟分位 deferred；α=0.35 未经离线校准（离线 harness 结构上不跑 Stage 1）。
- **A5**：Stage 1 per-call 超时保持 90s 未下调，待 O-6 生产数字回填后另议。

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references（4 个新建测试文件）
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
