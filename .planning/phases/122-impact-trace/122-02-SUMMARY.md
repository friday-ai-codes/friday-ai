---
phase: 122-impact-trace
plan: 02
subsystem: code-graph
tags: [symbol-resolution, disambiguation, pure-function, observability, barrel-boundary]

# Dependency graph
requires:
  - phase: 121-graph-base
    provides: "MultiDiGraph 内存契约（节点恒 5 属性）、17 名 barrel、AST 观测契约与 barrel 守护测试"
  - plan: 122-01
    provides: "known_topology 冻结图 fixture 与 test_symbol_resolve.py 的两个 Wave 0 桩"
provides:
  - "resolve_symbol_in_graph：impact 与 trace 共用的图内符号解析器（uid 优先 + 重名候选列表）"
  - "SymbolCandidate / SymbolResolution：D-19 候选面的两个冻结值对象，signature 列留给壳层 ORM 补取"
  - "CANDIDATE_LIMIT=20 与 total_candidates/truncated：agent 判断「看到的是不是全部」的依据"
  - "__init__.py docstring 里 D-28 的边界裁决（新内核不进 barrel / 包内 vs 包外兄弟模块 / 观测契约仍管到包外）"
affects: [122-03, 122-04, 122-05, 122-07, 122-08, 122-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "解析器返回「要么唯一答案、要么候选列表」的二选一不变式，不存在 resolved 与 candidates 并存的中间态"
    - "候选排序键带第三项 symbol_id，让同文件同名多符号的前 N 条在不同 worker 间可复现"

key-files:
  created:
    - server/services/code_graph/symbol_resolve.py
  modified:
    - server/services/code_graph/__init__.py
    - server/tests/services/code_graph/test_symbol_resolve.py

key-decisions:
  - "命中恰 1 个时 candidates 置空而非放入那一条，把「resolved 非空 ⇒ 无候选」写成可依赖的不变式"
  - "file_path 后缀匹配卡在 / 边界上，避免 r.go 匹上 user.go 这种「收窄参数反而放进不相干符号」"
  - "uid 落空时不回落按名字搜，且用一条同名节点在场的断言把这条协议钉死"
  - "ruff format 不作为本包的门禁：包内 5 个既有文件同样 --check 不过，本文件对齐既有 88 列换行风格"

requirements-completed: []  # IMPACT-05 需 trace 内核（122-04）与壳层（122-05/07/08）齐活才算交付

# Metrics
duration: 25min
completed: 2026-08-09
---

# Phase 122 Plan 02: 图内符号解析器（uid 优先 + 重名候选列表）Summary

**一个零 ORM、零 Django、零运行期 networkx 的纯函数解析器，把 D-19 的「⛔ 绝不静默取第一个」从一句 REQUIREMENTS 文字变成 impact 与 trace 共用的同一段代码，外加 barrel docstring 里写下新内核为什么不进 barrel、以及「内核可以直连」为什么不等于「图可以直连」**

## Performance

- **Duration:** ~25 min
- **Tasks:** 2
- **Files modified:** 3（1 新建 + 2 修改）
- **测试:** `tests/services/code_graph` 从 122-01 的 **97 passed / 23 skipped** 变为 **100 passed / 22 skipped**，零新增失败

## Accomplishments

- `resolve_symbol_in_graph` 落地，两条路径互不渗透：
  - **uid 优先**——传 `symbol_id` 时在图里直接命中（`candidates=()`、`total_candidates=1`），不在图里则明确落空（`total_candidates=0`）。这条分支**绝不**因落空而退化去按名字搜；「不存在」与「被 exclusion 挡掉 / 不在子图内」刻意合并成同一个出口，区分它们会泄漏被排除文件的存在性。
  - **名字路径**——精确匹配 `name`（大小写敏感），可选 `file_path`（相等或路径后缀）与 `symbol_type`（大小写不敏感）一次性收窄（RESEARCH Pitfall 2 §4：能一次收敛就不要往返两轮）。命中 ≥2 个时按 `(file_path, start_line, symbol_id)` 稳定排序、取前 `CANDIDATE_LIMIT=20` 条，`total_candidates` 记**未截断前**总数，`truncated` 声明看到的不是全部。
- 定下一条两个内核与壳层都可依赖的**不变式**并写进 `SymbolResolution` 的 docstring：`resolved` 非空 ⇒ 候选必空；候选非空 ⇒ `resolved` 必为 `None` 且总数 ≥2。不存在「给了 resolved 又附一堆候选」这种让调用方误以为可以直接用第一个的中间态。
- 三条零 DB 用例落地，每条都刻意设计成**实现走捷径就会红**：
  - `test_uid_takes_precedence` 的第 ③ 段在**同名节点在场**的前提下传 uid。只测「uid 不在图里返回空」的话，一个「uid 落空就回落到按 name 搜」的实现照样能通过（图里没有同名节点，回落也搜不到东西），D-19 的 uid 优先就白写了。
  - `test_ambiguous_never_silently_picks_first` 的两个节点**倒序插入**：实现若直接吐 `graph.nodes` 的顺序，file_path 升序断言当场红。
  - `test_candidate_list_is_capped` 的 25 个节点同样**倒序插入**，顺带守住「截断发生在排序之后」——先截断再排序的实现会留下 `f05`–`f24` 而不是断言里的 `f00`–`f19`。
- 新模块**自动**通过既有 AST 观测契约（`package_dir.glob("*.py")` 扫全包），未改动任何守护测试的判据。埋点 `_log_symbol_ambiguous` 取 DEBUG + `category="sampling"`，**只记 name 长度与候选计数**，不记符号名、不记 `file_path`、不逐候选打日志。
- `__init__.py` 的 D-28 边界段落地，四层意思一次写全：新内核不进 barrel 的理由、⚠️「内核可以直连」≠「图可以直连」、包内 vs 包外兄弟模块的判据（是否碰 ORM）、⚠️「在包外」≠「不受观测契约管」（122-05 会扩扫描面）。

## Task Commits

1. **Task 1: symbol_resolve.py —— uid 优先 + 重名候选列表** - `a0e2a21a` (feat)
2. **Task 2: barrel docstring 补记新内核的边界（D-28）** - `48feca84` (docs)

## Files Created/Modified

- `server/services/code_graph/symbol_resolve.py`（新建，约 290 行）— 三段式中文 docstring；`CANDIDATE_LIMIT: Final[int] = 20` 与 `_EVENT_SYMBOL_AMBIGUOUS: Final[str]`；`SymbolCandidate` / `SymbolResolution` 两个 `@dataclass(frozen=True, slots=True)`；`resolve_symbol_in_graph` + 私有 `_file_path_matches` / `_log_symbol_ambiguous`；`__all__` 恰四项字母序。运行期 import 仅 `__future__` / `dataclasses` / `typing` / `structlog`，`networkx` 只在 `TYPE_CHECKING` 块内。
- `server/services/code_graph/__init__.py` — **纯 docstring 变更**，插入 31 行（0 删除），全部落在 docstring 的行范围内（docstring 1–66 行，diff hunk `@@ -28,0 +29,31 @@`）。`__all__` 17 项一字未动。
- `server/tests/services/code_graph/test_symbol_resolve.py` — 模块 docstring 补记「为什么不用 `known_topology` 造重名」；新增 `_graph_with_names` 就地造冻结小图的 helper；`test_uid_takes_precedence` 摘 skip 并填实，新增 `test_ambiguous_never_silently_picks_first` 与 `test_candidate_list_is_capped`；`test_ambiguous_returns_candidates` 仍挂 skip 待 122-05。

## Decisions Made

- **命中恰 1 个时 `candidates` 置空**，而不是把那唯一一条也放进候选列表。这样 `resolved` 与 `candidates` 就构成一条干净的互斥不变式，壳层渲染时不必再判「候选里这条是不是就是 resolved 那条」。代价是唯一命中时拿不到 `file:line`——但那种情形壳层本来就要按 uid 回 ORM 取 `signature`，顺手取路径不额外增加查询。
- **`file_path` 后缀匹配卡 `/` 边界**。裸 `endswith` 会让 `r.go` 匹上 `user.go`；「收窄参数反而放进了不相干的符号」比不支持后缀更糟，因为调用方会以为自己已经消歧成功。
- **排序键的第三项 `symbol_id` 不是凑数**：生产有 24,312 组 `(repository_id, file_path, name)` 三元组冲突（同文件同名多符号，典型是不同 class 的同名 method），它们在前两项上完全打平；少了第三项，候选顺序就依赖 `graph.nodes` 的插入序，同一次查询在两个 worker 上可能给出不同的前 20 条。
- **`ruff format` 不作为本包门禁**。`services/code_graph/` 下 `cache.py` / `loader.py` / `signature.py` 等 5 个既有文件同样 `--check` 不过（ruff 配置 line-length 100，包内既有代码按 88 列换行）。本文件对齐既有风格而非单独格式化，避免在一个 2 行的埋点签名上与全包风格分叉。plan `<verification>` 要求的 `ruff check` 全绿。

## Deviations from Plan

None - plan executed exactly as written。两个 task 的 acceptance criteria 全部逐条实测通过，未触发任何 Rule 1–4 的自动修复。

## Verification Results

| 判据 | 结果 |
|---|---|
| `pytest tests/services/code_graph/test_symbol_resolve.py -q` | **3 passed, 1 skipped**（plan 明写的期望值） |
| `pytest tests/services/code_graph -q --reuse-db` | **100 passed / 22 skipped**（基线 97/23，+3 passed / −1 skipped，零新增失败） |
| `test_access.py -k "observability or upper_layer or barrel"` | 4 passed（新模块自动进扫描，契约未破） |
| D-04 机械判据就地复核（logger 首个位置实参须字面量或模块级 `Final[str]`） | 退出码 0 —— 无 `_emit()` 包装 |
| 零 ORM AST 断言（无 `django` / `codegraph` / `repositories` 运行期 import） | 退出码 0，实际 import 面 `['__future__','dataclasses','networkx','structlog','typing']`（`networkx` 在 `TYPE_CHECKING` 内） |
| barrel 17 项 + docstring 关键词 + 无 `from .` | 退出码 0 |
| `__init__.py` AST 节点数 vs HEAD | 顶层非 docstring 节点 **4 = 4**、全树节点 **46 = 46** —— 零代码变更 |
| `ruff check services/code_graph/ tests/services/code_graph/` | All checks passed |
| `mypy services/code_graph/` | 本 plan 三个文件零错误（报出的 9 条全在包外既有文件：`workflows/schemas/technical_plan.py:268` 等） |
| `git diff --name-only HEAD~2 HEAD` | 恰三个文件，**不含** `server/codegraph/services/repo_router_v2.py`（里程碑冻结面） |

## Issues Encountered

- 无。122-01 记入 `deferred-items.md` 的两条 `tests/mcp_tools/` ruff error 与本 plan 的编辑面无交集，未新增任何 deferred 项。
- 顺带发现工作区里有一个**先于本会话存在**的空目录 `server/server/`（内含 `.mypy_cache` 与一个空 `workflows/`，`git status` 不跟踪）。非本 plan 产物，未动；提醒后续 plan 从仓库根用绝对路径 `cd`，否则 `cd server` 会误入该目录导致 pytest 收不到用例。

## Known Stubs

- `SymbolCandidate.signature` 在本模块产出的候选里**恒为空串**——这是设计而非缺口。`loader.py:354-356` 明确不把 `Symbol.signature`（TextField，可达数 KB）取进图节点属性（节点恒 5 个）。D-19 要求候选带 `signature`，那一列由壳层用 `Symbol.objects.filter(id__in=…).values_list("id","signature")` 回 ORM 补取并截断到 200 字符（D-17 token 纪律），归 **122-05**。理由已写进字段注释与模块 docstring 边界②，防止下一个读代码的人以为解析器坏了。
- `test_ambiguous_returns_candidates`（挂 `django_db`）仍是 Wave 0 桩，归 **122-05** —— 它验的正是上面那条 ORM 补取链路。

## Threat Flags

无新增威胁面。plan `<threat_model>` 的三条 `mitigate` 均已落地并有机械判据守着：

| Threat ID | 落地方式 | 判据 |
|---|---|---|
| T-122-绕闸 | 模块运行期零 Django/ORM import；只吃已过三道闸的图对象 | AST 断言退出码 0 |
| T-122-日志放大 | `_log_symbol_ambiguous` 取 DEBUG + `category="sampling"`，不逐候选打日志 | 观测契约测试 + 就地复核 |
| T-122-exclusion 回流 | 埋点不记符号名、不记 `file_path`，只记 name 长度与两个计数 | 代码面为准；被排除文件的符号本就不在图里（`loader.py:401`） |

`T-122-SC`（供应链）维持 `accept`：**零新增依赖**，`structlog` / `networkx` 均为既有生产依赖。

## User Setup Required

None - 零新增依赖、零迁移、零模型变更、无外部服务配置。

## Next Phase Readiness

- **122-03 / 122-04** 可直接 `import services.code_graph.symbol_resolve` 复用解析器，无需各自实现符号定位；D-28 已把这条 import 的合法性写进 barrel docstring，review 时不会被误判为架构违规。
- **122-05** 接手两件事：① 用 `SymbolCandidate.symbol_id` 批量回 ORM 补 `signature`（截断 200 字符）并填实 `test_ambiguous_returns_candidates`；② 按 D-28 把 `test_observability_contract` 的扫描面扩展到 `services/code_graph_tools.py` 与 `services/code_graph_cross_repo.py` 两个包外兄弟模块（`category` 放宽到 `sampling` / `caller`，其余判据一条不放松）。
- **IMPACT-05 未标记完成**：本 plan 只交付「图内定位」这一半，另一半（trace 最短路 + 逐跳 file:line + ORM 补 `signature` + 双面壳层）分散在 122-04 / 05 / 07 / 08。⛔ 不得据本 plan 勾选 REQUIREMENTS。
- **无 blocker。**

## Self-Check: PASSED

- 交付文件均存在于磁盘：`server/services/code_graph/symbol_resolve.py`、`server/services/code_graph/__init__.py`、`server/tests/services/code_graph/test_symbol_resolve.py`。
- 两个 task commit（`a0e2a21a` / `48feca84`）均可在 `git log` 中查到。

---
*Phase: 122-impact-trace*
*Completed: 2026-08-09*
