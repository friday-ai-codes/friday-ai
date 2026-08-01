---
phase: 110-process-observability
reviewed: 2026-07-31T08:10:00Z
status: fixed
depth: standard
diff_base: f3292256
branch: milestone/v0.19.0-plan-trust
files_reviewed: 12
findings:
  blocker: 0
  high: 1
  medium: 2
  low: 3
fixed:
  blocker: 0
  high: 1
  medium: 2
  low: 0
accepted_debt:
  low: 3
fixed_at: 2026-07-31T08:56:00Z
fix_mode: "autonomous（--fix --auto，范围 HIGH + MEDIUM；三个 LOW 记为已接受技术债）"
fix_commits:
  - "aed7010f fix(110-HI-01): 编排失败气泡绑回自己那次会话，不再改播新一轮进度"
  - "88bd72db fix(110-MN-01): plan_research 归属改用 RepoResearchTask 权威表，去掉容器可写的绑定键"
  - "d17abf8f fix(110-MN-02): 编排终态后 2s 轮询不再重发全量事件流与容器日志"
tests_executed:
  backend: "8186 passed, 61 skipped, 26 deselected, 1 xfailed（tests/ 全量，排除三个沙箱受限文件）—— 与基线逐字一致"
  frontend: "1607 passed / 202 files, 1 skipped（CI=true pnpm vitest run --watch=false）—— 与基线逐字一致"
  types: "pnpm vue-tsc --noEmit 退出码 0，零输出"
  migrations: "manage.py makemigrations --check --dry-run → No changes detected"
  lint: "ruff check 四个改动 .py 文件 All checks passed；ruff format --check 三个文件 would reformat（归属见 LO-02）"
tests_after_fix:
  backend: "8204 passed, 61 skipped, 67 deselected, 1 xfailed（tests/ 全量，--deselect 三个沙箱受限文件）—— 较基线 +18，与新增用例数逐条对得上（6 + 1 + 11）"
  frontend: "1615 passed / 202 files, 1 skipped（CI=true pnpm vitest run --watch=false）—— 较基线 +8（store 5 条 + 气泡 3 条）"
  types: "pnpm vue-tsc --noEmit 退出码 0，零输出"
  migrations: "manage.py makemigrations --check --dry-run → No changes detected"
  lint: "ruff check 改动 .py 文件 All checks passed；ruff format --check 新增/改动测试文件与 chat/views.py 全部 already formatted；conversation_service.py 与 chat_runner.py 的 would reformat 逐 hunk 核对后全部落在既有代码（新增段落零命中），LO-02 的两处仍在（已接受）"
  eslint: "pnpm eslint 六个改动前端文件 退出码 0"
files_reviewed_list:
  - server/agents/core/events.py
  - server/chat/conversation_service.py
  - server/delivery/services/convergence_session_service.py
  - server/delivery/services/process_event_wire.py
  - web/src/components/chat/ChatMessageBubble.vue
  - web/src/components/chat/OrchestrationStageTimeline.vue
  - web/src/components/chat/PlanResearchLogGroup.vue
  - web/src/components/execution/dag/SubStepTimeline.vue
  - web/src/composables/useOrchestrationTimeline.ts
  - web/src/stores/chat.ts
  - web/src/types/chat.ts
  - web/src/types/execution.ts
