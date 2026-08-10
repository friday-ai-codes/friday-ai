---
phase: 122-impact-trace
plan: 03
subsystem: code-graph
tags: [reverse-bfs, confidence-tiers, path-min, risk-grading, truncation, pure-function, observability]

# Dependency graph
requires:
  - phase: 121-graph-base
    provides: "冻结 MultiDiGraph 内存契约、EdgeConfidence 四档、confidence_score() / derive_reason()、17 名 barrel、AST 观测契约"
  - plan: 122-01
    provides: "known_topology 13 节点冻结图（含只经裸名边可达的观察点 X）、hub_topology 可调扇入工厂、test_impact.py 的 8 个 Wave 0 桩"
provides:
  - "analyze_impact：分层反向 BFS + path-min 置信度 + 深度分组 + 确定性风险四级 + 截断 summary（纯函数，零 ORM）"
  - "grade_risk：D-15 阈值表 + D-29 弱证据封顶的确定性风险分级，可独立单测"
  - "_bare_name_allowed：D-08 双闸的唯一判据，独立可单测的私有谓词"
  - "输出契约：items / groups / risk / risk_inputs / summary / affected_processes / cross_repo 七个顶层字段位"
affects: [122-05, 122-06, 122-07, 122-08, 122-09, 122-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "path-min 与 path-top-tier 双量并行：同一条路径同时记「最弱边决定强度」与「路上见过的最强证据」，前者算 path_confidence，后者喂 D-29 封顶"
    - "阈值常量表如实标注「未经真实数据校准的初值」，与 LOW_RESOLUTION_THRESHOLD 的「已校准」形态刻意区分"

key-files:
  created:
    - server/services/code_graph/impact.py
  modified:
    - server/tests/services/code_graph/test_impact.py

key-decisions:
  - "_reverse_layers 返回 (best, truncated_by_nodes) 二元组而非纯 dict：撞遍历上限与「真的只有这么多」在结果形态上完全一样，不显式带出来调用方只能猜"
  - "risk 的 d1_count 与 best_path_tier 都取截断前的全集：风险等级描述真实影响面，不该因输出被截到 200 条就变小"
  - "D-29 封顶实现成「只降不升」：初判 LOW 时不被抬到 MEDIUM"
  - "test_risk_levels / test_min_confidence_filter 走表内循环而非 parametrize：保住 122-01 定下的 9 passed / 1 skipped 节点口径"

requirements-completed: []  # IMPACT-01/02/04 的内核已落地，但工具面（壳层 122-05~09）未齐，⛔ 不得据本 plan 勾选

# Metrics
duration: 13min
completed: 2026-08-09
---

# Phase 122 Plan 03: impact 内核（分层反向 BFS + 风险分级 + 截断纪律）Summary

**一个 627 行、零 ORM 零 Django 零运行期 networkx 的纯函数内核：在冻结图上只读反向展开，把 Phase 121 的四档置信度原样带到每一条输出上，并用「弱证据封顶 MEDIUM」这条规则让裸名边的假阳性再也顶不到 CRITICAL**

## Performance

- **Duration:** ~13 min
- **Started:** 2026-08-09T15:44:57Z
- **Completed:** 2026-08-09T15:58:03Z
- **Tasks:** 3
- **Files modified:** 2（1 新建 627 行 + 1 追加）

## Accomplishments

- **分层反向 BFS 落地，全程只读**。用 `graph.predecessors()` 逐层展开，⛔ 未出现任何 `copy()` / `reverse(copy=True)`（AST 断言守着）。MultiDiGraph 上同一符号对的多档边逐条取 `graph[pred][node].values()`，四档边契约在遍历这一层就没被压平。首次访问即最浅层，D-05 的「同符号多层出现取最浅」由 BFS 的天然性质保证，不需要额外逻辑。
- **path-min 与 path-top-tier 两个量并行推进**，这是本 plan 最容易被写成一个量的地方：`path_confidence` 取沿途**最小**（D-07，弱边决定强度），`path_top_tier` 取沿途**最高档**（D-29 的输入）。方向相反不是笔误——一条 `resolved → bare_name` 的路径强度由 `bare_name` 决定，但「路上见过 resolved 这一档证据」也是事实，风险封顶要看后者。用例 `test_edge_confidence_and_reason` 直接钉死 `X` 的 `path_confidence == 0.3`：取平均会是 0.65，实现走偏当场红。
- **D-08 双闸独立成 `_bare_name_allowed` 谓词**，docstring 逐条解释两道闸问的是两个不同问题（`include_low_confidence` 是 Phase 121 的**装配口径**、是 `get_graph` 的缓存键分量；`min_confidence` 是本次查询的**查询口径**）。第二道闸的判据走 `confidence_score(EdgeConfidence.BARE_NAME)` 而非写死 `0.3`，Phase 121 若调整档位数值本模块不会悄悄失配。输出另给 `bare_name_included` 合成结果，让「传了开关却因门槛太高没看到弱证据」与「这个符号确实没有弱证据调用方」可被一眼分辨。
- **D-29 封顶真的在起作用，且用例证明它不是恒假**：`d1_count=50, crosses_repo=True` 在 `bare_name` 档下返回 MEDIUM，把档位提到 `cross_repo` 后同样输入立刻回到 CRITICAL。另加一条「只降不升」断言（初判 LOW 时不被抬到 MEDIUM）——弱证据是压低结论的理由，不是抬高结论的理由。
- **三重预算各有独立标记**（T-122-遍历 DoS）：`max_depth` 限层、`max_nodes=2000` 软上限置 `truncated_by_nodes`、`limit=200` 输出截断给 `truncated_by_depth`。`_reverse_layers` 因此返回二元组而不是纯 dict——撞遍历上限与「真的只有这么多」在结果形态上完全一样，不显式带出来调用方只能猜。
- **截断排序在截断之前生效**，用例用 `limit=10` 钉死：返回的 10 条全部是 d1 且 `path_confidence` 非递增。先截后排的实现会混进 d2 的条目。`truncated_by_depth` 记的是**每层被截掉的条数**（不是每层总数）——d3 被截 300 条与 d1 被截 300 条对「这次改动有多危险」是完全不同的两件事。
- **风险等级取截断前的全量**：250 扇入的 hub 上输出被截到 200 条，`risk_inputs["d1_count"]` 仍是 250、等级仍是 CRITICAL。影响面的真实规模不该因为输出预算而缩水。
- 新模块**自动**通过既有 AST 观测契约（`package_dir.glob("*.py")` 扫全包），未改动任何守护测试的判据。一次 `analyze_impact` 恰一条 DEBUG `sampling` 事件，只记 `depth` / `returned` / `total_found` / `duration_ms`，⛔ 不记符号名与路径，🚨 BFS 循环内零 `logger.*`。

## Task Commits

1. **Task 1: 分层反向 BFS 与 path-min 置信度** - `ef98c683` (feat)
2. **Task 2: min_confidence 过滤与 D-08 双闸** - `1e66d328` (feat)
3. **Task 3: 确定性风险四级（含 D-29 封顶）与截断 summary** - `13a5400b` (feat)

## Files Created/Modified

- `server/services/code_graph/impact.py`（新建，627 行）— 三段式中文 docstring；六个模块级常量（`DEFAULT_MAX_DEPTH=3` / `DEFAULT_RESULT_LIMIT=200` / `DEFAULT_MAX_NODES=2000` / `DEPTH_LABELS` / `RISK_THRESHOLDS` / `_CONFIDENCE_TIER_RANK` / `_TEST_PATH_HINTS`）+ 事件名 `_EVENT_IMPACT_ANALYZED`；`RiskLevel` 四级 Enum；`_Reach` 冻结 dataclass；公开 `analyze_impact` / `grade_risk`；私有 `_edge_score` / `_bare_name_allowed` / `_depth_label` / `_looks_like_test_file` / `_render_via` / `_reverse_layers` / `_build_item` / `_log_impact_analyzed`。运行期 import 仅 `__future__` / `time` / `collections` / `collections.abc` / `dataclasses` / `enum` / `types` / `typing` / `structlog` + 包根 barrel；`networkx` 只在 `TYPE_CHECKING` 块内。
- `server/tests/services/code_graph/test_impact.py` — 摘掉 8 个 `@pytest.mark.skip` 并填实；新增三个模块级 helper（`_ids` / `_all_ids` / `_item`）。`test_graph_cross_repo_edges_are_intra_repo` 仍挂 skip 待 122-06。

## Decisions Made

- **`_reverse_layers` 返回 `(best, truncated_by_nodes)` 二元组**，plan 的类型注解写的是纯 `dict[str, _Reach]`，但同一段 action 又要求「撞上限即返回一个 `truncated_by_nodes` 标记」。取二元组而不是往 `_Reach` 上挂标记：软上限是**整次遍历**的属性，不是某个节点的属性，挂到节点上语义就错了。
- **风险的两个输入都取截断前的全集**（`d1_count` 与 `best_path_tier`）。plan 只写了 `best_path_tier = max(item.path_top_tier for item in 全部结果)`，「全部结果」在有截断时是有歧义的。取截断前是唯一说得通的口径——否则同一个符号，`limit=200` 判 CRITICAL、`limit=10` 就降成 MEDIUM，等级会变成输出预算的函数。
- **D-29 封顶实现成「只降不升」**：`level in (HIGH, CRITICAL)` 时才压到 MEDIUM。plan 说的是「封顶为 MEDIUM」，字面照做会让初判 LOW 的结果被「封」高一档。加了一条用例钉死这个方向。
- **两个跨档性质的用例走表内循环而不是 `parametrize`**。`test_min_confidence_filter` 断言的是「后一档是前一档的子集」这条**跨档**性质，拆成独立节点就没法比；`test_risk_levels` 若参数化会把文件撑到几十个节点，与 122-01 定下的「9 passed / 1 skipped」验收口径冲突。理由已写进两条用例的 docstring。
- **`analyze_impact` 输出补 `seed_in_graph`**（plan 未列，Rule 2 补的必要功能）。`graph.predecessors()` 对不存在的节点抛 `NetworkXError`，而「符号不在图里」是调用方完全可能撞上的正常输入（uid 打错 / 被 exclusion 挡掉 / 不在按需子图内），不该以异常形态穿透到壳层；同时「符号不存在」与「没有影响」必须能被壳层区分开——后者才是可以据以决定「改这里安全」的结论，这正是 Phase 121「绝不返回空图」那条硬约束在本层的对应物。
- **`ruff format` 不作为本包门禁**（沿用 122-02 的裁决）。包内既有 6 个文件同样 `--check` 不过（ruff 配置 line-length 100，包内代码按 88 列换行），本文件对齐既有风格。plan `<verification>` 要求的 `ruff check` 全绿。

## Deviations from Plan

三处，均为 Rule 2（补齐正确性所需的必要功能），无 Rule 1 / Rule 3 / Rule 4 触发：

**1. [Rule 2 - 缺失的必要功能] `_reverse_layers` 对不在图里的种子做显式短路**
- **Found during:** Task 1
- **Issue:** 直接调 `graph.predecessors(seed)` 时，种子不在图里会抛 `nx.NetworkXError`。这是调用方的常规输入之一，不是异常路径。
- **Fix:** 函数开头 `if seed_id not in graph: return {}, False`；`analyze_impact` 顶层输出补 `seed_in_graph` 布尔字段供壳层区分「不存在」与「无影响」。
- **Files modified:** `server/services/code_graph/impact.py`
- **Commit:** `ef98c683`

**2. [Rule 2 - 缺失的必要功能] 输出补 `bare_name_included` 合成字段**
- **Found during:** Task 2
- **Issue:** 只透出 `include_low_confidence` 入参的话，调用方无法分辨「我传了开关但第二道闸把它挡了」与「这个符号确实没有弱证据调用方」——而这两种情形对「要不要放宽门槛再查一次」的建议完全相反。
- **Fix:** 把 `_bare_name_allowed` 的返回值作为 `bare_name_included` 一并透出，并在用例里断言它与谓词逐点一致。
- **Files modified:** `server/services/code_graph/impact.py`、`server/tests/services/code_graph/test_impact.py`
- **Commit:** `1e66d328`

**3. [Rule 2 - 缺失的必要功能] `_depth_label` 对超出登记范围的深度落到最弱档**
- **Found during:** Task 1
- **Issue:** `DEPTH_LABELS` 只登记 1–3，但 `max_depth` 是调用方可传参数，理论上能超过 3。裸 `DEPTH_LABELS[depth]` 会 `KeyError`，返回空串则会让壳层渲染出一条没有档位的条目。
- **Fix:** `DEPTH_LABELS.get(depth, "MAY_NEED_TESTING")`，理由写进函数 docstring。
- **Files modified:** `server/services/code_graph/impact.py`
- **Commit:** `ef98c683`

## Verification Results

| 判据 | 结果 |
|---|---|
| `pytest tests/services/code_graph/test_impact.py -q`（**不带** `--reuse-db`，零 DB） | **9 passed, 1 skipped** —— plan 明写的期望值 |
| `pytest tests/services/code_graph -q --reuse-db` | **108 passed / 14 skipped**（基线 100/22，+8 passed / −8 skipped，零新增失败） |
| `test_access.py -k "observability or upper_layer or barrel"` | 4 passed（新模块自动进 glob 扫描，契约未破） |
| 性能红线 AST 断言（无 `.copy()` / `copy=True`） | 退出码 0 |
| D-04 机械判据（logger 首个位置实参须字面量或模块级 `Final[str]`） | 退出码 0 —— 无 `_emit()` 包装 |
| `_bare_name_allowed` 三点断言（0.3 放行 / 0.31 挡掉 / 单开开关挡掉） | 退出码 0 |
| `RISK_THRESHOLDS` 四键 + 源码含「未经真实数据校准」 | 退出码 0 |
| `ruff check services/code_graph/ tests/services/code_graph/` | All checks passed |
| `mypy services/code_graph/` | 本 plan 文件**零错误**（报出的 9 条全在包外既有文件：`initiatives/services/feature_solution_render.py` / `services/process_runtime/blueprint_execution.py` / `codegraph/services/repo_router_scoring.py`，且均属并发会话的编辑面） |
| `git diff --name-only HEAD~3 HEAD` | 恰两个文件，**不含** `services/code_graph/loader.py`（D-25 建边口径冻结面）与 `codegraph/services/repo_router_v2.py`（里程碑冻结面） |

## Issues Encountered

- 无新增。122-01 记入 `deferred-items.md` 的两条 `tests/mcp_tools/` ruff error 与本 plan 编辑面无交集，未新增任何 deferred 项。
- `mypy` 报出的 9 条既有错误比 122-02 时的构成有变化（多了 `codegraph/services/repo_router_scoring.py` 的四条），因为并发会话正在改那批文件。全部在包外，与本 plan 无关，未动。

## Known Stubs

两个**预留字段位**，是设计而非缺口，理由已写进代码注释：

| 字段 | 恒为 | 归属 |
|---|---|---|
| `affected_processes` | `[]` | Phase 126 回填的叙事层（本相位 OUT OF SCOPE，CONTEXT 明文只预留字段位） |
| `cross_repo` | `[]` | 壳层 122-06 / 122-07 填充 |

🚨 `cross_repo` 那一项的注释里写死了一条反滥用声明：内核**绝不**根据图内 `kind == "cross_repo"` 的边往这里放东西。D-25 实测确认 `loader._load_cross_repo_edges` 只在两端同属本仓时才建边，图里那一档边**从来不跨仓**；照着它填，填进去的会是一堆同仓边被误标成跨仓。122-06 的 `test_graph_cross_repo_edges_are_intra_repo`（本文件唯一仍挂 skip 的桩）正是这条的反向守护。

## Threat Flags

无新增威胁面。plan `<threat_model>` 的六条 `mitigate` / 一条 `transfer` / 一条 `accept` 落地情况：

| Threat ID | 落地方式 | 判据 |
|---|---|---|
| T-122-遍历 DoS | `max_depth=3` + `max_nodes=2000` 软上限 + `limit=200` 输出截断 + D-08 双闸，三重预算各有独立标记 | `test_truncation_summary` 三计数自洽；`truncated_by_nodes` 有独立字段位 |
| T-122-日志放大 | 一次 `analyze_impact` 恰一条 DEBUG `sampling` 事件；BFS 循环内零 `logger.*` | AST 观测契约 + 就地复核，退出码 0 |
| T-122-exclusion 回流 | 埋点只记四个计数，不记符号名与文件路径；内核不做二次过滤（被排除文件的符号在装配阶段就不入图） | 代码面为准 |
| T-122-空图误导 | 内核不 catch 任何 `GraphError`（它根本不取图）；`total_found == 0` 与 `seed_in_graph == False` 是两个可分辨的形态 | 输出字段面 |
| T-122-半新图误导 | `transfer` —— 内核不感知水位，`partial_edges` / `degraded` 由壳层从 `GraphMeta` 透出（归 122-05） | 未实现即为正确 |
| T-122-绕闸 | 运行期零 Django/ORM/networkx import，只吃已过三道闸的图对象 | 运行期 import 面：`__future__` / `time` / `collections` / `collections.abc` / `dataclasses` / `enum` / `types` / `typing` / `structlog` / `services.code_graph` |
| T-122-SC | `accept` —— **零新增依赖** | `122-RESEARCH.md` §Package Legitimacy Audit 表为空 |

## 如实记账（供 122-10 汇总）

- 🚨 **`RISK_THRESHOLDS` 的四个数是未经真实数据校准的初值**，⛔ 不得表述成经验结论。它们来自定性推理（「d1 到 20 已不是改完跑一下测试的量级」之类），没有任何一条对应实测分布。这一点已如实写进常量表注释，并与 `LOW_RESOLUTION_THRESHOLD`「已按 218 仓生产数据校准」的形态刻意区分开——照抄的是格式，不是「已校准」的语气。校准需要工具上线后的真实使用样本（agent 看到某个等级之后实际做了什么），届时照 121-10 的复校范式回来改。
- **D-29 封顶规则本身也未经真实数据验证**。它的正确性在合成图上可证（弱证据不产生强告警），但「封顶到 MEDIUM 而不是 LOW」这个落点同样是定性判断。
- **`mcp` submodule 与并发会话的编辑面全程未碰**：本 plan 三个 commit 恰触及两个文件，`git diff --name-only HEAD~3 HEAD` 中无 `mcp/`、无 `server/repositories/`、无 `server/durable/`、无 `web/`。

## User Setup Required

None - 零新增依赖、零迁移、零模型变更、无外部服务配置。

## Next Phase Readiness

- **122-05**（壳层）可直接 `from services.code_graph.impact import analyze_impact` 消费，输出的七个顶层字段位（`items` / `groups` / `risk` / `risk_inputs` / `summary` / `affected_processes` / `cross_repo`）已定型；壳层要做的是把 `GraphMeta` 的四个降级标记与 `resolution_rate` 数值并进同一份输出（D-23）。
- **122-06 / 122-07** 接手 `cross_repo` 字段位的填充，走 ORM 直查 `CrossRepoApiCall`（D-25），⛔ 不走图内 `cross_repo` 边。
- **122-04**（trace 内核）与本 plan 同为 wave 1，两者共用 122-02 的 `resolve_symbol_in_graph`，编辑面无交集。
- **IMPACT-01 / 02 / 04 未标记完成**：本 plan 只交付内核，工具面还差壳层（122-05）、跨仓（122-06）、双面接线（122-07/08/09）。⛔ 不得据本 plan 勾选 REQUIREMENTS。
- **无 blocker。**

## Self-Check: PASSED

- 交付文件均存在于磁盘：`server/services/code_graph/impact.py`（627 行）、`server/tests/services/code_graph/test_impact.py`（393 行）。
- 三个 task commit（`ef98c683` / `1e66d328` / `13a5400b`）均可在 `git log` 中查到。

---
*Phase: 122-impact-trace*
*Completed: 2026-08-09*
