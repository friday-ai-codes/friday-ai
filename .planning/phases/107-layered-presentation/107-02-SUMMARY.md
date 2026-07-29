---
phase: 107-layered-presentation
plan: 02
subsystem: infra
tags: [observability, percentile-cont, system-log-entry, management-command, latency, measurements, repo-router]

# Dependency graph
requires:
  - phase: 105-golden-set
    provides: "measure_repo_index_stats 命令形态与测试范式（add_arguments / --json / _quantile 线性插值分位）、Stage 1 输入哈希缓存与快照回放、数据环境标注纪律"
  - phase: 106-multi-signal-scoring
    provides: "106-MEASUREMENTS.md 的占位表与 deferred 标注形态、phase106-v2 权重下的 golden cross_group 离线实测（gk-008 0.1771 / gk-009 0.2614）"
  - phase: 107-layered-presentation
    provides: "107-01 落地的九个外置参数（REPO_ROUTER_GROUP_DELTA / REPO_ROUTER_STAGE1_ALPHA / REPO_ROUTER_STAGE1_TOTAL_BUDGET_SECONDS 等）及 A5 per-call 不下调的裁决"
provides:
  - "measure_stage1_latency 命令：任意环境一条命令算 Stage 1 延迟 p50/p90/p99 与样本量（Postgres percentile_cont / 非 Postgres Python 侧线性插值回退）"
  - "107-MEASUREMENTS.md：O-6 结论（deferred + 复测路径 + 三条口径说明）、delta 上界与 α 未校准局限、per-call 超时不下调理由、待回填清单"
affects: [107-05, 107-09, 110]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "分位查询双轨：Postgres percentile_cont（精确，口径与运维大盘一致）+ 非 Postgres Python 线性插值回退，vendor 经 connection.vendor 分支（LOGGING-SPEC §4.3）"
    - "原始 SQL 安全范式：表名取自模型 Meta.db_table（不写死物理表名），事件名/时间窗/数值正则全走 %s 参数化绑定，SQL 由字符串拼接受控常量组成（零 f-string/%/format）"
    - "排障命令的退出码纪律：零样本是正常结果（退出码 0 + 排查提示），查询失败必须非零退出码可见"
    - "观测输出只含聚合量：payload 原文一律不回显，用例正向断言 stdout 无凭证形态串"

key-files:
  created:
    - server/codegraph/management/commands/measure_stage1_latency.py
    - server/tests/codegraph/test_measure_stage1_latency.py
    - .planning/phases/107-layered-presentation/107-MEASUREMENTS.md
  modified: []

key-decisions:
  - "延迟数据源取 SystemLogEntry.payload.duration_ms（事件 repo_router_v2_stage1_completed）而非 ModelUsageRecord——Stage 1 直调 build_chat_model(...).ainvoke(...) 不经 record_model_usage chokepoint，该表查不到 aux_repo_router 的行；ledger 口径对照留到 107-05 埋点补齐后"
  - "Postgres 侧先用参数化正则过滤 payload->>'duration_ms' 再 ::numeric，避免单条脏行让整条聚合查询报错，与 Python 侧「非数值即跳过」同口径"
  - "Python 回退只取 payload 一列并只提取 duration_ms，其余键不进内存结果（原文零外泄）"
  - "生产分位按数据环境标注纪律记 deferred；已有的 34–71s 只作为「既有生产观测」引用，明确标注不得当 p50/p90/p99 使用"
  - "α 的局限写成结构性因果（离线 harness 不跑 Stage 1 → α 恒 0 → golden 无法扫 α）并附红线：不得为校准 α 把凸组合塞进 harness 污染 phase106-v2 baseline"

patterns-established:
  - "MEASUREMENTS 文档五节骨架：数据环境标注 → 实测结论（含 deferred 占位表与口径说明）→ 设计取舍 → 参数取值依据与局限 → 待回填清单（UAT 交接）"
  - "口径先于数字：延迟文档先写清「测的是缓存未命中时的上游延迟、事件为采样类、采样率必须同记」，再给分位格，避免数字被误读成用户感知延迟"

