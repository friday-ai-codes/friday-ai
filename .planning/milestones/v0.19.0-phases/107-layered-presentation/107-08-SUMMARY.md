---
phase: 107-layered-presentation
plan: 08
subsystem: api
tags: [routing-trace, migration, additive-column, degrade-reason, block-order, manual-override, api-contract, chat-tool]

# Dependency graph
requires:
  - phase: 107-layered-presentation
    provides: "107-03 的 RepoRouteResultV2.block_order / degrade_reason 结果级字段与 classify_degrade_reason 的 6 值闭集；107-07 的候选级 group/trust/score_ranked 透传链与 chat 入口分组接线"
  - phase: 105-golden-set
    provides: "RepositoryRoutingTrace.router_version 列（v2 / v2_stage0_only / v1_fallback / legacy_hybrid 取值域）"
provides:
  - "RepositoryRoutingTrace.degrade_reason（CharField(32)，6 值闭集 ∪ \"\"，可 SQL 聚合降级原因分布）"
  - "RepositoryRoutingTrace.block_order（JSONField(default=list)，呈现层区顺序，长度 2 = 有项目上下文）"
  - "写入侧接线：chat 工具 v2 路径的 trace 落库真的写这两列（值只来自 router 结果）"
  - "会话 detail 的 routing_trace payload 9 键契约（补 router_version / degraded / degrade_reason / block_order）"
  - "_derive_degraded：degraded 的后端唯一派生点，detail 与 manual override 两处 payload 共用"
  - "manual override 新 trace 继承三列且响应回传 4 键（Pitfall 3 后端半边闭合）"
affects: [107-09, 109, 110]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "受控枚举落单列而非塞 JSON：能当指标维度 SQL 聚合，且列长本身就是「装不下自由文本」的形状约束（脱敏的第二道防线）"
    - "可派生的事实不加列：degraded 由 router_version 在后端派生，既满足「前端不推断」的契约，又避免与既有列冗余 + 历史行回填"
    - "派生点唯一化 + 计数断言守护：两处 payload 共用一个 helper，并用「代码行计数 == 1」断言禁止别处再写等价字面判定"
    - "写入侧断言必须走真实调用路径：只测模型与 payload 时，写入侧漏填会让全套测试保持全绿而生产列恒为默认值"
    - "override 类「写新行」语义必须显式继承事实列：列默认值（legacy_hybrid）会在不继承时把「降级过」静默改写成「没降级过」"

key-files:
  created:
    - server/chat/migrations/0032_repositoryroutingtrace_degrade_reason.py
  modified:
    - server/chat/models.py
    - server/chat/views.py
    - server/agents/tools/repository_relevance.py
    - server/tests/chat/test_repository_routing_trace_model.py
    - server/tests/chat/test_routing_trace_manual_override_view.py
    - server/tests/agents/test_repository_relevance_tool.py

key-decisions:
  - "degrade_reason 加列而非塞 candidates JSON：candidates 是 list，结果级事实塞不进外层；单列可直接 SQL 聚合「降级原因分布」，迁移开销是一条 additive AddField"
  - "degraded 不加列、由后端派生（router_version ∈ {v2_stage0_only, v1_fallback}）：CONTEXT 只要求「前端不自行推断」，推断放后端即满足；加列则与 router_version 冗余且需回填历史行"
  - "legacy_hybrid 不算降级：它是 router_version 的列默认值，算作降级会让全部历史 trace 突然出现降级横幅（UI-SPEC backstop 1）"
  - "chat 工具 [:top_k] 后截断保留不改（107-07 遗留边界的裁决）：top_k 是 LLM 可见公开参数，返回上限改成 2*top_k 会单方面变更工具契约与 total_candidates 语义；block_order 取自 router 结果而非截断后的候选列表，故「有项目上下文 → 长度恒 2」在 API 边界仍成立"
  - "override 新 trace 显式继承 router_version / degrade_reason / block_order：同一次路由的事实不因用户改勾选而改变；不继承则退化成列默认值 legacy_hybrid，降级横幅在勾选后消失"
  - "顺带修三个测试文件先于本 plan 的 ruff import 报错：plan 级 <verification> 的 ruff 清单包含这三个文件，不修则该命令永远非零退出"

