---
phase: 110-process-observability
plan: 05
subsystem: ui
tags: [pure-function, timeline, state-machine, idempotency, closed-set, vitest, a11y]

# Dependency graph
requires:
  - phase: 110-02
    provides: "`TimelineStepItem` 泛化契约（6 态 status + 可选 summary / badge / pulse）——本 plan 的输出直接是它的数组"
  - phase: 110-04
    provides: "store 桶 `{ sessionId, snapshot, events, eventsTruncated }` 的实际形状，以及「payload 是半可信结构、类型不是运行时保证」的交棒结论"
provides:
  - "`buildOrchestrationTimeline`：快照 + 事件流 → `TimelineStepItem[]` + phase / title / doneCount / totalCount / liveMessage 的纯函数"
  - "`resolveRepoName`：仓库名解析与「绝不回显裸 UUID」兜底（110-07 日志组复用同一份，避免两处各写）"
  - "`STAGE_ORDER` / `STAGE_LABELS` / `FAIL_REASON_LABELS` / `TRANSITION_TO_STAGE` / `COPY` 五个模块常量"
  - "71 条穷举用例，含四条守卫用例（错位 / 回退转移 / 自然键去重 / 调研分母）"
affects: [110-06 时间线组件挂载, 110-07 调研日志组的仓库名解析]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "把用户可见的全部判定逻辑抽成纯函数，让每条规则可用固定输入穷举断言 —— DOM 断言天然松，「含某串」对错误实现常常也为真"
    - "序号在完整键集上算、可见性过滤放到最后一步，可选步的隐藏不影响任何序号"
    - "闭集 map + `?? 兜底常量`，未命中一律回退，绝不回显上游原值"
    - "计数走去重集合而非累加，自然键（repo_id / clarification_id）优先、无自然键才退回 ts"

key-files:
  created:
    - web/src/composables/useOrchestrationTimeline.ts
    - web/src/composables/__tests__/useOrchestrationTimeline.spec.ts
  modified:
    - web/src/auto-imports.d.ts

key-decisions:
  - "「一条证据都没有」时全 pending，而不是按 plan 伪码把指针落到 STAGE_ORDER[0] 让「拆分」显示 running —— 后者会在编排还没开始时就撒谎"
  - "失败时用 failIndex 而非 pointerIndex 作为进度分界（progressIndex），让「失败步之前 completed / 之后 pending」不依赖 failure.stage 与 current_stage 是否一致"
  - "F-16b 明文裁定原样执行：融合轮次继续按 `Set<ts>` 数，不去给 `architect_merge_adapter.py` 的 payload 加 `attempt`"
  - "自然键缺失时统一退回信封 `ts`（一个 helper 覆盖 repo_id / clarification_id 两处），而不是丢弃该事件"

requirements-completed: [OBS-01, OBS-03]

# Metrics
duration: 10min
completed: 2026-07-31
---

# Phase 110 Plan 05: 编排时间线折叠纯函数 Summary

**把「一堆事件 + 一份快照 → 一条六步（+ 可选第七步）时间线」的全部判定做成一个零依赖纯函数（536 行），并用 71 条固定输入用例把每条用户可见规则钉死；9 条负向对照逐条破坏后全部命中 plan 点名的那条测试。**

## Performance

- **Duration:** 10 min（06:40:31Z → 06:50:08Z）
- **Tasks:** 2/2
- **Files created:** 2 · **modified:** 1（生成物）
- **新增用例:** 71 条

## Accomplishments

