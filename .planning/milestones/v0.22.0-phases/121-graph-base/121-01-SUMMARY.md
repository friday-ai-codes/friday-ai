---
phase: 121-graph-base
plan: 01
subsystem: infra
tags: [networkx, pytest, structlog, settings, observability, code_graph]

# Dependency graph
requires: []
provides:
  - "networkx 3.6.1 提升为 server 直接依赖（>=3.6,<4），不再依赖 llama-index 传递"
  - "三个 CODE_GRAPH_* 内存预算 settings（512MB 总 / 256MB 单图 / 120s single-flight 等待）"
  - "LOGGING-SPEC §5 登记 component 取值 code_graph（与索引侧 codegraph 并存）"
  - "server/tests/services/code_graph/ 测试包 + 6 个本目录自建 fixture"
  - "29 个用例桩，覆盖 121-VALIDATION.md 全部 -k 选择器"
affects: [121-02, 121-03, 121-04, 121-05, 121-06, 121-07, 121-08, 121-09, 121-10]

# Tech tracking
tech-stack:
  added: [networkx>=3.6 <4]
  patterns:
    - "预算配置注释里写死字节算术与 per-worker 边界，供后人调参"
    - "测试子包 conftest 全部 fixture 自建 + lazy import ORM 模型"
    - "用例桩上方注明对应 VALIDATION 行为与交付它的 Plan"

key-files:
  created:
    - server/tests/services/code_graph/__init__.py
    - server/tests/services/code_graph/conftest.py
    - server/tests/services/code_graph/test_model.py
    - server/tests/services/code_graph/test_loader.py
    - server/tests/services/code_graph/test_signature.py
    - server/tests/services/code_graph/test_cache.py
    - server/tests/services/code_graph/test_access.py
  modified:
    - server/pyproject.toml
    - server/uv.lock
    - server/friday/settings.py
    - .planning/observability/LOGGING-SPEC.md

key-decisions:
  - "in-flight 超时复用既有 GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES，不新增配置项（防两个阈值漂移导致长鸣降级）"
  - "networkx 用 >=3.6,<4 而非锁死 ==3.6.1，避免与 llama-index 的版本解析冲突"
  - "component 取 code_graph（有下划线）与索引侧 codegraph 并存，两条链路日志可分开筛"
  - "补 3 个原 Task 清单遗漏、但 VALIDATION 追加表要求的选择器桩（exclusion_resolved_once / memo / barrel）"

patterns-established:
  - "预算类 settings：显式 : int 注解 + env.int + 多行中文注释写清算术与 per-worker 语义"
  - "测试子包隔离：conftest 不跨兄弟目录复用 fixture，indexed_repo 显式 index_status=INDEXED"
  - "Wave 0 用例桩：@pytest.mark.skip + 注明交付 Plan，桩体不 import 尚不存在的模块"

requirements-completed: [GRAPH-01, GRAPH-02, GRAPH-03, GRAPH-04]

# Metrics
duration: 31min
completed: 2026-08-09
---

# Phase 121 Plan 01: 内存图服务基座脚手架 Summary

**networkx 提升为直接依赖 + 三个 per-worker 字节预算 settings + LOGGING-SPEC 登记 `code_graph` + 可收集的 `tests/services/code_graph/` 测试包（6 fixture / 29 个用例桩，VALIDATION 的每个 `-k` 选择器都有落点）**

## Performance

- **Duration:** 约 31 分钟（含一次 18 分钟的既有套件回归跑）
- **Started:** 2026-08-09T04:49:30Z
- **Completed:** 2026-08-09T05:21:00Z
- **Tasks:** 3
- **Files modified:** 11（4 修改 + 7 新建）

## Accomplishments

- **依赖面收口**：`networkx` 从 `uv.lock:2371` 的 llama-index 传递依赖提升为 `pyproject.toml` 直接依赖，锁文件同步；上游停止传递不再导致运行期 `ImportError`。
- **预算面落地**：`CODE_GRAPH_CACHE_MAX_BYTES` / `CODE_GRAPH_MAX_GRAPH_BYTES` / `CODE_GRAPH_BUILD_WAIT_TIMEOUT_SECONDS` 三项可从 settings 读取、可被环境变量覆盖，注释里写死了 `n × 2320` 字节的预算算术与「这是 per worker」的运维警告。
- **规范面登记**：`code_graph` 进入 LOGGING-SPEC §5 组件清单，并补了一段说明解释它与索引侧 `codegraph` 为何刻意并存——满足 `.cursor/rules/observability-logging.mdc` 的强制要求。
- **验证面打通**：`tests/services/code_graph/` 可被 pytest 收集，29 个桩全 skip、0 failed、0 error；121-VALIDATION.md 里全部 25 个 `-k` 选择器逐个校验均能选中至少一个用例。

