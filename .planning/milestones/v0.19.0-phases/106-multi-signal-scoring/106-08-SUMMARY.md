---
phase: 106-multi-signal-scoring
plan: 08
subsystem: codegraph-routing
tags: [repo-router, golden-set, offline-eval, scoring, pivoted-normalization, ci-gate]

requires:
  - phase: 106-01
    provides: aggregate_and_score 六信号新签名（weights/repo_meta/constants/now）+ DEFAULT_WEIGHT_CONFIG（含 weight_set_version=phase106-v1）
  - phase: 106-06
    provides: 快照 weight_config/repo_meta/scored_at 键契约——fixture 的 repo_meta 同形取值依据
  - phase: 105-04
    provides: golden 门禁三规则 + baseline 结构 + GENERATE_GOLDEN=1 重建流程 + hold-out 封存纪律
provides:
  - golden fixture 六信号离线评估能力：14 条 main case 全量携带 hit facets 五维 / case 级 repo_meta（n_r、last_commit_at、facet_scores T1 内联、criticality_value、按需 dense_cos_max）/ scored_at 固定锚点 / constants.n_bar
  - score_case 单 case 打分入口：case 含 repo_meta 走六信号新路径，不含走 legacy 三信号（向后兼容）
  - WEIGHT_SET_VERSION 单一来源化并 bump 至 phase106-v1（取自 DEFAULT_WEIGHT_CONFIG，与 baseline 重建同提交生效）
  - gk-001 机制断言三件套（breadth 不偏袒巨仓 / rank 翻转 / 跨组两仓进 Top-5）进默认 pytest 门禁
  - phase106-v1 golden baseline：Recall@5 0.9643、MRR@10 1.0、Top-1 14/14、误自动选中率 0.0
affects: [107 权重调参（回归标尺已切换为六信号口径）, 后续任何排序/权重改动的门禁比较锚]

tech-stack:
  added: []
  patterns:
    - "离线评估 T1-only 口径：facet 匹配分由 fixture 内联给数值（repo_meta.facet_scores），机制断言不依赖 T2/embedding——门禁零网络且确定性"
    - "机制级断言 > 结果级断言（ROUTING-RANKING §7.4）：锁「尺寸偏置已消除」的因果性质（breadth 分项对比 + 相对名次 + Top-5 窗口），不锁权重敏感的绝对名次"
    - "版本纪律双保险（Pitfall 8）：WEIGHT_SET_VERSION 取自 DEFAULT_WEIGHT_CONFIG 单一来源 + 门禁字面绑定断言，bump 与 baseline 重建必须同提交"

key-files:
  created: []
  modified:
    - server/tests/codegraph/fixtures/repo_router_golden/golden_main.json
    - server/tests/codegraph/fixtures/repo_router_golden/golden_holdout.json
    - server/tests/codegraph/fixtures/repo_router_golden/golden_baseline.json
    - server/codegraph/services/repo_router_eval.py
    - server/codegraph/services/repo_router_scoring.py
    - server/tests/codegraph/test_repo_router_golden.py

key-decisions:
  - "WEIGHT_SET_VERSION = DEFAULT_WEIGHT_CONFIG[\"weight_set_version\"] 单一来源，而非再写一遍字面量——消除两处版本不同步的可能"
  - "门禁保留一条字面绑定断言 assert WEIGHT_SET_VERSION == \"phase106-v1\"：单一来源防不了「改配置忘了重建 baseline」，字面断言 + baseline 比对两条一起构成 Pitfall 8 闸门"
  - "不变量测试（INV-R1/R3）改走 score_case：门禁实际打分的是六信号路径，只验 legacy 路径的不变量属于验错了对象"
  - "baseline recall@5 门槛按 105 精确值 27/28=0.9642857142857143 比对，不用 plan 里 0.9643 的四舍五入字面量（1e-9 容差下会假红）"

