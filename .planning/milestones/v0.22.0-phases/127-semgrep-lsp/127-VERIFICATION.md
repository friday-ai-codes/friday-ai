---
phase: 127-semgrep-lsp
verified: 2026-08-10T18:49:12Z
status: human_needed
score: 4/4 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 2/4
  gaps_closed:
    - "MR 流程可触发 Semgrep diff-aware 扫描（--baseline-commit 取 merge-base），只报本次 MR 新增 finding；Semgrep 以独立 CLI/venv 形态集成，不进 server Python 依赖树"
    - "finding 带 severity 分级进 MR 描述/评论；门禁默认报告不阻断（advisory）；nosemgrep 误报通道生效；扫描超时 fail-open 且显式标注"
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "构建 server 镜像后记录相对基线的 size delta（+400–550MB 量级）写入发布说明"
    expected: "镜像含 /opt/semgrep、Node 22、vue-language-server、gopls；体积增量可审计"
    why_human: "需真实 docker build / docker images；静态读 Dockerfile 无法验证体积"
  - test: "在代表性 1× Vue/TS + 1× Go 仓上跑 measure_lsp_baseline，复核 D-16 保持默认 False 的判定"
    expected: "报告含 before/after 质量/耗时字段；recommend_flip_defaults 与 SUMMARY/ROADMAP 一致"
    why_human: "当前 lsp-baseline-report.json 缺仓与 gopls PATH，索引墙钟为 null；需真实环境复跑"
  - test: "开启 LSP 并重建索引后，用真实 CrossRepoApiCall 样本复验 IMPACT-03 四分支"
    expected: "样本 >0 时测出 (file_path, name) 命中率；样本仍为 0 则继续诚实延期"
    why_human: "依赖生产/夹具索引数据；本相位已诚实延期记账，闭环需人/环境"
---

# Phase 127: Semgrep 门禁 + LSP 基准 Verification Report

**Phase Goal:** MR 有外购的 taint 安全扫描（advisory 起步、边界如实声明），LSP 抽取后端开启门槛降低且有质量/耗时基准数据——两条与内存图零耦合的独立轨道收尾

**Verified:** 2026-08-10T18:49:12Z  
**Status:** human_needed  
**Re-verification:** Yes — after gap closure (previous `gaps_found` 2/4)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | ------- | ---------- | -------------- |
| 1 | MR 流程可触发 Semgrep diff-aware 扫描（`--baseline-commit` = merge-base）；Semgrep 独立 CLI，不进 server 依赖树 | ✓ VERIFIED | 三挂点均改走 `enqueue_semgrep_scan_for_branches`（`coding.py` L2325–2331 / L2372–2378；`mr_service.py` L273–280；`merge_request_service.py` L232–238）。解析链：`semgrep_sha.resolve_scan_shas`（known → `GitHubClient`/`GitLabClient.resolve_branch_sha` → `ensure_mirror_commit`）。两端非空才 `enqueue_semgrep_scan`；否则 `code_graph_enqueue_semgrep_scan_skipped_missing_sha` 且不入队。挂点测试断言 payload 含完整 40 位 sha（`test_coding_security_scan` / `test_mr_security_scan`）。CLI/merge-base/独立 `/opt/semgrep` 仍在 |
| 2 | finding 带 severity 进 MR；advisory；`nosemgrep`；超时 fail-open 显式标注 | ✓ VERIFIED | Level 4 已通：非空 SHA → durable `run_semgrep_scan` → persist `SecurityFinding.severity` → `maybe_patch_security_scan_section` → `_load_findings_for_mr` → `build_security_scan_section` / `_render_findings`（ERROR/WARNING/INFO 桶）。advisory / CE+`nosemgrep` / `stub_security_scan_section("timeout")` 单测绿。**可证接线**；**活体 finding 仍依赖** git 平台 SHA 解析 + mirror worktree + `SEMGREP_BIN` |
| 3 | 门禁文案如实声明 CE 仅函数内 taint；Pro 经加密 `SEMGREP_APP_TOKEN` opt-in | ✓ VERIFIED | `_CE_DISCLAIMER`；`semgrep_token` + Fernet；Pro 判定含 env escape hatch（MJ-02）；回归通过 |
| 4 | server 镜像补齐 Node/Go；volar/gopls 探测 + fail-soft + 孤儿清扫；基准报告驱动默认翻转（不盲翻） | ✓ VERIFIED | Dockerfile 层；`orphan_reap`；`VOLAR`/`GOPLS` 默认 False；`lsp-baseline-report.json` `recommend_flip_defaults: false`；IMPACT-03 诚实延期 |

