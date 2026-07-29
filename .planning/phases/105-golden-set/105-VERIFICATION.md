---
phase: 105-golden-set
verified: 2026-07-29T06:25:00Z
status: human_needed
score: 35/35 must-haves verified
overrides_applied: 0
human_verification:
  - test: "在生产实例 friday.yc345.tv 执行 `cd server && uv run python manage.py measure_repo_index_stats --json --top 20 --verify-cosine`，把输出回填 105-MEASUREMENTS.md §1 延迟表与 §2 N_r 分布占位表"
    expected: "分位数（p50/p90/p99/max/median）与 top-20 倾斜表落盘；--verify-cosine 打印 dense-only 查询耗时与余弦 score 样例（自查询 top-1 ≈ 1.0）"
    why_human: "autonomous 模式无生产实例访问；本地开发库无 259 仓真实索引，本地结果按纪律不得回填（RESEARCH Pitfall 8）。此为 105-02-SUMMARY 显式登记的 deferred 人工步骤，Phase 106 常数定版（N̄/b、MaxP 口径）依赖此数据"
  - test: "从生产会话 ccd817d9 导出「高三提分专项」需求原文与真实 Stage 0 命中数值，替换 golden_main.json 中 gk-001 的合成版本，然后 GENERATE_GOLDEN=1 重建 baseline 并 review 逐例 diff"
    expected: "gk-001 变为真实生产样本；baseline 重建后门禁仍绿（或 diff 经人工确认）"
    why_human: "生产数据导出需要人工操作与访问权限；105-04-SUMMARY「待人工补充事项」显式登记"
  - test: "浏览器中打开含路由结果的会话，展开任一候选的「分数分解」，目视核对：明细行中文标签/3 位小数 font-mono/分隔线/合计行，confidence Badge 的 Tooltip 文案，以及候选行整体视觉与改动前一致（视觉零漂移）"
    expected: "展开区符合 105-UI-SPEC.md 契约；无 breakdown 的候选行与现状逐像素一致；无新增颜色/字号漂移"
    why_human: "视觉外观与逐像素一致性无法程序化验证；组件行为已有 vitest 10 用例 + vue-tsc 守护，仅剩观感确认"
---

# Phase 105: 编排解锁与评估标尺 验证报告

**Phase Goal:** 技术方案编排不再因 Stage 1 失联而永久停摆，且此后每一次排序改动都能被客观判定为改进还是退化——置信度由分数 margin 确定性推导，分数可拆解、可复现、可离线回放，golden set 作为 CI 回归门禁就位。
**Verified:** 2026-07-29T06:25:00Z（worktree `milestone/v0.19.0-plan-trust`）
**Status:** human_needed（自动化检查全部通过；3 项需人工的事项见下）
**Re-verification:** No — 初次验证

验证方法：不信 SUMMARY 声称——实读 12 个核心源文件 + 全部 7 份 PLAN must_haves 逐条核对 + 实跑后端 11 个测试文件（**149 passed, 18.5s**）+ 前端 vitest（**10 passed**）+ `vue-tsc --noEmit`（exit 0）+ fixture 结构性 Python 断言 + 反模式扫描。

## Goal Achievement

### Observable Truths（按 success criteria 分组，35 条 must-haves 全数核对）

