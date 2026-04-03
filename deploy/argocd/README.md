# ArgoCD GitOps 部署
本目录包含 Friday AI 的 ArgoCD Application 配置，用于实现 GitOps 自动同步部署。
## 前置条件
- 运行中的 Kubernetes 集群（v1.24+）
- 已安装 ArgoCD（推荐 v2.8+）
- `kubectl` 已配置集群访问权限
- Git 仓库可被 ArgoCD 访问（私有仓库需先配置认证，见下文）
## 快速开始
### 1. 配置 Application Manifest
编辑 `application.yaml`，替换以下占位符为实际值：
| 字段 | 默认值 | 说明 |
|------|--------|------|
| `spec.source.repoURL` | `https://github.com/your-org/friday-ai.git` | 替换为实际 Git 仓库地址 |
| `spec.source.targetRevision` | `main` | 替换为目标分支或 tag |
| `spec.destination.server` | `https://kubernetes.default.svc` | 目标集群 API 地址（本地集群无需修改） |
| `spec.destination.namespace` | `friday` | 目标命名空间 |
### 2. 私有仓库认证（如需要）
如果 Git 仓库为私有仓库，需先在 ArgoCD 中配置认证：
```bash
# 使用用户名 + Token 认证
argocd repo add https://github.com/your-org/friday-ai.git \
 --username <username> \
 --password <token>
# 或使用 SSH 认证
argocd repo add git@github.com:your-org/friday-ai.git \
 --ssh-private-key-path ~/.ssh/id_rsa
```
### 3. 部署 Application
```bash
kubectl apply -f deploy/argocd/application.yaml
```
### 4. 验证同步状态
```bash
# 通过 ArgoCD CLI 查看 Application 状态
argocd app get friday
# 或通过 kubectl 查看
kubectl get application friday -n argocd
# 查看同步详情
argocd app sync friday --dry-run
```
## 镜像更新流程
标准 GitOps 镜像更新流程——通过修改 Git 仓库中的 values.yaml 触发自动部署：
1. 修改 `deploy/helm/friday/values.yaml` 中对应服务的 `image.tag`
2. 提交并推送到 Git 仓库
3. ArgoCD 自动检测变更并同步到集群
示例：
```bash
# 更新 server 镜像版本
# 编辑 deploy/helm/friday/values.yaml:
# server:
# image:
# tag: "v1.2.0" # 修改为新版本
git add deploy/helm/friday/values.yaml
git commit -m "chore: update server image to v1.2.0"
git push
# ArgoCD 将在数秒内检测到变更并自动同步
```
同样适用于 `web`、`runner`、`qdrant` 等服务的镜像更新。
## 同步策略说明
当前 Application 配置的同步策略如下：
| 策略 | 值 | 说明 |
|------|-----|------|
| `automated.prune` | `true` | 自动删除 Git 中已移除的资源 |
| `automated.selfHeal` | `true` | 集群手动修改自动回滚到 Git 状态 |
| `syncOptions.CreateNamespace` | `true` | 自动创建目标命名空间 |
| `syncOptions.PrunePropagationPolicy` | `foreground` | 确保资源按依赖顺序删除 |
| `retry.limit` | `5` | 同步失败最多重试 5 次 |
| `retry.backoff` | `5s / factor:2 / max:3m` | 指数退避重试策略 |
## 有状态服务保护
PostgreSQL 和 Qdrant 的 StatefulSet 及其 PersistentVolumeClaim 均已配置以下注解：
```yaml
annotations:
 argocd.argoproj.io/sync-options: Delete=false
```
此注解确保 ArgoCD 在同步（包括 prune）时**不会删除**这些资源及其关联的持久化数据。即使在 Git 仓库中移除了对应的模板文件，ArgoCD 也不会在集群中删除这些 StatefulSet 和 PVC。
受保护的资源：
- `friday-postgresql` StatefulSet 及其 `data` PVC
- `friday-qdrant` StatefulSet 及其 `data` PVC
## 高级配置
### ignoreDifferences
如果使用 HPA（Horizontal Pod Autoscaler）或有外部 controller 修改资源字段，可在 Application `spec` 中添加 `ignoreDifferences` 避免 ArgoCD 不断回滚：
```yaml
spec:
 ignoreDifferences:
 - group: apps
 kind: Deployment
 jsonPointers:
 - /spec/replicas
```
### 移除 Finalizer
Application 默认配置了 `resources-finalizer.argocd.argoproj.io` finalizer，删除 Application 时会级联清理集群中的所有托管资源。
如果希望删除 Application 时**保留**集群资源（仅删除 ArgoCD 跟踪记录），可移除 finalizer：
```bash
kubectl patch application friday -n argocd \
 --type json -p '[{"op":"remove","path":"/metadata/finalizers"}]'
```
### 自定义 Values
可在 Application `source.helm` 中添加额外的 valueFiles 或 parameters 覆盖默认值：
```yaml
spec:
 source:
 helm:
 releaseName: friday
 valueFiles:
 - values.yaml
 - values-production.yaml # 额外的生产环境配置
 parameters:
 - name: server.replicaCount
 value: "3"
```
