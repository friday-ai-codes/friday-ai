---
phase: 64-runner
plan: 02
subsystem: infra
tags: [kubernetes, client-go, runner, job, rbac, helm, golang]

# Dependency graph
requires:
  - phase: 64-01
    provides: KubernetesExecutor struct/New、splitID/sanitizeName 助手、friday.* labels、deleteJob(Background)、exec.BuildContainerEnv、config k8s env 绑定
provides:
  - KubernetesExecutor 生命周期四方法（RemoveContainer/StartupCleanup/ZombieScan/ReadContainerFile），七方法接口完整
  - StartupCleanup/ZombieScan 按 friday.runner label 隔离多副本（不误杀他 runner 在途 Job）
  - ZombieScan 杀活跃超龄僵尸 Job 并推 TaskFailed、清终态超保留期 Job
  - ReadContainerFile k8s best-effort 退化（返回 err+空串，主流程不阻断）
  - helm values-gated runner SA + namespaced 最小权限 Role/RoleBinding（runner-rbac.yaml）
  - runner-deployment k8s 分支：serviceAccountName + 去 docker.sock + downward-API podIP 回调 host
  - helm kubernetes/k8s 别名归一（与 Go resolveExecutorKind 一致）
affects: [helm-deploy, runner-k8s-runtime]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "清理/扫描以 friday.runner label selector 隔离多副本（T-64-05）"
    - "RemoveContainer 复用 64-01 deleteJob(Background)，单一删除真相源"
    - "ZombieScan 终态判定 Succeeded>0||Failed>0，CompletionTime 缺省回退 CreationTimestamp"
    - "helm executor 模式经 friday.runner.isK8s helper 归一 kubernetes/k8s，避免别名渲染漂移"

key-files:
  created:
    - deploy/helm/friday/templates/runner-rbac.yaml
  modified:
    - runner/internal/k8s/executor.go
    - runner/internal/k8s/executor_test.go
    - deploy/helm/friday/templates/runner-deployment.yaml
    - deploy/helm/friday/templates/_helpers.tpl
    - deploy/helm/friday/values.yaml

key-decisions:
  - "ReadContainerFile k8s 退化返回 err+空串而非 exec 已退出 Pod（Never restartPolicy 完成即终止，exec 恒失败）"
  - "ZombieScan/StartupCleanup 复用 runnerSelector（app=friday-task,friday.runner=<name>），不触他 runner Job"
  - "helm 用 friday.runner.isK8s helper 归一 kubernetes/k8s，正源处理别名（plan-check Warning 2）"
  - "downward-API metadata.namespace 注入 FRIDAY_RUNNER_K8S_NAMESPACE，运行期取真实 namespace"

patterns-established:
  - "label-scoped 清理：所有 list/delete 均带 friday.runner 限定，多副本天然隔离"
  - "helm 双分支零回归：docker 默认形态逐字保留，k8s 形态去逃逸面（docker.sock）"

requirements-completed: [RUNNER-02]

# Metrics
duration: 9min
completed: 2026-06-21
---

# Phase 64 Plan 02: KubernetesExecutor 生命周期收官 + helm RBAC/部署形态 Summary

**KubernetesExecutor 补齐 Remove/StartupCleanup/ZombieScan/ReadContainerFile（friday.runner label 隔离多副本、僵尸 Job 回收推 TaskFailed、产物读取 best-effort 退化），并落地 values-gated runner SA + 最小权限 Role/RoleBinding、k8s 模式去 docker.sock 并经 downward-API podIP 注入回调 host**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-06-21T03:17:00+08:00
- **Completed:** 2026-06-21T03:26:00+08:00
- **Tasks:** 2
- **Files modified:** 6（1 created + 5 modified）

## Accomplishments
- KubernetesExecutor 七方法全部实现：RemoveContainer（Job Background 删除、NotFound 吞错）、StartupCleanup（仅清本 runner 残留、返回计数）、ZombieScan（活跃超龄僵尸删除并推 TypeTaskFailed、终态超保留期删除）、ReadContainerFile（k8s 退化返回 err+空串不阻断主流程）
- 清理/扫描全程以 `friday.runner=<name>` label selector 隔离，多副本同 namespace 不误杀彼此在途 Job（Pitfall 3 / T-64-05）
- 移除 64-01 遗留的 `ErrNotImplemented`，补 fake-clientset 生命周期单测（runner 隔离 / NotFound 吞错 / 僵尸杀+推 / known 不动 / 终态清理 / 退化语义）
- 新增 values-gated `runner-rbac.yaml`：ServiceAccount + namespaced 最小权限 Role（jobs create/get/list/watch/delete；pods get/list/watch；pods/log get）+ RoleBinding
- runner Deployment k8s 分支：挂 serviceAccountName、去 docker.sock 宿主逃逸面（T-64-06）、经 downward API 注入 `FRIDAY_RUNNER_CALLBACK_HOST`(status.podIP) 与 k8s 配置 env；docker 默认分支逐字零回归
- helm 经 `friday.runner.isK8s` helper 归一 kubernetes/k8s 别名，与 Go `resolveExecutorKind` 行为一致（plan-check Warning 2）

