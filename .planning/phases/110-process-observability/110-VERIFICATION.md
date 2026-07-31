---
phase: 110-process-observability
verified: 2026-07-31T09:52:00Z
status: human_needed
score: 97/97 must-haves verified
gap_closure: "GAP-1 已闭合（commit ba761025）；同根因的 UI-MN-01 脉冲缺席一并修复（0681b463）"
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  note: "初次判定 gaps_found（GAP-1）。orchestrator 已按 autonomous 模式做一轮 gap closure：快照缺席时用失败事件兜底，快照在场仍以快照为准；补齐「快照有无 × 会话状态」缺维共 4 条用例，并连带修掉同根因的脉冲缺席（另 3 条用例）。负向对照均精确变红后还原。复跑：前端 1622 passed / 202 files，vue-tsc 退出 0。"
evidence:
  backend_tests: "8204 passed, 61 skipped, 26 deselected, 1 xfailed, 0 failed（`server/.venv/bin/python -m pytest -q -p no:cacheprovider`，全量套件 510.62s；按测试环境说明排除受文件系统沙箱限制的 `tests/services/test_commit_index.py` / `tests/services/test_commit_index_integration.py` / `tests/mcp_tools/test_grep_repository.py` 三个文件）"
  frontend_tests: "1615 passed, 1 skipped / 202 files passed, 1 skipped（`cd web && CI=true pnpm vitest run --watch=false`，14.04s；按要求断言 `Tests N passed` 行而非退出码）"
  types: "`npx vue-tsc --noEmit` 退出码 0、零输出"
  migrations: "`manage.py makemigrations --check --dry-run` → `No changes detected`，退出码 0"
  lint: "`ruff check` 覆盖 8 个改动后端文件 → `All checks passed!`；`ruff format --check` 仍有 4 个文件待格式化，其中落在 110 新增行上的恰为 LO-02 记录的两处（全角括号注释行、`has_classify` 换行），其余 hunk 逐条核对为既有代码"
  debt_markers: "31 个改动源文件（server/ + web/，含测试）零 TBD / FIXME / XXX / TODO / HACK / PLACEHOLDER"
  verifier_probe: "verifier 自建可执行探针（跑完即删）实测 `buildOrchestrationTimeline`：无快照 + `process.session.failed` 事件 ⇒ `phase='running'` / 标题「正在生成技术方案」 / 失败步渲染为 `running`；同输入加上 `status=failed` 快照 ⇒ `phase='failed'` / 红步 / 「该阶段执行出错」。两条断言式探针均通过，GAP-1 由实测而非评审转述坐实"
gaps_closed:
  - truth: "SC-3：编排失败时用户能直接看出停在哪一步、原因是什么"
    status: partial
    reason: >-
      失败态**只**由运行时快照的 `status` 决定（`useOrchestrationTimeline.ts:439-441`），
      而编排前半程（decompose / route / recall / classify / clarify）跑在 SSE 流内、
      此期间 `pollConversationRuntime` 根本没有被调度（`chat.ts:2407` 只在
      `waiting` / `waiting_clarification` 收尾时起轮询），桶里 `snapshot === null`。
      后端确实经 fan-out 把 `process.session.failed` 推到了前端并已入桶，但 `foldEvents`
      刻意不认这个事件名（`TRANSITION_TO_STAGE` 注释：「不推进 stage，只翻状态」），
      也没有任何其它分支据它翻 phase ⇒ 前半程失败时时间线**持续宣称「正在生成技术方案」**，
      须用户刷新页面才自愈。后半程（research / merge）失败因轮询已起，表现正确。
    artifacts:
      - path: "web/src/composables/useOrchestrationTimeline.ts"
        issue: "`isFailed` 仅取 `snapshot?.status`，无事件流兜底；`process.session.failed` / `fail` 在折叠逻辑里被静默丢弃"
      - path: "web/src/stores/chat.ts"
        issue: "SSE 直播期间不起 runtime 轮询 ⇒ 前半程 `bucket.snapshot` 恒为 null，失败事实无处落地"
    missing:
      - "在 `foldEvents` 里认 `process.session.failed`（以及 `fail`），命中即把 `phase` 翻 `failed` 并把当前指针那一步标红"
      - "该分支下摘要行留空即可（闭集原因文案仍由快照补齐；§A.4 本就允许缺数据时整行不渲染），不得由前端推断原因码"
      - "补一条「无快照 + failed 事件 ⇒ phase=failed 且指针步为 failed」的用例；现有 71 条穷举 spec 里没有任何一条覆盖这一输入组合（也没有任何一条把当前错误行为锁死，修复不需要改既有断言）"
