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

### 实施决策（[ASSUMED]，偏离/收敛说明）
- **resume CAS 与网关分层**：`resume` CAS 接受 `SUSPENDED/AWAITING→RUNNING`（plan 措辞，防御性）；
  但容器问答回复网关 `_do_resume_async` **仅当 `status == SUSPENDED` 才调 `resume`**——未挂起
  （容器仍存活、用户 5min 内回复）时答复已由 `handle_container_answer_enhanced` 经 answer.json /
  HTTP 直达活容器，绝不重复起容器。组合保证 question-reply 流不产生 spurious re-dispatch。
- **迁移**：纯 `AddField(parked_at)` + `AlterField(status choices)`，无 `RunPython` 回填；
  `unique_active_plan_repo` 约束**不**纳入 `SUSPENDED`（按 plan「仅 AddField/AlterField」收敛，
  挂起态不计活跃约束；resume 经 CAS 翻回 RUNNING 短窗内由 dispatcher 派发幂等兜底）。
