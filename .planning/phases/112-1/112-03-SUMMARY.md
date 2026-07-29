---
phase: 112-1
plan: 03
subsystem: process_runtime / 双面路由
requirements: [CHARTER-02, FLOW-04]
provides:
  - "`stage_state[\"routing\"]` 逐字字段契约（顶层 8 键 + candidates[] 七键 + evidence 13 键）——112-04 dispatch 与 112-05 确认门快照的唯一读取面，见下方契约表"
  - "`BlueprintRouteAdapter.route(session) -> dict`：RepoRouterV2 原样调用 + 三分量融合 + intent 加权 + breakdown 组装 + blueprint.route.scored 事件；形状恒定（空需求/无候选与正常路径逐键一致）"
  - "`build_score_breakdown(*, router_base, charter_match, history_match, weights, evidence) -> dict`：`total = sum(三项加权值)` 恒等式（同一批浮点值求和）"
  - "`resolve_boundary_override(*, violated_boundaries, router_reasoning, llm_reason) -> (reason, unjustified)`：命中禁区时「有理由」与「有标记」恰有其一"
  - "`role_suggestion` 确定规则：`confidence == \"high\"` 或 `breakdown[\"charter_match\"] > 0` → direct，否则 indirect"
  - "`score_charter_match(charter, *, query_terms, rules=None) -> CharterMatchResult`（纯函数三规则）+ `DEFAULT_CHARTER_RULES` 强度基准"
  - "`acollect_charter_candidates(...)` 章程候选补入机制：owned(planned) 命中的仓以 router_base=0.0 / confidence=low 进候选"
  - "`ascore_history_match(...) -> HistoryMatchResult`：单次 delivery knowledge 检索（entity_kinds=[code_change, tech_plan]）+ RetrievalTrace 埋点 + 四种显式降级原因"
  - "`aload_route_weights()`：BLUEPRINT_ROUTE_WEIGHTS 逐 intent 逐分量全兜底（负值取 0 / 缺项回默认 / 异常回默认）"
affects:
  - "112-04：dispatch 按本 SUMMARY 契约表读 candidates[].repository_id / role_suggestion / confidence（confidence 直作 routed_confidence 入参）"
  - "112-05：`_h_bp_route` 以 StageOutcome(event=\"routed\", stage_state_update={\"routing\": route() 返回值}) 落盘；确认门快照读顶层 router_version / auto_selected / weights_used / unjustified_boundary_hit_count"
  - "115：blueprint.route.scored 事件 payload 展开逐候选三分量与 router_version；citations（repo_charter / knowledge_entity）供证据面渲染"
tech-stack:
  added: []
  patterns:
    - "策略可注入 adapter（router / charter / history 全 keyword-only，缺省零参构造）"
    - "纯函数与 IO 严格分离：三规则打分、breakdown 组装、禁区理由判定全为无 DB 纯函数（可单测、可被 golden set 评估）"
    - "逐字段显式映射（不 to_dict 整包透传）：新增分量时形状变更点唯一"
    - "无分词依赖的中文命中判定：整串子串 → ≥2 字符片段双向子串 → CJK 3-gram token 交集"
key-files:
  created:
    - server/services/process_runtime/blueprint_charter_match.py
    - server/services/process_runtime/blueprint_route_history.py
    - server/services/process_runtime/blueprint_route.py
    - server/tests/services/process_runtime/test_blueprint_charter_match.py
    - server/tests/services/process_runtime/test_blueprint_route_breakdown.py
    - server/tests/services/process_runtime/test_blueprint_route_stage.py
  modified: []
decisions:
  - "breakdown = router_base（RepoRouterV2 整个 score 作单一不可拆分量）+ charter_match + history_match，三项加权值之和恒等于 total 并记 router_version"
  - "history_match 取该仓命中的 top_score 而非命中数——避免历史噪声多的大仓靠命中数虚高"
  - "多功能点 intent 平票取保守的 brownfield（混合需求不当纯 greenfield，避免过度放大章程权重）"
  - "charter_match 命中判定补 CJK 3-gram token 交集（Rule 2）：整句禁区规则原本必然漏判，会让「命中禁区应降权」在生产静默失效"
  - "无候选时透传真实 router_version 而非谎报 \"skipped\"（「跑了没召回」与「没跑」对排障是两件事）"
completed: 2026-07-30
---

# Phase 112-1 Plan 03: blueprint_route 双面路由 Summary

