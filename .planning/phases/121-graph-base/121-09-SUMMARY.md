---
phase: 121-graph-base
plan: 09
subsystem: api
tags: [code_graph, barrel, curated-exports, cache-invalidation, structlog, asvs-v1, threading]

# Dependency graph
requires:
  - phase: 121-graph-base (121-02)
    provides: "model.py 的 15 项契约（本 plan 从中 re-export 14 项，BARE_NAME_BLACKLIST 刻意留在包内）"
  - phase: 121-graph-base (121-03)
    provides: "access.invalidate_matcher_fingerprint_cache（invalidate 联动清 memo）与 AST 观测契约守护测试"
  - phase: 121-graph-base (121-07/121-08)
    provides: "GraphService / get_graph_service / 字节预算 LRU / _get_graph_sync 的签名复校与在途闸门"
provides:
  - "services.code_graph 的 curated barrel：恰 17 项字母序导出，loader/cache/signature/access 不可从包顶层取得（架构红线的机械防线）"
  - "GraphService.invalidate(repository_id)：按仓驱逐全部分支条目 + 联动清 matcher/指纹 memo，只驱逐不重建，异常内部吞掉"
  - "模块级 invalidate_repository(repository_id)：构建完成钩子的唯一公开入口"
  - "两处构建完成钩子（ChunkEdge 边构建轨 A / Symbol·CallEdge 抽取轨 B）接上主动驱逐"
  - "code_graph_cache_invalidated / code_graph_cache_invalidate_failed 两个 structlog 事件"
affects: [121-10, 122-impact-analysis, 上层图分析工具（MCP / AI 对话）]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "curated barrel 作为架构红线的机械防线（形态照 services/code_intel/__init__.py：绝对导入 + 字母序 __all__ + docstring 写明使用边界）"
    - "逐字写死期望导出面的守护测试（⛔ 不从被测模块反查自证）"
    - "构建完成钩子只经包根公开面调用，钩子自身不得 reach into 包内子模块"

key-files:
  created: []
  modified:
    - server/services/code_graph/__init__.py
    - server/services/code_graph/cache.py
    - server/code_relations/tasks.py
    - server/services/graph_builder.py
    - server/tests/services/code_graph/test_access.py
    - server/tests/services/code_graph/test_cache.py

key-decisions:
  - "barrel 恰 17 项 = model.py 的 14 项契约 + GraphService + get_graph_service + invalidate_repository；BARE_NAME_BLACKLIST 留在 model.__all__ 但不上包顶层（裸名过滤的内部细节）"
  - "invalidate 只驱逐不重建（与 GalaxyGraphCache.refresh_repo 的驱逐+重建刻意不同）：重建要在钩子线程上跑 2-4 秒纯 CPU，会拖慢索引流水线"
  - "invalidate 按仓（key[0]）驱逐全部分支条目，而非按 (repo, branch) 单键：overlay 语义下 feature 分支图 = base 全量 + 分支增量，重索引会同时证伪所有分支"
  - "invalidate 刻意不动 _inflight：领头请求可能在驱逐之后回写，那条回写带的是它自己那一刻的签名，下一次取图的签名复校会照常判掉"
  - "异常吞掉分两层（GraphService.invalidate 内部 + 模块级 invalidate_repository 外层），少吞一层就会让缓存维护故障把构建的成功出口变成失败"
  - "钩子必须 from services.code_graph import invalidate_repository（包根），钩子自己绕过 barrel 会让导出面守护测试形同虚设"

patterns-established:
  - "架构红线机械化：不导出把「绕过校验」从『需要自律』降级为『需要刻意书写内部模块路径』（ASVS V1）"
  - "主动失效 + 签名复校是两道独立闸：钩子只对本 worker 生效，签名比对不可删除，该理由在 cache.py 与两处钩子共三处留痕"

requirements-completed: [GRAPH-01, GRAPH-02, GRAPH-04]

# Metrics
duration: 45min
completed: 2026-08-09
---

