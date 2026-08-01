---
phase: 109-spine-convergence
plan: 04
subsystem: ui
tags: [vue3, composition-api, pinia, vitest, tailwind, shadcn-vue, idempotency, projection, chat]

# Dependency graph
requires:
  - phase: 109-02
    provides: CodingPlan.provenance / source_artifact_version_id 两列（前端 CodingPlanRuntime 扩字段的后端对侧）
  - phase: 109-03
    provides: POST /api/chat/coding-plans/from-artifact-version/ 惰性投影端点与七字段响应（前端投影客户端直接消费）
provides:
  - CodingPlanProvenance / ProjectPlanToCodingResponse 前端类型契约 + CodingPlanRuntime 五个扩字段
  - projectArtifactVersionToCodingPlan 投影端点客户端（web/src/api/chat.ts）
  - projectPlanToCodingPlan store action（只调端点 + 排一次 runtime polling，不拼 CodingPlan）
  - OrchestratedPlanCard.vue —— chat 内编排产出的最小可操作面 +「进入编码」按钮 + 投影后就地内嵌 TechPlanCard
  - isOrchestrationTool / orchestratedPlanData（ChatMessageBubble 判定与防御性双轨解析）
  - UNGROUPABLE_TOOLS 新成员 start_plan_research / start_feature_solution + 显式护栏断言
  - useToolDisplay 三处登记（TOOL_LABELS / TOOL_ICONS / toolAction 编排分支）
affects: [109-05, SPINE-01, SPINE-02, RELY-01]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "静默失守点必须有会转红的护栏断言：UNGROUPABLE_TOOLS 漏登记不报错不崩、只是入口不见；用负控实测（移出集合 → 12 条转红）证明断言有效而非只是同义重复"
    - "投影响应直接喂 props 而非等 runtime 刷新：消除「点击→卡片出现」之间的空窗与刷新时序竞态；activeCodingPlan 仍作 sessions 状态实时来源"
    - "幂等的用户可见口径走中性 success 通道：created=false 只提示「已复用既有编码方案」，断言的是通道而非仅文案（幂等是系统正确性，不是用户要理解的异常状态）"
    - "按钮完成后替换为说明行而非留一个可反复点击的按钮：幂等保证安全，但点了没反应的按钮是坏体验"
    - "边界机械化优于「先做个简版」：编排在途完全不呈现（无 artifact_version_id 天然抓手），把阶段可见性整块留给 Phase 110"

key-files:
  created:
    - web/src/components/chat/OrchestratedPlanCard.vue
    - web/src/components/chat/__tests__/OrchestratedPlanCard.spec.ts
  modified:
    - web/src/types/chat.ts
    - web/src/api/chat.ts
    - web/src/stores/chat.ts
    - web/src/components/chat/ChatMessageBubble.vue
    - web/src/composables/useToolDisplay.ts
    - web/src/composables/__tests__/useToolDisplay.spec.ts
    - web/src/components/chat/__tests__/chatMessageBubble.parts.spec.ts
    - web/src/components.d.ts

key-decisions:
  - "provenance 类型保留 `| string`：后端新增枚举取值时前端不该编译失败，而应走保守分支（未知取值视为未经调研）。让「未知按保守处理」成为类型层默认，而非依赖每个消费点自觉"
  - "store action 不手工拼 activeCodingPlan：前端不得构造 CodingPlan 业务字段，且手工写入会与 runtime 刷新竞态；卡片即时数据由投影响应直接喂 props 承担"
  - "localProvenance 存而不渲染，用 defineExpose 显式声明其为留痕字段：本 phase 不做草稿标注（RELY-01 落在 TechPlanCard），但投影响应带回该值，留作 109 后续接线与测试断言；尤其不渲染原始取值（上游非受控值上屏即泄漏面）"
  - "编排工具一并排除在「展开详情」之外：不只是不渲染卡片时的兜底 —— message / placeholder 经 StructuredJsonView 上屏与「不回显后端自由文本」纪律同源"
  - "toolAction 兜底分支在 requirement 缺失时回退 TOOL_LABELS 而非落 default：default 会产出「space_id: 7」这类裸入参串，正是本 plan 要消除的现状"

