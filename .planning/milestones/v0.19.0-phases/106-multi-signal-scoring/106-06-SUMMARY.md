---
phase: 106-multi-signal-scoring
plan: 06
subsystem: codegraph-routing
tags: [qdrant, dense-search, repo-router, scoring, systemsetting, snapshot]

requires:
  - phase: 106-01
    provides: aggregate_and_score 六信号新签名（weights/repo_meta/constants/now）与 ScoredCandidate.criticality
  - phase: 106-02
    provides: aload_weight_config/aload_nr_snapshot loader（保存即生效 + weight_set_version 真值）
  - phase: 106-03
    provides: resolve_facet_scores/FacetT2Matcher/merge_alias_dict/alias_dict_hash
provides:
  - QdrantService.dense_search_by_name——using="dense" 单独查询封装（O-3 口径，异常返回空列表不抛）
  - repo_router_config.load_alias_dict/aload_alias_dict——DEFAULT_ALIAS_DICT + SystemSetting 覆盖合并，返回 (生效词典, hash)
  - RepoRouterV2._load_repo_meta——repo_meta 组装编排（dense 余弦归仓 max + FileIndex 一次聚合 + N_r/N̄ 快照 + facet T1/T2 + criticality_value）
  - route() 六信号打分注入（v2 与 v2_stage0_only 两出口共用 Stage 0）+ 整体异常回退 legacy 三信号
  - 快照新节 weight_config（生效全值）/ repo_meta（per-候选 ≤12）/ stage0.scored_at；versions.weight_set_version 占位换真（106-07 回放材料）
  - RepoRouteCandidateV2.criticality 旁路字段 + to_dict 键（不进 breakdown）
affects: [106-07 replay 兼容, 106-08 golden 版本 bump 与 gk-001 翻转, 107 分组呈现]

tech-stack:
  added: []
  patterns:
    - "repo_meta 供数逐信号独立降级 + 组装整体 try/except 兜底回退 legacy——观测与新信号永不反噬路由主流程"
    - "快照携带本次生效全值（weight_config 节）——回放不依赖当时的 SystemSetting"

key-files:
  created:
    - server/tests/codegraph/test_repo_router_v2_meta.py
  modified:
    - server/services/qdrant_service.py
    - server/codegraph/services/repo_router_config.py
    - server/codegraph/services/repo_router_v2.py
    - server/services/process_runtime/builtin_processes.py

key-decisions:
  - "dense 余弦保留为 S_top 默认主干：+1 次 Qdrant 往返与 hybrid 同量级、复用已算好的 query_dense 零额外 embedding，未触发 CONTEXT 锁定的 RRF 回退开关；dense 失败/某仓不在 dense top-K 时该仓自动回退 RRF s_hat（Pitfall 6）"
  - "legacy 回退不写 weight_config/repo_meta 空节——106-07 以「缺 weight_config 节」识别 legacy 快照"
  - "快照 repo_meta 只记最终候选仓（<= STAGE0_REPO_K=12），不记全部分桶仓（Pitfall 5 体积护栏）"
  - "scored_at 为 route() 内唯一 datetime.now 来源并进快照——活跃度衰减时间锚点随快照可回放"

patterns-established:
  - "meta 供数降级矩阵：dense 异常→None、nr_snapshot 缺失→n_bar None、embedding 未配置→T1-only、权重行非法→loader 回退默认，四条全部 warning 采样观测"

requirements-completed: [ROUTE-03, ROUTE-04, ROUTE-05, ROUTE-06]

