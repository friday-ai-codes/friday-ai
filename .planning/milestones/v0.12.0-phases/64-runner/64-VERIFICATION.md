---
phase: 64-runner
verified: 2026-06-20T19:26:00Z
status: human_needed
score: 12/12 must-haves verified
overrides_applied: 0
human_verification:
  - test: "在真实 k0s/containerd 集群（无 docker.sock）部署 runner，executor=kubernetes，触发一个任务，观察 KubernetesExecutor 经 k8s API 创建 batch/v1 Job/Pod、任务容器在 containerd 上运行至退出。"
    expected: "Job 成功调度，Pod 在 containerd 运行任务镜像并以预期 exitCode 终止；runner 经 SA token + namespaced Role 完成 jobs/pods/pods/log 调用，无任何 docker.sock 依赖。"
    why_human: "需真实 k0s/containerd 集群与镜像拉取/调度，无法在本地用 fake clientset 或 helm 渲染验证（SC3 端到端运行时行为）。"
  - test: "任务运行时观察 StreamLogs 是否经 pods/log(Follow) 实时回传日志到 server；任务结束后确认 WaitContainer 取到真实 exitCode、Pod 经 TTL/RemoveContainer 被清理。"
    expected: "日志逐行实时回传；exitCode 准确；完成后 Job/Pod 按 TTLSecondsAfterFinished 或清理逻辑回收，残留 Job 由 StartupCleanup/ZombieScan 仅按 friday.runner label 回收本副本。"
    why_human: "日志流式/退出码/清理的运行期真实性依赖活动 Pod 生命周期，fake clientset 仅覆盖逻辑分支，需真机确认。"
  - test: "（已知限制，非 gap）确认 k8s 模式下 HITL answer 端到端投递与 ReadContainerFile 产物读取的当前行为符合文档化预期（退化不阻断主流程）。"
    expected: "ReadContainerFile 返回空+warning，任务仍按 exitCode 判 completed；HITL answer 在 k8s 为已知限制（需 task HTTP server 或 RWX 共享卷），核心 dispatch/wait/logs/cleanup 不依赖它。"
    why_human: "属计划 T-64-03/T-64-07 显式 accept 的已知限制，需人工确认实际运行表现与文档一致，不计为本阶段 gap。"
---

# Phase 64: runner k8s Job executor Verification Report

**Phase Goal:** 抽象 runner executor（docker/k8s）+ 经 k8s API 实现 k8s Job executor（Job/Pod、SA/RBAC、日志流式、Pod 清理、重试），去 docker.sock，可在 k0s/containerd 运行。
**Verified:** 2026-06-20T19:26:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | 默认/未配置时 runner 仍构造 DockerExecutor，docker 行为零回归（executor_test.go 不改且全绿） | ✓ VERIFIED | `git diff --stat 42a9ed186^ -- runner/internal/docker/executor_test.go` 为空；`docker/executor.go:120-122` `buildContainerEnv` 薄委托 `exec.BuildContainerEnv`；`go test ./...` 全绿（ok internal/docker） |
| 2 | executor.type=kubernetes（或别名 k8s）时 run.go 构造 KubernetesExecutor 而非报错 | ✓ VERIFIED | `cmd/run.go:48-73` 经 `resolveExecutorKind` 走 `k8s.New(...)`；`cmd/executor_test.go` 表驱动覆盖 docker/""/kubernetes/k8s/未知；无 "未实现" 字串 |
| 3 | StartContainer 经 k8s API 建 batch/v1 Job，携带 app/friday.task_id/friday.runner label 与 FRIDAY_TASK_* env（复用 BuildContainerEnv，无前缀漂移） | ✓ VERIFIED | `executor.go:134-150` Create Job + `job.go:34-39` labels；env 经 `exec.BuildContainerEnv`→`toEnvVars`；`TestStartContainerCreatesJob` 断言 friday.task_id/friday.runner + FRIDAY_TASK_REMOTE_TOOLS/FRIDAY_TASK_CALLBACK_URL |
| 4 | WaitContainer 取 Pod terminated exitCode；超时返回 exitCode=-1 且 err=nil（对齐 docker） | ✓ VERIFIED | `executor.go:176-206` watch terminated.ExitCode；超时 `return -1,"",nil` + best-effort deleteJob；`TestWaitContainerReturnsExitCode`(7) + `TestWaitContainerTimeoutReturnsMinusOne` |
| 5 | StreamLogs 经 Pods.GetLogs(Follow) 逐行回调 onLine | ✓ VERIFIED | `executor.go:209-231` GetLogs(Follow) + bufio.Scanner 逐行 onLine；`TestStreamLogs` 断言至少一行回调 |
| 6 | task→runner callbackURL host 可配置：docker 默认 host.docker.internal，k8s 取 FRIDAY_RUNNER_CALLBACK_HOST | ✓ VERIFIED | `ws/client.go:97,146-150` CallbackHost 字段 + 空回退 host.docker.internal；`config.go:124` GetCallbackHost；helm k8s 经 downward API `status.podIP` 注入 FRIDAY_RUNNER_CALLBACK_HOST |
| 7 | RemoveContainer 删 Job（PropagationBackground 连带 Pod），NotFound 吞错 | ✓ VERIFIED | `executor.go:256-279` deleteJob(Background) + IsNotFound 吞错；`TestRemoveContainerDeletesJobAndSwallowsNotFound` |
| 8 | StartupCleanup 仅按 friday.runner=<本 runner> label 删本 runner 残留 Job，不误杀他副本 | ✓ VERIFIED | `executor.go:267-299` runnerSelector(`app=friday-task,friday.runner=<name>`)；`TestStartupCleanupOnlyRemovesOwnRunnerJobs`（count=2，保留 r2 的 job） |
| 9 | ZombieScan 按 label list：活跃不在 known 且超阈值删除并推 TypeTaskFailed；完成 Job 超保留期删除 | ✓ VERIFIED | `executor.go:307-359`；`TestZombieScanKillsActiveUnknownAndKeepsKnown`（杀活僵尸+推 TaskFailed exit_code=-1，保留 known）+ `TestZombieScanRemovesTerminalRetainedJob`（终态超保留删除、不推消息） |
| 10 | ReadContainerFile 在 k8s 下 best-effort 退化（返回空+err），任务仍按 exitCode 判 completed，不阻断 | ✓ VERIFIED | `executor.go:366-368` 返回 ("", err)；`TestReadContainerFileDegradesGracefully`；ws/client.go ReadContainerFile 失败已 log.Warn 容错 |
| 11 | helm executor=kubernetes 渲染 runner SA + namespaced Role（jobs create/get/list/watch/delete；pods get/list/watch；pods/log get）+ RoleBinding，Deployment 用该 SA 且不挂 docker.sock | ✓ VERIFIED | `helm template --set runner.executor=kubernetes`：出 ServiceAccount/Role/RoleBinding，Role rules 精确匹配；serviceAccountName=release-name-friday-runner；docker.sock 计数=0；FRIDAY_RUNNER_CALLBACK_HOST←status.podIP |
| 12 | helm executor=docker（默认）不渲染 SA/RBAC 且仍挂 docker.sock（零回归） | ✓ VERIFIED | `helm template --set runner.executor=docker`：docker.sock 计数=4，kind:Role 计数=0；默认（不传 set）同 |