patterns-established:
  - "写入侧接线用「!= 列默认值」+「== router 结果值」两段断言：前者专门检出「漏填」这类会让其余测试全绿的缺陷，后者锁定值的来源"
  - "跨 task 边界的计数断言落在最后写入的那个 task：_derive_degraded 的 >= 2（Task 2）→ >= 3（Task 3），否则断言在提交时恒假"

requirements-completed: [RELY-03, ROUTE-01, ROUTE-02]

coverage:
  - id: D1
    description: "degrade_reason / block_order 两列落地：additive、零回填、默认值等价历史行、列长 32 装不下异常原文"
    requirement: "RELY-03"
    verification:
      - kind: unit
        ref: "tests/chat/test_repository_routing_trace_model.py#test_degrade_reason_and_block_order_default_to_empty"
        status: pass
      - kind: unit
        ref: "tests/chat/test_repository_routing_trace_model.py#test_degrade_reason_column_shape_constraints"
        status: pass
      - kind: unit
        ref: "tests/chat/test_repository_routing_trace_model.py#test_degrade_reason_rejects_overlong_value"
        status: pass
      - kind: unit
        ref: "tests/chat/test_repository_routing_trace_model.py#test_degrade_reason_and_block_order_round_trip"
        status: pass
      - kind: unit
        ref: "tests/chat/test_repository_routing_trace_model.py#test_migration_0032_is_additive_and_reversible"
        status: pass
      - kind: other
        ref: "uv run python manage.py migrate chat 0031（Unapplying 0032 OK）→ migrate chat（Applying 0032 OK）"
        status: pass
      - kind: other
        ref: "rg -c 'RunPython' chat/migrations/0032_*.py == 0；makemigrations --check --dry-run 干净"
        status: pass
    human_judgment: false
  - id: D2
    description: "写入侧真的在写（本 plan 的 WARNING 修复点）：经 repository_relevance 工具真实调用路径落 trace 后两列非列默认值；legacy 路径留默认值"
    requirement: "RELY-03"
    verification:
      - kind: integration
        ref: "tests/agents/test_repository_relevance_tool.py#test_trace_write_persists_degrade_reason_and_block_order"
        status: pass
      - kind: integration
        ref: "tests/agents/test_repository_relevance_tool.py#test_trace_write_undegraded_v2_leaves_degrade_reason_empty"
        status: pass
      - kind: integration
        ref: "tests/agents/test_repository_relevance_tool.py#test_trace_write_legacy_path_keeps_column_defaults"
        status: pass
      - kind: other
        ref: "rg -n 'RepositoryRoutingTrace.objects.acreate' -A 12 agents/tools/repository_relevance.py | rg -c 'degrade_reason' / 'block_order' 均 != 0；pytest -k trace_write → 3 passed"
        status: pass
    human_judgment: false
  - id: D3
    description: "会话 detail 的 routing_trace payload 9 键；degraded 后端派生且 legacy_hybrid 不算降级；block_order 原样出边界"
    requirement: "RELY-03"
    verification:
      - kind: integration
        ref: "tests/chat/test_repository_routing_trace_model.py#test_detail_payload_exposes_degraded_facts_for_stage0_only"
        status: pass
      - kind: integration
        ref: "tests/chat/test_repository_routing_trace_model.py#test_detail_payload_v1_fallback_is_degraded"
        status: pass
      - kind: integration
        ref: "tests/chat/test_repository_routing_trace_model.py#test_detail_payload_v2_is_not_degraded"
        status: pass
      - kind: integration
        ref: "tests/chat/test_repository_routing_trace_model.py#test_detail_payload_legacy_hybrid_is_not_degraded"
        status: pass
      - kind: integration
        ref: "tests/chat/test_repository_routing_trace_model.py#test_detail_payload_passes_block_order_through"
        status: pass
      - kind: integration
        ref: "tests/chat/test_repository_routing_trace_model.py#test_detail_payload_empty_block_order_stays_empty_list"
        status: pass
      - kind: integration
        ref: "tests/chat/test_repository_routing_trace_model.py#test_detail_payload_key_set_is_exactly_nine"
        status: pass
      - kind: integration
        ref: "tests/chat/test_repository_routing_trace_model.py#test_detail_payload_is_none_without_trace"
        status: pass
    human_judgment: false
  - id: D4
    description: "degraded 派生点唯一：helper 定义 + detail + override 三处调用，别处无等价版本字面判定"
    verification:
      - kind: other
        ref: "rg -v '^[[:space:]]*#' chat/views.py | rg -c '_derive_degraded' == 3；rg -c 'router_version in \\{' chat/views.py == 1"
        status: pass
    human_judgment: false
  - id: D5
    description: "manual override 新 trace 继承三列、响应回传 4 键、候选呈现字段不丢、连续两次 override 链式继承"
    requirement: "ROUTE-01"
    verification:
      - kind: integration
        ref: "tests/chat/test_routing_trace_manual_override_view.py#test_override_new_trace_inherits_degrade_facts"
        status: pass
      - kind: integration
        ref: "tests/chat/test_routing_trace_manual_override_view.py#test_override_response_returns_degrade_facts"
        status: pass
      - kind: integration
        ref: "tests/chat/test_routing_trace_manual_override_view.py#test_override_keeps_candidate_presentation_fields"
        status: pass
      - kind: integration
        ref: "tests/chat/test_routing_trace_manual_override_view.py#test_override_undegraded_original_stays_undegraded"
        status: pass
      - kind: integration
        ref: "tests/chat/test_routing_trace_manual_override_view.py#test_override_twice_keeps_facts_along_the_chain"
        status: pass
      - kind: other
        ref: "rg -n 'RepositoryRoutingTrace.objects.acreate' -A 10 chat/views.py | rg -c 'router_version=original' != 0"
        status: pass
    human_judgment: false
  - id: D6
    description: "V4 Access Control 零回归：跨用户 / 跨项目两条拒绝路径行为逐字不变"
    verification:
      - kind: integration
        ref: "tests/chat/test_routing_trace_manual_override_view.py#test_cross_user_access_forbidden"
        status: pass
      - kind: integration
        ref: "tests/chat/test_routing_trace_manual_override_view.py#test_cross_project_access_forbidden"
        status: pass
      - kind: integration
        ref: "tests/test_conversation_isolation.py#TestCrossUserDenied（#24 routing-trace-manual-override POST）"
        status: pass
    human_judgment: false
  - id: D7
    description: "ROUTE-02 的 block_order 契约在 API 边界成立（有项目上下文时长度 2、无上下文时 [] / ['global']）"
    requirement: "ROUTE-02"
    verification:
      - kind: integration
        ref: "tests/chat/test_repository_routing_trace_model.py#test_detail_payload_passes_block_order_through"
        status: pass
      - kind: integration
        ref: "tests/agents/test_repository_relevance_tool.py#test_trace_write_persists_degrade_reason_and_block_order"
        status: pass
    human_judgment: false
  - id: D8
    description: "派生 degraded 追溯性作用于历史 v2_stage0_only / v1_fallback trace（横幅只出主句、不出原因行）——预期的真实化行为变更"
    verification: []
    human_judgment: true
    rationale: "「历史 trace 突然出现降级横幅是否可接受」是产品判断：这些 trace 确实降级过，故本 plan 判定为如实呈现而非回归；需人工确认该判断（若不可接受，需按 created_at 划线或加显式列并回填）"
  - id: D9
    description: "回归基线不破：tests/chat + tests/test_conversation_isolation.py + tests/agents/test_repository_relevance_tool.py 共 186 passed"
    verification:
      - kind: integration
        ref: "cd server && uv run pytest tests/chat tests/test_conversation_isolation.py tests/agents/test_repository_relevance_tool.py -q → 186 passed"
        status: pass
    human_judgment: false