patterns-established:
  - "护栏断言要做负控实测：写完「两个编排工具属 UNGROUPABLE_TOOLS」的断言后，实际把两行从集合里删掉跑一遍，确认 12 条用例转红。不做负控的护栏断言可能只是在断言当前实现"
  - "源码级纪律断言用 readFileSync + 过滤注释行：`v-html` 零新增面的断言直接读组件源码并剔除注释行，避免「注释里提到 v-html」让断言自我失效"

requirements-completed: [SPINE-01]

coverage:
  - id: D1
    description: "前端数据契约与后端两个序列化面对齐：CodingPlanProvenance / ProjectPlanToCodingResponse（七字段）/ CodingPlanRuntime 五个扩字段"
    requirement: "SPINE-01"
    verification:
      - kind: automated_ui
        ref: "cd web && pnpm vue-tsc --noEmit -p tsconfig.json（全仓类型检查零错误）"
        status: pass
      - kind: unit
        ref: "web/src/stores/__tests__/chat.runtime.spec.ts（既有 runtime 契约零回归）"
        status: pass
    human_judgment: false
  - id: D2
    description: "投影端点客户端与 store action 就位：projectArtifactVersionToCodingPlan 打 /chat/coding-plans/from-artifact-version/；projectPlanToCodingPlan 只调端点 + 排一次 runtime polling，不构造 CodingPlan"
    requirement: "SPINE-01"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/OrchestratedPlanCard.spec.ts#点击「进入编码」以 artifactVersionId 调投影 action 恰好一次"
        status: pass
      - kind: unit
        ref: "web/src/stores/__tests__/（16 文件 119 用例，store 层零回归）"
        status: pass
    human_judgment: false
  - id: D3
    description: "「进入编码」入口卡片可用：点击触发惰性投影，投影后就地内嵌 TechPlanCard 交棒（props 直接取投影响应，不等 runtime 刷新）"
    requirement: "SPINE-01"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/OrchestratedPlanCard.spec.ts#投影成功后就地内嵌 TechPlanCard，props 来自投影响应"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/OrchestratedPlanCard.spec.ts#投影成功后按钮被替换为已投影说明行（不留一个点了没反应的按钮）"
        status: pass
    human_judgment: false
  - id: D4
    description: "幂等中性呈现与失败可重试：created=false 走中性 success toast；失败用前端常量 error toast 且按钮回 idle；投影期间 disabled 不重复发请求"
    requirement: "SPINE-01"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/OrchestratedPlanCard.spec.ts#created=false → 「已复用既有编码方案」走中性 success 通道而非 error"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/OrchestratedPlanCard.spec.ts#投影失败 → error toast 用前端常量，按钮回到可点击可重试"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/OrchestratedPlanCard.spec.ts#投影期间按钮 disabled 且不重复发请求"
        status: pass
    human_judgment: false
  - id: D5
    description: "两个编排工具同判定同卡片，且均已登记进 UNGROUPABLE_TOOLS（静默失守点有会转红的护栏断言）"
    requirement: "SPINE-01"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/chatMessageBubble.parts.spec.ts#%s 在 UNGROUPABLE_TOOLS 内：走单例 tool 分支而非「分析过程」折叠面板（参数化 2 条）"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/chatMessageBubble.parts.spec.ts#%s 终态渲染 OrchestratedPlanCard，并把 artifact_version_id 交给卡片（参数化 4 条，含 mcp__ 前缀形态）"
        status: pass
      - kind: other
        ref: "负控实测：从 UNGROUPABLE_TOOLS 移除两个工具后 `pnpm vitest run src/components/chat/__tests__/chatMessageBubble.parts.spec.ts` → 12 failed / 15 passed，随后原样恢复"
        status: pass
    human_judgment: false
  - id: D6
    description: "D-4 边界机械成立：编排在途（__blocking_task__ 无 artifact_version_id）与三条渲染条件任一不成立时零卡片、零进度 UI、不抛错；result 为 JSON string 与 dict 两形态都能解析"
    requirement: "SPINE-01"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/chatMessageBubble.parts.spec.ts#编排在途（__blocking_task__ 形态，无 artifact_version_id）→ 零卡片、零进度 UI、不抛错"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/chatMessageBubble.parts.spec.ts#artifact_version_id 为 null / 缺失 / 为空串 → 不渲染卡片、不抛错（参数化 3 条）"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/chatMessageBubble.parts.spec.ts#result 为 dict 形态（历史 chat_runner 路径）同样解析出 artifact_version_id + #result 解析失败（非 JSON）→ 不渲染卡片、不抛错"
        status: pass
    human_judgment: false
  - id: D7
    description: "工具展示三处登记齐备：两个编排工具的中文标签、workflow 图标、toolAction 三分支摘要（终态 / 在途 / 兜底）"
    requirement: "SPINE-01"
    verification:
      - kind: unit
        ref: "web/src/composables/__tests__/useToolDisplay.spec.ts#label 登记 / #icon 登记 / #toolAction 终态分支 / #toolAction 在途分支 / #toolAction 兜底分支（5 条）"
        status: pass
    human_judgment: false
  - id: D8
    description: "不回显后端自由文本 + 零 v-html 新增面：说明句与摘要全取前端常量；message / placeholder 不进渲染路径（含不经 StructuredJsonView 展开）"
    requirement: "SPINE-01"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/OrchestratedPlanCard.spec.ts#组件源码零 v-html（新增面不得引入未转义 HTML 渲染）"
        status: pass
      - kind: unit
        ref: "web/src/composables/__tests__/useToolDisplay.spec.ts#toolAction 在途分支：…且不回显后端 placeholder"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/chatMessageBubble.parts.spec.ts#展开详情不把编排工具的原始 input/output 经 StructuredJsonView 上屏"
        status: pass
    human_judgment: false
  - id: D9
    description: "用户在 chat 里看到编排产出后能一路走完「选目标仓 → 配置分支 → 确认编码 → 飞书导出」四步（SPINE-01 用户故事在 chat 入口下的端到端观感）"
    verification: []
    human_judgment: true
    rationale: "交棒之后的四步由既有 TechPlanCard 承载，本 plan 的单测只能证明 props 正确传递与卡片渲染；四步串起来的真实观感（含 render_merged_plan_markdown 的 lark_md 方言在 GFM 下的显示效果，见 109-03 Known Stubs）需人工在浏览器里走一遍"

