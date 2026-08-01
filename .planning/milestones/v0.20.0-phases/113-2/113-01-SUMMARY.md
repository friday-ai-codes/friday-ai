---
phase: 113-2
plan: 01
requirements: [BUS-01, BUS-02]
provides:
  - "delivery.BlueprintContextEntry：会话级 append-only 总线条目。字段 id/convergence_session FK/project FK(**可空**)/key(200)/kind(24)/repository_id(64)/content JSON/produced_by(64)/seq PositiveInteger/status(16)/initiated_by_user_id(64)/created_at/updated_at；db_table=delivery_blueprint_context_entry；ordering=[\"seq\"]"
  - "枚举 ContextEntryKind = finding|api_surface|contract|decision|dependency_claim|question（六值锁定）；ContextEntryStatus = active|superseded"
  - "三条复合索引（convergence_session 恒最左列）：[session,seq] 增量拉取 / [session,key] 前缀 range scan / [session,kind,status] 环检测；唯一约束 uq_blueprint_context_session_seq"
  - "migration 0032_blueprint_context_entry，dependencies = [(delivery,0031_blueprint_models), (initiatives,0014_project_context_link)]"
  - "BlueprintContextService(*, lifecycle_service=None) —— BlueprintContextEntry 唯一 writer（INV-6），模型层零业务方法"
  - "append_entry(*, session, key, kind, content, repository_id=\"\", produced_by=\"system\", project_id=None, initiated_by_user_id=\"system\") -> BlueprintContextEntry；非法 kind / 空 key 抛 ValueError 且 DB 零写入"
  - "read_entries(*, session, since_seq=0, key_prefix=\"\", kind=\"\", repository_id=\"\", status=\"active\", limit=50) -> list[dict]；dict 键 = id(str)/key/kind/repository_id/content/produced_by/seq/status/created_at(isoformat str)；恒返回 list，无条目 []，绝不抛；limit 被 _MAX_READ_LIMIT=200 硬夹紧"
  - "register_waiter(*, session, from_repository_id, wait_key_pattern, partial_plan_id=\"\", reason=\"\", artifact=None, initiated_by_user_id=\"system\") -> {\"entry_id\": str, \"cycle_detected\": bool, \"cycle\": list[list[str]], \"thread_id\": str}（形状恒定，下游无需判空分支）"
  - "adetect_wait_cycles(session) -> list[list[str]]；satisfy_waiters(*, session, key, repository_id=\"\", initiated_by_user_id=\"system\") -> list[str]（**待重派仓 id 清单**，去重保序，幂等：二次同 key 返回 []）；expire_waiters(*, session, max_age_seconds, initiated_by_user_id=\"system\") -> list[str]"
  - "纯函数契约：_redact_json(value) -> Any（递归叶子脱敏，dict 键也脱敏，非字符串叶子原样，脱敏失败 fail-closed 回落空串）；find_wait_cycles(edges: dict[str, set[str]]) -> list[list[str]]（含自环，同环只返一次）；matches_wait_pattern(key, pattern) -> bool（精确 / 尾 `*` 前缀 / 单 `*` 全匹配）"
  - "三个事件常量：blueprint.context.entry_appended（payload key/kind/seq/repository_id/entry_id/initiated_by_user_id）、blueprint.context.waiter_registered（payload entry_id/from_repository_id/to_key/cycle_detected/thread_id）、blueprint.context.waiter_satisfied（payload key/satisfied_count/redispatch_repository_ids/reason）；均在 BLUEPRINT_EVENTS，不在 ALL_EVENTS"
  - "模块常量：_MAX_CONTENT_BYTES=32768（超限置 {\"_truncated\": True, \"_original_bytes\": n}）/ _MAX_READ_LIMIT=200 / _DEFAULT_READ_LIMIT=50 / _SEQ_RETRY_ATTEMPTS=2 / _WAITER_KEY_PREFIX=\"dependency:\""