- **模块真的是纯的，并且这条有机械抓手。** `rg -n "^import"` 只有两行，全部是 `import type`；零 vue / pinia / store / api / 请求 / DOM。这不是风格洁癖：本 phase 用户可见的正确性全落在这段逻辑里，埋进组件后每条规则只能靠挂 DOM 验证，而 DOM 断言对错误实现常常也为真（这正是本里程碑前两次被咬到的形状）。
- **错位守卫是真的守得住。** 序号在完整 7 键 `STAGE_ORDER` 上算，可见性过滤是函数的倒数第三行。负向对照 1（迭代改用过滤后的数组、指针仍在完整数组上算）让 **11 条**用例同时变红，其中包括 plan 点名的错位守卫——说明这条实现约束是承重的，不是装饰。
- **回退转移与「最大序号」实现被精确区分开。** 临时指针取「按 ts 排序后最后一条可识别转移事件」的目标。负向对照 2 改成「见过的最大序号」后**精确红 2 条**（回退转移 + 乱序归并），其余 69 条对该破坏完全不敏感——这正是那两条必须存在的证明。
- **「单仓失败 ≠ 编排失败」有独立且不可替代的断言。** 负向对照 5（让 `repo.research.failed` 把调研步标红）**只红 1 条**：`单仓失败只进失败计数，该步 status 仍是 running`。断言写的是 `=== 'running'` 而不是 `!== 'failed'`——后者对把该步标成 `skipped` / `unknown` 的坏实现同样为真。
- **失败步之后的断言逐个 `=== 'pending'`。** 路由失败那条用例把召回 / 澄清 / 并行调研 / 融合四步各写一行 `toBe('pending')`；融合失败那条用 `toEqual([...5 个 'completed'])` 对整段前缀做全等比较。两处都没有出现「不等于 failed」这种能被坏实现钻过去的写法。
- **闭集回退有两道断言。** 未命中的 `reason_code` 不仅断言文案为「未知原因」，还断言 `JSON.stringify(view)` **整体不含** `weird_unmapped`——只断文案的话，把原值藏进别的字段（比如 liveMessage）仍能过。负向对照 8 证实这条：改成回显原值后该用例 + 「failure 缺失」那条一起红。
- **调研分母取实际容器数，且用例的 fixture 让分母取错立刻显形。** fixture 刻意造成「路由候选 5 个、实际派出 3 个容器」的分歧，断言 `2/3`。负向对照 4 把 `total` 改成 `candidates.length` 后变成 `2/5`，用例红。
- **零新增依赖、零 warn。** `git diff --exit-code pnpm-lock.yaml` 退出 0；71 条用例统一 spy `console.warn` / `console.error` 并在 `afterEach` 断言零调用。

## Task Commits

1. **Task 1: useOrchestrationTimeline.ts 纯函数实现** — `adc9b43e` (feat)
2. **Task 2: 穷举 spec（71 条）** — `ad0c6373` (test)
3. **auto-imports 生成物同步** — `1a7fa37b` (chore)

## Files Created/Modified

- `web/src/composables/useOrchestrationTimeline.ts` — **新建，536 行**。五个导出常量 + `buildOrchestrationTimeline` / `resolveRepoName` + 两个导出接口；内部拆为 `foldEvents`（事件折叠与去重集合）、七个 `*Summary` 函数、`buildInner`（状态机）、`conservativeView`（try/catch 兜底）。
- `web/src/composables/__tests__/useOrchestrationTimeline.spec.ts` — **新建，750 行 / 71 条**：模块常量 4、步骤集合与可见性 5、阶段指针 6、七套摘要 17、计数幂等 4、失败 11（含 6 个 `reason_code` 的 `it.each`）、中断 4、降级角标 5、终态与计数 2、live region 3、兜底 5。
- `web/src/auto-imports.d.ts` — unplugin 生成物，随新导出符号更新。

## Decisions Made