patterns-established:
  - "gk-001 事故以数据形式完整编码：N_r 620/30 + n_bar 60 + dense_cos_max 0.52/0.62（「6 个中等命中 vs 1 个 top 命中」），翻转由公式产生而非由标签硬指定"
  - "baseline 重建后逐例 diff 必须人工 review 并记入 SUMMARY——只允许预期的单例变好，出现意外 regressed 时改 fixture 元数据一致性，不许调权重凑基线"

requirements-completed: [ROUTE-03, ROUTE-04, ROUTE-05]

coverage:
  - id: D1
    description: "gk-001「高三提分专项」在六信号公式下完成翻转：Top-1 = onion-learning（105 baseline 为 study-app），且机制层面 study-app 的 breadth 贡献 0.0462 <= onion-learning 0.0697——尺寸偏置被 pivoted normalization 消除"
    requirement: ROUTE-03
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_golden.py#test_gk001_mechanism_breadth_not_favor_monolith + test_gk001_mechanism_rank_flipped"
        status: pass
      - kind: unit
        ref: "server/tests/codegraph/fixtures/repo_router_golden/golden_baseline.json#per_case[gk-001-gaosan-tifen].top1_repo_id == onion-learning（GENERATE_GOLDEN=1 生成，非手写）"
        status: pass
    human_judgment: false
  - id: D2
    description: "跨组两仓 study-course / study-user-status 进入 gk-001 Top-5（新信号未把跨组正确仓压出窗口）——SC-1 后半句，既有「进候选集合」断言升级为进 Top-5"
    requirement: ROUTE-03
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_golden.py#test_gk001_cross_group_repos_in_top5"
        status: pass
    human_judgment: false
  - id: D3
    description: "业务域/技术栈/关键程度等元数据与连续活跃度参与离线评估打分：14 条 case 全量携带 hit facets 五维 + repo_meta（facet_scores T1 内联 / criticality_value / last_commit_at 相对 scored_at）；baseline breakdown 出现 domain/stack 分项，活跃度按连续衰减取值（如 legacy-portal 0.0074 vs 活跃仓 0.1463）"
    requirement: ROUTE-04
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_golden.py#test_all_candidates_satisfy_score_invariants（走 score_case 六信号路径，值域 + 分解恒等）"
        status: pass
      - kind: unit
        ref: "server/tests/codegraph/fixtures/repo_router_golden/golden_baseline.json#per_case[*].top1_breakdown 含 domain/stack 键与连续 activity 值"
        status: pass
    human_judgment: false
  - id: D4
    description: "phase106-v1 baseline 成为此后一切排序改动的回归标尺，门禁三规则在新基线下继续生效：Recall@5 0.9642857（不低于 105）、Top-1 14/14、误自动选中率 0.0 <= 10%、全量评估 0.18s < 10s 零网络；版本守护双断言防「改公式不 bump 版本」"
    requirement: ROUTE-05
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_golden.py（9 passed：门禁三规则 + 版本守护 + 耗时预算 + 机制断言 + 确定性 + diff 自测）"
        status: pass
      - kind: integration
        ref: "cd server && uv run pytest tests/codegraph tests/delivery tests/services/test_repo_router_adapter.py -q → 839 passed / 20 skipped"
        status: pass
    human_judgment: false
  - id: D5
    description: "hold-out 封存纪律不破：golden_holdout.json 仅做同形字段扩展（结构性编辑），opened_count 保持 0、opened_log 未动、门禁测试文件对其零引用"
    verification:
      - kind: unit
        ref: "rg -c 'golden_holdout' server/tests/codegraph/test_repo_router_golden.py == 0；holdout opened_count == 0（6 条 case 全部同形扩展）"
        status: pass
    human_judgment: false

duration: ~25min（含前一执行器中断后的续接）
completed: 2026-07-30
status: complete
---

# Phase 106 Plan 08: golden 版本 bump 与 gk-001 翻转 Summary

**golden set 切换到六信号离线评估口径：fixture 内联 repo_meta/facets/scored_at 后 gk-001 事故用例由公式自然翻转（Top-1 study-app → onion-learning），WEIGHT_SET_VERSION bump 至 phase106-v1 与 baseline 重建同提交落地，机制断言三件套锁住「尺寸偏置已消除」的因果性质**