**Score:** 4/4 truths verified

### Gap Closure Detail (re-verification)

#### Gap 1 — MR 可触发 diff-aware 扫描 — CLOSED

| Check | Result |
| ----- | ------ |
| Empty SHA literals at hang-points | ✗ gone — no `source_sha=""` / `target_sha=""` enqueue at former sites |
| Guarded entry | `enqueue_semgrep_scan_for_branches` (`semgrep_enqueue.py` L102–164) resolves then enqueues or skips |
| SHA resolver | `semgrep_sha.py` L87–135；platform clients L89–107 (GitHub) / L218–243 (GitLab) |
| Stub-then-async | hang-points `attach_security_scan_pending(..., enqueue=False)` then post-create enqueue with `client` |
| Unit proof | `test_coding_create_mr_appends...` asserts `source_sha`/`target_sha` == 40-hex；skip path when unresolvable |

**Provably wired vs live deps:** Wiring + mocked platform SHA → non-empty durable payload is proven. Live scan still needs resolvable branches (API or warm mirror) and Semgrep binary on PATH/`SEMGREP_BIN`.

**Guarded skip assessment:** Refusing to enqueue when either SHA is unresolvable is the **correct fail-open** for MR creation: avoids permanent `unavailable` stubs from doomed jobs, leaves human-readable `pending`, and emits `code_graph_enqueue_semgrep_scan_skipped_missing_sha`. In common deployments with working GitHub/GitLab clients, `resolve_branch_sha` supplies SHAs; local bare mirror is fallback. Residual ops risk: dual failure (platform + cold/missing mirror) leaves pending forever until next create/reuse — observable in logs, not a hidden silent no-op of the previous empty-SHA enqueue.

#### Gap 2 — severity finding 进 MR — CLOSED (unblocked by Gap 1)

| Stage | Status |
| ----- | ------ |
| Persist findings with severity | ✓ `semgrep_scan.py` persist `severity` |
| Durable → MR patch | ✓ `tasks_impl.py` L972–976 → `patch_mr_security_scan_section` |
| Load + render severity buckets | ✓ `_load_findings_for_mr` + `_render_findings` (`security_scan_report.py`) |
| Level 4 | ✓ FLOWING when scan succeeds (no longer HOLLOW from empty SHA) |

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/services/code_graph/semgrep_sha.py` | SHA resolve chain | ✓ VERIFIED | new since gap closure |
| `server/services/code_graph/semgrep_enqueue.py` | `enqueue_semgrep_scan_for_branches` | ✓ VERIFIED | skip-if-missing-sha |
| `GitHubClient` / `GitLabClient.resolve_branch_sha` | platform HEAD | ✓ VERIFIED | fail-soft empty string |
| Hang-points (coding / mr_service / MCP) | route through guarded enqueue | ✓ VERIFIED | with `client`; `enqueue=False` on stub attach |
| `semgrep_scan.py` / Dockerfile / SecurityFinding / report helpers | prior phase core | ✓ VERIFIED | regression OK |
| `codegraph/migrations/0015_securityfinding_unique_fingerprint.py` | UniqueConstraint | ✓ VERIFIED | MJ-01 |
| LSP baseline / orphan / defaults | prior | ✓ VERIFIED | unchanged |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | ---- | ------ | ------- |
| coding / mr_service / MCP | `enqueue_semgrep_scan_for_branches` | post-MR-success + client | ✓ WIRED | SHAs resolved before enqueue |
| `enqueue_semgrep_scan_for_branches` | `resolve_scan_shas` | known→client→mirror | ✓ WIRED | |
| `enqueue_semgrep_scan` | QUEUE_SCAN / durable | defer payload | ✓ WIRED | only when both SHAs set |
| durable `run_semgrep_scan` | CLI + SecurityFinding | merge-base argv | ✓ WIRED | when SHAs present |
| durable result | MR body | `maybe_patch` → severity section | ✓ WIRED | |
| CE/Pro / LSP paths | (unchanged) | — | ✓ WIRED | regression |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| MR `## 安全扫描` stub | description | `attach_security_scan_pending(..., enqueue=False)` | pending stub | ✓ FLOWING |
| durable `source_sha`/`target_sha` | scan inputs | `resolve_scan_shas` via hang-point client/mirror | non-empty when resolvable | ✓ FLOWING |
| Semgrep CLI findings | `SecurityFinding` rows | `run_semgrep_scan` persist | when binary + worktree OK | ✓ FLOWING (wired; live binary env-dep) |
| MR severity section | findings list | `_load_findings_for_mr` → `_render_findings` | when scan persisted | ✓ FLOWING |
| Skip path | no enqueue | missing SHA | pending retained + warning log | ✓ intentional |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Phase 127 pytest suite (54) | see below | **54 passed** in 9.30s | ✓ PASS |
| Hang-point non-empty SHAs | `test_coding_create_mr_appends_security_scan_and_enqueues` etc. | PASSED | ✓ PASS |
| Skip when unresolvable | `test_coding_enqueue_skipped_when_sha_unresolvable` / MCP twin | PASSED | ✓ PASS |
| SHA resolver unit | `test_semgrep_sha.py` (6) | PASSED | ✓ PASS |

