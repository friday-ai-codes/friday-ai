---
phase: 110-process-observability
plan: 04
subsystem: ui
tags: [sse, pinia, orchestration, idempotency, dedup, runtime-snapshot, vitest]

# Dependency graph
requires:
  - phase: 110-01
    provides: "SSE 事件类型 `process_event` 与「信封 `ts` 由落库行回填」——前端去重键成立的前提；前端 `SSEEvent.type` 联合的另一半本 plan 补齐"
  - phase: 110-03
    provides: "`runtime[\"orchestration\"]` 八键 + `runtime[\"plan_research_sessions\"]`；以及「`active` 语义不迁就终态、修复点在前端」的交棒结论"
provides:
  - "六个前端契约类型（`ProcessEventEnvelope` / `OrchestrationRuntime` / `PlanResearchSession` / 三个枚举）+ `ConversationRuntime` 两个可选字段"
  - "按 `session_id` 分桶的编排原材料状态（`orchestrationSessions`），SSE 与快照两条链的**唯一**落点"
  - "`orchestrationEventKey` 去重键（event + ts + 自然键）与 `mergeOrchestrationEvents` 幂等归并"
  - "`applyOrchestrationRuntime`：独立于 `applyRuntimeSnapshot`，在 `runtime.active` 分流之前调用，编排终态得以到达 store"
affects: [110-05 折叠与摘要 composable, 110-06 时间线组件挂载, 110-07 按 plan_session_id 过滤气泡]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "双链合流：两条传输链写同一份 store 状态，组件不区分来源；store 只存原材料不做折叠"
    - "去重键 = 语义键(event) + 时间键(ts) + 自然键(repo_id/task_id/clarification_id)，让计数类摘要在 ts 对齐被破坏时仍正确"
    - "「独立函数 + 在分支判定之前调用一次」覆盖两条分支，而不是把新逻辑塞进一个语义不匹配的既有函数"

key-files:
  created:
    - web/src/stores/__tests__/chat.orchestration.spec.ts
  modified:
    - web/src/types/chat.ts
    - web/src/stores/chat.ts
    - web/src/auto-imports.d.ts

key-decisions:
  - "`applyOrchestrationRuntime` 是独立函数并在 `runtime.active` 分流之前调用一次——一处调用覆盖两条分支，而非在两条分支各写一次"
  - "`case 'process_event'` 放进既有 switch，自动继承前台守卫与中断守卫，不为它开后门"
  - "`orchestration` 为 null / 缺失时保持现有桶不动；`plan_research_sessions` 缺失时赋 `[]`（前者增量语义，后者全量语义）"
  - "清理点是切换会话（`selectConversation` / `createNewConversation` / `clearCurrentConversation` / `resetForkRuntimeState`），`resetStreamingState` 一行不碰"
  - "合并后按 `ts` 稳定升序（`Array#sort` 稳定），ts 相同的事件保持到达顺序"

patterns-established:
  - "半可信 payload 原样入桶：store 侧只读取去重用的自然键，不做属性访问链，形状意外交给消费方防御性读取"
  - "观测状态的写入点全程 try/catch 吞异常，绝不反噬对话主流程"

requirements-completed: [OBS-01, OBS-02, OBS-03]

# Metrics
duration: 18min
completed: 2026-07-31
---

# Phase 110 Plan 04: 前端编排进度契约与双链合流状态层 Summary

**SSE `process_event` 与 2s 运行时快照现在写同一份按 `session_id` 分桶的 store 状态，按 `(event, ts, 自然键)` 幂等去重；并且把 110-03 交棒过来的那个洞补上了——`applyOrchestrationRuntime` 在 `runtime.active` 分流之前调用，编排的 `done` / `failed` 终态终于能到达 store。**

## Performance

- **Duration:** 18 min
- **Tasks:** 3/3
- **Files created:** 1
- **Files modified:** 3
- **新增用例:** 25 条

## Accomplishments

