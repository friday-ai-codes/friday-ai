---
phase: 133
slug: commit-v0-22-baseline
status: active
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-24
---

# Phase 133 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x（pytest-asyncio auto / pytest-django / pytest-socket 网络隔离） |
| **Config file** | `server/pyproject.toml`（`[tool.pytest.ini_options]`，asyncio_mode=auto） |
| **Quick run command** | `cd server && uv run pytest tests/codegraph/ -k graph_bench -q` |
| **Full suite command** | `cd server && uv run pytest tests/codegraph/test_graph_bench_watermark.py tests/codegraph/test_graph_bench_gold_schema.py tests/codegraph/test_graph_bench_eval.py tests/codegraph/test_evaluate_graph_bench_command.py -q` |
| **Estimated runtime** | ~60 秒（纯逻辑，integration/perf 标记默认排除） |

---

## Sampling Rate

- **After every task commit:** Run `cd server && uv run pytest tests/codegraph/ -k graph_bench -q`
- **After every plan wave:** Run the Full suite command above
- **Before `/gsd-verify-work`:** Full suite must be green（integration 标记用例除外，见 Manual-Only）
- **Max feedback latency:** 60 秒

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 133-01-01 | 01 | 1 | BENCH-01 | T-133-SC | 水位不一致 → INVALID fail-closed，不产结论 | unit | `cd server && uv run pytest tests/codegraph/test_graph_bench_watermark.py -q` | ❌ W0 | ⬜ pending |
| 133-01-02 | 01 | 1 | BENCH-02 | T-133-SC | gold schema 闭集校验，缺必填字段即拒 | unit | `cd server && uv run pytest tests/codegraph/test_graph_bench_gold_schema.py -q` | ❌ W0 | ⬜ pending |
| 133-02-01 | 02 | 1 | BENCH-02 | T-133-SC | gold 独立标注、防反导 evidence_file_line 必填 | unit | `cd server && python -c "import json; json.load(open('tests/fixtures/graph_bench/manifest.json'))"` | ❌ W0 | ⬜ pending |
| 133-02-02 | 02 | 1 | BENCH-02 | — | holdout 空切分 + README 防反导说明 | unit | `cd server && test -s tests/fixtures/graph_bench/README.md` | ❌ W0 | ⬜ pending |
| 133-03-01 | 03 | 2 | BENCH-04 | — | 六 scorer 纯函数 + 固定分母 | unit | `cd server && uv run pytest tests/codegraph/test_graph_bench_eval.py -q` | ❌ W0 | ⬜ pending |
| 133-03-02 | 03 | 2 | BENCH-05 | — | 分桶 + INSUFFICIENT_DATA + macro + 受保护桶单列 | unit | `cd server && uv run pytest tests/codegraph/test_graph_bench_eval.py -q` | ❌ W0 | ⬜ pending |
| 133-03-03 | 03 | 2 | BENCH-03 | — | build_report 无阈值字段（grep==0） | unit | `cd server && grep -cE 'tolerance\|threshold\|compare_to_baseline\|target_value' codegraph/services/graph_bench_eval.py` == 0 | ❌ W0 | ⬜ pending |
| 133-04-01 | 04 | 3 | BENCH-01 | T-133-SC | command INVALID 短路 + schema 错误 fail-closed | unit | `cd server && uv run pytest tests/codegraph/test_evaluate_graph_bench_command.py -q` | ❌ W0 | ⬜ pending |
| 133-04-02 | 04 | 3 | BENCH-03 | — | 只读真跑 v0.22 能力产原始 baseline | integration | `cd server && uv run pytest tests/codegraph/test_graph_bench_integration.py -q -m integration`（默认排除） | ❌ W0 | ⬜ pending |
| 133-04-03 | 04 | 3 | BENCH-01 | T-133-SC | caller/sampling 埋点、脱敏、initiated_by_user_id=system | unit | `cd server && uv run pytest tests/codegraph/test_evaluate_graph_bench_command.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] 既有 pytest 基础设施覆盖（`server/pyproject.toml` + `server/tests/conftest.py`），无需新装框架
- [x] `server/tests/codegraph/` 测试目录沿用既有 codegraph 测试布局
- [x] `server/tests/fixtures/graph_bench/` 冻结数据集目录由 Plan 02 建立

*Existing infrastructure covers the test harness; new files are phase deliverables, not framework installs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 实仓端到端产出真实 baseline 数据 | BENCH-03 | 需已索引仓 + Qdrant，per-branch `last_indexed_commit_sha` 与 manifest `annotated_at_sha` 对齐；执行环境离线不可达 | 索引目标仓后运行 `evaluate_graph_bench` command，确认逐 case baseline + run manifest 产出且无阈值字段 |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-08-24