- **「一条证据都没有」时全 pending，而不是让「拆分」显示 running。** plan 的伪码写的是 `pointerStage = … : STAGE_ORDER[0]`，但 plan 自己的 Task 2 又要求「空输入 ⇒ 6 步**全 pending**」。两者只能取一个。取全 pending：`pointerIndex` 在无证据时为 `-1`，任何步的序号都 `>` 它，于是全 pending；`pointerStage` 仍按伪码回退到 `decompose`，只用于 live region 的标签。理由是语义——快照与事件都没有时我们**不知道**编排是否已经开始，把「拆分」画成进行中就是在没有依据的情况下报进度。组件侧本就有「至少一条已知事实才渲染」的门（UI-SPEC §A.5 条件 3），所以这个分支只是防御性默认值，与 `try/catch` 的保守视图取同一形状。
- **失败时的进度分界取 `failIndex` 而不是 `pointerIndex`。** 引入 `progressIndex = isFailed && failIndex >= 0 ? failIndex : pointerIndex`。若直接用 `pointerIndex`，在 `failure.stage` 与 `current_stage` 不一致时（后端两个字段各自演化的可能性是存在的）会出现「失败步在前、后面几步却显示 completed」的荒谬态。用失败步本身当分界，「其前 completed / 其后 pending」就成了结构性事实而非巧合。
- **自然键缺失时退回信封 `ts`，不丢弃事件。** 一个 `naturalKey(payload, field, ts)` helper 同时服务 `repo_id` 与 `clarification_id`。丢弃的话，`repo_id` 缺失的调研事件会让分母凭空变小、进度虚高；退回 `ts` 最多让同一仓被算成两个，方向上更保守。有专门用例锁这条行为（`0/2 个仓库完成`）。
- **F-16b 原样执行，一个字没改。** 融合轮次继续 `Set<ts>`，没有去动 `architect_merge_adapter.py`。裁定的四条理由在本 plan 的作用域内全部成立，执行中没有出现推翻它的新事实。
- **`COPY` 作为模块常量导出，接受它进入全局 auto-import。** 沿用 plan `<artifacts_produced>` 点名的符号名。潜在footgun 见「Issues Encountered」。

## 可观测性自检（`.cursor/rules/observability-logging.mdc`）

| 检查项 | 结论 |
|---|---|
| 结构化事件 + kv / `category` / `component` | 不适用：前端纯函数，无 `structlog` 面。**本模块零日志**——它在编排在途期间每次事件到达都会被重算（秒级数次），打日志即刷屏 |
| 高频循环禁 INFO | ✅ 模块内 `console.*` **零处**（`rg 'console\.' → 0 命中`）；71 条用例统一断言 `console.warn` / `console.error` 零调用 |
| 脱敏不可绕过 | ✅ 三道：① 服务端已剥离自由文本（110-01）；② 本模块源码中 7 个禁读键名逐个 `rg` 零命中；③ 失败原因走 6 值闭集 + `?? '未知原因'`，未受控值不回显（有序列化断言） |
| 触发用户绑定 | 不适用（前端纯计算，无请求、无落库） |
| 观测不反噬业务 | ✅ 函数级 `try/catch` 降级为保守视图，绝不向上抛；`events` 传非数组、事件项为 `null`、`payload` 为 `null` / 字符串 / 数组各有用例 |
| 新增请求入口 / LLM 调用 / 召回 / 队列 / webhook | 无（零网络面、零 LLM 调用——摘要全部取 payload 已有的结构化字段） |

## Deviations from Plan

### 1. [Rule 1 - Bug] 空输入的指针语义按 plan 的用例要求定，而非按 plan 的伪码

- **Found during:** Task 1
- **Issue:** plan `<action>` 第 4 点的伪码要求无证据时 `pointerStage = STAGE_ORDER[0]`（⇒「拆分」为 `running`），但同一 plan 的 Task 2 要求「空输入 ⇒ 6 步**全 pending**」。两条互斥。
- **Fix:** 指针索引与指针标签拆开：`pointerIndex` 在无证据时为 `-1`（全 pending），`pointerStage` 仍按伪码回退 `decompose`（只供 live region 取标签）。取「全 pending」的理由见「Decisions Made」第 1 条。
- **Files modified:** `web/src/composables/useOrchestrationTimeline.ts`
- **Commit:** `adc9b43e`

### 2. [Rule 3 - Blocking] 提交 `web/src/auto-imports.d.ts` 生成物

