---
phase: 106-multi-signal-scoring
plan: 04
subsystem: codegraph-routing
tags: [repo-router, measure-command, nr-snapshot, o2-calibration, o5-activity, management-command, embedding]

# Dependency graph
requires:
  - phase: 105-golden-set/105-02
    provides: measure_repo_index_stats command 骨架（per-repo 计数循环/JSON+markdown 双输出/_LOG_KV 观测模式）
  - phase: 106-multi-signal-scoring/106-02
    provides: SettingKeys.REPO_ROUTER_NR_SNAPSHOT 键 + load_nr_snapshot 读取端形状契约（写入端对齐目标）
  - phase: 106-multi-signal-scoring/106-03
    provides: repo_router_metadata 的 facet 键名常量/UNCLASSIFIED_VALUE/MAX_FACET_VALUE_LENGTH（覆盖率与校准复用）
provides:
  - measure --activity（O-5）：last_commit_at 覆盖率/新鲜度 p50/p90 + facets 五维覆盖率统计
  - measure --write-snapshot（ROUTE-03 数据管线）：N_r 全表 + N̄ 中位数写 SystemSetting repo_router.nr_snapshot，与 load_nr_snapshot 写读契约闭环
  - calibrate_repo_router_metadata command（O-2）：负样本 p95 → c_lo / 正样本 p50 → c_hi / c_hi-c_lo < 0.10 → T2 弃用判定；--structural 零网络降级
  - 106-MEASUREMENTS.md：O-2/O-5 占位表 + 生产执行指引 + deferred 挂账清单（O-1/O-2/O-5 三项 UAT 人工步骤）
affects: [106-06, 106-07, 106-08, UAT 生产回填]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "实测命令数据环境标注纪律：开发库结果只进「结构性结论」区，生产分布 deferred 占位表 + 执行指引（105-MEASUREMENTS 先例延续）"
    - "structural 降级模式：外部依赖（embedding）不可用时用 seed 确定性伪向量跑通全管线，管线正确性与真实分布解耦"
    - "SystemSetting 写入端与 loader 读取端形状契约用写读闭环测试锁定（write → load_nr_snapshot 断言）"

key-files:
  created:
    - server/codegraph/management/commands/calibrate_repo_router_metadata.py
    - server/tests/codegraph/test_calibrate_repo_router_metadata.py
    - .planning/phases/106-multi-signal-scoring/106-MEASUREMENTS.md
  modified:
    - server/codegraph/management/commands/measure_repo_index_stats.py
    - server/tests/codegraph/test_measure_repo_index_stats.py

key-decisions:
  - "N̄ 用有索引仓（node_count>0）节点数的 statistics.median（抗 monorepo 倾斜）；0 计数仓保留在 n_r_by_repo 全表供 106-06 显式判 0"
  - "空库（无任何已索引仓）--write-snapshot 拒绝写入（防空快照覆盖有效值，T-106-09）"
  - "正样本归属：条目可带显式 facet 键，缺省按闭集值反查维度；无法归属的条目跳过计数不猜"
  - "structural 模式正样本仍须 --positives-file（plan 字面「无 positives-file 时 c_hi 列 deferred」在两种模式一致；结构性正样本经测试用 positives-file 注入覆盖 c_hi/判定路径）"
  - "MEASUREMENTS 执行指引按命令真实接口书写（measure 无 --format 参数：默认 markdown、机器可读 --json），修正 plan 字面 `--format markdown`"

patterns-established:
  - "新鲜度/余弦分位数统一 repo_router_eval._quantile 线性插值口径（两 command 各自内联同款实现并以测试锁定一致性）"

requirements-completed: [ROUTE-03, ROUTE-04, ROUTE-05]

