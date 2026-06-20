---
phase: 64-runner
reviewed: 2026-06-20T19:29:43Z
depth: deep
files_reviewed: 14
files_reviewed_list:
  - runner/go.mod
  - runner/go.sum
  - runner/internal/exec/env.go
  - runner/internal/docker/executor.go
  - runner/internal/cmd/run.go
  - runner/internal/cmd/executor_test.go
  - runner/internal/config/config.go
  - runner/internal/ws/client.go
  - runner/internal/k8s/executor.go
  - runner/internal/k8s/job.go
  - runner/internal/k8s/executor_test.go
  - deploy/helm/friday/templates/runner-rbac.yaml
  - deploy/helm/friday/templates/runner-deployment.yaml
  - deploy/helm/friday/templates/_helpers.tpl
  - deploy/helm/friday/values.yaml
findings:
  critical: 1
  warning: 3
  info: 2
  total: 6
status: clean
fixes_applied: 2026-06-21T03:32:00Z
---

# Phase 64: Code Review Report

**Reviewed:** 2026-06-20T19:29:43Z
**Depth:** deep
**Files Reviewed:** 14
**Status:** clean（CR-01/WR-01/WR-02/IN-02 已修复；WR-03/IN-01 为已知接受限制，见文末 Fixes Applied）

## Summary

Phase 64 adds a `KubernetesExecutor` (client-go, batch/v1 Job) behind a values/config-gated executor selector, while keeping the docker path as a zero-regression default. The phase's stated focus checks largely hold up under adversarial review:

- **Docker zero-regression: CONFIRMED.** `git diff 42a9ed186^..HEAD` for `runner/internal/docker/executor_test.go` is empty; `buildContainerEnv` is now a thin delegate to `exec.BuildContainerEnv` with name/signature preserved; `var _ ws.ExecutorService` compile-time checks intact; `go test ./internal/docker/...` green.
- **Executor selection: CONFIRMED.** `resolveExecutorKind` (docker default / kubernetes canonical / k8s alias / unknown→error) is correct and unit-tested; helm `friday.runner.isK8s` mirrors it, so there is no docker-render + k8s-runtime mismatch.
- **All 7 methods implemented, polls bounded:** no `ErrNotImplemented` remains; every poll/watch is wrapped by an upper bound or `context` timeout — no hang observed under the fake clientset.
- **Multi-runner isolation: CONFIRMED.** `StartupCleanup`/`ZombieScan` are scoped by `app=friday-task,friday.runner=<sanitize(name)>`; tests prove other runners' Jobs are not deleted.
- **Helm least-privilege RBAC: CONFIRMED.** namespaced `Role` (not ClusterRole) with `jobs` create/get/list/watch/delete, `pods` get/list/watch, `pods/log` get; k8s mode drops `docker.sock`, uses the SA, and injects `status.podIP`→`FRIDAY_RUNNER_CALLBACK_HOST`; docker default still mounts `docker.sock` and renders no RBAC (`helm template` verified: docker render has 4 `docker.sock` hits / 0 `kind: Role`; k8s render has SA+Role+RoleBinding / 0 `docker.sock`). `helm lint` passes.
- **client-go config:** in-cluster first, kubeconfig fallback; no tokens logged; `StartContainer` logs only `task_id`/`job`/`answer_endpoint`.
- **HITL k8s limitation: documented**, not silently dropped (`ReadContainerFile` returns an explicit error; `answerEndpoint` is best-effort).

Build/vet/test all green (`go build ./...`, `go vet`, `go test ./internal/{k8s,cmd,config,docker}/...`).

The one **BLOCKER** is the `WaitContainer` watch loop: it treats a closed watch channel (server-side watch timeout or any transient watch break) as task completion with `exitCode=-1`, which on the core long-running coding-task path produces a false "timeout" failure **and** leaks the still-running Job (cleanup is skipped because `taskFailed` stays true). The remaining findings are robustness/quality concerns.

## Critical Issues

### CR-01: `WaitContainer` reports a false failure and leaks the Job when the watch channel closes mid-task