- **Found during:** Task 2 收尾走查
- **Issue:** 新增导出符号后 unplugin-auto-import 在跑 vitest 时重新生成了这份**已入库**的声明文件，留下游离 diff（与 110-04 Deviation 2 同因）。
- **Fix:** 单独一个 chore commit。
- **Files modified:** `web/src/auto-imports.d.ts`
- **Commit:** `1a7fa37b`

---

**Total deviations:** 2 auto-fixed（1 处 plan 内部自相矛盾的裁定、1 处生成物同步）
**Impact on plan:** 均在 plan 边界内，无范围蔓延。第 1 条是在 plan 的两条要求里选了更保守的那条。

## Verification

### 测试（全部带 `CI=true`，按 `Tests N passed` 行判定，不看退出码）

| 命令 | 改动前 | 改动后 |
|---|---|---|
| `src/composables/__tests__/useOrchestrationTimeline.spec.ts` | — | **71 passed / 1 file** |
| `src/composables` | **85 passed / 10 files**（实测，用 `--exclude` 排除新 spec） | **156 passed / 11 files**（+71） |
| `src/components/chat src/stores src/composables` | **505 passed / 52 files**（实测） | **576 passed / 53 files**（+71，零回归） |
| 上述 + `src/components/execution` | **556 passed / 56 files**（110-04 实测值） | **627 passed / 57 files**（+71，零回归） |

- Task 2 验收门 `N ≥ 既有基线 + 40`（按 `src/composables` 的实测基线 85 算）：**+71 ≥ +40 ✅**。
- 🔴 **基线口径更正（沿用 110-04 的更正，此处复核一致）**：plan `<verification>` 写的「基线 504 passed / 54 files」在本 worktree 的 `HEAD` 上不成立。三路径集实测 **505 / 52**，四路径集实测 **556 / 56**。两个数本次都在改动前后各跑过。

### 类型 / Lint / 依赖

| 项 | 结果 |
|---|---|
| `pnpm vue-tsc --noEmit -p tsconfig.json` | 退出码 **0**（Task 1 / Task 2 / 负向对照还原后各跑一次） |
| `pnpm eslint`（新增 2 个文件） | 退出码 **0** |
| `git diff --exit-code web/pnpm-lock.yaml` | 退出码 **0**，零新增依赖 |

### 源码走查（Task 1 验收条款逐条）

| 条款 | 核验方式 | 结论 |
|---|---|---|
| 模块只有类型 import | `rg -n "^import"` | ✅ 恰 2 行，均为 `import type` |
| `STAGE_ORDER` 长度 7 | 用例 `toEqual` 全等 + `toHaveLength(7)` | ✅ |
| 可见性过滤在序号计算**之后** | `STAGE_ORDER.map((stage, index) =>` 在 `allSteps.filter(...)` 之前 | ✅（负向对照 1 证实这个先后是承重的） |
| 临时指针取「最后一条」而非 `Math.max` | `foldEvents` 内直接覆写 `lastTransitionStage`，源码无 `Math.max` / 无序号比较 | ✅ |
| 调研计数用 `Set`，无累加写法 | 三个 `Set<string>` + `.add()`；源码零 `++` / 零 `+= 1` | ✅ |
| `total` 来自 `researchStarted` | `const total = folded.researchStarted.size` | ✅（负向对照 4 证实） |
| `FAIL_REASON_LABELS` 恰 6 键 + 一处兜底 | 用例断言键集全等；源码一处 `?? COPY.unknownReason` | ✅ |
| 7 个禁读键名零命中 | `rg -c` 逐个：`question` / `candidate_files` / `api_contracts_exposed` / `weight_config` / `repo_meta` / `stage0` / `stage1` | ✅ **全部 0** |
| `liveMessage` 构造处不含计数 | 三分支均只取标签与原因常量 | ✅（负向对照 9 证实） |
| 无 `console.*` | `rg 'console\.'` | ✅ 0 命中 |
| 产物 ≥ 180 行 | `wc -l` | ✅ **536** |

