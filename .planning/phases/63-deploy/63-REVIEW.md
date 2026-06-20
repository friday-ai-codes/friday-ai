---
phase: 63-deploy
reviewed: 2026-06-21T02:45:00Z
depth: deep
files_reviewed: 17
files_reviewed_list:
  - server/durable/management/commands/run_worker.py
  - server/friday/settings.py
  - server/services/git_platform/base.py
  - server/services/git_platform/gitlab_client.py
  - server/services/git_platform/github_client.py
  - server/workflows/nodes/ai/coding.py
  - server/workflows/nodes/integrations/feishu_chat.py
  - server/delivery/services/work_item_service.py
  - deploy/helm/friday/templates/worker-deployment.yaml
  - deploy/helm/friday/templates/scheduler-deployment.yaml
  - deploy/helm/friday/templates/worker-scaledobject.yaml
  - deploy/helm/friday/templates/keda-triggerauth.yaml
  - deploy/helm/friday/templates/worker-pdb.yaml
  - deploy/helm/friday/templates/web-pdb.yaml
  - deploy/helm/friday/templates/configmap.yaml
  - deploy/helm/friday/values.yaml
  - docker-compose.yaml
findings:
  critical: 0
  warning: 1
  info: 2
  total: 3
status: issues_found
---

# Phase 63: 部署硬化 + 外部副作用 fencing — Code Review Report

**Reviewed:** 2026-06-21T02:45:00Z
**Depth:** deep
**Files Reviewed:** 17 (source + helm + compose; tests inspected for guard strength)
**Status:** issues_found

## Summary

对 Phase 63（DEPLOY-01/02/03 + IDEMP-02）做了对抗式深度审查：通读全部改动文件、`helm template`/`helm lint` 实际渲染验证、跑通 42 个相关单测、并核对 procrastinate 真实 API 契约。

**整体评价：实现质量高，无 BLOCKER。** 所有 focus 检查均通过：

- **DEPLOY-01**：`--graceful-timeout` 透传的 `shutdown_graceful_timeout` 经核实是 procrastinate 3.8.1 `run_worker_async(**kwargs)` → `Worker` 的合法 kwarg（None=无限等），未自写信号循环，依赖内置 `install_signal_handlers`（默认 True）；不变式 `terminationGracePeriodSeconds(120) > graceful(110) > heartbeat(10s)/stalled(30s)` 与 procrastinate 默认值一致。
- **DEPLOY-02**：scheduler 渲染 `replicas: 1 + strategy.type=Recreate`（已 helm 渲染验证）；`runapscheduler` 仅在 scheduler workload；compose worker/scheduler command + `FRIDAY_PROCESS_ROLE` 正确；worker `depends_on server(healthy)` 解决首启迁移顺序（crash-loop self-heal）。
- **DEPLOY-03**：KEDA query 用正确枚举 `status = 'todo'`；`minReplicaCount: 1`（禁 scale-to-zero）；DB 凭证经 `TriggerAuthentication.secretTargetRef` 无明文；`scaleTargetRef→{fullname}-worker`；PDB 仅 web/worker（scheduler 无 PDB）；KEDA/PDB 默认 off（渲染计数 0 验证）；**`FRIDAY_EXPECT_MULTI_REPLICA` 已修正为只由 web 层（`server.replicaCount>1` 或 `gunicornWorkers>1`）驱动，剔除了 PLAN 中的 `worker.enabled`**（configmap 含显式注释说明，避免误伤"单 server + 关 Redis + 默认开 worker"的 web pod），helm 模板期 fail 条件与 settings 运行期校验同源、无"模板过/运行崩"的不对称。
- **IDEMP-02**：建群前 `aget_feishu_chat_id` fence（仅 project_key + 可 int 的 work_item_id 齐备时查）、MR 创建前 `find_open_merge_request` fence（GitHub `state="open"`+`head=owner:branch`，GitLab `state="opened"`+`source/target_branch`）；全部 reuse-first、无 outbox、fail-soft；守护测试确认重复执行时 `create_merge_request`/`create_chat` **未被调用**（单一外部动作）。
- token 绝不入日志；async ORM 走 `@sync_to_async` 私有同步块；结构化日志。

**核对到的两个"已知项"均确认无问题**：(1) `test_plan_session_inv6_guard` 来自 Phase 36-02（`df8e574d7`），与本期无关；(2) 63-01 重复的 Task-1 提交（`1bfb60aae` + `fff5a1226`）—— `run_worker.py` 在两个提交的内容 md5 完全一致，差异仅在测试文件的后续优化，最终状态一致无冲突。