**File:** `runner/internal/k8s/executor.go:188-205`
**Issue:**
The wait loop returns `(-1, "", nil)` whenever the watch result channel closes (`!ok`), treating channel closure as terminal:

```193:196:runner/internal/k8s/executor.go
		case ev, ok := <-w.ResultChan():
			if !ok {
				return -1, "", nil
			}
```

A Kubernetes watch is **not** a long-lived guarantee: the API server closes watches after a randomized `minRequestTimeout` window (default ~30–60 min), and the channel can also close on any transient apiserver/network blip. When that happens before the task's container reaches `Terminated`, this code returns `exitCode=-1` while the Job/Pod is still running. In `runTask` (`ws/client.go:438-475`) `exitCode=-1` is mapped to `errMsg="timeout"` → `TaskFailed`, so:

1. A still-running (or successful) long task is reported **failed** to the server — incorrect behavior on the project's primary use case (long AI coding tasks; default timeout is 1800s and custom timeouts can exceed the watch window).
2. Unlike the genuine timeout branch (`wctx.Done()` → `deleteJob`), the channel-close branch does **not** delete the Job, and `runTask` retains it (`taskFailed=true`). The task container keeps running orphaned; `TTLSecondsAfterFinished` never fires because the Job never finishes. Resource/credential leak.

The unit tests do not cover this path — `TestWaitContainerReturnsExitCode` injects the terminated Pod ~30ms after the watch starts, and no test closes the watch channel before termination, so the defect is invisible to the suite.

**Fix:** Re-establish the watch instead of returning on benign closure, and supplement with a poll/initial-list so an already-terminated Pod is always observed. Minimal change:

```go
sel := labelKeyJob + "=" + jobName
for {
	w, err := k.cs.CoreV1().Pods(ns).Watch(wctx, metav1.ListOptions{LabelSelector: sel})
	if err != nil {
		return -1, "", err
	}
	code, done := k.drainWatch(wctx, w) // returns (exitCode,true) on Terminated
	w.Stop()
	if done {
		return code, "", nil
	}
	select {
	case <-wctx.Done():
		_ = k.deleteJob(context.Background(), ns, jobName)
		return -1, "", nil
	default:
		// channel closed but not timed out → re-watch (optionally List first
		// to catch a Terminated state that occurred during the gap)
	}
}
```

Prefer `cache.NewListWatchFromClient` + `watchtools.UntilWithSync` / `RetryWatcher`, or a short `Pods(ns).List` poll on each re-watch, so a Pod that terminated during the watch gap is still detected. Only a real API error should surface as `err`.

## Warnings

### WR-01: `StartContainer` blocks up to ~5s per task on an answer endpoint that is almost never available (and unused in k8s)

**File:** `runner/internal/k8s/executor.go:143,153-171`
**Issue:**
`StartContainer` synchronously calls `pollAnswerEndpoint`, which polls `answerPollMax` (10) × `pollInterval` (500ms) ≈ 5s for a Pod IP before returning the `containerID`:

```142:149:runner/internal/k8s/executor.go
	containerID := k.namespace + "/" + jobName
	answerEndpoint := k.pollAnswerEndpoint(ctx, jobName)
```

A freshly created Job's Pod is essentially never scheduled, pulled, and assigned an IP within 5s, so this loop almost always exhausts its full budget and returns `""`. Worse, HITL/answer delivery is a **documented k8s limitation** for this phase, so the value produced is unused (`runTask` only pushes `answer_endpoint` when non-empty). The net effect is a fixed multi-second tax on every k8s task dispatch for a near-useless result, serialized on the scheduler's per-task hot path.

**Fix:** Either drop the synchronous poll for k8s (return an empty `answerEndpoint` immediately, consistent with the documented limitation), or move IP resolution off the dispatch path (resolve lazily/asynchronously only if/when HITL is actually wired up). At minimum, reduce `answerPollMax` so the worst case is sub-second.

### WR-02: `makeJobName` can collide for distinct task IDs that sanitize to the same ≤63-char name

**File:** `runner/internal/k8s/job.go:104-118`
**Issue:**
The disambiguating short hash is only appended when the assembled name exceeds 63 chars:

