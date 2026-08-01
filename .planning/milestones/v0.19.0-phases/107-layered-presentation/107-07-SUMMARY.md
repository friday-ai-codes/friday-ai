---
phase: 107-layered-presentation
plan: 07
subsystem: api
tags: [repo-router, grouping, repo-association, space-repositories, pydantic-additive, process-runtime, chat-tool]

# Dependency graph
requires:
  - phase: 107-layered-presentation
    provides: "107-03 的 grouping_repository_ids 正交参数、annotate_groups/decide_block_order 接线、候选 group/trust/cross_group_note/score_ranked 与结果 block_order/degrade_reason；107-05 的凸组合写 score_ranked 与 _rank_value 唯一排序所有者"
  - phase: 88-repo-association
    provides: "RepoAssociationService.get_verified_associations（status=verified 的只读输出契约）"
  - phase: 105-golden-set
    provides: "degraded / router_version / 快照材料 / breakdown 透传链（chat 链 pydantic → RepositoryRoutingTrace 的同一条路）"
provides:
  - "aresolve_grouping_repo_ids：「本项目关联仓」宽口径并集（Space.repositories ∪ Project 下 verified 关联）的唯一可单测解析入口，by work_item_id / by space_id 两个门"
  - "None（无项目上下文）与空 frozenset（有上下文零关联仓）的语义分离——直接决定 block_order 是长度 2 还是 ['global']"
  - "编排入口 D-1 落地：repository_ids 收窄为仅 include_repos 显式限定，项目关联仓改走 grouping_repository_ids"
  - "chat 入口 D-1 落地：repository_ids=None 全库召回 + grouping_repository_ids=<空间关联仓>；跨组候选用 repo_name 兜底不再被映射阶段丢弃"
  - "编排精简 dict 补 group/trust；结果 dict 补 block_order/degrade_reason"
  - "RepositoryRelevanceCandidate 的 group/trust/score_ranked 三字段（经 model_dump 进 RepositoryRoutingTrace.candidates JSON）"
affects: [107-08, 107-09, 109, 110]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "「无上下文」与「空上下文」必须是两个不同的返回值：None 表调用方没有项目上下文，空集合表有上下文但零关联仓——合并成一个值就等于把 block_order 的形状判断交给了猜测"
    - "并集的可选半边整块 try/except 降级：verified 关联查询失败只丢一半分组依据，不该让整个分组呈现消失"
    - "硬过滤与分组依据正交后，硬过滤语义保留给显式调用方（include_repos），不做全局放开"
    - "全库召回的必然结果：id→对象查表在跨组候选上必然 miss，此处必须兜底而不是 continue（否则等于在映射阶段重新实现硬过滤）"
    - "分层倒置的规避方式：codegraph 需要 initiatives/workflows 的解析规则时，在本模块内实现最小等价查询并在注释里写明为何不复用"

key-files:
  created:
    - server/codegraph/services/repo_group_scope.py
    - server/tests/codegraph/test_repo_group_scope.py
  modified:
    - server/services/process_runtime/repo_router_adapter.py
    - server/agents/tools/repository_relevance.py
    - server/agents/tools/schemas/repository_relevance.py
    - server/tests/services/test_repo_router_adapter.py
    - server/tests/agents/test_repository_relevance_tool.py

key-decisions:
  - "分组依据不做 index_status 过滤：分组是「归属」语义，未索引的仓同样属于本项目；候选本身只可能来自已索引的仓，故过滤与否对结果无影响、不过滤语义更干净"
  - "Space→Project 解析在本模块内重写最小等价查询而非复用：复用 board_split_review._aresolve_project 会让 codegraph 反向依赖 workflows（分层倒置），复用 RepoAssociationService._aresolve_project 是私有方法；规则变更时三处需同步（已写进注释）"
  - "编排入口的 grouping 返回 sorted(list) 而非 frozenset：快照/回放需要确定性的参数序列"
  - "chat 入口的 legacy HybridSearch 路径保留空间内 repository_ids 限定：D-1 只裁决 v2 路由的候选范围，legacy 聚合是另一条召回链，本 plan 不动"
  - "不加 cross_group_note 到 chat 链：UI-SPEC 的 T-107-06 明确前端只渲染前端常量、不渲染后端自由文本，留痕留在 router 侧即可（少一个字段少一条泄漏面）"