findings_index:
  - id: HI-01
    severity: HIGH
    origin: new
    file: web/src/components/chat/ChatMessageBubble.vue:866
    summary: 编排失败的 tool result 结构上不含 session_id，气泡回退到 store 的全局活跃会话——同一对话里「失败后重跑」时，失败那条气泡改显示新一轮的实时时间线，OBS-03 的失败呈现被抹掉，且同一份进度同时出现在两条气泡上
    status: fixed
    fix_commit: aed7010f
    fix_note: >-
      按建议两条一起做。后端：两个 _map_terminal 的失败分支补
      metadata={"session_id": ...}，_normalize_tool_result 把 metadata 并进失败体；固定的
      error / is_error 两键放在**最后**展开，metadata 不得覆写（否则一个工具就能把
      is_error 翻成 false，评审草案里 metadata 在后是有这个洞的）。前端：兜底限制在
      item.result 为空（在途）这一种情形，有 result 却绑不到会话时整块不渲染（§A.5 条件 2）。
      补上评审指出的缺失形状「终态且 result 可解析但缺 session_id」。
      负向对照四次，每次只掐一处：① 前端退回 `||` 链 → 「终态 result 可解析但缺
      session_id ⇒ 整块不渲染」变红（1 failed / 50）；② _normalize_tool_result 退回两键 →
      test_metadata_is_merged_into_the_failure_body 与 test_failure_body_end_to_end_is_bindable
      变红（2 failed / 6）；③ 拿掉 plan_research 的 metadata →
      test_failed_terminal_result_has_session_id_in_metadata 与端到端那条变红；④ 拿掉
      feature_solution 的 metadata → test_failed_result_carries_session_id_for_bubble_binding
      变红。气泡侧「绑对了」与「没绑成正在跑的那个」拆成两条独立 it，避免第一处失败遮住第二处。
  - id: MN-01
    severity: MEDIUM
    origin: new
    file: server/chat/conversation_service.py:2700
    summary: plan_research 归属谓词自称沿用 WR-03 交叉校验范式，但两个键（plan_session_id / source）同处 last_output 这一个容器可写面，progress 回调可任意写入其中的标量键；真正的 WR-03 是对 RepoResearchTask 这张服务端权威表做交叉验证
    status: fixed
    fix_commit: 88bd72db
    fix_note: >-
      比评审建议再进一步：不是「先按 last_output 查出来、再拿 research_task_id 交叉过滤」，
      而是直接让 RepoResearchTask 当驱动——取 (subagent_session_id → repository_id) 映射
      后按 SubAgentSession 主键 id__in 反查。理由是评审方案里 research_task_id 仍是
      last_output 上的键（虽然锚点已是权威表，容器仍可把它改成同会话内的兄弟 task），
      而 subagent_session_id 由 ResearchService.mark_running 服务端回填 ⇒ 整条绑定链上
      **没有任何容器可写的键**，last_output 从此只用于取日志内容。task_type == PLAN
      作为纵深防御保留；last_output__source / last_output__plan_session_id 两个谓词删除
      （留着等于在预测里继续摆半可信键）。repository_id 同步改取权威列，关掉「容器改写
      自己的 repository_id 就能让日志挂到别的仓库名下」这条不需要猜任何 UUID 的低配越权；
      由此旧的 UUID 过筛不再需要（权威列恒为合法 UUID）。
      附带语义收紧（已在代码注释里如实写出）：stale 重派会把 subagent_session 指向新容器
      ⇒ 每仓恒一张卡，旧实现会把同一仓的历次容器都列出来。
      测试：`_make_research_container` 改为同时建权威 RepoResearchTask，并加
      forged_plan_session_id / forged_repository_id / link_task 三个开关（对应容器唯一能做的
      三件事）；原 test_source_mismatch_is_rejected_by_cross_check 的论证已不成立，替换为三条
      更强的用例。负向对照两次：① 谓词退回 last_output 双键 → 伪造 plan_session_id、无权威
      task 链接两条变红（2 failed / 26）；② repository_id 退回 last_output → 伪造
      repository_id、garbage repository_id 两条变红（2 failed / 26）。两次对照命中的是不相交
      的用例集，说明两半各有独立抓手。
  - id: MN-02
    severity: MEDIUM
    origin: new
    file: server/chat/conversation_service.py:2504
    summary: 两个新分支在编排早已终态后仍每次 2s 轮询重发全量事件流（最多 200 条，逐条重新净化）与全量容器日志（每仓最多 80 行，逐条重新脱敏），无任何终态短路或增量协议
    status: fixed
    fix_commit: d17abf8f
    fix_note: >-
      选了评审的第二条（终态短路）而不是第一条（events_after 增量），因为 events_after
      只覆盖事件分支，而日志分支才是重的那一半（每仓 80 行 × 每行一次
      redact_secrets_in_text，5 个仓 = 每次轮询 400 次正则替换）；一个令牌同时管住两个分支，
      收敛后这两处的 DB 往返与 CPU 归零，而不是「少发一点」。
      协议：runtime 端点新增 orchestration_seen 查询参数（已进 drf-spectacular schema）。
      收敛三条同时成立才短路——令牌逐字等于本对话最近一次编排会话、会话已终态、
      **其下没有在途调研容器**。第三条是评审没提但必须有的：failed 可能停在 research，
      那时容器还在写日志，只看 session 终态会让日志组停在半截（正是本里程碑要消灭的
      「界面撒谎」）；代价是一次带 (session,status) 索引的 exists()。
      判定放在编排分支最前，后面每一步都是它要省掉的开销。日志分支的联动判据取
      **已写进 runtime 的那份快照**而不是局部变量——否则「算出收敛之后编排分支才抛」
      这一拍会同时回「没有编排」与「没有日志」，把前端已有的日志组整个抹掉。
      前端：轮询带令牌（仅当 store 里确实存过一份终态快照，那份必然是全量的那次响应），
      刷新补齐 restoreConversationRuntime 永不带；applyOrchestrationRuntime 在 converged
      时不覆盖已有事件与日志。顺带按建议给容器会话查询加 .only()。
      令牌只能让服务端**少**发数据，猜错 / 伪造只会退化成全量，不构成越权面。
      负向对照五次：① 拿掉「无在途容器」这一条 → test_live_research_container_blocks_the_short_circuit
      变红（1 failed / 35）；② 整个短路失效 → 事件短路、日志短路、「根本没查事件表」三条变红
      （3 failed / 35）；③ 日志分支改看局部变量 →
      test_degraded_orchestration_branch_never_short_circuits_the_logs 变红（1 failed / 35）；
      ④ 前端 converged 恒 false → eventsTruncated、调研日志两条变红（2 failed / 30）；
      ⑤ 轮询不带令牌 / 令牌不看终态 → 各自对应的一条变红。
      对照粒度注记：初版「converged 响应不清空已有事件」只断言 events.length，被对照 ④
      证明是假锁（mergeOrchestrationEvents(existing, []) 天然恒等，任何实现都通过）；
      已改为断言 events_truncated 不被冲回 false —— 那才是收敛守卫在事件侧真正保护的东西。
  - id: LO-01
    severity: LOW
    origin: new
    file: web/src/components/execution/dag/SubStepTimeline.vue:104
    summary: 泛化对既有调用方 ExecutionNode 并非「零行为变化」——每个子步骤行新增了原生 title 悬浮提示，失败摘要行新增了 role="alert"
    status: accepted_debt
    fix_note: >-
      本轮范围为 HIGH + MEDIUM，未处理。评审自己倾向的处置是 (a)「接受这两处 a11y 增强、
      把注释改成如实表述」——它是纯文档改动、零行为影响，与 110-02-SUMMARY 一并修订更合适，
      不适合塞进一次以行为修复为主题的提交（会让 diff 的意图变浑）。
      风险评估：两处变化对 ExecutionNode 都是净收益（悬浮状态文本 + 失败行被屏幕阅读器播报），
      不改变任何功能行为，既有回归用例组仍全绿。留待文档整理或下一次触碰该组件时一并修订。
  - id: LO-02
    severity: LOW
    origin: new
    file: server/chat/conversation_service.py:2518
    summary: 110 新增的后端代码未过 ruff format（两处），与 109 「新增代码零告警」的水位相比是一次回退
    status: accepted_debt
    fix_note: >-
      本轮范围为 HIGH + MEDIUM，未处理；两处仍在（全角括号那行、has_classify 的换行）。
      本轮**新增**的后端代码已自查为 format-clean：`ruff format --diff conversation_service.py`
      的 40 个 hunk 逐个核过行号，无一落在本轮新增段落（终态短路判定、权威表归属、
      converged 键）；chat_runner.py 的唯一 hunk 在 :284，是既有代码。
      即：本轮没有把 LO-02 的水位继续往下拉，但也没有把它补上。
      顺带一提，MN-01 的改写恰好覆盖了 has_classify 那处附近的区块但未触及该表达式本身，
      所以两处的行号相对评审时有位移，修复时应按内容而非行号定位。
  - id: LO-03
    severity: LOW
    origin: pre-existing
    file: server/delivery/services/convergence_session_service.py:316
    summary: _emit_event 的 per-event logger.info 仍在，一次编排数十条 INFO；fan-out 自身合规（debug + sampling），该行是本次直接改动的函数里唯一一条不合规的埋点
    status: accepted_debt
    fix_note: >-
      本轮范围为 HIGH + MEDIUM，未处理。评审自己判定为「可以接受」，且明确记录它是
      pre-existing、110 没有增加任何事件产出量。改动虽只有一个词（info → debug），
      但它落在 convergence_session_service 这个编排热路径上，且现有测试里可能有断言
      日志级别的用例——把它塞进一次以「气泡绑定 / 归属校验 / 轮询收敛」为主题的批次里，
      收益与风险都与本批次无关。
      建议按评审给的正确形态单独处置：per-event 降 debug，同时在 create_session 与终态转移
      两个低频点各留一条 INFO 作为「编排有在跑」的粗粒度信号。
