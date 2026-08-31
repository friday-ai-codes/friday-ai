---
phase: 63-deploy
verified: 2026-06-21T02:45:00Z
status: human_needed
score: 14/14 must-haves verified (static/test/render); 5 live-cluster behaviors pending human
overrides_applied: 0
re_verification:
human_verification:

  - test: "worker 滚动更新 SIGTERM 优雅 drain（DEPLOY-01）"
    expected: "kubectl rollout 重启 worker Deployment 时，收到 SIGTERM 的 pod 停止领取新 job、跑完在途或在 gracefulTimeout(110s) 内 drain，未完成 job 由 heartbeat-stalled + periodic rescue 重投，无在途 job 丢失"
    why_human: "需真实 k8s + Postgres + 在途 durable job；本地无法模拟 SIGTERM 信号经 Procrastinate install_signal_handlers 的真实 drain"

  - test: "compose up -d 升级不破坏既有部署（DEPLOY-02）"
    expected: "对既有单副本 compose 部署执行 `docker compose up -d`（拉新镜像重建），server 先 migrate→healthy，worker/scheduler 随后启动不崩循环，既有 server/web/runner/postgres/redis/qdrant 行为零回归"
    why_human: "需真实 Docker 守护进程 + 完整镜像 + 既有运行栈；config -q 仅校验语法，不验证运行期编排顺序"

  - test: "scheduler 单例滚动期不双跑 cron（DEPLOY-02）"
    expected: "scheduler 滚动更新时 strategy=Recreate 确保旧 pod 先终止再起新 pod，cron 任何时刻仅一个实例运行，无重复通知/backfill"
    why_human: "需真实 k8s 集群观察滚动更新期间 pod 生命周期"

  - test: "KEDA 按 todo 队列深度真实伸缩 worker（DEPLOY-03）"
    expected: "已装 KEDA operator 的集群，worker.keda.enabled=true 后，procrastinate_jobs todo 深度上升触发 worker 扩容（cooldown 300s 防抖），深度回落缩容但不低于 minReplicaCount=1"
    why_human: "需真实 KEDA operator + Postgres + 队列负载；render 仅证明 ScaledObject 正确生成"

  - test: "真实 GitLab/GitHub MR 去重 + 飞书建群去重（IDEMP-02）"
    expected: "at-least-once 重投下，同 source→target 分支不重复开 PR/MR（复用既有 open MR url），同 work_item 不重复建群（复用 WorkItem.feishu_chat_id）"
    why_human: "需真实 GitLab/GitHub 平台 token + 飞书应用；单测以 mock 验证 fence 逻辑，真实平台幂等行为待端到端验证"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 63: 部署硬化 + 外部副作用 fencing Verification Report

