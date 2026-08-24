---
phase: 133-commit-v0-22-baseline
plan: 02
subsystem: testing
tags: [benchmark, eval, gold-dataset, fixtures, json, anti-circular, watermark]

# Dependency graph
requires:
  - phase: 133-commit-v0-22-baseline
    provides: "Plan 01 graph_bench_eval.py：validate_gold_case/validate_gold_dataset + 四闭集常量（LANGUAGES/FRAMEWORKS/ENTRY_TYPES/CALL_SHAPES）"
provides:
  - "server/tests/fixtures/graph_bench/ 冻结 gold 数据集：manifest（gold_version/annotated_at_sha/splits/防反导 _doc）"
  - "dev.json + locked_test.json：覆盖 symbol/process/edge/trace/impact 全指标路径与多分桶的 seed case（edge_golds 带 call_shape 与 evidence_file_line 独立 callsite 锚点）"
  - "holdout.json 空壳（Phase 140 填充）+ README（标注口径/四维分桶/防反导声明/水位对齐/扩容 runbook）"
affects: [133-03, 133-04, 140]

# Tech tracking
tech-stack:
  added: []
  patterns: [版本化冻结 gold fixtures（沿袭 repo_route_recall/layered_search_golden 约定），独立于被测 codegraph]

key-files:
  created:
    - server/tests/fixtures/graph_bench/manifest.json
    - server/tests/fixtures/graph_bench/dev.json
    - server/tests/fixtures/graph_bench/locked_test.json
    - server/tests/fixtures/graph_bench/holdout.json
    - server/tests/fixtures/graph_bench/README.md
  modified: []

key-decisions:
  - "annotated_at_sha 用显式占位符（REPLACE_WITH_TARGET_REPO_LAST_INDEXED_COMMIT_SHA），并在 manifest._doc 与 README 钉死「评测者运行前须以目标仓实际 last_indexed_commit_sha 对齐并冻结」"
  - "dev/locked_test 两切分分桶组合刻意不同（dev 含 python/none/process_entry，locked_test 含 go/gin/process_entry），让 Plan 03 分桶与 INSUFFICIENT_DATA 逻辑有真实多桶输入"

patterns-established:
  - "Pattern 1: edge_golds 每条必带 call_shape 与 evidence_file_line（独立 callsite 人工核验锚点），不从被测 CallEdge 反导"
  - "Pattern 2: 分桶四维（language/framework/entry_type/call_shape）为必填标注字段，显式填写不从被测图派生"

requirements-completed: [BENCH-02]

# Coverage metadata
coverage:
  - id: D1
    description: "manifest.json 含 gold_version/annotated_at_sha/splits 三键且 splits 含 dev/locked_test/holdout 映射"
    requirement: BENCH-02
    verification:
      - kind: other
        ref: "cd server && uv run python -c (manifest 三键断言)"
        status: pass
    human_judgment: false
  - id: D2
    description: "dev/locked_test seed case 覆盖全指标路径与多分桶，四维分桶必填且落闭集，edge gold 带 evidence_file_line，含 protected/impact/trace 用例"
    requirement: BENCH-02
    verification:
      - kind: other
        ref: "cd server && uv run python -c (cases/buckets/closed-set 三条断言)"
        status: pass
      - kind: unit
        ref: "codegraph.services.graph_bench_eval.validate_gold_dataset + validate_gold_case（6 case 全通过）"
        status: pass
    human_judgment: false
  - id: D3
    description: "holdout.json 为空壳 {cases: []}；README 写明标注口径/四维分桶/防反导声明/水位对齐/扩容 runbook"
    requirement: BENCH-02
    verification:
      - kind: other
        ref: "cd server && uv run python -c (holdout=={'cases':[]}) + grep 水位/切分/防反导关键词计数"
        status: pass
    human_judgment: false

# Metrics
duration: 5min
completed: 2026-08-24
status: complete
---

# Phase 133 Plan 02: graph_bench 冻结 gold 数据集（manifest + 三切分 + README）Summary

**为 v0.22 图查询 baseline 落地可版本化、独立于被测 codegraph 的冻结 gold 数据集：manifest（gold_version + annotated_at_sha + splits + 防反导声明）+ dev/locked_test 双切分 seed case（四维分桶必填、edge gold 带独立 callsite 锚点）+ holdout 空壳 + 标注口径 README**

## Performance

- **Duration:** 5 min
- **Started:** 2026-08-24T09:40:47Z
- **Completed:** 2026-08-24T09:45:41Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- `manifest.json`：gold_version="1"、annotated_at_sha 占位符（`_doc` 钉死须对齐目标仓 `last_indexed_commit_sha`）、splits 三键映射、防循环论证 `_doc` 声明（gold 独立标注、禁从被测 codegraph 反向导出、resolved edge 来自独立 callsite 抽样）
- `dev.json` + `locked_test.json`：各 3 条 seed case，合起来覆盖 symbol/process/edge/trace/impact 全部五条指标路径；每条填齐 language/framework/entry_type 必填维度且取值落在 Plan 01 闭集；每条 edge_golds 带 `call_shape` 与 `evidence_file_line`（形如 `path/to/file.py:123`）独立 callsite 标注锚点
- 两切分分桶组合刻意不同：dev 含 python/django/http_endpoint（protected）、typescript/vue/plain_symbol、python/none/process_entry；locked_test 含 python/django/http_endpoint、typescript/vue/plain_symbol、go/gin/process_entry —— 让 Plan 03 的分桶与 INSUFFICIENT_DATA 逻辑有真实多桶输入
- 含 protected=true（dev-0001）、impact_golds（dev-0001、lt-0001）、trace_golds（dev-0002/0003、lt-0002/0003）用例
- `holdout.json` 空壳（`{"cases": []}`）留 Phase 140；`README.md` 写明标注口径、四维分桶闭集、防反导声明、水位对齐与扩容 runbook
- 交叉校验：6 条 case 全部通过 Plan 01 的 `validate_gold_dataset` + `validate_gold_case`（schema 与 wave 1 校验器对齐）