**一行结论**：`RepoRouterV2` 原样输出作 `router_base` 单一不可拆分量，adapter 层加 `charter_match`（owned 含 planned 加分 / boundaries 判负 / evolution 降权，clamp `[-1,1]`）与 `history_match`（delivery knowledge 单次召回取 top_score），按 feature_point 主导 intent 取权重向量加权，组装出 `total == sum(三项)` 的可拆解 breakdown；高三提分专项 case 的机制解落地——`onion-learning` 凭章程 `owned_domains(status=planned)` 以 `router_base == 0.0` / `charter_match > 0` 补入候选，排序差异可完全归因章程分量；禁区候选只降权不淘汰但必须带 `boundary_override_reason`（router `reasoning` → 单次 sanity-check LLM → 否则打 `unjustified_boundary_hit`，三情形各有断言）；`repo_router_v2.py` 与全部冻结面逐字未动。

## `stage_state["routing"]` 契约（112-04 与 112-05 的唯一读取面）

`BlueprintRouteAdapter.route(session)` 的返回值就是本摘要；112-05 的 `_h_bp_route` 以
`StageOutcome(event="routed", stage_state_update={"routing": <本摘要>})` 落盘（`engine.py` 浅合并）。
**空需求短路与无候选两条路径的返回值形状与正常路径逐键一致**（下游无需判空分支）。

### 顶层 8 键

| 键 | 类型 | 读取方 | 说明 |
|---|---|---|---|
| `router_version` | `str` | 04 事件 / 05 快照 | `RepoRouterV2` 原样透传（`v2` / `v2_stage0_only` / `v1_fallback`）；**空需求短路**时为 `"skipped"`；「跑了但零候选」透传真实值 |
| `auto_selected` | `bool` | 05 快照 | 原样透传 |
| `intent` | `str` | 04 分桶 | 主导 intent ∈ `greenfield\|brownfield\|fix`；空需求短路为 `""` |
| `weights_used` | `dict` | 05 快照 | `{router_base, charter_match, history_match}` 三个 float |
| `charter_supplement_count` | `int` | 事件 | 章程补入候选数 |
| `unjustified_boundary_hit_count` | `int` | 事件 / 05 快照 | 命中禁区但无显式理由的候选数 |
| `candidates[]` | `list[dict]` | 04 分桶 / 05 快照 | 逐候选，字段见下；按 `total` 降序（同分按 `repository_id`） |
| `citations` | `list[dict]` | 115 | `{citation_id, source_type: repo_charter\|knowledge_entity, source_id, locator}`；**不属于 04/05 读取面** |

### `candidates[]` 每项固定七键

| 键 | 类型 | 说明 |
|---|---|---|
| `repository_id` | `str` | |
| `repository_name` | `str` | |
| `role_suggestion` | `"direct" \| "indirect"` | **确定规则**：`confidence == "high"` 或 `breakdown["charter_match"] > 0` → `direct`；否则 `indirect`（保守：不确定的仓走轻量合成） |
| `confidence` | `"high" \| "medium" \| "low"` | `RepoRouterV2` 原样透传；章程补入候选恒 `"low"`。**112-04 直接作 `create_tasks_for_session` 的 `routed_confidence` 入参** |
| `total` | `float` | 恒等于 `breakdown` 三项之和 |
| `breakdown` | `dict` | `{router_base, charter_match, history_match}`，均为**加权后**值 |
| `evidence` | `dict` | 固定 13 键，见下 |

### `evidence` 固定 13 键（缺键补中性默认，下游无需 `.get` 兜底）

`router_version` / `auto_selected` / `confidence` / `reasoning` / `matched_node_paths` /
`charter_source` / `charter_version` / `matched_domains` / `violated_boundaries` /
`penalty_reasons` / `history_match_unavailable` / `boundary_override_reason` / `unjustified_boundary_hit`

## 关键语义