## Performance

- **Duration:** ~25 min（Task 1 由前一执行器完成于 23:21，本次续接 Task 2 约 12 min）
- **Started:** 2026-07-29T23:0xZ 前后（Task 1 起）／续接 2026-07-30T00:45+08:00
- **Completed:** 2026-07-30T00:52+08:00
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- **SC-1 兑现（gk-001 翻转由公式产生）**：fixture 按 ROUTING-RANKING §2.4 把事故编码成数据（N_r(study-app)=620 / N_r(onion-learning)=30 / n_bar=60，dense_cos_max 0.52 vs 0.62 表达「6 个中等命中 vs 1 个 top 命中」），六信号打分下 Top-1 = onion-learning，breadth 分项 study-app 0.0462 <= onion-learning 0.0697——翻转来自 pivoted normalization，不是标签硬指定。
- **机制断言三件套进默认 pytest 门禁**（ROUTING-RANKING §7.4）：`test_gk001_mechanism_breadth_not_favor_monolith`（breadth 不偏袒巨仓）、`test_gk001_mechanism_rank_flipped`（相对名次翻转）、`test_gk001_cross_group_repos_in_top5`（跨组两仓进 Top-5）。断言锁因果性质而非绝对名次，抗权重微调；辅助函数 `_rank_of` 在候选缺失时直接失败（召回缺失也算退化）。
- **版本纪律双保险（Pitfall 8）**：`WEIGHT_SET_VERSION` 改为取自 `DEFAULT_WEIGHT_CONFIG`（单一来源，删除 105 的「bump 归 106-08」过渡注释）+ 门禁字面绑定断言；bump 与 `GENERATE_GOLDEN=1` 重建 baseline 落在同一提交 `50f17c3d`，无中间态红灯窗口。
- **phase106-v1 baseline 生成并逐例 review**：Recall@5 0.9642857（与 105 持平，唯一 0.5 的 gk-013 部分召回未变）、MRR@10 0.9643 → 1.0、Top-1 13/14 → **14/14**、误自动选中率 0.0、全量评估 0.18s。
- **收官全量绿**：`tests/codegraph tests/delivery tests/services/test_repo_router_adapter.py` 839 passed / 20 skipped；`ruff check` + `ruff format --check` 三文件干净；前端 `RoutingDecisionPanel.test.ts` 12 passed（标签回归口径未破）。

## baseline 逐例 diff review（GENERATE_GOLDEN=1 重建后）

`diff_reports` 结论：**improved = [gk-001-gaosan-tifen]，regressed = 无，unchanged = 13 条**——与 plan 预期（唯一显著变化为 gk-001 翻转）完全一致。

| case | 变化 | 说明 |
|------|------|------|
| gk-001-gaosan-tifen | **improved** | top1 `study-app` → `onion-learning`；mrr@10 0.5 → 1.0；top1_correct false → true；breakdown 由 `{text .576, breadth .200, activity .090}` 变为 `{text .458, breadth .070, activity .133, domain .167, stack .053}`——breadth 由 0.200 降到 0.070 是尺寸偏置被消除的直接证据 |
| gk-005-deprecated-competitor | 指标不变 | confidence medium → high（六信号下正确仓与竞争仓分差拉开）；top1/recall/mrr 全部不变 |
| gk-011-ticket-ambiguous | 指标不变 | confidence medium → high（同上）；歧义 case 的 Top-1 仍正确 |
| 其余 11 条 | unchanged | top1/recall@5/mrr@10 逐字段不变；breakdown 形状变化（新增 domain/stack 分项、权重重归一化后 text 由 0.7 降至 0.503、activity 由枚举档位变连续衰减值） |

汇总项变化：`high_conf_count` 10 → 12（两条 medium 升 high），但 `false_auto_select_rate` 保持 0.0——护栏未因置信度上移而恶化；`mrr_at_10` bootstrap CI 收紧为 [1.0, 1.0]。