# Metrics
duration: 约 20min
completed: 2026-07-30
status: complete
---

# Phase 109 Plan 04: 编排产出「进入编码」入口（SPINE-01 前端半边）Summary

**chat 内新建 `OrchestratedPlanCard` 最小可操作面：两个编排工具同判定同卡片，点「进入编码」触发惰性投影并就地交棒给既有 `TechPlanCard`，在途与失败零卡片零进度 UI**

## Performance

- **Duration:** 约 20 min
- **Tasks:** 3
- **Files created:** 2
- **Files modified:** 8（含自动生成的 `components.d.ts`）
- **Tests:** 新增 23 条（卡片 9 / 编排工具登记 5 / bubble 渲染分支 9），回归 369 passed（chat 组件 250 + store 119）

## Accomplishments

- **SPINE-01 在 chat 入口下闭环**：`OrchestratedPlanCard` 拿到 `artifact_version_id` 后点一次按钮就把编排产出变成 `CodingPlan`，并**就地内嵌** `TechPlanCard` 走执行流四步 —— 用户无需重走一遍方案生成。交棒 props 直接取投影响应（109-03 让响应一次给全 `tech_plan` / `affected_files` / `provenance`），所以点击到卡片出现之间没有空窗、不依赖 runtime 刷新时序。
- **静默失守点被会转红的断言钉住**：`UNGROUPABLE_TOOLS` 漏登记时两个编排工具会被 `isProcessTool` 归入「分析过程」折叠面板，而卡片渲染分支只存在于单例 tool 分支 ⇒ **不报错、不崩、只是入口不见**。写完断言后做了负控实测：把两行从集合中删掉，`chatMessageBubble.parts.spec.ts` 立刻 12 failed / 15 passed，证明断言不是在同义重复当前实现。
- **两个编排入口一并覆盖**：`start_plan_research` 与 `start_feature_solution` 返回体同形，`isOrchestrationTool` 同时匹配（含剥离 `mcp__` 前缀），四种工具名形态各有一条参数化断言。只做前者会让另一条编排入口继续没有编码入口，SC-1 在该入口下不成立。
- **D-4 边界靠数据形态机械收边**：编排在途走 `__blocking_task__` 形态、**天然没有** `artifact_version_id`，因此「三条渲染条件同时成立」这一条判定就同时排除了在途与失败，**不需要**任何进度/阶段 UI 即正确收边。`artifact_version_id` 为 `null` / 缺失 / 空串三形态各有断言（`_map_terminal` 在 `current_artifact_version_id` 为空时确实返回 `null`）。
- **幂等在界面上是中性的**：`created === false` 只出「已复用既有编码方案」的 success toast，卡片表现与首次一致；用例断言的是**通道**（`success` 被调、`error` 未被调）而非仅文案 —— 幂等是系统正确性，把它渲染成异常状态是把实现细节推给用户。
- **不回显后端自由文本落三处断言**：卡片说明句与 toast 全取 `COPY` 常量；`toolAction` 在途分支断言返回值不含 `placeholder` 的任何片段；编排工具一并排除在「展开详情」之外，避免 `message` / `placeholder` 经 `StructuredJsonView` 上屏。另有源码级 `v-html` 零新增面断言（读源码 + 过滤注释行，避免注释提到 `v-html` 让断言自我失效）。
- **零新增依赖 / 零新增设计 token**：`git diff --exit-code web/pnpm-lock.yaml` 退出码 0；卡片只用仓内已出现的图标（`workflow` / `arrow-right` / `loader-2`）、既有 `.card` 底与 `Badge variant="success"`，新增 Badge **纯 variant 无 `:class` 追加颜色**（不复制 `TechPlanCard:350-357` 的既有违规形状）。