requirements-completed: [RELY-05]

coverage:
  - id: D1
    description: "measure_stage1_latency 命令可在任意环境算出 Stage 1 延迟 p50/p90/p99 与样本量：Postgres 走 percentile_cont，非 Postgres 回退 Python 线性插值分位"
    requirement: "RELY-05"
    verification:
      - kind: unit
        ref: "tests/codegraph/test_measure_stage1_latency.py#test_quantiles_over_five_samples"
        status: pass
      - kind: unit
        ref: "tests/codegraph/test_measure_stage1_latency.py#test_json_mode_keys"
        status: pass
      - kind: other
        ref: "cd server && DATABASE_URL=<临时已 migrate 的 sqlite> uv run python manage.py measure_stage1_latency --days 7 --json（退出码 0，输出可 json.loads）"
        status: pass
    human_judgment: false
  - id: D2
    description: "过滤与容错口径：时间窗外的行、非目标事件的行不计入 n；payload 缺 duration_ms / 值非数值 / 空 payload 跳过不抛；零样本输出 n=0 与排查提示且不抛 ZeroDivisionError"
    requirement: "RELY-05"
    verification:
      - kind: unit
        ref: "tests/codegraph/test_measure_stage1_latency.py#test_rows_outside_window_are_excluded"
        status: pass
      - kind: unit
        ref: "tests/codegraph/test_measure_stage1_latency.py#test_other_events_are_excluded"
        status: pass
      - kind: unit
        ref: "tests/codegraph/test_measure_stage1_latency.py#test_missing_or_non_numeric_duration_is_skipped"
        status: pass
      - kind: unit
        ref: "tests/codegraph/test_measure_stage1_latency.py#test_zero_samples_does_not_raise"
        status: pass
    human_judgment: false
  - id: D3
    description: "输出零敏感串且 SQL 无注入面（T-107-02 / T-107-09）：stdout 只含聚合量；表名取自 Meta.db_table、参数化绑定，无 f-string/%/format 拼 SQL"
    verification:
      - kind: unit
        ref: "tests/codegraph/test_measure_stage1_latency.py#test_output_contains_no_secret_material"
        status: pass
      - kind: other
        ref: "rg -v '^[[:space:]]*#' <command> | rg -c '<物理表名>' == 0 且 rg -c 'f\"SELECT|% \\(|\\.format\\(' == 0"
        status: pass
    human_judgment: false
  - id: D4
    description: "107-MEASUREMENTS.md 如实记录 O-6 deferred 状态与复测路径、α 未经离线校准的结构性局限（D-7）、delta 上界 0.1771 与 gk-008 因果、per-call 超时不下调理由（与 107-01 A5 一致）、设计取舍与待回填清单"
    requirement: "RELY-05"
    verification:
      - kind: other
        ref: "rg 断言：deferred / measure_stage1_latency / 0.1771 / REPO_ROUTER_STAGE1_ALPHA 均命中；p99 行同时带 deferred"
        status: pass
    human_judgment: true
    rationale: "「per-call 不下调理由与 107-01 assumptions 不冲突」「无编造数字」「口径表述如实」属文本一致性判断，自动断言只能覆盖字面命中，需人工对读 107-01-PLAN.md A5 与本文档 §4.3"

# Metrics
duration: 22min
completed: 2026-07-30
status: complete
---

# Phase 107 Plan 02: O-6 延迟查询管线与 MEASUREMENTS 文档 Summary

**`measure_stage1_latency` 命令（Postgres `percentile_cont` / SQLite Python 分位双轨、输出零敏感串、零样本不抛）+ `107-MEASUREMENTS.md`（O-6 分位 deferred 但复测路径明确，delta 上界 / α 未校准 / per-call 不下调三条依据与局限在文）**