deferred:
  - truth: "workflow / MCP 入口的过程可视化"
    addressed_in: "本里程碑外"
    evidence: "110-CONTEXT `<deferred>`：这两条链无 chat 会话、没有推送目标；事件照常落库，读取面（`(session, ts)` 索引）已具备"
  - truth: "`SOURCE_PROCESS_EVENT` 的工作流信号投影实现"
    addressed_in: "本里程碑外"
    evidence: "110-CONTEXT `<deferred>`：`workflows/reactions/signal.py:67` 有常量无投影实现，属工作流反应体系，与本相位的用户可见性目标不同源"
  - truth: "清理 `deep_analysis_progress` 死路径"
    addressed_in: "本里程碑外"
    evidence: "110-CONTEXT `<deferred>`：范围外的死代码清理；本相位已核实未触碰、也未救活"
  - truth: "把 Phase 107 的降级提示改为读事件表"
    addressed_in: "本里程碑外（裁决 D-3 明确不做）"
    evidence: "110-CONTEXT 裁决 D-3：返工面大、用户可见收益为零；SC-4 靠「谁渲染什么」的分工满足"
  - truth: "`RoutingDecisionPanel` 的重新上线（降级提示的可见承载）"
    addressed_in: "里程碑级缺口，非 Phase 110 缺陷"
    evidence: "该面板 2026-05 已退役，SPA 内无任何挂载点，且有锁测试断言其不渲染（`partsApiIntegration.spec.ts:178`）。110-CONTEXT 边界明确「不重做 Phase 107 已落地的降级提示」，本相位只在「路由」步加角标"
human_verification:
  - test: "真实会话触发一次跨仓编排，肉眼确认前半程（拆分 / 路由 / 召回 / 澄清）的阶段是**秒级**逐个出现，而不是每 2 秒跳一格"
    expected: "阶段推进与后端事件同步出现（秒级）；若呈 2 秒节拍，说明 `get_stream_writer()` 在 tool 调用栈里解析不到 writer，SSE 直播链静默失效（功能不坏，退化为快照节拍）"
    why_human: "全部 fan-out 用例都 monkeypatch 掉了 `langgraph.config.get_stream_writer`，端到端 SSE 路径从未真正跑过。静态核验已确认写入形状与 `graph.py:312/485/642` 等既有 `StreamWriter` 用法逐字同构、消费侧 `conversation_service.py:1699-1704` 对得上、三处 `astream` 都带 `custom`，但生产解析行为无法程序化断言"
    requirement: OBS-01
  - test: "真实跨仓编排跑到调研阶段，核对 `plan_session_id`（后端 `str(ConvergenceSession.id)`）与编排 tool result 里的 `session_id` 是否为**同一个字符串**"
    expected: "两者逐字相同，日志组出现在编排气泡内；若出现「时间线在跑、日志组永不出现」，这个不等就是第一嫌疑"
    why_human: "两侧各有后端用例，但跨进程的字符串相等性从未被端到端测量；110-02..110-07 没有任何一个 plan 跑过真实编排，全部验证都是单元级"
    requirement: OBS-02
  - test: "真实调研容器起来后，确认每仓一张卡、卡标题是仓库名、日志随容器 stdout 增量刷新，且编排完成后日志仍可展开查看"
    expected: "体验与深度分析一致；无裸 UUID 上屏；凭据类文本已在服务端脱敏"
    why_human: "需真实 Docker runner 与容器 stdout；本地只验证到 `last_output.logs` 的读取与脱敏（后端用例覆盖）"
    requirement: OBS-02
  - test: "制造一次**前半程失败**（打断 route 或 recall stage），确认 GAP-1 的复现：时间线是否持续显示「正在生成技术方案」，刷新后是否才翻红"
    expected: "复现 ⇒ 按 gaps 的 missing 清单修复；不复现 ⇒ 说明存在我未识别的快照触发路径，需回写本报告"
    why_human: "verifier 已用可执行探针在纯函数层坐实行为，但「前半程期间确实没有快照到达」这一条是从轮询调度点静态推出的，值得在浏览器里实测一次"
    requirement: OBS-03
  - test: "读屏（VoiceOver / NVDA）走一遍调研日志组的折叠按钮"
    expected: "能听到「方案调研 · N 个仓库」；当前实现用 `aria-label=\"展开方案调研日志\"` 覆盖了可见文案，读屏用户听不到仓库数（WCAG 2.5.3 Label in Name，Level A）"
    why_human: "真实读屏行为无法程序化断言；结构层已确认 `aria-label` 与可见文案不含蕴（`PlanResearchLogGroup.vue:100-108`）"
    requirement: OBS-02
  - test: "五个仓并行调研时确认 live region 只播报阶段变化，不随各仓完成连播"
    expected: "屏幕阅读器只在活跃阶段 key 或会话状态变化时播报一次"
    why_human: "代码层已守住（`COPY.stepCount` 不进 live region，卡内 `aria-live` 恰 1 个，有用例锁），但实际播报节奏须实听"
    requirement: OBS-03
  - test: "亮 / 暗主题下核对 `skipped` / `unknown` 空心点（`bg-transparent border border-muted-foreground/50`）的可辨识度"
    expected: "空心与实心的形状差异在两种主题下都能分辨（它是这两态唯一的非文字信号）"
    why_human: "视觉对比度与观感无法程序化断言"
    requirement: OBS-03