唯一可整改项是 `values.yaml` 中一处重复的 `keda:` 键（见 WR-01）。

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: `values.yaml` 中 `worker:` 段存在重复的 `keda:` 键

**File:** `deploy/helm/friday/values.yaml:92-109`
**Issue:** `worker:` 段下出现两个 `keda:` 映射键——第一块 `92-99`、第二块 `102-109`，内容几乎逐字相同（仅注释措辞略异）。Helm 底层用 yaml.v2（last-wins），故第二块生效、渲染结果正确（已 `helm template`/`helm lint` 验证通过，无运行期影响）。但这是真实的结构性缺陷：

- 维护者若编辑**第一块**（如调 `maxReplicaCount`/`jobsPerReplica`）会被静默忽略，改动不生效——隐蔽的"改了没用"陷阱。
- 更严格的 YAML 工具链（yaml.v3 / yamllint / 部分 CI lint）会对重复键直接报错。
- 很可能是 63-02 编辑/合并时的重复粘贴残留（与 63-01 executor 自监控误报的重复提交语境吻合）。

**Fix:** 删除其中一块，仅保留单一 `keda:` 定义。建议保留第二块（注释更贴合）并删除 `92-99`：

```yaml
worker:
  enabled: true
  replicaCount: 1
  gracefulTimeout: 110
  terminationGracePeriodSeconds: 120
  resources: {}
  # -- KEDA 队列深度伸缩（默认 off）。仅在已安装 KEDA operator 的集群启用；
  # 非 KEDA 集群保持 off，否则 apply ScaledObject 会因缺 CRD 整体失败。
  keda:
    enabled: false
    pollingInterval: 30
    cooldownPeriod: 300
    minReplicaCount: 1
    maxReplicaCount: 5
    jobsPerReplica: 10
    query: ""
  pdb:
    enabled: false
    maxUnavailable: 1
```

## Info

### IN-01: `test_mr_fence_failsoft` 与 `test_mr_create_when_none` 实质等价，未真正覆盖 fence 抛错路径

**File:** `server/tests/workflows/test_coding_mr_dedup.py:113-122`
**Issue:** `test_mr_fence_failsoft` 与 `test_mr_create_when_none` 都用 `find_return=None` 构造 client，断言也几乎一致。它验证的是"`find` 返回 None 时照常创建"，但并未真正触发 fence 内部抛异常被吞的路径（fail-soft 的吞异常逻辑实际在 `gitlab_client`/`github_client` 的 `except` 分支，已由各自实现保证）。当前测试名暗示覆盖了"异常 fail-soft"，但行为上与上一例重复。

**Fix:** 可让 client mock 的 `find_open_merge_request` 直接 `side_effect=RuntimeError(...)` 来断言 `_create_mr_for_repo` 不冒泡（若想守护"调用方层"也不阻断）；或直接接受 fail-soft 已在 client 层守护、把本例并入说明性注释。非阻断，测试现状全绿。

### IN-02:（范围外/既有）`migration-job.yaml` 渲染出明文 `SECRET_KEY`/`FRIDAY_ENCRYPTION_KEY`/`DATABASE_URL`

**File:** `deploy/helm/friday/templates/migration-job.yaml`（非本期改动文件）
**Issue:** 在做 KEDA 凭证泄漏核查（`helm template --set worker.keda.enabled=true`）时，附带发现 pre-install/upgrade 迁移 Job 以内联 `env: value:` 形式渲染出 chart 默认占位的 `SECRET_KEY`、`FRIDAY_ENCRYPTION_KEY` 与含默认口令的 `DATABASE_URL`（`postgres://friday:friday@...`）。这属于既有模板行为、**不在 Phase 63 范围内**，且本期 KEDA/TriggerAuth 路径本身已正确用 `secretTargetRef` 无明文。仅作记录，供后续部署硬化阶段评估是否改为 `envFrom secretRef`/外部 secret。

**Fix:**（范围外，建议而非要求）迁移 Job 改用 `envFrom secretRef` 引用 chart secret，避免渲染态明文敏感值；生产部署务必覆盖 `server.secretKey` / `postgresql.auth.password` 等默认占位值。

---

_Reviewed: 2026-06-21T02:45:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