affects:
  - "113-02（容器 MCP view）：read_blueprint_context / report_blueprint_context 只调 read_entries / append_entry，零裸 ORM 写"
  - "113-04（等待原语与重派）：satisfy_waiters / expire_waiters 的返回值即「待重派仓清单」，直接喂 dispatch(force_deep_repository_ids=…)；超时清理挂 barrier 续驱路径，本 plan 不起定时任务"
  - "113-06（distill 沉淀）：按 kind ∈ {decision, contract, api_surface} + status=active 取条目；project 可空需在沉淀侧 best-effort 反查"
  - "115（时间线）：三个 blueprint.context.* 事件的 payload 键即「谁在等谁」可视化数据源"
key-files:
  created:
    - server/delivery/models/blueprint_context_entry.py
    - server/delivery/migrations/0032_blueprint_context_entry.py
    - server/delivery/services/blueprint_context_service.py
    - server/tests/delivery/test_blueprint_context_seq.py
    - server/tests/delivery/test_blueprint_context_service.py
  modified:
    - server/delivery/models/__init__.py
    - server/delivery/services/event_taxonomy.py
    - server/tests/delivery/test_blueprint_event_taxonomy_112.py
completed: 2026-07-30
---

# Phase 113-2 Plan 01: Blueprint Context Bus 数据面与唯一写入口 Summary

**一行结论**：`delivery.BlueprintContextEntry` + `0032` migration 建成会话级 append-only 总线（三条以 `convergence_session` 为最左列的复合索引 + `uq_blueprint_context_session_seq`），`BlueprintContextService` 作为唯一 writer 落地五个公开方法——`seq` 锁父 `ConvergenceSession` 行串行分配、`IntegrityError` 有界重试兜底、`content` 走自建 `_redact_json` 递归叶子脱敏（fail-closed）、waiter 以 `dependency_claim` 行登记且**登记瞬间**做环检测抛 blocking 澄清、`satisfy_waiters` 判定与置 `superseded` 同事务因而幂等；21 例新测试全绿且**经变异验证真能证伪**（去掉重试或去掉脱敏，两条 ⭐ 用例立刻失败），`tests/delivery/` 620 passed 零回归。

## Accomplishments

- **BUS-01 数据面（模型 + migration）**：六个 `kind`、两个 `status` 逐值锁定；`seq` 是 `PositiveIntegerField` 而非 `AutoField`（跨会话空洞会让 `since_seq` 增量语义失效）；模型层零业务方法（除 `__str__`）；三条索引各带「驱动查询」注释；唯一约束显式命名、索引名交由 Django 自动生成（照 `0031` 范式）。`makemigrations --check` 退出码 0。
- **seq 并发安全**：`_append_entry_locked` 内 `ConvergenceSession.objects.select_for_update().get(pk=…)` 锁**父行**（不锁子表：`select_for_update` 对空结果集无可靠 gap lock），`_next_seq` 抽为**独立可打桩接缝**，整体包 `_SEQ_RETRY_ATTEMPTS + 1` 轮 `IntegrityError` 重试。重试时重新读 `max(seq)`，故兜底后 seq 仍无重复无空洞。
- **JSON 递归脱敏（T-113-01）**：`_redact_json` 对 dict 的**键与值**、list/tuple 元素递归，字符串叶子逐个过 `redact_secrets_in_text`，`int/float/bool/None` 原样返回。**未使用** `redact_secrets_in_text(json.dumps(...))` 再 `loads`。单点脱敏失败 **fail-closed 回落空串**（不回落原文）并记 warning。另加 `_truncate_content` 对超 32KB 的 content 置截断标记（T-113-03）。
- **BUS-02 waiter 数据面**：waiter 一律落 `kind="dependency_claim"` 行（key = `dependency:{from}->{pattern}`），**零触碰** `stage_state`（并行容器高频写 = 单行 JSON lost-update）。`register_waiter` 登记后**同步**跑 `adetect_wait_cycles`：从 `wait_key_pattern` 的 `repo:{id}.` 前缀解析被等仓建有向图（解析不出的跨仓契约边不入图），命中含自身的环即经 `BlueprintLifecycleService.open_thread(kind=ai_clarification, blocking=True, return_stage=session.current_stage)` 抛用户裁决并把该 waiter 置 `superseded`——**不靠超时兜底**（T-113-04）。
- **satisfy / expire 同事务（T-113-05）**：判定匹配与 `.update(status="superseded", updated_at=timezone.now())` 在同一 `transaction.atomic()` 内（`.update()` 绕过 `auto_now`，显式带 `updated_at`）；两者都**不 dispatch**，只返回待重派仓清单，重派归 113-04。二次调用同 key 恒返回 `[]`。
- **观测（T-113-06）**：条目读写 `category="sampling"`、waiter 登记/满足/超时 `category="caller"`，统一 `component="blueprint_context"`，全部带 `initiated_by_user_id`（缺省 `system`）与 `duration_ms`。**`content` 正文零进日志与事件 payload**，并有一条测试用 `structlog.testing.capture_logs` 逐字断言事件序列化后不含 content 任何字符串值。事件落库整段 `except Exception` 吞掉 + warning（异常文本先脱敏截断 500）。
- **event_taxonomy 纯追加**：三个 `blueprint.context.*` 常量在 `__all__` / 常量区 / `BLUEPRINT_EVENTS` 三处各加，`git diff | rg "^-"` 输出为空，`ALL_EVENTS` 与既有 15 个蓝图常量一字未动。