---

# Phase 110: 过程可观测（阶段流式 + 容器日志 + 阶段时间线）验证报告

**Phase Goal**: 方案生成全过程对用户实时可见——阶段进展与阶段性内容边跑边出、调研容器日志可查、失败停在哪一步一目了然。

**Verified**: 2026-07-31T09:52:00Z
**Status**: gaps_found（1 个真实缺口落在 SC-3 上；其余自动化面全通）
**Diff base**: `f3292256` → `c3e0cb29`（31 个改动源文件 + 测试，8652 insertions / 64 deletions）
**Re-verification**: No —— 首次验证

---

## 1. 成功标准达成情况

### SC-1 —— 实时看到阶段进展与阶段性内容（OBS-01）

| # | 可观测事实 | 状态 | 证据 |
|---|-----------|------|------|
| 1 | 编排每条领域事件与转移事件都被推给前端 | ✓ VERIFIED | `_emit_event` 内 `_persist_event` 之后单点 fan-out（`convergence_session_service.py:334-390`）；`test_real_transition_is_fanned_out` 走真实 `transition()` 证明「stage handler 零改动即自动获得推送」，不是逐处补推 |
| 2 | 六个用户面阶段取 ROADMAP SC-1 原文措辞 | ✓ VERIFIED | `STAGE_LABELS` 逐字为 拆分 / 路由 / 召回 / 澄清 / 并行调研 / 融合；第七个「功能点分类」是 feature_list 专属扩展点 |
| 3 | 每阶段一句结构化摘要，零新增 LLM 调用 | ✓ VERIFIED | 七套摘要全部取 payload 已有字段（`segment_count` / `candidates.length` / `hits` / `summary{new,modify,unclear}` / 澄清轮次 / 调研 done+total / 融合轮次）；`useOrchestrationTimeline.ts` 不 import 任何 provider |
| 4 | 阶段指针不撒谎（不倒退、不卡死、不虚高） | ✓ VERIFIED | 指针以 `current_stage` 为权威、事件流为缺失时的临时指针；`TRANSITION_TO_STAGE` 我逐条比对 `_TECHNICAL_PLAN_STAGES` 的真实转移表（含 `validation_failed_reclarify` / `validation_failed_reresearch` 两条**回退**转移），12 个键全部对得上，取「最后一条可识别转移」而非「最大序号」正是为这两条回退准备的 |
| 5 | 调研分母取实际派了容器的去重 repo 数 | ✓ VERIFIED | `researchSummary` 用 `folded.researchStarted.size`，不用路由候选数——light path 的仓不起容器，用候选数会让进度永远到不了满 |
| 6 | 秒级直播链在生产可用 | ? 待人工 | 见 §5：全部用例 monkeypatch `get_stream_writer`，端到端未跑过 |

**判定：满足。** 传输分工是明确设计而非缺陷：`process_event` SSE 覆盖 decompose→clarify 的秒级直播，research→merge 由容器回调续驱（不在任何 graph 运行上下文内），后半程由 2s 快照承担——这一分工在 110-01 F-1 与 `conversation_service.py:2475-2478` 都写明了。我另核实：三处 `astream` 只有主流式路径（`:1696`）消费 `custom` chunk，两处 resume 路径只取 `values`——与上述分工自洽，那两条路径本就没有活着的 SSE 连接。

### SC-2 —— 调研容器日志对用户可见（OBS-02）