patterns-established:
  - "分组语义的正向断言用真实 _apply_presentation 做替身：手写 group 值的替身只能证明自己，用真实分组函数 + 尊重 repository_ids 的替身才能让「global 分区非空」真正检出 Pitfall 2（旧语义下正确仓被替身的硬过滤同样挡在池外）"
  - "语义变更的断言迁移要留档：被改写的断言在测试文件 docstring 里点名旧用例名与它锁定的旧语义，避免后人把改写当成放宽"

requirements-completed: [ROUTE-01, ROUTE-02]

coverage:
  - id: D1
    description: "「本项目关联仓」= Space.repositories ∪ 该项目 verified 关联的宽口径并集（D-2），有唯一可单测入口，两个门（work_item_id / space_id）"
    requirement: "ROUTE-01"
    verification:
      - kind: integration
        ref: "tests/codegraph/test_repo_group_scope.py#test_work_item_returns_union_of_space_and_verified"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_group_scope.py#test_union_deduplicates_repo_present_in_both_halves"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_group_scope.py#test_space_id_entry_returns_union"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_group_scope.py#test_work_item_id_takes_precedence_over_space_id"
        status: pass
    human_judgment: false
  - id: D2
    description: "None（无项目上下文）与空 frozenset（有上下文零关联仓）语义分离；无 Project / 无 space / 主键不存在均优雅退化不抛"
    requirement: "ROUTE-01"
    verification:
      - kind: integration
        ref: "tests/codegraph/test_repo_group_scope.py#test_missing_work_item_returns_none"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_group_scope.py#test_work_item_without_space_returns_none"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_group_scope.py#test_missing_space_returns_none"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_group_scope.py#test_space_with_zero_repositories_returns_empty_frozenset"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_group_scope.py#test_space_without_project_returns_space_repositories"
        status: pass
    human_judgment: false
  - id: D3
    description: "并集的 verified 半边失败即降级为只返回 space 半边，不抛；返回值为 frozenset[str]（id 归一）"
    verification:
      - kind: integration
        ref: "tests/codegraph/test_repo_group_scope.py#test_verified_query_failure_degrades_to_space_half"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_group_scope.py#test_result_is_frozenset_of_str_ids"
        status: pass
      - kind: other
        ref: "rg -c 'sync_to_async' codegraph/services/repo_group_scope.py == 5（!= 0，async ORM 纪律）"
        status: pass
    human_judgment: false
  - id: D4
    description: "编排入口 D-1：项目关联仓改走 grouping_repository_ids、repository_ids 放开为 None；include_repos 显式限定时硬过滤语义保留且与分组依据正交；无 work_item 时两者均 None 不抛"
    requirement: "ROUTE-01"
    verification:
      - kind: integration
        ref: "tests/services/test_repo_router_adapter.py#test_scope_project_repos_become_grouping_not_filter"
        status: pass
      - kind: integration
        ref: "tests/services/test_repo_router_adapter.py#test_include_repos_keeps_hard_filter_alongside_grouping"
        status: pass
      - kind: integration
        ref: "tests/services/test_repo_router_adapter.py#test_scope_no_work_item_full_repo"
        status: pass
    human_judgment: false
  - id: D5
    description: "global 分区不再恒空（Pitfall 2 的唯一检出手段）：正确仓在项目关联范围之外时结果含 group == 'global' 候选，block_order 长度 2 且全局组置顶"
    requirement: "ROUTE-02"
    verification:
      - kind: integration
        ref: "tests/services/test_repo_router_adapter.py#test_global_group_is_not_empty_when_best_repo_is_outside_project"
        status: pass
    human_judgment: false
  - id: D6
    description: "chat 入口 D-1：repository_ids=None + grouping_repository_ids=<空间关联仓>；跨组候选不被映射阶段丢弃（用候选自带 repo_name 兜底）"
    requirement: "ROUTE-01"
    verification:
      - kind: integration
        ref: "tests/agents/test_repository_relevance_tool.py#test_v2_route_receives_grouping_not_hard_filter"
        status: pass
      - kind: integration
        ref: "tests/agents/test_repository_relevance_tool.py#test_v2_cross_group_candidate_is_not_dropped_in_mapping"
        status: pass
      - kind: other
        ref: "rg -n 'repo_by_id.get' -A 3 agents/tools/repository_relevance.py | 滤注释行 | rg -c 'continue' == 0"
        status: pass
    human_judgment: false
  - id: D7
    description: "其余 6 个 RepoRouterV2.route() 调用方零改动（静态可验证）；无项目上下文入口（MCP / REST）的调用形状仍是全 global + block_order == ['global']、不报错"
    verification:
      - kind: other
        ref: "rg -c 'grouping_repository_ids' space_tools.py repo_association_service.py artifact.py skill_steps.py mcp_tools/views.py route_views.py == 0"
        status: pass
      - kind: integration
        ref: "tests/services/test_repo_router_adapter.py#test_no_project_context_all_global_single_block"
        status: pass
    human_judgment: false
  - id: D8
    description: "chat 链候选携带 group / trust / score_ranked（全部带默认值），逐跳透传到 RepositoryRoutingTrace.candidates JSON；score_ranked 为 None 时原样输出 None；Input schema fixture 未动"
    requirement: "ROUTE-02"
    verification:
      - kind: unit
        ref: "tests/agents/test_repository_relevance_tool.py#test_presentation_fields_default_to_empty_and_none"
        status: pass
      - kind: unit
        ref: "tests/agents/test_repository_relevance_tool.py#test_model_dump_key_set_includes_presentation_fields"
        status: pass
      - kind: unit
        ref: "tests/agents/test_repository_relevance_tool.py#test_model_dump_keeps_score_ranked_none_as_none"
        status: pass
      - kind: integration
        ref: "tests/agents/test_repository_relevance_tool.py#test_v2_presentation_fields_mapped_to_pydantic_candidate"
        status: pass
      - kind: integration
        ref: "tests/agents/test_repository_relevance_tool.py#test_trace_candidates_json_carries_presentation_fields"
        status: pass
      - kind: integration
        ref: "tests/agents/test_repository_relevance_tool.py#test_input_schema_snapshot"
        status: pass
      - kind: other
        ref: "git diff --name-only 不含 repository_relevance_input_schema.json；schemas 文件滤注释行后 cross_group_note 计数 == 0"
        status: pass
    human_judgment: false
  - id: D9
    description: "既有回归基线不破：三个既有测试文件改前 31 passed、改后连同新增用例 63 passed（含 tests/agents/test_tool_contracts.py）"
    verification:
      - kind: integration
        ref: "cd server && uv run pytest tests/codegraph/test_repo_group_scope.py tests/services/test_repo_router_adapter.py tests/agents/test_repository_relevance_tool.py tests/agents/test_tool_contracts.py tests/initiatives/test_repo_association_service.py -q → 63 passed"
        status: pass
    human_judgment: false
  - id: D10
    description: "T-107-01（放开硬过滤后结果含项目外仓名）的前提如实记录：沿用两个已上线全库入口的既有判断，不新增可见性面、不绕过任何现存权限检查"
    verification: []
    human_judgment: true
    rationale: "「仓名是否敏感」是团队判断而非可自动断言的性质；前提已写进两处改动的代码注释与本 SUMMARY，需人工确认判断未变（若变则需在 Phase 109/110 补可见性过滤层）"