# Metrics
duration: 22min
completed: 2026-07-30
status: complete
---

# Phase 107 Plan 08: 降级与分组事实持久化并送出 API 边界 Summary

**`RepositoryRoutingTrace` 加 `degrade_reason`（`CharField(32)`，6 值闭集）与 `block_order`（`JSONField`）两列 additive 迁移，chat 工具的 v2 落库路径真的在写这两列（有「经真实工具路径落 trace 后断言两列非默认值」的用例），会话 detail 的 `routing_trace` payload 从 5 键补到 9 键、`degraded` 由后端 `_derive_degraded` 唯一派生（`legacy_hybrid` 刻意不算降级），manual override 新 trace 显式继承三列并回传 4 键——降级提示与分组分区从此跨刷新、跨 override 存活，两条权限拒绝路径零回归。**

## Performance

- **Duration:** 约 22 min
- **Started:** 2026-07-29T23:52:00Z
- **Completed:** 2026-07-30T00:14:00Z
- **Tasks:** 3（全部走 TDD：RED → GREEN，无 REFACTOR 轮）
- **Files created:** 1 / **modified:** 6

## Accomplishments

- **降级原因与区顺序持久化，且可 SQL 聚合。** `degrade_reason = CharField(max_length=32, blank=True, default="")`、`block_order = JSONField(default=list, blank=True)`，迁移 `0032_repositoryroutingtrace_degrade_reason` 恰两条 `AddField`、无 `RunPython`（有断言）、前向/后向各实跑一次（`Unapplying 0032 ... OK` → `Applying 0032 ... OK`）。列长 32 本身就是形状约束：结构上装不下上游异常原文（T-107-02 第二道防线），有一条「`ConnectionResetError: peer closed the connection` 过不了 `full_clean`」的用例锁定。
- **写入侧真的在写（本 plan 的 WARNING 修复点，也是最容易假绿的一处）。** `repository_relevance.py` 的 v2 分支把 `v2_result.degrade_reason` / `list(v2_result.block_order or [])` 捕获成局部量（在 `try` 之外初始化为列默认值，v2 任意失败回落时自然留默认），`acreate` 显式传两列。守护它的是三条**经真实工具调用路径**的用例：替身 router 返回 `router_version="v2_stage0_only"` / `degrade_reason="timeout"` / `block_order=["global","in_project"]`，落库后从 DB 取回该行断言 `degrade_reason != ""` 且 `block_order != []`（**再**断言等于 router 给的值）。前一半断言专门检出「漏填」——漏填时模型测试与 payload 测试全绿，而生产两列恒为默认值：`degraded` 虽仍由 `router_version` 派生为 True，但 RELY-03 要求的降级原因行永不出现、`block_order` 恒空让前端永远走平铺。用例名含 `trace_write`（`pytest -k trace_write` → 3 passed）。
- **刷新页面后降级提示不再消失。** 会话 detail 的 `routing_trace` payload 补 `router_version` / `degraded` / `degrade_reason` / `block_order` 四键（恰 9 键，有精确集合断言防将来漏键或悄悄加键）。七条行为用例**全部经真实 `GET /api/chat/conversations/{id}/`** 请求断言——直接调函数验不出「刷新后消失」这条，那条缺陷的现场就在 payload 组装处。
- **`degraded` 在后端派生且只有一个派生点。** `_derive_degraded(router_version) -> bool` 判 `{"v2_stage0_only", "v1_fallback"}`，detail 与 override 两处 payload 共用。`legacy_hybrid` 刻意排除：它是 `router_version` 的列默认值，算作降级会让全部历史 trace 突然出现降级横幅（UI-SPEC backstop 1 的历史兼容要求），有独立用例断言。唯一性由两条断言守护：`_derive_degraded` 的代码行（滤注释后）恰 3 处、`router_version in {` 全文恰 1 处（禁止别处再写等价字面判定）。
- **用户改一次勾选后降级事实不再丢失（Pitfall 3 后端半边闭合）。** override 新 trace 显式继承 `router_version` / `degrade_reason` / `block_order`——不继承的话新行会退化成列默认值 `legacy_hybrid`，`_derive_degraded` 随之变 False，降级横幅在勾选后凭空消失。响应同步回传 4 键（前端 `applyManualOverride` 的数据来源，前端半边在 107-09）。含一条「连续两次 override」用例：第二次的原 trace 是第一次的新 trace，事实沿链不丢。
- **候选级呈现字段未被白名单化丢弃。** 现行实现是 `dict(c)` 浅拷后只改 `selected_by_user_final`（天然保留 `group` / `trust` / `score_ranked`），补了一条断言防将来被重写成显式字段列表时静默丢字段（丢了前端分组分区就失效）。
- **V4 Access Control 零回归且新增了缺失的那半边。** 跨用户拒绝路径原有用例逐字未动；**新增** `test_cross_project_access_forbidden`（会话归属自己但对该空间无成员权限 → 仍 404），此前该分支只有 `tests/test_conversation_isolation.py` 的跨用户参数化覆盖、无跨项目定向用例。两条拒绝路径的代码一行未改，改动处加了「新增字段不得挪到校验之前读写」的注释。