## Task Commits

| Task | Commit | 内容 |
| ---- | ------ | ---- |
| 1 | `42370654` | `BlueprintContextEntry` 模型 + barrel 导出 + `0032` migration（三复合索引 + seq 唯一约束） |
| 2 | `ba48afea` | `BlueprintContextService` 全量（append/read/register_waiter/adetect/satisfy/expire + 三纯函数）+ `event_taxonomy` 三常量纯追加 + 112 taxonomy 形状快照同步 |
| 3 | `80029587` | 21 例测试：确定性冲突重试 + 真线程并发 + 脱敏结构保真 + 环检测 + 幂等 satisfy + expire + fail-loud + 观测分类 |

## Files

- `server/delivery/models/blueprint_context_entry.py`（新建 113 行：四段模块 docstring 声明 append-only / 唯一 writer / content 已脱敏 / 不复用 ProjectMemory；两枚举 + 十三字段 + Meta 五件套 + `__str__`）
- `server/delivery/migrations/0032_blueprint_context_entry.py`（新建，Django 自动生成后仅经 `ruff check --fix` 排序 import）
- `server/delivery/services/blueprint_context_service.py`（新建 ~700 行：五段模块 docstring、五个模块常量、三个模块级纯函数 + 两个内部 helper、`BlueprintContextService` 六个公开 async 方法 + 五个 `@sync_to_async` 事务方法 + `_next_seq` 打桩接缝 + `_emit`）
- `server/delivery/models/__init__.py`（修改：barrel 追加三个符号 + `__all__` 同步，既有导出顺序未动）
- `server/delivery/services/event_taxonomy.py`（修改：纯追加三常量，零删除行）
- `server/tests/delivery/test_blueprint_context_seq.py`（新建 6 例：串行单调 / 确定性冲突重试 / 真线程并发 / 跨会话独立 / 唯一约束存在 / seq 非 AutoField）
- `server/tests/delivery/test_blueprint_context_service.py`（新建 15 例：脱敏保真 / 增量与叠加过滤 / 空结果与 limit 夹紧 / 三纯函数 / 无环不开线程 / 命中环开 blocking 线程带 return_stage / 无 artifact 仍报环 / satisfy 幂等 / satisfy 去重且不误伤 / expire / 非法入参 ×2 / 两条观测分类）
- `server/tests/delivery/test_blueprint_event_taxonomy_112.py`（修改：`BLUEPRINT_EVENTS` 形状快照 15 → 18 + 新增 `_NEW_113_EVENTS` 快照，既有 112/111 断言逐字未动）

## Decisions