## Task Commits

Each task was committed atomically:

1. **Task 1: manifest + dev + locked_test 数据集文件** - `8f822092` (feat)
2. **Task 2: holdout 空壳 + 标注口径 README** - `88ce7e63` (docs)

## Files Created/Modified

- `server/tests/fixtures/graph_bench/manifest.json` - 数据集身份：gold_version / annotated_at_sha / repository / branch / splits / 防反导 _doc
- `server/tests/fixtures/graph_bench/dev.json` - baseline 用 dev 切分 3 条 seed case（含 protected + impact + trace）
- `server/tests/fixtures/graph_bench/locked_test.json` - baseline 用 locked test 切分 3 条 seed case（含 go/gin 桶）
- `server/tests/fixtures/graph_bench/holdout.json` - holdout 空壳（Phase 140 填充，baseline 不读）
- `server/tests/fixtures/graph_bench/README.md` - 标注口径 / 四维分桶 / 防反导声明 / 水位对齐 / 扩容 runbook

## Decisions Made

- `annotated_at_sha` 用显式占位符而非编造 SHA：当前无真实冻结目标仓，编一个看似真实的 SHA 会被误当已对齐水位；占位符 + `_doc`/README 双重声明「运行前须对齐 `last_indexed_commit_sha`」更安全（BENCH-01 INVALID 校验前提）
- 两切分分桶组合刻意不同（dev 出 python/none、locked_test 出 go/gin）：避免两切分桶完全一致，让 Plan 03 的分桶聚合与稀疏桶标记有真实多桶输入可消费

## Deviations from Plan

None - plan executed exactly as written.

（说明：plan 验收命令以 `cd server && python` 书写，本机 `server/.python-version` 指向的 pyenv 3.14.2 未安装，改用 `uv run python` 执行同一断言；为环境执行方式差异，非计划内容偏差。另在 plan 验收之外，额外用 Plan 01 的 `validate_gold_dataset`/`validate_gold_case` 对 6 条 case 做了一次交叉校验（全通过），以确认闭集取值与 wave 1 校验器对齐——这是 plan key_links 要求的一致性核验，不属新增工作。）

## Issues Encountered

- `python` 直接调用触发 pyenv 报 `3.14.2 is not installed`（`server/.python-version` 钉的版本本机未装）。改用 `uv run python`（走 `server/uv.lock` 锁定的解释器）执行全部验收断言，功能等价。
- 单条 Bash 复合命令里第二个 `cd server` 在 cwd 已是 `server/` 时失败导致后续 grep 找不到文件；改用绝对路径单次 `cd` 重跑即过。为 shell 使用问题，非产物问题。

## User Setup Required

None - no external service configuration required.

## Known Stubs

以下为**有意为之**的占位，已在 README 与 manifest._doc 显式声明，不阻碍本 plan 目标（ authoring 冻结数据集结构与 seed case）：

- `manifest.json` 的 `annotated_at_sha` / `repository` 为占位符——真实冻结仓的独立标注与水位对齐是评测者运行真实 baseline 前的后续动作（README 扩容 runbook 第 1 步）。
- `dev.json` / `locked_test.json` 的 uid/file_line 为最小 seed 标注（让 harness 端到端可跑），并非对某个真实已索引仓的完整独立标注——README 已说明完整标注是后续动作。
- `holdout.json` 为 `{cases: []}` 空壳，由 Phase 140 最终验收填充。

## Threat Flags

无新增威胁面。本 plan 只 authoring 仓内版本化 JSON/MD fixtures，不引入网络端点、auth 路径、文件访问或 schema 信任边界变更；threat_model 中 T-133-04/05（gold 被被测图污染、水位/版本漂移）已通过 evidence_file_line 必填、防反导声明与水位对齐声明落地为文档与数据约束。

## Next Phase Readiness

- Plan 03（指标/分桶/报告）可直接消费本分桶四维与 edge/trace/impact gold 字段；多桶输入已就位
- Plan 04（薄 command）可将 dev/locked_test 作为真实输入端到端跑；schema 与 Plan 01 `validate_gold_dataset` 完全对齐，command 加载即可过校验
- 无 blocker；真实冻结仓选定与完整独立标注为评测者后续动作（README runbook）

## Self-Check: PASSED

- `server/tests/fixtures/graph_bench/manifest.json` — FOUND
- `server/tests/fixtures/graph_bench/dev.json` — FOUND
- `server/tests/fixtures/graph_bench/locked_test.json` — FOUND
- `server/tests/fixtures/graph_bench/holdout.json` — FOUND
- `server/tests/fixtures/graph_bench/README.md` — FOUND
- commit `8f822092` / `88ce7e63` — 均 FOUND in git log

---
*Phase: 133-commit-v0-22-baseline*
*Completed: 2026-08-24*