### Probe Execution

| Probe | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| — | — | No phase-declared `scripts/*/tests/probe-*.sh` | SKIPPED |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| TAINT-01 | 127-01..03 | diff-aware Semgrep + independent CLI | ✓ SATISFIED | SHA resolve + enqueue + CLI isolation |
| TAINT-02 | 127-01, 127-04 | severity / advisory / nosemgrep | ✓ SATISFIED | Level 4 unblocked; report helpers |
| TAINT-03 | 127-02, 127-04 | CE 边界 + Pro token | ✓ SATISFIED | disclaimer + Fernet + env hatch |
| LSP-01 | 127-02, 127-05 | 镜像/探测/孤儿/基准/不盲翻 | ✓ SATISFIED | Dockerfile + orphan + baseline |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| — | — | Former empty-SHA hang-point literals | — | **Resolved** (Gap 1 closed) |
| Phase 127 modules | — | TBD/FIXME/XXX | — | None found |

### New Issues (this re-verification)

| Item | Severity | Notes |
| ---- | -------- | ----- |
| Pending-forever if SHA dual-fail | ℹ️ Info | Guarded skip is intentional; ops should alert on `code_graph_enqueue_semgrep_scan_skipped_missing_sha`. Does **not** reopen Gap 1 |
| End-to-end live Semgrep on real MR | ℹ️ Info | Covered by human/env deps below — not an automated must-have failure |

### Observability Compliance (phase 127)

| Check | Status |
| ----- | ------ |
| structlog + started/completed/failed + `duration_ms` | ✓ |
| `category` + `component` | ✓ |
| skip event `code_graph_enqueue_semgrep_scan_skipped_missing_sha` | ✓ |
| `initiated_by_user_id` on durable/enqueue | ✓ |
| redact on hang-point / errors | ✓ MJ-03 |
| No `import semgrep` / GraphService coupling | ✓ |

### Human Verification Required

#### 1. 镜像体积审计

**Test:** 构建 server 镜像并记录 size delta  
**Expected:** Semgrep/Node/Go/LSP 层可用；体积可写入发布说明  
**Why human:** 需真实 `docker build`

#### 2. LSP 基准复跑

**Test:** 在 Vue/TS + Go 仓上跑 `measure_lsp_baseline`  
**Expected:** 完整 before/after；确认保持默认 False  
**Why human:** 当前报告缺仓与 gopls PATH

#### 3. IMPACT-03 真实样本

**Test:** LSP 开启并重建索引后复验四分支  
**Expected:** 命中率可测或继续诚实延期  
**Why human:** 依赖索引数据（本相位已诚实延期）

### Gaps Summary

Previous blockers (empty SHA enqueue → scan always `unavailable` → severity section HOLLOW) are **closed**. All 4 roadmap must-haves are verified in code with 54/54 phase tests passing. Status is `human_needed` solely for the three retained environment/human checks (docker size, live LSP baseline, IMPACT-03 samples) — not for the former SHA/finding gaps.

---

_Verified: 2026-08-10T18:49:12Z_  
_Verifier: Claude (gsd-verifier)_
