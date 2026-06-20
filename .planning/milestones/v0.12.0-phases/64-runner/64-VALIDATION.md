---
phase: 64
slug: runner
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-20
---

# Phase 64 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Go `testing` + `gotest.tools/v3` + `k8s.io/client-go/kubernetes/fake` |
| **Config file** | `runner/go.mod`, `runner/Makefile` |
| **Quick run command** | `cd runner && go test ./internal/k8s/... ./internal/docker/... ./internal/config/...` |
| **Full suite command** | `cd runner && go test ./...` |
| **Build** | `cd runner && go build ./...` + `go vet ./...` |
| **Helm render** | `helm lint deploy/helm/friday` + `helm template --set runner.executor=kubernetes` |
| **Estimated runtime** | ~30s |

---

## Sampling Rate

- **After every task commit:** `go build ./...` + the touched package's `go test`.
- **After every plan wave:** `go test ./...` + helm render.
- **Max feedback latency:** ~30 seconds.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Status |
|---------|------|------|-------------|-----------|-------------------|--------|
| 64-* executor.type selection (docker default zero-regression) + config | 01 | 1 | RUNNER-01 | unit | `go test ./internal/config/... ./internal/cmd/...` | ⬜ pending |
| 64-* KubernetesExecutor 7 methods via client-go (fake clientset) | 01/02 | 1/2 | RUNNER-02 | unit | `go test ./internal/k8s/...` | ⬜ pending |
| 64-* callbackURL via downward-API podIP (task→runner reachable in k8s) | 02 | 2 | RUNNER-02 | unit | env-injection assertion | ⬜ pending |
| 64-* docker executor zero-regression | 01 | 1 | RUNNER-01 | unit | `go test ./internal/docker/...` | ⬜ pending |
| 64-* helm runner SA/Role/RoleBinding values-gated; k8s mode no docker.sock | 02 | 2 | RUNNER-02 | render | `helm template --set runner.executor=kubernetes` | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Add `k8s.io/client-go` (+ apimachinery) to runner/go.mod (pin compatible version, e.g. v0.34.x).
- [ ] Reuse existing docker executor_test.go patterns; add k8s fake-clientset tests.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real task container runs via k8s Job on k0s/containerd (no docker.sock) | RUNNER-02 | Needs a real k0s/containerd cluster + runner SA/RBAC | Deploy runner with executor=kubernetes + RBAC; dispatch a task; confirm a Job/Pod runs the task container, logs stream back, Pod cleaned up |
| HITL answer end-to-end delivery in k8s | RUNNER-02 (limitation) | Requires task container change / RWX volume — OUT OF SCOPE this phase | Documented limitation: HITL answer channel in k8s deferred; core dispatch/logs/cleanup work without it |

*fake-clientset unit tests cover Job create/wait/logs/cleanup/zombie/config-selection/env-injection; only real-cluster execution is manual.*

---

## Validation Sign-Off

- [x] All tasks have automated verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] nyquist_compliant: true set in frontmatter

**Approval:** approved 2026-06-20 (autonomous)