| # | 可观测事实 | 状态 | 证据 |
|---|-----------|------|------|
| 1 | 根因（读取谓词）已放宽，走独立字段 | ✓ VERIFIED | `runtime["plan_research_sessions"]` 是独立分支、独立键，绝不 append 进 `deep_sessions`；有专门用例断言不混入 |
| 2 | 归属链上无容器可写键（MN-01 修复后） | ✓ VERIFIED | `RepoResearchTask` 当驱动：`session`/`repository`/`subagent_session` 我逐个确认为真 FK（`delivery/models/research_task.py:41/48/54`），`subagent_session` 由 `ResearchService.mark_running`（`research_service.py:72-80`）在服务端派发后回填，唯一调用点 `research_adapter.py:219`。`last_output` 从此只用于取日志内容 |
| 3 | 按仓一张卡、复用 `DeepAnalysisCard` 零改动 | ✓ VERIFIED | diff stat 逐字核对：`DeepAnalysisCard.vue` / `DeepAnalysisGroup.vue` / `useDeepAnalysisLog` 均不在改动清单内 |
| 4 | 仓库名服务端解析，任何情况不回显裸 UUID | ✓ VERIFIED | 后端批量查 `Repository.name` 回填 `repository_name`，解析不出回 `""`；前端三级兜底末级是常量「未知仓库」 |
| 5 | 容器日志出网前脱敏 | ✓ VERIFIED | 读取面逐条 `redact_secrets_in_text(content)`（写入侧 `_append_runtime_log` 不脱敏，读取面补上了） |
| 6 | 编排完成后仍可查 | ✓ VERIFIED | 日志组不随终态卸载，整组可折叠；MN-02 的 `converged` 短路刻意**不**清空前端已有的那份 |

**判定：满足（自动化层面）。** 端到端仍需真实容器验收，尤其 `plan_session_id` 与 tool result `session_id` 的跨进程字符串相等——见 §5。

### SC-3 —— 阶段时间线 + 失败停在哪一步、原因是什么（OBS-03）

| # | 可观测事实 | 状态 | 证据 |
|---|-----------|------|------|
| 1 | 前端展示阶段时间线 | ✓ VERIFIED | `OrchestrationStageTimeline.vue` 挂在编排气泡内、`OrchestratedPlanCard` 之前；终态收敛为一行而不是消失 |
| 2 | 失败原因走 7 值闭集，绝不回显原始取值 | ✓ VERIFIED | 服务端 `compress_failure_reason` 返回值恒 ∈ 闭集（闭集外走 `unknown`）；前端 `FAIL_REASON_LABELS` 未命中回退「未知原因」。我逐条回查了闭集里 6 个非 `unknown` 取值的真实产出点，全部存在（`resume.py:48` / `expire_pending_clarifications.py:78` / `builtin_processes.py:258` / `engine.py` 的 `unknown_process_type` `unknown_stage` `exception` 三路） |
| 3 | 失败落在真实 stage key 上而不是 `__failed__` | ✓ VERIFIED | 关键实读：`_fail` 与 `STAGE_FAILED` 转移都**保持 `current_stage = from_stage`**（`convergence_session_service.py:167/243-244`），所以 `failure.stage` 是 `research` / `merge` 这样的真 key，`failIndex` 解析得出、红步落得准 |
| 4 | **后半程**（research / merge）失败时时间线翻红、给出闭集原因 | ✓ VERIFIED | 该期间轮询已起（tool 返回 `__blocking_task__` ⇒ `currentPhase='waiting'` ⇒ `scheduleRuntimePoll`），快照带 `status=failed` + `failure` 到达 |
| 5 | **前半程**（decompose / route / recall / classify / clarify）失败时时间线翻红 | ✗ FAILED | 见下方 GAP-1，verifier 可执行探针实测 |

**判定：部分满足 —— 记为 gap。**

#### GAP-1：前半程失败时，时间线持续宣称「正在生成技术方案」

这一条我**没有**采信 110-UI-REVIEW 的转述，而是自建了两条断言式探针（跑完即删）直接测 `buildOrchestrationTimeline`：

| 输入 | phase | 标题 | live region | 步态 |
|------|-------|------|-------------|------|
| `snapshot: null` + `decomposed` / `routed` / `process.session.failed` | `running` | 正在生成技术方案 | 当前阶段：召回 | 拆分:completed / 路由:completed / **召回:running** / 其余 pending |
| 同上但带 `status=failed` 快照 | `failed` | 方案编排失败 | — | 拆分:completed / 路由:completed / **召回:failed（该阶段执行出错）** / 其余 pending |

两条探针**均通过**，即当前实现确实如此。链路成因（三条实读事实叠加）：