coverage:
  - id: D1
    description: "measure --activity（O-5）：FileIndex 按仓 Max(last_commit_authored_at) 覆盖率 + 新鲜度 p50/p90 分位数 + facets 五维覆盖率（「未分类」不算覆盖），并入 report JSON 与 markdown"
    requirement: ROUTE-05
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_measure_repo_index_stats.py#test_activity_stats_coverage_and_freshness/test_activity_null_authored_at_counts_uncovered/test_activity_facets_coverage_five_dims/test_markdown_output_includes_activity_and_snapshot_sections"
        status: pass
    human_judgment: false
  - id: D2
    description: "measure --write-snapshot（ROUTE-03）：{n_r_by_repo 全表, n_bar 中位数, generated_at} 写 SystemSetting repo_router.nr_snapshot，与 106-02 load_nr_snapshot 写读闭环；空库拒绝写入"
    requirement: ROUTE-03
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_measure_repo_index_stats.py#test_write_snapshot_roundtrip_with_loader/test_write_snapshot_refuses_empty_library"
        status: pass
    human_judgment: false
  - id: D3
    description: "calibrate_repo_router_metadata（O-2/ROUTE-04）：闭集采样 → 余弦分布 → c_lo/c_hi 建议 → 逐 facet T2 弃用判定；--structural 零网络降级；positives 文件严格校验；embedding 失败即退提示 --structural"
    requirement: ROUTE-04
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_calibrate_repo_router_metadata.py（7 条：结构性端到端/markdown 判定表/正样本 c_hi 判定/文件结构校验/embedding 失败/分位数同口径/伪向量确定性）"
        status: pass
    human_judgment: false
  - id: D4
    description: "106-MEASUREMENTS.md：O-5/O-2 占位表（数据环境: 生产实例 deferred）+ 四步执行指引 + 开发库结构性结论区 + deferred 挂账清单（O-1/O-2/O-5）——生产回填为 UAT 人工步骤"
    verification: []
    human_judgment: true
    rationale: "文档面交付：占位表/指引可读性与生产回填流程正确性需人工确认；生产实测数字本身即挂账人工步骤"

# Metrics
duration: 20min
completed: 2026-07-29
status: complete
---

# Phase 106 Plan 04: 实测管线（O-5 活跃度统计 + N_r 快照 + O-2 校准 command） Summary

**`measure_repo_index_stats` 新增 `--activity`（last_commit_at 覆盖率/新鲜度 p50/p90 + facets 五维覆盖率）与 `--write-snapshot`（N_r 全表 + N̄ 中位数写 SystemSetting，与 106-02 loader 写读闭环）；新建 `calibrate_repo_router_metadata`（负样本 p95→c_lo、正样本 p50→c_hi、区分度 <0.10 判弃 T2，--structural 零网络定管线）；106-MEASUREMENTS.md 占位表 + 指引 + deferred 挂账落盘**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-07-29T09:34:59Z
- **Completed:** 2026-07-29T09:55:21Z
- **Tasks:** 2
- **Files modified:** 5（新建 3 + 修改 2）

## Accomplishments

- **O-5 执行工具就位（ROUTE-05）**：`--activity` 用 `FileIndex.values("repository_id").annotate(Max("last_commit_authored_at"))` 单条聚合出全仓 last_commit_at 覆盖率与新鲜度分位数（距 now 天数，线性插值与 `repo_router_eval._quantile` 同口径）；facets 五维覆盖率逐键统计（`业务线/产品线` 的「未分类」计未覆盖，键名复用 106-03 resolver 常量）。覆盖不足的仓在打分侧自动走枚举回退。
- **ROUTE-03 数据管线闭环**：`--write-snapshot` 组装 `{"n_r_by_repo": 全表, "n_bar": 有索引仓中位数, "generated_at": UTC iso}` 经 `SystemSetting.objects.update_or_create` 写入 `SettingKeys.REPO_ROUTER_NR_SNAPSHOT`（post_save signal 自动失效读缓存，写后下一次路由即生效）；写读闭环测试断言 `load_nr_snapshot()["n_bar"] == statistics.median(...)`；空库拒绝写入（T-106-09）。
- **O-2 校准管线完整可执行（ROUTE-04）**：`calibrate_repo_router_metadata` 独立 command——facet 闭集值（语义分面 FacetVocabulary + 技术栈 `_EXT_LANGUAGE_MAP` 18 语言）× 需求文本（WorkItem 标题）确定性采样负样本 → stdlib 余弦 → p95→c_lo；`--positives-file`（严格结构校验 + 超长值 DoS 护栏）→ p50→c_hi；`c_hi-c_lo < 0.10 → 建议加入 t2_disabled_facets`；结尾输出 PUT weight-config 回填指引（含换模型必须重校准提示）。
- **降级路径可测**：`--structural` 用 seed 确定性伪向量（sha256 播种、单位范数）零网络跑通全管线（`--disable-socket` 下 7 条测试全绿）；EmbeddingService 未配置/失败报错退出并提示 `--structural`（失败即退不重试，T-106-11）。
- **观测按 LOGGING-SPEC**：`measure_activity_stats_completed`/`nr_snapshot_written`/`calibrate_repo_router_metadata_started/completed/failed`（caller、component=codegraph、initiated_by_user_id=system、duration_ms）；异常文本 `redact_secrets_in_text` 脱敏；样本 query 文本不入日志只记计数（T-106-10）。
- **106-MEASUREMENTS.md（SC-5 文档面）**：O-5/O-2 两节占位表全部标注 `数据环境: 生产实例 friday.yc345.tv（deferred）`；开发库结果只进「结构性结论」区（字面 `数据环境: 开发库（结构性结论）`）；deferred 挂账清单三项（O-1 N_r 分布 / O-2 校准数字 / O-5 覆盖率）列为 UAT 人工步骤。
- **13 条新测试全绿**（measure 新增 6 + calibrate 7，验收要求 ≥4+≥4）；`tests/codegraph` 全量 364 passed / 20 skipped 零回归；两 command ruff check/format 双绿。

