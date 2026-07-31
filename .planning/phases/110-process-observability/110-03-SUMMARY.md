---
phase: 110-process-observability
plan: 03
subsystem: api
tags: [runtime-snapshot, convergence-session, plan-research, redaction, observability, polling]

# Dependency graph
requires:
  - phase: 110-01
    provides: "`process_event_wire` 的 `sanitize_process_event_payload` / `compress_failure_reason`——快照侧**共用**这把筛子，不另写第二份净化"
  - phase: 109-plan-trust-spine
    provides: "`ConvergenceSession.conversation_id` 由 `start_orchestration` 服务端写入，是本 plan 归属链的第一环"
provides:
  - "`runtime[\"orchestration\"]`：编排阶段指针 + 事件流 + 失败闭集（research → merge 后半程的**唯一**进度来源）"
  - "`runtime[\"plan_research_sessions\"]`：按仓一条的调研容器日志，带服务端解析的仓库名、已脱敏"
  - "`orch_session` 预置 + 显式判空的分支协作范式（共享变量绝不留 UnboundLocalError 暗路）"
affects: [110-04 前端 store 消费, 110-05 时间线组件, 110-07 按 plan_session_id 过滤气泡]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "半可信 id 进 ORM 前先过 UUID 过筛（109-REVIEW MN-03 同款）"
    - "跨 try 共享的变量在所有 try 之外预置 None，各支显式判空早退"
    - "写入侧不脱敏的日志，在**读取面**补 `redact_secrets_in_text`"

key-files:
  created:
    - server/tests/test_conversation_runtime_orchestration.py
  modified:
    - server/chat/conversation_service.py

key-decisions:
  - "事件取 201 条判截断、保留最新 200 条再反转为升序——保留最旧会让时间线永远停在早期阶段"
  - "`failure` 只有 `stage` + `reason_code` 两个键，分支内不存在对 error.message/exception/report 的读取点"
  - "归属链走 `ConvergenceSession.conversation_id` + `last_output.plan_session_id`，并以 `source` 交叉校验 fail-closed"
  - "边界用例改为 200（不截断）/ 201（截断）——plan 原文写的「249 条 ⇒ 不截断」与同一 task 定义的 200 上界自相矛盾"

patterns-established:
  - "运行时快照的新分支各自独立 try/except，失败只降级自己的字段，绝不反噬 2s 轮询端点"
  - "降级路径的**日志缺席**本身是断言对象：早退不打 warning，打了就说明走的是被吞掉的异常"

requirements-completed: [OBS-01, OBS-02, OBS-03]

# Metrics
duration: 38min
completed: 2026-07-31
---

# Phase 110 Plan 03: 运行时快照的编排进度与调研日志 Summary

**给 `get_conversation_runtime` 加了两个物理隔离的新分支：`orchestration` 让刷新 / 重连后编排时间线可完整还原，`plan_research_sessions` 让调研容器日志走出「读取时被谓词过滤掉」的坑——日志本来就在库里，缺的只是一条正确的归属链。**

## Performance

- **Duration:** 38 min
- **Tasks:** 3/3
- **Files created:** 1
- **Files modified:** 1
- **新增用例:** 24 条

## Accomplishments