## 负向对照（9 条全部执行 → 确认变红 → 还原）

| # | 破坏方式 | plan 点名必红的测试 | 实际变红 | 结果 |
|---|---|---|---|---|
| 1 | 可见性过滤提到序号计算之前（迭代用过滤后数组，指针仍在完整数组算） | 错位守卫用例 | **错位守卫** + 指针 4 条 + 澄清 1 条 + 单仓失败 1 条 + 失败 1 条 + 中断 3 条 | ✅ 11 failed / 60 passed |
| 2 | 临时指针改成「见过的最大序号」 | 回退转移用例 | **回退转移** + 乱序归并 | ✅ **2 failed / 69 passed** |
| 3 | 调研计数改成事件条数累加 | 「同 repo_id 不同 ts 只算一次」 | **同 repo_id 不同 ts** + 同 ts 重复投递 | ✅ 2 failed / 69 passed |
| 4 | `total` 改成 `candidates.length` | 调研摘要用例（`2/3` → `2/5`） | **分母取实际容器数** + 单仓失败（同一 fixture） | ✅ 2 failed / 69 passed |
| 5 | `repo.research.failed` 把调研步标红 | 「调研步 status 不为 failed」 | **单仓失败只进失败计数** | ✅ **1 failed / 70 passed** |
| 6 | `degraded` 判定从 `=== true` 改成真值判断 | `degraded: 'true'` 字符串用例 | **degraded 为字符串 true ⇒ 无角标** | ✅ **1 failed / 70 passed** |
| 7 | `waiting_clarification` 也算中断 | 「waiting_clarification + 不活跃仍是 running」 | **不活跃 + waiting_clarification 不算中断** | ✅ **1 failed / 70 passed** |
| 8 | 未命中的 `reason_code` 原值回显 | 「序列化后不含 `weird_unmapped`」 | **未命中 reason_code** + failure 缺失回退 | ✅ 2 failed / 69 passed |
| 9 | 把 `{done}/{total}` 写进 `liveMessage` | live region 不含 `/` 的断言 | **在途 live region 不含调研计数** | ✅ **1 failed / 70 passed** |

**粒度说明**：

- 对照 5 / 6 / 7 / 9 各只红 **1 条**——其余 70 条对这些破坏完全不敏感，这正是那 4 条断言必须单独存在的证明（如果它们缺失，这些破坏会静默通过）。
- 对照 1 红 11 条属**预期的高扇出**：序号错位是全局性失真，几乎每条依赖阶段状态的用例都会被波及；plan 点名的错位守卫在其中。对照 1 的破坏形状取「迭代用过滤后的数组、`pointerIndex` 仍在完整数组上算」——只把 `STAGE_ORDER.filter()` 整体前移（指针也一并在过滤后数组上算）是**良性**的，前后两个数组同步移位不会产生错位。plan 描述的症状（「融合已经在跑，界面上还显示在调研」）对应的正是这个「混用」形状，因此按它来破坏。
- 对照 2 的 2 条、对照 3 的 2 条、对照 8 的 2 条都是「点名那条 + 一条同族收紧」，不是失真。

还原方式一律为 `git checkout -- src/composables/useOrchestrationTimeline.ts`（逐文件，**未使用任何 blanket reset / clean / stash**）。9 条全部还原后复跑：spec **71 passed**、四路径集 **627 passed / 57 files**、`vue-tsc` 退出码 0、`eslint` 退出码 0、`git status` 对已提交版本干净。

## must_haves 逐条核对