- **`build_score_breakdown` 恒等式**：`total = sum(components.values())` —— 由三项**同一批浮点值**求和得出，绝不另算一遍。返回值另含 `weights`（本次生效权重向量）与 `evidence`（补齐 13 键）；`route()` 把它投影为契约里的 `total` / `breakdown` / `evidence` 三键。
- **`resolve_boundary_override(reason, unjustified)`**：未命中禁区恒 `("", False)`；命中禁区时优先取 router `reasoning`（截断 300）→ 其次单次 sanity-check LLM 理由 → 皆空返 `("", True)`。**不变量 `bool(reason) != unjustified`**（参数化断言 5 例），不存在「命中禁区却既无理由也无标记」的静默保留。
- **章程补入机制**：`acollect_charter_candidates` 扫章程 `owned_domains`（`status ∈ {implemented, planned}`）命中 query_terms 且不在既有候选内的仓，按 raw 分降序取前 5；补入项 `router_base=0.0` / `confidence="low"` / `reasoning="章程 owned_domains 命中（能力树未召回）"` / `matched_node_paths=[]`。
- **`HistoryMatchResult` 降级语义**：`unavailable_reason` 取 `""`（可得）/ `"empty_query"`（无查询或无候选）/ `"no_acting_user"`（`session.created_by` 为空，绝不伪造 actor）/ `"retrieval_error"`（检索异常）。降级时 `scores` 为空 → 该分量贡献 0，但原因写进 `evidence["history_match_unavailable"]`，**不伪装成「历史无命中」**。
- **intent 权重**：默认 greenfield `0.40/0.35/0.25`、brownfield `0.60/0.20/0.20`、fix `0.70/0.15/0.15`；主导 intent = 单功能点取其 intent、多功能点取多数、**平票取保守的 brownfield**。
- **章程 clamp**：正分累加后先 clamp 到 `1.0` 再叠加负分（否则多写几条 owned 就能抵消禁区命中）；总分 clamp `[-1, 1]`。

## Task Commits

| Task | Commit | 内容 |
| ---- | ------ | ---- |
| 1 | `d7181a8f` | 章程分量纯函数（三规则 + clamp + 证据）+ `aload_charters` / `acollect_charter_candidates` + 28 例单测 |
| 1 | `7e2a5de5` | 模块措辞去掉冻结路由器名（满足「章程分量与路由器解耦」零命中验收） |
| 2 | `6b33054d` | history_match 分量：单次召回覆盖两分路 + RetrievalTrace 埋点 + 无 actor / 检索异常显式降级 |
| 3 | `cd31c8f7` | BlueprintRouteAdapter 三分量融合 + intent 加权 + 禁区显式理由 + 契约摘要 + 事件；charter 命中判定补 CJK 3-gram |

## 测试与验证

- `tests/services/process_runtime/test_blueprint_charter_match.py`：**30 passed**（纯函数 22 + DB 8）
- `tests/services/process_runtime/test_blueprint_route_breakdown.py`：**48 passed**（恒等式参数化 21 + 归因/加权方向 5 + evidence 3 + 禁区不变量 10 + 权重兜底 9）
- `tests/services/process_runtime/test_blueprint_route_stage.py`：**20 passed**
- PLAN verification 全套（三文件 + `tests/codegraph/` + `tests/knowledge/`）：**694 passed, 20 skipped**（既有路由/召回链零扰动）
- `uv run python manage.py makemigrations --check --dry-run`：**No changes detected**，退出码 0
- 冻结面自检：`git diff --stat` 对 `codegraph/services/repo_router_v2.py` / `agents/call_source.py` / `event_taxonomy.py` / `settings_service.py` / `charter_service.py` / `resume.py` / `builtin_processes.py` / `repo_router_adapter.py` / `recall_adapter.py` **输出全空**
- 并行自检：本 plan 四个 commit 只触及自有 3 个源文件 + 3 个测试文件；`blueprint_spec_gate.py` / `blueprint_ambiguity_score.py` / `blueprint_intent_classify.py` / `blueprint_lifecycle_service.py`（112-02 独占）零命中
- 代码风格：全部改动经 `uv run ruff format` + `ruff check --fix`，All checks passed

### 高三提分专项机制断言（可证伪，全绿）

`test_charter_planned_owner_enters_candidates_as_supplement`：建 `onion-learning` + 章程
`owned_domains=[{"domain": "培优/学习提分", "status": "planned"}]`；mock router **不返回**该仓
（模拟能力树无培优节点）→ 对 greenfield 功能点跑 `route`，断言

- `onion-learning` **在 candidates 里**（`assert ... in by_id` 带失败信息）
- `breakdown["router_base"] == 0.0` 且 `breakdown["charter_match"] > 0`
- `evidence["matched_domains"]` 含该 planned 领域、`charter_supplement_count == 1`、`confidence == "low"`

配套 `test_charter_component_fully_explains_ranking_difference` 断言排序差异**完全且仅**由章程分量贡献：
同 `router_base` 下 `owned_c["total"] - plain_c["total"] == owned_c["charter_match"] - plain_c["charter_match"]`。

### SC2 后半（禁区显式理由）三情形断言

1. router `reasoning` 非空 → 候选**仍在列表**、`boundary_override_reason == reasoning`、`unjustified is False`，且 `_aexplain_boundary_overrides` **await_count == 0**（有现成理由不多花 LLM）
2. `reasoning=""`（两个禁区候选）→ `build_chat_model` **call_count == 1**（合并成一批单次调用）、两候选皆有理由且未被标记
3. `reasoning=""` + `build_chat_model` 抛异常 → 不抛、候选仍返回、`unjustified_boundary_hit is True`、顶层 `unjustified_boundary_hit_count == 1`

