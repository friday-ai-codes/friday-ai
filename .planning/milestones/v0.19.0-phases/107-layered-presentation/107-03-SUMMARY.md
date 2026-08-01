---
phase: 107-layered-presentation
plan: 03
subsystem: api
tags: [repo-router, block-ranking, grouping, degrade-reason, redaction, dataclass-additive, structlog]

# Dependency graph
requires:
  - phase: 107-layered-presentation
    provides: "107-01 的六个纯函数（annotate_groups / decide_block_order / classify_degrade_reason / clamp_ranking_params 等）与 9 个 settings 键"
  - phase: 106-multi-signal-scoring
    provides: "六信号可拆解打分与 Σbreakdown == score 恒等式（本 plan 一行未动）"
  - phase: 105-golden-set
    provides: "degraded / router_version / 确定性 confidence 与 skipped_reason 六个产出点"
provides:
  - "RepoRouteCandidateV2 的 group / trust / cross_group_note / score_ranked 四个 additive-safe 旁路字段（to_dict 同步输出）"
  - "RepoRouteResultV2 的 block_order / degrade_reason 两个结果字段（前端判定是否启用分组呈现的唯一依据 + 6 值闭集降级原因）"
  - "route(grouping_repository_ids=...)：与 repository_ids 正交的分组依据参数（只标注、不过滤、不打分）"
  - "_rank_value / _rank_sort_key：排序比较值与排序键的唯一所有者"
  - "_apply_presentation：四条 return 出口共用的分组标注 + 组内 top_k + 全局排序 + block_order"
  - "两处上游异常文本的源头脱敏（Stage 1 失败 + repo_meta 组装失败）"