- **两条链合流成一份状态，且真的是幂等的。** 双向都测了：先 SSE 后快照、先快照后 SSE，两次都断言事件数为 **5**（3 条重叠 + 2 条新增）而不是 8。只测一个方向会漏掉「合并函数只在某一侧做去重」的实现——负向对照里去掉去重后，正是这两条同时变红。
- **110-03 交棒的那半个修复落地了，并且有回归锁。** `applyOrchestrationRuntime` 是独立函数，在 `pollConversationRuntime` 的 `if (runtime.active)` 判断**之前**调用（源码 1222 行 vs 1223 行），一处调用覆盖两条分支。回归锁走**真实的 2s 轮询**（fake timers 推进）：第一拍 `active: true` 起轮询，终态那一拍 `active: false` + `status: 'done'`，断言桶里的 `snapshot.status === 'done'`。把调用挪进 `if (runtime.active)` 内部，这两条立刻红。
- **「不并进 `applyRuntimeSnapshot`」这条有独立的、可检出的断言。** `applyRuntimeSnapshot` 第一行是 `isStreaming.value = true`，在非活跃分支调用它会把输入框错误锁住。断言直接打在导出的 `applyOrchestrationRuntime` 上：`active: false` 的快照写进桶之后 `isStreaming` 不为 true。负向对照把两者合并（并让导出符号指向 `applyRuntimeSnapshot`）时，这条与上面两条一起变红——**三条一起红才说明它守的是「合并」而不只是「调用点错位」**。
- **去重键里的 `ts` 有专属检出用例。** 只有「同 `event`、同自然键、不同 `ts` ⇒ 两条都保留」这条在，去掉 `ts` 的退化才会被抓到。缺它的话该破坏静默通过——实测：加上后 NC4 精确红 1 条，其余 24 条全绿。
- **清理点的方向做对了，并且用例站在「编排完成那一刻」看它。** 桶在**切换会话**时清空，`resetStreamingState` 一行不碰。锁这条的用例走的是真实路径（非活跃 runtime 的 `restoreConversationRuntime`，其内部会调 `resetStreamingState`），断言桶仍在 3 条事件。把清理挪进 `resetStreamingState` 后，这条 + 两条终态用例一起红——顺带证明了「编排一完成时间线就消失」不是假想，而是同一处改动的直接后果。
- **未知事件与异常 payload 静默容纳，零 warn。** 未知事件名的用例断言它**在 `events` 里**（而不是只断言「不抛」）；`payload` 为 `null` / 字符串 / 数组 / `undefined` 四种形态各投一条，全部入桶。25 条用例统一 spy `console.warn` / `console.error` 并在 `afterEach` 断言零调用。

## Task Commits

1. **Task 1: 前端数据契约（types/chat.ts）** — `4be5a29a` (feat)
2. **Task 2: store 分桶状态 + process_event 分发 + applyOrchestrationRuntime 双链合流** — `af42ad50` (feat)
3. **Task 3: store 用例（双链合流 / 幂等 / 分桶隔离 / 终态可达 / 守卫）** — `f7dbfe6e` (test)
4. **auto-imports 生成物同步** — `63de2326` (chore)

## Files Created/Modified

- `web/src/types/chat.ts` — `SSEEvent.type` 联合加 `'process_event'` 并平铺四个信封键（`event` / `work_item_id` / `ts` / `payload`；`session_id` 复用既有键，同名不同义在注释里点名）；新增六个导出类型；`ConversationRuntime` 扩两个可选字段。+120 行。
- `web/src/stores/chat.ts` — 模块级 `orchestrationEventKey` / `mergeOrchestrationEvents` 纯函数与两个导出接口；store 内四个状态、`upsertOrchestrationBucket` / `applyOrchestrationRuntime` / `clearOrchestrationState` 三个函数、`case 'process_event'`；两处调用点与四处清理点。+213 行。
- `web/src/stores/__tests__/chat.orchestration.spec.ts` — 25 条：双链合流 6、终态可达 4、分桶隔离 2、清理点 2、守卫与兜底 8、`plan_research_sessions` 1、`orchestrationRuntimeActive` 2。
- `web/src/auto-imports.d.ts` — unplugin 生成物，随新导出符号更新（否则下次构建会产生游离 diff）。

## Decisions Made

