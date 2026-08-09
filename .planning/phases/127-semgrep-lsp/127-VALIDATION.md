---
phase: 127
slug: semgrep-lsp
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-08-10
---

# Phase 127 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `127-RESEARCH.md` § Validation Architecture.
> Aligned to final five plan IDs: `127-01` .. `127-05`（无幽灵第六 plan）。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-django（server） |
| **Config file** | `server/pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest <scoped> -q --reuse-db` |
| **Full suite command** | `cd server && uv run pytest -q`（注意 addopts 排除 `perf/integration/slow/postgres_queue`） |
| **Estimated runtime** | ~30–90 seconds（quick）；full suite per CI norms |

---

## Sampling Rate

- **After every task commit (quick):** Run the relevant new/changed test files from the Per-Task map only（scoped pytest，非全量）
- **After every plan wave (full-for-wave):** Scoped suite covering that plan’s Automated Command column
- **Before `/gsd-verify-work` (full phase):** Default suite green；已知 `mcp` snapshot 漂移仍白名单（D-18）
- **Max feedback latency:** 90 seconds（quick）

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 127-01 | 127-01 | 0 | TAINT-01..03 + LSP-01 | T-127-01..05 | Wave 0 stubs + fixture + frozen-surface before impl | unit/collect | `pytest … --collect-only -q`（见 127-01 PLAN verify） | ✅ | ⬜ pending |
| 127-02 | 127-02 | 1 | TAINT-01 + TAINT-03(key) + LSP-01(image/defaults) | T-127-01 | Dockerfile 层；SecurityFinding；Fernet token；LSP 默认 False | unit/smoke | `pytest tests/services/code_graph/test_dockerfile_semgrep_lsp_layers.py tests/codegraph/test_security_finding_model.py tests/services/code_graph/test_semgrep_app_token.py tests/codegraph/test_lsp_defaults_unchanged.py -q` | ✅ W0 | ⬜ pending |
| 127-03 | 127-03 | 2 | TAINT-01 | T-127-02/03 | CLI argv / fail-open / QUEUE_SCAN enqueue | unit | `pytest tests/services/code_graph/test_semgrep_scan.py tests/services/code_graph/test_semgrep_enqueue.py -q` | ✅ W0 | ⬜ pending |
| 127-04 | 127-04 | 3 | TAINT-02 + TAINT-03 | T-127-01/05 | MR `## 安全扫描` advisory/CE/nosemgrep + dual hang-points | unit | `pytest tests/services/code_graph/test_security_scan_report.py tests/workflows/test_coding_security_scan.py tests/mcp_tools/test_mr_security_scan.py -q` | ✅ W0 | ⬜ pending |
| 127-05 | 127-05 | 4 | LSP-01 | T-127-04 | orphan reap + IMPACT-03 revisit/honest defer + defaults；`depends_on: [127-02, 127-04]` | unit/cmd | `pytest codegraph/lsp/tests/test_orphan_reap.py tests/codegraph/test_revisit_impact03.py tests/codegraph/test_lsp_defaults_unchanged.py -q` | ✅ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `server/tests/services/code_graph/test_semgrep_scan.py` — TAINT-01 CLI 契约 / fail-open
- [x] `server/tests/services/code_graph/test_security_scan_report.py` — TAINT-02/03 段文案与幂等
- [x] `server/tests/services/code_graph/test_semgrep_enqueue.py` — QUEUE_SCAN / lock / idempotency
- [x] `server/tests/services/code_graph/test_semgrep_app_token.py` — D-09 Fernet 写读 round-trip
- [x] `server/tests/codegraph/test_security_finding_model.py` — 模型字段 / 无 Symbol FK
- [x] `server/tests/workflows/test_coding_security_scan.py` — 127-04 dual-link coding hang-point
- [x] `server/tests/mcp_tools/test_mr_security_scan.py` — 127-04 dual-link MCP/mr_service hang-point
- [x] `server/codegraph/lsp/tests/test_orphan_reap.py` — 孤儿收割
- [x] `server/tests/codegraph/test_lsp_defaults_unchanged.py` — kill-switch 默认 False
- [x] `server/tests/services/code_graph/test_frozen_surface_127.py` — D-18 冻结面（`repo_router_v2` / `mcp/` / GraphService）
- [x] `server/tests/services/code_graph/test_dockerfile_semgrep_lsp_layers.py` — Dockerfile Semgrep/Node/Go 层
- [x] `server/tests/codegraph/test_revisit_impact03.py` — D-17 IMPACT-03 revisit / honest defer
- [x] Fixture：`server/tests/fixtures/semgrep/sample_findings.json`（含 `check_id` / `extra.severity` / fingerprint / nosemgrep 说明）

*Existing infrastructure covers LSP probe unit tests (`node_check` / `go_check`); Wave 0 stubs land all new Semgrep + orphan + defaults + dual-link hang-points. `wave_0_complete` flips true after 127-01 SUMMARY.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 镜像体积 +400–550MB 记入发布说明 | LSP-01 | 需真实 `docker build` / `docker images` | 构建 server 镜像后记录 size delta 到 SUMMARY/发布说明 |
| 基准报告 before/after 质量净收益判定 | LSP-01 / D-16 | 数据驱动门禁，非断言阈值 | 跑 `measure_lsp_baseline` 于 1× Vue/TS + 1× Go；SUMMARY 写「建议翻默认」或保持 False |
| IMPACT-03 生产真实样本（若环境有数据） | D-17 | 依赖重建索引后生产/夹具仓数据 | 样本 >0 则四分支复验；=0 则 SUMMARY 诚实延期记账 |

---

## Threat → Test Cross-Ref

| Threat | STRIDE | Mitigations to verify |
|--------|--------|----------------------|
| T-127-01 Token/snippet leak | Information Disclosure | redact + no token in logs/MR；`test_stub_omits_token_*` + Fernet round-trip |
| T-127-02 CPU exhaustion | Denial of Service | wall-clock + concurrency slot + fail-open 节点 |
| T-127-03 Command injection | Tampering | fixed `SEMGREP_BIN` + argv list；never `import semgrep` |
| T-127-04 Orphan LSP OOM | Denial of Service | finally kill + reap counter |
| T-127-05 False “blocking” expectation | Spoofing | advisory + CE disclaimer copy |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 90s
- [x] `nyquist_compliant: true` set in frontmatter after Wave 0 stubs land（`wave_0_complete` 仍由 SUMMARY 勾选）

**Approval:** pending