- **`project` FK 取可空**：`ConvergenceSession` 无 `project` FK，本仓从 session 到 `Project` 只有 `conversation_id → Conversation.bound_project_id` 或 `work_item → ProjectWorkItemLink` 两条多跳 best-effort 链（见 `architect_merge_adapter._maybe_bind_plan_to_project`）。设成必填会让 `append_entry` 在最常见的容器上报路径上无从取值；改为可空 + 新增 `project_id=None` 可选 kwarg，调用方知道归属时传，不知道就留空，**绝不伪造归属**。113-06 沉淀侧仍需自己解析一次（已写入 affects）。
- **真并发用方案 ①（`ThreadPoolExecutor`）而非方案 ②（按 postgres 条件跳过）**：方案 ② 在默认 SQLite 套件里等于零覆盖。实测方案 ① 在 SQLite 上会真实抛 `database table is locked`——这本身就是「8 线程确实同时写同一表」的硬证据。故 worker 侧吸收该 `OperationalError` 并重投（重投重新读 `max(seq)`，不掩盖被测机制），并**反向断言重投次数 > 0**：将来若写入被悄悄串行化，这条断言先挂，用例不会退化成平凡通过。
- **环检测图只收「仓→仓」边**：`contract:{name}` 类 key 解析不出被等仓，该边不入图。理由：它不构成可判定的互等关系，强行入图会产生假环并误开澄清。
- **`register_waiter` 增 `artifact=None` kwarg**：`open_thread` 的第一参数是 `Artifact` 而非 session，而 PLAN 伪码未说 artifact 从哪来。落法：显式传优先，否则经 `session.current_artifact_version → ArtifactVersion.artifact` 解析；解析不到只记 warning 并返回 `thread_id=""`，但 `cycle_detected` 仍为真——**环的存在绝不因开不出线程而被吞掉**（有专门一例断言）。
- **`satisfy_waiters` / `expire_waiters` 增 `initiated_by_user_id` kwarg**：观测规范要求 `caller` 事件必须能回答「谁触发的」，PLAN 签名漏了该参数。缺省 `system`。

## Deviations from Plan

共 5 处：3 处为 PLAN 前提与本仓事实不符的修正，2 处为被既有守护测试逼出的必要调整。

**1. [Rule 3 - 前提不成立] `project` FK 由必填改可空，并新增 `append_entry(project_id=None)` 可选 kwarg**

- **Found during:** Task 1
- **Issue:** PLAN Task 1 要求 `project = ForeignKey("initiatives.Project", on_delete=CASCADE)` 必填，但 `append_entry` 签名里没有任何 project 入参，而 `ConvergenceSession` **没有** `project` 字段（`rg "initiatives.Project" server/delivery/models/` 零命中，全仓引用 Project 的模型都在 `initiatives/`）。必填 FK 会让唯一 writer 在主路径上无从取值 → 每次写入必抛。
- **Fix:** 字段保留（CONTEXT 字段清单含 project FK）但取 `null=True, blank=True`，字段注释写明「可空原因 + 沉淀侧再解析」；`append_entry` 增 `project_id=None` 可选 kwarg 供已知归属的调用方传值。
- **Files modified:** `server/delivery/models/blueprint_context_entry.py`、`server/delivery/services/blueprint_context_service.py`
- **Commit:** `42370654` / `ba48afea`

**2. [Rule 3 - 既有守护测试冲突] `test_blueprint_event_taxonomy_112.py` 的 `BLUEPRINT_EVENTS` 计数快照 15 → 18**

- **Found during:** Task 2
- **Issue:** 112-01 留下 `assert len(BLUEPRINT_EVENTS) == 15` 的形状快照，任何新增蓝图事件都会撞它。PLAN 允许 `event_taxonomy.py` 纯追加，但未预告这条快照。
- **Fix:** 追加 `_NEW_113_EVENTS` 三常量快照，计数改 18，另两处 declared 列表并入 113 三值。既有 112 的 11 常量与 111 的 4 常量断言逐字未动（守护强度未被削弱，仍是「逐值字面量 + 计数」双断言）。
- **Files modified:** `server/tests/delivery/test_blueprint_event_taxonomy_112.py`
- **Commit:** `ba48afea`

**3. [Rule 1 - 既有守护测试冲突] service 模块 docstring 触发 INV-6 grep 守护，改写措辞**