- **`applyOrchestrationRuntime` 调用点选「分流之前一次」而不是「两条分支各一次」。** 后者能work，但它把「两条分支都要写」变成一条需要每次改动都记得维护的约定；前者让它成为控制流的结构性事实。负向对照里把它挪进 `if` 内部是一行改动，说明这条约定确实容易被无意破坏——所以除了位置本身，还有两条走真实轮询的回归锁在守。
- **合并函数对 `payload` 不做任何规整。** 类型上标 `Record<string, unknown>` 是为了与后端契约一致（110-05 的消费面按它写），但运行时值原样入桶：`null` / 字符串 / 数组都可能出现。自然键提取先判 `typeof === 'object' && !Array.isArray`，不做属性访问链。这条在注释里写明了，避免 110-05 误以为类型是运行时保证。
- **`orchestration` 缺失保桶、`plan_research_sessions` 缺失清空**，两者不对称是**语义决定的**：前者是「本对话最近一次编排」的增量补齐（后端降级返回 null 时不该抹掉已有进度），后者是全量列表（少一条就是真的少一条）。两条各有用例。
- **清理点铺到四处而非一处。** plan 只点名「切换会话」，实际实现放进了 `selectConversation` / `createNewConversation` / `clearCurrentConversation` / `resetForkRuntimeState` —— 后三者同样是「当前会话换了」的时刻，与它们既有的 `pendingClarifications` 清理并列。fork 那处尤其必要：fork 会切到一个全新会话，留着旧桶就是跨会话串渲染。
- **`orchestrationRuntimeActive` 的复位断言换了个观测位置。** 它在 `clearOrchestrationState` 里复位为 `true`，但 `selectConversation` 紧接着就会 `restoreConversationRuntime` 写入**新会话**的 `active`——所以在切换会话的用例里断言它为 `true` 是错的（详见 Deviations 1）。复位语义改由 `createNewConversation` 的用例守（那条路径后面没有 runtime 写入）。

## 可观测性自检（`.cursor/rules/observability-logging.mdc`）

| 检查项 | 结论 |
|---|---|
| 结构化事件 + kv | 不适用：本 plan 是前端 store，无 `structlog` 面。**新增代码零日志**——`case 'process_event'` 是高频路径（编排在途每秒数条），打日志即刷屏 |
| 高频循环禁 INFO | ✅ `rg 'console\.(warn\|error)' src/stores/chat.ts` 改动前后同为 **3 处**（中断超时 / routing trace 解析 / 未知 SSE 事件），位置未变；`process_event` 进 switch 后不再落入第三处那个 `default` 分支 |
| 脱敏不可绕过 | 出网净化在后端（`sanitize_process_event_payload`，110-01/110-03 共用同一把筛子）；前端不新增任何渲染路径，store 只存原材料 |
| 触发用户绑定 | 不适用（前端内存态） |
| 观测不反噬业务 | ✅ `applyOrchestrationRuntime` 与 `case 'process_event'` 各包一层 `try/catch` 吞异常；异常 payload 四形态用例证明不抛 |
| 新增请求入口 / LLM 调用 / 召回 / 队列 / webhook | 无（复用既有 `GET .../runtime/` 轮询与既有 SSE 通道，零新增网络面） |

## Deviations from Plan

### 1. [Rule 1 - Bug] 「切换会话后 `orchestrationRuntimeActive` 复位为 true」的断言拆到另一条路径

- **Found during:** Task 3
- **Issue:** plan 的 Task 3 要求「切换会话后复位 `true`」与「切换会话后桶被清空」写在一起。实测首轮红：`selectConversation` 清理之后会 `await restoreConversationRuntime(newId)`，后者调 `applyOrchestrationRuntime` 写入**新会话**的 `runtime.active`。新会话若是非活跃（用例里就是），该值正确地变回 `false`。这是实现正确、断言错误——`orchestrationRuntimeActive` 的语义是「最近一次快照里的 active」，切换会话后它应当反映**新会话**的事实，而不是停在初值。
- **Fix:** 拆成两条。切换会话那条只断言桶 / `activeOrchestrationSessionId` / `planResearchSessions` 被清空；复位语义改由新增的 `createNewConversation` 用例守——那条路径清理之后不再有 runtime 写入，是观测「复位为 true」的唯一干净位置。覆盖比 plan 原文更严（多了一条 `createNewConversation` 的清理路径）。
- **Files modified:** `web/src/stores/__tests__/chat.orchestration.spec.ts`
- **Commit:** `f7dbfe6e`

### 2. [Rule 3 - Blocking] 提交 `web/src/auto-imports.d.ts` 生成物

- **Found during:** Task 3 收尾走查
- **Issue:** store 新增导出符号（`orchestrationEventKey` + 两个 interface）后，unplugin-auto-import 在跑 vitest 时重新生成了这份**已入库**的声明文件，留下游离 diff。
- **Fix:** 单独一个 chore commit 提交生成物，避免下次任何人跑构建都看到一份莫名其妙的改动。
- **Files modified:** `web/src/auto-imports.d.ts`
- **Commit:** `63de2326`

---

**Total deviations:** 2 auto-fixed（1 个用例缺陷、1 个生成物同步）
**Impact on plan:** 都在 plan 边界内，无范围蔓延。第 1 条让覆盖比原文更严。

## Verification

### 测试

