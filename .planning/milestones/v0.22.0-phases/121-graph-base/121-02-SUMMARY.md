---
phase: 121-graph-base
plan: 02
subsystem: infra
tags: [code_graph, networkx, dataclass, enum, contract, adapter-seam, multidigraph]

# Dependency graph
requires:
  - phase: 121-01
    provides: "networkx 直接依赖、CODE_GRAPH_* settings、tests/services/code_graph/ 测试包与 test_model.py 的两个用例桩"
provides:
  - "EdgeKind（call / chunk / cross_repo）与 EdgeConfidence 四档（resolved / bare_name / cross_repo / chunk_level）枚举"
  - "confidence_score()：静态档查表 + cross_repo 取 match_confidence 原值，缺参抛 ValueError"
  - "derive_reason()：四档理由串现推，D-08「不作为第 4 个边属性存储」写进 docstring"
  - "ChunkEvidence / GraphMeta（15 字段）/ CodeGraph 三个 frozen+slots 值对象"
  - "GraphError + GraphAccessDenied / GraphNotIndexed / GraphBuildTimeout / GraphBuildFailed 五级异常"
  - "BARE_NAME_BLACKLIST（17 项 frozenset）/ LOW_RESOLUTION_THRESHOLD=0.6 / REDACTED_REPOSITORY"
  - "model.__all__ 15 项（121-09 barrel 的 17 项 = 本 15 项 + GraphService + invalidate_repository）"
affects: [121-03, 121-04, 121-05, 121-06, 121-07, 121-08, 121-09, 121-10, 122, 123, 124, 125, 126, 127]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "契约层运行期零 networkx：import 只在 if TYPE_CHECKING 块内，用例用 AST 结构化断言守住"
    - "标记类字段设为必填无默认，让「漏透出」在 review 暴露而不是静默取默认值"
    - "跨相位纪律写进模块 docstring + 用例对 __doc__ 断言，纪律有可执行的留痕"

key-files:
  created:
    - server/services/code_graph/__init__.py
    - server/services/code_graph/model.py
  modified:
    - server/tests/services/code_graph/test_model.py

key-decisions:
  - "GraphError.details 未提供时保持 None，不照 AgentError 折成 {}——「没带上下文」与「带了个空上下文」对排障是两回事（plan 验收条款即如此要求）"
  - "networkx 的 TYPE_CHECKING import 在 Task 1 就落地（带 noqa: F401），Task 2 用上后摘掉 noqa，避免留下失效抑制"
  - "adapter seam 用 AST 断言而非 `\"networkx\" not in sys.modules`：测试进程里 llama-index 随时可能已载入 networkx，那个断言是环境噪声"
  - "chunk_evidence 的值取 tuple 而非 list：CodeGraph 是 frozen，证据面同样不可变，防上层就地 append 污染缓存里的同一张图"

patterns-established:
  - "契约模块三段式 docstring（问题背景 / 方案 / 边界），「边界」段专门承载要传给下游相位的纪律"
  - "纪律可执行化：用例对 __doc__ 断言关键子串（D-08 / depth_limit / rustworkx / MultiDiGraph / 绝不返回空图）"
  - "枚举 docstring 逐档写明「来源 + 默认是否参与扩散」，让默认值本身成为契约的一部分"

requirements-completed: []

# Metrics
duration: 9min
completed: 2026-08-09
---

# Phase 121 Plan 02: 图服务契约层 Summary

**`services/code_graph/model.py` 落地：四档边置信度枚举 + `reason` 现推函数 + 三个 frozen/slots 值对象 + 五级异常，零 Django、运行期零 networkx，三条跨相位纪律有可执行留痕**

## Performance

- **Duration:** 约 9 分钟
- **Started:** 2026-08-09T05:25:00Z
- **Completed:** 2026-08-09T05:33:29Z
- **Tasks:** 3
- **Files modified:** 3（2 新建 + 1 修改）

## Accomplishments