## Task Commits

1. **Task 1: 依赖提升、`CODE_GRAPH_*` 配置项与 LOGGING-SPEC 组件登记** — `e746a0a3` (chore)
2. **Task 2: 测试包与本目录自建 fixture** — `658ac913` (test)
3. **Task 3: 五个用例桩文件** — `058a81ac` (test)

**Plan metadata:** 见本文件的收尾 docs 提交。

## Files Created/Modified

- `server/pyproject.toml` — 新增 `networkx>=3.6,<4`，上方注释说明来源与不锁死版本的理由
- `server/uv.lock` — `uv add` 同步（networkx 从传递依赖变为顶层依赖声明）
- `server/friday/settings.py` — 紧邻 `GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES` 追加三个 `CODE_GRAPH_*` 常量与预算算术注释
- `.planning/observability/LOGGING-SPEC.md` — §5 组件清单追加 `code_graph` + 并存说明
- `server/tests/services/code_graph/__init__.py` — 空文件，与 `tests/services/retrieval/` 目录约定一致
- `server/tests/services/code_graph/conftest.py` — `indexed_repo` / `branch_index` / `symbols_factory` / `call_edges_factory` / `exclusion_rule_factory` + autouse 的 `_reset_code_graph_state`
- `server/tests/services/code_graph/test_model.py` — 2 个桩（Plan 121-02 填充）
- `server/tests/services/code_graph/test_loader.py` — 5 个桩（Plan 121-05 / 121-06 填充）
- `server/tests/services/code_graph/test_signature.py` — 4 个桩（Plan 121-04 填充）
- `server/tests/services/code_graph/test_cache.py` — 11 个桩（Plan 121-04 / 121-07 / 121-08 / 121-09 填充）
- `server/tests/services/code_graph/test_access.py` — 7 个桩（Plan 121-03 / 121-05 / 121-09 填充）

## Decisions Made

- **保留 `GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES` 的显式引用**：settings 注释里点名这个既有常量，说明「in-flight 判定复用它、不新增阈值」。让后人一眼看到复用关系，比迎合一条粗粒度 grep 更重要（见 Deviations）。
- **`env.int(...)` 保持多行写法**：`ruff format` 会把它折成单行，但相邻的 `GRAPH_BUILD_ORPHAN_*` 也是多行，且 `server/friday/settings.py` 在 HEAD 就不是 format-clean、CI 只跑 advisory 的 `ruff check`。跟邻居保持一致优先。
- **临时 fixture 冒烟用例跑完即删**：Task 2 的「fixture 可实例化」用一个临时用例真跑了一遍（`indexed_repo.index_status == INDEXED`、解析边/裸名边/排除规则均创建成功），验证通过后删除——因为 Task 3 的验收要求本目录「全部 skipped」，留一个 passed 用例会破坏该断言。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] 补 3 个 VALIDATION 要求但 Task 3 清单遗漏的用例桩**

- **Found during:** Task 3（五个用例桩文件）
- **Issue:** Task 3 枚举的 26 个用例名覆盖了 VALIDATION 主表的选择器，但漏了「计划外补充的自动化验证」表里的三个：`-k exclusion_resolved_once`（121-08）、`-k memo`（121-03）、`-k barrel`（121-09）。`pytest -k` 选不中任何用例时退出码是 5，这三个 plan 的 `<automated>` 命令会从第一次运行就报失败——正是 Wave 0 要消灭的 Nyquist 缺口，且 Task 3 的验收条款本身就要求「VALIDATION 中出现的每一个 `-k` 选择器都能选中至少 1 个用例」。
- **Fix:** 追加 `test_exclusion_resolved_once_per_call`（test_cache.py）、`test_matcher_fingerprint_memo_ttl`、`test_barrel_exports_are_curated`（test_access.py），形态与其余桩一致。
- **Files modified:** `server/tests/services/code_graph/test_cache.py`、`server/tests/services/code_graph/test_access.py`
- **Verification:** 25 个选择器的逐个 `--collect-only` 循环全过（`ALL_SELECTORS_OK`）
- **Committed in:** `058a81ac`（Task 3 提交）

### 验收命令的机械化调整（两处 grep 过粗，intent 已满足）

这两处不是实现偏离，是**验收 grep 的字面表达与 action 指令自相矛盾**，取 action 指令的语义、并给出更精确的检查式：

**a. `git diff server/friday/settings.py | grep -c '^+.*TIMEOUT_MINUTES'` 期望 0，实际 1**