**Phase Goal:** 多副本/弹性部署硬化（优雅终止 + compose/helm 拆 web/worker/scheduler + KEDA/PDB/Redis 约束）+ 外部副作用 fencing/outbox，使 at-least-once 不重复触发外部动作。
**Verified:** 2026-06-21T02:45:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `run_worker --graceful-timeout` 透传 `shutdown_graceful_timeout`（DEPLOY-01） | ✓ VERIFIED | `run_worker.py:40` arg 定义 + `:96` `shutdown_graceful_timeout=graceful_timeout` 透传；`test_run_worker_args.py` 守护（durable 套件 passed） |
| 2 | helm worker Deployment（run_worker, role=worker, termGrace>graceful>心跳）（DEPLOY-02） | ✓ VERIFIED | 渲染解析 worker termGrace=120 > gracefulTimeout=110 > 心跳10s/stalled30s；env FRIDAY_PROCESS_ROLE=worker；run_worker(default render)=2 |
| 3 | helm scheduler Deployment（runapscheduler, role=scheduler, replicas=1, Recreate）（DEPLOY-02） | ✓ VERIFIED | 渲染解析 scheduler replicas=1, strategy=Recreate；runapscheduler(default)=2；role=scheduler |
| 4 | compose worker+scheduler service（同镜像+不同 command+role），config -q 合法（DEPLOY-02） | ✓ VERIFIED | `config -q`（base）OK + `config -q`（base+build）OK；config 含 run_worker / runapscheduler / FRIDAY_PROCESS_ROLE worker+scheduler |
| 5 | 既有 server/compose service 零回归（升级 up -d 不破坏单副本部署） | ✓ VERIFIED（静态） | gating off → component:worker=0；既有 service 未改（git diff 仅新增）；真实 up -d 升级 → human_needed |
| 6 | 多副本/多 worker 无 Redis → settings raise ImproperlyConfigured（运行期 fail-closed）（DEPLOY-03） | ✓ VERIFIED | `settings.py:195` `_require_redis_for_multi_replica` + `:214` `_EXPECT_MULTI_REPLICA`（FRIDAY_EXPECT_MULTI_REPLICA or GUNICORN_WORKERS>1）；`test_settings_fail_closed.py` 4 passed |
| 7 | helm 模板期 fail：replicaCount>1/gunicornWorkers>1 且无 redis → 渲染失败（DEPLOY-03） | ✓ VERIFIED | replicaCount=2+redis off → RENDER FAILED（configmap.yaml:10 中文 fail 信息）；gunicornWorkers=2+redis off → RENDER FAILED（同源 trigger）|
| 8 | KEDA ScaledObject 仅 keda.enabled 时渲染，按 procrastinate_jobs status='todo' 伸缩，minReplica>=1，凭证经 TriggerAuthentication（DEPLOY-03） | ✓ VERIFIED | enabled → ScaledObject=1/TriggerAuth=1；query `...FROM procrastinate_jobs WHERE status = 'todo'`；minReplicaCount=1（minReplica0=0）；scaleTargetRef→release-name-friday-worker；secretTargetRef→DATABASE_URL，无明文密码 |
| 9 | PDB 仅 *.pdb.enabled 时渲染（worker+web），scheduler 不配 PDB（DEPLOY-03） | ✓ VERIFIED | pdb enabled → PDB=2；scheduler has PDB?=False（解析确认）|
| 10 | KEDA/PDB 默认 off：默认安装不渲染（不破坏既有安装）（DEPLOY-03） | ✓ VERIFIED | 默认 render：ScaledObject=0, PDB=0；FRIDAY_EXPECT_MULTI_REPLICA=false |
| 11 | `_create_mr_for_repo` 创建前查既有 open MR/PR，命中复用不重复创建（IDEMP-02） | ✓ VERIFIED | `coding.py:1867` 前置 fence；命中 `existing.success` → return deduplicated（跳过 create_merge_request）；`test_coding_mr_dedup.py` reuse/create/fail-soft 3 例 passed |
| 12 | CreateGroupChatNode 建群前查 WorkItem.feishu_chat_id（锚齐备时），命中跳过 create_chat（IDEMP-02） | ✓ VERIFIED | `feishu_chat.py:396-420` 锚齐备时 fence，命中 return deduplicated chat_id；fail-soft try/except；`test_chat_nodes.py` fenced/no-anchor/fail-soft 3 例 passed |
| 13 | git 平台 client（GitLab/GitHub）新增 find_open_merge_request（OQ4 原无此方法）（IDEMP-02） | ✓ VERIFIED | base.py:46 默认 `return None`（非 @abstractmethod，零回归）；gitlab_client.py:114 `state="opened"`；github_client.py:88 `state="open"` + `head=f"{owner}:{source}"`；均 fail-soft |
| 14 | 无 WorkItem 锚/无既有 MR 时 fence 退化 no-op，行为与现状逐字等价（零回归+fail-soft） | ✓ VERIFIED | coding fence None→照常创建；feishu 无锚→不查照常建群；`test_coding_pr_target_branch.py` 4 例零回归 passed（_make_client 桩 find_open_merge_request=None）|