- **编排后半程终于有了进度源。** 110-01 的 SSE 只覆盖 `decompose → clarify` 五个阶段；`research → merge` 的容器回调续驱不在任何 graph 运行上下文内、没有流可推。这条 2s 轮询快照不是兜底，是后半程**唯一**的投递通道。快照带 8 个键：`session_id` / `status` / `current_stage` / `has_classify` / `segment_count` / `failure` / `events` / `events_truncated`。
- **截断方向做对了，并且有能证明它做对的用例。** 取最新 200 条再反转为升序。只断言「长度 200 + truncated=true」的话，保留最旧的错误实现同样会通过——所以用例同时断言首尾两条事件名（`events[0] == "evt-50"` 且 `events[-1] == "evt-249"`）。
- **`ts` 的跨链不变量第一次被真正守住。** 快照写的是 `row.ts.isoformat()`，与 110-01 fan-out 逐字符同源。两条用例分别站在两个位置上看这件事：一条比对「快照 ts == 落库行 ts」，另一条比对「**内存实例** 与 **DB 回读实例** 的 `isoformat()`」——后者才是隔着一次数据库往返的那个不变量，此前没有任何用例站在跨链位置上看过它。负向对照证实这两条守的是不同的点（把 `.isoformat()` 换成 `str()` 时只有前者变红）。
- **OBS-02 的根因确认是读取谓词。** deep analysis 那一支要求 `task_type == EXPLORE` 且 `source == "chat_deep_analysis"`，而 plan_research 是 `TaskType.PLAN` + `source == "plan_research"`，双重不匹配；日志早就由 `_append_runtime_log` 写进 `last_output.logs`。新分支用三重谓词取回它们，按仓一条、按 id 升序。
- **F-5 的静默陷阱被用例钉死。** plan_research 的 `AgentSession.metadata` 只有 `{source, plan_session_id}`，照抄 deep analysis 的 `main_session__metadata__conversation_id` 会得到一个恒空且不报错的查询集。负向对照实测：换成那个谓词，7 条 plan_research 用例**全红**。
- **原始异常文本在渲染路径上根本不存在。** `failure` 只有 `stage` 与 `reason_code`（闭集）。泄漏面用例对整段 `json.dumps(runtime["orchestration"])` 同时断言三个键名与两个值片段都不出现——只断言键名会漏掉「换个键名塞出去」的实现。

## Task Commits

1. **Task 1: orchestration 快照分支** — `818bec15` (feat)
2. **Task 2: plan_research_sessions 独立分支** — `5189c76b` (feat)
3. **Task 3: 两个分支的用例** — `c7f1865a` (test)

## Files Created/Modified

- `server/chat/conversation_service.py` — `get_conversation_runtime` 内新增两段独立分支（+231 行，含解释性注释）。`runtime` 字面量预置 `"orchestration": None` 与 `"plan_research_sessions": []`，保证任何降级路径下键恒存在、类型恒定。
- `server/tests/test_conversation_runtime_orchestration.py` — 24 条：形状 5、事件与 ts 6、失败闭集与泄漏面 4、归属与脱敏 7、分支隔离 2。

## Decisions Made

- **共享变量 `orch_session` 在两个 `try` 之外预置 `None`，两支各自显式判空。** 不预置的话，orchestration 分支的 `try` 在赋值**之前**抛（`conv_uuid` 解析 / DB 连接 / 查询本身出错）会让 plan_research 分支撞 `UnboundLocalError` → 被它自己的 `except` 吞掉 → 静默降级成空数组。那个症状与「后端根本没写日志」**逐字相同**，正是本 plan 要根除的失败形状。
- **「降级时不打日志」本身成了断言对象。** 上面那条不变量的观测抓手不好找：预置与不预置，`plan_research_sessions` 最终都是 `[]`，值上分不出来。区别在于**路径**：早退不打 warning，`UnboundLocalError` 被吞会打。所以用例 patch 了 `logger.warning` 并断言 `conversation_runtime_plan_research_failed` **不在**日志事件列表里。负向对照的输出里能直接看到那条 `UnboundLocalError` 的 traceback。
- **两个分支复用同一个 `ConvergenceSession` 实例但**不合并** `try`。** orchestration 分支自己发一次查询（不复用 `pending_plan_clarification` 那次），plan_research 复用 orchestration 取到的实例。分支隔离用例用「只掐事件查询」与「只掐第二次会话查询」两种粒度分别验证三段 `try` 没有被合并——无差别抛错会让合并的错误实现也碰巧看起来正确。
- **`repository_name` 必须后端解析。** 前端的 `repoNames` 只覆盖当前用户可见仓，跨组仓在前端解析不出名字（UI-SPEC 后端契约要求 #7）。收集到的 `repository_id` 先过 UUID 过筛再一次批量查——`repository_id` 来自容器可写的 `last_output`，是半可信值，`filter(id__in=['not-a-uuid'])` 会抛 `ValidationError`。解析不出留空串，**不回填 UUID 串**。
- **不动 `runtime["active"]` 的语义。** 编排在途期间 `OrchestrationRun` 停在 `WAITING` ⇒ `active` 为 true ⇒ 前端持续轮询。终态那一拍 `active` 变 false、而前端现有代码只在 `active === true` 时才 `applyRuntimeSnapshot`——终态的 `orchestration` 因此到不了 store。**这一半的修复属于 110-04**（`applyOrchestrationRuntime` 要在两个分支上都调用）。把「这条对话还在跑吗」和「时间线还要不要更新」混起来会污染既有的 deep analysis / coding 判定。