Task 1 的 action 明确要求「在注释里显式写明复用 `GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES` 这条决策」，而该 grep 会连注释里的引用一起命中。真实意图是「未新增 `*_TIMEOUT_MINUTES` 配置项」，精确检查式为：

```
git diff server/friday/settings.py | grep -c '^+.*TIMEOUT_MINUTES: int = env.int'   # → 0 ✅
```

**b. `grep -c 'tests.codegraph' conftest.py` 期望 0，实际 2**

两处都是模块 docstring 里对兄弟目录 `tests/codegraph/conftest.py` 的**散文引用**（解释为什么本目录 fixture 必须自建），grep 里的 `.` 作为正则通配符匹配到了路径分隔符 `/`。真实意图是「没有跨目录 import」，精确检查式为：

```
grep -Ec '(from|import) +tests\.codegraph' conftest.py   # → 0 ✅
```

---

**Total deviations:** 1 auto-fixed（Rule 2 缺失关键功能）+ 2 处验收命令的机械化澄清
**Impact on plan:** 无 scope creep。补的三个桩恰好落在 plan 自己的验收条款内；两处 grep 澄清不改变任何代码行为。

## Issues Encountered

**既有套件回归跑出 4 个 failed，均与本 plan 无关，属预存在环境/工作区问题：**

`cd server && uv run pytest tests/codegraph tests/code_relations -q` → **4 failed, 890 passed, 20 skipped**。

1. `tests/code_relations/test_models.py::test_chunkedge_fan_in_query_uses_target_index` — 该用例硬编码 SQLite 方言的 `EXPLAIN QUERY PLAN`（`test_models.py:276`），而本机 `.env` 把测试库指向 PostgreSQL，报 `psycopg.errors.SyntaxError: syntax error at or near "QUERY"`。属**测试与 DB 后端耦合**的既有缺陷，与本 plan 零关系。
2. `tests/codegraph/test_repo_summary_builder.py` 的 3 个用例 — 单独重跑**全部通过**，仅在全量顺序下失败；工作区里 `server/repositories/summary_service.py` 等文件带有本 plan 之外的未提交改动，是更可能的成因。

按 scope boundary 纪律**不做修复**（本 plan 只动依赖声明、三个 settings 常量、一份文档和一个全新测试目录，物理上不可能影响这两处）。建议登记为 Phase 121 之外的独立事项。

**Lint / 类型检查：**

- `uv run ruff check .` → 276 errors，**其中 0 条落在本 plan 触碰的文件**（全量 ruff 在本仓是 advisory baseline，CI 不阻塞）。
- `uv run mypy friday/settings.py tests/services/code_graph` → 唯一 1 条错误在 `workflows/schemas/technical_plan.py`（预存在），本 plan 文件 0 错误。

## User Setup Required

None — 无外部服务配置。`CODE_GRAPH_*` 三项均有保守默认值，部署方无需设置环境变量即可运行；需要调参时再按 settings 注释里的算术覆盖。

## Next Phase Readiness

**已就绪：**

- 后续 9 个 plan 的每个 task 都能跑 `cd server && uv run pytest tests/services/code_graph -x -q`（当前 29 skipped，反馈延迟 < 4 秒）并解析到真实用例名。
- `import networkx` 在 server venv 内可用（3.6.1）；`settings.CODE_GRAPH_*` 三项可读，实测值 `536870912 / 268435456 / 120`。
- `indexed_repo` fixture 天然通过 Plan 121-03 将要实现的 `ensure_repository_readable` 索引态闸门。

**留给后续 plan 的显式待办：**

- **Plan 121-07** 交付 `GraphService._reset_for_tests()` 后，必须回填进 `conftest.py::_reset_code_graph_state`（当前该 fixture 只清 exclusion matcher 的 60s TTL 缓存，模块级单例还没得可清，docstring 已标注）。
- **Plan 121-10** 的最大仓内存实测出数后，回来复校 `CODE_GRAPH_CACHE_MAX_BYTES` / `CODE_GRAPH_MAX_GRAPH_BYTES` 默认值与 `NODE_COST=640 / EDGE_COST=560` 两个常数（tracemalloc 不含 arena 碎片，真实 RSS 通常更高）。同时它自带的 `-m perf` 诊断用例由该 plan 自己创建，本 plan 未预置 perf 桩。

## Self-Check: PASSED

7 个新建文件全部存在；3 个 task 提交 `e746a0a3` / `658ac913` / `058a81ac` 均在 git 历史中可查。

---
*Phase: 121-graph-base*
*Completed: 2026-08-09*