affects: [107-04, 107-05, 107-06, 107-07, 107-08, 107-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "旁路字段纪律（延续 criticality 先例）：新增展示/排序字段一律带默认值、绝不进 breakdown，Σbreakdown == score 恒等式不受影响"
    - "比较值单一所有者：同一「缺省回退」语义只在 _rank_value 内声明一次，排序键 _rank_sort_key 亦只声明一次，静态断言锁定定义唯一性（而非调用次数）"
    - "呈现层与决策层分离：block_order 只排分区顺序，auto_selected 恒读扁平列表首位——组别结构上无法进编排决策路径"
    - "脱敏在截断之前：str(exc)[:200] 全文件归零，异常文本先过 redact_secrets_in_text 再限长"
    - "源头脱敏的机制断言：用 structlog.testing.capture_logs 绕过全局 redact_credentials processor，断言事件字段本身已脱敏（否则测试会被兜底脱敏骗过）"

key-files:
  created: []
  modified:
    - server/codegraph/services/repo_router_v2.py
    - server/tests/codegraph/test_repo_router_v2_meta.py
    - server/tests/codegraph/test_repo_router_v2_degraded.py

key-decisions:
  - "排序键抽成独立的 _rank_sort_key（而非在 _apply_presentation 内定义局部 key）：plan 允许两者之一，取模块级函数是因为组内排序与并集后全局排序两处共用，且静态断言可对定义唯一性取行首锚定"
  - "_stage0_only_result 改为先按全部 Stage 0 候选定稿再交呈现层截断：分组启用时要按组各取 top_k，先截到 top_k 会让 global 组几乎恒空；confidence 推导只依赖候选在 Stage 0 分数序列里的位次，与截断上限无关，故口径零变化"
  - "degrade_reason 的 classify 调用点收在 _stage0_only_result / _fallback_v1 两处，而非在每个 skipped_reason 产出点各调一次：内部 skipped_reason 字符串保持逐字不变（排障口径不破），映射只发生在结果构造处"
  - "stage1_meta 的 degrade_reason 由 _stage0_only_result 合并写入（不在 except 分支重复 classify）：一次分类同时喂结果字段与快照 stage1 节，两者恒等可交叉核对"
  - "无分组上下文时 _apply_presentation 只做 [:top_k] 不重排：Stage 1 成功路径的 LLM 排列必须原样保留，若此时按 score 排序会把 LLM 重排整体丢弃（现阶段 score_ranked 恒为 None）"

patterns-established:
  - "additive-safe dataclass 扩展：新字段全部带默认值 + 位置参数构造用例守护，8 个消费方与既有测试替身零改动"
  - "机制断言优先：SC-2 用「同一候选在传/不传分组依据两次调用下 score/breakdown/confidence 逐键相等」证明组别零分数影响，而非断言某个具体分值"
  - "闭集守护测试：对 5 种注入异常类型循环断言 degrade_reason ∈ DEGRADE_REASONS | {\"\"}"

requirements-completed: [ROUTE-01, ROUTE-02, RELY-03]

coverage:
  - id: D1
    description: "候选与结果的六个新字段全部 additive-safe：5 位置参数构造仍可用、to_dict 键集合 == 既有键 ∪ 四个呈现键、score_ranked 为 None 时原样输出 None"
    requirement: "ROUTE-01"
    verification:
      - kind: unit
        ref: "tests/codegraph/test_repo_router_v2_meta.py#test_candidate_positional_construction_keeps_new_fields_default"
        status: pass
      - kind: unit
        ref: "tests/codegraph/test_repo_router_v2_meta.py#test_candidate_to_dict_key_set_includes_presentation_fields"
        status: pass
      - kind: unit
        ref: "tests/codegraph/test_repo_router_v2_meta.py#test_candidate_to_dict_score_ranked_none_stays_none"
        status: pass
      - kind: unit
        ref: "tests/codegraph/test_repo_router_v2_meta.py#test_result_construction_defaults_block_order_and_degrade_reason"
        status: pass
    human_judgment: false
  - id: D2
    description: "三参数（delta / α / K）调用时读取且非法值经 clamp 收敛、绝不抛（T-107-05）"
    verification:
      - kind: unit
        ref: "tests/codegraph/test_repo_router_v2_meta.py#test_ranking_conf_clamps_illegal_settings"
        status: pass
      - kind: unit
        ref: "tests/codegraph/test_repo_router_v2_meta.py#test_ranking_conf_reads_settings_at_call_time"
        status: pass
    human_judgment: false
  - id: D3
    description: "grouping_repository_ids 与 repository_ids 正交：无项目上下文全部 global 且 block_order == ['global'] 不报错；传入分组依据则分两组、跨组候选带后端留痕说明、block_order 恒长度 2（含某组为空）"
    requirement: "ROUTE-01"
    verification:
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_meta.py#test_route_no_project_context_all_global_block_order"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_meta.py#test_route_grouping_annotates_two_groups"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_meta.py#test_route_grouping_with_empty_in_project_group"
        status: pass
    human_judgment: false
  - id: D4
    description: "delta 迟滞置顶在 router 侧生效；分组启用时按组各取 top_k 后并集并按同一比较键全局降序；扁平首位与置顶组可以不同"
    requirement: "ROUTE-02"
    verification:
      - kind: unit
        ref: "tests/codegraph/test_repo_router_v2_meta.py#test_presentation_hysteresis_at_delta_threshold"
        status: pass
      - kind: unit
        ref: "tests/codegraph/test_repo_router_v2_meta.py#test_presentation_per_group_top_k_and_global_descending"
        status: pass
      - kind: unit
        ref: "tests/codegraph/test_repo_router_v2_meta.py#test_presentation_flat_top_is_global_max_regardless_of_block_order"
        status: pass
    human_judgment: false
  - id: D5
    description: "组别绝不进分数也不进编排决策：同一候选在传/不传分组依据两次调用下 score/breakdown/confidence 逐键相等；auto_selected 在三种分区顺序下恒由扁平首位驱动"
    requirement: "ROUTE-02"
    verification:
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_meta.py#test_score_and_breakdown_identical_with_and_without_grouping"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_meta.py#test_auto_selected_is_independent_of_block_order"
        status: pass
      - kind: other
        ref: "test \"$(rg -v '^[[:space:]]*#' server/codegraph/services/repo_router_v2.py | rg -c 'score \\+=|score \\* 1\\.|boost' || echo 0)\" = \"0\""
        status: pass
    human_judgment: false
  - id: D6
    description: "排序比较值只有一个所有者：_rank_value 恰一处定义、无内联等价回退表达式绕过它、组首位取值与两处排序均经它"
    verification:
      - kind: unit
        ref: "tests/codegraph/test_repo_router_v2_meta.py#test_rank_value_prefers_score_ranked_including_zero"
        status: pass
      - kind: other
        ref: "test \"$(rg -c '^def _rank_value' server/codegraph/services/repo_router_v2.py)\" = \"1\" && test \"$(rg -v '^[[:space:]]*#' ... | rg -c 'score_ranked is not None else .*score')\" = \"1\" && _rank_value 出现 4 次（>= 3）"
        status: pass
    human_judgment: false
  - id: D7
    description: "六条降级出口产出 6 值闭集内的 degrade_reason（timeout / upstream_error / provider_missing / unparsable / no_node_index / 空串），任意异常类型下恒 ∈ DEGRADE_REASONS | {\"\"}"
    requirement: "RELY-03"
    verification:
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_degrade_reason_timeout"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_degrade_reason_upstream_error"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_degrade_reason_provider_missing"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_degrade_reason_no_model_maps_to_provider_missing"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_degrade_reason_unparsable"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_degrade_reason_no_valid_candidates_maps_to_unparsable"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_degrade_reason_v1_fallback_is_no_node_index"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_degrade_reason_empty_for_non_user_visible_paths"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_degrade_reason_is_always_in_closed_set"
        status: pass
    human_judgment: false
  - id: D8
    description: "上游异常文本无裸露路径（T-107-02）：快照与两处 warning 事件均无密钥明文，str(exc)[:200] 全文件归零"
    requirement: "RELY-03"
    verification:
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_redact_upstream_secret_from_snapshot_and_meta"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_redact_meta_load_failure_log_event"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_redact_stage1_failure_log_event"
        status: pass
      - kind: other
        ref: "test \"$(rg -c 'str\\(exc\\)\\[:200\\]' server/codegraph/services/repo_router_v2.py || echo 0)\" = \"0\" && rg -c 'redact_secrets_in_text' == 3（>= 2）"
        status: pass
    human_judgment: false
  - id: D9
    description: "打分口径与消费方零回归：Σbreakdown == score 两条既有断言继续绿、golden baseline 与 repo_router_scoring.py 零改动、8 个消费方全量绿"
    verification:
      - kind: unit
        ref: "cd server && uv run pytest tests/codegraph -q → 502 passed / 20 skipped（含 golden 门禁与回放）"
        status: pass
      - kind: integration
        ref: "cd server && uv run pytest tests/codegraph tests/services/test_repo_router_adapter.py tests/agents/test_repository_relevance_tool.py tests/initiatives/test_repo_association_service.py -q → 533 passed"
        status: pass
      - kind: integration
        ref: "cd server && uv run pytest tests/knowledge/test_artifact_repo_routing.py tests/agents tests/tools tests/repositories tests/mcp_tools tests/services -q → 1548 passed"
        status: pass
    human_judgment: false

# Metrics
duration: 40min
completed: 2026-07-30
status: complete
---

# Phase 107 Plan 03: Router 呈现字段与链路韧性接线 Summary

**`RepoRouterV2` 接入 107-01 纯函数：候选扩出 group/trust/cross_group_note/score_ranked 四个旁路字段、结果扩出 block_order/degrade_reason，`route()` 新增与 `repository_ids` 正交的 `grouping_repository_ids`，四条 return 出口共用同一套呈现逻辑；降级原因收敛为 6 值闭集，两处 `str(exc)[:200]` 裸露改为源头脱敏——`score`/`breakdown` 与 golden baseline 一行未动。**

## Performance

- **Duration:** 约 40 min
- **Started:** 2026-07-29T21:45:00Z
- **Completed:** 2026-07-29T22:25:00Z
- **Tasks:** 3（全部走 TDD：RED → GREEN，无 REFACTOR 轮）
- **Files modified:** 3

## Accomplishments

- **六个新字段全部 additive-safe**：`RepoRouteCandidateV2` 的四个呈现字段与 `RepoRouteResultV2` 的两个结果字段都带默认值，5 位置参数构造仍成立；`to_dict()` 键集合断言进测试（不是人工核对），8 个消费方与既有测试替身零改动仍绿。
- **分组依据与硬过滤真正正交**：`route(grouping_repository_ids=...)` 只做 `group`/`trust` 标注，不参与任何过滤或打分；`None` 时全部 `global`、`block_order == ["global"]`、候选列表行为逐字不变（只做 `[:top_k]`，不重排）。现有 8 个入口一个都没传新参数，因此候选构成与顺序零变化。
- **组别对分数与编排的零影响可机制断言**：SC-2 用「同一候选在传/不传分组依据两次调用下 `score`/`breakdown`/`confidence` 逐键相等」证明；`auto_selected` 在三种不同 `block_order`（`["global"]` / `["in_project","global"]` / `["global","in_project"]`）下恒为 `True` 且恒由扁平首位驱动。
- **排序比较值收敛到一个所有者**：`_rank_value` 恰一处定义、无任何内联等价回退表达式绕过它；`_rank_sort_key`（先量化到 6 位再比较、第二键取不可变 `repo_id`）被组内排序与并集后全局排序共用。107-05 只需把 `score_ranked` 写上，不必再碰排序。
- **降级原因成为受控闭集事实**：三条降级出口 + v1 回落全部经 `classify_degrade_reason` 产出 `degrade_reason`；内部 `skipped_reason` 字符串保持逐字不变（排障口径不破），两者同进快照 `stage1` 节可交叉核对；5 种注入异常类型循环断言恒 ∈ `DEGRADE_REASONS | {""}`。
- **两处真实脱敏缺口被堵住**：`repo_router_meta_load_failed`（原 `:236`）与 Stage 1 失败分支（原 `:326`）的 `str(exc)[:200]` 全部改走 `redact_secrets_in_text` 后再限长，`str(exc)[:200]` 在本文件归零；`stage1_meta` 追加 `error_redacted` 供排障下钻，原始 `str(exc)` 不再进入任何会回前端的结构。
- **打分口径冻结得到验证**：`repo_router_scoring.py` 与 `golden_baseline.json` 未出现在任何提交的改动清单中；两条 `Σbreakdown == score`（fsum 1e-9）断言继续绿。

## Task Commits

1. **Task 1: 候选/结果新字段 + to_dict + 参数读取 clamp** — `180f3d28` (test, RED) → `78942764` (feat, GREEN)
2. **Task 2: grouping_repository_ids 参数 + 分组标注/block_order 接线** — `86c585ec` (test, RED) → `21c1ab9e` (feat, GREEN)
3. **Task 3: 降级原因分类接线 + 异常文本脱敏** — `3cf1ad0e` (test, RED) → `96fdd14e` (feat, GREEN)

_三个 task 的 REFACTOR 轮均未产生改动（GREEN 实现即最终形态）。_

## Files Created/Modified

- `server/codegraph/services/repo_router_v2.py` — 四个候选字段 + 两个结果字段 + `to_dict` 四键；`_ranking_conf` / `_rank_value` / `_rank_sort_key` / `_apply_presentation` 四个新 helper；`route()` 新增 `grouping_repository_ids` 并把 `group_delta` 透传四条出口；`_stage0_only_result` 新增 `exc_type_name` / `grouping_repository_ids` / `delta` 三个带默认值参数；`_fallback_v1` 新增两个；`_build_snapshot` 新增 `block_order` 键；两处异常文本改走 `redact_secrets_in_text`。
- `server/tests/codegraph/test_repo_router_v2_meta.py` — 新增两节共 15 个用例（呈现字段契约 6 个 + 分组接线 9 个），含 `_install_stage0` 轻量 seam 与 `_cand` 构造 helper。
- `server/tests/codegraph/test_repo_router_v2_degraded.py` — 新增 11 个用例（降级原因 9 个 + 脱敏 3 个，其中一个既覆盖快照又覆盖 meta），含 `_APIConnectionError` 类型名替身与 `_install_no_model` seam。

## Decisions Made

- **排序键抽成模块级 `_rank_sort_key`**：plan 允许「局部 key 函数或模块级 `_sort_key`」二选一。取模块级是因为组内排序与并集后全局排序两处共用，且「只声明一次」这件事能被行首锚定的静态断言核验。
- **`_stage0_only_result` 先按全部 Stage 0 候选定稿再交呈现层截断**：分组启用时要按组各取 `top_k`，若沿用 `_finalize_stage0(stage0_candidates, top_k)` 先截到 3，`global` 组会几乎恒空——正是 D-1 要避免的「上线即无信息量」。`_deterministic_confidence` 只依赖候选在 Stage 0 分数序列里的位次，与此处截断上限无关，故 confidence 口径零变化（既有降级用例全绿佐证）。
- **`classify_degrade_reason` 的调用点收在结果构造处（2 处）而非每个 `skipped_reason` 产出点（6 处）**：内部 `skipped_reason` 字符串因此保持逐字不变，快照/排障口径不破；同时避免 6 处各写一遍映射。
- **`stage1_meta` 的 `degrade_reason` 由 `_stage0_only_result` 合并写入**：一次分类同时喂结果字段与快照 `stage1` 节，两者恒等；`except` 分支只负责把 `error_redacted` 放进 meta。
- **无分组上下文时不重排候选**：Stage 1 成功路径的候选顺序是 LLM 排列（刻意的），现阶段 `score_ranked` 恒为 `None`，若此时按 `_rank_value` 排序会把 LLM 重排整体丢弃回 Stage 0 分数序。plan 的「无上下文时行为逐字不变（`[:top_k]`）」正是这个理由，实现严格照做。
- **脱敏机制断言改用 `structlog.testing.capture_logs`**：首轮用 `caplog` 断言不可行（structlog 事件不进 stdlib handler，`caplog.text` 为空），且即便可行也会被全局 `redact_credentials` processor 骗过——RED 阶段用 `capture_logs` 拿到的事件字典里 `sk-ant-` 明文清晰可见，证明源头确有缺口而非只是兜底生效。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] plan 的比较键表达式用了不存在的属性名 `c.repository_id`**
- **Found during:** Task 2（`_apply_presentation` 排序键实现）
- **Issue:** plan 的 action 步骤 3 与 acceptance criteria 把稳定排序的第二键写成 `c.repository_id`，但 `RepoRouteCandidateV2` 的字段名是 `repo_id`（`repository_id` 只存在于 Qdrant payload 与 `_stage0_candidates` 的中间 dict 里）。照抄会直接 `AttributeError`。
- **Fix:** 第二键取 `candidate.repo_id`——语义与 plan 一致（不可变 id，不用 name/path，ROUTING-RANKING §6.2 第 4 条）。
- **Files modified:** server/codegraph/services/repo_router_v2.py
- **Verification:** `test_presentation_per_group_top_k_and_global_descending` 断言并集后顺序，`tests/codegraph` 全量绿
- **Committed in:** `21c1ab9e`（Task 2 GREEN 提交）