## Task Commits

1. **Task 1: 前端数据契约扩字段 + 投影 API 客户端 + store action** — `e109f45e` (feat)
2. **Task 2: OrchestratedPlanCard.vue —— 「进入编码」入口 + 投影后就地交棒** — `78123030` (feat)
3. **Task 3: 渲染分支与 UNGROUPABLE_TOOLS 登记 + useToolDisplay 三处登记** — `d1c99599` (feat)

**附带提交：** `de9cad43` (chore) — `web/src/components.d.ts` 的自动组件声明（unplugin 生成、仓内已跟踪，新组件落地后必然变更）

## Files Created/Modified

- `web/src/components/chat/OrchestratedPlanCard.vue`（新）— 头部 workflow 图标 + `Badge variant="success"`、一句常量说明、primary「进入编码」按钮；投影后按钮替换为说明行并就地内嵌 `TechPlanCard`
- `web/src/components/chat/__tests__/OrchestratedPlanCard.spec.ts`（新）— 9 用例：入口文案与徽标、调用一次、两种 toast 通道、交棒 props、按钮替换、期间 disabled、失败重试、源码零 `v-html`
- `web/src/types/chat.ts` — `CodingPlanProvenance`、`ProjectPlanToCodingResponse`（7 字段）、`CodingPlanRuntime` 五个扩字段
- `web/src/api/chat.ts` — `projectArtifactVersionToCodingPlan` + 默认导出清单
- `web/src/stores/chat.ts` — `projectPlanToCodingPlan` action + store 公开清单
- `web/src/components/chat/ChatMessageBubble.vue` — `isOrchestrationTool`、`orchestratedPlanData`（防御性双轨）、`UNGROUPABLE_TOOLS` 两个新成员 + 静默失守点注释、`<OrchestratedPlanCard>` 渲染分支、展开详情排除条件
- `web/src/composables/useToolDisplay.ts` — `TOOL_LABELS` / `TOOL_ICONS` 各两条 + `toolAction` 编排 `case`（终态 / 在途 / 兜底三分支）
- `web/src/composables/__tests__/useToolDisplay.spec.ts` — 新增 5 用例（含在途分支不回显 `placeholder`）
- `web/src/components/chat/__tests__/chatMessageBubble.parts.spec.ts` — 新增 9 用例（参数化后共 12 条断言实例）
- `web/src/components.d.ts` — 自动生成的组件声明

## Decisions Made

