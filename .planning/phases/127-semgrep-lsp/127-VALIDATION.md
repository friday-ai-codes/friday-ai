---
phase: 127
slug: semgrep-lsp
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-10
---

# Phase 127 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `127-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-django（server） |
| **Config file** | `server/pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `cd server && uv run pytest tests/services/code_graph/test_security_scan_report.py tests/services/code_graph/test_semgrep_scan.py tests/codegraph/lsp/test_orphan_reap.py -q` |
| **Full suite command** | `cd server && uv run pytest -q`（注意 addopts 排除 `perf/integration/slow/postgres_queue`） |
| **Estimated runtime** | ~30–90 seconds（quick）；full suite per CI norms |

---

## Sampling Rate

- **After every task commit:** Run the relevant new/changed test files from the Per-Task map
- **After every plan wave:** `cd server && uv run pytest tests/services/code_graph/ tests/workflows/test_coding_impact_report.py tests/mcp_tools/test_mr_impact_report.py codegraph/lsp/tests/ -q`
- **Before `/gsd-verify-work`:** Full default suite green；已知 `mcp` snapshot 漂移仍白名单（D-18）
- **Max feedback latency:** 90 seconds（quick）

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 127-W0 | 00 | 0 | TAINT-* / LSP-01 | T-127-01..05 | stubs land before impl | unit | Wave 0 stub files exist | ❌ W0 | ⬜ pending |
| 127-TAINT-CLI | 01+ | 1+ | TAINT-01 | T-127-03 | argv 含 `--baseline-commit`；无 `import semgrep`；固定 `SEMGREP_BIN` | unit | `pytest tests/services/code_graph/test_semgrep_scan.py -q` | ❌ W0 | ⬜ pending |
| 127-TAINT-FAIL | 01+ | 1+ | TAINT-01 | T-127-02 | mirror/CLI/timeout → fail-open；`error_code` 稳定 | unit | 同上 | ❌ W0 | ⬜ pending |
| 127-TAINT-ADV | 02+ | 2+ | TAINT-02 | T-127-05 | severity 进 `## 安全扫描`；advisory 无 raise | unit | `pytest tests/services/code_graph/test_security_scan_report.py -q` | ❌ W0 | ⬜ pending |
| 127-TAINT-NOSE | 02+ | 2+ | TAINT-02 | — | `nosemgrep` 语义 / 文档句 | unit | 同上 | ❌ W0 | ⬜ pending |
| 127-TAINT-DUAL | 02+ | 2+ | TAINT-02 | — | workflow + MCP 双链路 append | unit | 扩展 coding/MR impact report 测 | ❌ W0 | ⬜ pending |
| 127-TAINT-CE | 02+ | 2+ | TAINT-03 | T-127-05 | CE 函数内 taint disclaimer | unit | `test_security_scan_report` | ❌ W0 | ⬜ pending |
| 127-TAINT-TOK | 02+ | 2+ | TAINT-03 | T-127-01 | token 不出现在日志/MR | unit | assert 无明文 token | ❌ W0 | ⬜ pending |
| 127-TAINT-PRO | 02+ | 2+ | TAINT-03 | T-127-01 | 空=CE；有=「Pro 已配置」不夸大 | unit | 同上 | ❌ W0 | ⬜ pending |
| 127-LSP-IMG | 03+ | 1+ | LSP-01 | T-127-02 | Dockerfile 含 node/go/semgrep 层 | smoke | 静态 grep / CI image probe | ❌ W0 | ⬜ pending |
| 127-LSP-PROBE | 03+ | 1+ | LSP-01 | — | 缺二进制 → available=False | unit | `pytest codegraph/lsp/tests/test_node_check.py test_go_check.py -q` | ✅ | ⬜ pending |
| 127-LSP-ORPH | 03+ | 2+ | LSP-01 | T-127-04 | 孤儿收割 / finally stop | unit | `test_orphan_reap.py` | ❌ W0 | ⬜ pending |
| 127-LSP-DEF | 03+ | 1+ | LSP-01 | — | VOLAR/GOPLS 默认 False | unit | `test_lsp_defaults_unchanged.py` | ❌ W0 | ⬜ pending |
| 127-LSP-BASE | 04+ | 3+ | LSP-01 | — | 基准命令 skip-on-missing | unit/cmd | `measure_lsp_baseline --skip-on-missing-binary` | ❌ W0 | ⬜ pending |
| 127-IMPACT03 | 04+ | 3+ | D-17 / IMPACT-03 | — | 样本 0→诚实延期；>0→四分支 | unit | `test_revisit_impact03.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/services/code_graph/test_semgrep_scan.py` — TAINT-01 CLI 契约 / fail-open
- [ ] `server/tests/services/code_graph/test_security_scan_report.py` — TAINT-02/03 段文案与幂等
- [ ] `server/tests/services/code_graph/test_semgrep_enqueue.py` — QUEUE_SCAN / lock / idempotency
- [ ] `server/tests/codegraph/test_security_finding_model.py` — 模型字段 / 无 Symbol FK
- [ ] `server/codegraph/lsp/tests/test_orphan_reap.py` — 孤儿收割
- [ ] `server/tests/codegraph/test_lsp_defaults_unchanged.py` — kill-switch 默认 False
- [ ] Fixture：假 semgrep JSON stdout（含 severity / fingerprint / nosemgrep 形态）
- [ ] （可选）Dockerfile 静态 grep：断言 `semgrep` / `nodejs` / `gopls` 安装层存在

*Existing infrastructure covers LSP probe unit tests (`node_check` / `go_check`); all new Semgrep + orphan + defaults need Wave 0 stubs.*

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
| T-127-01 Token/snippet leak | Information Disclosure | redact + no token in logs/MR |
| T-127-02 CPU exhaustion | Denial of Service | wall-clock + concurrency slot + fail-open |
| T-127-03 Command injection | Tampering | fixed `SEMGREP_BIN` + argv list |
| T-127-04 Orphan LSP OOM | Denial of Service | finally kill + reap counter |
| T-127-05 False “blocking” expectation | Spoofing | advisory + CE disclaimer copy |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter after plans land Wave 0 tasks

**Approval:** pending