1. `isFailed` 只取 `snapshot?.status`（`useOrchestrationTimeline.ts:439-441`），事件流没有任何翻状态的兜底；
2. 后端**确实**把失败事实推到了前端——`_fail` 走 `_emit_event(EVENT_PROCESS_SESSION_FAILED, …)` 并 fan-out，事件也确实进了 store 的桶（`case 'process_event'` 不做白名单过滤）——但 `foldEvents` 刻意不认这个事件名，`TRANSITION_TO_STAGE` 的注释写的是「它们不推进 stage，只翻状态」，而「翻状态」这半句没有落点；
3. 前半程期间 `bucket.snapshot` 恒为 `null`：`pollConversationRuntime` 只由 `scheduleRuntimePoll` 起，我把 11 个调用点逐个看过，没有一个发生在 SSE 直播期间（`chat.ts:2407` 的 `finally` 分支只在 `waiting` / `waiting_clarification` 收尾时起轮询；前半程失败时 tool 返回失败结果、graph 继续走到 `completed`，这个分支不成立）。轮询循环也不会从上一轮存活——`runtime.active` 一 false 就 `stopRuntimePolling()`。

**用户看到什么：** 工具气泡的 pill 变失败、错误文本照常显示，但它上方的时间线仍在说「正在生成技术方案」、把出错那一步画成进行中。刷新页面才自愈。这正好命中本里程碑要消灭的形态，而且 OBS-03 的字面要求就是「失败停在哪一步一目了然」。

**为什么算 gap 而不是「已接受债务」：** 数据已经在前端手里（事件已入桶），缺的只是折叠逻辑里的一个分支；且 71 条穷举 spec 里**没有任何一条**把当前行为锁死（`snapshot: null` 只出现两次，都是 classify 可见性用例），修复不需要改既有断言。

**为什么不阻断整个 phase：** 后半程失败（跨仓调研 / 融合校验耗尽，实践中占多数）表现完全正确；SC-1、SC-2 与 SC-3 的时间线本体均已交付。

### SC-4 —— 与 Phase 107 降级提示复用同一事件源

**判定：部分满足（PARTIALLY，按字面读法无法完全成立）。**

字面要求是「实时进展与 Phase 107 的降级提示**复用同一事件源**（`ConvergenceSessionEvent`），未新建平行推送通道，同一状态不存在两处各自实现」。两条实读事实让「复用」这个动词失去对象：

1. Phase 107 的降级 UI 读的是 tool-result 里的路由 trace，**不是**事件表（110-CONTEXT 裁决 D-3 已勘察确认，并明确本相位不回改）；
2. 更根本的是 `RoutingDecisionPanel` 在 SPA 里**根本没有挂载点**——2026-05 已退役，且有锁测试断言其不渲染（`partsApiIntegration.spec.ts:178`）。没有第二个渲染者，也就没有第二个主体可供「复用」。

本相位实际交付的是可辩护的弱化版本，三条都成立：

| 子命题 | 状态 | 证据 |
|--------|------|------|
| 新进度面事实来源唯一 | ✓ | 全部读 `ConvergenceSessionEvent`（SSE 与快照两条链同一张表、同一把净化筛子、同一个 `row.ts.isoformat()` 去重键） |
| 未新建平行推送通道 | ✓ | 复用既有 chat SSE 连接，只在既有信封协议里多一个 `type`；`ALL_EVENT_TYPES` 从 21 增至 22，无第二条连接、无第二个注册表（裁决 D-2） |
| 降级这个事实只有一个渲染者 | ✓ | 时间线只在「路由」步加 `warning` 角标、不写解释句；有专门用例断言编排气泡上不出现路由面板、不含「未经 LLM 推理」与「置信度」 |

**`RoutingDecisionPanel` 的缺席不计为 Phase 110 缺陷** —— 它先于本里程碑退役，且 110-CONTEXT 边界明确「不重做 107 已落地的降级提示」。记为里程碑级缺口（见 frontmatter `deferred`）。

附带一条实读观察（不构成缺陷）：`degraded` 键只在 RouterV2 产出 `snapshot.stage0` 时才进 payload（`builtin_processes.py:132/167`），skipped / stub router / v1_fallback 三种情形下该键缺失 ⇒ 角标不显示。110-05 的 must-have 显式规定「严格 `=== true`，缺失视为 false，绝不按 `router_version` 或候选内容自行推断」，实现与契约一致。

---

## 2. Must-have 计分

