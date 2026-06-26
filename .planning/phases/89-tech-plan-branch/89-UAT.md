# Phase 89 — UAT / Deferred Live Verification

> autonomous 链路以 respx/seam/mock 覆盖（对齐 87/88）；真机 E2E 记此。

## PLAN-03 容器 5min 挂起 / resume（89-03）

### [ASSUMED] 真机延迟挂起 / resume（需 runner + Docker 真实容器）
- **5min 计时真触发挂起**：容器编码遇阻发飞书卡 → 5min 无回复 → apscheduler `DateTrigger`
  一次性 job 到点 → `dispatcher.cancel` 真停容器 + `CodingSession.status=SUSPENDED` /
  `parked_at`。单测以 seam 直调 `suspend(...)` 覆盖 CAS + cancel + parked_at；真实计时器到点
  触发链 deferred。
- **卡片回复真 resume 续到终态**：用户飞书卡片回复 → `container_callback` → `schedule_container_resume`
  → `SessionStore` 取 transcript → re-dispatch 容器 `ClaudeAgentOptions(resume=...)` 续跑到 PR
  终态。单测以 mock `dispatch_coding_task` + `build_resume_dispatch_env` 覆盖事件分流；真实容器
  resume 续跑 deferred。
- **session miss 真重灌**：Redis 失效 + DB 无 transcript → `build_resume_dispatch_env` 返回 `{}`
  → 应用态重灌新 session 全新执行。单测 mock 覆盖 reloaded 分流；真实冷启动重灌 deferred。

### [ASSUMED] apscheduler 计时载体多副本 / web 进程行为
- **承载模型确认（A1，已 read_first 落实）**：单仓编码容器 SDK session 承载于
  `CodingSession`（持 `sdk_session_id` / `sdk_transcript`，`SessionStore` / `build_resume_dispatch_env`
  / `_persist_sdk_session` 均以其为对象）。挂起态字段 `SUSPENDED` + `parked_at` 落 `CodingSession`
  （**非** `RepoCodingTask`——后者是 v0.8 多仓 wave 执行实体，不持单仓容器 SDK session）。已确认。
- **计时载体**：5min 计时用 apscheduler `DateTrigger` 一次性 job（已在栈，repo sync 轮询用），
  落共享 `DjangoJobStore`，job_id=`suspend-{coding_session_id}` 幂等 `replace_existing`。
  `_get_timeout_scheduler` 惰性在调用进程（web ASGI / runapscheduler）起一个 best-effort
  `BackgroundScheduler`。**多副本/多进程去重**靠 `DjangoJobStore` 共享 + `suspend` CAS 幂等
  （RUNNING/AWAITING→SUSPENDED 条件 update，重复触发即 no-op）+ `dispatcher.cancel` 幂等
  （无 assignment 返回 False）兜底——即便两个 scheduler 都执行同一 job 也状态安全。真实多副本下
  job 唯一执行 / web 进程内 scheduler 生命周期 deferred 验证；计时载体不可用即降级失效（fail-soft，
  挂起仅资源优化，缺失不影响功能正确性）。

## PLAN-04 固定格式分支名 + 卡片确认 + 逐仓建分支推送 + 绑项目（89-04）

### [ASSUMED] 真机建分支推送（需 DATA_DIR/repos/{repo_id} 真实克隆 + git token + 远端可达）
- **逐仓真建推**：`BranchProvisionService._provision_repo` 复用 CreateBranchNode server-local git
  逻辑（`DATA_DIR/repos/{repo_id}` fetch → checkout base → pull → `checkout -b` → `push -u <auth_url>
  HEAD:refs/heads/<branch>`）。单测以 seam mock（`_agit` / `_abranch_exists` / `_arepo_exists` /
  `aresolve_git_token`）覆盖编排 + 幂等 + token 注入；**真实 git 子进程对真仓建推 + 远端落分支
  deferred**（需已克隆仓 + 有效 token + 网络）。
- **push token 注入真鉴权**：push URL 经 `ssh_git_url_to_https` + `build_authenticated_git_url`
  注入 `oauth2:<token>@host`（单测断言 argv 含 `oauth2:<token>@` 且日志不含明文 token）；真实远端
  接受该鉴权 URL push deferred。
- **分支已存在幂等**：`git rev-parse --verify refs/heads/<branch>` returncode 判定，已存在跳过
  create/push 仅 bind。单测覆盖（仅 fetch、无 checkout/-b/push）；真实远端已存在分支场景 deferred。

### [ASSUMED] 分支名 AI 生成（需真 provider）
- `generate_branch_name` 经 `use_call_source(CallSource.BRANCH_NAMING)`（89-01 已注册）LLM 仅定
  `change_type` + 版本号，id/项目名/日期由 server 权威拼装。单测以 `_ainvoke_naming_llm` mock 覆盖
  成功/失败兜底/override/兜底项目名/id 权威；**真 provider 产出质量 deferred**。卡片改 type
  （`branch_confirm_edit`）走 server 确定性重拼（`build_branch_name` + 用户 type），不再调 LLM。

### 实施决策（[ASSUMED]，偏离/收敛说明）
- **branch_names 载体**：`provision_and_bind(branch_names=...)` 接受 `{repository_id: name}` 映射
  （per-repo type 可不同）或单一 str（应用到所有仓）。`output_data.branch_plan` 逐仓持
  server 权威组件（change_type/yymmdd/tracking_id/project_name/version）+ 拼好的 branch_name，
  供 edit 轮无损重拼。
- **cancel 语义**：`branch_confirm_cancel` 不建分支但 `approve_node`（携 `cancelled=True`）解除
  HITL 闸放行工作流，而非保持 waiting（闭环须可结束）。
- **project 解析**：apply 经 `_resolve_space` + `_aresolve_project`（镜像 repo_association 回调）从
  NodeExecution→workflow→space 解析绑定目标项目。
- **resume CAS 与网关分层**：`resume` CAS 接受 `SUSPENDED/AWAITING→RUNNING`（plan 措辞，防御性）；
  但容器问答回复网关 `_do_resume_async` **仅当 `status == SUSPENDED` 才调 `resume`**——未挂起
  （容器仍存活、用户 5min 内回复）时答复已由 `handle_container_answer_enhanced` 经 answer.json /
  HTTP 直达活容器，绝不重复起容器。组合保证 question-reply 流不产生 spurious re-dispatch。
- **迁移**：纯 `AddField(parked_at)` + `AlterField(status choices)`，无 `RunPython` 回填；
  `unique_active_plan_repo` 约束**不**纳入 `SUSPENDED`（按 plan「仅 AddField/AlterField」收敛，
  挂起态不计活跃约束；resume 经 CAS 翻回 RUNNING 短窗内由 dispatcher 派发幂等兜底）。
