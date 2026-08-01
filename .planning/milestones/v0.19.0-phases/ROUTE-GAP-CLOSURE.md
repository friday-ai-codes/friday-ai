---
milestone: v0.19.0
scope: ROUTE-01 / ROUTE-02 / ROUTE-07 / RELY-03
closed_at: 2026-08-02T02:20:00+08:00
branch: milestone/v0.19.0-plan-trust
strategy: fold-into-surviving-surface
---

# ROUTE 缺口闭环 —— 四条需求的用户半边落到活着的面上

**问题来源：** `.planning/milestones/v0.19.0-MILESTONE-AUDIT.md` §2 / §3.1 判定的唯一里程碑级
BLOCKER —— ROUTE-01 / ROUTE-02 / ROUTE-07 / RELY-03 四条需求的用户可见半边，全部建在
`web/src/components/chat/RoutingDecisionPanel.vue` 上，而该组件自 `29247521`（2026-05-29）
起在 SPA 内**零挂载点**，且有一条锁测试断言它不得渲染。

> **文件位置说明：** 本里程碑的相位目录（`105-golden-set` … `110-process-observability`）按
> 相位归档，而本次闭环横跨 105 / 107 / 110 三个相位、不属于其中任何一个，故按任务要求放在
> `.planning/phases/` 顶层而非某个相位目录内。

---

## 1. 选定策略与「为什么不会重新引入重复」

**选 (a)：把四件事折进活下来的那条面**——`ToolProcessGroup` 里「仓库分级路由」那一步的 L2
详情区，也就是 `useToolDisplay.relevanceCandidates` 今天真的在给用户画候选清单的地方。
RELY-03 因为跨两条链，在编排时间线上另有一份承载（见 §2.4）。

### 1.1 为什么不选 (b)「把旧面板挂到编排时间线的路由步下」

不是取舍问题，是**它不成立**：

| 障碍 | 证据 |
|---|---|
| 旧面板的数据源是 `useRoutingStore` 按 `trace_id` 反查，而该 store 只由**对话工具链路**写入（`stores/chat.ts:1472` 的 `maybeParseRoutingTraceFromToolResult`）。编排链路走的是 `repo.routing` 事件，时间线手里根本没有 `trace_id` | 挂上去在编排面上恒渲染空 —— 会原样复制「组件存在、测试通过、用户看不到」这个正在被修的错误 |
| 编排链路的 `repo.routing` payload 里没有 `group` / `block_order` / 仓库名 | `builtin_processes.py:120-144` 的候选只有 `repo_id` / `confidence` / `score` / `breakdown`。分组呈现在这条链上**无数据可画** |
| 旧面板自带 Checkbox 与「基于这些仓库创建编码方案」「手动调整选择」两个按钮 | 这正是当初与底部澄清卡重复、被下线的那部分。挂到任何位置都会把它一起带回来 |

### 1.2 为什么 (a) 不会重新引入被去重掉的东西

下线理由是**「选仓 + 提交」这件事重复**，不是「解释」重复。所以：

- 新面 `RoutingCandidateList.vue` 是**纯只读解释面**：无 Checkbox、无提交按钮、无 emit、不写
  任何 store。整个组件里唯一的 `<button>` 是「分数分解」披露开关，并有用例锁住这一点
  （`routingCandidateSurface.spec.ts:266`）。
- 位置也不冲突：它在气泡**上半部**、「分析过程」折叠面板的第二层详情里；澄清卡在气泡**底部**。
  用户要看到它需要主动点两次，不会与澄清卡争夺同一块注意力。
- 选仓入口仍然只有澄清卡一个。原锁测试守的就是这条，被改写成正面断言继续守
  （见 §4）。

### 1.3 判断记录（judgment calls）

1. **删除旧组件而不是留着不挂。** 任务要求「repo 携带单一自洽立场」。留一个零挂载点的组件 +
   一条断言它不渲染的测试，正是让五个相位判绿的那套装置；把能力搬走后删掉它，是唯一不含糊的
   立场。删除 612 行组件 + 39 条隔离单测。