# Metrics
duration: 17min
completed: 2026-07-30
status: complete
---

# Phase 107 Plan 07: D-1 候选范围语义改造（硬过滤 → 分组依据） Summary

**编排与 chat 两个入口把项目/空间关联仓从 `RepoRouterV2.route(repository_ids=...)` 的硬过滤改为独立的 `grouping_repository_ids` 分组依据（`repository_ids` 放开为全库召回，硬过滤语义完整保留给 `include_repos`），新增 `aresolve_grouping_repo_ids` 承载 D-2 宽口径并集（`Space.repositories` ∪ 该项目 `verified` 关联，`None` 与空集语义分离），chat 链候选补 `group`/`trust`/`score_ranked` 三字段——`global` 分区从此不再恒空，其余 6 个调用方逐字未动。**

## Performance

- **Duration:** 约 17 min
- **Started:** 2026-07-29T23:30:00Z
- **Completed:** 2026-07-29T23:47:00Z
- **Tasks:** 3（全部走 TDD：RED → GREEN，无 REFACTOR 轮）
- **Files created:** 2 / **modified:** 5

## Accomplishments

- **`global` 分区不再恒空，ROUTE-01/02 从「字段就位」变成「用户真能看到两组」。** 编排入口 `_resolve_repository_ids` 删掉「② `work_item.space` 仓」这一级（它正是硬过滤的来源），chat 入口改传 `repository_ids=None`。检出手段是一条正向断言：替身 route **尊重** `repository_ids` 硬过滤并复用**真实** `_apply_presentation` 分组，构造「正确仓（0.95）在项目关联范围之外、项目内只有弱命中（0.40）」的场景后断言结果含 `group == "global"` 候选、`block_order` 长度 2 且 `block_order[0] == "global"`（分差 0.55 >= delta 0.15）。旧语义下该外部仓会被替身的硬过滤挡在候选池外，断言当场变红——这条断言是**可失效的**，不是自证。
- **「本项目关联仓」有了唯一、口径明确的解析入口。** `aresolve_grouping_repo_ids(work_item_id=... | space_id=...)` 返回 `Space.repositories` ∪ 该 Space 下 `Project` 的 `RepoAssociation(status=verified)` 并集（D-2 宽口径）。**`None` 与空 `frozenset` 是两个不同的答案**：前者表「调用方无项目上下文」（`block_order == ["global"]`），后者表「有上下文但该项目零关联仓」（`block_order` 恒长度 2）——两条独立用例分别断言 `is None` 与 `== frozenset()`。
- **并集的可选半边失败只降级、不毁分组。** `verified` 半边整块 `try/except`：monkeypatch `get_verified_associations` 抛异常后仍返回 space 半边（有用例断言），只记一条 `repo_group_scope_verified_half_failed`（sampling，异常文本经 `redact_secrets_in_text`）。
- **跨组候选在 chat 链的第二个丢弃点被堵住。** 全库召回后跨组候选**必然**不在 `repo_by_id`（它只装空间内仓）里，旧写法 `if repo is None: continue` 会让 `global` 分区在映射阶段被重新清空——等于在 Pitfall 2 上再开一个入口。改为用候选自带的 `repo_name` 兜底 `repository_name`，`repo_id` 为空的防御性跳过前移到 `repo_by_id.get` 之前（同时满足验收的窗口归零断言）。
- **硬过滤语义完整保留给需要它的调用方。** `include_repos` 非空时 `repository_ids` 仍为该显式列表，且与 `grouping_repository_ids` 并存（有独立用例断言两者同时非空、语义正交）。
- **其余 6 个调用方逐字未改（静态可验证）。** `space_tools` / `repo_association_service` / `knowledge.sources.artifact` / `skill_steps` / MCP / REST 六处的 `grouping_repository_ids` 计数为 0；无项目上下文的调用形状仍产出全 `global` + `block_order == ["global"]`。
- **分组事实进入 `RepositoryRoutingTrace.candidates`。** `RepositoryRelevanceCandidate` 追加 `group: str = ""` / `trust: str = ""` / `score_ranked: float | None = None`（键名与 UI-SPEC 字面对齐），经既有 `model_dump()` 自动进 trace JSON，无需额外代码；`score_ranked` 为 `None` 时原样输出 `None`（前端据此回退 `score`）。`RepositoryRelevanceInput` 的 schema fixture 未动（fixture 只冻结 Input，Output 加字段不触发该守护）。
- **回归基线未破。** 改前 31 passed（`test_repo_router_adapter.py` + `test_repository_relevance_tool.py` + `test_repo_association_service.py`），改后含新增用例的定向套 63 passed；两条被 D-1 语义变更影响的既有断言逐条记入下方 Deviations。

