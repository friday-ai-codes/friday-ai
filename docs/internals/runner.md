---
title: Runner 与 Task 执行器
---

# Runner 与 Task 执行器

AI 编码任务不在 server 进程里执行，而是由 Go Runner 调度到隔离的任务容器中运行。这层隔离带来三个好处：编码代理拿不到 server 的密钥与数据库、资源消耗可控、宿主机与执行环境解耦。

## Runner（Go）

代码位于 `runner/`，Go 1.25，单二进制 `friday-runner`（cobra CLI：`run` / `register` / `service` 等）。

### 注册与连接

```bash
friday-runner register   # 用 RUNNER_REGISTRATION_TOKEN 注册，换取长期凭据
friday-runner run        # 建立 WebSocket 连接，接收任务派发
```

- 注册令牌（`RUNNER_REGISTRATION_TOKEN`）一次性使用，server 与 runner 共享；
- 注册后 Runner 通过 WebSocket（`coder/websocket`）长连接到 server（`runner/internal/ws/`），定时上报心跳与系统指标（`gopsutil`）；
- 配置存于 `config.toml`，可被 `FRIDAY_RUNNER_*` 环境变量覆盖（viper 绑定）。

### 任务调度

`runner/internal/scheduler/` 实现 FIFO 队列 + semaphore 并发控制：

- server 经 WebSocket 推送 `TaskPayload`，入队后由信号量控制并发执行数量；
- Runner 维护 `task_id → container_id` 映射，支持取消与优雅停机（停止接收新任务、等待在途任务结束）；
- HTTP 通信用 `go-retryablehttp` 自动重试。

### 执行器

| 执行器 | 实现 | 说明 |
| --- | --- | --- |
| `docker` | `runner/internal/docker/` | 通过 Docker SDK（`/var/run/docker.sock`）启动任务容器，默认方式 |
| `k8s` | `runner/internal/k8s/` | 在 Kubernetes 中以 Job 方式运行任务 |

### 回调通道

Runner 内置 CallbackServer（默认端口 `8976`，`runner/internal/callback/`）。任务容器是宿主 daemon 上的「兄弟容器」，通过 `host.docker.internal` 回调 Runner 上报进度；交互式提问（任务执行中需要人类补充信息）也走这条链路转发回 server。

## Task 执行器（Python）

代码位于 `task/`，Python 3.14，入口 `friday-task`（click CLI）。镜像由 CI 构建并推送 `ghcr.io/friday-ai-codes/friday-ai/task`，带 750 MB 体积门禁与 Trivy CVE 扫描。

### 核心模块

| 模块 | 职责 |
| --- | --- |
| `core/config.py` | `pydantic-settings` 配置（任务模式、仓库、凭据均经环境注入） |
| `core/runner.py` | `TaskRunner`：编排一次任务的完整生命周期 |
| `core/executor.py` | 驱动 claude-agent-sdk（固定版本 `0.1.58`）执行编码代理 |
| `core/remote_tools.py` | 容器内代理可调用的远程工具（经回调链路访问 Friday 的检索能力） |
| `git_ops/` | GitPython：clone、建分支、提交、推送 |
| `integrations/` | 与 server 的回调协议实现 |

### 任务生命周期

<FlowPipeline :steps="['Runner 注入参数启动容器', 'clone 仓库 + 检出分支', '编码代理执行', '提交并推送分支', 'server 继续推进 PR / MR']" />

1. Runner 以环境变量注入任务参数（模式、仓库地址、一次性凭据、回调地址）启动容器；
2. Task clone 仓库、检出工作分支；
3. claude-agent-sdk 启动编码代理执行任务，期间 Tool Call、进度与 token 用量持续回传；
4. 完成后提交并推送分支，回报分支名、commit、diff 摘要与恢复点（`recovery_state`）；
5. server 侧继续推进：分支总结、AI 代码审查、创建 PR / MR、回写飞书。

支持多种任务模式（`TASK_MODE`），除编码外还包括 `repo_summary` 等分析型任务。

### 失败恢复

- 容器内瞬时错误用 `tenacity` 重试；
- 执行结果为 `partial` 时（代码已推送但后续步骤失败），server 保留 `runner_logs`、`last_diff` 与 `recovery_state`，可只重试 `summarize_branch` / `create_merge_request` 而不重跑代码。

## 跨进程契约

server ↔ runner ↔ task 之间的消息结构必须保持同步，相关代码：

- `server/runners/` —— server 侧任务派发与 Runner 管理
- `runner/internal/ws/` —— WebSocket 消息类型（`TaskPayload` 等）
- `server/subagent/api/` —— 任务容器回调端点

修改任何一侧的协议字段时，需要同时检查其余两处。

## 相关文档

- [管理指南 · Runner 管理](/guide/admin#runner-管理) —— 注册流程、心跳监控、配置项
- [Docker Compose 部署](/deploy/docker-compose) —— Docker socket、回调端口编排细节