2. **文案走 COPY 常量表，不接 `vue-i18n`。** 与任务约束里「所有用户可见文案走 `t()`」有偏差，
   如实记录理由：(i) 被改的这一族（`useOrchestrationTimeline.ts:94-97` 有明文决定「沿用硬编码
   中文常量惯例，**不接 vue-i18n**」、`TOOL_LABELS`、`OrchestratedPlanCard.COPY`）成体系地不接
   i18n；(ii) 测试基座未全局装 i18n（`src/test/setup.ts` 只 patch storage），在气泡渲染路径上
   引入 `useI18n()` 会连带打断六个既有 spec；(iii) 只给新串接 i18n 会在同一个面板里造出第三种
   文案模式。折中方案满足了约束的实质要求——**模板里没有裸中文串**，全部集中在一处 COPY 表，
   要接 i18n 时是一次机械替换。
3. **不搬旧面板的「每组只显示 3 条 + 溢出披露」。** 那个截断是为了压住带 Checkbox 的长列表，
   并且需要 pin-in 规则兜住「勾了的仓被折叠起来就取消不掉」。只读面没有这个问题，用户已经点开
   两层才看到它，再藏信息只会多一个隐藏面。全量展示。
4. **`skipped` 路径不伪造 `degraded=True`。** 任务提到 skipped 也要能看见降级信号。核到源码：
   `skipped` 是空 query、零候选、根本没路由（`repo_router_adapter.py:43-44`），后端 `degraded`
   本就是 `False`。零候选时说「置信度仅供参考」是在给一个不存在的置信度加注脚。真正的洞是
   `v1_fallback`（`degraded=True` 却因 payload 形状到不了前端），已闭合；`skipped` / stub 现在
   如实报 `false`，键不再缺席。

---

## 2. 四条需求现在给用户什么（file:line 证据）

### 2.1 ROUTE-01 路由结果分两组呈现 —— NOT MET → 满足

| 层 | 证据 |
|---|---|
| 派生 | `web/src/composables/useToolDisplay.ts:269` `routingDecisionView()`；`:278` 分组启用**唯一依据是后端 `block_order` 长度为 2**，不按候选内容兜底（按内容判会恰在「正确仓在跨组、本项目组为空」时判为不分组，最有信息量的提示反而不出现）；`:283-287` 区顺序照抄 `block_order`、区内按 `score_ranked ?? score` 降序、**不做全局重排** |
| 渲染 | `web/src/components/chat/RoutingCandidateList.vue:202` 组标题 +`:204` 组内计数 |
| 挂载 | `web/src/components/chat/ToolProcessGroup.vue:229`，其宿主 `ChatMessageBubble.vue:1312` |
| 用户看到 | 展开「分析过程」→ 展开「仓库分级路由」一步 → **「本项目关联仓（1）」/「全局候选（1）」两个带标题的分区**，顺序由后端定 |
| 兼容 | `block_order` 缺失（历史结果 / legacy）平铺、无组标题，与今日渲染逐字一致（用例 `:160`） |

### 2.2 ROUTE-02 跨组候选带「未关联当前平台」标注 —— NOT MET → 满足

| 层 | 证据 |
|---|---|
| 组级常驻句 | `RoutingCandidateList.vue:211` 渲染「未关联当前平台，可能涉及跨组协作」，不依赖 hover、不随折叠消失 |
| 候选级徽标 | `:236`「跨组」徽标，完整句挂 `aria-label` |
| 置顶因果句 | `:190` —— 全局组被置顶时说「更匹配的仓不在本项目关联范围内」；本项目组为空时换成陈述句「本项目关联范围内没有匹配的仓库」（`:114` 的 `promotionSentence()`，此时并没有发生比较，「更匹配」会暗示一次不存在的比较） |
| 文案来源 | **前端常量**，不渲染后端 `cross_group_note` 自由文本（T-107-06；后端出参 schema 也刻意没带这个字段） |