## α 参与排序的复核结论（107-05 Explicit Scope Boundary 第 1 条）

107-05 记录的边界是「无分组上下文时凸组合不参与排序——`_apply_presentation` 的 `grouping_repository_ids is None` 分支只截断不重排，α 影响顺序的前提是调用方传了分组依据；107-07 会给编排与 chat 两个真实入口接上」。本 plan 接完后实测（构造 `score_ranked` 与 `score` 排序**相反**的两个候选，直接调 `_apply_presentation`）：

| 分组上下文 | 最终顺序 | `block_order` | α 是否参与排序 |
|---|---|---|---|
| `None` | `['rB','rA']`（= 输入的 LLM 排列，原样保留） | `['global']` | **否** |
| `['rA']`（真实并集） | `['rA','rB']`（= 按 `score_ranked` 降序） | `['in_project','global']` | **是** |
| `[]`（空集，有上下文零关联仓） | `['rA','rB']` | `['global','in_project']` | **是** |

据此逐入口结论：

- **chat 入口：α 恒参与排序。** `space_id` 是必填参数且 `Space` 存在性在更早处已校验，故 `aresolve_grouping_repo_ids(space_id=...)` 必返回非 `None`（零关联仓时是空集，同样进排序分支）。
- **编排入口：workflow 发起的会话 α 参与排序**（`session.work_item_id` 能解析出 Space）；**chat 发起的编排（无 `work_item`）α 仍不参与**——`grouping_repository_ids` 为 `None`，顺序仍是裁剪后的 K-有界 LLM 排列。这一半边界**未关闭**，是刻意的（无项目上下文时没有分组事实可用）。
- **其余 6 个调用方：α 仍不参与排序**（它们不传分组依据，`_apply_presentation` 走只截断分支）。
- **降级路径不受影响**：Stage 1 降级时 `score_ranked` 恒 `None`，`_rank_value` 回退 `score`，顺序即 Stage 0 分数序（107-05 的 D9 不回退）。