**Score:** 14/14 truths verified（静态/单测/渲染层）；5 项 live-cluster 行为 → human_needed

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `server/durable/management/commands/run_worker.py` | --graceful-timeout 透传 | ✓ VERIFIED | arg + shutdown_graceful_timeout 透传，零信号代码 |
| `deploy/helm/friday/templates/worker-deployment.yaml` | worker workload | ✓ VERIFIED | role=worker, run_worker, termGrace=120 |
| `deploy/helm/friday/templates/scheduler-deployment.yaml` | scheduler 单例 | ✓ VERIFIED | runapscheduler, replicas=1, Recreate |
| `deploy/helm/friday/templates/worker-scaledobject.yaml` | KEDA scaler | ✓ VERIFIED | procrastinate_jobs todo 深度, values-gated off |
| `deploy/helm/friday/templates/keda-triggerauth.yaml` | TriggerAuthentication | ✓ VERIFIED | secretTargetRef→DATABASE_URL |
| `deploy/helm/friday/templates/worker-pdb.yaml` / `web-pdb.yaml` | PDB | ✓ VERIFIED | policy/v1, values-gated off |
| `server/friday/settings.py` | 运行期 fail-closed | ✓ VERIFIED | `_require_redis_for_multi_replica` + ImproperlyConfigured |
| `server/services/git_platform/{base,gitlab_client,github_client}.py` | find_open_merge_request | ✓ VERIFIED | 双平台实现 + base 默认 None |
| `server/workflows/nodes/ai/coding.py` | MR 前置 fence | ✓ VERIFIED | _create_mr_for_repo:1867 |
| `server/delivery/services/work_item_service.py` | aget_feishu_chat_id | ✓ VERIFIED | @sync_to_async 读访问器:229 |
| `server/workflows/nodes/integrations/feishu_chat.py` | 建群前置 fence | ✓ VERIFIED | CreateGroupChatNode:396 |
| 守护测试（run_worker_args/settings_fail_closed/coding_mr_dedup/chat_nodes） | 单测 | ✓ VERIFIED | 全 passed |

### Key Link Verification

| From | To | Via | Status |
|------|----|----|--------|
| worker-deployment.yaml | roles.py | env FRIDAY_PROCESS_ROLE=worker | ✓ WIRED（渲染含 role=worker）|
| scheduler-deployment.yaml | runapscheduler.py | command runapscheduler + replicas=1 Recreate | ✓ WIRED |
| worker-scaledobject.yaml | worker-deployment.yaml | scaleTargetRef.name={fullname}-worker | ✓ WIRED（release-name-friday-worker）|
| keda-triggerauth.yaml | secret.yaml | secretTargetRef→DATABASE_URL | ✓ WIRED |
| settings.py | GUNICORN_WORKERS/FRIDAY_EXPECT_MULTI_REPLICA env | env.bool/env.int 校验 | ✓ WIRED |
| coding.py | git_platform/base.py | find_open_merge_request 前置 fence | ✓ WIRED（coding.py:1867）|
| feishu_chat.py | work_item_service.py | aget_feishu_chat_id 建群前调 | ✓ WIRED（feishu_chat.py:400）|

### Behavioral Spot-Checks / Render Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| helm lint | `helm lint` | 0 failed | ✓ PASS |
| 默认 render KEDA/PDB | grep counts | 0 / 0 | ✓ PASS |
| KEDA enabled | --set worker.keda.enabled=true | ScaledObject=1/TriggerAuth=1, todo query, minReplica=1 | ✓ PASS |
| PDB enabled | --set *.pdb.enabled=true | PDB=2, scheduler 无 PDB | ✓ PASS |
| 模板期 fail（replicaCount=2+redis off） | helm template | RENDER FAILED（中文 fail）| ✓ PASS |
| 模板期 fail（gunicornWorkers=2+redis off） | helm template | RENDER FAILED（同源）| ✓ PASS |
| 多副本+redis on | --set server.replicaCount=2 | OK + MULTI_REPLICA=true | ✓ PASS |
| worker.enabled only（plan-check fix） | --set worker.enabled=true replica=1 | MULTI_REPLICA=false（不误置 true）| ✓ PASS |
| compose config -q（base/build） | docker compose config -q | 均 OK | ✓ PASS |
| 单测（settings+MR dedup+chat+pr target） | pytest | 40 passed | ✓ PASS |
| tests/durable + tests/delivery | pytest | 500 passed, 1 failed（见下）| ✓ PASS（失败 pre-existing 无关）|

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| DEPLOY-01 | 63-01 | worker 优雅终止 + termGrace | ✓ SATISFIED | Truth 1,2；真实 SIGTERM drain → human |
| DEPLOY-02 | 63-01 | compose/helm 拆 web/worker/scheduler，scheduler 单例 | ✓ SATISFIED | Truth 2,3,4,5；真实 up -d 升级 → human |
| DEPLOY-03 | 63-02 | KEDA scaler + PDB + 多副本强制 Redis fail-closed | ✓ SATISFIED | Truth 6,7,8,9,10；真实 KEDA 伸缩 → human |
| IDEMP-02 | 63-03 | 外部副作用 fencing（MR/PR + 建群） | ✓ SATISFIED | Truth 11,12,13,14；真实平台去重 → human |