```104:109:runner/internal/k8s/job.go
func makeJobName(taskID string) string {
	sanitized := sanitizeName(taskID)
	name := jobNamePrefix + sanitized
	if len(name) <= 63 {
		return name
	}
```

`sanitizeName` maps every non-`[a-z0-9]` rune to `-` and lowercases, so distinct task IDs collapse to the same name (e.g. `Task_1`, `task.1`, `task-1` → `task-1`; `AB/CD` vs `ab-cd`). Two concurrent/sequential tasks with colliding sanitized IDs produce the same `jobName`; the second `Jobs.Create` fails with `AlreadyExists`, and `StartContainer` returns an error → that task fails. With opaque UUID task IDs the risk is low, but the contract accepts arbitrary `task_id` strings, so it is a real correctness edge.

**Fix:** Always incorporate a deterministic short hash of the **raw** `taskID` into the name (not only on overflow), e.g. `friday-task-<truncated-sanitized>-<sha8(taskID)>`. This keeps determinism (re-derivable for get/list) while guaranteeing uniqueness across sanitize-collisions.

### WR-03: k8s `ReadContainerFile` degradation makes `text_output`/`output` permanently empty for every k8s task

**File:** `runner/internal/k8s/executor.go:366-368`, consumed at `runner/internal/ws/client.go:451-465`
**Issue:**
`ReadContainerFile` always returns an error in k8s mode, so the success path in `runTask` always hits the `log.Warn` fallback and emits `TaskCompleted` with `text_output=""` and `output=nil`:

```451:465:runner/internal/ws/client.go
	if exitCode == 0 {
		taskFailed = false
		...
		if rawSession, readErr := cfg.Executor.ReadContainerFile(...); readErr != nil {
			log.Warn().Str("task_id", task.TaskID).Err(readErr).Msg("read_session_file_failed")
		}
		...
		queue.Push(NewMessage(TypeTaskCompleted, map[string]any{
			... "text_output": textOutput, "output": sessionData,
		}))
```

This is intentional and documented (Open Q4), and it does not block the main flow (task still completes by `exitCode`). But it is a real functional gap versus the docker executor: any server-side feature relying on `text_output`/`output` (session summary, last output) silently receives empty data for all k8s-mode tasks. Flagging so it is consciously accepted rather than a surprise in production.

**Fix:** Out of scope to fully solve here, but track the follow-up (callback-based session upload from the task, or an RWX shared volume) and ensure the server side degrades gracefully when `output` is null for k8s runs.

## Info

### IN-01: Task secrets are stored as plaintext env in the Job/Pod spec

**File:** `runner/internal/exec/env.go:17-65` (consumed by `runner/internal/k8s/job.go:42-51`)
**Issue:** `BuildContainerEnv` emits `FRIDAY_CALLBACK_TOKEN`, `FRIDAY_TASK_CALLBACK_TOKEN`, and any `env_`-prefixed metadata (e.g. injected `FRIDAY_TASK_CLAUDE_API_KEY`) as literal env values, which `toEnvVars` places directly in `corev1.EnvVar.Value`. These are readable by anyone with `get` on `jobs`/`pods` in the namespace (`kubectl get job -o yaml`). This matches docker behavior and is mitigated by the namespaced least-privilege RBAC, but k8s offers a stronger primitive.
**Fix:** Consider materializing sensitive values into a per-task `Secret` (owner-referenced to the Job for GC) and referencing them via `valueFrom.secretKeyRef`. Lower priority given parity with the existing docker path.

### IN-02: Task Job has no resource requests/limits or `activeDeadlineSeconds`

**File:** `runner/internal/k8s/job.go:42-69`
**Issue:** The generated Pod spec sets no `resources` and the Job has no `activeDeadlineSeconds`. Cleanup of an orphaned running Job relies on the runner staying alive (`WaitContainer` timeout → delete) plus `StartupCleanup`/`ZombieScan` on restart; `TTLSecondsAfterFinished` only applies after completion. If the runner is permanently lost, a hung task Job can run unbounded until a runner with the same `friday.runner` label restarts and scans.
**Fix:** Optionally set `activeDeadlineSeconds` from the task timeout as a server-side backstop, and expose pod `resources` via values for scheduling/quotas. Non-blocking.