# Phase 121 Plan 09: 包封口（curated barrel）+ 构建完成失效钩子 Summary

**`services.code_graph` 的公开面收敛为恰 17 个符号（loader/cache/signature/access 一律不导出），并在 ChunkEdge 边构建与 Symbol/CallEdge 抽取两处完成点各接上一行经包根调用的 fail-soft 主动驱逐**

## Performance

- **Duration:** 45 min
- **Started:** 2026-08-09T08:01:00Z
- **Completed:** 2026-08-09T08:46:00Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- **架构红线从「靠自律」变成「靠 import 失败」**：`__init__.py` 由占位替换为 curated barrel，恰 17 项字母序导出；`loader` / `cache` / `signature` / `access` 与 `estimate_graph_bytes` / `NODE_COST_BYTES` / `invalidate_matcher_fingerprint_cache` 均不可从包顶层取得。想绕过 `GraphService.get_graph()` 的权限 / exclusion / 水位三道闸，必须刻意写出内部模块路径——那在 code review 里藏不住（威胁登记 T-121-绕闸，ASVS V1）。
- **`GraphService.invalidate` 按仓驱逐 + 联动清指纹 memo**：弹出该仓**全部分支**条目并扣减字节记账，同时清 `access` 的 matcher/指纹 memo（否则规则已变而指纹仍是 60s 旧值时，签名复校算出的签名与旧条目恰好一致，陈旧图照样命中）。只驱逐不重建；全部异常内部吞掉。
- **两处构建完成钩子接上主动驱逐**：`code_relations/tasks.py` 的 `inserted > 0` 块（轨 A）与 `services/graph_builder.py` 的成功出口（轨 B），各在既有 `GalaxyGraphCache.refresh_repo` 紧邻加一行 `await sync_to_async(invalidate_repository)(repository_id)`，均从**包根**函数内 lazy import。
- **「失效不替代签名校验」在三处代码留痕**：`cache.py::invalidate` 的 docstring 与两处钩子注释都写明「只对本 worker 生效，多 worker 部署下旧图仍靠取图时的签名复校发现陈旧，故 `_get_graph_sync` 的签名比对不可删除」。
- **测试：`tests/services/code_graph` 86 passed / 0 skipped**（基线 81 passed / 2 skipped——两个 skip 桩即本 plan 的交付物，替换为 5 个真用例）。

## Task Commits

Each task was committed atomically:

1. **Task 1: invalidate 能力 + curated barrel `__init__.py`** — `8f47f36f` (feat)
2. **Task 2: 两处构建完成钩子接上主动驱逐** — `1c5006d1` (feat)

**Plan metadata:** `_(见下方 final commit)_` (docs: complete plan)

## Files Created/Modified

- `server/services/code_graph/__init__.py` — 占位 → curated barrel。三段式 docstring（用什么 / 架构红线 / 不导出什么）写明红线**理由**：`get_graph` 是权限校验、exclusion 过滤、水位一致性校验三道闸的唯一收口点，绕过它等于同时绕过三道。绝对导入，`__all__` 恰 17 项字母序。
- `server/services/code_graph/cache.py` — 新增 `GraphService.invalidate`、模块级 `invalidate_repository`、`_log_invalidate_failed`，以及 `_EVENT_CACHE_INVALIDATED` / `_EVENT_CACHE_INVALIDATE_FAILED` 两个事件常量；`__all__` 补 `invalidate_repository`。
- `server/code_relations/tasks.py` — 边构建完成钩子（轨 A）加一行主动驱逐 + 防误删注释。
- `server/services/graph_builder.py` — 图谱构建完成钩子（轨 B）同款。
- `server/tests/services/code_graph/test_access.py` — 移除 barrel 桩，新增 `test_barrel_exports_only_public_surface`（逐字写死 17 个字面量 + 7 项禁止名 + 字母序 + 每项可取到 + 实际 import 形态）与 `test_barrel_docstring_records_the_architecture_red_line`（docstring 含「架构」「loader」，源码不含相对导入）。
- `server/tests/services/code_graph/test_cache.py` — 移除 invalidate 桩，新增 `test_invalidate_evicts_repo_entries`（两分支 + 邻仓隔离 + 记账扣减 + memo spy + 汇总事件 + 幂等）、`test_invalidate_swallows_errors_and_never_breaks_the_hook`（两层吞异常）、`test_invalidate_repository_delegates_to_the_singleton`。