## 可观测性自检（`.cursor/rules/observability-logging.mdc`）

| 检查项 | 结论 |
|---|---|
| 结构化事件 + kv | 两条新 warning 走 `conversation_runtime_orchestration_failed` / `conversation_runtime_plan_research_failed`，字段全 kv |
| `category` / `component` | 两条均 `category="sampling"` + `component="chat.conversation"` |
| 高频循环禁 INFO | ✅ 两个分支的正常路径**零日志**。`rg -c 'logger\.info' chat/conversation_service.py` 改动前后同为 **14**（`git show HEAD~3:` 核对） |
| 脱敏不可绕过 | 事件 payload 过 `sanitize_process_event_payload`；容器日志 `content` 过 `redact_secrets_in_text`；`failure.reason_code` 过 `compress_failure_reason` 压 7 值闭集 |
| 触发用户绑定 | 未改动上下文注入：runtime 是 REST 入口，`user_id` / `request_id` 由既有中间件注入 |
| 观测不反噬业务 | 两个分支各自 `try/except`，失败只降级自己的字段；两条分支隔离用例证明三段 `try` 未合并 |
| 新增请求入口 / LLM 调用 / 召回 / 队列 / webhook | 无（复用既有 `GET /api/chat/conversations/{id}/runtime/`，QPS / 时长 / 错误率已由既有请求指标中间件覆盖；无新 `call_source`） |

## Deviations from Plan

### 1. [Rule 1 - Bug] 截断边界用例的条数改为 200 / 201

- **Found during:** Task 3
- **Issue:** plan 的 Task 3 写「249 条 ⇒ `events_truncated is False`（边界）」，但同一个 task 定义的上界是 **200**。249 > 200 必然截断，照写必红（实测 `assert 200 == 249`）。这是 plan 内部的算术不自洽，不是实现问题。
- **Fix:** 改为两条覆盖真实边界的用例——`test_exactly_at_limit_is_not_truncated`（恰好 200 ⇒ 全量、`truncated=False`，守住「多取一条只为判定，不该把刚好满误判成截断」）与 `test_one_over_limit_truncates_the_oldest`（201 ⇒ 截断且丢掉的是最旧的 `evt-0`）。边界覆盖比 plan 原文更严（原文只有下沿一条）。
- **Files modified:** `server/tests/test_conversation_runtime_orchestration.py`
- **Commit:** `c7f1865a`

### 2. [Rule 1 - Bug] 泄漏面用例的键名断言改为带引号比对

- **Found during:** Task 3
- **Issue:** `assert "exception" not in json.dumps(orch)` 会被闭集取值 `"stage_exception"` 自身子串命中，产生假阳性（实测首轮红）。
- **Fix:** 改为 `assert f'"{leaked_key}"' not in blob`——按 JSON 键名形态比对。值片段断言（`上游 500` / `自由文本`）原样保留，两类断言仍都在，负向对照证实注入 `error.message` 时该用例照样变红。
- **Files modified:** `server/tests/test_conversation_runtime_orchestration.py`
- **Commit:** `c7f1865a`