---

# Phase 110: 代码评审报告

**评审范围:** `f3292256..HEAD` 中在册的 12 个源码文件（另核对 8 个新增/改动测试文件，以及 6 个被牵连但未改动的既有模块：`event_taxonomy` / `research_adapter` / `research_aggregation` / `progress_payload` / `subagent.api.callbacks` / `runners.consumers`）
**深度:** standard（逐文件 + 双向消费方追踪 + 全量后端与前端实跑 + 类型与迁移核验）
**结论:** `findings` —— 0 个 BLOCKER、1 个 HIGH、2 个 MEDIUM、3 个 LOW

**修复状态（2026-07-31，autonomous `--fix --auto`）:** HIGH 与两个 MEDIUM 已修复并各自原子提交；
三个 LOW 记为**已接受技术债**（逐条理由见 frontmatter 的 `fix_note`）。详见下面的「修复记录」。

---

## 修复记录

| ID | 处置 | 提交 | 一句话 |
|----|------|------|--------|
| HI-01 | **已修复** | `aed7010f` | 两个编排工具的失败出口补 `metadata={"session_id"}`，`_normalize_tool_result` 并进失败体；前端兜底限制在「还没有 result」这一种在途情形 |
| MN-01 | **已修复** | `88bd72db` | 归属改由 `RepoResearchTask` 驱动（`subagent_session_id` 是服务端回填的 FK）⇒ 绑定链上没有任何容器可写的键；`repository_id` 同步取权威列 |
| MN-02 | **已修复** | `d17abf8f` | runtime 端点加 `orchestration_seen` 收敛令牌；终态 + 无在途容器时 `events` 与 `plan_research_sessions` 不重发，`converged=true` 让前端保留现有的 |
| LO-01 | 已接受 | — | 评审自己倾向的处置是纯注释修订，与 110-02-SUMMARY 一并改更合适 |
| LO-02 | 已接受 | — | 两处仍在；本轮**新增**代码经逐 hunk 核对为 format-clean，水位未继续下拉 |
| LO-03 | 已接受 | — | pre-existing 且评审判定「可以接受」；应与「在 create_session / 终态转移补低频 INFO」一并单独处置 |

### 修复后核验（实跑数字，非推断）

| 项 | 基线 | 修复后 |
|----|------|--------|
| 后端 `pytest tests/`（排除三个沙箱受限文件） | 8186 passed / 61 skipped | **8204 passed / 61 skipped / 1 xfailed** |
| 前端 `CI=true pnpm vitest run --watch=false` | 1607 passed / 202 files | **1615 passed / 202 files / 1 skipped** |
| `pnpm vue-tsc --noEmit` | 退出码 0 | **退出码 0，零输出** |
| `makemigrations --check --dry-run` | No changes detected | **No changes detected** |
| `pnpm eslint`（六个改动前端文件） | — | **退出码 0** |

后端 +18 与新增用例数逐条对得上：`test_tool_result_failure_locator.py` 6 条、
`test_feature_solution_tool.py` +1 条、`test_conversation_runtime_orchestration.py` +11 条
（新增 14、删除 3：`test_source_mismatch_is_rejected_by_cross_check` 的论证随 MN-01 失效，
替换为三条更强的用例）。前端 +8 = store 5 条 + 气泡 3 条。

**每个修复都做了负向对照**（掐掉自己的实现、确认有测试变红、再还原），共 11 次，
逐次命中的用例记在 frontmatter 的 `fix_note` 里。其中一次对照直接改进了用例质量：
「converged 响应不清空已有事件」初版只断言 `events.length`，被对照证明是假锁
（`mergeOrchestrationEvents(existing, [])` 天然恒等，任何实现都通过），已改为断言
`events_truncated` 不被冲回 `false`。

**载重不变量复核（本轮改动未触碰）**：`_emit_event` 仍不抛且 fan-out 的 blanket catch 未动；
`ts` 去重键两条链仍同为 `row.ts.isoformat()`；仍只有一把筛子且 `summary` 按值类型区分；
`failure` 仍只组装 `stage` + `reason_code`，闭集未扩；日志组的 `v-if` 与 `:sessions` 仍是
同一个 `planResearchSessionsFor(item)`；`SubStepTimeline` 零改动；`orchestratedPlanData`
仍按 `item.result` 逐条解析；`chat/views.py` 只在 runtime 端点加了一个查询参数，
`_stream_events` 未触碰；`RoutingDecisionPanel` / `DeepAnalysisGroup` / `DeepAnalysisCard`
仍零改动，`deep_analysis_progress` 未被救活。

**新增可观测面合规**：本轮未新增 LLM 调用（无新 `call_source`）、未新增请求入口
（`orchestration_seen` 是既有端点的查询参数，既有请求指标自动覆盖）、未新增队列或 webhook。
新增的收敛判定与权威表查询都在既有 `try/except` 的 best-effort 包裹内，失败只让本分支降级，
异常分支的那一行 warning 仍带 `category="sampling"` + `component="chat.conversation"`；
高频轮询面上正常路径**零新增日志**。

---

## 摘要

**十条高风险不变量逐条核过，九条成立、一条部分成立。** 详见文末对照表。先说这个 phase 最容易做坏而实际做对了的地方——这些不是客套，是我逐条追证过、且每一条都有一个「很容易写成另一个样子」的反面：

