---
phase: 54
slug: emit
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-17
---

# Phase 54 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Covers AUDITCOV-01（54-01 身份/权限 emit）+ AUDITCOV-02（54-02 凭证治理 emit + purge 收口）。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x (pytest-django, pytest-asyncio, pytest-socket) |
| **Config file** | `server/pyproject.toml` ([tool.pytest.ini_options]) |
| **Quick run command** | `cd server && uv run pytest tests/audit/ -q` |
| **Full suite command** | `cd server && uv run pytest -q` |
| **Estimated runtime** | ~quick <30s, full several min |

---

## Sampling Rate

- **After every task commit:** Run `cd server && uv run pytest tests/audit/ -q`
- **After every plan wave:** Run `cd server && uv run pytest -q`
- **Before `$gsd-verify-work`:** Full suite green + `cd server && uv run python manage.py makemigrations --check`
- **Max feedback latency:** ~30 seconds (quick)

---

## Per-Task Verification Map

> SC → test type → concrete command. 所有行为均后端 pytest 可验证，无需真实容器/外部系统。

| SC | Requirement | Behavior under test | Test Type | Automated Command |
|----|-------------|---------------------|-----------|-------------------|
| SC-1 identity emit | AUDITCOV-01 | 成员/用户增删改、启停、角色、空间配置、仓库权限产生 AuditEvent（actor + target + before/after）；启停仅值变更时 emit；删前快照 | unit (sync + async) | `cd server && uv run pytest tests/audit/test_emit_identity.py -q` |
| SC-2 credential emit | AUDITCOV-02 | Provider/Git/per-repo/飞书凭证、PAT 增吊、飞书同步产生 AuditEvent | unit (async) | `cd server && uv run pytest tests/audit/test_emit_credentials.py -q` |
| SC-2 redaction (核心) | AUDITCOV-02 | 凭证字段在 DB 无明文（api_key/access_token/app_secret/encrypted_config/PAT 明文/token_hash），只含非敏感标识 | unit | `cd server && uv run pytest tests/audit/test_emit_credentials.py -k redacted -q` |
| SC-2 PAT idempotent | AUDITCOV-02 | 重复 revoke 同一 token 仅产 1 条 `pat.revoked` | unit | `cd server && uv run pytest tests/audit/test_emit_credentials.py -k idempotent -q` |
| SC-2 feishu webhook actor | AUDITCOV-02 | webhook 自动同步 actor=None + source=feishu_webhook，仅派发成功 emit；url_verification/duplicate 无 emit | unit (async) | `cd server && uv run pytest tests/audit/test_emit_credentials.py -k feishu -q` |
| SC-3 purge 收口 | AUDITCOV-02 | `log_purge_event` 保留 logger.info + 追加 emit；`run_cleanup` 产 started+completed 2 条 AuditEvent（actor=None/scheduler） | unit (async) | `cd server && uv run pytest tests/audit/test_emit_purge_consolidation.py -q` |
| SC-3 既有日志不破 | AUDITCOV-02 | 既有 purge_reconcile 结构化日志/流程测试仍全绿（收口是补 emit 非重写） | regression | `cd server && uv run pytest tests/ -k purge_reconcile -q` |
| SC-4 no-noise identity | AUDITCOV-01 | 用户/成员列表读、空间详情读、自助改密不产生 AuditEvent | unit | `cd server && uv run pytest tests/audit/test_emit_no_noise_identity.py -q` |
| SC-4 no-noise credentials | AUDITCOV-02 | 凭证/PAT/排除规则 list 读、refresh-models 运维不产生 AuditEvent | unit | `cd server && uv run pytest tests/audit/test_emit_no_noise_credentials.py -q` |
| INV-6 guard (regression) | AUDITCOV-01/02 | 新接线仅经 AuditService，无旁路 `AuditEvent.objects.<write>` | unit (源码扫描) | `cd server && uv run pytest tests/audit/test_audit_inv6_guard.py -q` |
| taxonomy purge promotion | AUDITCOV-02 | `ACTION_PURGE_*` 纳入 ALL_ACTIONS、RESERVED 不再含 purge、命名规范 | unit | `cd server && uv run pytest tests/audit/test_audit_taxonomy.py -q` |
| migrations clean | — | 无新增 migration（本 phase 纯接线，无模型变更） | command | `cd server && uv run python manage.py makemigrations --check --dry-run` |

---

## SC → Test File 映射汇总

| Success Criterion (from phase goal) | 测试文件 | Plan |
|-------------------------------------|----------|------|
| SC-1 成员/用户增删改、启停、角色/权限、空间配置、仓库权限 emit | `test_emit_identity.py` | 54-01 |
| SC-2 Provider/Git/飞书凭证、PAT、飞书同步 emit（凭证脱敏） | `test_emit_credentials.py` | 54-02 |
| SC-3 排除规则变更 + purge 埋点收口统一 AuditEvent | `test_emit_credentials.py`（排除规则）+ `test_emit_purge_consolidation.py`（purge） | 54-02 |
| SC-4 读/普通业务操作不产生审计噪音 | `test_emit_no_noise_identity.py` + `test_emit_no_noise_credentials.py` | 54-01 / 54-02 |

---

## Wave 0 Requirements

- [ ] 既有 `server/tests/audit/__init__.py` + `conftest.py` 已就位（Phase 53 建）——共享 actor user fixture / sample before-after dicts 复用既有
- [ ] async view 调用范式：复用既有 `server/tests/accounts/`、`server/tests/projects/`、`server/tests/system/` 的 adrf async test client / request.user 注入模式
- [ ] 既有 pytest 基础设施（pytest-django + pytest-asyncio + pytest-socket）覆盖框架需求，无需新装框架

*Existing infrastructure (pytest-django / pytest-asyncio) covers all phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| (none) | — | 所有接线行为（emit 行落库 / 脱敏 DB / 幂等 / actor 分支 / purge 收口 / 无噪音 / INV-6）均 unit 可测 | — |

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