## Task Commits

Each task was committed atomically:

1. **Task 1: measure command 扩展 O-5 统计 + N_r 快照写入** - `334b61a1` (feat)
2. **Task 2: calibrate_repo_router_metadata O-2 校准管线 + MEASUREMENTS O-2 节** - `1e95615a` (feat)

## Files Created/Modified

- `server/codegraph/management/commands/measure_repo_index_stats.py` - 新增 `--activity`/`--write-snapshot`；`_quantile` 线性插值；`_collect_activity_stats`/`_write_nr_snapshot`；markdown 渲染三个新节
- `server/tests/codegraph/test_measure_repo_index_stats.py` - 新增 6 条（覆盖率/NULL 口径/facets 五维/写读闭环/空库拒写/markdown 回显）+ settings 缓存清理 autouse fixture（106-02 纪律）
- `server/codegraph/management/commands/calibrate_repo_router_metadata.py`（553 行）- O-2 校准 command：参数五件套（--facet/--negatives/--positives-file/--structural/--format）、闭集采集、确定性采样、批量 embedding（CallSource.EMBEDDING 作用域）、分布统计与判定、markdown/json 双输出
- `server/tests/codegraph/test_calibrate_repo_router_metadata.py` - 7 条：结构性端到端/判定表与回填指引/正样本 c_hi 判定口径/文件结构校验/embedding 失败提示/分位数同口径/伪向量确定性
- `.planning/phases/106-multi-signal-scoring/106-MEASUREMENTS.md`（159 行）- O-5/O-2 占位表 + 执行指引 + 结构性结论区 + deferred 挂账清单

## Decisions Made

- **N̄ 口径**：有索引仓（node_count>0）的中位数（代码注释标注「monorepo 拉爆均值」依据 ROUTING-RANKING §2.3）；0 计数仓保留在 `n_r_by_repo` 全表——106-06 breadth 对未索引仓可显式判 0 而非缺 key。
- **正样本归属**：`--positives-file` 条目可带显式 `facet` 键，缺省按闭集值 casefold 反查；无法归属跳过计数（`skipped_positives`）不猜——外部文件不可信（威胁边界），结构非法直接报错退出。
- **structural 模式正样本语义**：plan 字面「无 positives-file 时该列输出需人工正样本，deferred」在 structural/embedding 两种模式一致适用；c_hi/判定计算路径由 structural + positives-file 组合测试覆盖（管线完整性不依赖真实 embedding）。
- **技术栈闭集来源**：直接 import `facet_service._EXT_LANGUAGE_MAP`（plan 指定）而非复制 106-03 的 DEFAULT_ALIAS_DICT 键——command 运行于 Django 上下文，无 resolver 的「零 Django import」约束。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - 门禁冲突] 验收 grep `numpy == 0` 与注释字面冲突**
- **Found during:** Task 1（acceptance criteria 自检）
- **Issue:** 文件内「禁 numpy」注释字样（含 105-02 既有 docstring `禁 numpy/scipy` 1 处 + 本次新增 2 处）命中验收断言 `rg -c "numpy" == 0`（守护本意是禁 import/使用）
- **Fix:** 三处注释改写为「禁第三方数值库」/「stdlib 实现」，语义不变（106-02「禁逐键 aget_setting」deviation 同型处理）
- **Files modified:** server/codegraph/management/commands/measure_repo_index_stats.py
- **Verification:** `rg -c "numpy"` 零命中；12 条测试仍全绿
- **Committed in:** 334b61a1