其余逐条按 plan 执行，无偏离。

## Verification

### 测试

| 命令 | 结果 |
|---|---|
| `pytest tests/test_conversation_runtime_orchestration.py -q` | **24 passed** |
| `pytest tests/test_conversation_runtime_orchestration.py tests/test_conversation_runtime.py tests/delivery/ -q` | **573 passed** |
| 基线：`pytest tests/chat tests/agents tests/services tests/delivery tests/mcp_tools tests/knowledge tests/codegraph tests/workflows tests/test_conversation_runtime.py tests/test_conversation_runtime_orchestration.py -q`（排除三个沙箱环境失败文件） | **3597 passed, 21 skipped** |

基线核对：110-01 记录的 8 目录基线为 **3555 passed**；本次多带的两个根级文件为既有 18 + 新增 24 = 42 条，3555 + 42 = **3597**，**零回归**。

排除的三个文件为本机文件系统沙箱禁止在临时目录 `git init` 所致的环境失败，与本 phase 无关：`tests/services/test_commit_index.py`、`tests/services/test_commit_index_integration.py`、`tests/mcp_tools/test_grep_repository.py`。

**查询预算**：既有的 `test_runtime_coding_plan_query_budget_no_n_plus_1`（断言 3 session 场景下总 SQL ≤ 12）**依旧全绿**——2s 轮询面未被新分支拖垮。无编排会话时两个新分支合计 +1 次查询（一次 `ConvergenceSession.afirst()`，plan_research 走判空早退零查询）；有编排会话时 +3（会话 / 事件 / 一次批量取仓名，无 per-session N+1）。

### 迁移与依赖

- `python manage.py makemigrations --check --dry-run` → **No changes detected**（退出码 0）。
- `git diff --exit-code server/uv.lock server/pyproject.toml` → **退出码 0**，零新增依赖。T-110-03-SC 缓解成立。

### Lint

- `ruff check chat/conversation_service.py tests/test_conversation_runtime_orchestration.py` → **All checks passed**。
- `ruff format` → 新建的测试文件已格式化通过。`chat/conversation_service.py` 的格式化状态未被本 plan 改变（仓内未强制 `ruff format`，见 110-01 同一条记录）。

## 负向对照（全部执行并还原）

| # | 破坏方式 | 实际变红的测试 | 结果 |
|---|---|---|---|
| 1 | `order_by("-ts","-created_at")` → `order_by("ts","created_at")`（保留最旧） | `test_truncation_keeps_newest_not_oldest` + `test_exactly_at_limit_is_not_truncated` + `test_one_over_limit_truncates_the_oldest` | ✅ 3 failed |
| 2 | `row.ts.isoformat()` → `str(row.ts)` | `test_snapshot_ts_is_isoformat_of_the_persisted_row`（**DB 往返那条依旧全绿**，印证两条守的是不同的点） | ✅ 1 failed / 1 passed |
| 3 | `failure` 顺手带上 `error.get("message")` | `test_stage_exception_shape_leaks_nothing` | ✅ 1 failed / 3 passed |
| 4 | 删掉 `last_output__source="plan_research"` | `test_source_mismatch_is_rejected_by_cross_check` | ✅ 1 failed / 6 passed |
| 5 | 归属谓词换成 `main_session__metadata__conversation_id`（F-5 陷阱） | `TestPlanResearchSessions` **全部 7 条** | ✅ 7 failed |
| 6 | `redact_secrets_in_text(content)` → `content` | `test_log_content_is_redacted_on_the_wire` | ✅ 1 failed / 6 passed |
| 7 | 三段合并进同一个 `try`（模拟：orchestration 的 `except` 连坐另两个字段） | `test_event_query_failure_only_degrades_orchestration` | ✅ 1 failed / 1 passed |
| 8 | 删掉 `orch_session: Any = None` 预置 | `test_session_query_failure_degrades_both_fields_independently`——日志里可直接看到 `UnboundLocalError: cannot access local variable 'orch_session'` 的 traceback | ✅ 1 failed / 1 passed |

