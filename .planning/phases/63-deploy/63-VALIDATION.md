---
phase: 63
slug: deploy
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-20
---

# Phase 63 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Backend framework** | pytest 9.x (pytest-django) |
| **Helm** | `helm lint deploy/helm/friday` + `helm template deploy/helm/friday` (render check) |
| **Compose** | `docker compose -f docker-compose.yaml config -q` (validity) |
| **Backend quick run** | `cd server && uv run pytest tests/durable tests/delivery -q` |
| **Estimated runtime** | ~1min backend / seconds helm+compose |

---

## Sampling Rate

- **After every task commit:** run touched-area check (pytest for settings/fencing; helm lint/template for chart; compose config for compose).
- **After every plan wave:** backend quick + helm template + compose config.
- **Max feedback latency:** ~60 seconds.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Status |
|---------|------|------|-------------|-----------|-------------------|--------|
| 63-* run_worker --graceful-timeout + helm/compose terminationGracePeriodSeconds | 01 | 1 | DEPLOY-01 | unit + render | `helm template` + arg test | ⬜ pending |
| 63-* compose/helm web/worker/scheduler split (role) + scheduler replicas=1 Recreate + cron wiring | 01/02 | 1 | DEPLOY-02 | render | helm template + compose config | ⬜ pending |
| 63-* KEDA ScaledObject (procrastinate_jobs todo) + PDB + multi-replica Redis fail-closed | 02 | 2 | DEPLOY-03 | unit + render | settings fail-closed test + helm template | ⬜ pending |
| 63-* fencing: create_chat checks feishu_chat_id; MR create checks existing-by-branch | 03 | 2 | IDEMP-02 | unit | duplicate-exec → single external action guard | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Reuse server/tests; add settings fail-closed test + fencing guard tests.
- [ ] helm lint/template + compose config available in environment (skip-gracefully if helm not installed; note as human/CI check).

*Existing infrastructure covers backend requirements; helm/compose render is static validation.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real worker drain on SIGTERM (k8s rolling update) | DEPLOY-01 | Needs live k8s + in-flight jobs | Rolling-update worker deployment, confirm in-flight job finishes / is picked up, no loss |
| KEDA scale-up/down by queue depth | DEPLOY-03 | Needs KEDA-enabled cluster | Enqueue many jobs, observe worker replicas scale on todo depth, scale down after cooldown |
| compose `up -d` upgrade on existing deploy | DEPLOY-02 | Needs a running deploy | Upgrade an existing single-node compose deploy, confirm no break + migrate order |

*helm render / compose config / settings fail-closed / fencing idempotency ARE automated; only live-cluster runtime behaviors are manual.*

---

## Validation Sign-Off

- [x] All tasks have automated verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] nyquist_compliant: true set in frontmatter

**Approval:** approved 2026-06-20 (autonomous)