## `[:top_k]` 截断边界的裁决（107-07 Explicit Scope Boundary 第 2 条）

107-07 留的问题：router 现在按组各取 `top_k` 后并集（`<= 2*top_k`），而 `_analyze_relevance_core` 沿用 `v2_candidates[:top_k]`——若前 `top_k` 个全局最优候选都在 `global` 组，`in_project` 组会在工具输出层被整组截掉。

**裁决：保留 `[:top_k]` 不改**，理由三条（已写成 `repository_relevance.py` 的代码注释）：

1. `top_k` 是 **LLM 可见的公开参数**（"返回的相关仓库数量上限"）。把返回上限悄悄改成 `2*top_k` 是单方面变更工具契约，且 `total_candidates` 语义随之漂移。
2. **分组呈现的契约不受影响**：本 plan 落的 `block_order` 取自 **router 结果**而非截断后的候选列表，所以「有项目上下文 → `block_order` 长度恒 2」在 API 边界仍然成立（UI-SPEC covered 11 的后端要求）。被截空的组由前端按「空组不渲染」处理（UI-SPEC §分组呈现已定义该行为）。
3. 改成按组配额会改变**送进 LLM 与前端的候选构成**，属于路由质量变更——需要 golden-set 评估背书，不属于本 plan（持久化 + payload）的范围，也不该在无评估的情况下顺手改。