**2. [Rule 1 - Bug] plan 的 `auto_selected` 用例构造在 `decide_block_order` 规则下自相矛盾**
- **Found during:** Task 2（behavior 第 7 条落测试）
- **Issue:** plan 要求构造「global 组置顶且其首位 confidence=medium，而全局最高分候选在 in_project 且 confidence=high」。但 `decide_block_order` 只在 `global_top - in_project_top >= delta` 时置顶 global——此时全局最高分必然在 global 组，「global 置顶」与「全局最高分在 in_project」不可同时成立，照抄写不出用例。
- **Fix:** 改成等价且可构造的机制断言，且拆成两条：（a）`test_presentation_flat_top_is_global_max_regardless_of_block_order` —— 分差 0.10 < delta=0.15 时 `block_order[0] == "in_project"`，而扁平首位是全局最高分的**跨组**候选（即置顶组与扁平首位所属组确实不同）；（b）`test_auto_selected_is_independent_of_block_order` —— 同一输入以三种分组上下文调用产出三种 `block_order`，`auto_selected` 恒为 `True` 且恒由扁平首位驱动。两条合起来覆盖 plan 的原意「呈现层置顶不得影响编排是否自动推进」，断言强度未放宽。
- **Files modified:** server/tests/codegraph/test_repo_router_v2_meta.py
- **Verification:** 两条用例独立命名且绿（plan 要求「必须独立命名便于门禁定位」）
- **Committed in:** `86c585ec`（RED）/ `21c1ab9e`（GREEN）

