# 88-03 SUMMARY — RepoVerifyDispatchService 逐仓容器深验 + verdict 回调

**Plan:** 88-03（REPO-02）｜**Status:** ✅ 实现完成，plan 测试全绿（31 passed）

## 交付内容

### 新增

- **`server/initiatives/services/repo_verify_dispatch.py`** — `RepoVerifyDispatchService`
  （复刻 `ResearchDispatchAdapter` 结构，**复刻不复用**，避免污染 PlanSession 编排）：
  - `dispatch(associations, *, initiated_by_user_id)` → `{dispatched, failed, runner_offline}`：
    逐仓建 `RepoVerifyTask`（经 service）+ `_dispatch_verify_task`；单仓 try/except 隔离
    （异常 → `mark_verify_failed` + continue，绝不上抛）；`_count_online_runners()==0`
    runner 离线降级（跳过容器、每仓 verdict 记 `unknown`，不阻断终态）。
  - `_dispatch_verify_task`：缺 git_url → `mark_failed("missing_git_url")`；建
    `AgentSession` + `SubAgentSession(task_type=REPO_VERIFY, node_execution_id=self or None,
    last_output={source:"repo_verify", repo_verify_task_id, association_id, repository_id,
    initiated_by_user_id})` → `DispatchTask(task_type="repo_verify", node_execution_id, timeout=30min)`
    → `get_dispatcher().dispatch` → `mark_verify_running`。
  - `_build_dispatch_metadata`：逐字复刻 explore **双层**（`env_FRIDAY_TASK_MODE` /
    `env_FRIDAY_TASK_TASK_MODE='explore'`）+ cc 凭证 + `aresolve_git_token`（git@→https），
    token 绝不入日志（仅 `has_git_token` 布尔）。
  - `_build_verify_prompt`（server 权威状态注入 feature/路由理由 + JSON verdict schema，V5）、
    `_count_online_runners`、`_get_repository`。

- **`server/tests/initiatives/test_repo_verify_dispatch.py`**（8 tests）：explore 派发 /
  node_execution_id 透传 / per-repo 隔离 / runner 离线降级 / 缺 git_url / collect_verdicts
  聚合（含缺 task→unknown、running→all_terminal=False）/ confirm_repos。
- **`server/tests/subagent/test_repo_verify_callback.py`**（8 tests）：结构化 verdict 落库 +
  关联→verified / JSON 围栏文本 mismatch→rejected / 空→mark_failed / container_failed /
  非 verify 不触发 / 钩子异常 swallow 200 / call_source=repo_verify_container /
  parse_verify_verdict 变体。
- **`.planning/phases/88-repo-association/88-UAT.md`**：A1（未知 task_type=repo_verify 容错 [ASSUMED]）
  + A2（真实 explore E2E）+ A3（fail-soft/离线真机）deferred。

### 扩展

- **`server/initiatives/services/repo_association_service.py`**（RepoVerifyTask 唯一写入口，INV-6）：
  `confirm_repos`（proposed→confirmed）、`dispatch_verify`（置 verifying + 薄委托 dispatch）、
  `create_verify_task`/`mark_verify_running`/`mark_verify_failed`/`record_verdict`（pending→running→
  done|failed 条件更新幂等 + verdict 脱敏 `_sanitize_verdict`，fit→关联 verified/mismatch→rejected）、
  `collect_verdicts`（聚合 `{fit, mismatch, unknown, all_terminal}`，缺/失败仓记 unknown 不阻断）。
- **`server/subagent/api/callbacks.py`**：`_is_repo_verify` / `parse_verify_verdict` /
  `_aload_verify_task` / `_handle_repo_verify_completion`（解析 verdict → record_verdict，
  空 → mark_verify_failed）/ `_handle_repo_verify_failure`（container_failed）；在
  `_handle_completed`/`_handle_failed` 内以独立 try/except swallow 调用（Pitfall 4 不回 5xx）；
  `_schedule_agent_session_resume` 加 `source=="repo_verify"` 短路（防幽灵 agent，mirror
  plan_research）；`_derive_container_call_source` 加 `REPO_VERIFY → repo_verify_container` 分支。
  续驱复用既有 `_schedule_workflow_resume`（node_execution_id 非空），无新写续驱。

## 测试结果

```
uv run pytest tests/initiatives/test_repo_verify_dispatch.py \
  tests/subagent/test_repo_verify_callback.py \
  tests/initiatives/test_repo_association_inv6_guard.py \
  tests/initiatives/test_repo_association_service.py \
  tests/initiatives/test_repo_association_models.py -q
→ 31 passed
```

- INV-6 grep 守护绿（RepoVerifyTask/RepoAssociation 写入仅经 service）。
- ruff 干净；`subagent.api.callbacks` 模块导入正常。

## 设计决策 / [ASSUMED]

- **[ASSUMED] dispatch/collect 以 `list[RepoAssociation]` 为入参**（而非 plan 草稿的单
  `association` + `confirmed_repo_ids`）：88-02 每个确认仓有独立 per-repo `RepoAssociation`
  （unique `(project, repository)`），且 `RepoVerifyTask.association` 与 `.repository` 同仓
  1:1。以确认批次列表聚合最契合模型与 fail-soft「缺失仓记 unknown」语义。签名非 LOCKED 项。
- **[ASSUMED] record_verdict 同步推进 per-repo 关联状态**（fit→verified / mismatch→rejected /
  unknown→保持 verifying），满足「更新 RepoAssociation status」；**批量最终确认/mismatch 回退留
  88-05**。
- **[ASSUMED] 容器 `task_type="repo_verify"` 行为**为只读 explore（A1，依据 task 容器按
  `task_mode` 分流不读 task_type）；真机验证 + 回退预案记 88-UAT.md。

## Deferred（88-UAT.md）

- A1 未知 task_type=repo_verify 容器容错（真实 runner + Docker）；A2 真实 explore E2E 读代码产
  verdict + node_execution_id 续驱；A3 单仓 fail-soft / runner 离线真机表现。
