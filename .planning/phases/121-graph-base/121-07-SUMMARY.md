---
phase: 121-graph-base
plan: 07
subsystem: infra
tags: [code_graph, cache, lru, byte-budget, singleton, threading, observability]

# Dependency graph
requires:
  - phase: 121-01
    provides: "CODE_GRAPH_CACHE_MAX_BYTES / CODE_GRAPH_MAX_GRAPH_BYTES 两项预算 settings、tests/services/code_graph/ 测试包与 _reset_code_graph_state autouse fixture、test_cache.py 的两个用例桩"
  - phase: 121-02
    provides: "CodeGraph / GraphMeta 值对象（_Entry 的载荷类型）"
  - phase: 121-03
    provides: "test_observability_contract AST 守护（本模块的两个埋点受其管辖）"
provides:
  - "estimate_graph_bytes(node_count, edge_count) -> int：确定性线性估算纯函数，同时服务装配前准入判据与装配后 LRU 记账"
  - "NODE_COST_BYTES=640 / EDGE_COST_BYTES=560，注释含完整标定条件与两个被证伪的『优化』"
  - "GraphService：OrderedDict + threading.RLock 的字节预算 LRU（_put / _get_entry / _evict_until_within_budget / stats）"
  - "_Entry：graph / estimated_bytes / built_signature / built_at"
  - "6 个 Final[str] 事件名常量（cache_hit / cache_evicted / stale_watermark / build_started·completed·failed），121-08 可直接取用"
  - "get_graph_service() 模块级单例工厂（lazy 读 settings）+ _reset_for_tests() 测试钩子"
  - "两个埋点 code_graph_cache_hit（DEBUG）/ code_graph_cache_evicted（INFO）"