外加总不变量：`for c in candidates: if violated_boundaries: assert reason or flag` 且 `bool(reason) != flag`。

## 观测面（LOGGING-SPEC 自检）

- 三处新增结构化事件全带 `category="sampling"` / `component="process_runtime"` / `duration_ms`：
  `blueprint_route_history_started|completed|failed`、`blueprint_route_boundary_explain_started|completed|failed`、`blueprint_route_completed`
- 新增召回点写 `RetrievalTrace`（`arecord_retrieval_trace(None, kind=CHUNK, payload={source: "blueprint_route_history", session_id, kinds, result_count, per_repo_counts, scores, top_score, duration_ms})`），上报召回条数 / 逐仓命中数 / score / duration_ms
- 新增 LLM 调用点赋 `call_source`：复用路由族已注册的 `CallSource.BLUEPRINT_REROUTE`（**未新增枚举值**，`agents/call_source.py` diff 为空），日志 kv 用 `reason_kind="boundary_override"` 区分子用途
- 脱敏：所有异常文本经 `redact_secrets_in_text` 后写 warning；**需求原文、召回正文、禁区规则正文一律不进 trace payload 与日志**（反向 rg 断言通过）
- 归因：`session_id` 作关联键；history 分量 actor 取 `session.created_by`，为空显式降级（不伪造提权）
- best-effort：章程读 / 补入 / 打分 / 历史分量 / 禁区解释 / 事件 / 埋点全部 `except Exception` 吞掉并返降级值，观测与旁路依赖绝不反噬路由主流程

## Deviations from Plan

共 4 处，均为按现实修正，无功能缺口。

**1. [Rule 2 - 缺失关键功能] `charter_match` 命中判定补 CJK 3-gram token 交集**

- **Found during:** Task 3（构造禁区降权断言时）
- **Issue:** PLAN Task 1 要求「规范化后的 token 交集判定」，初版实现为「整串互为子串 + ≥2 字符片段双向子串」。中文章程禁区常写成**无分隔符整句**（如 `"不承接课程权益鉴权"`），需求文本同样是连写长句——两侧互不包含且各自只有一个片段，片段子串判定**必然漏判**。漏判会让「命中禁区应降权」这条 SC2 机制在生产上静默失效（测试若只用带分隔符的规则则完全测不出来）。
- **Fix:** `_tokens()` 对 CJK 片段取 3-gram（ASCII 片段取整词），`_matches` 在原两条判定后追加 token 交集判定。取 3 而非 2：2-gram 在中文里通用词过多（"学习"/"功能"）会大量假阳性。零新增外部依赖（守 T-112-SC）。
- **Verification:** 新增 2 例断言——整句规则 `"不承接课程权益鉴权"` 对 `"展示课程内容与权益鉴权状态"` 命中判负；无关整句 `"不承接支付结算与发票开具"` 不误判（3-gram 交集为空）。
- **Files modified:** `server/services/process_runtime/blueprint_charter_match.py`、`test_blueprint_charter_match.py`
- **Commit:** `cd31c8f7`

**2. [Rule 1 - 事实修正] 空需求短路与无候选返回**顶层 8 键全集**而非 PLAN 字面的 3 键**

- **Found during:** Task 3
- **Issue:** PLAN Task 3 ① 写空需求返回 `{"candidates": [], "router_version": "skipped", "weights_used": {}}` 并注「形状恒定」。字面只返 3 键与正常路径的 8 键不一致，112-04/05 读 `candidates` 之外的键会 KeyError——与「形状恒定」的意图自相矛盾。
- **Fix:** `_empty_result()` 统一返回 8 键全集（`intent=""` / `weights_used={}` / 两个计数 0 / `citations=[]`），空需求短路与「跑了但零候选」共用；后者透传真实 `router_version` 而非谎报 `"skipped"`（两者对 115 排障是不同事实）。
- **Files modified:** `server/services/process_runtime/blueprint_route.py`
- **Commit:** `cd31c8f7`

**3. [Rule 3 - 前提缺失] `requirement_spec` 取数走三级解析（PLAN 未指定来源）**