**由此产生的一个新事实（见下方 Explicit Scope Boundaries 第 1 条）**：`auto_selected = final[0].confidence == "high"` 读扁平列表首位，而 workflow 会话的扁平首位现在由 `score_ranked` 决定而非 LLM 排列首位——即 α 现在**可以**改变 `auto_selected`。这是 D-3/RELY-05 设计的直接后果（凸组合就是要影响最终顺序），不是回归；组别本身依旧不进决策路径（107-03 的 `test_auto_selected_is_independent_of_block_order` 继续绿）。

## Task Commits

1. **Task 1: repo_group_scope 宽口径并集解析（D-2）** — `b99bf31a` (test, RED) → `6e66ae60` (feat, GREEN)
2. **Task 2: D-1 候选范围语义改造（两个入口改传分组依据）** — `e09d3570` (test, RED) → `7e756a8d` (feat, GREEN)
3. **Task 3: chat 链候选字段透传（pydantic Output schema 扩展）** — `8c359a77` (test, RED) → `d0f68b17` (feat, GREEN)

_三个 task 的 REFACTOR 轮均未产生改动（GREEN 实现即最终形态）。_

## Files Created/Modified

- `server/codegraph/services/repo_group_scope.py`（新建，171 行）— `aresolve_grouping_repo_ids` 两门解析 + `_aresolve_space` / `_aspace_repository_ids` / `_aresolve_project` 三个 `sync_to_async` helper + `_log_scope` best-effort 采样事件（`repo_group_scope_resolved`，kv: `source` / `space_repo_count` / `verified_repo_count` / `union_count` / `duration_ms`）。模块 docstring 写明 D-2 裁决理由、`None` 与空集的语义差异、以及「分组依据不做 `index_status` 过滤」的判断。
- `server/tests/codegraph/test_repo_group_scope.py`（新建）— 11 个用例（并集 / 去重 / 无 Project 退化 / `None` 与空集分离 / 两个门 / 半边失败降级 / 类型归一 / 双参优先级），含 `_make_space` / `_make_work_item` / `_make_verified_association` 三个 `sync_to_async` 建数据 helper。
- `server/services/process_runtime/repo_router_adapter.py` — `_resolve_repository_ids` 收窄为「仅 `include_repos`」并写入 D-1 因果与 T-107-01 前提注释；新增 `_resolve_grouping_repository_ids`（返回 `sorted(list)` 保证快照确定性）；删除已无调用方的 `_project_repository_ids`（连带删掉 `sync_to_async` import）；`route()` 传两个正交参数，候选 dict 补 `group`/`trust`，结果 dict 补 `block_order`/`degrade_reason`。
- `server/agents/tools/repository_relevance.py` — v2 路由改传 `repository_ids=None` + `grouping_repository_ids`；`repo_by_id.get` 的 `continue` 改为 `repo_name` 兜底（防御性跳过前移）；候选构造处映射三个呈现字段；两处 D-1 因果与 T-107-01 前提注释。legacy HybridSearch 路径的空间内 `repository_ids` 限定未动。
- `server/agents/tools/schemas/repository_relevance.py` — `RepositoryRelevanceCandidate` 追加三个带默认值字段 + 中文注释（含 D-3 的「徽标与分数分解合计行继续用 `score`」纪律，以及「刻意不加后端留痕说明字段」的设计决定）。
- `server/tests/services/test_repo_router_adapter.py` — 改写 1 条既有用例、调整 2 条候选键断言、新增 3 条用例（`include_repos` 硬过滤保留 / global 分区非空 / 无项目上下文单分区），新增 `_presentation_aware_route` 替身工厂；文件 docstring 点名被改写的旧用例与它锁定的旧语义。
- `server/tests/agents/test_repository_relevance_tool.py` — 新增 7 条用例（D-1 两条 + 呈现字段透传五条），含 `_bare_candidate` / `_make_v2_result_with_presentation` 两个 helper。

## Decisions Made