| 来源 | 总数 | 通过 | 部分 / 未达 |
|------|------|------|------------|
| ROADMAP Success Criteria | 4 | 2（SC-1 / SC-2） | SC-3 部分（GAP-1）、SC-4 部分（按简报裁定记录） |
| 110-01 PLAN（7 truths + 4 backstop） | 11 | 11 | — |
| 110-02 PLAN（9 + 4） | 13 | 12 | backstop「缺省时渲染结果与改动前逐像素一致」部分（LO-01） |
| 110-03 PLAN（8 + 6） | 14 | 14 | — |
| 110-04 PLAN（7 + 5） | 12 | 12 | — |
| 110-05 PLAN（11 + 5） | 16 | 16 | — |
| 110-06 PLAN（9 + 4） | 13 | 13 | — |
| 110-07 PLAN（9 + 5） | 14 | 14 | — |
| **合计** | **97** | **94** | **3** |

Requirements 覆盖：OBS-01 ✓ 满足；OBS-02 ✓ 满足（待真实容器验收）；OBS-03 ⚠️ 部分满足（GAP-1）。`.planning/REQUIREMENTS.md` 已把三条标为 Complete —— OBS-03 那条与本报告结论不一致，建议在缺口闭合前回退为进行中。

---

## 3. 高风险载重不变量逐条核验（post-fix 代码实态，非 SUMMARY 转述）

| # | 不变量 | 结论 |
|---|--------|------|
| 1 | `_emit_event` 永不抛；fan-out catch 覆盖 `RuntimeError` **与** `KeyError` | ✓ 持久化包 try/except，`_fanout_process_event` 整体 blanket `except Exception: pass`。两种形态各有独立用例（`test_get_stream_writer_runtime_error_is_swallowed` / `..._key_error_...`），后者的用例注释写明「只有 RuntimeError 那条时，收紧 `except` 不会有任何测试变红」——收紧防护真的锁住了 |
| 2 | `ts` 去重键跨链逐字节一致 | ✓ 两条链都是 `row.ts.isoformat()`（`convergence_session_service.py:379` / `conversation_service.py:2600`）。`test_ts_survives_database_round_trip_bit_for_bit` 显式比对「内存实例 vs DB 回读实例」，避开了两侧都读 DB 的自指断言 |
| 3 | 唯一一把筛子，`summary` 按**值类型**区分 | ✓ 快照侧 import `process_event_wire`，无第二份实现。`_DROP_IF_STR = {summary, error, detail}` 按 str 剥离，classify 的结构化 dict（`builtin_processes.py:218`）保留 —— 按键名一刀切会砍掉「新增 N · 改造 M」的唯一数据源 |
| 4 | 无自由文本抵达渲染路径 | ✓ 三层筛：恒剥离 12 键 → 按 str 剥离 3 键 → 残留 str 过 `redact_secrets_in_text` + 200 截断（兜住未知事件）。失败原因只走 7 值闭集。补一条实读观察：`knowledge.recalling` 的 `query` 键不在任一张表里、会出网（经脱敏 + 截断），但它是用户自己在自己会话里的检索串，且**没有任何渲染者**读它（`recallSummary` 只取 `hits`）—— must-have 的键清单里也没有它，不算违反 |
| 5 | plan_research 归属链上零容器可写键 | ✓ `RepoResearchTask` 驱动；三个绑定字段全是真 FK / DB 列；`subagent_session` 由服务端 `mark_running` 回填。附带语义收紧：stale 重派后每仓恒一张卡 |
| 6 | `orch_session` 预置 `None`，两支各自判空 | ✓ `conversation_service.py:2492` 预置在**两个 try 之外**，两支各有 `if orch_session is None` 显式早退；两个 try 刻意不合并；`runtime` 字面量预置两键保证类型恒定 |
| 7 | 日志组 `v-if` 与 `:sessions` 同一表达式 | ✓ 两处都是 `planResearchSessionsFor(item)`，逐字相同，过滤键为 `plan_session_id` |
| 8 | HI-01 修复：失败终态携 `session_id`；`error`/`is_error` 最后展开；兜底限于「还没有 result」 | ✓ `{**(result.metadata or {}), "error": …, "is_error": True}` —— 固定两键在**最后**，工具无法把 `is_error` 翻成 false（`ToolResult.metadata` 是 `agents/tools/base.py:47` 的真字段）。前端 `orchestrationSessionIdFor` 的兜底写成 `item.result ? '' : (store…)`，「有 result 但解析不出会话」整块不渲染，有专门用例 |
| 9 | MN-02 短路要三条件齐备（含「其下无在途容器」） | ✓ 令牌逐字匹配 + 会话终态 + `RepoResearchTask` PENDING/RUNNING 的 `aexists()` 取反。`test_live_research_container_blocks_the_short_circuit` 专锁第三条；`test_short_circuit_never_touches_the_event_table` 把事件表查询掐成抛异常，证明那次查询**根本没发生**而不只是结果被丢弃 |
| 10 | `SubStepTimeline` 泛化纯加性 | ⚠️ 功能行为对 `ExecutionNode` 逐字不变（`interactive` 默认 true、新字段全可选、`output_data.error` 50 字截断回退逐字保留，有回归用例组）。但新增了**无条件**的 `:title` 与失败行 `role="alert"`，两者对 `ExecutionNode` 同样生效 ⇒「逐像素一致」的表述不准确（LO-01，已接受债务） |
| 11 | Phase 109 不变量完好 | ✓ 编排卡片仍按 `resolveOrchestratedPlanData(item.result)` 逐条解析（`ChatMessageBubble.vue:1383`），`lastOrchestrationToolItemId` 只用于时间线 / 日志组的去重渲染位置且有专门边界回归锁；`chat/views.py` 只加了一个 query 参数，`_stream_events` 生成器体内的用户重绑（`:1487`）原样保留；`TechPlanCard` 的 `runtime.plan_id === codingPlanId` 守卫未被触碰 |
| 12 | 边界守住 | ✓ `RoutingDecisionPanel` / `DeepAnalysisGroup` / `DeepAnalysisCard` / `useDeepAnalysisLog` 零改动；`deep_analysis_progress` 未被救活（events.py 里那条常量与 store 里那个 case 均为既有代码，本次未触碰） |