**残留风险（如实记录，交给后续 plan 决定是否收口）：** 最坏情形是 `block_order[0] == "in_project"` 但 `in_project` 组被整组截掉——需要 `global` 组前 `top_k` 名全部高于 `in_project` 首位、且差距**小于** delta（否则 `block_order[0]` 就是 `global`）。此时前端渲染「全局候选」单区、无置顶提示，观感等同未启用分组。反过来，`block_order[0] == "global"` 时截掉 `in_project` 反而是**正确**呈现（置顶提示「更匹配的仓不在本项目关联范围内」正是该说的话）。若要收口，最小改法是「`block_order` 里的非空组各保底 1 条」（保持 `len == top_k`、契约不变，但仍改变候选构成，需评估）。

## Task Commits

1. **Task 1: 两列 + 迁移 + 写入侧接线** — `6eca5f40` (test, RED：8 failed) → `355c96d8` (feat, GREEN：43 passed)
2. **Task 2: detail payload 补 4 键 + `_derive_degraded`** — `40699541` (test, RED：7 failed / 1 passed) → `f1cb5c6c` (feat, GREEN)
3. **Task 3: override 继承并回传** — `3417233a` (test, RED：4 failed / 8 passed) → `c6947835` (feat, GREEN：12 passed)

_三个 task 的 REFACTOR 轮均未产生改动（GREEN 实现即最终形态）。Task 2/3 的 RED 阶段各有若干新增用例即为绿：它们是**回归守护**（无 trace → `routing_trace is None`、候选呈现字段浅拷保留、跨项目拒绝），守护的是既有事实而非本 plan 的新行为，故不视为 RED 失效。_

## Files Created/Modified