## Task Commits

Each task was committed atomically:

1. **Task 1: KubernetesExecutor 生命周期四方法 + fake 单测** - `f92a57453` (feat)
2. **Task 2: helm runner SA/RBAC + k8s 模式部署形态** - `a8867ddc2` (feat)

## Files Created/Modified
- `deploy/helm/friday/templates/runner-rbac.yaml` - NEW：values-gated SA + namespaced Role + RoleBinding（仅 k8s 模式渲染）
- `runner/internal/k8s/executor.go` - 四方法实现 + runnerSelector 助手；删除 ErrNotImplemented 与 errors import
- `runner/internal/k8s/executor_test.go` - 生命周期 fake-clientset 单测（Remove/StartupCleanup 隔离/ZombieScan 活+终态/ReadContainerFile 退化）
- `deploy/helm/friday/templates/runner-deployment.yaml` - docker/k8s 双分支：k8s 挂 SA、去 docker.sock、注入 podIP 回调 host + k8s env
- `deploy/helm/friday/templates/_helpers.tpl` - 新增 `friday.runner.isK8s`（别名归一）与 `friday.runner.serviceAccountName`
- `deploy/helm/friday/values.yaml` - runner 段新增 `k8s.*`（namespace/backoffLimit/ttlSecondsAfterFinished/serviceAccountName/imagePullSecret）与 `rbac.create`

## Decisions Made
- **ReadContainerFile 退化而非 exec**：Job `restartPolicy=Never` 完成即终止，对已退出 Pod exec/cp 恒失败；直接返回 err+空串，使 `ws/client.go:455` 既有 `log.Warn` 容错生效（text_output 退化为空、output=nil，任务仍按 exit0 判 completed）。完整产物读取（callback 回传 / RWX 共享卷）超出本阶段不动 task 约束（Open Q4），属已知限制。
- **runnerSelector 单一来源**：StartupCleanup 与 ZombieScan 共用 `app=friday-task,friday.runner=<sanitize(name)>`，保证两处隔离语义一致，避免漂移。
- **helm 别名正源归一**：用 `friday.runner.isK8s` helper（`or (eq ... "kubernetes") (eq ... "k8s")`）而非在 values 文档要求 canonical，使 `--set runner.executor=k8s` 与 `kubernetes` 渲染结构一致（仅 FRIDAY_RUNNER_EXECUTOR env 值不同，由 runner 端再归一）。
- **namespace 走 downward API**：注入 `FRIDAY_RUNNER_K8S_NAMESPACE ← metadata.namespace`，运行期取 Pod 真实 namespace，无需在 values 写死。

## Deviations from Plan

None - 计划按原样执行。两任务的实现选择（RemoveContainer 复用 64-01 已有 `deleteJob`、ZombieScan 终态 CompletionTime 缺省回退 CreationTimestamp）均在计划语义范围内，无 scope creep、无需 deviation rule 介入。

## Issues Encountered
None - go build/vet/test 全绿，helm lint 0 失败，docker/kubernetes/k8s 三态渲染均符合验收。

## User Setup Required
None - 本 plan 仅代码 + helm 模板。真机 k0s/containerd 起 Job 端到端跑通 + 日志回传 + Pod 清理为 manual / human_needed（研究环境无真实集群，逻辑层已由 fake clientset 全覆盖）。k8s 模式 HITL answer 端到端投递为已知限制（需 task HTTP answer server 或 RWX 共享卷，out-of-scope，T-64-07 accept）。

## Next Phase Readiness
- RUNNER-02 收官：KubernetesExecutor 七方法完整、helm 可部署形态就绪（SA/RBAC + 去 docker.sock + podIP 回调）。
- 已知限制（文档化）：k8s 模式 ReadContainerFile 产物读取与 HITL answer 端到端投递留待后续（callback/RWX 方案）；真机端到端验收 human_needed。

## Threat Flags
None — 未引入计划 `<threat_model>` 之外的新信任边界面。已落地缓解：T-64-04（namespaced 最小权限 Role + values-gated）、T-64-05（friday.runner label 隔离）、T-64-06（k8s 去 docker.sock）；T-64-07（HITL answer k8s 端到端）按计划 accept 并文档化。

## Self-Check: PASSED

- 创建/修改文件全部存在：executor.go、executor_test.go、runner-rbac.yaml、runner-deployment.yaml、_helpers.tpl、values.yaml、64-02-SUMMARY.md
- 任务提交全部存在：f92a57453（Task 1）、a8867ddc2（Task 2）
- `cd runner && go build ./... && go vet ./... && go test ./...` 全绿；gofmt 干净
- `helm lint deploy/helm/friday` 0 失败；默认(docker) 挂 docker.sock 且无 RBAC（kind:Role==0）；kubernetes 出 SA/Role/RoleBinding、无 docker.sock、有 status.podIP env；k8s 别名与 kubernetes 渲染结构一致（仅 executor env 值不同）

---
*Phase: 64-runner*
*Completed: 2026-06-21*