## Decisions Made

- **barrel 算术锚定在 model.py 的 15 项上**：`model.__all__` 有 15 项，barrel 只 re-export 其中 14 项——`BARE_NAME_BLACKLIST` 是裸名过滤的内部细节，留在 `model.__all__` 供包内使用但不上包顶层；`REDACTED_REPOSITORY` 是跨仓折叠的返回契约，**在** barrel 里。14 + 3 = 17。
- **任务顺序按计划先 `invalidate` 后 barrel**：反过来 barrel 会导出一个还不存在的名字，import 直接炸。
- **`invalidate` 里 `logger.info` 也放在 try 内**：整个方法 best-effort，观测失败与驱逐失败走同一个 warning 出口，不为了区分二者多写一层嵌套。
- **memo 清理用关键字实参 `repository_id=`**：让 spy 断言能写成 `assert_called_once_with(repository_id="repo-a")`，比断言位置实参更抗重构。
- **format 漂移不顺手修**：`ruff format --check` 显示本包 9 个文件（含 `access.py` / `loader.py` / `signature.py` 等**本 plan 未触碰**的文件）都会被重排——这是本相位既有状态（已逐个用 `git show HEAD:<path> | ruff format --check -` 核对，在 HEAD 上就已漂移），不是本 plan 引入。逐字重排未触碰文件会污染 diff、违反 scope boundary，故不做；`ruff check` 在本 plan 触碰的全部 6 个文件上通过。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 钩子注释里的示例文本触发了自己的守护命令**

- **Found during:** Task 2（两处构建完成钩子）
- **Issue:** 注释原文写的是「直连 ``services.code_graph.cache`` 正是它要挡住的架构违规」——这句**散文**里含字面量 `code_graph.cache`，于是 acceptance 的机械守护 `test "$(grep -l 'code_graph.cache' code_relations/tasks.py services/graph_builder.py | wc -l)" -eq 0` 直接判红。守护本身是对的（它就该按字面量扫），是注释措辞踩了它。
- **Fix:** 两处改写为「直连包内 ``cache`` 子模块正是它要挡住的架构违规（红线连钩子自己也不例外，否则那道守护测试形同虚设）」——语义完全保留、且把「钩子自己也受约束」这层意思写得更明白，同时不再含被禁字面量。
- **Files modified:** `server/code_relations/tasks.py`、`server/services/graph_builder.py`
- **Verification:** `grep -l 'code_graph.cache' ... | wc -l` = 0；`grep -l 'from services.code_graph import invalidate_repository' ... | wc -l` = 2；两处注释仍各含「签名」与「多 worker」。
- **Committed in:** `1c5006d1`（Task 2 commit）

**2. [Rule 2 - Missing Critical] 测试用例名按计划正文对齐，并补两条计划要求但未列进 artifacts 的用例**

- **Found during:** Task 1
- **Issue:** Wave 0 留的桩叫 `test_barrel_exports_are_curated`，而计划的 acceptance 与 artifacts 两处都写 `test_barrel_exports_only_public_surface`；另外 acceptance 还要求「异常吞掉」与「docstring 含『架构』与『loader』」两条断言，但 artifacts 只列了一个用例名。
- **Fix:** 桩按计划正文改名为 `test_barrel_exports_only_public_surface`；docstring 红线留痕与两层异常吞掉各独立成一个用例（`test_barrel_docstring_records_the_architecture_red_line` / `test_invalidate_swallows_errors_and_never_breaks_the_hook`），另补 `test_invalidate_repository_delegates_to_the_singleton` 守「模块级入口必须打进程单例、不能误建新实例」。计划的 `-k "export or barrel"` 与 `-k invalidate` 选择器对新名字全部可解析。
- **Files modified:** `server/tests/services/code_graph/test_access.py`、`server/tests/services/code_graph/test_cache.py`
- **Verification:** `uv run pytest tests/services/code_graph -q` → 86 passed，**0 skipped**。
- **Committed in:** `8f47f36f`（Task 1 commit）