- **分组依据不做 `index_status` 过滤**：分组是「归属」语义，未索引的仓同样属于本项目；而候选本身只可能来自已索引的仓，故过滤与否对结果无影响、不过滤语义更干净（写进模块 docstring）。
- **`Space → Project` 解析在本模块内重写最小等价查询**：复用 `board_split_review._aresolve_project` 会让 `codegraph` 反向依赖 `workflows`（分层倒置），复用 `RepoAssociationService._aresolve_project` 是私有方法。规则（优先 `feishu_project_key` 命中、否则首个）现在有三份，注释里写明变更需三处同步。
- **编排入口的分组依据返回 `sorted(list)`**：`aresolve_grouping_repo_ids` 返回 `frozenset`（集合语义正确），但传给 `route()` 前排序——快照/回放需要确定性的参数序列。
- **chat 入口的 legacy HybridSearch 路径保留空间内限定**：D-1 裁决的是 v2 路由的候选范围；legacy 聚合是另一条召回链（只在 v2 不可用时走），本 plan 不动它，避免把回归面从「v2 候选构成」扩大到「legacy 召回构成」。
- **不加 `cross_group_note` 到 chat 链**：UI-SPEC 的 T-107-06 明确前端只渲染前端常量、不渲染后端自由文本；该留痕留在 router 侧即可，少一个字段少一条泄漏面（该设计决定写成 `#` 注释行，以免命中同 task 的归零断言——本 phase 的既定口径）。
- **「global 分区非空」的替身用真实 `_apply_presentation`**：手写 `group` 值的替身只能证明自己。让替身**尊重** `repository_ids` 硬过滤并调用真实分组函数，旧语义下正确仓会被替身滤掉、断言当场变红——这条断言因此是可失效的检出手段而非装饰。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 两条既有断言逐字锁定了 D-1 明确放弃的旧语义，必须改写**

- **Found during:** Task 2（编排入口改造）
- **Issue:** `tests/services/test_repo_router_adapter.py` 的两处断言与 D-1 直接冲突：
  1. `test_scope_project_repos_fallback` 断言 `mock_route.await_args.kwargs["repository_ids"] == [repo_id]`（原文档串「无 include_repos 时回退 work_item.space 仓库 id 列表」）——它锁定的正是「空间内仓当硬过滤」这一被 D-1 放弃的语义。
  2. `test_maps_router_result` 与 `test_adapter_dict_carries_degraded_and_snapshot` 断言候选精简 dict **恰等于**三键字典（`== {"repo_id", "confidence", "repository_name"}`），而 plan action 步骤 1 要求补 `group`/`trust` 两键。
- **Fix:** (1) 改写为 `test_scope_project_repos_become_grouping_not_filter`——断言 `repository_ids is None` **且** `grouping_repository_ids == [repo_id]`，并在文件 docstring 点名旧用例名与它锁定的旧语义（避免后人把改写当成放宽）。(2) 两处改为「三个既有键**逐个**断言值不变 + `set(cand) == 五键`」——既有键的语义与值一字未改（下游 clarify/research/feature_confirm 只读 `confidence`），只是从「恰三键」放宽到「恰五键」，仍是精确集合断言而非 `<=` 包含断言，强度未降。
- **为何是预期：** D-1 就是要改变这两条断言描述的行为；不改这两条就无法兑现 ROUTE-01/02（且**不得**为让测试过而回退 D-1）。
- **Files modified:** server/tests/services/test_repo_router_adapter.py
- **Verification:** 改后定向套 63 passed；新增 `test_global_group_is_not_empty_when_best_repo_is_outside_project` 正向证明新语义生效
- **Committed in:** `e09d3570`（RED）/ `7e756a8d`（GREEN）

**2. [Rule 3 - Blocking] `_project_repository_ids` 与 `sync_to_async` import 成为死代码**

- **Found during:** Task 2（`_resolve_repository_ids` 收窄）
- **Issue:** 删掉「② `work_item.space` 仓」一级后，`_project_repository_ids` 唯一调用方消失；连带 `sync_to_async` 顶层 import 变成未使用（`ruff` F401 会红）。
- **Fix:** 一并删除该方法与 import。归属查询的等价能力已由 `repo_group_scope._aspace_repository_ids` 承载（且口径更宽——含 verified 半边），不存在能力丢失。
- **Files modified:** server/services/process_runtime/repo_router_adapter.py
- **Verification:** `uv run ruff check services/process_runtime/repo_router_adapter.py` 全绿；无任何测试引用该私有方法
- **Committed in:** `7e756a8d`

**3. [Rule 2 - Missing Critical] `repo_id` 为空的防御性跳过必须前移到 `repo_by_id.get` 之前**