coverage:
  - id: D1
    description: "dense_search_by_name：using=\"dense\" 单独查询封装，异常返回空列表；dense 失败时 S_top 回退 RRF、路由不失败"
    requirement: ROUTE-03
    verification:
      - kind: integration
        ref: "server/tests/codegraph/test_repo_router_v2_meta.py#test_degraded_dense_failure_falls_back_rrf"
        status: pass
      - kind: integration
        ref: "server/tests/codegraph/test_repo_router_v2_meta.py#test_one_route_query_budget_no_nplus1"
        status: pass
    human_judgment: false
  - id: D2
    description: "repo_meta 组装（dense 归仓 max / FileIndex 一次聚合 / N_r 快照 / facet T1-T2 / criticality）与降级矩阵四行全部路由可用；breakdown 出现 domain/stack 键且 Σ==score、缺失信号键不出现"
    requirement: ROUTE-04
    verification:
      - kind: integration
        ref: "server/tests/codegraph/test_repo_router_v2_meta.py#test_full_meta_breakdown_criticality_and_snapshot"
        status: pass
      - kind: integration
        ref: "server/tests/codegraph/test_repo_router_v2_meta.py#test_degraded_nr_snapshot_missing + test_degraded_embedding_unconfigured_t1_only + test_degraded_invalid_weight_config_row"
        status: pass
    human_judgment: false
  - id: D3
    description: "快照契约：weight_config 生效全值（含 n_bar/alias_dict_hash/embedding_model_id）+ per-候选 repo_meta（<=12）+ stage0.scored_at + versions.weight_set_version 真值；legacy 构造快照的既有用例零改动全绿"
    requirement: ROUTE-03
    verification:
      - kind: integration
        ref: "server/tests/codegraph/test_repo_router_v2_meta.py#test_full_meta_breakdown_criticality_and_snapshot"
        status: pass
      - kind: integration
        ref: "uv run pytest tests/codegraph tests/delivery tests/services/test_repo_router_adapter.py -q → 827 passed / 20 skipped（golden 门禁与 legacy 回放零改动全绿）"
        status: pass
    human_judgment: false
  - id: D4
    description: "保存即生效（SC-4 前半）：写入新权重配置后无重启，下一次 route() 版本换新且 breakdown 数值随权重变化"
    requirement: ROUTE-06
    verification:
      - kind: integration
        ref: "server/tests/codegraph/test_repo_router_v2_meta.py#test_save_takes_effect_without_restart"
        status: pass
    human_judgment: false
  - id: D5
    description: "免 N+1（一次路由恰 2 次 Qdrant + 恰 1 次 FileIndex 聚合）与 repo_meta 整体异常回退 legacy 三信号（永不反噬）；活跃度供数走一次聚合的 last_commit_authored_at"
    requirement: ROUTE-05
    verification:
      - kind: integration
        ref: "server/tests/codegraph/test_repo_router_v2_meta.py#test_one_route_query_budget_no_nplus1"
        status: pass
      - kind: integration
        ref: "server/tests/codegraph/test_repo_router_v2_meta.py#test_meta_overall_failure_falls_back_legacy"
        status: pass
    human_judgment: false

duration: ~2h30m（跨两次执行会话：首会话完成 Task 1/2 后于 Task 3 中断，恢复会话验证并收尾）
completed: 2026-07-29
status: complete
---

# Phase 106 Plan 06: 六信号打分生产接线 Summary

**dense-only 余弦查询 + repo_meta 组装编排接入 route()，快照携带 weight_config 生效全值与 per-候选 repo_meta，四降级 + 整体回退全部被 9 条集成测试锁定**

## Performance

- **Duration:** ~2h30m 有效执行（跨两次会话，中断间隙不计）
- **Started:** 2026-07-29T10:56Z 前（首会话；Task 1 提交于 10:56:58Z）
- **Completed:** 2026-07-29T14:47Z（恢复会话收尾）
- **Tasks:** 3
- **Files modified:** 5（4 改 1 建）

## Accomplishments

- `QdrantService.dense_search_by_name`：与 `hybrid_search_by_name` 同层对称的 `using="dense"` 单独查询（O-3 定论落地），任何异常返回空列表——S_top 主干拿到真余弦，失败自动回退 RRF s_hat。
- `RepoRouterV2._load_repo_meta`：一次 dense 查询归仓取 max + 一次 `FileIndex` `values().annotate(Max("last_commit_authored_at"))` 聚合 + N_r/N̄ 快照 + facet T1/T2 解析——免 N+1（+1 Qdrant / +1 DB 聚合）被测试锁定。
- `route()` 六信号注入：`aload_weight_config` 调用时读取（保存即生效，SC-4），`v2` 与 `v2_stage0_only` 两出口共用；组装整体异常回退 legacy 三信号，永不反噬路由。
- 快照扩展：`weight_config`（weights/constants 含 n_bar/weight_set_version/alias_dict_hash/embedding_model_id）+ `repo_meta`（≤12 仓体积护栏）+ `stage0.scored_at`；`versions.weight_set_version` 从 loader 取真值，模块常量 `WEIGHT_SET_VERSION` 引用清除（105 占位换真）。
- `RepoRouteCandidateV2.criticality` 旁路字段透传（不进 breakdown，前端 Σ 校验不受影响）。
- 集成测试 9 条（min_lines 200 要求，实际 492 行）：全量 meta 契约 / 降级矩阵四行 / 保存即生效 / 免 N+1 / 整体回退 / 尺寸偏置路由侧印证。

## Task Commits

1. **Task 1: dense 查询封装 + alias loader + repo_meta 组装编排** - `6a5ef915` (feat)
2. **Task 2: route() 六信号打分注入 + 快照扩展 + criticality 透传** - `653dd500` (feat)
3. **Task 3: 集成测试——降级矩阵/快照契约/保存即生效** - `760fffcd` (test)

## Files Created/Modified

- `server/services/qdrant_service.py` - 新增 `dense_search_by_name`（classmethod，同 filter 构造/返回形状/异常处理）
- `server/codegraph/services/repo_router_config.py` - 新增 `load_alias_dict`/`aload_alias_dict`（默认词典 + SystemSetting 覆盖合并 + hash）
- `server/codegraph/services/repo_router_v2.py` - `_load_repo_meta` 组装编排、route() 注入、快照扩展、criticality 字段、观测事件 3 个
- `server/services/process_runtime/builtin_processes.py` - `_routing_snapshot_payload` 透传 weight_config/repo_meta 新节（经 redact_for_ledger，T-106-15）
- `server/tests/codegraph/test_repo_router_v2_meta.py` - 9 条集成测试（492 行）