---

**Total deviations:** 2 auto-fixed（1 blocking、1 missing critical）
**Impact on plan:** 两条都是把计划的既定意图落准，没有扩大范围。Task 2 的编辑面严格限于两处钩子点各 +12/13 行（纯新增，无删除、无重构）。

## Issues Encountered

- **`tests/code_relations` 的既有失败**：`test_chunkedge_fan_in_query_uses_target_index` 红（309 passed / 1 failed）。这条是**本 plan 之前就存在**的已知失败（编排方明确列为 out of scope），与两处钩子无关——钩子只在成功出口新增一行，不改任何查询或索引。零回归。
- **`ruff format` 在本包有既有漂移**：见上方 Decisions，已核对为 HEAD 上的既有状态。
- **⚠️ 仓库级 `ruff check .` 当前红（276 errors，221 可 `--fix`）**：全部落在 `workflows/nodes/**` 等**与本相位无关**的文件上（`rg 'code_graph|graph_builder.py|code_relations/tasks.py'` 在报错输出里 0 命中；工作树另有大量不相关的未提交改动）。本 plan 触碰的 6 个文件 `ruff check` 全绿。**这条要留给 121-10 的相位门处理**——它是全量 `ruff check .` + `mypy .` 的把关点，届时要先判定这 276 条属于既有债务还是并行工作引入。
- **`mypy` 的既有报错**：`workflows/schemas/technical_plan.py:268`（编排方列为 out of scope），`services/code_graph/` 6 个源文件自身零报错。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **包已封口**，Phase 122 起的上层图分析工具只能拿到 `GraphService` / `get_graph_service` / `invalidate_repository` + 14 项数据契约；任何直连 `loader` 的写法在 code review 与 `test_barrel_exports_only_public_surface` 两道上都会被拦。
- **相位剩最后一个 plan（121-10）**：全量测试门（`uv run pytest`、`ruff check .`、`mypy .`）与「最大仓实测」复校 `NODE_COST_BYTES` / `EDGE_COST_BYTES`（须按 **RSS** 而非 tracemalloc 口径），以及把 `code_graph` 写进 `LOGGING-SPEC §5` 组件清单（D-07）。本 plan 新增的两个事件名 `code_graph_cache_invalidated` / `code_graph_cache_invalidate_failed` 需一并登记进事件目录。
- **GRAPH-01..04 未在 REQUIREMENTS.md 标 Complete**：相位在 121-10 才闭合，本 plan 刻意不勾。
- 冻结面 `server/codegraph/services/repo_router_v2.py` 全程未触碰（`git diff --name-only` 已断言）。

## Self-Check: PASSED

- 6 个交付文件全部存在于磁盘（`__init__.py` / `cache.py` / `tasks.py` / `graph_builder.py` / `test_access.py` / `test_cache.py`）。
- 2 个任务提交在 git 历史中可查：`8f47f36f`、`1c5006d1`；两次提交均**零文件删除**（`git diff --diff-filter=D HEAD~1 HEAD` 空）。
- 机械守护全绿：barrel 17 项 + 字母序 + 无相对导入（`grep -c 'from \.'` = 0）；钩子包根导入计**文件数** = 2；`code_graph.cache` 字面量计文件数 = 0；冻结面 `server/codegraph/services/repo_router_v2.py` 不在 `git diff --name-only` 中。
- `tests/services/code_graph`：**86 passed / 0 skipped**（两个 skip 桩已由 5 个真用例取代）。

---
*Phase: 121-graph-base*
*Completed: 2026-08-09*
