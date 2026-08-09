---
phase: 121-graph-base
plan: 04
subsystem: infra
tags: [code_graph, cache-signature, in-flight, two-tracks, fail-quiet, observability]

# Dependency graph
requires:
  - phase: 121-01
    provides: "tests/services/code_graph/ 测试包与 indexed_repo / branch_index fixture、GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES 复用决策"
  - phase: 121-02
    provides: "GraphMeta.built_signature 签名落点字段"
  - phase: 121-03
    provides: "build_matcher_and_fingerprint 产出的 16 位 exclusion 规则指纹（excl: 分量入参）、test_observability_contract AST 守护"
provides:
  - "compute_signature(repository_id, branch, *, exclusion_fingerprint)：7 分量复合签名（wm / ihA / ghB / repoG / nsym / ncall / excl）"
  - "detect_edge_build_in_flight(repository_id, branch) -> (bool, reason)：四个原因短码，三种「疑似在途」情形一律判不在途"
  - "ihA: 分量刻意排除 started_at —— 121-08 让在途翻转而签名不变的唯一支点"
  - "两个 DEBUG 埋点 code_graph_signature_computed / code_graph_edge_build_in_flight"
affects: [121-05, 121-07, 121-08, 121-09, 121-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "签名分量拆成 per-分量私有函数，每个函数的 docstring 承载该分量的失效场景与反面教材"
    - "「无行」用等长占位元组表达，靠真实行首项恒为 UUID 保证两者不碰撞"
    - "回归用例自带反证段：证明判据不误报之后，再证明它不是恒假的"

key-files:
  created:
    - server/services/code_graph/signature.py
  modified:
    - server/tests/services/code_graph/test_signature.py
    - server/tests/services/code_graph/test_cache.py

key-decisions:
  - "埋点不抽通用 _emit(event, **fields) 转发器，两个事件各自成函数把常量写在第一个位置实参上——121-03 的 AST 观测契约要求事件名可静态解析，转发器只会让它看到一个形参名（本 plan 实际被这条契约拦下过一次）"
  - "signature 的 ihA: 排除 started_at、in-flight 的轨 A 判据要求 started_at >= cutoff：两个判据共用同一批字段但口径必须错开，签名答「数据变了吗」、在途答「现在正在写吗」"
  - "轨 B 的 RUNNING 不单看 Repository 聚合态，额外要求一条新鲜的 RUNNING GraphBuildHistory 佐证——聚合态自己也会被崩溃的 worker 留成孤儿"
  - "detect_edge_build_in_flight 收下 branch 参数但当前只用于埋点归因：两条轨的在途判据都是仓库级的，假装它按分支精确会误导 121-08 的调用方"

requirements-completed: []

# Metrics
duration: 20min
completed: 2026-08-09
---

# Phase 121 Plan 04: 复合签名与 in-flight 边构建判定 Summary

**`services/code_graph/signature.py` 落地：7 分量复合签名（同时纳入两条互相独立的边构建轨，D-02）+ 三条件复合的 in-flight 判定（同时躲开 PENDING 默认值长鸣与 RUNNING 孤儿卡死，D-03），两条边构建轨的独立敏感性做了双向反证**

## Performance

- **Duration:** 约 20 分钟
- **Started:** 2026-08-09T05:56:00Z
- **Completed:** 2026-08-09T06:15:31Z
- **Tasks:** 3
- **Files modified:** 3（1 新建 + 2 修改）

## Accomplishments

- **签名同时盯住两条轨，且每条都单独可证**。`ihA:`（`IndexHistory` / ChunkEdge）与 `ghB:` + `repoG:`（`GraphBuildHistory` / Symbol·CallEdge）互不重叠地读各自的表。`test_signature_generation_two_tracks` 的两个分支每段只动一条轨的字段，另一条全程静止——并且**做了双向反证**：临时抽掉 `_track_a_part` 后 (a) 段如期红（"新增 IndexHistory 未改变签名（轨 A 缺失）"），抽掉 `_track_b_parts` 后 (b) 段如期红，两次改动均已还原、`git diff` 干净。这条是 D-02 的核心，CONTEXT 原文只提到了轨 A，而 `CallEdge` 恰恰是本相位图的主边源。
- **降级标记不会长鸣**。`test_pending_not_inflight` 把轨 A 的三条件判据锁成五段：无 history 行、`PENDING` + 已终态、`SKIPPED` + 行仍在跑，三段判不在途；再用「真在途」与「真 PENDING 在途」两段反证判据不是恒假的——只写前三段的话，把整个函数改成 `return False, ""` 也能全绿，降级保护会静默消失而无人察觉。
- **孤儿不会永久卡死一个仓**。`test_orphan_running_not_inflight` 用 `GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES + 5` 分钟前的 `started_at` 造孤儿，断不在途；同一行改成 1 分钟前立刻转为在途。阈值直接 `getattr(settings, ...)` 复用既有常量，**没有新增任何配置项**——`grep -n TIMEOUT signature.py` 只有两处命中，一处是注释里对该常量的引用，一处是读取它本身。
- **给 121-08 留的支点是精确的**。`ihA:` 的 `values_list` 是 `id / graph_build_status / status / finished_at / payload_synced_at / edge_count` 六项，**不含 `started_at`**；而轨 A 的在途判据要求 `started_at >= cutoff`。这个差异是 121-08 的回归用例「让在途翻转但签名不变」唯一能用的杠杆，已写进 `_track_a_part` 的 docstring 并说明理由（否则后人"顺手补全字段"就会把它抹掉）。
- **水位分量的键翻译有可执行证据**。`test_signature_watermark_sensitive` 第一段只改 `RepositoryBranchIndex.last_indexed_commit_sha`、不动 `Repository` 的——签名若不变就说明查询没命中 `is_base_branch=True`、静默退化成了永远走仓库级回落。第二段另造一个无分支索引行的仓库验证回落路径本身。
- **无行与空行不会碰撞**。两条轨的「无 history」用等长占位元组（`("-",) * 6` / `("-",) * 5`）表达，长度对齐保证分量结构一致；而两者永不互相冒充，因为真实行的第一项是 `id`（UUID），永远不是 `"-"`。

## Task Commits

1. **Task 1: `compute_signature` 骨架——水位、计数与 exclusion 指纹三分量** — `20d2d643` (feat)
2. **Task 2: 两条边构建轨的代数分量（D-02）** — `7a8e8dad` (feat)
3. **Task 3: `detect_edge_build_in_flight`——躲开 PENDING 长鸣与 RUNNING 孤儿（D-03）** — `066c9673` (feat)

**Plan metadata:** 见本文件的收尾 docs 提交。

## Files Created/Modified

- `server/services/code_graph/signature.py`（新建，384 行）— 三段式模块 docstring（含四条边界）/ 2 个 `Final[str]` 事件名常量 + 2 个专用埋点函数 / 4 个分量私有函数 / 2 个导出函数；`compute_signature` 的 docstring 带分量表与两轨对照表
- `server/tests/services/code_graph/test_signature.py` — 4 个桩全部转真实断言（稳定性 / 水位双路径 / 两轨独立敏感 / 指纹穿透）
- `server/tests/services/code_graph/test_cache.py` — 本 plan 负责的 2 个桩转真实断言（`test_pending_not_inflight` 五段、`test_orphan_running_not_inflight` 两段），其余 9 个桩留给 121-07/08/09

## Decisions Made

- **埋点不抽通用转发器**：最初写成 `_emit(event: str, **fields)` 统一加 `component` / `category`，被 121-03 的 `test_observability_contract` 当场拦下（`signature.py:80:<unresolved> 事件名不是字符串字面量/模块级字面量常量`）。改成两个专用函数、把 `Final[str]` 常量直接写在 `logger.debug` 的第一个位置实参上。**这是契约按设计生效的一次，不是契约过严**——转发器一旦成立，后人往里传 f-string 就没人拦得住了。理由已写进代码注释，防后人再抽一次。
- **两个埋点取 DEBUG 而非 INFO**：这两个函数在**每次** `get_graph` 都会跑（含缓存命中的那些），INFO 会直接违反 `.cursor/rules/observability-logging.mdc` 的级别纪律。`category="sampling"` 与 `component="code_graph"` 齐备，`duration_ms` 挂在签名计算上。
- **轨 B 的 RUNNING 需要 history 行佐证**：只看 `Repository.graph_build_status == RUNNING` 是不够的——那个聚合态由 `reset_repository_graph_progress` 写入、由 `mark_repository_graph_terminal` 收尾，中途崩溃的 worker 会把它留在 RUNNING。要求一条 `started_at >= cutoff` 的 RUNNING `GraphBuildHistory` 佐证，才让超时兜底真正生效。
- **`detect_edge_build_in_flight` 的 `branch` 当前只用于埋点**：签名保留了完整的按分支口径（`ghB:` 按 `branch_name` 过滤、计数走 overlay），但在途判定的两条轨都是仓库级的（`Repository.graph_build_status` 与最近一条 `IndexHistory` 都不分分支）。参数照 plan 的接口签名收下，语义缺口如实写进 docstring，不假装它按分支精确。

## Deviations from Plan

**None — plan executed exactly as written.**

三个 task 的 action 与验收条款逐条落地，无 Rule 1–4 触发，无 scope creep。一处**验收 grep 的字面表达过粗**需要说明：

**Task 1 条款「`signature.py` 中不含 `branch_name=""` 形式的 `RepositoryBranchIndex` 过滤」**

`grep -c 'branch_name=""' signature.py` → 1，唯一命中在 `_watermark_part` 的 docstring 里，是那条禁令本身的散文表述（「⛔ 绝不能拿 `branch_name=""` 去查 `RepositoryBranchIndex`」）。真实意图是「没有这种形状的过滤调用」，精确检查式：

```
grep -cE 'filter\([^)]*branch_name=""' services/code_graph/signature.py   # → 0 ✅
grep -c 'is_base_branch' services/code_graph/signature.py                 # → 2 ✅（条款要求 ≥ 1）
```

与 Plan 121-01 记录的两处 grep 澄清同类，不改变任何代码行为。

## Issues Encountered

**观测契约拦截一次（已修，见 Decisions）。** 这是 121-03 交付的 AST 守护第一次对新模块生效，行为符合预期：违规信息精确到 `文件:行号:<unresolved>`。

**Lint / 类型检查：**

- `uv run ruff check services/code_graph/ tests/services/code_graph/` → All checks passed。
- `uv run mypy services/code_graph/` → 唯一 1 条错误落在 `workflows/schemas/technical_plan.py:268`（预存在，121-01 / 121-02 / 121-03 已三次登记），本 plan 的文件 0 错误。

**测试范围：** 按本 plan 的测试预算跑了 `tests/services/code_graph`（**32 passed / 16 skipped**，本 plan 把 6 个桩转成真实断言）与 plan `<verification>` 点名的 `tests/codegraph/test_galaxy_cache.py`（**11 passed，零回归**——本 plan 只新增文件、未触碰 Galaxy 的任何代码路径）。全量 `pytest` 与 `tests/codegraph tests/code_relations` 的 18 分钟回归已排期为 Plan 121-10 的相位闸门；Wave 0 登记的 4 条预存在失败与本 plan 无关，未处理。

## User Setup Required

None — 纯 service 层查询模块，无外部服务、无新增配置项、无迁移。

## Next Phase Readiness

**已就绪：**

- **Plan 121-07（`cache.py`）**：`compute_signature` 可直接作为缓存条目的有效性判据，写进 `GraphMeta.built_signature`；两个函数全同步，由 `cache.py` 一次性 `sync_to_async` 包裹即可（⛔ 不要在本模块内做 async ORM 调用）。
- **Plan 121-08（半新图闸门）**：`detect_edge_build_in_flight` 返回的 `(bool, reason)` 直接映射成 `partial_edges=True` + `partial_reason=<短码>`。四个短码：`symbol_extraction_running` / `indexing` / `chunk_edge_build_pending` / `chunk_edge_build_running`。
  **关键性质（勿动）**：`ihA:` 分量**不含** `started_at`，而轨 A 的在途判据**要求** `started_at >= cutoff`——这是 `test_partial_edges_when_edge_build_running` 能「让在途翻转而签名不变」的唯一杠杆。轨 B 侧同理：`ghB:` 不含 `started_at`，而轨 B 的在途判据按 `started_at__gte=cutoff` 过滤 `GraphBuildHistory`，`test_cache.py` 里已有的双 mutation 造法（`Repository.graph_build_status=RUNNING` + 新鲜 RUNNING history）可直接复用 `test_orphan_running_not_inflight` 的第二段。
- **Plan 121-09（barrel）**：本模块的两个导出名**刻意不进** `services/code_graph/__init__.py` —— 121-02 已定「不导出 loader / cache 是架构红线」，签名与在途判定同属内部判据，上层只应看见 `GraphService`。

**留给后续 plan 的显式待办：**

- **Plan 121-08**：在途判定当前是**仓库级**的，`branch` 参数只用于埋点归因。若 121-08 需要「base 在建、feature 不受影响」这种粒度，得先让边构建本身按分支隔离（`GraphBuildHistory` 有 `branch_name`，`IndexHistory` 没有），属独立事项。
- **Plan 121-10**：`compute_signature` 的成本注释（「与 Galaxy 的 7 条聚合同量级」）是照字段形状推断的，未实测。相位闸门若跑 perf 诊断，顺带把它在最大仓上的实际耗时记一笔。

## Threat Flags

无——本 plan 未引入 `<threat_model>` 之外的新安全面（零新增网络入口、零新增鉴权路径、零文件访问、零 schema 变更）。威胁登记表的四条 `mitigate` 均已落地：`T-121-半新图`（两轨签名 + in-flight 判定）、`T-121-长鸣`（三条件复合判据 + `test_pending_not_inflight`）、`T-121-孤儿`（超时兜底 + `test_orphan_running_not_inflight`）、`T-121-陈旧规则`（`excl:` 分量）。`T-121-签名伪造` 按 accept 处理：`hashlib.sha256` 仅用于非安全用途的缓存一致性比对，不是认证凭证。

## Self-Check: PASSED

- `server/services/code_graph/signature.py` FOUND（384 行 ≥ plan 要求的 110）
- `server/tests/services/code_graph/test_signature.py` FOUND
- `server/tests/services/code_graph/test_cache.py` FOUND
- 提交 `20d2d643` / `7a8e8dad` / `066c9673` 均在 git 历史中可查
- `grep -c 'is_base_branch' signature.py` → 2（≥ 1）；`grep -c 'IndexHistory'` → 7、`grep -c 'GraphBuildHistory'` → 7（各 ≥ 1）
- `grep -n 'TIMEOUT' signature.py` → 2 处命中，全部指向 `GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES`，无新增 `CODE_GRAPH_*_TIMEOUT*`
- 两个导出名 `compute_signature` / `detect_edge_build_in_flight` 均在 `__all__` 内
- `cd server && uv run pytest tests/services/code_graph -q` → **32 passed, 16 skipped**
- `cd server && uv run pytest tests/codegraph/test_galaxy_cache.py -q` → **11 passed**
- 6 个用例桩的 `@pytest.mark.skip` 已全部移除（test_signature.py 4 个 + test_cache.py 2 个）
- 工作区内与本 plan 无关的预存在改动保持未提交、未修改

---
*Phase: 121-graph-base*
*Completed: 2026-08-09*