**Score:** 12/12 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `runner/internal/exec/env.go` | 导出 BuildContainerEnv 共享 env 装配 | ✓ VERIFIED | `func BuildContainerEnv`（行17）+ taskModeForPython；docker/k8s 复用 |
| `runner/internal/k8s/executor.go` | KubernetesExecutor + New + 七方法（client-go） | ✓ VERIFIED | struct + New/NewWithClientset + 七方法全实现，`grep -c ErrNotImplemented`==0 |
| `runner/internal/k8s/job.go` | buildJobSpec 纯函数 + toEnvVars/sanitize/splitID/makeJobName | ✓ VERIFIED | `func buildJobSpec`（行29）+ 全部助手 + label 常量 |
| `runner/internal/k8s/executor_test.go` | fake clientset 单测（核心三方法 + 生命周期四方法 + buildJobSpec） | ✓ VERIFIED | `fake.NewSimpleClientset`；11 个测试覆盖 Start/Wait/超时/Stream/spec/Remove/Cleanup/Zombie×2/Read |
| `runner/internal/cmd/executor_test.go` | resolveExecutorKind 选择/归一单测 | ✓ VERIFIED | `TestResolveExecutorKind` 表驱动 docker/""/kubernetes/k8s/未知 |
| `deploy/helm/friday/templates/runner-rbac.yaml` | values-gated SA + namespaced Role + RoleBinding | ✓ VERIFIED | `kind: Role` 渲染，仅 k8s 模式（docker 模式计数=0） |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `cmd/run.go` | `k8s.New` | kubernetes 分支构造 | ✓ WIRED | `run.go:61` `k8s.New(k8s.Config{...})` |
| `k8s/executor.go` | `exec.BuildContainerEnv` | StartContainer env 复用 | ✓ WIRED | `executor.go:136` |
| `ws/client.go` | `cfg.CallbackHost` | callbackURL host 注入 | ✓ WIRED | `client.go:146-150` |
| `runner-deployment.yaml` | runner-rbac SA | serviceAccountName（k8s） | ✓ WIRED | 渲染 `serviceAccountName: release-name-friday-runner` |
| `k8s/executor.go` | Jobs.Delete(PropagationBackground) | RemoveContainer | ✓ WIRED | `executor.go:257` DeletePropagationBackground |
| `runner-deployment.yaml` | status.podIP | downward API 回调 host | ✓ WIRED | 渲染 `fieldPath: status.podIP` → FRIDAY_RUNNER_CALLBACK_HOST |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| runner 编译/静态检查/单测全绿 | `cd runner && go build ./... && go vet ./... && go test ./...` | exit 0；internal/cmd, internal/docker, internal/k8s ok | ✓ PASS |
| helm chart 合法 | `helm lint deploy/helm/friday` | 0 chart(s) failed | ✓ PASS |
| k8s 渲染 RBAC + 无 docker.sock + podIP | `helm template --set runner.executor=kubernetes --set runner.rbac.create=true` | SA/Role/RoleBinding + serviceAccountName + status.podIP，docker.sock=0 | ✓ PASS |
| k8s Role 最小权限 verbs | `helm template ... | sed -n '/kind: Role/,/RoleBinding/p'` | jobs(create/get/list/watch/delete)、pods(get/list/watch)、pods/log(get) | ✓ PASS |
| docker 默认零回归 | `helm template --set runner.executor=docker` | docker.sock=4，kind:Role=0 | ✓ PASS |
| k8s 别名一致性 | `helm template --set runner.executor=k8s --set runner.rbac.create=true` | 与 kubernetes 渲染结构一致（SA/Role/RoleBinding/podIP），docker.sock=0 | ✓ PASS |
| 任务容器在 containerd 运行至退出（SC3） | 需真实 k0s/containerd 集群 | 无法本地运行 | ? SKIP → human_needed |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| RUNNER-01 | 64-01 | runner 抽象 executor 接口（docker/k8s），与 WS 派发 + HTTP 回调契约解耦，docker 零回归 | ✓ SATISFIED | `ws.ExecutorService` 接口（client.go:59，7 方法）；docker 与 k8s 均 `var _ ws.ExecutorService`；run.go 经 resolveExecutorKind 选择；docker executor_test.go diff 为空且全绿 |
| RUNNER-02 | 64-01, 64-02 | k8s Job executor 经 k8s API 起 Job/Pod（去 docker.sock），含 SA/RBAC、日志流式、Pod 清理、失败重试；k0s/containerd 可用 | ✓ SATISFIED (实现+RBAC+渲染层)；运行时 k0s/containerd 端到端 → human_needed | KubernetesExecutor 七方法（client-go batch/v1+core/v1）；BackoffLimit 重试可配；helm SA/Role/RoleBinding + 去 docker.sock + podIP；fake clientset 单测全覆盖。真机运行（SC3）需人工验证 |