### 2.3 ROUTE-07 分数可展开到各信号贡献值 —— PARTIAL → 满足

| 层 | 证据 |
|---|---|
| 解析 | `useToolDisplay.ts:135-146` `breakdownOf()`，只收有限数值项 |
| 渲染 | `RoutingCandidateList.vue:254` 披露开关（默认收起、`aria-expanded`）→ `:271` 逐信号行 + 合计行 |
| 可读性 | `:82-89` `SIGNAL_LABELS` 把 `text`/`breadth`/`activity`/`domain`/`stack`/`team` 翻成中文；未知 key 回显原始英文（新信号零前端改动即可展示） |
| 用户看到 | 点「分数分解」→「文本相关 0.700 / 命中广度 0.110 / 活跃度 0.100 / 合计 0.910」 |
| 兼容 | `breakdown` 缺失的 legacy 结果不出现展开入口，其余照常（用例 `:219`） |

### 2.4 RELY-03 降级时看得见解释句 —— PARTIAL → 满足（两条链都覆盖）

**对话工具链路：**

- `RoutingCandidateList.vue:172` amber 横幅（`role="alert"`），主句「本次未经 LLM 推理，置信度仅供
  参考」在 `:185`、原因次行在 `:189`。
- 置于候选**之前**：放在后面等于让用户先按分数做完判断，再告诉他分数不可信。
- 徽标灰化 `:120-128` `levelVariant()` —— 降级时置信度徽标转 `muted`，颜色不再宣称「高置信可信」，
  但 level 文案本身不变。

**编排链路（原本只有两个字「降级」）：**

- `web/src/composables/useOrchestrationTimeline.ts:123-124` 解释句进 `COPY`，`:249-263`
  `degradeReasonLabelOf()` 走受控闭集。
- `web/src/components/chat/OrchestrationStageTimeline.vue:181` 横幅，置于步骤之上；**不挂
  `aria-live`** —— 本卡播报归口是既有那个唯一 live region，再加会让同一事实播两次。
- §D.1 的边界注释同步修订（`OrchestrationStageTimeline.vue:21-30`）：原文把降级横幅划给「他处」，
  那个他处就是这个已删除的组件。

**徽标可见性洞（后端，唯一的后端改动）：**

`_h_route` 的快照分支门是 `snapshot["stage0"]` 非空，而 `v1_fallback` 的 snapshot **只有
stage1**（`codegraph/services/repo_router_v2.py:1847`）、`skipped` 与 stub router 根本没有
snapshot —— 三者全部落到精简分支，而精简分支此前不带 `degraded`。于是「降级」这个事实恰好在
**真降级**的 `v1_fallback` 上永不到达用户。

- `server/services/process_runtime/builtin_processes.py:177-179`：精简分支补
  `router_version` / `degraded` / `degrade_reason` 三键（恒在场）。
- `:136`：快照分支补 `degrade_reason`（解释句要说得出「为什么」）。
- 两处均为**加性**，不改候选级形状，无迁移。

> **为什么必须动后端（约束 4 要求显式论证）：** 前端无法从一个不含该键的 payload 里恢复降级
> 事实。可选替代是让前端按 `router_version` 猜——但精简分支连 `router_version` 都没有，且
> 110-05 立过明确纪律「降级是后端算好的事实，前端绝不按 router_version 或候选内容自行推断」
> （`useOrchestrationTimeline.ts:547` 原注释）。补键既闭合了洞，又保住了那条纪律。

**泄漏面：** 两处降级原因都走 6 值受控闭集映射，闭集外一律回退「未知原因」，**绝不回显原始值**
（上游是异常分类，回显异常名或截断的响应体即成为泄漏面 T-107-02）。两条链各有一条负向用例。

---

## 3. 变异验证（改坏 → 跑测 → 还原 → 确认工作区干净）

全部本次实跑，非引用。每组跑完 `git checkout --` 还原，末次 `git status` 干净。