- **`localProvenance` 存而不渲染，并用 `defineExpose` 显式声明其性质**：本 plan 不做草稿标注（RELY-01 的横幅/徽标落在 `TechPlanCard`，属后续 plan），但投影响应带回 `provenance`，plan 正文要求接下来。为避免它成为一个无人解释的死变量，用 `defineExpose` 显式声明「留痕供后续接线与测试断言」并在注释里写明**不渲染原始取值**的理由（上游非受控值上屏即泄漏面）。
- **`toolAction` 兜底分支回退 `TOOL_LABELS` 而非 `default`**：`requirement` 缺失时若继续落 `default`，会产出「`space_id: 7, requirement: …`」这类裸入参串 —— 那正是本 plan 要消除的现状。回退工具标签是「不比 pill 名多说什么，但也不倒退成裸入参」的最小选择。
- **编排工具一并加入「展开详情」排除条件**：plan 把这条列为 §Backstop 第 7 条的落法。它不是「卡片不渲染时的兜底」，而是与「不回显后端自由文本」同源 —— 卡片不渲染 `message`，但 `StructuredJsonView` 展开会把整段 result（含 `message` / `placeholder`）原文上屏，只堵前者等于没堵。
- **护栏断言做负控实测**：`UNGROUPABLE_TOOLS` 的断言最容易写成「断言当前实现」而不是「断言失守会被发现」。实际把两行删掉跑一遍（12 条转红）后再恢复，才确认这条护栏有效。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `:status="'draft'"` 触发 `vue/no-useless-v-bind` lint error**

- **Found during:** Task 2（OrchestratedPlanCard 交棒 props）
- **Issue:** plan 正文给的交棒写法是 `:status="'draft'"`，但本仓 ESLint 的 `vue/no-useless-v-bind` 规则禁止用 `v-bind` 绑定字符串字面量，直接 lint error（阻塞 plan 级 `<verification>` 的 eslint 项）。
- **Fix:** 改为静态属性 `status="draft"`。语义完全一致（`TechPlanCard` 的 `status` prop 是字符串联合类型，静态属性传字符串字面量正确）。
- **Files modified:** `web/src/components/chat/OrchestratedPlanCard.vue`
- **Verification:** `pnpm eslint`（6 个改动文件）零 error；`OrchestratedPlanCard.spec.ts` 断言交棒 `data-status` 为 `draft` 仍绿。
- **Committed in:** `78123030`（Task 2 commit）

**2. [Rule 3 - Blocking] 测试用 `import.meta.url` 读源码在 vitest 环境下抛 `The URL must be of scheme file`**

- **Found during:** Task 2（`v-html` 零新增面的源码级断言）
- **Issue:** 首版用 `fileURLToPath(new URL('../OrchestratedPlanCard.vue', import.meta.url))` 定位组件源码；vitest + happy-dom 下 `import.meta.url` 是 http URL，`fileURLToPath` 直接抛错。
- **Fix:** 改用仓内既有惯例 `readFileSync(resolve(process.cwd(), 'src/components/chat/OrchestratedPlanCard.vue'))`（与 `chat-draft-conversation.spec.ts` / `PromptBodyEditor.test.ts` 同款写法）。
- **Files modified:** `web/src/components/chat/__tests__/OrchestratedPlanCard.spec.ts`
- **Verification:** 该用例转绿（9 passed）；断言仍是**真断言**（源码含 `v-html` 时会红）。
- **Committed in:** `78123030`（Task 2 commit）

**3. [Rule 3 - Blocking] 两处 lint error：`test/prefer-lowercase-title` 与 `style/spaced-comment`**

- **Found during:** Task 3
- **Issue:** 用例标题以 `TOOL_LABELS：` / `TOOL_ICONS：` 开头触发 `test/prefer-lowercase-title`；`useToolDisplay.ts` 中一行注释以 `//（` 开头（全角括号紧跟 `//`）触发 `style/spaced-comment`。
- **Fix:** 标题改为「label 登记 / icon 登记」（不用 `tOOL_LABELS` 这种为过 lint 而破坏可读性的写法）；注释改为破折号续行。
- **Files modified:** `web/src/composables/__tests__/useToolDisplay.spec.ts`、`web/src/composables/useToolDisplay.ts`
- **Verification:** `pnpm eslint`（6 个改动文件）零 error；对应用例仍绿。
- **Committed in:** `d1c99599`（Task 3 commit）

---