---

## 4. 「第五个空转用例」的主动搜捕

简报要求主动找第五个「实现不存在也能通过」的用例。我按四类已知形态逐一搜：

| 已知形态 | 本 phase 的对应检查 | 结论 |
|---------|-------------------|------|
| stub 组件掩盖接线缺口 | `chatMessageBubble.parts.spec.ts` 的 110-07 组**不 stub** 两个新组件，绑定断言直接读 `findComponent(...).props('sessionId')` | 未复现 |
| 负向对照松到坏实现也过 | F-21 跨消息过滤那条**双向**断言（第二轮有 + 第一轮既无组、全文也不含第二轮仓名）；MN-02 那条把事件表查询掐成抛异常 | 未复现 |
| 一个 `it` 塞两条断言、前者遮后者 | 提交 `52857a33` 专门把「步骤行非交互」拆成两条独立用例；MN-02 的「不重发事件」与「不重发日志」也是分开两条，注释写明理由 | 未复现 |
| 断言在合并语义下恒真 | 去重用例写成「5 条，不是 8 条」，另有一条「同 event 同自然键但 ts 不同 ⇒ 两条都保留」作为反向锚 | 未复现 |

**新形态：找到一处，但性质相反 —— 不是空转用例，是「无人看守的输入组合」。** `useOrchestrationTimeline.spec.ts` 的 71 条穷举里，`snapshot: null` 只出现两次，两次都在 classify 可见性一节；「无快照 + 失败事件」这个组合从未被断言过，于是 GAP-1 得以在全绿套件下存活。这不是断言写松了，而是穷举表少了一维（快照有无 × 会话状态），值得在补 GAP-1 用例时把这一维补齐。

另附一处「测试与实现同源、但已被第二条用例救回」的记录：`test_snapshot_ts_is_isoformat_of_the_persisted_row` 两侧都从 DB 读，本身对「DB 往返丢精度」是自指的；紧邻的 `test_ts_survives_database_round_trip_bit_for_bit` 显式比对内存实例与回读实例，把这一维补上了。plan 在写的时候就点名要求了这条，执行也做到了。

---

## 5. 明确**未**验证的部分