| # | truth | 证据 |
|---|---|---|
| 1 | 六标签取 ROADMAP SC-1 原文，分类是可选第七步 | `STAGE_LABELS` 常量；用例 `toEqual(['拆分','路由','召回','澄清','并行调研','融合'])` 全等 |
| 2 | 非 feature_list 时分类**整步不出现** | 断言 `names(view)` **不含** + `filter(...)` 长度 0 + 总长 6（三重，均为「不存在」而非「存在且置灰」） |
| 3 | 序号在完整 7 键上算、之后再过滤 | 错位守卫用例 + 负向对照 1（11 条红） |
| 4 | 指针以快照为权威、事件为临时、冲突不 warn | 「快照优先」「无快照取事件」「未知 key 退回事件」三条 + 显式 spy 断言 |
| 5 | 摘要全取已有结构化字段、缺数据即为空、不产「暂无」 | 七套摘要 17 条；`segment_count: null` / `candidates` 字符串 / `hits` 字符串 / `summary` 非 dict 四条均断言 `toBeUndefined()` |
| 6 | 计数按自然键去重，重复投递不翻倍 | 幂等 4 条 + 负向对照 3 |
| 7 | 调研分母取实际容器数 | `2/3`（候选 5）用例 + 负向对照 4 |
| 8 | 单仓失败不标红该步 | `status === 'running'` 精确断言 + 负向对照 5（只红 1 条） |
| 9 | 失败原因 7 值闭集、未命中回退、绝不回显原值 | `it.each` 6 条 + 未命中回退 + 序列化不含原值 + 负向对照 8 |
| 10 | 澄清判 skipped 的精确规则 | 「已推进 + 无 clarification.*」⇒ skipped；「已推进 + 有 asked/answered」⇒ completed，两条对照 |
| 11 | 中断判定：`waiting_clarification` 不算中断 | 中断 4 条（running / waiting_event 判中断；waiting_clarification 保持 running + `pulse === false`）+ 负向对照 7 |
| 12 | **backstop** — payload 形状意外时该摘要为空、其余照常 | `candidates` 字符串那条同时断言「路由无摘要」**且**「拆分摘要照常」**且**「步骤数 6」 |
| 13 | **backstop** — 未知事件名静默忽略 | `brand.new.event` 用 `toEqual` 与不含它的结果**整体全等**比较 + 零 warn |
| 14 | **backstop** — `current_stage` 未知 key 退回事件指针、不崩、不清空 | 「未知 key」用例断言步骤数 6 + 召回 running；另有「`failure.stage` 未知 key ⇒ 零红步、步骤数不变」一条 |
| 15 | **backstop** — 纯函数，不读 store / 不发请求 / 无 Vue 副作用 | `rg "^import"` 恰 2 行 `import type`；spec 未 mock 任何依赖即可运行 |
| 16 | **backstop** — 解析异常吞掉降级、绝不上抛 | 函数级 `try/catch` + `conservativeView()`；`events` 非数组、事件项 `null` / 缺 `event`、`payload` 三形态共 4 条用例 |

## Threat Flags

无。本 plan 是纯前端计算，未引入网络端点 / 鉴权路径 / 文件访问模式 / 信任边界上的 schema 变更。`threat_model` 5 条 disposition 全部落地：

| Threat ID | 落地形态 |
|---|---|
| T-110-05-01（摘要文案泄漏） | 文案全部取 `COPY` 常量 + 结构化数值；7 个自由文本键名在本模块源码中 `rg` **零命中**；服务端已剥离（110-01）是第一道 |
| T-110-05-02（失败原因泄漏） | 6 值闭集 map + `?? '未知原因'`；用例断言 `JSON.stringify(view)` 不含未受控原值；负向对照 8 证实该断言有效 |
| T-110-05-03（前端自行推断降级） | 严格 `=== true`；`degraded` 缺失 / `false` / 字符串 `'true'` 三条用例；负向对照 6 只红字符串那条 |
| T-110-05-04（payload 形状意外冒泡） | 纯字面读取（`asRecord` / `asFiniteNumber` / `asNonEmptyString` 三个守卫）+ 函数级 `try/catch`；`null` / 字符串 / 数组 payload 各有用例 |
| T-110-05-SC（供应链） | 零新增依赖，`git diff --exit-code web/pnpm-lock.yaml` 退出码 0 |

## Known Stubs

无。本 plan 明确划界为「不写任何 `.vue`」——渲染归 110-06、调研日志组归 110-07。这是 plan 的边界，不是未完成的桩。