- **Found during:** Task 3
- **Issue:** PLAN 只写「从 `session` 取当前蓝图 `requirement_spec`」，未指定字段位置；实读代码，在途蓝图产物挂 `stage_state`，已落版本的蓝图在 `current_artifact_version.content`，两处都可能是路由期的真实来源。
- **Fix:** `_aresolve_requirement_spec` 三级解析：`stage_state["blueprint"]["requirement_spec"]` → `stage_state["requirement_spec"]` → `current_artifact_version.content["requirement_spec"]`（经 `@sync_to_async`，读失败 warning + 视作无 spec）。`_resolve_repository_ids` 同构三级（`include_repos` 三处来源 → work_item.space 仓 → None 全库）。
- **Files modified:** `server/services/process_runtime/blueprint_route.py`
- **Commit:** `cd31c8f7`

**4. [Rule 1 - 验收口径] 章程分量模块 docstring 去掉冻结路由器的字面名**

- **Found during:** Task 1（跑验收 rg 时）
- **Issue:** 验收要求 `rg "repo_router_v2|RepoRouterV2" blueprint_charter_match.py` **零命中**（证明章程分量与路由器解耦）。初版 docstring 用「不碰 `RepoRouterV2`」表达解耦意图，反而触发该硬断言。
- **Fix:** 改为「与能力树路由器完全解耦、本模块零引用」等表述，语义不变且验收零命中。
- **Files modified:** `server/services/process_runtime/blueprint_charter_match.py`
- **Commit:** `7e2a5de5`

## Known Stubs

无。三个模块的所有返回值均有真实数据源（`RepoRouterV2` / `RepoCharter` / delivery knowledge），无硬编码空值或占位文案；降级路径返回的空结构均带显式 `unavailable_reason` / `penalty_reasons` 说明原因，不是未接线的占位。

## Threat Flags

无新增安全面。本 plan 引入的三处外部交互均落在既有 threat register 内：delivery knowledge 检索（T-112-10，`user=actor` fail-closed 且不伪造）、SystemSetting 权重（T-112-12，逐分量强转 + 负值取 0 + 全兜底）、sanity-check LLM（T-112-14b，理由经白名单归一：只保留入参内 `repository_id`、截断 300）。零 ORM 写、零新增外部依赖、零新增 REST 入口。

## Self-Check: PASSED

- 文件存在：6 个 `key-files.created` 全部命中（3 源 + 3 测试）
- commit 存在：`d7181a8f` / `7e2a5de5` / `6b33054d` / `cd31c8f7` 均在 `git log`
- artifacts contains 断言：`def score_charter_match` ∈ blueprint_charter_match.py ✓；`entity_kinds` ∈ blueprint_route_history.py ✓；`build_score_breakdown` ∈ blueprint_route.py ✓；`onion-learning` ×7 ∈ test_blueprint_route_stage.py ✓；`boundary_override_reason` ∈ test_blueprint_route_stage.py ✓
- key_links 断言：`RepoRouterV2` 只在 `_resolve_router` 内 lazy import 调用（零改动）；`BLUEPRINT_ROUTE_WEIGHTS` ∈ blueprint_route.py ✓；`search_similar` ∈ blueprint_route_history.py ✓
- 硬验收：`sum(` ✓ / `resolve_boundary_override` ✓ / `unjustified_boundary_hit` ×12 ✓ / `use_call_source(CallSource.BLUEPRINT_REROUTE)` ✓ / `role_suggestion` ✓ / adapter `.objects.(create|acreate|update|aupdate)` 零命中 ✓ / `repo_router_v2.py` diff 空 ✓

## Next Phase Readiness

- **112-04（repo_research / reroute）**：按本 SUMMARY 契约表读 `stage_state["routing"]` —— 只读 `candidates[]` 的 `repository_id` / `role_suggestion` / `confidence`；`confidence` 直接作 `create_tasks_for_session` 的 `routed_confidence` 入参。缺 `"routing"` 键或 `candidates == []` 时按 PLAN 返回零派发结构（本 plan 保证 `candidates` 键恒存在，不会缺键）。
- **112-05（stage 注册 / 确认门）**：`_h_bp_route` 直接 `StageOutcome(event="routed", stage_state_update={"routing": await adapter.route(session)})`；确认门快照可读顶层 `router_version` / `auto_selected` / `weights_used` / `unjustified_boundary_hit_count`（后者是「有多少候选无人解释地留在禁区里」的门控信号）。
- **115（证据面）**：`blueprint.route.scored` 事件 payload 已含逐候选三分量与 `router_version`；`citations` 条目 `source_type` 取 `repo_charter` / `knowledge_entity`，`evidence.charter_source` / `charter_version` 支持标注「依据未经人工确认的草案」。
- **Phase 105 同步点**：分数分解落地后只需把 `router_base` 展开为路由器内部各信号，`build_score_breakdown` 的组装契约与本 SUMMARY 的字段表**不变**。