- **Found during:** Task 2
- **Issue:** `register_waiter` docstring 里写了字面量 ``BlueprintThread(kind=ai_clarification, blocking=True)``，被 `test_blueprint_inv6_guard._RE_INSTANTIATE`（`BlueprintThread\s*\(`）判为旁路实例化 → 该守护测试 fail。
- **Fix:** 改写为「经 `BlueprintLifecycleService.open_thread` 开一条 `ai_clarification` 阻塞线程」——语义不变且更准确（本 service 确实只经 lifecycle service 开线程，从不自己建线程行）。`test_blueprint_inv6_guard` 3 例全绿。
- **Files modified:** `server/delivery/services/blueprint_context_service.py`
- **Commit:** `ba48afea`

**4. [Rule 1 - 断言必然假绿] 测试凭证样本加长至满足 `SENSITIVE_VALUE_PATTERN` 的 ≥20 字符门槛**

- **Found during:** Task 3
- **Issue:** PLAN Task 3 给的样本 `friday_pat_abcdef1234567890`（前缀后 16 字符）与 `Bearer sk-XXXXXXXX` **都不会被 `redact_secrets_in_text` 命中**（`common/logging.py:36-44` 的正则要求 `friday_pat_[A-Za-z0-9_\-]{20,}` / `Bearer\s+[A-Za-z0-9._\-]{20,}`）。照抄会让「凭证已脱敏」断言在脱敏根本没发生时也通过——即断言恒真、零覆盖。
- **Fix:** 样本改为 `friday_pat_abcdefghij1234567890`（20 字符）与 `Bearer sk-0123456789abcdefghijklmn`，并加一条 `assert "***REDACTED***" in dumped` 正向确认替换真的发生过（不只是「原文不在」这种可被空串蒙对的弱断言）。
- **Files modified:** `server/tests/delivery/test_blueprint_context_service.py`
- **Commit:** `80029587`

**5. [Rule 3 - 范围外，未修] `ruff check delivery/` 报 4 条 I001，全在既有 Django 生成 migration**

- **Found during:** verification
- **Issue:** PLAN verification 要求 `ruff check delivery/` 通过，实跑报 4 错，全部是 `0026_clarification_questions.py` / `0027_artifact_...` / `0030_humantask.py` / `0031_blueprint_models.py` 的 import 未排序——Django `makemigrations` 生成风格，与本 plan 无关（本 plan 的 `0032` 已经 `ruff check --fix` 处理，自身通过）。
- **Fix:** 按「只修本 task 改动直接导致的问题」的范围纪律**不修**（改动既有 migration 属无收益扰动）。改以「本 plan 5 个新建/修改 py 文件 `ruff check` + `ruff format --check` 全通过」作为等价验收。
- **Files modified:** 无
- **Commit:** —

## 测试与验证

