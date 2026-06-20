---
phase: 64-runner
plan: 01
subsystem: infra
tags: [kubernetes, client-go, runner, job, executor, golang]

# Dependency graph
requires:
  - phase: prior-runner-work
    provides: ws.ExecutorService 契约、DockerExecutor 实现、run.go 选择骨架、config viper 绑定
provides:
  - 共享 exec.BuildContainerEnv（docker/k8s 复用的 env 装配唯一真相源）
  - KubernetesExecutor 核心三方法（StartContainer/WaitContainer/StreamLogs，client-go）
  - executor 选择接通（resolveExecutorKind，docker 默认零回归，k8s 别名归一）
  - 可配置 callbackURL host（ws.Config.CallbackHost，docker 默认 host.docker.internal）
  - fake-clientset 单测（StartContainer/Wait/StreamLogs/buildJobSpec）+ 选择单测
affects: [64-02, helm-rbac, runner-deployment]

# Tech tracking
tech-stack:
  added: [k8s.io/client-go@v0.34.5, k8s.io/api@v0.34.5, k8s.io/apimachinery@v0.34.5]
  patterns:
    - "containerID 统一 ns/jobName（确定性、可重 get/list）"
    - "buildJobSpec 纯函数 + toEnvVars/sanitizeName/makeJobName/splitID 助手便于单测"
    - "全部 poll 有界封顶（pollInterval/answerPollMax/logPollMax），单测注入小值保快"
    - "friday.job=<jobName> label 提供与 taskID sanitize 无关的确定性 Pod 选择器"

key-files:
  created:
    - runner/internal/exec/env.go
    - runner/internal/k8s/job.go
    - runner/internal/k8s/executor_test.go
    - runner/internal/cmd/executor_test.go
  modified:
    - runner/go.mod
    - runner/go.sum
    - runner/internal/docker/executor.go
    - runner/internal/k8s/executor.go
    - runner/internal/config/config.go
    - runner/internal/ws/client.go
    - runner/internal/cmd/run.go

key-decisions:
  - "client-go v0.34.5（三者 minor 对齐，与 Go 1.25/1.26 兼容）"
  - "WaitContainer 超时返回 (-1,\"\",nil) 对齐 docker，仅 API error 才返 err（Pitfall 1）"
  - "WaitContainer 超时内联 deleteJob（Background）做 best-effort 清理，因公开 RemoveContainer 仍为 64-02 stub"
  - "新增 friday.job label 作确定性选择器，规避 taskID 截断后 label≠jobName 的不一致"
  - "KubernetesExecutor 不设 callbackHost 字段：回调 host 完全由 ws.Run 经 cfg.CallbackHost 解析，executor 持有会是死代码"

patterns-established:
  - "env 装配单一真相源：docker buildContainerEnv 薄委托 exec.BuildContainerEnv，保零回归"
  - "executor 选择经可测纯函数 resolveExecutorKind 归一 + 错误处理"

requirements-completed: [RUNNER-01, RUNNER-02]

# Metrics
duration: 11min
completed: 2026-06-21
---

# Phase 64 Plan 01: runner k8s Job executor 核心接通 Summary

**KubernetesExecutor 经 client-go 以 batch/v1 Job 跑任务容器（StartContainer/WaitContainer/StreamLogs），executor 选择接通 docker 默认零回归，callbackURL host 可配置**

## Performance

- **Duration:** ~11 min
- **Started:** 2026-06-21T03:03:37+08:00（基线提交后）
- **Completed:** 2026-06-21T03:14:30+08:00
- **Tasks:** 3
- **Files modified:** 11（4 created + 7 modified）

## Accomplishments
- 抽出共享 `exec.BuildContainerEnv`，docker executor 薄委托保逐字零回归（`executor_test.go` 未改且全绿）
- 实现 KubernetesExecutor 三方法：Job 创建（label + 复用 env）、watch Pod 终态取 exitCode、GetLogs(Follow) 逐行流式
- run.go kubernetes 分支真正构造 `k8s.New`（不再报"未实现"），`resolveExecutorKind` 归一 docker/k8s/kubernetes
- callbackURL host 可配置：docker 默认 `host.docker.internal`，k8s 取 `FRIDAY_RUNNER_CALLBACK_HOST`
- fake-clientset 单测全覆盖核心路径，所有 poll 有界封顶（k8s 测试 0.11s）

## Task Commits

Each task was committed atomically:

1. **Task 1: client-go 依赖 + 共享 BuildContainerEnv** - `42a9ed186` (feat)
2. **Task 2: KubernetesExecutor 核心三方法 + job.go + fake 单测** - `e32fc3cd1` (feat)
3. **Task 3: executor 选择接通 + callbackURL host 可配置 + 选择单测** - `1263cfdf0` (feat)

## Files Created/Modified
- `runner/internal/exec/env.go` - 导出 `BuildContainerEnv` + `taskModeForPython`，env 装配唯一真相源
- `runner/internal/k8s/job.go` - `buildJobSpec` 纯函数 + `toEnvVars`/`sanitizeName`/`makeJobName`/`splitID` 助手 + label/常量
- `runner/internal/k8s/executor.go` - `KubernetesExecutor` + `Config` + `New`/`NewWithClientset` + 三方法实现，其余四方法暂 stub
- `runner/internal/k8s/executor_test.go` - fake-clientset 单测（StartContainer/Wait/超时/StreamLogs/buildJobSpec）
- `runner/internal/cmd/executor_test.go` - `resolveExecutorKind` 表驱动单测
- `runner/internal/docker/executor.go` - `buildContainerEnv` 改为薄委托 `exec.BuildContainerEnv`，删除已迁移代码
- `runner/internal/config/config.go` - 新增 `callback.host`/`executor.k8s.*` 绑定与 getter，`GetExecutorType` 归一 k8s→kubernetes
- `runner/internal/ws/client.go` - `Config.CallbackHost` 字段 + callbackURL host 注入逻辑
- `runner/internal/cmd/run.go` - `resolveExecutorKind` + kubernetes 分支构造 `k8s.New` + 传入 `CallbackHost`
- `runner/go.mod` / `runner/go.sum` - 新增 k8s.io/client-go、api、apimachinery v0.34.5（及大量间接依赖）