## Performance

- **Duration:** 约 22 min
- **Started:** 2026-07-29T21:28Z
- **Completed:** 2026-07-29T21:50Z
- **Tasks:** 2
- **Files modified:** 3（全部新建）

## Accomplishments

- **延迟分位可一条命令复测**：`measure_stage1_latency --days N [--event E] [--json]` 从系统日志落库表取 `repo_router_v2_stage1_completed` 事件 payload 的 `duration_ms` 算 p50/p90/p99 与样本量。Postgres 用 `percentile_cont(...) WITHIN GROUP`（精确，口径与运维大盘一致，LOGGING-SPEC §4.3 纪律「不自研直方图」）；非 Postgres 自动回退 Python 侧线性插值分位（与 `repo_router_eval._quantile` 同口径，stdlib，零新增依赖）。
- **数据源纠偏落到代码里**：命令 docstring 写明「不能用 `ModelUsageRecord`」及其原因（Stage 1 直调 `ainvoke` 不经 `record_model_usage` chokepoint），并指向 107-05 的埋点补齐——后续读者不会再走错数据源。
- **安全边界双向守护**：输出只含 `event` / `window_days` / `window_start` / `db_vendor` / `n` / 三个分位（T-107-02，用例正向断言 stdout 不含 `sk-` / `Bearer ` / `AIza` 与 payload 原文片段）；原始 SQL 的表名取自模型 `Meta.db_table`、事件名与时间窗与数值正则全走 `%s` 参数化绑定（T-107-09，验收断言禁 f-string/`%`/`format` 拼 SQL）。
- **零样本是正常结果、查询失败必须可见**：无匹配行 → 退出码 0 + `n=0` + 三种常见成因提示（采样配置 / 组件日志级别被调到 WARNING / 缓存命中率过高）；查询本身异常 → 脱敏后 warning 留痕并以非零退出码结束。
- **`107-MEASUREMENTS.md` 五节齐备**：数据环境标注（本地/CI 一律 `n=0（无生产数据）`，生产行 deferred + 复测命令）→ O-6 分位占位表 + 三条口径说明 → 设计取舍（压不下来时收益来自缓存/快照回放/总预算硬上界）→ 三个数值参数的依据与局限 → 待回填清单（4 项 UAT 交接）。

## Task Commits

1. **Task 1: measure_stage1_latency 命令 + 单测（TDD）** — `9cb4533a`（test，RED：命令不存在即失败）→ `ca399789`（feat，GREEN：7 用例全绿）
2. **Task 2: 107-MEASUREMENTS.md** — `9e3815ec`（docs）

## Files Created/Modified

- `server/codegraph/management/commands/measure_stage1_latency.py` — Stage 1 延迟分位查询命令（`--days` / `--event` / `--json`；vendor 双轨分位；`stage1_latency_measured` 采样类事件，`initiated_by_user_id="system"`，观测块 best-effort 包裹）
- `server/tests/codegraph/test_measure_stage1_latency.py` — 7 用例覆盖分位/时间窗/事件名过滤、非数值 payload 跳过、零样本不抛、`--json` 键集合、stdout 零敏感串
- `.planning/phases/107-layered-presentation/107-MEASUREMENTS.md` — O-6 结论与三个数值参数的取值依据/局限/待回填清单

## Decisions Made