1. **`process_event` 的端到端直播链从未真正跑通过。** 全部 fan-out 用例都 monkeypatch 掉 `langgraph.config.get_stream_writer`，「生产环境下它能否在 tool 调用栈里解析出 writer」是静态推断。我独立复核了三段：写入形状 `writer({"type": X, "data": Y})` 与 `graph.py` 的 8 处既有用法逐字同构；消费侧 `conversation_service.py:1699-1704` 的 `chunk["type"] == "custom"` → `AgentEvent(type=…, data=…)` 正好对上；`format_sse` 的 `{"type": …, **event.data}` 展开与信封五键无任何冲突（`message_id` / `run_id` 不重名）。即便这条链静默失效，退化也只是「2 秒跳一格」而非功能损失 ⇒ 记为人工验证项，不是缺口。
2. **无任何 plan 跑过真实编排。** 110-02..110-07 的验证全部是单元级。最高价值的实测项是 `plan_session_id` 与 tool result `session_id` 的跨进程字符串相等——两侧各有后端用例，端到端相等性未测量；若 UAT 看到「时间线在跑、日志组永不出现」，这个不等是第一嫌疑。
3. **真实容器、真实 Docker runner、真实读屏、真实浏览器视觉**：均无法程序化断言，已列入 `human_verification`。
4. **`ts.isoformat()` 的跨数据库精度**：round-trip 用例只在测试库配置下跑过。若生产库的 datetime 列精度低于内存值（例如秒级精度），去重键会失配、计数虚高。当前配置下已锁住，换库时需重跑该用例。

---

## 6. 已接受债务（3 条 LOW，verifier 复核后同意不阻断）

| ID | 内容 | verifier 独立复核 |
|----|------|------------------|
| LO-01 | `SubStepTimeline` 新增无条件 `:title` 与失败行 `role="alert"`，对 `ExecutionNode` 同样生效，「逐像素一致」的注释表述不准确 | **同意为 LOW。** 我确认两处都是 a11y 净收益、零功能行为变化，既有回归用例组（状态点色值 / `stepClick` / 50 字截断回退）全绿。正确处置是改注释而非收回改进 |
| LO-02 | 两处 110 新增行未过 `ruff format`（全角括号注释行、`has_classify` 换行） | **同意为 LOW。** 我独立跑了 `ruff format --diff`，确认这两处仍在且确实落在 110 新增行上；同时 `ruff check`（E,F,I,W）全部通过。纯格式、零行为影响 |
| LO-03 | `_emit_event` 的 per-event `logger.info` 仍在 | **同意为 LOW。** 该行是 pre-existing，110 未增加任何事件产出量；本 phase 自己新增的 fan-out 埋点严格走了 `debug` + `category="sampling"`，规范上合规。但它落在本次改动的函数里，且与本 phase 刚立的纪律相反，建议按评审给的形态（per-event 降 debug + 在 `create_session` / 终态转移留低频 INFO）单独处置 |

另记 110-UI-REVIEW 的三条（advisory，本报告不重复计分，但其中两条已并入 `human_verification`）：

- UI-HI-01 = 本报告的 **GAP-1**（我用可执行探针独立坐实，升格为 gap）；
- UI-MN-01「真直播的前半程不脉冲、2s 轮询的后半程才脉冲」：与 GAP-1 同根因（`shouldPulse` 也只看快照 status），修 GAP-1 时应一并考虑；属表达问题，不构成 SC 未达；
- UI-MN-02「日志组折叠按钮的 `aria-label` 盖掉可见文案」：我读码确认属实（`PlanResearchLogGroup.vue:100-108`，可见文案「方案调研 · N 个仓库」被 `aria-label="展开方案调研日志"` 覆盖，违反 WCAG 2.5.3 Label in Name / Level A）。注意同批的 `OrchestrationStageTimeline` 折叠按钮**没有**这个问题（纯图标按钮，`aria-label` 是它唯一的名称来源）。已列入人工验证。

---

## 7. 其它观察（不影响判定）

- **非 feature_list 流程下指针落在被隐藏的 classify 那一格时**（`recalled → classify` 是真实转移），可见的六步会全部呈 completed / pending、没有 running 步。classify 是零副作用 pass-through、瞬时穿过，观感窗口极短，不构成缺陷。
- **`converged` 短路期间 `bucket.snapshot.events` 为空数组**，但所有消费方读的都是合流后的 `bucket.events`（`OrchestrationStageTimeline.vue:75`），不受影响；`useOrchestrationTimeline` 从 snapshot 只取 `status` / `current_stage` / `has_classify` / `segment_count` / `failure` 五个权威字段，均不被短路清空。
- **`orchestration_seen` 令牌不构成越权面**：它只能让服务端**少**发数据，猜错或伪造都退化成全量，且短路前提含「逐字等于本对话最近一次编排会话」。

---

_Verified: 2026-07-31T09:52:00Z_
_Verifier: Claude (gsd-verifier)_
_Method: 逐文件读码（post-fix 实态）+ 四道自动化闸门实跑 + 2 条 verifier 自建可执行探针 + 12 条载重不变量独立复核；未采信 SUMMARY 与 REVIEW 的自报结论_