还原后复跑 24 passed；`rg 'NEGATIVE CONTROL' server/` 零命中，`git diff` 确认源码与提交态逐字一致。

**粒度**：对照 7 与对照 8 分别只掐**事件查询**与**第二次会话查询**（前者发生在 `orch_session` 赋值之后、后者之前），而不是让整个函数抛错——无差别抛错会让「三段合并」的错误实现也碰巧看起来正确（109-REVIEW MN-02 同款要求）。

## Issues Encountered

- 首轮两条用例红，均为**用例自身**的缺陷而非实现缺陷（见 Deviations 两条）：截断边界条数与 plan 的 200 上界自相矛盾；泄漏面键名断言被 `"stage_exception"` 子串误命中。
- ruff I001：测试内的函数级导入未排序，已修正。

## Threat Flags

无。本 plan 未引入新端点 / 鉴权路径 / 文件访问模式 / 信任边界上的 schema 变更；`threat_model` 的 6 条 disposition 全部落地：

| Threat ID | 落地形态 |
|---|---|
| T-110-03-01 | `compress_failure_reason` 闭集 + `sanitize_process_event_payload`；泄漏面用例双断言（对照 3 证实） |
| T-110-03-02 | 出网前 `redact_secrets_in_text`（对照 6 证实） |
| T-110-03-03 | `conversation_id`（服务端 DB 列）+ `source` 双条件；两条独立归属用例（对照 4/5 证实） |
| T-110-03-04 | UUID 过筛后再进 ORM；`"not-a-uuid"` 用例覆盖 |
| T-110-03-05 | 两分支各自 `try/except` + 事件上界 200 + 单次批量取仓名；查询预算用例仍绿（对照 7 证实隔离） |
| T-110-03-06 | 正常路径零日志、仅异常 warning + `category="sampling"`；`logger.info` 计数走查前后同为 14 |
| T-110-03-SC | 零新增依赖，`git diff --exit-code` 退出码 0 |

## Known Stubs

无。

## Next Phase Readiness

- **110-04（前端 store）** 可直接消费两个新字段。🔴 **必须注意**：`runtime["active"]` 在编排终态那一拍变 false，而现有 `pollConversationRuntime` 只在 `active === true` 时才 `applyRuntimeSnapshot` ⇒ 终态的 `orchestration`（`done` / `failed` + reason_code）会到不了 store。本 plan **刻意不改** `active` 的语义去迁就它（那会污染既有 deep analysis / coding 判定），修复点在前端：`applyOrchestrationRuntime` 要在 `active` 的两个分支上都调用。
- **110-07** 需要的 `plan_session_id` 已按仓逐条携带，可直接按气泡过滤。
- **去重键的后端侧已就位**：SSE 与快照两条链的 `ts` 逐字符同源、payload 过同一把筛子。前端按 `(event, ts, repo_id/task_id)` 去重即可。
- **`events` 上界 200 与容器日志上界 80**（`_MAX_RUNTIME_LOGS`）都不给用户提示（UI-SPEC Backstop #5 / Unresolved #10 既定裁定）。

## Self-Check: PASSED

- `server/tests/test_conversation_runtime_orchestration.py` 存在于磁盘；`server/chat/conversation_service.py` 含 `plan_research_sessions` 与 `events_truncated` 两个 `contains` 断言字面量。
- 三个 task commit（`818bec15` / `5189c76b` / `c7f1865a`）均可在 `git log` 中检索到。

---
*Phase: 110-process-observability*
*Completed: 2026-07-31*