- **`ts` 对齐是真的成立，而且锁得住。** `_fanout_process_event` 用 `envelope["ts"] = row.ts.isoformat()` 覆盖 `build_envelope()` 自取的瞬时值，快照侧 `conversation_service.py:2534` 同样用 `row.ts.isoformat()`。`test_pushed_ts_is_identical_to_persisted_ts` 把落库行**重新 `aget` 回来**再比对——这一点很关键：如果它比对的是 `create()` 返回的内存实例，DB 往返丢精度（MySQL 非 `datetime(6)` 列）就测不出来。我另外确认了 `ConvergenceSessionEvent.ts` 是 `DateTimeField(default=timezone.now)`（不是 `auto_now_add`），内存值与落库值同源。
- **顺带一提，去重对 `ts` 的依赖比设计时预期的还要小，这是好事。** 我按事件逐条追了「哪些事件会同时经 SSE 与快照到达」：`repo.research.*` 与 `clarification.*` 都有自然键（`repo_id` / `clarification_id`），即便 `ts` 某天失准，调研完成数与澄清轮次仍然正确；唯一纯靠 `ts` 去重的 `technical_plan.merge.started` 发生在容器回调续驱阶段，那时根本没有 graph 流可推 ⇒ 它只会从快照来一份，不存在双链重复。**最脆的那个去重键恰好落在不会重复的路径上。**
- **一把筛子是真的只有一把，而且按值类型区分 `summary` 的判断是对的、也是必须的。** 快照侧从 `process_event_wire` import，没有第二份实现。我实读了两个 `summary` 的产出点：`builtin_processes.py:218` 的 classify 传的是 `classification["summary"]` 结构化 dict（`{new, modify, unclear}`），`callbacks.py:1793` 的 research 传的是 `content["research_summary"]`，而 `research_aggregation._build_structured:133` 用 `str(... or "")` 强制转成字符串、`_degrade:145` 是字符串切片——**两条路径都保证它是 str**，所以 `_DROP_IF_STR` 能干净地只砍掉后者。若按键名一刀切，「新增 N · 改造 M」这行摘要的唯一数据源就没了。
- **自由文本确实在服务端就消失了，不是靠前端不渲染。** `question` / `message` / `exception` / `report` / `reasons` / `candidate_files` / `unclarified_points` 全在恒剥离表里；`compress_failure_reason` 的返回值恒 ∈ 7 值闭集，`reason` 落在闭集外时走 `unknown` 而不是回显原值；快照的 `failure` 只组装 `stage` + `reason_code` 两个键，不从 `error` 补任何字段。第三层「残留 str 过 `redact_secrets_in_text` + 截断 200」对**未知事件**这个真实风险面（后端加了新事件而两张表没同步）是有效的兜底。
- **`orch_session` 的 `None` 预置与两支各自判空是对的，并且注释把「为什么不是 `UnboundLocalError`」写清楚了。** 两个 `try` 刻意不合并，一支失败不连带吞掉另一支；两支各自 `except` 里都是「回退到预置的空值 + 一行 warning + `exc_info=True`」，`runtime` 字面量里预置了两个键保证类型恒定。这一段是本 phase 最容易写出「静默降级成空数组，症状与后端根本没写日志逐字相同」的地方，实现避开了。
- **plan_research 谓词避开了那个恒空查询集的陷阱。** 我实读 `research_adapter.py:179-196` 确认：`AgentSession.metadata` 只有 `{source, plan_session_id}`，**没有** `conversation_id`；照抄 deep analysis 的 `main_session__metadata__conversation_id` 会得到一个永远空、永远不报错的 queryset。实现用的是 `ConvergenceSession.conversation_id`（DB 列，服务端写）+ `plan_session_id` + `task_type=PLAN`，方向正确。归属**强度**上有一处名不副实，见 MN-01——但那是加固问题，不是「查不出来」的问题。
- **`_append_runtime_log` 与 progress 回调都是 merge 语义（`consumers.py:932-946`、`callbacks.py:1225`），`plan_session_id` 不会被日志写入冲掉**——这是 OBS-02 能成立的隐含前提，我专门核了，成立。
- **`SubStepTimeline` 的泛化在功能层面确实是纯加性的**：`interactive` 默认 `true`、三个 item 字段全可选、`failed` 时 `summary` 缺失仍回退既有 `output_data.error.slice(0,50)` 路径。`SubStepTimeline.spec.ts` 里有一组专门锁 `ExecutionNode` 既有用法的用例。（两个非功能性的附带变化见 LO-01。）
- **双链合流的 store 设计经得起推敲。** `applyOrchestrationRuntime` 挂在 `if (runtime.active)` **分流之前**——注释给的两条理由我都验证了：`applyRuntimeSnapshot` 第一行是 `isStreaming.value = true`（在非活跃分支调用会错误锁输入框），而编排终态那一拍 `active` 恰好翻 `false`（挂在活跃分支里 `done`/`failed` 永远到不了 store）。`orchestrationRuntimeActive` 初值取 `true` 而不是 `false`，避免「还没查过」被判成「已中断」。清理点选在切换会话而不是 `resetStreamingState`，避免「编排一完成时间线就消失」。**三个都是「反过来写也能跑通大部分用例、但会在特定一拍出错」的选择，三个都选对了。**
- **`orchestratedPlanData` 的 per-item 解析（109 载重不变量）没有被 `lastOrchestrationToolItemId` 污染。** 我特意确认了这个 computed 只出现在时间线与日志组的 `v-if` 里，`OrchestratedPlanCard` 的渲染条件仍是逐条 `resolveOrchestratedPlanData(item.result)`；`chatMessageBubble.parts.spec.ts` 里那条「末条编排 item 在途时，产出卡片仍挂在前面那条终态上」就是这条边界的回归锁。
- **测试质量比前两个 phase 明显好。** 抽查的负向对照是**双向**的：F-21 那条同时断言「第二轮气泡有日志组」**和**「第一轮气泡没有、且全文不含 second-round-repo」——只写前半句的话「完全不过滤」的实现同样为真。`test_get_stream_writer_key_error_is_swallowed` 与 `RuntimeError` 那条并存，用例注释明确写了「只有 RuntimeError 那条时，把 `except Exception` 收紧不会有任何测试变红」；`test_writer_raising_does_not_break_emit` 只让 writer 在**被调用时**抛错并断言 `len(writer.calls) == 1`，堵住了「压根没接上也能通过」。`chatMessageBubble.parts.spec.ts` 这一组**不 stub** 两个新组件（109 的 HI-01 正是被 stub 掩盖的）。commit `52857a33` 还专门把两条断言拆成独立用例。
- **107 / 109 的边界守住了。** `RoutingDecisionPanel` / `DeepAnalysisGroup` / `DeepAnalysisCard` / `chat/views.py` 全部零改动（diff stat 逐字核对），`deep_analysis_progress` 没有被救活，`_stream_events` 的生成器体内用户重绑未被触碰。降级信号只有「路由」步行尾一个 `Badge variant="warning"`，取值严格 `=== true`，前端不自行推断。

**问题集中在一处，另有两处工程债：**