## Task Commits

1. **Task 1: fixture 字段扩展 + evaluate_cases 新路径透传** - `896a4367` (feat) — 14 条 main case 六信号字段扩展 + holdout 同形扩展 + `score_case` 新旧路径分流
2. **Task 2: 版本 bump + 机制断言 + baseline 重建** - `50f17c3d` (feat) — 三者同提交（版本纪律要求）

## Files Created/Modified

- `server/tests/codegraph/fixtures/repo_router_golden/golden_main.json` - 14 条 case 扩展 hit facets 五维 / repo_meta / scored_at / constants.n_bar；gk-001 `_notice` 更新为「Phase 106 已按 pivoted normalization 翻转（106-08）」
- `server/tests/codegraph/fixtures/repo_router_golden/golden_holdout.json` - 6 条同形字段扩展（结构性编辑），opened_count 保持 0，`_notice` 注明未参与评估
- `server/codegraph/services/repo_router_eval.py` - 新增 `score_case`（repo_meta 有→六信号新路径 / 无→legacy）；模块 docstring 记录 case 新字段契约与 T1-only 离线口径；零 Django/numpy import 保持
- `server/codegraph/services/repo_router_scoring.py` - `WEIGHT_SET_VERSION` 单一来源化并生效 phase106-v1，删除 105 过渡注释
- `server/tests/codegraph/test_repo_router_golden.py` - 机制断言三件套 + `gk001_ranked` module fixture + `_rank_of`/`_breadth_of` 辅助；不变量测试改走 `score_case`；版本字面绑定断言
- `server/tests/codegraph/fixtures/repo_router_golden/golden_baseline.json` - phase106-v1 新基线（GENERATE_GOLDEN=1 生成）

## Decisions Made

- **版本单一来源 + 字面断言并存**：`WEIGHT_SET_VERSION` 取自 `DEFAULT_WEIGHT_CONFIG` 消除「两处字面量不同步」，但单一来源防不住「改了配置忘了重建 baseline」——因此门禁保留一条 `assert WEIGHT_SET_VERSION == "phase106-v1"`，与 baseline 比对断言共同构成 Pitfall 8 闸门。
- **翻转不写成结果断言**：三条机制断言均不写 `ranked[0] == "onion-learning"`（§7.4 的脆弱反例），改为 breadth 分项对比 + 相对名次 + Top-5 窗口；权重后续微调时红灯能直接指向失效的机制。
- **不动 gk-013 的部分召回**：其 recall@5=0.5 是 fixture 既有语义（候选集只召回 2 个 expected 中的 1 个），六信号未改变该结论；Recall@5 因此与 105 持平而非上升，符合「不允许下降」门禁而无需美化。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] plan verify 里 `recall_at_5 >= 0.9643 - 1e-9` 是假红断言**
- **Found during:** Task 2（baseline 门禁核对）
- **Issue:** 105 基线 Recall@5 的精确值是 13.5/14 = `0.9642857142857143`，plan 写的 `0.9643` 是四舍五入后的字面量。在 1e-9 容差下 `0.9642857 >= 0.9642999` 恒为 False——照抄该断言会把「与基线持平」误判为退化。
- **Fix:** 核对断言改用 105 精确值 `0.9642857142857143 - 1e-9`；门禁测试本身早已用 `report.recall_at_5 >= baseline["recall_at_5"] - 1e-9`（读 baseline 实际值，不含此问题），无需改代码。
- **Files modified:** 无（仅核对命令口径修正）
- **Verification:** 新 baseline `recall_at_5 == 0.9642857142857143`，`test_golden_gate_vs_baseline` 绿
- **Committed in:** 无代码变更