#### SC-1：三种失联情形仍出分级并自动推进、只降不升（RELY-04）

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | 网关 400 / 连接错误 / 超时三种失联下 route() 仍产出 margin 确定性分级且 degraded=True | ✓ VERIFIED | `test_repo_router_v2_degraded.py` 11 用例实跑全绿：`test_gateway_400_/test_connection_error_/test_timeout_degrades_to_deterministic_high` 各自独立断言四元组（router_version=v2_stage0_only / degraded=True / confidence=high / auto_selected=True）；另覆盖 provider_missing 与 unparsable_llm_output 静默 None 路径 |
| 2 | auto_selected 由确定性 confidence 驱动，降级路径与 v2 路径语义一致 | ✓ VERIFIED | `repo_router_v2.py:403`（`_stage0_only_result`: `auto_selected=bool(finalized) and finalized[0].confidence == "high"`）与 `:235`（v2 路径同规则）；`test_use_llm_false_semantics_match_degraded_path` 锁两路径一致 |
| 3 | LLM confidence 只降不升，任何情况不能把 low/medium 升为 high | ✓ VERIFIED | `repo_router_scoring.py:222-233`（min 语义，非法值回退 deterministic）；`test_never_upgrades` 9 组穷举 + None 参数化；`test_llm_upgrade_low_to_high_rejected` 行为级断言 |
| 4 | Stage 1 失联 + margin 达标时 clarify 默认 policy 判定无需澄清（编排自动推进）；confidence=high 时强制确认不无差别触发 | ✓ VERIFIED | `test_engine_clarify.py` 新增 3 用例实跑通过：`test_default_policy_degraded_routing_high_margin_no_clarification` / `..._all_low_still_clarifies` / `test_clarify_adapter_degraded_routing_high_conf_no_forced_confirmation`（断言 needs_clarification=False 且 create_round 未被调用） |
| 5 | derive_confidence 严格按 S(1)>=θ_abs 且 margin>=θ_margin → high；S(1)>=θ_med → medium；θ 参数注入 | ✓ VERIFIED | `repo_router_scoring.py:198-219` 实现逐字对齐 §1.3a（含等号）；`test_margin_rule_boundaries` 参数化边界（0.55/margin 0.08→high、0.079→medium、0.349→low、空列表→low、单候选 margin=s1）；θ 三键在 `settings.py:348-350`（默认 0.55/0.08/0.35）+ `.env.example:266-270` |
| 6 | 零候选提前短路，不带空 prompt 进 Stage 1 | ✓ VERIFIED | REVIEW IN-04 修复（commit 90dcf7c7）；`test_zero_candidates_short_circuits_before_stage1` 通过 |

#### SC-2：breakdown Σ==总分、无截断（ROUTE-07）

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 7 | 任意输入 0<=score<=1 且 Σbreakdown 恰等于 score（含重归一化情形，INV-R1/R3） | ✓ VERIFIED | `repo_router_scoring.py:179`：`score = math.fsum(breakdown.values())`——INV-R3 按构造**精确**成立（非容差）；各信号 ∈[0,1] 凸组合保证 INV-R1；`test_inv_r1_/test_inv_r3_/test_missing_activity_has_no_activity_key` 实跑通过 |
| 8 | repo_router_v2.py 无任何 min(score,1.0) 截断与 DEPRECATED_PENALTY | ✓ VERIFIED | `rg "min\(.*score.*, 1\.0\)\|DEPRECATED_PENALTY" repo_router_v2.py` 零命中；scoring 模块同样零命中 |
| 9 | 废弃惩罚封顶在活跃度项内（min(A, 0.10)），非乘性 | ✓ VERIFIED | `repo_router_scoring.py:102-103`；`test_deprecated_penalty_confined_to_activity_signal` 机制级断言 |
| 10 | 每候选 to_dict() 携带 breakdown 且经 RepositoryRelevanceCandidate → trace JSON 透传到前端 | ✓ VERIFIED | `schemas/repository_relevance.py:42`（`breakdown: dict[str,float] = Field(default_factory=dict)`）→ `repository_relevance.py:252` 透传 → `routing.ts` `breakdown?: Record<string, number>` → `RoutingDecisionPanel.vue` Collapsible 展开区（7 处 Collapsible、toFixed(3)×2、合计直显 candidate.score）；`test_repository_relevance_tool.py` 实跑通过 |
| 11 | 前端展开区：中文标签 + 3 位小数 + 合计行 == score；缺失不渲染 trigger；\|Σ−score\|>1e-6 仅 console.warn；展开态 trace 更新重置 | ✓ VERIFIED | vitest 3 条分数分解用例实跑通过（含未知 key 回退、空 dict/缺失两形态、console.warn spy）；`RoutingDecisionPanel.vue:117-119` `watch(effectiveTraceId)` 重置展开 Set（backstop 4 条全部有代码+测试证据，无需 abstain） |