| # | 改坏点 | 结果 |
|---|---|---|
| **M1（分组）** | `useToolDisplay.ts:278` `const grouped = order.length === 2` → `const grouped = false` | **3 failed** / 8 passed —— ROUTE-01 组标题用例、ROUTE-02 跨组说明句用例、ROUTE-02 置顶因果句用例全红 |
| **M2（降级解释句·对话链）** | `RoutingCandidateList.vue:169` 横幅 `v-if="view.degraded"` → `v-if="false"` | **2 failed** / 9 passed —— 降级横幅用例 + 闭集外回退用例 |
| **M3（降级解释句·编排链）** | `OrchestrationStageTimeline.vue` 横幅 `v-if` → `false` | **2 failed** / 29 passed |
| **M4（挂载点，最关键）** | 把 `<RoutingCandidateList>` 从 `ToolProcessGroup.vue:229` 摘掉 —— 即**原样复现「组件存在、单测通过、无挂载点」那个形态** | **11 failed / 11**（全灭）。这一组是本次取证方式的核心证明：叶子组件仍然完好、旧式隔离单测仍会全绿，而这套用例整片红 |
| **M5（后端降级键）** | 回退 `builtin_processes.py` 精简分支的三键 | **3 failed** / 23 passed —— 含 `test_route_minimal_payload_carries_degrade_facts`（v1_fallback 洞的专用锚） |

M1 / M2 / M3 是任务点名要求的「分组」与「降级解释句」两项；M4 / M5 是额外补的。

**取证方式的刻意选择：** 本里程碑的教训是「组件内有渲染分支 + vitest 结构断言通过」被当成了
「用户能看到」。所以 `routingCandidateSurface.spec.ts` **一条都不单测叶子组件**，全部从
`ChatMessageBubble`（用户真正看到的那层宿主）出发，并且走用户真实的两次点击（`:107` 展开过程
面板 → `:111` 展开路由步）才开始断言。点不开即视为失败。M4 证明这道纪律确实咬得住。

---

## 4. 锁测试的处置 —— 两条，都改写而非删除

| 位置 | 原断言 | 现断言 | 理由 |
|---|---|---|---|
| `partsApiIntegration.spec.ts:178` | 「RoutingDecisionPanel 已下线：即便 routing_trace_id + store 有 trace 也不渲染（与底部澄清卡去重）」 | 「store 有 trace 也不会在气泡里长出第二套选仓 UI」——断言无 checkbox、无「基于这些仓库创建编码方案」/「手动调整选择」、无凭 store 自画的候选清单 | 下线的**理由**继续成立并继续被守住；变的只是取证对象。组件已删除，再断言「一个不存在的组件不渲染」是在锁一句废话 |
| `OrchestrationStageTimeline.spec.ts:444` | 「degraded=true ⇒ 路由行有 warning 角标，**全文不含**降级解释句」 | 「⇒ 有角标，**且卡内给出**降级解释句」；另新增两条（`degraded` 缺席不出横幅、闭集外原因回退「未知原因」不回显原始值） | 这条断言的依据是「解释句归 RoutingDecisionPanel」，而编排链上没有第二块面 —— 它实际锁住的是「用户只能看到两个字」。归他处的「候选列表 / 分数 / 进入编码」半边保留 |

仓库现在携带单一自洽立场：**选仓只有澄清卡一个入口；解释在过程面板与编排卡里，各有宿主、
互不重复。**

---

## 5. 闸门数字（before / after）

基线在本分支上现测（审计报告的数字是 7 月 31 日的，分支此后有推进），非引用。