无孤儿需求：REQUIREMENTS.md 映射到 Phase 64 的 ID（RUNNER-01/02）均被 plan 的 `requirements` 字段声明并实现。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `k8s/executor.go` | 366-368 | ReadContainerFile 返回 ("", err) | ℹ️ Info | 计划显式声明的 k8s best-effort 退化（Open Q4 / T-64-03），非 stub；ws/client.go log.Warn 容错使任务仍按 exitCode completed。已被单测覆盖语义。 |

无 TBD/FIXME/XXX/HACK 债务标记（`grep` 全部修改文件返回 NO_DEBT_MARKERS）。无未接线/空数据渲染型 stub。

### Human Verification Required

1. **真机 k0s/containerd 端到端运行（SC3）** — 在真实 k0s/containerd 集群部署 runner（executor=kubernetes，无 docker.sock），触发任务，确认经 k8s API 建 Job/Pod、容器在 containerd 运行至退出码。
   - Expected: Job 调度成功，Pod 跑任务镜像并以预期 exitCode 终止，runner 经 SA token+Role 完成全部 API 调用，无 docker.sock 依赖。
2. **日志流式/退出码/Pod 清理运行期真实性** — 任务运行时确认 StreamLogs 实时回传、WaitContainer 取真实 exitCode、完成后 Job/Pod 按 TTL/清理逻辑回收（StartupCleanup/ZombieScan 仅清本 runner）。
   - Expected: 日志逐行回传，exitCode 准确，清理按 friday.runner label 隔离。
3. **已知限制确认（非 gap）** — k8s 模式 HITL answer 端到端投递与 ReadContainerFile 产物读取为计划 accept 的已知限制（T-64-03/T-64-07）。
   - Expected: ReadContainerFile 退化不阻断主流程；HITL answer 限制与文档一致，核心 dispatch/wait/logs/cleanup 不依赖它。

### Gaps Summary

无阻断性 gap。全部 12 条 must-have 真相、6 个产物、6 条关键接线均在代码与 helm 渲染层验证通过；`go build/vet/test` 全绿、`helm lint` 0 失败、docker 零回归（executor_test.go diff 为空 + docker.sock 渲染保留 + 无 RBAC）、k8s 渲染出最小权限 RBAC + 去 docker.sock + podIP 回调、k8s/kubernetes 别名渲染一致。RUNNER-01、RUNNER-02 均满足实现契约。

状态判为 **human_needed** 的唯一原因：成功标准 SC3「在 k0s/containerd 真实集群经 k8s Job executor 运行」属运行期端到端行为，无法在本地以 fake clientset / helm 渲染验证。按验证指引，当实现 + RBAC + 渲染齐备且单测全绿时，真机运行归为 human_needed 而非 gap。HITL-answer-in-k8s 为文档化已知限制，不计为 gap。

---

_Verified: 2026-06-20T19:26:00Z_
_Verifier: Claude (gsd-verifier)_