1. **失败后重跑时，时间线会挂到错误的气泡上。** 两个编排工具的失败终态返回的是 `ToolResult(success=False, error=...)`，**结构上不带 `session_id`**；气泡于是回退到 store 的全局 `activeOrchestrationSessionId`。同一对话里重跑一次，失败那条气泡就改显示新一轮的实时进度——失败呈现（OBS-03 的核心交付物）被抹掉，同一份进度还同时出现在两条气泡上。这正是 §A.7 想防的「同一进度出现两遍」，也正是本里程碑要消灭的「时间线撒谎」（HI-01）。
2. **归属谓词的「交叉校验」名不副实。** 注释自称沿用 `callbacks.py` 的 WR-03 范式，但 WR-03 校验的是 `RepoResearchTask` 这张**服务端权威表**，而这里的两个键同处 `last_output`——`_handle_progress` 会把 progress payload 的 `details` 里任意标量键 merge 进去（黑名单只有两个键）。一个键能写的地方，两个键都能写（MN-01）。
3. **2s 轮询面上没有终态短路。** 编排早就 `done` 了，之后每一次轮询（包括随后的整个编码会话期间）都在重新查 200 条事件、逐条重新净化、并把每仓 80 行容器日志逐条重新脱敏后整包下发（MN-02）。

---

## HIGH

> **已修复（`aed7010f`）。** 下面保留评审时的原文与论证；实际落地与建议的两点差异：
> ① `_normalize_tool_result` 里固定的 `error` / `is_error` 两键放在**最后**展开，
> 而不是像草案那样让 `metadata` 在后——否则一个工具就能把 `is_error` 覆写成 `false`；
> ② 补的用例按「绑对了」与「没绑成正在跑的那个」拆成两条独立 `it`，避免第一处失败遮住第二处。

### HI-01：编排失败后重跑，失败那条气泡改显示新一轮的实时时间线

**文件:** `web/src/components/chat/ChatMessageBubble.vue:866-868`、`server/agents/tools/plan_research_tools.py:276-297`（`_map_terminal` 的 failed 分支）、`server/agents/tools/feature_solution_tools.py:197-202`

**问题:**

会话绑定的两级来源是这样写的：

```866:868:web/src/components/chat/ChatMessageBubble.vue
function orchestrationSessionIdFor(item: ToolItemShape): string {
  return resolveOrchestrationSessionId(item.result) || chatStore.activeOrchestrationSessionId || ''
}
```

「result 优先、store 兜底」的顺序本身是对的，注释给的理由（在途五个阶段根本没有 result）也是对的。问题在于**第二级兜底没有被限制在「在途」这个前提上**，而恰好有一条终态路径不带 `session_id`：

```293:297:server/agents/tools/plan_research_tools.py
    error = session.error if isinstance(session.error, dict) else {}
    return ToolResult(
        success=False,
        error=str(error.get("message") or error.get("reason") or "plan session failed"),
    )
```

`start_feature_solution` 的失败分支形状逐字相同（`feature_solution_tools.py:197-202`）。两者的其余出口——`WAITING_CLARIFICATION`（`:241`）、`WAITING_EVENT` 的 `__blocking_task__` marker（`:262`）、`DONE`（`:284`）——**都带顶层 `session_id`**，只有失败这一条不带。而失败 `ToolResult` 到前端的形状是被 `chat_runner._normalize_tool_result:402-405` 固化的：

```402:405:server/agents/chat_runner.py
def _normalize_tool_result(result: ToolResult) -> Any:
    if result.success:
        return result.output
    return {"error": result.error or "未知错误", "is_error": True}
```

⇒ 气泡拿到的 `result` 是 `'{"error":"…","is_error":true}'`，能 JSON.parse、但没有 `session_id` ⇒ `resolveOrchestrationSessionId` 返回 `''` ⇒ 落到第二级兜底。

**用户可见后果**（按发生顺序）：

| 时刻 | 失败那条气泡显示 | 新那条气泡显示 |
|---|---|---|
| 编排 #1 失败，用户还没重跑 | `方案编排失败` + 红步 + 闭集原因行（**正确**） | — |
| 用户在同一对话里重跑，编排 #2 开始 | **`正在生成技术方案` + #2 的实时进度** | 同样是 #2 的实时进度 |

失败后在同一对话里重跑是最普通不过的操作，而它恰好把 OBS-03 唯一的交付物（「失败停在哪一步一目了然」）从界面上擦掉：用户滚回去想看「刚才到底停在哪一步」，看到的是一条正在跑的新时间线。同时两条气泡播同一份进度，正是 UI-SPEC §A.7 末段「避免同一进度出现两遍」明令要防的形态。

顺带一提，`activeOrchestrationSessionId` 会被 SSE（`stores/chat.ts:1734`）与快照（`:1000`）**两条链**都写成 #2，所以这不是某一条链的时序问题，刷新页面也不会自愈。

**这条缺口为什么没被测试抓住：** `chatMessageBubble.parts.spec.ts` 里覆盖会话绑定的三条用例分别是「result 有 session_id ⇒ 优先」「result 取不到（**在途早期**，`status: 'running'` 且 `result: undefined`）⇒ 回退 store」「两级都取不到 ⇒ 不渲染」。第二条用的是**在途**形态，正好是兜底应该生效的那一种；没有任何一条覆盖「**终态**且 result 可解析但缺 `session_id`」——而那正是失败路径的形状。

**修复建议（两条一起做，各治一半）:**

1. **让失败的编排 tool result 也带上 `session_id`。** `_normalize_tool_result` 是共享函数，最小侵入的改法是让它在失败时并上 `metadata`：

```python
def _normalize_tool_result(result: ToolResult) -> Any:
    if result.success:
        return result.output
    # 失败结果也需要携带定位键（编排失败的气泡要靠 session_id 绑回它自己那次编排）。
    # metadata 由工具显式给出，不含自由文本。
    return {"error": result.error or "未知错误", "is_error": True, **(result.metadata or {})}
```

两个 `_map_terminal` 的失败分支相应加 `metadata={"session_id": str(session.id)}`。`ToolResult.metadata` 字段本来就在（`agents/tools/base.py:48`）、当前无人使用，不新增契约面。

2. **把第二级兜底限制在「这条 tool item 还没有终态 result」上**，让「有 result 但绑不到会话」按 §A.5 条件 2 走「整块不渲染」而不是绑到别人身上：

```ts
function orchestrationSessionIdFor(item: ToolItemShape): string {
  const fromResult = resolveOrchestrationSessionId(item.result)
  if (fromResult)
    return fromResult
  // 🔴 兜底只服务「在途还没有 result」这一种情形（§A.7）。已有 result 却解析不出
  // 会话，说明它不属于当前活跃编排——宁可不渲染，也不能把别人的进度挂上来。
  return item.result ? '' : (chatStore.activeOrchestrationSessionId || '')
}
```

两条都做之后，失败气泡靠自己的 `session_id` 绑回 #1（时间线保持红步），新气泡绑 #2，互不串台。

