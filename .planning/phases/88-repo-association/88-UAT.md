# Phase 88 — 逐仓容器深验 UAT（deferred live 验证）

**Scope:** 88-03（REPO-02）逐仓 claude code explore 容器深验 + verdict 回调。
**Status:** 自动化层（respx/seam mock dispatcher + 回调 + git 凭证）已覆盖；以下需真实
runner + Docker + 飞书租户的端到端项延后人工验收（autonomous 模式不打断，记录在此）。

## Deferred Live Checks

### A1 — 容器对未知 task_type=`repo_verify` 的容错（[ASSUMED]）

- **假设（RESEARCH A1）：** task 容器对未知 `DispatchTask.task_type`（本期新增
  `repo_verify`）不强校验，按 `env_FRIDAY_TASK_MODE` / `env_FRIDAY_TASK_TASK_MODE=explore`
  分流到只读 explore 模式（`task/core/runner.py::_run_explore_mode`）；`task_type` 仅
  server 端 `SubAgentSession` 语义维度。
- **依据：** `task/core/config.py::normalize_legacy_task_mode` 仅特判 `coding/coding_commit`，
  其余按 `task_mode` 走；故 `repo_verify` + `task_mode=explore` 预期落 explore（风险低）。
- **需真实验证：** 起真实 runner + Docker，派 `task_type="repo_verify"` 容器，确认：
  1. 容器不因未知 task_type 报错、按 explore 只读执行；
  2. explore 全程 `_check_workspace_clean` 通过（深验不写 git，T-88-03-TAMPER）；
  3. 容器产出可被 `parse_verify_verdict` 解析为 JSON verdict。
- **回退预案：** 若容器按 task_type 强校验报错 → 改复用既有 `task_type`（如
  `repo_summary`/`plan`）+ `last_output.source="repo_verify"` 路由（callback 已按 source
  判定，改 dispatch 的 `DispatchTask.task_type` 即可，回调侧无需改）。

### A2 — 真实 explore E2E（读代码产 verdict）

- 真实 runner + Docker + claude code，对一个真实仓库跑 explore 深验，验证：
  1. verdict JSON schema（`fit`/`confidence`/`summary`/`evidence_files`/`mismatch_reasons`）
     被容器稳定产出；
  2. 回调 `_handle_repo_verify_completion` 落 `RepoVerifyTask.verdict` 正确；
  3. `node_execution_id` 续驱经 `_schedule_workflow_resume` 重入挂起节点（工作流入口）。
- **现状：** 自动化以 mock dispatcher + 构造 payload 覆盖回调解析/落库/状态机；真机
  E2E 延后（对齐 Phase 39/83/87 里程碑惯例）。

### A3 — 单仓 fail-soft / runner 离线降级真机表现

- 自动化已覆盖（per-repo 隔离、runner offline → unknown）；真机确认：
  1. 单仓 clone 失败/容器崩溃仅该仓 `failed`，其余仓 verdict 正常；
  2. runner 全离线时确认仓全标 `unknown`、终态不阻断（可继续最终确认/回退，88-05）。

## Automated Coverage (this plan)

- `server/tests/initiatives/test_repo_verify_dispatch.py` — explore 派发 / node_execution_id
  透传 / per-repo 隔离 / runner 离线降级 / 缺 git_url / collect_verdicts 聚合 / confirm。
- `server/tests/subagent/test_repo_verify_callback.py` — verdict 解析落库（结构化 + JSON 文本）/
  空 mark_failed / container_failed / 非 verify 不触发 / 钩子异常 swallow 200 /
  call_source=repo_verify_container。
- `server/tests/initiatives/test_repo_association_inv6_guard.py` — RepoVerifyTask/RepoAssociation
  写入收口守护（覆盖本 plan 新增写入）。
