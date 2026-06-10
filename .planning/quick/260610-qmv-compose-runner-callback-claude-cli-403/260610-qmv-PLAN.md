---
quick_id: 260610-qmv
description: 修复 compose 部署下任务容器回调失败（runner callback 端口未发布）并抑制 claude CLI 403 遥测噪音
date: 2026-06-10
---

# Quick Task 260610-qmv: compose 部署回调失败修复

## 背景（故障诊断）

在 compose 部署的机器（Linux）上运行 repo_summary 等任务时，任务容器日志报：

```
"Failed to report status", "error": "All connection attempts failed"
"report_completed_failed", "error": "All connection attempts failed"
```

根因链路：

1. runner 启动任务容器时注入回调地址 `http://host.docker.internal:8976/callback`
   （`runner/internal/ws/client.go` L141，端口来自 `GetCallbackPort()` 默认 8976）。
2. 任务容器带 `ExtraHosts: host.docker.internal:host-gateway`，能解析到宿主机网关。
3. 但 compose 部署下 runner 自身是容器（`friday-runner`），CallbackServer 监听在
   runner 容器内的 8976，`docker-compose.yaml` 的 runner 服务没有任何 `ports` 映射，
   宿主机 8976 无人监听 → 任务容器连接被拒 → 进度/状态回调全部丢失。
4. 同源隐患：runner 把任务容器的 `answer_endpoint` 上报为
   `http://host.docker.internal:<hostPort>/answer`，server 容器
   （`server/subagent/question_handler.py`）会向该地址回传交互答案，但 compose 里
   server 服务未配置 `extra_hosts`，Linux 上 server 容器内无法解析
   `host.docker.internal` → 交互问答同样会失败。

另有无害噪音：任务容器内 claude CLI 因 `ANTHROPIC_BASE_URL` 指向第三方代理
（DeepSeek），遥测/bootstrap 端点持续 403 报错刷屏。

## Tasks

### Task 1: docker-compose.yaml — 发布 runner callback 端口 + server extra_hosts

- **files**: `docker-compose.yaml`
- **action**:
  - runner 服务增加 `ports: - "${FRIDAY_RUNNER_CALLBACK_PORT:-8976}:${FRIDAY_RUNNER_CALLBACK_PORT:-8976}"`
    与 `FRIDAY_RUNNER_CALLBACK_PORT=${FRIDAY_RUNNER_CALLBACK_PORT:-8976}` 环境变量
    （监听端口与 URL 端口同源，宿主端口必须等于容器端口）。
  - server 服务增加 `extra_hosts: - "host.docker.internal:host-gateway"`，
    使 Linux 上 server 容器可达 answer_endpoint。
- **verify**: `docker compose config` 可解析；runner 服务含端口映射与 env。
- **done**: 任务容器经宿主机网关可达 runner CallbackServer。

### Task 2: runner — 抑制 claude CLI 非必要流量（403 噪音）

- **files**: `runner/internal/docker/executor.go`, `runner/internal/docker/executor_test.go`
- **action**: `buildContainerEnv` 注入 `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`，
  关闭 claude CLI 遥测/统计/bootstrap 等非必要外联，消除第三方 BASE_URL 下的 403 刷屏。
- **verify**: `go test ./internal/docker/` 通过；`go build ./...` 通过。
- **done**: 新建任务容器环境变量包含该项。

## must_haves

- compose 部署下任务容器能成功回调 runner（端口可达）
- server 容器可解析 host.docker.internal
- 不影响 runner 裸机部署（host 上直跑监听 8976 行为不变）