3. **补一条用例**：同一 store 里 seed 两个桶（S1 `failed` / S2 `running`）、`activeOrchestrationSessionId = 'S2'`，挂载一条 result 为 `{"error":"…","is_error":true}` 的编排气泡，断言它绑到 **S1**、标题是「方案编排失败」、且全文**不含**「正在生成技术方案」。只断言前半句的话，「绑到 S2」的实现在标题断言上同样会红——但两条一起写才能同时锁住「绑对了」与「没绑成正在跑的那个」。

---

## MEDIUM

> **两条均已修复（`88bd72db` / `d17abf8f`）。** 下面保留评审原文；与建议的差异：
> MN-01 没有停在「按 `research_task_id` 交叉过滤」，而是直接让 `RepoResearchTask` 当驱动
> 并按 `subagent_session_id`（服务端回填的 FK）反查 —— 那个键容器根本改不到；
> MN-02 选了第二条（终态短路）而非第一条（`events_after`），因为一个令牌能同时管住
> 事件与日志两个分支，且额外加了一条评审未提的必要条件「其下没有在途调研容器」。

### MN-01：plan_research 归属谓词的「交叉校验」两个键同处一个容器可写面

**文件:** `server/chat/conversation_service.py:2688-2707`

**问题:**

谓词与它的论证是这么写的：

```2700:2707:server/chat/conversation_service.py
                research_candidates = [
                    sess
                    async for sess in SubAgentSession.objects.filter(
                        task_type=SubAgentSession.TaskType.PLAN,
                        last_output__source="plan_research",
                        last_output__plan_session_id=str(orch_session.id),
                    ).order_by("id")
                ]
```

注释称 `source == "plan_research"` 是「**交叉校验**（fail-closed）……两键同时命中才算数（109 callbacks.py WR-03 范式）」。**这个论证不成立**：两个键住在同一个 dict 里，而那个 dict 是容器可写的。

`_handle_progress` 把 progress payload 的 `details` 里的标量键无差别 merge 进 `last_output`：

```69:75:server/orchestration/progress_payload.py
        for key, value in details.items():
            if key in _RESERVED_OUTPUT_KEYS:
                continue
            if value is None or isinstance(value, (str, int, float, bool)):
                output[key] = value
```

`_RESERVED_OUTPUT_KEYS` 只有 `{"progress", "coding_progress"}`。⇒ `plan_session_id` 与 `source` **都**能被容器经一次 progress 回调改写。能改一个的，就能同时改两个；两个半可信键的合取，强度等于一个。

而真正的 WR-03 范式（`callbacks.py:434-440`，注释逐字写着「绝不单信 runner 可经 progress 篡改的 `last_output.plan_session_id`」）校验的是**另一张服务端权威表**：

```435:440:server/subagent/api/callbacks.py
            research_task_id = lo.get("research_task_id")
            if research_task_id:
                task = await RepoResearchTask.objects.filter(id=research_task_id).afirst()
                if task is None or str(task.session_id) != str(plan_session.id):
                    return
```

**后果与可达性:** 攻击面窄但确实存在。`task_type` 是真列（不可篡改），全仓只有 `research_adapter._dispatch_deep_task` 建 `TaskType.PLAN`，所以能进这个查询的只有别的 plan_research 容器。要把自己的日志投进他人会话，需要猜中受害者的 `ConvergenceSession` UUID——不可猜，所以这不是一条现实可用的越权路径。**但同一个洞有一个不需要猜任何东西的低配版**：容器改写自己的 `repository_id` 即可让自己的日志挂到**另一个仓库名**下（`repo_name_by_id` 按这个值查名字）。用户看到的是「A 仓的调研日志」而内容来自 B 仓。

真正值得改的理由是注释本身：它把「两个半可信键」写成了「交叉校验」，下一位评审会按这个前提判定这里已经加固过，从而不再复查。

**修复建议:** 换成对 `RepoResearchTask` 的真交叉校验——`last_output.research_task_id` 已经在手（`research_adapter.py:194` 服务端写入），一次批量查即可，不引入 N+1：

```python
# 服务端权威表交叉验证：本会话下的调研任务集合（RepoResearchTask.session_id 是 DB 列，
# 容器改不到）。last_output 里的 plan_session_id / source 都是 progress 回调可写的面，
# 两个半可信键的合取强度等于一个 —— 必须有一个不可写的锚点。
authoritative_task_ids = {
    str(tid)
    async for tid in RepoResearchTask.objects.filter(
        session_id=orch_session.id
    ).values_list("id", flat=True)
}
research_candidates = [
    sess for sess in research_candidates
    if str((sess.last_output or {}).get("research_task_id") or "") in authoritative_task_ids
]
```

`repository_id` 同理可以改成取 `RepoResearchTask.repository_id`（权威列）而不是 `last_output.repository_id`，顺手把仓库名错挂那条也关掉。并把注释里「两键同时命中才算数（WR-03 范式）」改成如实表述。补一条用例：一个 `last_output.plan_session_id` 指向本会话、但 `research_task_id` 不属于本会话的 `SubAgentSession`，断言它**不出现**在 `plan_research_sessions` 里。

### MN-02：编排终态后，2s 轮询仍在无限期重发全量事件流与全量容器日志

**文件:** `server/chat/conversation_service.py:2504-2547`（events 分支）、`:2700-2760`（logs 分支）

**问题:**

两个新分支都是**无条件**执行的，谓词只看「本对话有没有 ConvergenceSession」，不看它是不是早就终态了：

```2519:2527:server/chat/conversation_service.py
                rows = [
                    row
                    async for row in ConvergenceSessionEvent.objects.filter(
                        session_id=orch_session.id,
                    ).order_by("-ts", "-created_at")[:201]
                ]
```

每次轮询：取最多 201 行 → 逐行 `sanitize_process_event_payload`（每行走两层键剥离 + 逐字符串 `redact_secrets_in_text` 正则）→ 整包序列化下发。日志分支同理，每仓最多 80 行、每行 `content` 各跑一次 `redact_secrets_in_text`（5 个仓 = 每次轮询 400 次正则替换）。

而 `pollConversationRuntime` 的存活条件是 `runtime.active`，**它不是「编排活跃」，是「本对话有任何活跃 run」**（`stores/chat.ts:1223`）。所以典型时序是：编排跑完（假设 90 秒，45 次轮询）→ 用户点「进入编码」→ 编码会话跑十几分钟，期间**每 2 秒**继续把那份早已凝固的 200 条事件 + 5 仓 400 行日志重新查一遍、重新净化一遍、重新下发一遍。10 分钟 = 300 次，全是重复内容。