- **契约面定型**：`EdgeKind` × `EdgeConfidence` 两个正交枚举 + `confidence_score()` 数值映射。`cross_repo` 档刻意不入静态表——它取 `CrossRepoApiCall.match_confidence` 原值，缺参直接抛 `ValueError` 而不是静默兜底成常量（静默兜底会让跨仓边的可信度凭空变成一个假数）。
- **D-08 写死在契约层**：`derive_reason()` 是模块级函数而非边属性，docstring 写明「1–3 个边属性成本完全相同，第 4 个才跳一级，30 万边省约 6.9MB」；用例额外断言**任何契约 dataclass 都不得有 `reason` 字段**——这条断言会随 Plan 121-05/06 新增值对象自动生效，堵住 loader「顺手存成第 4 个属性」的路。
- **可信度声明的唯一依据**：`GraphMeta` 15 个字段，其中 `partial_edges` / `degraded` / `low_resolution` / `cross_repo_unresolved_count` 四个标记字段**必填无默认**（用例断言 `default is MISSING`），上层漏透出会在 review 暴露；`cross_repo_branch_unfiltered` 如实声明「`ApiCallSite` 没有 `branch_name`，跨仓边无法按分支过滤」这个语义缺口。
- **adapter seam 有机械防线**：`import networkx as nx` 只在 `if TYPE_CHECKING:` 内，用例用 `ast` 解析源码、断言每一处 networkx import 的行号都落在 TYPE_CHECKING 块的行范围内，再核对 `vars(model)` 里没有 `nx`。未来换 rustworkx 只需改 loader 与本文件的注解。
- **纪律留痕可执行**：模块 docstring 的「边界」段同时含 `rustworkx` / `depth_limit` / `MultiDiGraph` / `D-08`，四个子串都有用例断言。Pitfall 10 的千倍差（`list(bfs_layers)[:d]` 97.3ms vs `islice` 0.0ms）与 `reverse(copy=False)` 视图写法一并写进去，Phase 122 写遍历时不必回头翻 RESEARCH。

## Task Commits

1. **Task 1: 边种类与四档置信度契约 + reason 现推函数** — `ed2bc73d` (feat)
2. **Task 2: CodeGraph / GraphMeta / ChunkEvidence 值对象** — `d64ee409` (feat)
3. **Task 3: 异常层级、模块 docstring 纪律与 `__all__`** — `c6a05dbd` (feat)

**Plan metadata:** 见本文件的收尾 docs 提交。

## Files Created/Modified

- `server/services/code_graph/__init__.py` — 占位，只有 docstring；写明「导出面由 121-09 补全」与「不导出 loader / cache 是架构红线」
- `server/services/code_graph/model.py` — 契约层全部内容（三段式 docstring / 2 枚举 / 2 函数 / 3 常量 / 3 dataclass / 5 异常 / `__all__`）
- `server/tests/services/code_graph/test_model.py` — 2 个桩转为真实断言 + 12 个新增用例，共 14 passed

## Decisions Made

- **`GraphError.details` 保持 `None`**：analog `agents/core/exceptions.py::AgentError` 写的是 `details or {}`，本模块刻意不照抄。plan 的验收条款明确要求 `GraphError("x").details is None`，理由成立——「没带上下文」与「带了个空上下文」对排障是两回事，抹平之后调用方无法区分。差异写进了 `GraphError` 的 docstring，防后人「对齐 analog」时改回去。
- **adapter seam 用 AST 断言，不用 `sys.modules`**：plan 的验收条款给了两个选项（`"networkx" not in sys.modules` 前提下 import 成功，或退化为断言 `model.__dict__` 无 `nx`）。实测本仓测试进程里 llama-index 会先把 networkx 载入，前者恒假。选了更强的第三种：对源码 AST 断言「每处 networkx import 的行号都在 TYPE_CHECKING 块内」，既不依赖进程状态，也比 `vars()` 检查更早发现问题（两者都做了）。
- **`chunk_evidence` 值类型取 `tuple`**：`CodeGraph` 是 frozen，但 `Mapping[str, list[...]]` 的 list 仍可就地 append——缓存里的同一张图被上层污染就是跨请求的脏数据。用 tuple 把不可变性贯彻到底。
- **常量与值对象的排布顺序**：枚举 → 数值/理由函数 → 常量 → 值对象 → 异常 → `__all__`。裸名黑名单与阈值紧跟置信度枚举，读的人一眼能把「四档 + 三道过滤 + 阈值」当成一个整体。

## Deviations from Plan

**None — plan executed exactly as written.**