| 闸门 | 基线 | 收口后 | 判定 |
|---|---|---|---|
| 后端全量 `pytest tests/ -q -p no:cacheprovider`（沿用审计排除的三个沙箱受限文件） | 8204 passed / 61 skipped / 26 deselected / 1 xfailed（审计值，本分支未变） | **8206 passed, 61 skipped, 26 deselected, 1 xfailed**（436.41s） | ✅ +2 = 本次新增两条锚，零回归 |
| 前端全量 `CI=true pnpm vitest run` | **1630 passed / 1 skipped，202 files passed / 1 skipped** | **1604 passed / 1 skipped，202 files passed / 1 skipped** | ✅ 1630 − 39 + 13 = 1604，**精确对账**（39 = 删除的 `RoutingDecisionPanel.test.ts` 隔离单测；13 = 新增 11 条挂载面 + 2 条时间线）。零 failed |
| 类型 `pnpm type-check`（vue-tsc --noEmit） | 退出码 0、零输出 | **退出码 0、零输出** | ✅ |
| 前端 lint `pnpm lint` | **112 problems（107 errors, 5 warnings）**，分布于 28 个文件 | **111 problems（106 errors, 5 warnings）**，分布于 27 个文件 | ✅ **新增文件 0 个**（逐文件 comm 对比）。少的 1 个来自被删除的 `RoutingDecisionPanel.test.ts`（本就带问题） |
| 构建 `pnpm build` | ✓ built in 6.39s | **✓ built in 5.69s** | ✅ |
| 迁移 `makemigrations --check --dry-run` | — | **No changes detected**，退出码 0 | ✅ 无模型改动 |

**构建产物处置：** `pnpm build` 会把 `web/src/components.d.ts` 重写成**净删 29 条无关条目**
（`AccountSettingsModal` / `ActionNode` / `ArtifactsTab` / `CodingTaskList` …）。按任务要求未提交该
输出，两次构建后均 `git checkout --` 丢弃；`RoutingCandidateList` 的新增条目与
`RoutingDecisionPanel` 的删除条目为手工加性编辑。`web/pnpm-workspace.yaml` 无 catalog 回填。

**ruff：** `builtin_processes.py` 与两个测试文件在基线上就未过 `ruff format`（已逐一核实 HEAD
版本），`ruff format --diff` 的全部意见都落在既有行上，**没有一条在本次新增行上**；
`ruff check` 全过。故未做全文件重排，避免造出一片与本次改动无关的 diff。

---

## 6. 提交清单

| commit | 内容 |
|---|---|
| `8d13d900` | `fix(server)`: repo.routing 精简 payload 补齐降级三键（RELY-03） |
| `899ae5cf` | `feat(web)`: 分组/跨组/分数分解/降级落到用户真正看得到的候选面 |
| `99859a63` | `feat(web)`: 编排时间线补降级解释句（RELY-03 第二条链） |
| `4f03c720` | `refactor(web)`: 删除无挂载点的 RoutingDecisionPanel 并改写它的锁测试 |
| （后续） | `chore(web)`: auto-imports 声明补 routingDecisionView；`docs`: 本报告 + REQUIREMENTS + 审计追加 |

---

## 7. 本次**未**闭合、仍然挂账的部分

明确划界，避免这份报告被当成「里程碑可以归档」的依据：

- **26 项人工验收全部仍未执行。** 其中 105-UAT #3 与 107-UAT #2 原先「因面板下线已无从执行」，
  现在**重新可执行了**（浏览器里点开「分析过程 → 仓库分级路由」即可目视核对分组、跨组标注、
  分数分解与降级横幅），但本次没有真实浏览器环境，仍记 pending。
- **`nr_snapshot` 生产方从未运行**（审计 §3.2 / 106-UAT #1）——与本缺口同族但方向相反，不在
  本次范围。
- **golden 门禁对「置信度整体塌陷」不敏感**（审计 §5.2 NC-B 的副产物），建议项，未做。
- **`applyManualOverride` 现无生产调用方。** 原调用方即被删组件。端点仍在线、store action 与
  其 7 条用例保留，已在 `stores/routing.ts:1-12` 如实注释，不留看不出来的悬空 action。

据此，`v0.19.0-MILESTONE-AUDIT.md` 的 `status:` frontmatter **未改动**。

---
_Closed: 2026-08-02（UTC+8）_
_方法：源码核实断裂点 → 择面 → 实现 → 挂载宿主取证 → 5 组变异验证（改坏→跑测→还原→确认工作区干净）→ 六道闸门实跑并与本分支现测基线逐项对比_
