---
phase: 105-golden-set
plan: 02
subsystem: codegraph
tags: [qdrant, management-command, measurement, repo-router, statistics]

# Dependency graph
requires: []
provides:
  - "measure_repo_index_stats management command：按仓 exact count 统计 repo_index_nodes N_r 分布（p50/p90/p99/max/mean/median + --top 倾斜表 + --json）"
  - "--verify-cosine：dense-only 查询（using=\"dense\"）验证 COSINE 分可得性与延迟（O-3）"
  - "105-MEASUREMENTS.md：O-3 代码级定论 + O-1 生产执行指引与占位表——Phase 106 planning 直接输入"
affects: [phase-106, repo-router-v2, routing-ranking]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "measure_* management command：structlog started/completed/failed + best-effort 单项跳过（沿 measure_extractor_precision 先例）"
    - "内存 Qdrant 测试：QdrantClient(\":memory:\") + monkeypatch QdrantService.get_client，collection 用与生产同形的 hybrid 命名向量"

key-files:
  created:
    - server/codegraph/management/commands/measure_repo_index_stats.py
    - server/tests/codegraph/test_measure_repo_index_stats.py
    - .planning/phases/105-golden-set/105-MEASUREMENTS.md
  modified: []

key-decisions:
  - "--verify-cosine 不用 QdrantService.search_by_name（其查询匿名默认向量，对 hybrid collection 不可用），改为 client.query_points(using=\"dense\") 直查——该限制本身作为 O-3 子结论写入 MEASUREMENTS"
  - "余弦探针用现存点的 dense 向量做自查询（top-1 预期 ≈ 1.0），最直接证明返回分是 COSINE 而非 RRF 融合分"
  - "分位数用 statistics.quantiles(n=100)，零 numpy/scipy 新依赖"

patterns-established:
  - "数据环境标注纪律：measurement 结论逐条注明「开发库（结构性结论）」或「生产实例（分布实测）」，开发库结论仅限结构性"

requirements-completed: [ROUTE-08]

coverage:
  - id: D1
    description: "measure_repo_index_stats command：按仓统计 repo_index_nodes 节点数，输出 N_r 直方图（p50/p90/p99/max/median）与 markdown 表 / --json / --top / --verify-cosine"
    requirement: ROUTE-08
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_measure_repo_index_stats.py（6 用例：计数一致/分位数键/top 排序/余弦探针/无索引 skip/容错跳过）"
        status: pass
    human_judgment: false
  - id: D2
    description: "105-MEASUREMENTS.md 落盘：O-3 dense 余弦可得性为确定性代码级答案；O-1 含生产实例执行指引与占位表，每条结论标注数据环境"
    requirement: ROUTE-08
    verification:
      - kind: other
        ref: "rg 检查：O-3/measure_repo_index_stats/数据环境(×7)/hybrid_search_by_name/FusionQuery/待生产实例执行补录 全部命中"
        status: pass
    human_judgment: false
  - id: D3
    description: "O-1 生产分布实测数据 + O-3 延迟数字回填（在 friday.yc345.tv 执行 command 并转写占位表）"
    verification: []
    human_judgment: true
    rationale: "autonomous 模式无生产实例访问；本地开发库无 259 仓数据，本地结果不得回填（RESEARCH Pitfall 8）——deferred 人工步骤"

# Metrics
duration: 13min
completed: 2026-07-29
status: complete
---

# Phase 105 Plan 02: Phase 106 公式定版输入实测 Summary

**measure_repo_index_stats command 产出 N_r 直方图与余弦探针（内存 Qdrant 六用例全绿），105-MEASUREMENTS.md 落盘 O-3 定论（RRF 融合分不含余弦，取余弦须 using="dense" 单独查询）与 O-1 生产补录路径**

## Performance

- **Duration:** ~13 min
- **Started:** 2026-07-29T03:40:00Z
- **Completed:** 2026-07-29T03:53:00Z
- **Tasks:** 2
- **Files modified:** 3（全部新建）

## Accomplishments