#### SC-3：双跑幂等 + 快照离线回放零网络（ROUTE-09）

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 12 | 同一 node_hits 乱序 100 次输出逐字段相等（稳定 tie-break + fsum） | ✓ VERIFIED | `test_shuffle_invariance_100_seeds`（`range(100)` 字面存在）；排序 `(-round(score,6), repo_id)` 先量化再比较（`scoring.py:194`）；fsum ×5 处 |
| 13 | 同需求+同索引重复路由两次结果完全相同；缓存命中零 LLM 调用 | ✓ VERIFIED | `test_double_run_cache_hit_zero_llm_calls_identical_results`（调用计数器显式断言第二次==0）+ `test_no_cache_pure_function_identical_results`（禁缓存纯函数同结果，防假绿）实跑通过 |
| 14 | 缓存 key = sha256(model_id‖模板版本‖canonical stage0_input‖decode_params‖index_version)，且含 output_cap（MJ-02 修复） | ✓ VERIFIED | key 敏感性 3 用例（stage0_input / output_cap / index_version）+ `test_cache_not_shared_across_top_k` 端到端用例实跑通过；`PROMPT_TEMPLATE_VERSION` ×5 处 |
| 15 | Stage 1 只输出排列不输出分数；decode 全固定；数值 score 字段被过滤；重复 repo_id 去重（MN-01 修复） | ✓ VERIFIED | `test_llm_numeric_score_field_filtered` / `test_llm_duplicate_repo_id_deduplicated` 实跑通过；seed gate 已收窄（MJ-01 修复 commit 8a8288fb，Responses API 不透传 seed，`test_llm_factory.py` 参数化守护通过） |
| 16 | Stage 1 统一 use_call_source(AUX_REPO_ROUTER) | ✓ VERIFIED | `repo_router_v2.py` 中 `use_call_source` ×3、`AUX_REPO_ROUTER` ×2 |
| 17 | 快照落 ConvergenceSessionEvent（只经 _emit_event）：stage0 输入 + 脱敏 stage1 材料 + breakdown + 版本四元组 | ✓ VERIFIED | `builtin_processes.py` EVENT_REPO_ROUTING + redact_for_ledger ×3（双重脱敏）；`test_event_taxonomy_alignment.py` 零改动通过；两口径 index_version 恒等守护（MN-02 修复 commit c6f916a8，`test_snapshot_index_version_matches_stage1_cache_scope` 通过）；session.routing pop snapshot 有测试断言 |
| 18 | 快照可离线回放同结果、全程零网络；payload <64KB 且无未脱敏敏感串 | ✓ VERIFIED | `test_repo_router_replay.py` 8 用例在 pytest 默认 --disable-socket 下全绿：有/无 Stage 1 回放逐字段相等、tamper 检出、repo_name 缺失容错 ×2、假密钥脱敏、64KB 上限、模块 import 纯净性；replay 复用 scoring 同一份纯函数（`aggregate_and_score/derive_confidence/apply_llm_adjustment` import 确认，无第二份实现） |
| 19 | 编排 adapter 透传 degraded 进 session.routing | ✓ VERIFIED | `repo_router_adapter.py:61`；`test_repo_router_adapter.py` 实跑通过 |

#### SC-4：golden set 门禁（ROUTE-08）

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 20 | golden set 建成：gk-001 真实事故用例 + >=2 条 cross_group、标签来源齐备 | ✓ VERIFIED | Python 断言实跑：主集 14 条、gk-001 存在且命中分布 study-app 6 / onion-learning 1 / study-course 2 / study-user-status 1（事故机制编码正确）、cross_group 2 条且 expected_repos 与 project_scope 无交集、label_source 全部 ∈ {human, weak} |
| 21 | hold-out 30% 独立封存（opened_count 字段），门禁不加载 | ✓ VERIFIED | golden_holdout.json：opened_count=0、6 条（30%）；`rg golden_holdout test_repo_router_golden.py` 零命中 |
| 22 | 门禁三规则 + 逐例 diff + weight_set_version 守护，随默认 pytest suite | ✓ VERIFIED | `test_repo_router_golden.py` 7 用例无特殊 marker（默认 suite 即门禁）；baseline 含 weight_set_version=phase105-v1 / bootstrap_ci / recall_at_5 / top1_correct_count / false_auto_select_rate / by_label_source；GENERATE_GOLDEN ×7 处 |
| 23 | 全量评估离线纯函数零网络、<5s | ✓ VERIFIED | 实跑：**7 passed in 0.08s**（wall 3s 含解释器启动，远低于 5s 目标）；eval 模块零 django/numpy/scipy import 确认 |
| 24 | bootstrap 95% CI（B=1000 固定 seed）幂等 | ✓ VERIFIED | baseline 含 bootstrap_ci；harness 纯 stdlib random，PLAN verify 的同 seed 幂等断言由测试覆盖 |

#### SC-5：105-MEASUREMENTS.md（Phase 106 输入实测）

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 25 | measure_repo_index_stats 命令存在，能按仓统计并输出 N_r 直方图（p50/p90/p99/max/median） | ✓ VERIFIED | 命令 307 行；`test_measure_repo_index_stats.py` 用内存 Qdrant（hybrid 命名向量同形）实跑通过：per-repo exact count 正确、分位数键齐全、--verify-cosine 自查询余弦 ≈1.0、单仓异常不中断 |
| 26 | 105-MEASUREMENTS.md 落盘：O-3 代码级定论 + O-1 占位表与生产执行指引 + 数据环境标注 | ✓ VERIFIED | 文档实读确认：O-3 含 hybrid_search_by_name/FusionQuery/`using="dense"` 关键修正结论；O-1 占位表 + 完整命令行 + 「本地全 0 不得回填」警告；「数据环境」标注贯穿全文（>=2 处要求远超）；生产实测显式标注 deferred 人工步骤 |