三个 task 的 action 与验收条款逐条落地，无 Rule 1–4 触发，无 scope creep。两处需要说明的**执行细节**（不是偏离，是 plan 明确留给执行方的选择）：

1. **networkx TYPE_CHECKING import 的落位时机** — Task 1 的验收条款要求「grep 命中行落在 TYPE_CHECKING 块内」，但 Task 1 本身还没有用到 `nx`（`CodeGraph` 在 Task 2 才定义）。选择在 Task 1 就写下该 import 并带 `# noqa: F401`，Task 2 用上后摘掉 noqa——这样每个 task 的验收都能字面通过，且终态没有失效的 lint 抑制。
2. **adapter seam 断言形态** — plan 的验收条款自带二选一（见上文 Decisions），按其授权选了 AST 形态。

## Issues Encountered

**`uv run mypy services/code_graph/model.py` 报 1 条错误，落在 `workflows/schemas/technical_plan.py:268`（预存在）。**

`Unexpected keyword argument "spaces" for "TechnicalPlan"` —— 与 Plan 121-01 记录的是同一条（该 plan 的 SUMMARY「Lint / 类型检查」段已登记）。mypy 会连带检查依赖闭包内的模块，本 plan 的两个新文件**零错误**。按 scope boundary 纪律不修（本 plan 物理上没有触碰 workflows/）。

`uv run ruff check services/code_graph/ tests/services/code_graph/test_model.py` → All checks passed。

未运行全量 `pytest` 与 `tests/codegraph tests/code_relations` 回归（约 18 分钟），该项已排期为 Plan 121-10 的相位闸门；Wave 0 建立的 4 条预存在失败（`test_chunkedge_fan_in_query_uses_target_index` 的 SQLite/PostgreSQL 方言耦合 + 3 条 `test_repo_summary_builder`）与本 plan 无关，未做处理。

## User Setup Required

None — 纯 dataclass/Enum 模块，无外部服务、无配置项、无迁移。

## Next Phase Readiness

**已就绪：**

- Plan 121-03（`access.py`）可直接 `from services.code_graph.model import GraphAccessDenied, GraphNotIndexed`，两个异常的 fail-closed 语义已在 docstring 里定死。
- Plan 121-04（`signature.py`）可用 `GraphMeta.built_signature` 作为签名落点字段。
- Plan 121-05/121-06（`loader.py`）四档边的判据、裸名黑名单、`LOW_RESOLUTION_THRESHOLD`、`ChunkEvidence` 的旁挂形态全部可直接消费；边属性个数契约（节点 5 / 边 3 / cross_repo 例外 4）写在 `CodeGraph` docstring 里。
- Plan 121-07（`cache.py`）可用 `GraphMeta.estimated_bytes` / `degraded` 承接字节预算与降级标记。
- Plan 121-09（barrel）：`model.__all__` 15 项 + `GraphService` + `invalidate_repository` = 121-VALIDATION.md 要求的 **17 项**，数量已对齐。

**留给后续 plan 的显式待办：**

- **Plan 121-10**：`LOW_RESOLUTION_THRESHOLD = 0.6` 是经验值，需用该 plan 的「per repo / per language 解析率统计」交付物复校（常量注释已标注）。
- **Plan 121-05/06**：装配时务必让边属性停在 3 个（`kind` / `confidence` / `line_number`），`reason` 走 `derive_reason()` 现推。`test_reason_not_stored_on_edge_attrs` 会自动扫描本模块新增的 dataclass，但**扫不到 loader 里直接 `add_edge(..., reason=...)` 的写法**——那需要 loader 自己的用例守。

## Self-Check: PASSED

- `server/services/code_graph/__init__.py` FOUND
- `server/services/code_graph/model.py` FOUND
- `server/tests/services/code_graph/test_model.py` FOUND
- 提交 `ed2bc73d` / `d64ee409` / `c6a05dbd` 均在 git 历史中可查
- `cd server && uv run pytest tests/services/code_graph -x -q` → **14 passed, 27 skipped**（29 个 Wave 0 桩中的 2 个已转真实断言）
- 工作区内 41 项与本 plan 无关的预存在改动保持未提交、未修改

---
*Phase: 121-graph-base*
*Completed: 2026-08-09*