**2. [Rule 1 - Doc] MEASUREMENTS 执行指引的 plan 字面命令参数不存在**
- **Found during:** Task 1（写 106-MEASUREMENTS.md 执行指引时）
- **Issue:** plan 字面指引 `measure_repo_index_stats --activity --write-snapshot --format markdown`——measure command 无 `--format` 参数（该参数属 calibrate command；measure 沿用 105-02 的 `--json`/默认 markdown 接口，plan 的 artifacts 表也只列 `--activity`/`--write-snapshot` 两个新参数）
- **Fix:** 指引按真实接口书写：默认 markdown 输出、机器可读加 `--json`；未给 measure 增加冗余 `--format` 参数（避免同一 command 两套输出开关）
- **Files modified:** .planning/phases/106-multi-signal-scoring/106-MEASUREMENTS.md
- **Verification:** 指引中的命令行与 `add_arguments` 实际参数一致
- **Committed in:** 334b61a1

---

**Total deviations:** 2 auto-fixed（1 门禁冲突、1 文档字面修正）
**Impact on plan:** 均为一致性修正，无 scope creep；命令接口、值形状契约、判定口径与 plan 完全一致。

## Issues Encountered

- ruff format 对两个新文件（calibrate command + 测试）有格式意见，`ruff format` 后复跑测试全绿再提交（Task 2 提交前处理，未进历史）。

## User Setup Required

None - no external service configuration required.
（生产实测回填是 deferred UAT 人工步骤，见 106-MEASUREMENTS.md §3 挂账清单，不属于部署配置。）

## Next Phase Readiness

- **106-06（router 组装）**：`load_nr_snapshot`/`aload_nr_snapshot` 读到的快照由本 plan 的 `--write-snapshot` 供数（写读契约已闭环）；快照缺失时 loader 回退空形状 → denom_size=1.0 降级路径不变。
- **生产回填（UAT 人工步骤）**：`measure_repo_index_stats --activity --write-snapshot`（O-5 + N_r 快照）与 `calibrate_repo_router_metadata --positives-file ...`（O-2）在 friday.yc345.tv 执行后按 106-MEASUREMENTS.md 占位表回填；校准建议值经 PUT weight-config 端点生效（保存即生效）。
- **索引重建后**：运维需重跑 `--write-snapshot` 刷新 N_r 快照（指引已写入 MEASUREMENTS §1）。

## Self-Check: PASSED

- FOUND: server/codegraph/management/commands/calibrate_repo_router_metadata.py
- FOUND: server/tests/codegraph/test_calibrate_repo_router_metadata.py
- FOUND: .planning/phases/106-multi-signal-scoring/106-MEASUREMENTS.md（159 行 ≥ 60；command 553 行 ≥ 150）
- FOUND: commit 334b61a1（feat, Task 1）
- FOUND: commit 1e95615a（feat, Task 2）
- 验证命令复核：19 passed（两测试文件合并）；tests/codegraph 全量 364 passed / 20 skipped；ruff check 两 command 全绿；`REPO_ROUTER_NR_SNAPSHOT`/`generate_embeddings_batch|CallSource.EMBEDDING`/`redact_secrets_in_text`/`statistics.median` grep 全命中；`numpy` 零命中；MEASUREMENTS 含 `数据环境: 开发库（结构性结论）` 与 `deferred` 字面、O-2/O-5 两节、挂账清单 O-1/O-2/O-5 三项

---
*Phase: 106-multi-signal-scoring*
*Completed: 2026-07-29*