净化后的单包体积不至于失控（我核过 `_routing_snapshot_payload:110-143`，最肥的 `stage0` / `stage1` / `weight_config` / `repo_meta` 恰好都在恒剥离表里），主要代价在**服务端 CPU 与 DB 往返**，以及日志分支的 `last_output` 全量读取。这不构成正确性问题，也确实与 deep analysis 分支既有的做法同构——但 deep analysis 至少随任务终态自然停下，编排快照没有任何收敛机制。

**修复建议（择一，都不改前端契约）:**

- **（推荐，最小）给端点加一个 `events_after` 查询参数**：前端把桶里已有的最大 `ts` 带上，后端只回该 `ts` 之后的行。前端的 `mergeOrchestrationEvents` 本来就是按去重键合并、天然接受增量，不需要改。`restoreConversationRuntime`（刷新补齐）不带这个参数即拿全量，两个调用点各取所需。
- **或按终态短路**：`orch_session.status in {DONE, FAILED}` 且客户端带了 `orchestration_seen=<session_id>` 时，只回权威字段、`events` 回空并置一个 `events_unchanged: true`。改动更小但多一个契约键。

无论走哪条，建议同时给日志分支的 `last_output` 查询加 `.only("session_id", "status", "last_output")`（当前是整行 `SELECT *`）。

---

## LOW

> **三条均记为已接受技术债，本轮未处理**（范围限 HIGH + MEDIUM）。逐条理由见
> frontmatter 的 `fix_note`；简言之：LO-01 的正确处置是纯注释修订（宜与 110-02-SUMMARY 同批），
> LO-02 的两处仍在但本轮新增代码经逐 hunk 核对为 format-clean，
> LO-03 应与「在 `create_session` / 终态转移补低频 INFO」一并单独处置。

### LO-01：`SubStepTimeline` 的泛化对 `ExecutionNode` 不是「零行为变化」

**文件:** `web/src/components/execution/dag/SubStepTimeline.vue:104`、`:132`

功能层面确实是纯加性的（三个新 item 字段与两个新 prop 全部可选、默认值保持既有行为、`output_data.error` 回退路径逐字保留），但有两处**非功能性**的变化会落到既有唯一调用方 `ExecutionNode.vue:340` 上：

```104:104:web/src/components/execution/dag/SubStepTimeline.vue
        :title="statusLabel(step.status)"
```

`title` 是新增的，且不受 `interactive` 开关约束 ⇒ 工作流执行面板里悬停任意子步骤行，现在会弹出浏览器原生提示（`未开始` / `进行中` / `已完成` / `失败`）。

```132:132:web/src/components/execution/dag/SubStepTimeline.vue
            :role="step.status === 'failed' ? 'alert' : undefined"
```

`role="alert"` 同样是无条件的 ⇒ `ExecutionNode` 的失败子步骤摘要现在也会被屏幕阅读器播报。

两处都是**可辩护的改进**（a11y 上正向），也都不会让 `SubStepTimeline.spec.ts` 里锁 `ExecutionNode` 既有用法的那组用例变红——因为那组断言的是状态点色值、`stepClick` 是否 emit、摘要文案回退，没有断言属性集合。但 110-02-SUMMARY 与组件头部注释都写的是「缺省时渲染结果与泛化前**逐字一致**」，这句话现在不准确了。

**修复:** 二选一。(a) 接受这两处变化，把注释改成如实表述（「功能行为逐字一致；另新增 `title` 与失败行 `role=alert` 两处 a11y 增强，对 `ExecutionNode` 同样生效」）；(b) 若要严格零变化，把 `title` 挂在 `interactive === false` 时才输出。我倾向 (a)——这两处对 `ExecutionNode` 也是净收益，把注释改准比把改进收回去好。

### LO-02：110 新增的后端代码未过 `ruff format`

**文件:** `server/chat/conversation_service.py:2518`、`:2523-2525`

`ruff format --check` 报三个文件待格式化。我逐段比对了 `--diff` 的位置：`convergence_session_service.py` 与 `agents/core/events.py` 的待改格式**全部落在既有代码**（`events.py` 是整个 `ALL_EVENT_TYPES` 字面量的既有写法，110 只在里面加了一行）。但 `conversation_service.py` 有**两处落在 110 新增的行上**：

```
-                #（UI-SPEC §E.3：前端不渲染空壳，后端也不该先造出这个壳）。
+                # （UI-SPEC §E.3：前端不渲染空壳，后端也不该先造出这个壳）。

-                has_classify = (
-                    isinstance(decomposition, dict)
-                    and decomposition.get("mode") == "feature_list"
-                )
+                has_classify = (
+                    isinstance(decomposition, dict) and decomposition.get("mode") == "feature_list"
+                )
```

纯格式、零行为影响。记为 LOW 是因为 109-REVIEW 明确记录过「109 新增代码零告警」，这是一次小幅回退；文件整体本来就不是 format-clean，所以也不适合整文件格式化（会把无关行卷进 diff）。

**修复:** 只对这两处手工对齐（或 `ruff format` 后把无关 hunk 撤回）。

### LO-03：`_emit_event` 的 per-event `logger.info` 仍在（pre-existing，本次直接触及）

**文件:** `server/delivery/services/convergence_session_service.py:316-323`

```316:323:server/delivery/services/convergence_session_service.py
        logger.info(
            "convergence_session_event",
            category="sampling",
            component="convergence_session_service",
            event_name=event_name,
            session_id=str(session.id),
            status=session.status,
        )
```

**判定：可以接受，但建议顺手改掉，理由不是规范条文而是这个 phase 自己的处境。**

先说为什么可以接受：这行是 pre-existing 的，110 没有增加任何事件产出量（fan-out 挂在既有出口上、不新增 emit 点），所以它不是本 phase 引入的回归；`category="sampling"` / `component` 都齐备，只是级别选错。而 110 **自己新增**的那条 fan-out 埋点（`:371-378`）严格按 CONTEXT 的要求走了 `debug` + `sampling`，规范上是合规的。

再说为什么仍建议改：`.cursor/rules/observability-logging.mdc` 的「高频循环内禁止 INFO 刷屏（用 `sampling` 分类 + debug 或采样）」在这里字面命中——一次技术方案编排会走十几次 `transition()` 加十几条领域事件，几十条 INFO 挤在一次用户操作里；多仓调研 + 融合重试的场景 UI-SPEC 自己估的是「轻松破百」。更关键的是位置：`_emit_event` 正是本次改动的函数，而这个 phase 的主题就是可观测性——在这里留一条与自己刚立的纪律相反的埋点，会成为后续「这条能 INFO，我这条为什么不行」的先例。改动是一个词（`logger.info` → `logger.debug`），风险接近零，两条埋点级别就此一致。

