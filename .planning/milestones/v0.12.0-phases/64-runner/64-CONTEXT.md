# Phase 64: runner k8s Job executor - Context

**Gathered:** 2026-06-20
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — 灰区默认值按里程碑锁定约束自动采纳)

<domain>
## Phase Boundary

把 runner 从硬绑 docker.sock 抽象为 executor 接口（docker/k8s 两实现），并落地 k8s Job executor，使任务容器可在 k0s/containerd 多副本环境经 k8s API 运行。交付：

1. **executor 接口解耦（RUNNER-01）**：runner executor 接口（`ws.ExecutorService`）docker/k8s 两实现，与现有 server↔runner WebSocket 派发 + HTTP 回调契约解耦；docker executor 行为零回归。
2. **k8s Job executor（RUNNER-02）**：`KubernetesExecutor` 经 k8s API 起 Job/Pod 跑任务容器（去 `/var/run/docker.sock`），含 ServiceAccount/RBAC、日志流式回传、Pod 清理、失败重试；在 k0s/containerd 环境可用。

**现状坐标（已存在 vs 需建）**：
- ✅ `ws.ExecutorService` 接口已存在（`runner/internal/ws/client.go:59`，7 方法）。
- ✅ `DockerExecutor` 完整实现并工作（`runner/internal/docker/executor.go`）。
- ⚠️ `KubernetesExecutor` 仅为**桩**（`runner/internal/k8s/executor.go`，全方法返回 `ErrNotImplemented`，已过编译期接口检查）。
- ⚠️ executor 选择**硬编码** docker（`runner/internal/cmd/run.go:38` `docker.NewDockerExecutor`）——需加 docker/k8s 选择。
- ⚠️ 无 `k8s.io/client-go` 依赖——需 `go get`。

**不在范围内**：改 server 侧 WebSocket/回调契约（保持解耦不动）；改 task 容器内部逻辑。

</domain>

<decisions>
## Implementation Decisions

### executor 选择与解耦（RUNNER-01）
- RUNNER-01 大部分已就位（接口 + docker 实现 + 编译期 k8s 桩）；本阶段补 **executor 选择**：runner 配置新增 `executor.type`（`docker`|`k8s`，默认 `docker` 零回归），`run.go` 据此构造 `DockerExecutor` 或 `KubernetesExecutor`。
- 选择经既有 viper config（`FRIDAY_RUNNER_*` env + config.toml），默认 docker 保现有部署零回归。
- docker executor 路径逐字不动（零回归命门）；只新增分支。

### k8s Job executor 实现（RUNNER-02）
- 实现 `KubernetesExecutor` 7 方法（对齐 `ws.ExecutorService` 契约）：
  - `StartContainer` → 创建 k8s **Job**（单 Pod，task 容器镜像 + env/回调 URL+token 注入），返回 job/pod 标识作 containerID + answerEndpoint（Pod IP/Service）。
  - `WaitContainer` → watch Job 完成/失败，取 exitCode + 末尾日志（带 timeout）。
  - `ReadContainerFile` → 经 Pod exec 或日志/结果约定读文件（复用既有 task 回调产物约定，倾向 exec 或 cp 等价）。
  - `StreamLogs` → k8s Pod log stream（follow）逐行回调。
  - `RemoveContainer` → 删 Job（propagation=Background 连带 Pod 清理）。
  - `StartupCleanup` → 启动时清理本 runner 残留 Job（按 label selector）。
  - `ZombieScan` → 按 label 扫超时/失联 Job 比对 knownIDs，清理僵尸。
- client-go：in-cluster config（`rest.InClusterConfig`）优先，fallback kubeconfig（dev）；目标 namespace 可配。
- Job 命名/标签：确定性 + label selector（`app=friday-task` + runner/ task id）便于清理/扫描；`backoffLimit` 承载失败重试；`ttlSecondsAfterFinished` 辅助清理。
- ServiceAccount/RBAC：helm 给 runner 配 SA + Role/RoleBinding（jobs/pods/pods/log create/get/list/watch/delete），values-gated（仅 k8s executor 模式需要）。
- 不依赖 docker.sock（k8s 模式完全经 k8s API）。

### Claude's Discretion
- `ReadContainerFile` 在 k8s 下的具体实现（Pod exec vs 约定结果回传 vs initContainer/sidecar）——倾向复用既有 task 回调产物约定，最小侵入；若必须 exec 则用 client-go remotecommand。
- answerEndpoint 在 k8s 下的形态（Pod IP:port vs headless Service vs 回调反向）——对齐 docker executor 当前 answerEndpoint 语义。
- Job 模板字段默认（backoffLimit、ttlSecondsAfterFinished、resources、restartPolicy=Never）。
- namespace/SA 名、label 约定的具体值。
- client-go 版本（对齐 k0s/containerd 目标）。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `runner/internal/ws/client.go`（`ExecutorService` 接口 7 方法 + `TaskPayload` + Config.Executor）——契约真相源。
- `runner/internal/docker/executor.go`（`DockerExecutor` 完整实现）——k8s 实现的行为参照（每方法语义对齐）。
- `runner/internal/k8s/executor.go`（`KubernetesExecutor` 桩 + 编译期接口检查）——填充对象。
- `runner/internal/cmd/run.go:38`（executor 构造点）——加选择分支。
- `runner/internal/config/`（viper config，`FRIDAY_RUNNER_*`）——加 `executor.type` + k8s 配置。
- `runner/internal/scheduler/scheduler.go`（调度，经接口调用 executor，无需改）。
- `deploy/helm/friday/templates/runner-deployment.yaml` + values.yaml——加 SA/RBAC（values-gated）。
- `runner/Makefile`、`runner/go.mod`、docker `executor_test.go`（测试范式）。

### Established Patterns
- 编译期接口检查 `var _ ws.ExecutorService = (*X)(nil)`。
- viper config + env 绑定（默认值保零回归）。
- helm values-gated 可选特性（Phase 63 范式）。
- Go 标准 testing + gotest.tools/v3。

### Integration Points
- `run.go` executor 选择分支。
- `config` 新增 executor.type + k8s 段。
- `k8s/executor.go` 7 方法实现 + client-go 依赖（go.mod）。
- helm runner SA/Role/RoleBinding（values-gated）。
- runner 单测（k8s executor 用 fake clientset / docker 零回归）。

</code_context>

<specifics>
## Specific Ideas

- docker executor 行为零回归是命门（默认 type=docker，docker 路径不动）。
- k8s 模式完全去 docker.sock，经 k8s API 起 Job/Pod。
- 含 SA/RBAC、日志流式回传、Pod 清理（删 Job 连带）、失败重试（backoffLimit）。
- 在 k0s/containerd 多副本环境可用（in-cluster config）。

</specifics>

<deferred>
## Deferred Ideas

- 改 server↔runner WebSocket/回调契约（保持解耦，不动）。
- task 容器内部逻辑变更（不动）。
- 多 namespace / 多集群调度、Job 优先级/队列（v2）。

</deferred>

---

*Phase: 64-runner*
*Context gathered: 2026-06-20 via smart discuss (autonomous)*