| 命令 | 结果 |
|---|---|
| `CI=true pnpm vitest run --watch=false src/stores/__tests__/chat.orchestration.spec.ts` | **25 passed** |
| `CI=true pnpm vitest run --watch=false src/stores` | **144 passed / 17 files**（改动前 119 / 16） |
| `CI=true pnpm vitest run --watch=false src/components/chat src/stores src/composables`（plan 的路径集） | **505 passed / 52 files**（基线 480 / 51，+25，零回归） |
| `CI=true pnpm vitest run --watch=false src/components/chat src/stores src/composables src/components/execution` | **556 passed / 56 files**（基线 531 / 55，+25，零回归） |

🔴 **基线口径更正**（实测，两次都在本 worktree 的 `HEAD` 上跑过）：

- plan `<verification>` 写的「基线 **504 passed / 54 files**」与实测不符。本 plan 路径集（`src/components/chat src/stores src/composables`）的真实基线是 **480 passed / 51 files**。
- 编排任务给的「**531 / 55**」是**另一个路径集**的数：加上 `src/components/execution`（110-02 新建的 `SubStepTimeline.spec.ts` 在那里，51 条）后恰好 531 / 55。两个数都对，只是量的不是同一把尺。
- 两个口径本次都跑了并都零回归，`N ≥ 基线 + 18` 按 480 算成立（+25）。

全部命令均带 `CI=true` 并按 `Tests N passed` 行判定，不看退出码。

### 类型与 Lint

- `pnpm vue-tsc --noEmit -p tsconfig.json` → **退出码 0**（Task 1 / Task 2 / 收尾各跑一次）。
- `pnpm eslint src/stores/chat.ts src/types/chat.ts src/stores/__tests__/chat.orchestration.spec.ts` → **零 error**。

### 依赖

- `git diff --exit-code web/pnpm-lock.yaml` → **退出码 0**，零新增依赖。T-110-04-SC 缓解成立。

### 源码走查（验收条款逐条）

| 条款 | 核验方式 | 结论 |
|---|---|---|
| `applyOrchestrationRuntime` 调用行号 < `if (runtime.active)` | `rg -n` | ✅ 1222 < 1223 |
| `applyRuntimeSnapshot` 体内无 `applyOrchestrationRuntime` / 无 `orchestrationSessions` 写 | 函数区间 1020–1158 内 `rg` 零命中 | ✅ |
| `resetStreamingState` 体内无编排状态清空 | 四处 `clearOrchestrationState`（605 / 655 / 876 / 901）均在 `resetStreamingState`（909）之外 | ✅ |
| `case 'process_event'` 在既有 switch 内且无 `console.warn/error` | 实读 + `rg` | ✅ 3 处 console.warn 全为 pre-existing |
| 去重键含三选一自然键 | `orchestrationNaturalKey` 读 `repo_id ?? task_id ?? clarification_id` | ✅ |
| store 内无阶段中文标签 / 状态机 / 摘要文案 | `rg "'拆分'\|'路由'\|'召回'\|'澄清'\|'并行调研'\|'融合'"` → **0 命中** | ✅ |
| `ConversationRuntime` 两个新字段均可选 | 实读 | ✅ |

## 负向对照（全部 7 条执行并还原）

| # | 破坏方式 | plan 预期变红 | 实际变红 | 结果 |
|---|---|---|---|---|
| 1 | `applyOrchestrationRuntime` 调用挪进 `if (runtime.active)` 内部 | 终态两条 | `active: false 时 done 仍到达` + `active: false 时 failed + failure 完整到达` | ✅ 2 failed / 23 passed |
| 2 | 并进 `applyRuntimeSnapshot`（导出符号一并指向它） | 终态两条 + isStreaming | 上述两条 **+** `applyOrchestrationRuntime 不把 isStreaming 置 true` | ✅ 3 failed / 22 passed |
| 3 | 去掉去重（合并时直接 concat） | 双向幂等两条 | `先 SSE 后快照` + `快照先 / SSE 后`（均变 8 条） | ✅ 2 failed / 23 passed |
| 4 | 去重键去掉 `ts`（只按 event + 自然键） | 需专属用例 | `同 event 同自然键但 ts 不同 ⇒ 两条都保留` | ✅ **1 failed / 24 passed**（专属用例成立，其余 24 条对该破坏完全不敏感——这正是它必须存在的证明） |
| 5 | 清理挪进 `resetStreamingState` | 「桶仍在」一条 | `流结束后桶仍在` **+** 终态两条（轮询非活跃分支末尾就调 `resetStreamingState`，刚写进去的快照当场被抹） | ✅ 3 failed / 22 passed |
| 6 | `case 'process_event'` 按事件名白名单过滤 | 「未知事件名入桶」一条 | `未知事件名正常入桶` **+** `payload 四形态仍入桶`（后者用的也是构造事件名） | ✅ 2 failed / 23 passed |
| 7 | `orchestration` 为 null 时清空桶 | 「null 不清空」一条 | `orchestration 为 null 不清空` **+** `流结束后桶仍在` + `切换会话后桶被清空` + `老后端 runtime 桶保持不变` | ✅ 4 failed / 21 passed |