**Total deviations:** 3 auto-fixed（全为 Rule 3 阻塞项：2 处 lint 规则冲突、1 处测试运行时 API 不可用）
**Impact on plan:** 三处都是「plan 给的写法在本仓工具链下不可用」的机械替换，语义与断言强度不变，无范围外改动。

**一处非偏离的实现细化**（已记入 Decisions）：`defineExpose({ localProvenance })`。plan 要求在成功分支给 `localProvenance` 赋值但未指定其消费方；本仓 `tsconfig` 开了 `noUnusedLocals`，用 `defineExpose` 把它显式声明为留痕字段既满足 plan 要求，也避免留下一个无人解释的死变量。

## Issues Encountered

- **`web/src/components.d.ts` 在跑测试时被 unplugin 自动改写**：该文件仓内已跟踪，新组件落地后必然变更。按「不留生成文件未跟踪/未提交」的纪律单独提了一个 `chore` commit（`de9cad43`），而不是塞进 Task 3 的 feat 提交里混淆语义。
- **`web/src/components/chat/__tests__/chatMessageBubble.parts.spec.ts` 需要 stub `OrchestratedPlanCard`**：真实卡片依赖 chat store 与 `useToast`（vue-sonner），在 bubble 测试里挂载它会把「渲染分支是否被走到」和「卡片自身投影交互」两件事绞在一起。用 `vi.mock` stub 掉并透出 `data-artifact-version-id`，让本文件只断言分支与传参，卡片交互归 `OrchestratedPlanCard.spec.ts`。

## Verification Results

| 命令 | 结果 |
|---|---|
| `pnpm vitest run src/components/chat/__tests__/OrchestratedPlanCard.spec.ts` | 9 passed |
| `pnpm vitest run src/composables/__tests__/useToolDisplay.spec.ts` | 17 passed（新增 5） |
| `pnpm vitest run src/components/chat/__tests__/chatMessageBubble.parts.spec.ts` | 27 passed（新增 12 条断言实例） |
| `pnpm vitest run src/composables/__tests__/useToolDisplay.spec.ts src/components/chat/__tests__/` | **250 passed / 26 files**（chat 组件零回归） |
| `pnpm vitest run src/stores/__tests__/` | **119 passed / 16 files**（store 零回归） |
| `pnpm vitest run src/stores/__tests__/chat.runtime.spec.ts src/api/__tests__/` | 44 passed |
| `pnpm vue-tsc --noEmit -p tsconfig.json` | 无输出（零类型错误） |
| `pnpm eslint`（6 个改动文件 + 2 个测试文件） | 零 error |
| `git diff --exit-code web/pnpm-lock.yaml` | 退出码 0（零新增依赖） |
| 负控：从 `UNGROUPABLE_TOOLS` 移除两个工具 | **12 failed / 15 passed**（护栏断言有效），已原样恢复 |

## Threat Model Coverage

| Threat ID | 落法 |
|---|---|
| T-109-04-01（Tampering，未转义 HTML） | 新增文案全走 `{{ }}` 插值；`OrchestratedPlanCard.spec.ts` 有源码级 `v-html` 零匹配断言（过滤注释行）；编排工具的原始 input/output 不经 `StructuredJsonView` 展开（bubble 侧有断言） |
| T-109-04-02（Information Disclosure，后端自由文本上屏） | 说明句与 toast 全取 `COPY` 常量；`toolAction` 三分支全取本文件常量并断言不含 `placeholder` 片段；`provenance` 原始取值不渲染 |
| T-109-04-03（EoP，越权投影） | 前端只传 `artifact_version_id`；store action 内**不构造**任何 `CodingPlan` 业务字段；conversation 与 owner 判定完全在服务端（109-03 两道 owner gate） |
| T-109-04-04（DoS，重复点击） | 按钮 `projecting` 期间 `disabled` + 处理函数首行 `if (projecting) return` 双层守卫，用例断言重复点击不再发请求；即便重复到达，服务端唯一约束保证只产一行，前端按 `created=false` 走幂等 toast |
| T-109-04-SC（供应链） | 零新增依赖、未跑 `shadcn init` / `shadcn add`、未从任何 registry 拉块；`git diff --exit-code web/pnpm-lock.yaml` 退出码 0 |

## Observability