## Decisions Made
- **client-go v0.34.5**：三者 minor 对齐，batch/v1 + core/v1 GA，client-server 偏移容忍度高；对 k0s 1.30+ 稳妥。
- **WaitContainer 语义对齐 docker**：超时/正常完成都用 exitCode 表达，仅 API error 返 err，避免与 `ws/client.go` 调用方判定分叉。
- **新增 `friday.job=<jobName>` label**：作 WaitContainer/StreamLogs/answerEndpoint 的确定性 Pod 选择器，规避 taskID sanitize/截断后 label 与 jobName 不等的不一致风险。
- **超时清理内联 `deleteJob`**：公开 `RemoveContainer` 按计划仍为 64-02 stub，WaitContainer 超时改用内部 `deleteJob`（Background propagation）做真实 best-effort 清理。

## Deviations from Plan

[轻微，均为按计划意图所需的实现选择，无 scope creep。]

### Auto-fixed / 计划内裁量

**1. [Rule 3 - Blocking] go mod tidy 与 Task 1 require 行的次序处理**
- **Found during:** Task 1
- **Issue:** `go mod tidy` 会修剪尚无代码导入的 k8s.io 依赖，导致 Task 1 单独 commit 时 go.mod 出现 require 行的验收无法满足（Task 2 才真正 import）。
- **Fix:** Task 1 用 `go get` 重新加入三者 require 行（标 `// indirect`）并 commit；Task 2 写入 k8s 代码后 `go mod tidy` 将其转为直接依赖。两次 commit 均 `go build ./...` 绿。
- **Files modified:** runner/go.mod, runner/go.sum
- **Verification:** Task 1/2 后 `grep k8s.io go.mod` 均命中；全程 build/test 绿。
- **Committed in:** `42a9ed186`（require 行）/ `e32fc3cd1`（tidy 转直接依赖）

**2. [计划裁量] KubernetesExecutor 省略 callbackHost 字段 + 新增 friday.job label**
- **Found during:** Task 2
- **Issue:** 计划列出 struct `callbackHost` 字段，但回调 host 实际完全由 ws.Run 经 `cfg.CallbackHost` 解析（Task 3），executor 持有该字段会是无引用死代码；另计划用 `friday.task_id` 选择 Pod，但 taskID 截断后 label≠jobName，选择器不可靠。
- **Fix:** 省略 executor 的 callbackHost 字段（回调 host 仍按 Task 3 经 ws 层可配，约束达成）；新增 `friday.job=<jobName>` Pod 模板 label 作确定性选择器。
- **Files modified:** runner/internal/k8s/executor.go, runner/internal/k8s/job.go
- **Verification:** `go vet ./internal/k8s/...` 无告警；WaitContainer/StreamLogs 单测绿。
- **Committed in:** `e32fc3cd1`

---

**Total deviations:** 2（1 blocking 处理，1 计划裁量）
**Impact on plan:** 均为达成计划意图（零回归、依赖入 go.mod、可配置回调、确定性选择器）所需，无范围蔓延。

## Issues Encountered
- 本机 Go 工具链为 1.26.2（go.mod 声明 1.25.0），client-go v0.34.5 编译/测试均正常，无兼容问题。

## Known Stubs
- `KubernetesExecutor.ReadContainerFile/RemoveContainer/StartupCleanup/ZombieScan` 按计划暂返回 `ErrNotImplemented`，留待 64-02 实现。这是计划显式声明的分期实现，非遗漏；编译期 `var _ ws.ExecutorService = (*KubernetesExecutor)(nil)` 已保接口完整。

## Threat Flags
None — 未引入计划 `<threat_model>` 之外的新信任边界面（env/token 不入日志，仅记 task_id/job/answer_endpoint；taskID sanitize 防非法对象名）。

## User Setup Required
None - 本 plan 仅代码层接通；k8s 真机运行所需的 SA/RBAC、deployment 去 docker.sock、`FRIDAY_RUNNER_CALLBACK_HOST` downward-API 注入由 64-02 helm 落地。

## Next Phase Readiness
- 核心派发/等待/日志三方法就绪，64-02 可接续实现 ReadContainerFile/RemoveContainer/StartupCleanup/ZombieScan 及 helm RBAC + deployment 改造。
- 已知限制（按 RESEARCH）：k8s 模式 HITL answer 端到端投递需 task HTTP answer server 或 RWX 共享卷，属 out-of-scope；answerEndpoint 仅结构性对齐 docker（best-effort Pod IP）。
- 真机 k0s/containerd 端到端为 human_needed（研究环境无集群，逻辑层已由 fake clientset 全覆盖）。

## Self-Check: PASSED

- 创建文件全部存在：exec/env.go, k8s/job.go, k8s/executor.go, k8s/executor_test.go, cmd/executor_test.go, 64-01-SUMMARY.md
- 任务提交全部存在：42a9ed186, e32fc3cd1, 1263cfdf0
- `cd runner && go build ./... && go vet ./... && go test ./...` 全绿
- docker `executor_test.go` 零回归（diff 为空且测试全绿）

---
*Phase: 64-runner*
*Completed: 2026-06-21*