- **Found during:** Task 2（chat 入口映射改造）
- **Issue:** plan 要求「仍保留对 `repo_id` 为空的防御性跳过」，但该跳过若写在 `repo_by_id.get` **之后**，验收的窗口归零断言（`rg -n 'repo_by_id.get' -A 3 | 滤注释行 | rg -c 'continue' == 0`）会必红；而放宽断言等于放弃对「旧写法回归」的守护。
- **Fix:** `if not c.repo_id: continue` 前移到 `repo = repo_by_id.get(...)` 之前（语义等价——空 id 无论如何都映射不出候选），因果注释三行紧跟 `.get` 之后并全部写成 `#` 注释行（可被滤除），措辞刻意避开 `continue` 字面量（用「查不到就丢弃」表述）。断言与因果说明都保留，未放宽也未删除任何断言。
- **Files modified:** server/agents/tools/repository_relevance.py
- **Verification:** 窗口断言实测为 `0`；`test_v2_cross_group_candidate_is_not_dropped_in_mapping` 绿
- **Committed in:** `7e756a8d`

---

**Total deviations:** 3 auto-fixed（1 个 plan 与既有测试的语义冲突、1 个 blocking 死代码、1 个断言口径下的实现顺序调整）
**Impact on plan:** 第 1 条是 D-1 的必然结果（plan 已预告「若某条断言本质上锁定了旧语义 → 调整并逐条记录，不得回退 D-1」），断言强度未降；第 2、3 条分别是收窄改动的连带清理与归零断言纪律下的实现顺序选择。无 scope creep：`repo_router_v2.py` / `repo_router_scoring.py` / `golden_baseline.json` / 六个未改调用方均未出现在任何提交的改动清单中。

## Explicit Scope Boundaries

- **`auto_selected` 现在可被 α 改变（workflow 会话）。** `auto_selected = bool(final) and final[0].confidence == "high"` 读扁平列表首位；接上分组上下文后 workflow 会话的扁平首位由 `score_ranked` 决定而非 LLM 排列首位，故凸组合可以改变 `auto_selected`。这是 D-3/RELY-05 的设计意图（凸组合就是要影响最终顺序），不是回归；组别本身依旧不进决策路径（107-03 的 `test_auto_selected_is_independent_of_block_order` 继续绿）。下游 clarify policy 判定「候选无任一 confidence ∈ {high, medium}」在候选变多（`<= top_k` → `<= 2*top_k`）时更容易满足「有 confident 候选」→ 澄清触发变少，方向与本里程碑目标一致。
- **chat 工具的 `[:top_k]` 后截断可能整组截掉 `in_project`。** router 现在按组各取 `top_k` 后并集（长度 `<= 2*top_k`），而 `_analyze_relevance_core` 沿用既有的 `v2_candidates[:top_k]`——若前 `top_k` 个全局最优候选都在 `global` 组，`in_project` 组会在工具输出层被整组截掉（前端因此看不到本项目分区）。**本 plan 刻意不改**：`top_k` 是 LLM 可见的公开参数（"返回的相关仓库数量上限"），把返回上限悄悄改成 `2*top_k` 会单方面变更工具契约与 `total_candidates` 语义。留给 **107-08 / 107-09** 裁决（可选方案：按组各留配额后截断，或在 trace 里同时落 `block_order` 让前端知道某组被截）。
- **chat 链的 legacy HybridSearch 路径未接分组**：只在 v2 不可用时走，其候选仍限定空间内仓、`group`/`trust` 为空串（前端按缺省视为 `global`）。历史 trace 同理——UI-SPEC 已把「无这些字段时逐像素一致」列为验收项。
- **`RepositoryRoutingTrace` 的 `degraded` / `block_order` / `degrade_reason` 三个**结果级**字段本 plan 未落**（该表无对应列）：本 plan 只把**候选级**字段送进 `candidates` JSON。表结构迁移是 107-08 的范围。
- **V4 Access Control 未触碰**：`chat/views.py:2688`/`:2702` 的跨用户 / 跨项目 override 校验一行未改。

## Issues Encountered