- `server/chat/migrations/0032_repositoryroutingtrace_degrade_reason.py`（新建）— 两条 `AddField`（`block_order` / `degrade_reason`），依赖 `chat.0031_remove_codingplan_canonical_plan_id`。Django 生成的文件名与 plan frontmatter 一致，无需改名。
- `server/chat/models.py` — `RepositoryRoutingTrace` 紧跟 `router_version` 追加两列 + 中文注释（6 值闭集枚举、列长即形状约束、单列可聚合的理由；`block_order` 的长度语义与「不进任何排序或打分逻辑」的纪律）。
- `server/chat/views.py` — 新增模块级 `_derive_degraded`（唯一派生点，docstring 写明 `legacy_hybrid` 为何排除）；`routing_trace_payload` 补 4 键（`block_order` 用与 `candidates` 同款的 `isinstance(..., list)` 防御）；override 的 `acreate` 显式继承三列 + 响应补 4 键 + 两处因果与「不得绕过校验」注释。
- `server/agents/tools/repository_relevance.py` — v2 分支捕获 `degrade_reason` / `block_order` 两个局部量并在 `acreate` 显式传入；`[:top_k]` 裁决注释；legacy `acreate` 处注明刻意留列默认值。
- `server/tests/chat/test_repository_routing_trace_model.py` — 新增 5 条两列用例（默认值 / 形状约束 / 超长拒绝 / round trip / 迁移 additive 可逆）+ 8 条 detail payload 用例（全部经真实 endpoint），含 `_DETAIL_PAYLOAD_KEYS` 九键集合与 `_detail_routing_trace` / `_make_trace` 两个 helper。
- `server/tests/chat/test_routing_trace_manual_override_view.py` — 新增 6 条用例（继承 / 响应回传 / 候选字段不丢 / 未降级原样 / 连续两次链式继承 / 跨项目拒绝）+ `degraded_trace` fixture 与 `_override` helper；文件 docstring 补第 6 类测试范围与 `legacy_hybrid` 列默认值的 bug 根源说明。
- `server/tests/agents/test_repository_relevance_tool.py` — 新增 3 条写入侧用例 + `_make_degraded_v2_result` helper；段落注释写明「这三条守护的不是模型有列，而是写入侧真的在写」。

## Decisions Made

- **`degrade_reason` 加列而非塞 `candidates` JSON**：`candidates` 是 list，结果级事实塞不进外层；单列能直接 SQL 聚合「降级原因分布」当指标维度，而迁移代价只是一条 additive `AddField`。
- **`degraded` 不加列、由后端派生**：CONTEXT 的要求是「前端不自行推断」，推断放到后端即满足契约；加列则与 `router_version` 冗余，还得回填历史行。
- **`legacy_hybrid` 不算降级**：它是 `router_version` 的列默认值（v2 完全不可用时的历史聚合路径），算作降级会让全部历史 trace 突然出现降级横幅。
- **`block_order` 也走新列而非复用 `candidates` 外层**：与 `degrade_reason` 同理（结果级事实），且 `JSONField(default=list)` 的默认值天然等价「无分组上下文」。
- **override 显式继承三列**：同一次路由的降级/分组事实不因用户改勾选而改变；这不是「顺手继承」而是**必须**——不继承就等于把「降级过」静默改写成「没降级过」。
- **`[:top_k]` 保留**（详见上文专节）。
- **顺带修三个测试文件的 ruff import 报错**：见 Deviations 第 1 条。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 三个测试文件先于本 plan 的 `ruff` 报错让 plan 级验证命令无法通过**

- **Found during:** Task 3 收尾（plan 级 `<verification>` 的 ruff 清单）
- **Issue:** `<verification>` 明确要求 `ruff check` 覆盖 `tests/chat/test_repository_routing_trace_model.py` / `tests/chat/test_routing_trace_manual_override_view.py` / `tests/agents/test_repository_relevance_tool.py`，但这三个文件各带一条 `I001`（外加第三个文件一条 `unittest.mock.patch` 未使用的 `F401`），共 4 条。用 `git show f8f51331:<path> | ruff check --stdin-filename` 对**改动前**的三个文件逐一确认：同样的 4 条报错在本 plan 之前即存在（107-07 SUMMARY 也记录过其中 2 条，当时按 scope boundary 未修）。
- **Fix:** 对这三个文件跑 `ruff check --fix`。实际改动是纯机械的：删掉未使用的 `patch` import + 三处多余空行（`git diff` 共 1 insertion / 4 deletions，零行为变更）。
- **为何这次修：** 与 107-07 不同，本 plan 的验收清单**包含**这三个文件，不修则该命令永远非零退出、验收无法为真；且修法是 `--fix` 的机械输出，不涉及任何逻辑判断。
- **Files modified:** server/tests/chat/test_repository_routing_trace_model.py, server/tests/chat/test_routing_trace_manual_override_view.py, server/tests/agents/test_repository_relevance_tool.py
- **Verification:** 7 个文件的 `ruff check` 全绿；修完后定向套 186 passed（与修前同数）
- **Committed in:** `c6947835`

