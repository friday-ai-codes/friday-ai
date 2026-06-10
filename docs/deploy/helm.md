---
title: Helm / Kubernetes 部署
---

# Helm / Kubernetes 部署

官方 Helm Chart 随每次发布推送到 GHCR（OCI registry），适合已有 Kubernetes 集群的生产环境。

Chart 源码位于仓库 [`deploy/helm/friday/`](https://github.com/friday-ai-codes/friday-ai/tree/main/deploy/helm/friday)。

## 一键安装

```bash
# 零配置安装：SECRET_KEY / 加密 key / Runner 令牌自动随机生成并持久化
helm install friday oci://ghcr.io/friday-ai-codes/friday-ai/charts/friday \
  --namespace friday --create-namespace

# 指定版本（省略则取 chart 最新版）
helm install friday oci://ghcr.io/friday-ai-codes/friday-ai/charts/friday \
  --version <版本号> --namespace friday --create-namespace
```

Chart 默认部署 Server、Web、Runner、内置 PostgreSQL（StatefulSet）和 Qdrant（StatefulSet），并通过 pre-install / pre-upgrade Hook 自动执行数据库迁移 Job。

::: tip 导出自动生成的密钥
零配置安装时密钥由 chart 随机生成，建议导出留存：

```bash
kubectl get secret friday-secret -n friday \
  -o jsonpath='{.data.RUNNER_REGISTRATION_TOKEN}' | base64 -d
```
:::

## 升级

```bash
# 升级到最新版本：DB 迁移由 pre-upgrade Hook 自动执行，密钥自动复用不会轮换
helm upgrade friday oci://ghcr.io/friday-ai-codes/friday-ai/charts/friday \
  --namespace friday

# 升级到指定版本
helm upgrade friday oci://ghcr.io/friday-ai-codes/friday-ai/charts/friday \
  --version <版本号> --namespace friday
```

镜像 tag 留空时自动跟随 Chart 的 `appVersion`（发布时由 CI 注入），保证镜像与 chart 版本一致。

## 配置项参考

完整默认值见 [`values.yaml`](https://github.com/friday-ai-codes/friday-ai/blob/main/deploy/helm/friday/values.yaml)。

### Server

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `server.replicaCount` | Server 副本数 | `1` |
| `server.image.repository` | 镜像仓库 | `ghcr.io/friday-ai-codes/friday-ai/server` |
| `server.image.tag` | 镜像标签（留空跟随 `appVersion`） | `""` |
| `server.secretKey` | Django `SECRET_KEY`（`existingSecret` 优先） | 自动生成 |
| `server.encryptionKey` | `FRIDAY_ENCRYPTION_KEY` | 自动生成 |
| `server.debug` | 调试模式 | `"false"` |
| `server.allowedHosts` | 允许的主机名 | `"*"` |
| `server.gunicornWorkers` | Gunicorn Worker 数量 | `1` |
| `server.gunicornTimeout` | Worker 超时秒数 | `300` |

Server 自带 `/health` 的 liveness / readiness 探针。

### Runner

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `runner.enabled` | 是否部署 Runner | `true` |
| `runner.replicaCount` | 副本数 | `1` |
| `runner.registrationToken` | 注册令牌（留空自动生成） | `""` |
| `runner.name` | Runner 名称 | `"k8s-runner"` |
| `runner.executor` | 执行器类型 | `"docker"` |
| `runner.dockerSocketPath` | Docker socket 路径 | `/var/run/docker.sock` |
| `runner.dockerGID` | Docker 组 GID | `999` |

::: warning Runner 与 Docker socket
`executor: docker` 模式下 Runner 需要挂载节点的 Docker socket 来启动任务容器，相当于赋予节点级 Docker 权限。请将 Runner 调度到专用节点池，或评估使用 k8s executor。
:::

### 数据库与向量库

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `postgresql.enabled` | 内置 PostgreSQL StatefulSet | `true` |
| `postgresql.persistence.size` | PVC 大小 | `10Gi` |
| `externalDatabase.url` | 外部数据库 URL（内置禁用时） | `""` |
| `qdrant.enabled` | 内置 Qdrant StatefulSet | `true` |
| `qdrant.persistence.size` | PVC 大小 | `10Gi` |
| `externalQdrant.url` | 外部 Qdrant URL | `""` |
| `externalQdrant.apiKey` | 外部 Qdrant API Key | `""` |

使用外部 Qdrant 时（`qdrant.enabled=false` + `externalQdrant.url` 非空），server 通过环境变量直连，前端向导 / 设置页会锁定 Qdrant 地址（env 优先）。两者都留空时，Qdrant 交由首启向导手动配置。

### Ingress

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `ingress.enabled` | 是否启用 Ingress | `false` |
| `ingress.className` | Ingress Class | `traefik` |
| `ingress.host` | 域名 | `friday.local` |
| `ingress.tls` | TLS 配置 | `[]` |

示例：

```bash
helm upgrade --install friday oci://ghcr.io/friday-ai-codes/friday-ai/charts/friday \
  --namespace friday --create-namespace \
  --set ingress.enabled=true \
  --set ingress.className=nginx \
  --set ingress.host=friday.example.com
```

### 引用已有 Secret

生产环境建议预先创建 Secret 并通过 `existingSecret` 引用，避免密钥进入 values 历史：

```bash
kubectl create secret generic my-friday-secret -n friday \
  --from-literal=SECRET_KEY="$(openssl rand -base64 32)" \
  --from-literal=FRIDAY_ENCRYPTION_KEY="$(openssl rand -base64 32)" \
  --from-literal=RUNNER_REGISTRATION_TOKEN="$(openssl rand -base64 32)"

helm install friday oci://ghcr.io/friday-ai-codes/friday-ai/charts/friday \
  --namespace friday --set existingSecret=my-friday-secret
```

## 从 Docker Compose 迁移

1. 将 `.env` 中的环境变量迁移到 `values.yaml` 或 Kubernetes Secret（尤其是 `FRIDAY_ENCRYPTION_KEY`，否则已加密的凭据无法解密）；
2. 数据库数据用 `pg_dump` / `pg_restore` 单独迁移；
3. Runner 需要重新注册（注册令牌一次性使用）。

## 下一步

- [环境变量参考](/deploy/configuration)
- [管理指南](/guide/admin) —— Runner 管理、OIDC、用户权限