- **数据源锁 `SystemLogEntry.payload.duration_ms`**：107-RESEARCH §9 已 VERIFIED「Stage 1 不落 `ModelUsageRecord`」，故本命令不查 ledger；ledger 口径对照写成 §5 待回填清单第 4 项，等 107-05 补齐埋点后再做（本 plan 不预写代码）。
- **Postgres 侧先正则过滤再 `::numeric`**：单条脏行（`duration_ms` 为非数值）在纯 `::numeric` 写法下会让整条聚合查询报错。用参数化正则先过滤，行为与 Python 回退侧「非数值即跳过」一致，两轨口径不背离。
- **Python 回退只取 `payload` 一列并只提取 `duration_ms`**：不取 `message` 等自由文本，其余 payload 键不进内存结果——即使日志里有上游错误文本也不可能流到 stdout。
- **命令统计口径写在 docstring 顶部三条**（缓存未命中的上游延迟 / 采样类事件受采样配置影响 / 分位口径双轨），与文档 §2 同源，避免代码与文档两处说法漂移。
- **文档不写任何编造分位数字**：p50/p90/p99 三格均为 `deferred`；既有的「34–71s」只作为**既有生产观测**引用，明确标注「不得当作 p50/p90/p99 使用」，仅用于支撑「per-call 90s 已接近可接受上界量级」的量纲判断。
- **α 局限写成结构性因果 + 红线**：离线 harness（`score_case` / `evaluate_cases`）结构上不跑 Stage 1（α 恒 0）→ golden set 无法扫 α；并显式写下「不得为校准 α 把凸组合塞进 harness」——那会污染 `phase106-v2` baseline 与 106-07 回放比对，同时违反 D-3。

## Deviations from Plan

None - plan executed exactly as written.

（说明：计划 `<known_assertion_pitfall>` 提示的「注释含被禁字面量导致自己验收必红」未发生——实现时对物理表名与 SQL 拼接写法一律采用「描述因果不写出字面量」的措辞，两条归零断言在滤注释行前后都为 0，无需放宽或删除断言。）

## Issues Encountered

- **验收命令在本地 dev 库上以非零退出码结束**：`cd server && uv run python manage.py measure_stage1_latency --days 7 --json` 直接跑会报「缺表」并退出码 1——原因是本地 dev 库（`DATA_DIR/friday.db`）尚未 migrate 到含系统日志落库表的版本，**不是命令缺陷**（缺表属查询异常，按计划设计就该非零退出码可见）。改为在临时 `DATABASE_URL` 指向的**已 migrate** SQLite 上验证零样本路径：退出码 0、输出可 `json.loads`、`n=0` 且带 `note` 提示，criterion 语义达成。未对用户的 dev 库执行 migrate（避免副作用）。
- **`ruff format` 与 SQL 拼接写法的取舍**：多段字符串相加的 `select_parts` 行超长，`ruff format` 会拆成逐项换行的加法链——已按 formatter 输出定稿（`ruff check` + `ruff format --diff` 均干净），拼接结构不变、仍无 f-string。

## User Setup Required

None - 无外部服务配置。生产分位回填是**运维执行既有命令**的动作（见 107-MEASUREMENTS.md §5 待回填清单），不需要新配置项。

## Next Phase Readiness

- **107-05 可直接接续**：Stage 1 的 `ModelUsageRecord` 埋点补齐后，只需在 107-MEASUREMENTS.md §5 第 4 项做一次 ledger 口径对照，本命令无需改动。
- **A5 收口有了依据**：per-call 超时是否从 90.0 下调，判定输入（O-6 p90/p99 + 建议区间 40–45s + 降级率评估）与回填位置均已在文档中定位。
- **待生产回填（不阻塞本 phase）**：O-6 分位、执行时刻的采样率与组件日志级别快照——两项都在 §5 清单里并标注「记入 107-UAT」。
- **口径提醒**：本命令测的是缓存未命中时的上游延迟，不能当用户感知延迟指标使用；若后续要做用户感知延迟，需另取包含缓存命中路径的观测点。

## Self-Check: PASSED

- 三个交付文件均存在（命令 / 测试 / MEASUREMENTS）。
- 三个 task 提交均在 git 历史中（`9cb4533a` test / `ca399789` feat / `9e3815ec` docs）。
- `STATE.md` / `ROADMAP.md` 零改动（本次执行范围明确排除）。

---
*Phase: 107-layered-presentation*
*Completed: 2026-07-30*