**修复:** 降为 `logger.debug`。若确实需要保留一条 INFO 作为「编排有在跑」的粗粒度信号，正确的位置是 `create_session` / 终态转移这两个低频点，而不是每条事件。

---

## 逐项回应高风险不变量

| # | 不变量 | 结论 |
|---|---|---|
| 1 | fan-out 永不打断编排 | **通过。** `_emit_event` 仍不抛：持久化包 `try/except` + `_fanout_process_event` 整体 blanket `except Exception: pass`。`RuntimeError` 与 `KeyError` 两条路径**各有一条独立用例**，且用例注释写明了「只有 RuntimeError 那条时收紧 `except` 不会有测试变红」——收紧防护是真的锁住了。落库失败时刻意不推（无权威 ts 的孤儿事件），也有用例 |
| 2 | `ts` 去重键跨链一致 | **通过。** 两条链都是 `row.ts.isoformat()`；模型是 `DateTimeField(default=timezone.now)`，内存值与落库值同源；`test_pushed_ts_is_identical_to_persisted_ts` 把行**重新 `aget`** 回来比对，DB 往返被覆盖。另注：唯一纯靠 `ts` 去重的 `merge.started` 只从快照来一份（那时无 graph 流可推），最脆的键落在不会重复的路径上 |
| 3 | 一把筛子 + `summary` 按值类型区分 | **通过。** 快照侧 import `process_event_wire`，无第二份实现。classify 的 `summary` 实读是结构化 dict（`builtin_processes.py:218`）被保留；research 的 `summary` 经 `research_aggregation:133/145` 强制为 str 后被 `_DROP_IF_STR` 剥离。按键名一刀切会砍掉「新增 N · 改造 M」的唯一数据源，实现避开了 |
| 4 | 无自由文本出网 | **通过。** `question`/`message`/`exception`/`report`/`reasons`/`candidate_files`/`api_contracts_exposed`/`unclarified_points` 恒剥离；`summary`/`error`/`detail` 按 str 剥离；残留 str 过 `redact_secrets_in_text` + 200 截断（对未知事件的兜底）。`failure` 只组装 `stage` + `reason_code`，`compress_failure_reason` 返回值恒 ∈ 7 值闭集，闭集外取值走 `unknown` 不回显 |
| 5 | plan_research 谓词用对了绑定键 | **通过（强度上有保留）。** 用的是 `ConvergenceSession.conversation_id` + `plan_session_id` + `task_type=PLAN`，**没有**碰 `main_session__metadata__conversation_id`——我实读 `research_adapter.py:179-181` 确认那个字段根本不存在，照抄会得到恒空且不报错的 queryset。方向正确、能查出数据。但自称的「交叉校验」两个键同处容器可写面，见 MN-01 |
| 6 | 无 unbound 变量路径 | **通过。** `orch_session: Any = None` 预置在两个 `try` 之外，两支各自显式判空；两个 `try` 刻意不合并；`runtime` 字面量预置两个键保证类型恒定。这一段的注释把「为什么不预置就会静默降级成空数组、症状与后端没写日志逐字相同」讲清楚了 |
| 7 | 日志组按 session 维度过滤，`v-if` 与 `:sessions` 同表达式 | **通过。** 两处都是 `planResearchSessionsFor(item)`，逐字相同。`chatMessageBubble.parts.spec.ts` 的 F-21 用例是**双向**断言（第二轮有 + 第一轮既没有组、全文也不含第二轮的仓名），单向写法挡不住「完全不过滤」的实现 |
| 8 | `SubStepTimeline` 纯加性 | **部分通过。** 功能行为对 `ExecutionNode` 逐字不变（默认 `interactive: true`、新字段全可选、`output_data.error` 回退保留），有专门的回归用例组。但新增了无条件的 `title` 与失败行 `role="alert"`，「逐字一致」的表述不准确（LO-01） |
| 9 | Phase 109 不变量保留 | **通过。** 编排卡片仍按 `resolveOrchestratedPlanData(item.result)` 逐条解析，`lastOrchestrationToolItemId` 只用于时间线/日志组的去重渲染位置，并有一条专门的边界回归锁；`TechPlanCard` 的 `runtime.plan_id === codingPlanId` 守卫未被触碰；`chat/views.py` 全文未改动 ⇒ `_stream_events` 生成器体内的用户重绑原样保留 |
| 10 | 边界守住 | **通过。** diff stat 逐字核对：`RoutingDecisionPanel` / `DeepAnalysisGroup` / `DeepAnalysisCard` / `useDeepAnalysisLog` 零改动，`deep_analysis_progress` 未被救活。气泡上有一条专门用例断言不出现路由决策面板、不含「未经 LLM 推理」与「置信度」 |

## 未构成缺陷、但建议在 VERIFICATION 里如实记录的一点

**`process_event` 的端到端直播链没有被任何测试真正跑通过。** 全部 fan-out 用例都 monkeypatch 掉了 `langgraph.config.get_stream_writer`，所以「生产环境下 `get_stream_writer()` 能否在 tool 调用栈里解析出 writer」这件事是静态推断而非实测结论。

我做了能做的静态核验，结论是**大概率成立**：写入形状 `writer({"type": X, "data": Y})` 与 `graph.py:312/485/642` 等 8 处既有 `StreamWriter` 用法逐字同构，消费侧 `conversation_service.py:1699-1704` 的 `chunk["type"] == "custom"` → `AgentEvent(type=event_data["type"], data=event_data.get("data", {}))` 正好对上，`astream` 的 `stream_mode=["custom", "values"]` 三处调用点都带了 `custom`。

之所以只作为记录而不是缺陷：即使这条链在生产里静默失效，**功能不会坏**——2s 运行时快照覆盖全部七个阶段（110-01 的 F-1 本来就把 research → merge 后半程交给了快照），用户看到的差别只是「进度每 2 秒跳一格」而不是「秒级刷新」。SC-1 仍然成立。建议 UAT 时实跑一次编排、确认在途五个阶段是秒级出现而不是 2 秒一跳，以此代替一条难写的集成测试。

---

_Reviewed: 2026-07-31T08:10:00Z_
_Reviewer: gsd-code-reviewer_
_Depth: standard_

_Fixed: 2026-07-31T08:56:00Z_
_Fixer: gsd-code-fixer（autonomous `--fix --auto`，范围 HIGH + MEDIUM）_
_Fix commits: `aed7010f` / `88bd72db` / `d17abf8f`_
