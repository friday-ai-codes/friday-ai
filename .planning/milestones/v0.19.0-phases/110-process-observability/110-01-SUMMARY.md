---
phase: 110-process-observability
plan: 01
subsystem: api
tags: [sse, langgraph, structlog, observability, redaction, convergence-session]

# Dependency graph
requires:
  - phase: 107-routing-transparency
    provides: 出网净化与「原始文本只入留痕面」的既有裁定（Unresolved #4），本 plan 逐字沿用
  - phase: 109-plan-trust-spine
    provides: chat SSE 生成器内的触发用户重绑（_stream_events），本 plan 未触碰
provides:
  - SSE 事件类型 `process_event`（编排事件的统一信封出网通道）
  - `_emit_event` 内的单一 fan-out 出口（7 个 stage handler 与 6 个 adapter emit 点零改动即获得推送）
  - `process_event_wire`：SSE 与运行时快照共用的出网净化筛子 + 失败原因 7 值闭集
  - `_persist_event` 返回落库行，信封 `ts` 由该行回填（前端去重键成立的前提）
affects: [110-02 运行时快照, 110-03 前端事件消费, 110-04 阶段时间线]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "出网净化三层：恒剥离键表 / 按值类型剥离 / 残留字符串脱敏截断"
    - "取不到 langgraph stream writer 即视为「没有推送目标」，无需自建注册表或透传 writer"
    - "落库行是权威时间源，出网信封的 ts 一律由它回填"

key-files:
  created:
    - server/delivery/services/process_event_wire.py
    - server/tests/delivery/test_process_event_wire.py
    - server/tests/delivery/test_process_event_fanout.py
  modified:
    - server/agents/core/events.py
    - server/delivery/services/convergence_session_service.py
    - server/tests/test_sse_event_contract.py

key-decisions:
  - "`summary` 按值类型区分而非按键名一刀切：classify 的结构化 dict 保留，research 的自由文本 str 剥离"
  - "fan-out 外层用 blanket `except Exception`：`get_stream_writer()` 除 RuntimeError 外还会抛 KeyError"
  - "落库失败即不 fan-out：没有权威 ts 的事件推出去是无法去重也无法补齐的孤儿事件"
  - "取不到 writer 不打日志——那是 workflow / MCP / 回调续驱三种入口的正常态"

patterns-established:
  - "出网面与留痕面分离：事件表存原文供 superuser 排障，渲染路径上只存在净化后的形状"
  - "失败原因服务端压成闭集枚举，原始异常文本永不出网"

requirements-completed: [OBS-01]

# Metrics
duration: 42min
completed: 2026-07-31
---

# Phase 110 Plan 01: 编排事件桥接到 chat SSE Summary

**把只写不读的 `ConvergenceSessionEvent` 接上 chat SSE：新增 `process_event` 事件类型，在 `_emit_event` 的持久化之后做 best-effort fan-out，出网信封的 `ts` 由落库行回填，并建立一把 SSE 与运行时快照共用的净化筛子。**

## Performance

- **Duration:** 42 min
- **Tasks:** 2/2
- **Files created:** 3
- **Files modified:** 3
- **新增用例:** 55 条（净化 46 + fan-out 9）

## Accomplishments

- **桥搭出来了**：编排的领域事件与阶段转移事件，在 chat 入口下都会以 `process_event` 推给前端，承载 `{event, session_id, work_item_id, ts, payload}` 原样信封。
- **单一出口**：fan-out 挂在 `_emit_event`（INV-6），7 个 stage handler 与 6 个 adapter emit 点**一行未改**即自动获得推送。用真实 `transition()` 的端到端用例锁住了这一条，而不只是直接调 `_emit_event`。
- **ts 对齐**：`_persist_event` 改为返回落库行，信封 `ts` 由 `row.ts.isoformat()` 覆盖 `build_envelope()` 自取的那个瞬时值。不做这一步，前端按 `(event, ts, …)` 去重时 SSE 那条与快照那条会算成两条不同事件，调研完成数 / 融合轮次 / 澄清轮次会成倍虚高——且症状看起来像前端算错了。
- **自由文本在服务端就消失**：`question` / `message` / `exception` / `report` / `reasons` / `candidate_files` / `api_contracts_exposed` / `stage0` / `stage1` / `weight_config` / `repo_meta` / `unclarified_points` 恒剥离；字符串形态的 `summary` / `error` / `detail` 按值类型剥离；残留字符串过 `redact_secrets_in_text` 并截断到 200 字符。
- **绝不反噬编排**：writer 不可用的两种形态、writer 自身抛错、落库失败，四种情形下 `_emit_event` 都不抛、不阻断，各有用例。

## Task Commits

1. **Task 1: 出网净化筛子 + 失败原因闭集** — `5fb9947c` (feat)
2. **Task 2: SSE 事件类型 + `_emit_event` 内的 fan-out** — `78a46ae3` (feat)

## Files Created/Modified