## Issues Encountered

- **首轮一条用例红，是用例自身写错**：`routed` 转移事件指向的是 `recall` 而不是 `route`（转移事件名描述的是「刚完成了什么」，目标 stage 是下一个）。断言从「路由 running」改为「召回 running + 路由 completed」，覆盖比原来更严。实现无改动。
- **`COPY` 进入了全局 auto-import 命名空间**（`auto-imports.d.ts` 新增 `const COPY: typeof import('./composables/useOrchestrationTimeline').COPY`）。当前无影响：`OrchestratedPlanCard.vue` 有自己的局部 `const COPY`，局部声明优先，unplugin 不会注入；四路径集 627 条全绿已覆盖 chat 家族。**但这是一个 footgun**——将来任何 `.vue` 若引用了未定义的 `COPY`，会静默拿到本模块的常量而不是报错。110-06 新建 `OrchestrationStageTimeline.vue` 时应显式 `import { COPY } from '~/composables/useOrchestrationTimeline'` 或定义自己的局部常量，不要依赖 auto-import。

## User Setup Required

None - 纯前端逻辑，无外部服务配置。

## Next Phase Readiness

- **110-06（组件挂载）** 可直接 `buildOrchestrationTimeline({ snapshot, events, runtimeActive, repoNames })` 拿到 `steps` 喂给 `<SubStepTimeline :steps :interactive="false" />`，`phase` / `title` / `doneCount` / `totalCount` / `liveMessage` 分别对应卡头三态标题、`{done}/{total} 步` 计数、单一 live region。**组件侧不需要再做任何状态判定**——本模块已经把六态、可选步、摘要、角标、脉冲全部算好。
  - 三条渲染条件（UI-SPEC §A.5）仍归组件：`isOrchestrationTool` / 能绑到会话 / 至少一条已知事实。**本模块对空输入返回的是「6 步全 pending」，不是空数组**——组件必须自己判「至少一条已知事实」，否则历史消息会渲染出一个全灰空壳（§E.3 第三行明确禁止）。
  - 自动折叠（`done` 首次到达时一次性）、`aria-expanded` / `aria-controls`、`role="group"` 都是组件本地状态，本模块不涉及。
- **110-07（调研日志组）** 直接复用导出的 `resolveRepoName(repoId, repoNames)`，不要再写第二份「未知仓库」兜底。
- **未验证面**：本 plan 全程为纯函数单测，**未跑过一次真实编排**。三处最可能在 UAT 才暴露的地方：① `technical_plan.feature.classified` 的 `summary` 字典键名实读为 `new` / `modify` / `unclear`（来自 UI-SPEC 的 payload 实读表），若后端实际键名不同则分类摘要恒为空（表现为该行不渲染，不会报错）；② 融合轮次依赖 `merge.started` 的 `ts` 在两条链上逐字符一致（110-04 同样标注此面未端到端实测）；③ `segment_count` 要等第一次 2s 轮询才有值，编排头 2 秒「拆分」步有状态无摘要——这是 F-14 明确的**预期行为**，不是缺陷。

## Self-Check: PASSED

- `web/src/composables/useOrchestrationTimeline.ts`（536 行，含 `buildOrchestrationTimeline`）与 `web/src/composables/__tests__/useOrchestrationTimeline.spec.ts`（750 行，含 `buildOrchestrationTimeline`）均存在于磁盘，两个 `contains` 断言字面量命中，`min_lines: 180` 满足。
- 三个 commit（`adc9b43e` / `ad0c6373` / `1a7fa37b`）均可在 `git log` 中检索到。
- `key_links`：`useOrchestrationTimeline.ts` 的返回类型 `steps: TimelineStepItem[]` 直接引用 `web/src/types/execution.ts` 的 `TimelineStepItem`，`vue-tsc` 退出码 0 提供类型层证据。

---
*Phase: 110-process-observability*
*Completed: 2026-07-31*