**3. [Rule 2 - Missing Critical] 归零断言口径下的注释措辞规避**
- **Found during:** Task 2 / Task 3
- **Issue:** plan 要求写「in-domain boost 禁令」与「`str(exc)[:200]` 不是脱敏」两处因果说明，但同 task 的归零断言分别对 `boost` 与 `str\(exc\)\[:200\]` 取 `rg -c ... = "0"`。docstring 不是 `#` 注释行，滤注释也滤不掉，写在 docstring 里会让自己的验收必红。
- **Fix:** 把两处说明改写为 `#` 注释行（可被 `rg -v '^[[:space:]]*#'` 滤除）并改用「in-domain 加分禁令」「截断只是限长，不是脱敏」的措辞避开被禁字面量。断言与因果说明都保留，未放宽也未删除任何断言。
- **Files modified:** server/codegraph/services/repo_router_v2.py
- **Verification:** `rg -v '^[[:space:]]*#' ... | rg -c 'score \+=|score \* 1\.|boost'` = 0；`rg -c 'str\(exc\)\[:200\]'` = 0
- **Committed in:** `21c1ab9e` / `96fdd14e`

---

**Total deviations:** 3 auto-fixed（2 个 plan 文本 bug、1 个断言口径调整）
**Impact on plan:** 均未改变 plan 语义或放宽任何验收断言；两处 plan 文本 bug 若照抄会直接报错或写不出用例。无 scope creep。