**2. [Rule 2 - Missing Critical] 跨项目拒绝路径缺定向回归用例**

- **Found during:** Task 3（plan `<behavior>` 第 6 条要求「跨项目访问 → 仍拒绝，`_cross_project` 行为逐字不变」）
- **Issue:** `test_routing_trace_manual_override_view.py` 只有跨**用户**的定向用例；跨项目分支（owner gate 通过、`has_project_access` 不通过）此前只被 `tests/test_conversation_isolation.py` 的跨用户参数化间接覆盖，**没有**任何用例真正走进那条 `routing_trace_manual_override_denied_cross_project` 分支。没有它，本 plan「新增字段只在通过两道校验后的分支里读写」这条 V4 断言就没有可失效的证据。
- **Fix:** 新增 `test_cross_project_access_forbidden`——建一个当前用户**无** `SpaceMembership` 的 Space、会话 `created_by=user`（故意让 owner gate 通过），断言 404。
- **Files modified:** server/tests/chat/test_routing_trace_manual_override_view.py
- **Verification:** 该用例在 RED 阶段即为绿（守护既有行为，非新行为）；GREEN 后仍绿，证明本 plan 的三列继承没有把读写挪到校验之前
- **Committed in:** `3417233a`（RED）

---

**Total deviations:** 2 auto-fixed（1 条 blocking 的 lint 债务清理、1 条缺失的权限回归用例补齐）
**Impact on plan:** 均不改变 plan 的任何设计决策；第 1 条是让验收命令可执行的前提，第 2 条把 plan 已写进 `<behavior>` 但既有测试未覆盖的那半边补上。无 scope creep：`repo_router_v2.py` / `repo_router_scoring.py` / 前端任何文件 / `STATE.md` / `ROADMAP.md` 均未出现在任何提交的改动清单中。

## Explicit Scope Boundaries

- **派生 `degraded` 追溯性作用于历史 trace（预期的行为变更，须人工复核）。** 历史的 `v2_stage0_only` / `v1_fallback` trace 刷新后**会**开始显示降级横幅——它们确实降级过，只是当时没有 `degrade_reason`，故横幅只出主句、不出原因行（UI-SPEC 已定义该行为）。本 plan 判定这是「如实呈现」而非回归。若产品判断不可接受，需按 `created_at` 划线或改为显式列 + 回填。`legacy_hybrid` 不在此列（渲染逐字不变）。
- **`total_candidates` 与 `[:top_k]` 语义未动**（详见裁决专节），残留最坏情形已量化。
- **legacy HybridSearch 路径未接降级/分组**：两列留列默认值，`degraded` 派生为 False，前端渲染与今日一致。
- **前端半边未动（107-09 的范围）**：`stores/routing.ts` 的 `applyManualOverride` 仍只用响应 4 键 + `original` 的 2 键重建 trace。**后端已把它需要的 4 键都回传了**，但前端不从 `original` 兜底继承的话，勾选后横幅依旧会消失——Pitfall 3 的另一半必须在 107-09 修（UI-SPEC covered 12）。`sortedCandidates` 的全局重排（Pitfall 4）同理未动。
- **OpenAPI schema 未补 4 键**：`ConversationDetailSerializer` 与 override view 都**没有**声明 `routing_trace` 字段（该 payload 一直是手工组装的 dict、不在 serializer 契约里），故 plan action「若有 `@extend_schema` response 说明则同步补」判定为跳过——不是遗漏，是该处本就无字段声明可补。
- **`RequestMetric` / 指标聚合未接**：本 plan 只让 `degrade_reason` **可**聚合（单列受控枚举），未新增任何聚合查询或大盘。