affects: [121-08, 121-09, 121-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "本仓第一个按**字节预算**逐出的缓存：既有两套先例分别按条目数（volar_pool）与按文件（GalaxyGraphCache）记账，都约束不住 worker RSS"
    - "记账字段冗余在条目上而非从载荷现算：逐出发生在持锁区间内，现算意味着锁内遍历图"
    - "_reset_for_tests 既换指针**又**清旧实例状态：只换指针挡不住已持有旧引用的调用方"

key-files:
  created:
    - server/services/code_graph/cache.py
  modified:
    - server/tests/services/code_graph/test_cache.py
    - server/tests/services/code_graph/conftest.py

key-decisions:
  - "两处 grep 验收条款改用 AST 断言：`grep -c 'await'` 与 `grep -c 'asyncio\\.Lock'` 都会命中 plan 自己要求写进 docstring 的禁令散文，字面条款与 action 指令互斥；AST 判据（无 Await/AsyncFunctionDef/AsyncWith/AsyncFor、未 import asyncio）严格更强"
  - "_Entry 的用例载荷造真实 CodeGraph/GraphMeta 而非哑对象：让 _Entry 的类型契约随 GraphMeta 字段变更一起红"
  - "estimate_graph_bytes 负数入参抛 ValueError 而非钳到 0：静默取 0 会让一张大图被记成 0 字节、永远逐不出去——正是 121-05 handoff 点名的那个失效形状"
  - "用例间无污染用**成对**用例证明（两条各自断言自己看到空缓存），单独任一条都会假绿"

patterns-established:
  - "验收 grep 与 docstring 禁令互斥时，取 action 语义并给出 AST 形态的精确判据（本 plan 第三次遇到同类，前两次见 121-01 / 121-04 / 121-05）"
  - "预算算术自洽性写成用例：estimate_graph_bytes(110k, 330k) 与 CODE_GRAPH_MAX_GRAPH_BYTES 的比值锁在 0.9–1.1，让 settings 注释里那句『约 11 万符号触顶』不再是无人校验的散文"

requirements-completed: []

# Metrics
duration: 18min
completed: 2026-08-09
---

# Phase 121 Plan 07: 图缓存的存储侧 Summary

**`services/code_graph/cache.py` 落地存储侧：实测标定的确定性字节估算纯函数 + `OrderedDict`/`RLock` 的字节预算**循环**逐出 LRU + lazy 读 settings 的进程级单例与测试重置钩子——本仓第一个按字节而非条目数记账的缓存**

## Performance

- **Duration:** 约 18 分钟
- **Started:** 2026-08-09T06:38:00Z
- **Completed:** 2026-08-09T06:56:00Z
- **Tasks:** 3
- **Files modified:** 3（1 新建 + 2 修改）

## Accomplishments

- **字节估算是可单测纯函数，且与 settings 默认值讲同一套算术**。`estimate_graph_bytes` 不读 settings、不收图对象（用例用 `inspect.signature` 断言形参恰为 `(node_count, edge_count)`）、无副作用。更要紧的是 `test_estimate_bytes_matches_budget_arithmetic`：`estimate_graph_bytes(110_000, 330_000) / CODE_GRAPH_MAX_GRAPH_BYTES` 被锁在 0.9–1.1（实测 0.951），让 settings 注释里那句「256MB → 单仓约 11 万符号触顶」从散文变成会红的断言——常数与预算默认值任一被改而另一未改，当场暴露。
- **逐出是 `while` 不是 `if`，且有独立用例证明**。`test_evict_loop_drops_multiple_entries` 造一个要挤掉**两个**旧条目的新条目，断言两个都走、总字节回到预算内。只逐一次的实现能通过基础逐出用例，却会让缓存长期停在超预算状态——那正是 OOM 的形状，而这条是 GRAPH-03 的核心。
- **记账不漂移有针对性回归**。`test_put_overwrite_does_not_double_count` 对同一键写两次后断 `total_bytes` 等于单条目字节数，再覆盖成一个**更小**的条目验证减法方向也对（只加不减的实现会在第二段才露馅）。对应威胁登记 `T-121-记账漂移`。
- **载荷是真图，`estimated_bytes` 真的被记进去**。用例的 `_make_entry` 装配真实 `CodeGraph` + 15 字段 `GraphMeta` + `nx.MultiDiGraph`，并显式断 `entry.estimated_bytes > 0`——这正是 121-05 handoff 点名的那条：`GraphMeta.estimated_bytes` 若停在 0，LRU 会把每张图都记成 0 字节、永远逐不出东西，GRAPH-03 静默失效。
- **锁纪律与 `asyncio` 禁令都有机械防线**。`test_lock_discipline_documented_and_no_await` 用 AST 断言模块内**零**异步构造（`Await` / `AsyncFunctionDef` / `AsyncWith` / `AsyncFor`）且**未 import asyncio**，再断三个私有方法的 docstring 都含「调用方必须已持锁」。全同步让「持锁 await」在物理上不可能发生（D-04 / Pitfall 7）。
- **用例间无污染是成对证明的**。`test_singleton_isolation_first_writer` / `_second_writer` 各自写入后都断言**自己看到的是空缓存**——单独看任一条都会通过，合起来才说明 conftest 的 autouse 重置真的生效，且与执行顺序无关。
- **观测契约一次通过**。两个埋点各自把 `Final[str]` 常量写在 `logger.*` 的第一个位置实参上，`component="code_graph"` / `category="sampling"` 齐备；命中事件取 **DEBUG**（每次取图都跑，INFO 会违反级别纪律），逐出事件取 **INFO**（只在预算被撑破时发，是排查「命中率为何突然掉了」的第一手线索）。121-04 踩过的 `_emit` 转发器坑本 plan 直接绕开，且把理由写进了常量上方的注释。

## Task Commits

1. **Task 1: 字节估算纯函数与实测标定常数** — `09645353` (feat)
2. **Task 2: GraphService 的字节预算 LRU 与逐出埋点** — `766d27b9` (feat)
3. **Task 3: 模块级单例工厂与测试重置钩子** — `1f29ffd4` (feat)

**Plan metadata:** 见本文件的收尾 docs 提交。

## Files Created/Modified

- `server/services/code_graph/cache.py`（新建，320 行 ≥ plan 要求的 150）— 三段式模块 docstring（含四条边界：per-worker 纯内存不落盘 / 全同步锁内不 await / 锁原语一律 threading / 只做存储侧不 import loader·signature）/ 2 个字节常数 + 标定注释 + 「不要做的优化」注释 / 6 个 `Final[str]` 事件名常量 / `estimate_graph_bytes` / `CacheKey` 类型别名 / `_Entry` / `GraphService`（`_get_entry` / `_put` / `_evict_until_within_budget` / `stats`）/ 单例三件套 / `__all__` 5 项
- `server/tests/services/code_graph/test_cache.py` — 2 个桩转真实断言（`test_estimate_bytes_is_pure` / `test_evict_lru_until_within_budget`）+ 13 条新增用例 + `_make_entry` 助手
- `server/tests/services/code_graph/conftest.py` — autouse fixture 补调 `cache._reset_for_tests()`（`try/except ImportError` 兜住子计划顺序），并移除 121-01 留下的「待 121-07 补」说明；docstring 从「两份 memo」改成「三份进程级状态」并写明单例那份为何尤其隐蔽

## Decisions Made

- **`_reset_for_tests()` 既换指针又清旧实例状态**。`background_runner._reset_for_tests()` 的先例只需置空模块级变量，但这里不够：用例常常先 `svc = get_graph_service()` 拿到引用、再触发重置，只换指针会让那份引用继续带着上一个用例的条目跑。`test_reset_for_tests_returns_fresh_service` 对**旧引用**也断言 `stats()` 归零，把这条锁住。
- **`_Entry.estimated_bytes` 冗余存储，不从 `graph` 现算**。逐出发生在持锁区间内，现算意味着在锁内遍历图的节点/边；而条目一旦写入就不再变形，这个冗余数不会与图本身漂移。理由写进了 `_Entry` 的 docstring。
- **`max_graph_bytes` 同样校验 ≤ 0**。plan 的验收条款只点名 `max_bytes=0` 要抛，但两个入参是对称的预算值，只校验一个会让 `max_graph_bytes=0` 在 121-08 的准入判据里把**每一张图**都判成超限、静默走降级——比不校验更难查。用例覆盖三种坏值组合。
- **缓存键不做归一化别名**。`(repository_id, branch_name)` 里的 `branch_name` 沿用既有模型语义（`""` = 基线），⛔ 不把 `"main"` 折成 `""`：默认分支名因仓库而异（`main` / `master` / `trunk`），别名折错就是两张不同的图共用一个键、返回另一个分支的结论。理由写进了 `CacheKey` 上方注释。
- **单例段的 `threading` 理由写在代码里而非只写在 SUMMARY 里**。三类 event loop（ASGI 主循环 / `background_runner` daemon 线程循环 / workflow engine `_run_in_thread` 的每次执行独立循环）共用同一个进程级单例这件事，后人不看 CONTEXT 是想不到的；注释直接点名这三者与「跨 loop 会 `RuntimeError`」。

## Deviations from Plan

**None — plan executed exactly as written.**

三个 task 的 action 与验收条款逐条落地，无 Rule 1–4 触发，无 scope creep。一处需要说明的**验收条款字面表达与 action 指令互斥**（与 121-01 / 121-04 / 121-05 记录的同类，不改变任何代码行为），以及一处 plan `<verification>` 的路径笔误：

**1. 两处 grep 验收条款改用 AST 判据**

- Task 2 条款：`grep -c 'await' cache.py == 0` → 实际 **2**。命中在模块 docstring 边界② 与 `GraphService` 类 docstring 里，而那两处恰恰是 plan 的 action 要求写下的禁令散文（「⛔ 本 task 的所有方法均为同步方法，不含任何 `await`」）。两条字面互斥。
- Task 3 条款：`grep -c 'asyncio\.\(Lock\|Event\|Condition\)' cache.py == 0` → 实际 **1**，命中在模块 docstring 边界③ 的「⛔ 不用 `asyncio.Lock` / `asyncio.Event`」——同样是 action 明确要求写下的那条禁令本身。

两处的真实意图都是「没有这种构造」，落成 `test_lock_discipline_documented_and_no_await` 里的 AST 断言，**严格强于原 grep**（连字符串拼接、别名 import 都拦得住）：

```python
# 无 Await / AsyncFunctionDef / AsyncWith / AsyncFor 节点  → ✅
# ast.Import / ast.ImportFrom 的顶层模块名集合中无 "asyncio"，且含 "threading"  → ✅
```

**2. plan `<verification>` 的 `tests/codegraph/lsp` 收集不到用例**

volar_pool 的既有套件实际在 `server/codegraph/lsp/tests/`（源码树内），不是 `server/tests/codegraph/lsp/`。按真实路径跑 `codegraph/lsp/tests/test_volar_pool.py` → **12 passed，零回归**。

## Issues Encountered

**无功能性问题。** 三个 task 均一次通过，未触发观测契约拦截（121-04 踩过的 `_emit` 转发器坑本 plan 从一开始就绕开，并把理由写进常量上方的注释防后人再抽一次）。

**Lint / 类型检查：**

- `uv run ruff check services/code_graph/ tests/services/code_graph/` → All checks passed。
- `uv run mypy services/code_graph/` → 唯一 1 条错误落在 `workflows/schemas/technical_plan.py:268`（预存在，121-01 / 121-02 / 121-03 / 121-04 / 121-05 已五次登记），本 plan 的文件 0 错误。

**测试范围：** 按本 plan 的测试预算跑了 `tests/services/code_graph`（**62 passed / 11 skipped**，本 plan 把 2 个桩转成真实断言并新增 13 条用例；121-05 收尾时是 47 passed / 13 skipped）与 volar_pool 既有套件（**12 passed**）。约 18 分钟的 `tests/codegraph tests/code_relations` 广谱回归**未跑**——已排期为 Plan 121-10 的相位闸门，且本 plan 只新增一个文件、未触碰 `codegraph/` 的任何代码路径。Wave 0 登记的 4 条预存在失败（`test_chunkedge_fan_in_query_uses_target_index` 的 SQLite/PostgreSQL 方言耦合 + 3 条 `test_repo_summary_builder`）与本 plan 无关，未处理。

## User Setup Required

None — 纯进程内缓存模块，无外部服务、无新增配置项（复用 121-01 已落地的两项预算 settings）、无迁移。

## Next Phase Readiness

**已就绪：**

- **Plan 121-08（编排侧）**：`GraphService` 的存储面全部就位，`get_graph` 只需在 `self._lock` 内调 `_get_entry` / `_put`，把 `loader.load_graph` 与 `signature.compute_signature` 的调用放在**锁外**。6 个事件名常量已声明齐（`_EVENT_STALE_WATERMARK` / `_EVENT_BUILD_STARTED` / `_EVENT_BUILD_COMPLETED` / `_EVENT_BUILD_FAILED` 本 plan 未发出，留给该 plan）；`self._inflight: dict[CacheKey, Any]` 与 `self._max_graph_bytes` 两个占位字段已备好，前者填 single-flight 的等待原语、后者是准入判据的阈值。
- **`estimated_bytes` 的覆写路径已通**：121-05 把 `GraphMeta.estimated_bytes` 置 0 是分层的刻意结果，121-08 装配后须用 `estimate_graph_bytes(graph.number_of_nodes(), graph.number_of_edges())` 重算并经 `dataclasses.replace` 覆写（`GraphMeta` 是 frozen），同一个值也要写进 `_Entry.estimated_bytes`。⚠️ **两处必须是同一个数**，否则 LRU 记的与元数据声明的对不上。
- **Plan 121-09（barrel）**：`cache.__all__` 5 项中只有 `GraphService` 会进 `services/code_graph/__init__.py`（121-02 已定「不导出 loader / cache 是架构红线」，`estimate_graph_bytes` / 两个常数 / `get_graph_service` 均属内部实现细节）。
- **测试隔离已闭环**：conftest 的 autouse fixture 现在清三份进程级状态，setup/teardown 两侧都调；后续 plan 新增的缓存用例天然获得隔离，不必各自 `_reset_for_tests()`。

**留给后续 plan 的显式待办：**

- **Plan 121-10（相位闸门）**：`NODE_COST_BYTES=640` / `EDGE_COST_BYTES=560` 必须用「最大仓实测」交付物复校，且**要按 RSS 而非 tracemalloc** —— tracemalloc 不含 arena 碎片与解释器开销，真实 RSS 通常更高，比值显著 > 1 时两个常数都要再上调（RESEARCH 假设 A1）。同时该 plan 应顺带产出本仓真实的**边:节点比**（本 plan 的预算算术用例硬编码了 3:1 这个假设 A2，比值更高时「11 万符号触顶」的结论要下修），以及在 Linux 容器内复现一次（假设 A3）。复校后若改常数，`test_estimate_bytes_matches_budget_arithmetic` 会连带要求同步调整 `CODE_GRAPH_MAX_GRAPH_BYTES`——这正是那条用例存在的意义。
- **Plan 121-08**：`stats()` 目前只有三项（`entries` / `total_bytes` / `max_bytes`）。若要做命中率诊断，需要在该 plan 加 hit/miss 计数器——本 plan 刻意不加，因为没有编排侧就没有「miss」这个概念。

## Threat Flags

无——本 plan 未引入 `<threat_model>` 之外的新安全面（零新增网络入口、零新增鉴权路径、零文件访问、零 schema 变更）。威胁登记表的落地情况：

| Threat ID | Disposition | 落地 | 回归用例 |
|-----------|-------------|------|----------|
| T-121-OOM | mitigate | ✅ 部分（存储侧） | `test_evict_lru_until_within_budget` / `test_evict_loop_drops_multiple_entries` / `test_estimate_bytes_matches_budget_arithmetic`。**装配前用 COUNT 做准入**那半条在 121-08，本 plan 已备好 `_max_graph_bytes` 与纯函数判据 |
| T-121-记账漂移 | mitigate | ✅ | `test_put_overwrite_does_not_double_count`（含「覆盖成更小条目」的减法方向验证） |
| T-121-跨loop崩溃 | mitigate | ✅ | `test_lock_discipline_documented_and_no_await`（AST：零异步构造 + 未 import asyncio + 有 threading） |
| T-121-用例污染 | mitigate | ✅ | `test_reset_for_tests_returns_fresh_service` + 成对的 `test_singleton_isolation_first/second_writer` + `test_conftest_autouse_fixture_calls_reset` |
| T-121-多worker放大 | accept | — | 按 CONTEXT 接受；模块 docstring 边界① 如实写明「多 worker 各持一份是已知且接受的代价」，由 121-10 的实测与生产 RSS 观察复核默认值 |

## Self-Check: PASSED

- `server/services/code_graph/cache.py` FOUND（320 行 ≥ plan 要求的 150）
- `server/tests/services/code_graph/test_cache.py` FOUND
- `server/tests/services/code_graph/conftest.py` FOUND
- 提交 `09645353` / `766d27b9` / `1f29ffd4` 均在 git 历史中可查
- `grep -c '_reset_for_tests' tests/services/code_graph/conftest.py` → **2**（≥ 1）
- 5 个导出名（`GraphService` / `get_graph_service` / `estimate_graph_bytes` / `NODE_COST_BYTES` / `EDGE_COST_BYTES`）均在 `__all__` 内，与 plan 的 artifacts.exports 逐项对齐
- `cd server && uv run pytest tests/services/code_graph -x -q` → **62 passed, 11 skipped**
- `cd server && uv run pytest codegraph/lsp/tests/test_volar_pool.py -q` → **12 passed**（零回归）
- 2 个用例桩的 `@pytest.mark.skip` 已移除（`test_estimate_bytes_is_pure` / `test_evict_lru_until_within_budget`）
- 三次提交均按显式路径 staging，未出现文件删除；工作区内与本 plan 无关的预存在改动（`server/repositories/` / `server/durable/` / `web/src/` 等 28 项 modified + 13 项 untracked，含 `mcp` / `skills` 两个 submodule）保持未提交、未修改

---
*Phase: 121-graph-base*
*Completed: 2026-08-09*