- **`ruff` 的 isort 首方判定随文件存在与否翻转。** Task 1 的 RED 阶段 `codegraph.services.repo_group_scope` 还不存在，`ruff` 把 `codegraph` 判为第三方并要求与 `pytest` 同组（`--fix` 会删掉分组空行）；GREEN 落完模块后它又变回首方、要求独立分组。结论：RED 阶段不要为 import 分组与 `ruff` 较劲，GREEN 之后再跑一次 `ruff check --fix` 即收敛。
- **`tests/agents/test_repository_relevance_tool.py` 有两条先于本 plan 的 `ruff` 报错**（`unittest.mock.patch` 未使用的 F401 + 该文件的 I001）。已用 `git show HEAD:...` 对原文件跑 `ruff check --stdin-filename` 确认二者在本 plan 之前即存在，按 scope boundary 未修；本 plan 新增的行本身干净，且该文件不在任何 task 的 `ruff` 验收清单内（验收清单只列源文件 + Task 1 的两个文件）。
- **RED 阶段有一条用例即为绿**：`test_no_project_context_all_global_single_block` 守护的是 107-03 已交付的「无分组上下文 → 全 `global` + `block_order == ["global"]`」这一既有事实（对应 plan behavior 第 8 条中 MCP / REST 的降级路径），性质是回归守护而非新行为，故不视为 RED 失效。

## T-107-01 前提（显式记录，必须人工复核）

放开 `repository_ids` 硬过滤后 Stage 0 走全库召回，结果里**会**出现用户所在项目之外的仓名。本 plan 沿用团队既有判断「仓名不敏感」，依据是两个**已上线**入口本来就全库路由且无任何 per-user 可见性过滤：

- `server/mcp_tools/views.py:434`（`RouteRepositoriesView`）：`RepoRouterV2.route(query, top_k=top_k)`
- `server/repositories/route_views.py:39`（`POST /api/repositories/route/`）：同上

`_stage0_node_search` 侧不存在按用户过滤的机制，故「放开 Space 硬过滤」**不绕过任何现存权限检查、不新增可见性面**。该前提已写进 `repo_router_adapter._resolve_repository_ids` 与 `repository_relevance` v2 分支两处代码注释。**若团队判断改变，需在 Phase 109/110 补可见性过滤层**（本 plan 的 disposition 是 accept，不是 mitigate）。

## User Setup Required

None — 零新增配置项、零新增依赖。既有部署升级后的行为变化仅限：编排（有 work_item 的会话）与 chat 两个入口的路由候选从「空间内仓」变为「全库 + 分组标注」，候选数上限从 `top_k` 变为 `<= 2*top_k`（chat 工具输出层仍截到 `top_k`）。

## Next Phase Readiness

- **107-08（`RepositoryRoutingTrace` 迁移）** 可直接消费本 plan 已落的候选级 `group` / `trust` / `score_ranked`；仍需自行加 `degraded` / `degrade_reason` / `block_order` 三个结果级列（`repo_router_adapter` 的结果 dict 已备好后两个键，`_h_route` 侧的 payload 组装未改，需 107-08 接线）。同时请裁决上文 Explicit Scope Boundaries 第 2 条（`[:top_k]` 可能整组截掉 `in_project`）。
- **107-09（前端）** 消费 `block_order?.length === 2` 启用分区、区内按 `score_ranked ?? score` 降序；本 plan 已确认后端在两个真实入口都产出非退化的 `block_order`，且 `score_ranked` 恒为「`None` 或凸组合值」（无 `0.0` 伪装）。
- **Phase 109（编排产出直连执行流）** 注意 `auto_selected` 现在受 α 影响（见 Explicit Scope Boundaries 第 1 条）。
- 无阻塞项。

## Self-Check: PASSED

- 七个改动/新建文件均在磁盘：`repo_group_scope.py` / `test_repo_group_scope.py` / `repo_router_adapter.py` / `repository_relevance.py` / `schemas/repository_relevance.py` / `test_repo_router_adapter.py` / `test_repository_relevance_tool.py`
- 六个 task 提交均在 git 历史：`b99bf31a` / `6e66ae60` / `e09d3570` / `7e756a8d` / `8c359a77` / `d0f68b17`
- `git diff --stat HEAD~6 HEAD` 恰 7 个文件；`repo_router_v2.py` / `repo_router_scoring.py` / `golden_baseline.json` / 六个未改调用方 / `repository_relevance_input_schema.json` 均未出现
- `STATE.md` / `ROADMAP.md` 未被本 plan 修改（`git diff --name-only HEAD~6 HEAD` 无命中）
- 全部 task 的 `<acceptance_criteria>` 已逐条执行并 PASS（含三条归零/窗口断言与四个文件的 `ruff check`）；plan 级定向套 63 passed
- 无 stub / 无占位实现：三个 task 的行为由 18 条新用例 + 1 条改写用例覆盖

---
*Phase: 107-layered-presentation*
*Completed: 2026-07-30*
