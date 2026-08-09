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
> Aligned to plans `127-01` .. `127-05` (no ghost sixth plan).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-django（server） |
| **Config file** | `server/pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest <Per-Task files> -q --reuse-db` |
| **Full suite command** | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest -q --reuse-db`（注意 addopts 排除 `perf/integration/slow/postgres_queue`；本相位禁止 `-m perf`） |
| **Estimated runtime** | ~30–90 seconds（quick）；full suite per CI norms |

---

## Sampling Rate

| Cadence | Scope | Command style |
|---------|-------|---------------|
| **After every task commit（quick）** | 仅本 task 触及的测试文件 | Per-Task Map 的 Automated Command |
| **After every plan wave（full）** | 该 wave 全部相关节点 | 同 Map 行 Command；wave 结束后可并跑本相位已落地文件 |
| **Before `/gsd-verify-work`（full / phase）** | 默认 suite | Full suite green；已知 `mcp` snapshot 漂移仍白名单（D-18） |
| **Max feedback latency** | quick ≤ 90s | — |

---

## Per-Task Verification Map

主表 **恰好 5 行**（`127-01` .. `127-05`）。Wave / Requirement / Command 与各 plan frontmatter 一致。

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 127-W0 | 127-01 | 0 | TAINT-01..03 + LSP-01 | T-127-01..05 | Wave 0 验收桩 + fixture + 冻结面可收集；实现由后续 plan 去 skip | unit / collect | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest tests/services/code_graph/test_semgrep_scan.py tests/services/code_graph/test_security_scan_report.py tests/services/code_graph/test_semgrep_enqueue.py tests/services/code_graph/test_semgrep_app_token.py tests/codegraph/test_security_finding_model.py codegraph/lsp/tests/test_orphan_reap.py tests/codegraph/test_lsp_defaults_unchanged.py tests/services/code_graph/test_frozen_surface_127.py tests/services/code_graph/test_dockerfile_semgrep_lsp_layers.py tests/codegraph/test_revisit_impact03.py tests/workflows/test_coding_security_scan.py tests/mcp_tools/test_mr_security_scan.py --collect-only -q --reuse-db` | ✅ | ✅ green（collect） |
| 127-FOUNDATION | 127-02 | 1 | TAINT-01 + TAINT-03(key) + LSP-01(image/defaults) | T-127-01 | Dockerfile Semgrep/Node/Go/volar/gopls 层；SecurityFinding；Fernet token；VOLAR/GOPLS 默认 False | unit / smoke | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest tests/services/code_graph/test_dockerfile_semgrep_lsp_layers.py tests/codegraph/test_security_finding_model.py tests/services/code_graph/test_semgrep_app_token.py tests/codegraph/test_lsp_defaults_unchanged.py -q --reuse-db` | ✅ W0 | ⬜ pending |
| 127-SCAN | 127-03 | 2 | TAINT-01 | T-127-02/03 | CLI argv `--baseline-commit`；fail-open；QUEUE_SCAN + scan-slot；无 `import semgrep` | unit | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest tests/services/code_graph/test_semgrep_scan.py tests/services/code_graph/test_semgrep_enqueue.py -q --reuse-db` | ✅ W0 | ⬜ pending |
| 127-MR | 127-04 | 3 | TAINT-02 + TAINT-03 | T-127-01/05 | `## 安全扫描` 幂等/advisory/CE/nosemgrep；workflow+MCP 双链路；stub 脱敏 | unit | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest tests/services/code_graph/test_security_scan_report.py tests/workflows/test_coding_security_scan.py tests/mcp_tools/test_mr_security_scan.py -q --reuse-db` | ✅ W0 | ⬜ pending |
| 127-LSP | 127-05 | 4 | LSP-01 | T-127-04 | orphan reap + finally stop；IMPACT-03 复验或诚实延期；defaults 仍 False；`depends_on: [127-02, 127-04]` | unit / cmd | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest codegraph/lsp/tests/test_orphan_reap.py tests/codegraph/test_revisit_impact03.py tests/codegraph/test_lsp_defaults_unchanged.py -q --reuse-db` | ✅ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**依赖备注：** `127-05` frontmatter `depends_on: [127-02, 127-04]`（Wave 4；可与 Wave 3 后并行于实现落地，但验证命令以上表为准）。

---

## Wave 0 Requirements

与 `127-01` Task 1 文件列表一致：

- [x] `server/tests/services/code_graph/test_semgrep_scan.py` — TAINT-01 CLI 契约 / fail-open
- [x] `server/tests/services/code_graph/test_security_scan_report.py` — TAINT-02/03 段文案与幂等
- [x] `server/tests/services/code_graph/test_semgrep_enqueue.py` — QUEUE_SCAN / lock / idempotency
- [x] `server/tests/services/code_graph/test_semgrep_app_token.py` — D-09 Fernet 写读 round-trip
- [x] `server/tests/codegraph/test_security_finding_model.py` — 模型字段 / 无 Symbol FK
- [x] `server/tests/workflows/test_coding_security_scan.py` — 127-04 dual-link coding hang-point
- [x] `server/tests/mcp_tools/test_mr_security_scan.py` — 127-04 dual-link MCP/mr_service hang-point
- [x] `server/codegraph/lsp/tests/test_orphan_reap.py` — 孤儿收割
- [x] `server/tests/codegraph/test_lsp_defaults_unchanged.py` — kill-switch 默认 False
- [x] `server/tests/services/code_graph/test_dockerfile_semgrep_lsp_layers.py` — Dockerfile Semgrep/Node/Go 层
- [x] `server/tests/services/code_graph/test_frozen_surface_127.py` — D-18 冻结面（router/mcp/GraphService）
- [x] `server/tests/codegraph/test_revisit_impact03.py` — D-17 IMPACT-03 复验/诚实延期
- [x] Fixture：`server/tests/fixtures/semgrep/sample_findings.json`（假 semgrep JSON：severity / fingerprint / nosemgrep 说明）

*Existing infrastructure covers LSP probe unit tests (`node_check` / `go_check`); Semgrep + orphan + defaults + dual-link hang-points Wave 0 stubs landed in 127-01.*

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
| T-127-01 Token/snippet leak | Information Disclosure | fixture 假数据；`test_stub_omits_token_*`；Fernet round-trip；redact at write |
| T-127-02 CPU exhaustion | Denial of Service | wall-clock + concurrency slot + fail-open 节点（127-03） |
| T-127-03 Command injection | Tampering | fixed `SEMGREP_BIN` + argv list；never `import semgrep` |
| T-127-04 Orphan LSP OOM | Denial of Service | finally kill + reap counter（127-05） |
| T-127-05 False “blocking” expectation | Spoofing | advisory + CE disclaimer copy（127-04） |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references（stubs collectable）
- [x] No watch-mode flags
- [x] Feedback latency < 90s（quick）
- [x] `nyquist_compliant: true` set in frontmatter after Wave 0 stubs land
- [ ] `wave_0_complete: true` — set after 127-01 SUMMARY

**Approval:** pending