所有 4 个 phase requirement ID 均被 plan 认领且实现到位，无 ORPHANED 需求。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `deploy/helm/friday/values.yaml` | 92-99 / 102-109 | `worker.keda:` 键重复定义两次 | ℹ️ Info | YAML last-wins，两块值完全一致，功能无影响；helm lint 通过、渲染正确。建议清理冗余重复键以免后续编辑只改其一造成困惑 |

无 TBD/FIXME/XXX 债务标记；无 stub / 空实现 / 占位返回；无明文密码泄漏（KEDA 凭证经 secret）。

### Pre-existing Failure（非 Phase 63 回归，已确认）

`tests/delivery/test_plan_session_inv6_guard.py::test_inv6_no_bypass_plan_session_write` 失败：

- **根因**：静态 grep 守护把 `chat/conversation_service.py:1922` 的一行**注释**（"# SDD spec 反查：conversation → PlanSession..."）误判为旁路写表。
- **确认无关**：Phase 63 三个 plan 均未触及 `test_plan_session_inv6_guard.py`（最后修改于 commit `df8e574d7` / phase 36-02）或 `chat/conversation_service.py`（不在任何 plan files_modified 列表）。63-03-SUMMARY 已记此为已知 pre-existing 失败。**非 Phase 63 引入的回归。**

### rescue-lives-on-worker 修正确认

✓ 已honored：`values.yaml:117` 明确"durable 周期 rescue 不在此（由 worker periodic deferrer 承载）"，scheduler 仅承载 apscheduler cron；`values.yaml:96,106` worker KEDA minReplicaCount=1 注释"保 periodic deferrer 驱动 rescue"。周期 rescue 锚在 worker 而非 scheduler，与 63-01-SUMMARY 决策一致。

### Human Verification Required

5 项 live-cluster 行为需真实环境验证（实现/渲染均到位、静态测试全绿，仅运行期行为无法本地自动化）：

1. **worker 滚动更新 SIGTERM 优雅 drain（DEPLOY-01）** — 需真实 k8s+Postgres+在途 job
2. **compose up -d 升级不破坏既有部署（DEPLOY-02）** — 需真实 Docker 守护进程 + 完整镜像
3. **scheduler 单例滚动期不双跑 cron（DEPLOY-02）** — 需真实 k8s 观察 Recreate pod 生命周期
4. **KEDA 按 todo 深度真实伸缩 worker（DEPLOY-03）** — 需真实 KEDA operator + 队列负载
5. **真实 GitLab/GitHub MR 去重 + 飞书建群去重（IDEMP-02）** — 需真实平台 token + 飞书应用

### Gaps Summary

无阻断性 gap。全部 14 条 must-have truth 在代码/单测/helm 渲染/compose config 层验证通过：DEPLOY-01（优雅终止纯配置透传）、DEPLOY-02（compose/helm 同构拆 workload + scheduler 单例 Recreate）、DEPLOY-03（settings 运行期 + helm 模板期双层 fail-closed + KEDA todo 深度 scaler + PDB + 默认 off）、IDEMP-02（MR/PR + 建群 reuse-first fencing，fail-soft 零回归）均落地。唯一失败单测确认为 pre-existing 静态守护误报、与本 phase 无关。唯一 anti-pattern 为 values.yaml 重复 keda 键（功能无影响）。

剩余仅 5 项需真实集群/平台的运行期行为，依据本次任务约定（实现/渲染就位 + 静态测试通过的 live-cluster 行为归 human_needed），整体状态判定为 **human_needed**。

---

_Verified: 2026-06-21T02:45:00Z_
_Verifier: Claude (gsd-verifier)_
