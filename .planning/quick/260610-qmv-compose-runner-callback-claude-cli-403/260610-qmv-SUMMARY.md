---
quick_id: 260610-qmv
status: complete
date: 2026-06-10
commits:
  - 203a09eb fix(deploy): compose 部署发布 runner callback 端口并为 server 配置 host-gateway
  - 68ddaa4c fix(runner): 任务容器注入 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC 消除第三方代理 403 噪音
---

# Summary: compose 部署回调失败修复

## 故障现象

Linux + docker compose 部署机器上，任务容器（repo_summary 等）日志报：

```
"Failed to report status", "error": "All connection attempts failed"
"report_completed_failed", "error": "All connection attempts failed"
```

## 根因

- runner 给任务容器注入的回调地址是 `http://host.docker.internal:8976/callback`，
  但 compose 部署下 runner 自身是容器，CallbackServer 监听在容器内 8976，
  `docker-compose.yaml` 未发布该端口 → 任务容器经宿主机网关连接被拒。
- 同源隐患：server 容器需要经 `host.docker.internal` 访问任务容器的
  answer_endpoint，但未配置 `extra_hosts`，Linux 上无法解析。
- 噪音：claude CLI 在第三方 `ANTHROPIC_BASE_URL`（DeepSeek 等）下，
  遥测/bootstrap 端点持续 403 报错刷屏。

## 改动

1. `docker-compose.yaml`
   - runner 服务发布 `${FRIDAY_RUNNER_CALLBACK_PORT:-8976}` 端口
     （宿主端口 = 容器端口，与回调 URL 同源），并注入
     `FRIDAY_RUNNER_CALLBACK_PORT` 环境变量支持自定义。
   - server 服务增加 `extra_hosts: host.docker.internal:host-gateway`。
2. `runner/internal/docker/executor.go`
   - `buildContainerEnv` 注入 `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`。

## 验证

- `go build ./...` / `go test ./internal/docker/` 通过。
- `docker compose config` 解析正常，runner 含端口映射与 env，server 含 extra_hosts。

## 部署侧注意

已部署的机器需要拉取新 compose 文件后 `docker compose up -d`（重建 runner/server）；
runner 镜像需更新到包含本修复的版本才能消除 403 噪音（端口修复仅靠 compose 即生效）。