## Issues Encountered

- **`caplog` 抓不到 structlog 事件**：首版脱敏测试用 `caplog.text` 断言，实测 `caplog.text` 为空串（structlog 事件不经 stdlib handler 传播到 pytest 的 capture）。改用 `structlog.testing.capture_logs` 后拿到结构化事件列表，顺带获得更强的性质——它绕过全局 `redact_credentials` processor，断言的是**源头脱敏**而非兜底脱敏。
- **`ruff format` 的既存偏差**：`repo_router_v2.py` 与两个测试文件都有若干本 plan 之前就存在的可合并换行（窄包裹风格）。按 scope boundary 未修；本 plan 新增的行本身 `ruff format` 干净（新写的三处被 ruff 判定应合并的行已按 ruff 输出调整），`ruff check` 全绿。
- **首版 `common.logging` import 位置触发 I001**：ruff isort 要求 `common` 排在 `codegraph` 之后，移到 `repo_router_scoring` import 块之后即通过。

## User Setup Required

None — 三个参数（delta / α / K）在 107-01 已有代码内默认值，本 plan 未新增任何配置项；`grouping_repository_ids` 默认 `None`，既有部署行为零变化。

## Next Phase Readiness

- **107-05（Stage 1 有界重排）** 可直接把 `blend_ranked_scores` 结果写进 `score_ranked`：排序与置顶判据全部经 `_rank_value` / `_rank_sort_key`，写完即自动生效；**不得**再声明任何等价取值或排序（WARNING 3，静态断言已锁定 `_rank_value` 定义唯一性）。
- **107-06 / 107-09（前端）** 可消费 `block_order`（`len == 2` 即启用分组呈现）、候选的 `group` / `trust`、以及 6 值 `degrade_reason`；`cross_group_note` 是后端留痕，前端一律用前端常量渲染文案（T-107-06 契约已写进字段注释）。
- **107-07（改编排与 chat 两个入口）** 是唯一有实际回归风险的 plan：本 plan 未改任何入口，候选构成与可见性面零变化；该 plan 传入 `grouping_repository_ids` 后候选数会从 `top_k` 变为 `<= 2*top_k`，需按 plan 约定配回归守护。
- **107-08（`RepositoryRoutingTrace.degrade_reason` 迁移）** 可直接消费 router 侧已产出的 6 值枚举与快照 `stage1.degrade_reason` / `stage1.error_redacted`。
- 无阻塞项。

## Self-Check: PASSED

- 三个改动文件均在磁盘且改动已提交：`repo_router_v2.py` / `test_repo_router_v2_meta.py` / `test_repo_router_v2_degraded.py`
- 六个 task 提交均在 git 历史：`180f3d28` / `78942764` / `86c585ec` / `21c1ab9e` / `3cf1ad0e` / `96fdd14e`
- `repo_router_scoring.py` 与 `golden_baseline.json` 未出现在任何提交的改动清单中（`git diff --stat HEAD~6 HEAD` 仅 3 个文件）
- `STATE.md` / `ROADMAP.md` 未被本 plan 修改

---
*Phase: 107-layered-presentation*
*Completed: 2026-07-30*