- `server/delivery/services/process_event_wire.py` — 出网净化的**唯一面**：`sanitize_process_event_payload` 三层筛子 + `compress_failure_reason` 7 值闭集。SSE 与 110-02 的运行时快照两条链共用同一把筛子——这是前端去重能成立的前提。
- `server/delivery/services/convergence_session_service.py` — `_emit_event` 在持久化后追加 `_fanout_process_event`；`_persist_event` 返回类型由 `None` 改为 `ConvergenceSessionEvent`。
- `server/agents/core/events.py` — 新增 `PROCESS_EVENT` 常量并入 `ALL_EVENT_TYPES`。
- `server/tests/test_sse_event_contract.py` — 契约由 21 种改为 22 种，新增 `test_process_event_constant`。
- `server/tests/delivery/test_process_event_wire.py` — 46 条：逐事件形状、同名不同义成对断言、遍历 `ALL_EVENTS` 的全事件守护、未知事件凭据兜底、闭集性。
- `server/tests/delivery/test_process_event_fanout.py` — 9 条：推送成立、ts 对齐、净化生效与留痕原文、四种不反噬情形、真实 `transition()` 端到端。

## Decisions Made

- **`_DROP_IF_STR` 与 `_ALWAYS_DROP` 是两个分开的集合。** `technical_plan.feature.classified` 的 `summary` 是结构化 dict `{new, modify, unclear}`，是「功能点分类」那一步摘要的**唯一**来源；`repo.research.completed` 的 `summary` 是容器产出的自由文本。同名不同义，按值类型区分是唯一不误伤的判据。用例里这一对是成对存在的。
- **净化的作用深度是有界的**：顶层键 + `list[dict]` 元素内的一层做键剥离，字符串兜底再多下探一层。不做无限递归——payload 是受控结构，无限递归只带来性能与栈深度的不确定性。dict 型值内部**只做字符串兜底、不做键剥离**，否则 classify 的 `summary` 与路由候选的 `breakdown` 会被同名键误伤。
- **fan-out 外层必须是 blanket `except Exception`。** `get_stream_writer()` 的实现是 `get_config()[CONF][CONFIG_KEY_RUNTIME]`：「压根没有 runnable context」抛 `RuntimeError`，「有 runnable context 但不是 langgraph runtime」抛 `KeyError`。收紧成 `except RuntimeError` 会让后一条路径把异常放出去、直接打断编排主流程——负向对照证实了只有 `KeyError` 那条用例会变红。
- **取不到 writer 不打任何日志。** workflow / MCP 入口与容器回调续驱三种情形都取不到，那是正常态；为正常路径打日志等于刷噪音。

## 可观测性自检（`.cursor/rules/observability-logging.mdc`）

| 检查项 | 结论 |
|---|---|
| 结构化事件 + kv | `process_event_fanout` 走 `logger.debug`，字段 `event_name` / `session_id` / `conversation_id` 全为 kv |
| `category` / `component` | `category="sampling"`（高频路径）+ `component="convergence_session_service"` |
| 高频循环禁 INFO | ✅ `rg -c 'logger\.info' convergence_session_service.py` 改动前后同为 **3**，且位置未变 |
| 脱敏不可绕过 | 出网前过 `sanitize_process_event_payload`，残留 str 过 `redact_secrets_in_text`；失败原因压成闭集，`message`/`exception`/`report` 永不出网 |
| 触发用户绑定 | 未改动上下文注入：`_emit_event` 沿用调用方 contextvars（chat 入口经中间件、超时命令经 `bound_contextvars(initiated_by_user_id=…)`） |
| 观测不反噬业务 | fan-out 整体 `try/except Exception: pass`，四种失败形态各有用例 |
| 新增 LLM 调用 / 请求入口 / 召回 / 队列 / webhook | 无 |

## Deviations from Plan

None — 计划逐条执行。以下两处是计划**已写明**的处置，非偏离：

- `_emit_event` 既有那行 `logger.info("convergence_session_event", …)` 形式上是「每事件一行 INFO」，违反高频路径纪律。按 `<assumptions>` #1 **不动**（pre-existing，且可能有既有用例依赖），本 plan 的义务是不再加第二行。**记为已接受债务**，供后续统一降级为 debug 时一并处置。
- 前端 `web/src/types/chat.ts` 的 `SSEEvent.type` 联合类型未同步加 `process_event`，按 `<assumptions>` #2 留给 110-03 与消费同批落地。后端契约测试只比对后端常量集，不会因此变红；已在 `EXPECTED_EVENT_TYPES` 旁留注释指明前端那半边的落点。

## Verification

### 测试

| 命令 | 结果 |
|---|---|
| `pytest tests/delivery/test_process_event_wire.py -q` | **46 passed** |
| `pytest tests/delivery/test_process_event_fanout.py tests/test_sse_event_contract.py -q` | **23 passed** |
| `pytest tests/delivery/ tests/test_sse_event_contract.py -q` | **545 passed** |
| `pytest tests/ -k "convergence or process_runtime or event_taxonomy" -q` | **54 passed**, 8237 deselected |
| 基线：`pytest tests/chat tests/agents tests/services tests/delivery tests/mcp_tools tests/knowledge tests/codegraph tests/workflows -q`（排除三个沙箱环境失败文件） | **3555 passed, 21 skipped** —— 基线 3500 + 本 plan 新增 55，**零回归** |