## Issues Encountered

- **跨 task 的计数断言必须落在最后写入的那个 task。** `_derive_degraded` 的计数在 Task 2 是 `>= 2`（helper 定义 + detail 调用），Task 3 才是 `>= 3`（加 override 调用）。plan 已按此口径写死，执行时逐 task 实测为 2 → 3，未出现「断言在提交时恒假」。
- **`router_version in {` 的唯一性断言不滤注释行**（plan 原样保留），故所有注释措辞都刻意避开该字面量（用「等价的版本字面判定」表述）。实测全文恰 1 处。
- **`migrate chat 0031` 首次执行时 worktree 的 dev sqlite 落后于代码**，那一次是**前向**补齐 0029→0031 而非回退。故又跑了一次 `migrate chat 0031`（`Unapplying 0032 ... OK`）+ `migrate chat`（`Applying 0032 ... OK`），才真正验证了可逆性。

## T-107-02 前提（信息泄漏面，已 mitigate）

`degrade_reason` 出 API 边界到浏览器，但三道约束叠加后不承载自由文本：(1) 列长 32，结构上装不下上游异常原文（有超长拒绝用例）；(2) 写入侧值**只**来自 `RepoRouteResultV2.degrade_reason`，其上游是 107-03 的 `classify_degrade_reason`（6 值闭集），本 plan 不做任何再分类；(3) payload 未新增任何自由文本键（`cross_group_note` 依 107-07 的决定仍不进 chat 链）。前端侧的最后一道（`DEGRADE_REASON_LABELS` 未命中一律回退「未知原因」、绝不回显原始值）在 107-09。

## User Setup Required

None — 零新增配置项、零新增依赖。既有部署升级需跑 `migrate`（一条 additive 迁移、零回填、可逆）；升级后行为变化仅限：历史 `v2_stage0_only` / `v1_fallback` trace 开始显示降级横幅（见 Explicit Scope Boundaries 第 1 条）。

## Next Phase Readiness

- **107-09（前端）** 可直接消费 detail 与 override 两处 payload 的同一组 4 键（`router_version` / `degraded` / `degrade_reason` / `block_order`），`degraded` 已是后端算好的布尔、无需推断。**必须**同时修 `applyManualOverride` 的 `original` 兜底继承——后端已备好数据，前端不接则勾选后横幅仍会消失。
- **`[:top_k]` 的裁决结论与残留风险**见专节；若 107-09 落地后实测到「`block_order[0] === 'in_project'` 但本项目分区为空」的观感问题，按专节末的最小改法处理（需 golden-set 评估）。
- **Phase 109/110** 若要做「降级原因分布」大盘，`degrade_reason` 已是可 `GROUP BY` 的受控单列。
- 无阻塞项。

## Self-Check: PASSED

- 7 个改动/新建文件均在磁盘（`chat/models.py` / `migrations/0032_*.py` / `chat/views.py` / `agents/tools/repository_relevance.py` + 3 个测试文件）
- 6 个 task 提交均在 git 历史：`6eca5f40` / `355c96d8` / `40699541` / `f1cb5c6c` / `3417233a` / `c6947835`
- `git diff --name-only HEAD~6 HEAD` 恰 7 个文件；`STATE.md` / `ROADMAP.md` / 前端任何文件 / `repo_router_v2.py` 均无命中
- 全部 task 的 `<acceptance_criteria>` 已逐条执行并 PASS（含 `RunPython == 0`、`max_length=32 != 0`、acreate 窗口两键 `!= 0`、`_derive_degraded` 代码行 `== 3`、`router_version in {` `== 1`、`router_version=original != 0`、`-k trace_write` → 3 passed）
- plan 级 `<verification>` 全绿：定向套 **186 passed**、`makemigrations --check --dry-run` 干净、7 个文件 `ruff check` 全绿、迁移前向/后向各实跑一次
- 无 stub / 无占位实现：三个 task 的行为由 22 条新增用例覆盖（其中 19 条在 RED 阶段确为红）

---
*Phase: 107-layered-presentation*
*Completed: 2026-07-30*