本 plan 为纯前端改动，**无新增后端请求入口、无 LLM 调用点、无召回、无队列任务或 webhook**，故不涉及 `.cursor/rules/observability-logging.mdc` 的 `call_source` / `RequestMetric` / `RetrievalTrace` 等埋点要求。新增的投影调用打的是 109-03 的既有端点，其 `plan_projection_started` / `completed` / `failed` / `idempotent_hit` 四事件（`category=caller`、`component=chat`、带 `duration_ms` 与触发用户）已在服务端就位；前端不重复上报，避免同一次调用在两处各记一笔。

## Known Stubs

无占位实现。以下是**按 plan 设计**分派到后续 plan 的下游接线，不是本 plan 的 stub：

- `TechPlanCard` 的草稿横幅 / 折叠态徽标 / 送编码确认弹层、`techPlan` 三级优先数据源、空正文占位 —— 属 RELY-01 与 SPINE-02 连带面（UI-SPEC §B/§C/§E），本 plan 明令只做 SPINE-01 入口侧。`localProvenance` 已备好该接线的数据入口。
- 后端 `provenance` / `tech_plan` / `affected_files` 在 `ConversationRuntimeCodingPlanSerializer` 与 `CodingPlanSerializer` 双侧透出（UI-SPEC §后端契约要求 #1）不在本 plan 范围；因此 `CodingPlanRuntime` 的扩字段目前只在类型层就位，runtime 实际能否拿到值取决于后续 plan。这**不影响**本 plan 的交棒路径 —— 卡片 props 直接取投影响应，不经 runtime。
- fan-out 的 `acknowledge_unresearched` 与 `draft_requires_explicit_confirm` 机器码分支（UI-SPEC §C）属后续 plan。
- `ArtifactTimeline.vue` 的「进入编码」方案 B、`source_artifact_version_id` 的用户可见追溯：UI-SPEC §Unresolved 第 1 / 9 条明确本 phase 不做。
- `render_merged_plan_markdown` 的 lark_md 方言（`•` 项目符号在 GFM 下显示为纯文本）：UI-SPEC §Unresolved 第 7 条裁定接受现状；若 UAT 判观感不可接受，处置方式是给该函数加 `flavor` 参数，**不 fork 渲染器**。

## User Setup Required

None —— 无外部服务配置需求，零新增依赖、零新增迁移。

## Next Phase Readiness

- **SPINE-01 两侧齐备**：服务端半边（109-03，投影一条记录即执行流四步全通，有 e2e 背书）+ 前端半边（本 plan，chat 内有入口能触发投影并交棒）。109-05 收窄编排工具 schema 的前置条件已完全满足。
- ⚠️ **提醒 109-05**：本 plan 的投影调用方仍是「有 owner gate 的端点」这一条路径。109-05 让 chat `@tool` 成为第二个调用方时，必须按 109-03 的提醒把归属判定下移进 service（机器码 `artifact_version_forbidden`），否则 `@tool` 路径会绕过 gate。
- ⚠️ **提醒 RELY-01 执行者**：`CodingPlanRuntime` 的扩字段已在前端类型层就位，但**后端两个序列化器尚未透出**（UI-SPEC §后端契约要求 #1 未落）。该 plan 必须两侧同改 —— 只改前端不会有 TS 报错，字段会永远是 `undefined`，而按 UI-SPEC §B.1 的保守判定这会让**所有**方案卡都挂上「未经调研」横幅（含真正的编排产出）。
- ⚠️ **UAT 提醒（D9）**：交棒后的四步走真实浏览器时，注意 `tech_plan` 的 lark_md 方言观感（见 Known Stubs 最后一条），以及存量 `CodingPlan` 在 RELY-01 落地后会集体出现草稿标注 —— 那是预期行为而非回归。

## Self-Check: PASSED

- 两个新建文件均存在于磁盘：`web/src/components/chat/OrchestratedPlanCard.vue`、`web/src/components/chat/__tests__/OrchestratedPlanCard.spec.ts`。
- 四个 commit 均可在 git 历史中检得：`e109f45e` / `78123030` / `d1c99599` / `de9cad43`。
- 四次提交 `git diff --diff-filter=D` 均无文件删除。
- 未修改 `.planning/STATE.md` 与 `.planning/ROADMAP.md`（编排器职责）。

---
*Phase: 109-spine-convergence*
*Completed: 2026-07-30*