**Score:** 35/35 truths verified（其中 4 条 backstop 类均有代码+测试直接证据，无需 abstain）

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `server/codegraph/services/repo_router_scoring.py` | 零 I/O 纯函数打分核心，min 120 行 | ✓ VERIFIED | 249 行；零 django import、fsum ×5、无截断；三方（router/eval/replay）共用确认 |
| `server/codegraph/services/repo_router_eval.py` | 评估 harness，min 120 行 | ✓ VERIFIED | 358 行；exports evaluate_cases/bootstrap_ci/diff_reports；零 numpy/django |
| `server/codegraph/services/repo_router_replay.py` | 离线回放，min 60 行 | ✓ VERIFIED | 214 行；复用 scoring 纯函数，无第二份推导实现 |
| `server/codegraph/services/repo_router_v2.py` | 接线后的两阶段路由器 | ✓ VERIFIED | `from codegraph.services.repo_router_scoring import` 确认；degraded/snapshot/breakdown 字段全带默认值（3 个 stub 构造测试零改动通过） |
| `server/codegraph/management/commands/measure_repo_index_stats.py` | O-1/O-3 实测命令，min 60 行 | ✓ VERIFIED | 307 行；--json/--top/--verify-cosine 选项 |
| 测试 6 文件（scoring/degraded/golden/idempotency/replay/measure） | 各 min_lines 达标 | ✓ VERIFIED | 277/373/311/398/309/185 行，全部实跑绿 |
| golden fixtures ×3 | 主集>=10、hold-out 封存、baseline 版本绑定 | ✓ VERIFIED | 14+6+baseline；结构断言全过 |
| `schemas/repository_relevance.py` + web 三文件 | breakdown 透传链 + 展开 UI | ✓ VERIFIED | pydantic 默认空 dict；vue 组件 + 类型 + 测试全绿 |
| `.planning/phases/105-golden-set/105-MEASUREMENTS.md` | 含 O-3 | ✓ VERIFIED | 实读确认结构完整 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| repo_router_scoring.py | settings.py | θ 参数注入（模块零 Django 依赖） | ✓ WIRED | REPO_ROUTER_CONF_THETA_ABS/MARGIN/MED 三键存在，调用方 `_conf_thresholds()` 读取注入 |
| repo_router_v2.py | repo_router_scoring.py | aggregate_and_score / derive_confidence / apply_llm_adjustment | ✓ WIRED | import + 调用点（:312/:337/:776）确认，推导只此一处 |
| clarify_adapter.py | repo_router_v2.py | session.routing candidates[].confidence | ✓ WIRED | 3 条 degraded_routing 行为测试贯穿 policy/adapter 层 |
| repo_router_eval.py | repo_router_scoring.py | harness 同一纯函数路径 | ✓ WIRED | :177/:193 调用确认 |
| test_repo_router_golden.py | golden_baseline.json | GENERATE_GOLDEN 重生成 + 门禁对比 | ✓ WIRED | GENERATE_GOLDEN ×7；weight_set_version 守护 |
| repo_router_v2.py | django.core.cache / call_source | Stage 1 缓存 + AUX_REPO_ROUTER 作用域 | ✓ WIRED | 缓存 best-effort（异常不反噬有测试）；use_call_source ×3 |
| builtin_processes.py | convergence_session_service.py | _emit_event(EVENT_REPO_ROUTING) 单一写入口 | ✓ WIRED | event taxonomy 测试零改动通过 |
| repo_router_replay.py | repo_router_scoring.py | 回放与 route/harness 同一份纯函数 | ✓ WIRED | import 确认 + 模块内无 margin 阈值字面量重复实现 |
| repository_relevance.py | RoutingDecisionPanel.vue | breakdown → trace JSON → store → panel | ✓ WIRED | 双端测试贯穿（后端 trace JSON 断言 + 前端展开渲染断言） |