排除的三个文件为本机文件系统沙箱禁止在临时目录 `git init` 所致的环境失败，与本 phase 无关：`tests/services/test_commit_index.py`、`tests/services/test_commit_index_integration.py`、`tests/mcp_tools/test_grep_repository.py`。

### 迁移与依赖

- `python manage.py makemigrations --check --dry-run` → **No changes detected**（退出码 0，本 plan 无模型字段变更）。
- `git diff --exit-code server/uv.lock server/pyproject.toml` → **退出码 0**，零新增依赖（`langgraph` 早在依赖内，`get_stream_writer` 是其既有公开 API）。T-110-01-SC 缓解成立。

### Lint

- `ruff check delivery/services/ agents/core/events.py tests/delivery/` → **All checks passed**。
- `ruff format --check`：两个新建文件已格式化。`agents/core/events.py` / `convergence_session_service.py` / `tests/test_sse_event_contract.py` 报 would-reformat 属 **pre-existing**（已用 `git show HEAD:<file> | ruff format --check -` 逐个核实改动前即未格式化；`tests/delivery/` 下 58 个文件里有 28 个同样如此，仓内并未强制 `ruff format`）。本 plan 未新增格式漂移。

## 负向对照（全部执行并还原）

| 破坏方式 | 实际变红的测试 | 结果 |
|---|---|---|
| 删掉 `envelope["ts"] = row.ts.isoformat()` | `test_pushed_ts_is_identical_to_persisted_ts` | ✅ 1 failed / 8 passed |
| `_DROP_IF_STR` 并进 `_ALWAYS_DROP`（`summary` 一刀切） | `test_classified_structured_summary_is_kept` | ✅ 1 failed / 45 passed |
| 从 `_ALWAYS_DROP` 删掉 `question` | `test_clarification_asked_question_is_stripped` **+ 全事件守护 15 个参数全红** | ✅ 16 failed |
| 移除 `conversation_id` 为空的早退 | `test_missing_conversation_id_skips_push_but_still_persists` | ✅ 1 failed / 8 passed |
| 外层 `except Exception` 收紧成 `except RuntimeError` | `test_get_stream_writer_key_error_is_swallowed`（**`RuntimeError` 那条依旧全绿**，印证两条必须都写）+ `test_writer_raising_does_not_break_emit` | ✅ 2 failed / 7 passed |
| 落库失败也推（去掉 `row is not None` 前置） | `test_persist_failure_skips_fanout` | ✅ 1 failed / 8 passed |

还原后复跑三个文件共 **69 passed**；`rg 'NEGATIVE CONTROL' server/` 零命中，`git status` 确认源码与提交态逐字一致。

**粒度**：writer 相关用例让 writer **只在被调用时**抛错（`_WriterSpy(raises=…)`），而不是让整个 `_emit_event` 抛错——无差别抛错会让「fan-out 根本没接上」的实现也碰巧通过断言（109-REVIEW MN-02 同款要求）。

## Issues Encountered

- 新增的模块级 `from agents.core.events import PROCESS_EVENT` 触发 ruff I001（导入未排序），已把它移到 `delivery.models` 之前修正。无循环导入（`agents/core/events.py` 只依赖 stdlib）。

## Threat Flags

无。本 plan 未引入新的网络端点、鉴权路径、文件访问模式或信任边界上的 schema 变更；`threat_model` 的 5 条 disposition 全部落地（净化 + 全事件守护用例 / fan-out 吞异常 + 负向对照 / writer 只能拿到当前 graph 运行的推送目标 / debug + 零新增 INFO 走查 / 零新增依赖并 diff 校验）。

## Known Stubs

无。

## Next Phase Readiness

- **110-02（运行时快照）** 可直接 `from delivery.services.process_event_wire import sanitize_process_event_payload, compress_failure_reason`——两条出网链共用同一把筛子是设计前提，快照侧**不要**另写一份净化。快照的 `events` 上界截断必须保留**最新** N 条并置 `events_truncated`（UI-SPEC 后端契约要求 #3）。
- **110-03（前端消费）** 需同步 `web/src/types/chat.ts` 的 `SSEEvent.type` 联合类型加 `process_event`，并按 `(event, ts, repo_id/task_id)` 去重——ts 对齐已在后端保证。
- **传输分工是既定事实**：`process_event` 只覆盖 `decompose → clarify` 五个阶段的秒级直播；`research → merge` 由 110-02 的 2s 运行时快照轮询覆盖（容器回调续驱不在任何 graph 运行上下文内，没有流可推）。前端时间线**不得**依赖 SSE 覆盖后半程。

## Self-Check: PASSED

三个新建文件与本 SUMMARY 均存在于磁盘；两个 task commit（`5fb9947c` / `78a46ae3`）均可在 git log 中检索到。

---
*Phase: 110-process-observability*
*Completed: 2026-07-31*