**粒度说明**：对照 2 不只是「把调用挪个位置」，而是同时把导出符号指向 `applyRuntimeSnapshot`——只挪调用位置等价于对照 1，无法区分「调用点错位」与「函数被合并」这两种不同的坏实现。三条同时红才证明 isStreaming 那条断言守的是后者。

还原方式为 `git checkout -- web/src/stores/chat.ts`（逐文件，未使用任何 blanket reset / clean）。还原后复跑：路径集 **505 passed**、超集 **556 passed**、`vue-tsc` 退出码 0、`git status` 干净。

## Issues Encountered

- 首轮一条用例红，是**用例自身**的缺陷而非实现缺陷（见 Deviations 1）：`orchestrationRuntimeActive` 的复位断言放错了观测位置。
- ESLint `test/prefer-lowercase-title`：一条用例名以 `SSE` 开头被判为大写起首，改为「先 SSE 后快照」。

## Threat Flags

无。本 plan 未引入网络端点 / 鉴权路径 / 文件访问模式 / 信任边界上的 schema 变更；`threat_model` 5 条 disposition 全部落地：

| Threat ID | 落地形态 |
|---|---|
| T-110-04-01 | `case` 置于既有前台守卫之后；「后台会话流不写桶」用例 |
| T-110-04-02 | 纯字面读取 + 两处 `try/catch`；`null` / 字符串 / 数组 / `undefined` 四形态用例 |
| T-110-04-03 | 去重键含 `ts` + 自然键；双向幂等两条 + 「ts 不同则各自保留」一条（对照 3 / 4 证实两者守不同的点） |
| T-110-04-04 | store 只存原材料；「无阶段标签 / 状态机 / 摘要文案」走查 `rg` 零命中 |
| T-110-04-SC | 零新增依赖，`git diff --exit-code web/pnpm-lock.yaml` 退出码 0 |

## Known Stubs

无。本 plan 只做状态层，不做渲染——这是 plan 明确划定的边界，不是未完成的桩。折叠与摘要计算归 110-05，组件挂载归 110-06。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **110-05（折叠与摘要 composable）** 可直接从 `orchestrationSessions[sessionId]` 取 `{ snapshot, events, eventsTruncated }` 算。三条约束随桶交付：① 阶段指针取 `snapshot.current_stage`（权威），事件流只用于算摘要；② 计数类摘要按**去重自然键集合**算（`repo_id` / `clarification_id`），只有无自然键的融合轮次依赖 `ts`；③ `events[].payload` 是半可信结构，类型上的 `Record<string, unknown>` 不是运行时保证，必须纯字面读取。
- **110-06（组件挂载）** 按 UI-SPEC §A.7 用 `activeOrchestrationSessionId` 绑会话；中断判定用 `orchestrationRuntimeActive`（初值 `true`，一次快照都没到达时不判中断）。
- **110-07** 需要的 `plan_session_id` 在 `planResearchSessions[]` 上逐条携带，整形过程未丢字段（有用例断言）。
- **未验证面**：本 plan 全程为单测，未跑一次真实编排。「SSE 与快照的同一条事件 `ts` 逐字符一致」在后端两侧各有用例，但**跨进程的端到端一致性尚未实测**——若 110-06 落地后 UAT 观察到计数虚高，第一嫌疑就是这条。

## Self-Check: PASSED

- `web/src/stores/__tests__/chat.orchestration.spec.ts` 存在于磁盘；`web/src/types/chat.ts` 含 `ProcessEventEnvelope`、`web/src/stores/chat.ts` 含 `applyOrchestrationRuntime` 三个 `contains` 断言字面量均命中。
- 四个 commit（`4be5a29a` / `af42ad50` / `f7dbfe6e` / `63de2326`）均可在 `git log` 中检索到。

---
*Phase: 110-process-observability*
*Completed: 2026-07-31*