---

## Fixes Applied (2026-06-21)

代码评审发现已按优先级修复，每项独立原子提交（Conventional Commits）：

- **CR-01（BLOCKER）— 已修复。** `WaitContainer` 不再把 watch channel 关闭当作任务终止。
  改为「List 捕获已终态 + Watch + channel 关闭重建」的有界循环（`drainWatch`/`terminatedExitCode`
  辅助）：仅 Pod 真正 `Terminated`（返真实 exitCode）、调用方超时（返 `(-1,"",nil)` 并删 Job，
  对齐 docker）、或 ctx 取消才退出；channel 关闭只触发 re-watch，所有等待受 `wctx` 有界。
  长任务不再被误判 timeout/failed，仍在运行的 Job 不再泄漏。新增关闭/重建 watch 单测
  `TestWaitContainerReWatchesOnClosedChannel`，超时仍返回 `(-1,"",nil)`。
- **WR-02（WARNING）— 已修复。** `makeJobName` 始终以源 `taskID` 的 sha8 作后缀（不再仅超长时补哈希），
  不同 taskID 即便 sanitize 后塌缩同名也永不撞名（消除 `Jobs.Create AlreadyExists`），
  仍确定性可重 get/list、≤63 且 DNS-1123 合法。`containerID=ns/jobName` 与 `friday.job` 选择器
  逻辑不变。新增冲突区分单测 `TestMakeJobNameDisambiguatesSanitizeCollisions`。
- **WR-01（WARNING）— 已修复。** k8s `StartContainer` 不再同步 poll Pod IP（旧逻辑≈5s/任务且几乎必然
  返回空），直接返回空 `answerEndpoint`，消除调度热路径上的固定时延税；移除随之失效的
  `pollAnswerEndpoint`/`answerPollMax`/`defaultAnswerPollN`。HITL 真正接入时再以惰性/异步解析 IP。
  docker 路径零改动。
- **IN-02（INFO）— 已应用。** 任务 Job 增加 values-gated 的 `activeDeadlineSeconds` 兜底（>0 时由 k8s
  主动终止超期 Job，兜住 runner 永久丢失场景）与 Pod 资源 `requests/limits`，经
  `FRIDAY_RUNNER_K8S_ACTIVE_DEADLINE` / `CPU|MEMORY_REQUEST|LIMIT` 贯通 helm→config→executor，
  默认 0/空（不改变既有行为）。`helm lint` 0 failed，k8s 渲染仍含 RBAC+podIP，docker 渲染不受影响。

### 接受的已知限制（不在本轮修复范围）

- **WR-03 — 已接受。** k8s `ReadContainerFile` 对已退出 Pod 恒失败属设计内退化（Open Q4，本阶段不动 task），
  `text_output`/`output` 对 k8s 任务恒空，但任务仍按 exitCode 判完成、不阻断主流程。后续以 callback 回传
  或 RWX 共享卷补齐；服务端在 `output=null` 时已优雅降级。维持文档化限制，不改 task 容器。
- **IN-01 — 已接受。** 任务 secret 以明文 env 注入 Job/Pod，与 docker env 注入行为一致，已由 namespaced
  最小权限 RBAC 缓解。v2 可考虑 per-task `Secret` + `valueFrom.secretKeyRef`（owner-ref 到 Job 做 GC）。不阻断。

验证：`go build ./... && go vet ./... && go test ./...` 全绿（无 hang）；`gofmt -l` 干净；
`helm lint deploy/helm/friday` 0 failed；`helm template --set runner.executor=kubernetes` 仍渲染 RBAC+podIP
（启用 values 时叠加 activeDeadline/resources 环境变量）。docker 零回归（`docker/executor_test.go` 未改动）。

---

_Reviewed: 2026-06-20T19:29:43Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Fixes applied: 2026-06-21 (gsd-code-fixer)_
_Depth: deep_