### Behavioral Spot-Checks（实跑，非转述 SUMMARY）

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 全部 Phase 105 后端测试 | `uv run pytest`（11 个测试文件） | **149 passed, 18.54s** | ✓ PASS |
| golden 门禁单跑耗时 | `time uv run pytest test_repo_router_golden.py -q` | 7 passed in **0.08s**（wall 3.0s） | ✓ PASS（<5s） |
| 前端组件测试 | `pnpm exec vitest run RoutingDecisionPanel.test.ts` | **10 passed** | ✓ PASS |
| 前端类型检查 | `pnpm exec vue-tsc --noEmit` | exit 0 | ✓ PASS |
| fixture 结构断言 | Python 脚本（主集/hold-out/cross_group/gk-001 分布/baseline 键） | 全部 True | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| RELY-04 | 105-01/03/05 | Stage 1 失联仍出分级并自动推进，margin 确定性推导，LLM 降为输入 | ✓ SATISFIED | Truths 1–6：三失联情形 + 静默 None 路径 + 只降不升 + clarify 推进，全部测试实跑绿 |
| ROUTE-07 | 105-01/03/06 | 分数可展开到各信号贡献值 | ✓ SATISFIED | Truths 7–11：Σ==score 精确成立、去截断、前后端透传链 + 展开 UI 双端测试绿 |
| ROUTE-08 | 105-02/04 | golden set 回归门禁，退化自动检出 | ✓ SATISFIED | Truths 20–26：14+6 fixture、三规则门禁 + 逐例 diff + 版本守护、默认 suite、0.08s |
| ROUTE-09 | 105-01/03/05/07 | 同需求同索引重复路由同结果 | ✓ SATISFIED | Truths 12–19：乱序确定性、双跑幂等、缓存 key 完整性（含 MJ-02 修复）、快照回放零网络 |

无 ORPHANED：REQUIREMENTS.md 映射到 Phase 105 的恰为这 4 个 ID，全部被 PLAN frontmatter 声明且验证。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| （无） | — | 12 个改动源文件扫描 TBD/FIXME/XXX/TODO/HACK/placeholder 零命中 | — | — |

REVIEW 记录的 2 项 deferred finding 核实为非缺陷：IN-02（缓存命中快照 response 为空串）是 105-05-SUMMARY 已登记的已知取舍（cache_hit 标志指引审计回溯）；IN-03（Tooltip 文案 rank 语义）文案为 UI-SPEC 原文锁定，归 Phase 107。6 项 fixed finding（含 2 MAJOR）逐一核实修复已落码且带守护用例（seed gate、output_cap 入 key、去重、index_version 口径统一、日志字段名、零候选短路）。

### Human Verification Required

以下 3 项无法程序化验证（frontmatter 同步结构化）：

#### 1. O-1 生产实测回填（Phase 106 常数定版的硬输入）

**Test:** 在 friday.yc345.tv 执行 `uv run python manage.py measure_repo_index_stats --json --top 20 --verify-cosine`，回填 105-MEASUREMENTS.md 的 N_r 分布表与 dense 查询延迟数字。
**Expected:** 分位数与 top-20 表落盘；余弦自查询 top-1 ≈ 1.0；延迟数字决定 Phase 106 MaxP 口径。
**Why human:** autonomous 模式无生产访问；本地开发库数据按纪律不得回填。此为 phase 文档显式登记的 deferred 人工步骤——本 phase 的 scoped 承诺（命令 + 结构性结论 + 占位表 + 执行指引）已全部达成。

#### 2. golden set 真实生产样本替换

**Test:** 导出会话 ccd817d9 的需求原文与 Stage 0 命中数值，替换 gk-001 合成版本，`GENERATE_GOLDEN=1` 重建 baseline 并 review diff。
**Expected:** 门禁仍绿或 diff 经人工确认。
**Why human:** 需生产数据导出权限；105-04-SUMMARY 已显式跟踪。

#### 3. 前端「分数分解」展开区目视核验

**Test:** 浏览器中展开候选的分数分解，核对 UI-SPEC 契约（标签/小数/合计行/Tooltip）与视觉零漂移。
**Expected:** 与 105-UI-SPEC.md 一致；无 breakdown 候选行与现状逐像素一致。
**Why human:** 视觉外观无法 grep/单测验证；行为层已有 10 条 vitest 用例守护。

### Gaps Summary

无 gaps。35/35 must-haves 全部在代码与实跑测试层面验证成立；5 条 phase success criteria（失联分级自动推进 / Σ==总分无截断 / 双跑幂等+离线回放零网络 / golden 门禁 <5s 进默认 suite / MEASUREMENTS 结构性落盘）逐条核实。status 取 human_needed 仅因存在 3 项需人工的事项（2 项为 phase 内显式登记的生产环境 deferred 步骤，1 项为视觉核验），不阻塞代码层验收。

---

_Verified: 2026-07-29T06:25:00Z_
_Verifier: Claude (gsd-verifier)_