## Decisions Made

- **dense 余弦保留为默认主干（CONTEXT 延迟取舍纪律的记录）**：额外往返与 hybrid 查询同量级（同 collection/top_k/filters），且复用 Stage 0 已算好的 `query_dense` 零额外 embedding；集成与回归测试未显示不可接受的结构性代价，故未启用 RRF query-local max 回退默认值。RRF 路径作为 dense 失败/未命中的降级分支已就位，若生产实测（O-1 口径）显示延迟问题，切换仅是默认值问题。
- **legacy 回退不写空节**：`repo_meta=None` 回退路径的快照不含 `weight_config`/`repo_meta` 键，106-07 以缺节判定 legacy 快照，无需版本嗅探。
- **快照体积护栏**：`repo_meta` 只记最终候选（≤ STAGE0_REPO_K=12），打分虽发生在全部分桶仓上，但回放只需候选仓数据。
- **`scored_at` 唯一 now 来源**：活跃度指数衰减的时间锚点进快照，106-07 回放可零网络、零时钟漂移复算。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] ledger 落盘 payload 透传新快照节**
- **Found during:** Task 2（快照扩展）
- **Issue:** `_routing_snapshot_payload`（`server/services/process_runtime/builtin_processes.py`）按白名单键构造落盘 payload，新节 weight_config/repo_meta 不透传则 Interaction Ledger 里的快照缺 106-07 回放材料，且 T-106-15 的 redact_for_ledger 覆盖要求无从谈起
- **Fix:** 仅当键存在且为 dict 时透传（legacy 快照不加空节），整体仍经 `redact_for_ledger`
- **Files modified:** server/services/process_runtime/builtin_processes.py（+6 行，plan files_modified 未列该文件）
- **Verification:** 定向回归全绿；tests/delivery 覆盖 ledger 路径
- **Committed in:** 653dd500（Task 2 提交）

**2. [Rule 1 - Bug] `_load_latest_commits` 非 UUID repository_id 容错**
- **Found during:** Task 2
- **Issue:** 上游 Qdrant payload 的 repository_id 为不可信数据（threat model 信任边界），非 UUID 值进入 `repository_id__in` 过滤会抛 ValidationError 使聚合整体失败
- **Fix:** 逐字段容错过滤非法 id（T-106-14 mitigation 的落实）
- **Verification:** 集成测试中 bare 仓等路径全绿
- **Committed in:** 653dd500（Task 2 提交）

---

**Total deviations:** 2 auto-fixed（1 missing critical, 1 bug）
**Impact on plan:** 均为 threat model 既定 mitigation（T-106-14/T-106-15）的正确性要求，无 scope creep。

## TDD Gate Compliance

Task 3 标记 `tdd="true"`，但本 plan 的任务结构本身把实现（Task 1/2，feat 提交）排在测试任务之前——git log 门序为 `feat 6a5ef915 → feat 653dd500 → test 760fffcd`，无独立 RED 提交（测试首跑即 9/9 全绿，因被测行为已由 Task 1/2 交付）。该测试任务实为行为锁定（lockdown）性质而非 red-green 驱动；另因执行中断发生在 Task 3 写作中途，恢复会话按「不盲目重写未提交代码」纪律验证后原样提交。

## Issues Encountered

- **执行器中断恢复**：首会话在 Task 3（测试文件写作）中途中断，文件已完整落盘但未提交。恢复会话首跑 `test_repo_router_v2_meta.py` 9/9 全绿、定向回归（tests/codegraph + tests/delivery + tests/services/test_repo_router_adapter.py）827 passed / 20 skipped，确认无需修改后原样提交。

## User Setup Required

None - 无外部服务配置需求。

## Next Phase Readiness

- 106-07（replay 兼容）：新格式快照材料齐备——weight_config 生效全值 + per-候选 repo_meta + scored_at 可零网络消费；legacy 快照以「缺 weight_config 节」识别。
- 106-08（golden 版本 bump 与 gk-001 翻转）：golden 门禁当前保持绿（版本 bump 前的既定纪律）；六信号已在生产链路生效，尺寸偏置反向倾斜有路由侧集成测试印证。

## Self-Check: PASSED

- `server/tests/codegraph/test_repo_router_v2_meta.py` 存在（492 行 ≥ min_lines 200）✓
- 提交存在：`6a5ef915` / `653dd500` / `760fffcd` ✓
- Task 1 验收：`using="dense"` 出现（5 处）、`annotate(.*Max(` == 1、`generate_embedding` 未增（1 处，复用）✓
- Task 2 验收：`WEIGHT_SET_VERSION` 引用 == 0、`datetime.now` == 1 ✓
- Task 3 验收：9 用例 ≥ 8 全绿 ✓
- Plan 级验证：`uv run pytest tests/codegraph tests/delivery tests/services/test_repo_router_adapter.py -q` → 827 passed / 20 skipped；`ruff check`（4 文件）All checks passed ✓

---
*Phase: 106-multi-signal-scoring*
*Completed: 2026-07-29*