**2. [Rule 2 - Missing Critical] 不变量测试验的是没在门禁里跑的那条路径**
- **Found during:** Task 2（机制断言落地）
- **Issue:** `test_all_candidates_satisfy_score_invariants` 用 `aggregate_and_score(case["node_hits"])`（legacy 三信号）验 INV-R1/R3，而门禁 `evaluate_cases` 实际走的是 `score_case` 六信号路径——新路径的值域与分解恒等无人守护（新增 domain/stack 分项 + 权重重归一化正是最容易破坏分解恒等的地方）。
- **Fix:** 改走 `score_case(case)`；相应移除已无用的 `aggregate_and_score` 导入（前一执行器已预留 `score_case` 导入，ruff F401 由此消解）。
- **Files modified:** server/tests/codegraph/test_repo_router_golden.py
- **Verification:** 14 条 case 全部候选满足 `0 <= score <= 1` 且 `fsum(breakdown) == score`（零违例）
- **Committed in:** `50f17c3d`

---

**Total deviations:** 2 auto-fixed（1 plan 断言字面量 bug、1 缺失关键守护）
**Impact on plan:** 均为正确性修正，未扩大范围；权重、fixture 取值、baseline 生成方式一律未动（未通过调权重凑基线）。

## Issues Encountered

- **前一执行器中断后的现场续接**：`repo_router_scoring.py`（版本单一来源化）与 `test_repo_router_golden.py`（字面绑定断言 + 预留 `score_case` 导入）已有未提交改动，处于「版本已 bump 但 baseline 未重建」的中间态红灯（2 failed）。按版本纪律未拆分提交，而是补齐机制断言并重建 baseline 后一次性提交，落地即全绿。

## User Setup Required

None - 无外部服务配置需求。

## Next Phase Readiness

- **回归标尺已切换**：此后任何权重/公式改动都以 phase106-v1 baseline 为比较锚，跨版本指标不可比由版本守护双断言强制；改公式必须 `GENERATE_GOLDEN=1` 重建 + 逐例 diff review + 同提交 bump。
- **Phase 107 权重调参就绪**：离线 harness 已支持 case 级 `weight_overrides`/`constants` 注入（`score_case`），坐标上升扫参可直接复用，全量 0.18s 足够进交互式循环。
- **hold-out 仍封存**：6 条 hold-out 已同形扩展但 `opened_count=0`，里程碑验收时可零改造直接评估。
- **注意**：gk-001 的 `_notice` 仍标注「待人工补充生产原文」——当前为会话场景合成重写，真实原文补入时需重跑 baseline 重建流程。

## Self-Check: PASSED

- `.planning/phases/106-multi-signal-scoring/106-08-SUMMARY.md` 存在 ✓
- 提交存在：`896a4367`（Task 1）、`50f17c3d`（Task 2，版本 bump + baseline + 断言同提交）✓
- `server/tests/codegraph/fixtures/repo_router_golden/golden_baseline.json` `weight_set_version == "phase106-v1"`、`top1_correct_count == 14`、`recall_at_5 == 0.9642857142857143`、`false_auto_select_rate == 0.0` ✓
- `rg -c '"phase105-v1"' server/codegraph/services/repo_router_scoring.py` == 0 ✓
- `rg -c 'breadth' server/tests/codegraph/test_repo_router_golden.py` == 10 >= 1 ✓
- `rg -c 'golden_holdout' server/tests/codegraph/test_repo_router_golden.py` == 0 且 holdout `opened_count == 0` ✓
- `rg -c 'import numpy|from numpy|import django|from django' server/codegraph/services/repo_router_eval.py` == 0 ✓
- `uv run pytest tests/codegraph/test_repo_router_golden.py -q` → 9 passed（0.18s < 10s）✓
- `uv run pytest tests/codegraph tests/delivery tests/services/test_repo_router_adapter.py -q` → 839 passed / 20 skipped ✓
- `uv run ruff check` + `ruff format --check`（eval / scoring / golden 测试三文件）全过 ✓
- `pnpm vitest run src/components/chat/__tests__/RoutingDecisionPanel.test.ts` → 12 passed ✓
- STATE.md / ROADMAP.md 未改动（本次执行约束）✓

---
*Phase: 106-multi-signal-scoring*
*Completed: 2026-07-30*