- `tests/delivery/test_blueprint_context_seq.py`：**6 passed**（串行 1..5 / 确定性冲突重试 / 8 路真线程并发 / 跨会话各自 1..3 / 唯一约束名存在 / seq 非 AutoField）
- `tests/delivery/test_blueprint_context_service.py`：**15 passed**
- **PLAN verification 全套**：`uv run pytest tests/delivery/ -q` → **620 passed**（既有 599 例零扰动）
- ⭐ **变异验证（证伪能力实测，非声明）**：临时把 `_SEQ_RETRY_ATTEMPTS + 1` 改成 `range(1)`（去掉重试）并把 `_redact_json` 的字符串分支改成原样返回 → `test_stale_next_seq_triggers_integrity_error_retry` 与 `test_content_credentials_redacted_without_breaking_json_shape` **双双 fail**（`UNIQUE constraint failed: …convergence_session_id, …seq`）；变异已回滚，`git diff` 干净。两条 ⭐ 用例确实能逮住防线失效。
- ⭐ **并发用例的真实性证据**：加重投逻辑之前，8 路 `ThreadPoolExecutor` 用例直接以 `OperationalError: database table is locked` 失败——SQLite 无行锁，该错只可能来自「多线程同时写同一表」，即并发**确实发生**（不是被 `thread_sensitive` 串行掉的假并发）。定稿版本保留该竞争并反向断言 `sum(retries) > 0`，一旦将来被串行化，用例先挂。
- `uv run python manage.py makemigrations --check --dry-run`：退出码 0
- `uv run python manage.py migrate delivery --plan`：`delivery.0032_blueprint_context_entry → Create model BlueprintContextEntry`（接在 0031 之后）
- 运行时验收：`BlueprintContextEntry._meta.db_table == "delivery_blueprint_context_entry"`；`rg -c "models.Index"` == 3；`rg "def [a-z]" | rg -v "__str__"` 零命中（模型层零业务方法）
- 冻结面自检：3 commit 触及 8 文件全在 `server/delivery/` 与 `server/tests/delivery/`；`repo_router_v2 / decompose_segments / research_adapter / architect_merge_adapter / merged_plan / clarify_adapter / render / resume / builtin_processes / blueprint_schema / blueprint_route / blueprint_confirm_gate / blueprint_resume / entrypoint / charter_service / settings_service / knowledge_tools` **零命中**；`git diff --name-only | rg "^web/"` 零命中
- 受限面自检：`git diff HEAD~3 HEAD -- server/delivery/services/event_taxonomy.py | rg "^-" | rg -v "^---"` 输出为空（纯追加）；`rg -n "BLUEPRINT_CONTEXT" event_taxonomy.py | rg "ALL_EVENTS"` 零命中
- 观测面自检：`category="sampling"` ×7、`category="caller"` ×7、全部带 `component="blueprint_context"`；`rg -n "content=" blueprint_context_service.py | rg "logger\.|payload"` 零命中（content 不进日志/事件）
- 代码风格：本 plan 5 个 py 文件全部经 `uv run ruff format` + `uv run ruff check --fix`，All checks passed

## Self-Check: PASSED

- 文件存在：8 个 key-files 全部命中（5 新建 + 3 修改）
- commit 存在：`42370654` / `ba48afea` / `80029587` 均在 `git log`
- artifacts contains 断言：`uq_blueprint_context_session_seq` ∈ 模型 + migration 两文件 ✓；`0031_blueprint_models` ∈ `0032` ✓；`_redact_json` ∈ service ✓；`transaction=True` ∈ seq 测试 ✓
- key_links 断言：`redact_secrets_in_text` ∈ service（`_redact_json` 递归叶子调用）✓；`select_for_update` ∈ service（锁父 `ConvergenceSession` 行）✓；`open_thread` ∈ service（环检测命中开 blocking 线程）✓

## Next Phase Readiness

- **113-02（容器 MCP view）**：`read_entries` / `append_entry` 签名与返回形状见 provides；`read_entries` 恒返回 list 且 `id`/`created_at` 已转 str，可直接进 MCP 响应体无需二次序列化。view 层仍须自建三道会话校验（CONTEXT 锁定，本 plan 不含任何鉴权逻辑）。
- **113-04（等待原语与重派）**：`satisfy_waiters` / `expire_waiters` 返回的仓 id 清单即重派输入；两者都**不 dispatch**，重派与 barrier 续驱由 113-04 负责；超时清理请调 `expire_waiters(max_age_seconds=…)`，不要新起定时任务。
- **113-06（distill 沉淀）**：按 `kind ∈ {decision, contract, api_surface}` + `status="active"` 过滤；⚠️ `project` 可空，沉淀侧需自行 best-effort 反查 project 并在解析不到时跳过（不伪造 `proposed_by`）。
- **115（时间线）**：三个 `blueprint.context.*` 事件已在 `BLUEPRINT_EVENTS`，payload 键见 provides；`waiter_registered` 的 `from_repository_id` + `to_key` + `cycle_detected` 即「谁在等谁」的完整可视化数据。
- **给后续 writer 的硬约束**：本 service 是 `BlueprintContextEntry` 的唯一 writer（INV-6）。新增写入点请加方法而不要裸 ORM；新增 `content` 来源必须经 `_redact_json`（勿改成先 `json.dumps` 再脱敏）。