- `measure_repo_index_stats` command：遍历 `Repository.objects.filter(is_deleted=False)` 按仓 `client.count(..., exact=True)` 计数，输出 p50/p90/p99/max/mean/median（`statistics.quantiles`，零 numpy）、`--top N` 倾斜表、`--json` 机器可读输出；单仓异常 warning 跳过不中断；structlog `measure_repo_index_stats_started/completed/failed`（category=caller, component=codegraph, initiated_by=system）
- `--verify-cosine`：scroll 取任一有索引仓现存点的 dense 向量做自查询（`query_points(using="dense")`），打印 COSINE score 样例与耗时 ms——O-3 验证辅助
- 测试 6 用例全绿：内存 Qdrant（hybrid 命名向量与生产同形）验证 per-repo 计数一致、分位数键齐全、top 排序、余弦探针 top-1 ≈ 1.0、无索引仓 skip、单仓失败容错
- `105-MEASUREMENTS.md`：O-3 定论（3 条：fusion 不回传余弦 / dense-only 需 `using="dense"` / 无一次双分官方途径，A1 假设标注）+ O-1 执行指引（完整命令行 + 占位表 + 本地全 0 禁回填警告）+ Phase 106 输入清单（N̄ 中位数、b=0.6 初值、MaxP 口径依赖延迟实测）

## Task Commits

1. **Task 1: 实现 measure_repo_index_stats management command** - `75eb9b8e` (feat)
2. **Task 2: 撰写 105-MEASUREMENTS.md** - `549af540` (docs)

## Files Created/Modified

- `server/codegraph/management/commands/measure_repo_index_stats.py` - O-1/O-3 一次性实测命令（Phase 106 公式定版输入）
- `server/tests/codegraph/test_measure_repo_index_stats.py` - 内存 Qdrant 结构性测试（6 用例）
- `.planning/phases/105-golden-set/105-MEASUREMENTS.md` - Phase 106 planning 直接输入文档

## Decisions Made

- **余弦探针实现方式**：自查询（用现存点自身 dense 向量查询）而非合成向量——top-1 余弦恒 ≈ 1.0，是「返回分即 COSINE」的最强直接证据
- **`search_by_name` 不可用于 hybrid collection 的事实升级为 O-3 子结论**：Phase 106 若走余弦路径需新增带 `using` 的封装或直接用 client

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] --verify-cosine 不按计划调 QdrantService.search_by_name，改为 client.query_points(using="dense") 直查**
- **Found during:** Task 1（O-3 验证辅助实现）
- **Issue:** 计划指定「发一次 `QdrantService.search_by_name`（dense-only）」，但代码实读确认 `repo_index_nodes` 是 hybrid collection（命名向量 dense/sparse），而 `search_by_name` 的 `query_points` 不带 `using` 参数、查询匿名默认向量——对 hybrid collection 会 UnexpectedResponse 并静默返回空列表，验证必然失败
- **Fix:** `--verify-cosine` 直接用 `client.query_points(collection_name="repo_index_nodes", query=vec, using="dense")`；该 API 限制写入 MEASUREMENTS §1 作为 O-3 子结论（Phase 106 余弦路径的实现约束）
- **Files modified:** server/codegraph/management/commands/measure_repo_index_stats.py
- **Verification:** `test_verify_cosine_returns_cosine_scores`（hybrid 内存 collection 上 top-1 ≈ 1.0）
- **Committed in:** 75eb9b8e (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** 修正计划中会导致验证失败的 API 用法，且把根因升级为 O-3 子结论——增强而非偏离计划目标。No scope creep.

## Issues Encountered

None（首轮 ruff format 需重排两文件，格式化后测试保持全绿）。

## 待人工步骤（deferred）

- **O-1 生产分布实测 + O-3 延迟数字回填**：在 friday.yc345.tv 执行
  `cd server && uv run python manage.py measure_repo_index_stats --json --top 20 --verify-cosine`，
  把输出回填 `105-MEASUREMENTS.md` §1 延迟表与 §2 占位表（数据环境标注为生产实测）。
  本地开发库无生产数据，本地结果不得回填（RESEARCH Pitfall 8）。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 106 planner 可直接消费 `105-MEASUREMENTS.md`：O-3 已定论（含 `using="dense"` 实现约束），O-1 有明确补录路径与占位表
- 公式形式设计可先按「余弦口径 + b=0.6 初值」推进，常数定版等生产回填

## Self-Check: PASSED

- 3 个新建文件 + SUMMARY 均存在于磁盘
- 任务 commits `75eb9b8e` / `549af540` 均在 git log 中
- `uv run pytest tests/codegraph/test_measure_repo_index_stats.py -q` 6 passed

---
*Phase: 105-golden-set*
*Completed: 2026-07-29*
