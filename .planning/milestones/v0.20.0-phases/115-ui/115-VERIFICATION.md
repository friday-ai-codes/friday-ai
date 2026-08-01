---
phase: 115-ui
status: passed
score: 107/107
verified: 2026-08-01
deferred:
  - truth: "引用二级预览中「代码位置」展示**源码正文与行高亮**"
    addressed_in: "Phase 116"
    evidence: "ROADMAP SC-3 已同步收窄为「代码位置：文件路径 + 行号区间 + 引用快照」，REQUIREMENTS.md:63 与 :130 逐字标注同一收窄。实证依据：`chunk_lookup._query_covering_chunks` 只 select `{chunk_id, file_path, line_start, line_end, chunk_index}`，`chunk_at_views` 返 `{path, line, chunks}` **不带正文**；全仓唯一带 `content` 的读面是需要 `query` 的向量搜索，无法按 path + 行号区间取。⇒ 降级形态是当前 SC 的**内核**而非缺口"
  - truth: "蓝图关联的反向「被谁引用」与互引成图谱边"
    addressed_in: "Phase 116（知识图谱物化）"
    evidence: "ROADMAP SC-4 逐字「**反向「被谁引用」随 Phase 116 知识图谱物化交付**」；REQUIREMENTS.md:66 把 VIEW-04 标为 `PARTIAL @ Phase 115，剩余部分顺延 Phase 116`，:132 的追溯表同样记 PARTIAL。实证依据：`knowledge/artifact_associations.py:75` 查的是 `initiatives.Artifact` 投影的 KnowledgeEntity，拿 `delivery.Artifact.id`（蓝图所在表）必然 404/空。⇒ 115 交付正向「本蓝图引用了 + 关联项目」，已实现并经 `sections.spec.ts:595-596` 锁死零调用"
  - truth: "范围闸 400 分支对「`meta.project_id` 不合法」那批 artifact 的存在性预言机（MN-03）"
    addressed_in: "Phase 116（与 111-MN-12「权限口径」、115-07「gate 链无范围闸」三条一并定夺）"
    evidence: "`115-REVIEW.md` Fix Log 判为设计决策而非缺陷（四条理由），`.planning/STATE.md:152` 已显式登记。**不影响任何一条 SC**：五条 SC 都是查看器能力判据，无一依赖该闸的回显语义；且形状正常的蓝图其「非成员 404」与「不存在 404」用**同一个常量对象** `_ARTIFACT_MISSING_DETAIL`（11 端点逐字一致），预言机对主路径已关闭"
human_verification:
  # ⚠️ 以下四项**均不阻塞任何 SC**（status 仍为 passed）：SC 的可判定内核已由自动化证据结论性覆盖，
  # 这里剩下的是 happy-dom 无版面引擎 / 无真实渲染引擎所致的**视觉抛光面**，属 UAT 范畴。
  #
  # ⭐ 2026-08-02 更新：四项的 `why_human` 全部是 happy-dom 的能力缺口，而**不是**真需要人的判断。
  # Chromium 有版面引擎、真 `getBoundingClientRect`、真 IntersectionObserver、真媒体查询 ⇒ 四条
  # 理由同时消解。已用 Playwright 从 `/knowledge/blueprints/:id` 真实入口实跑，见各项 `result` /
  # `covered_by` / `mutation_evidence`。**四项判定核心全部 pass，过程中发现并修复 1 个真实缺陷。**
  # 每项仍留的 `residual_human` 是**真正需要人眼**的审美判断，⛔ 不因为主体转绿就整条勾掉。
  # 执行记录：`.planning/UAT-AUTOMATION-REPORT.md` §10。
  - test: "在真实浏览器打开一份含 mermaid 块的蓝图，确认交互流程图正常出图"
    expected: "mermaid 块渲染为 SVG 流程图；空源码时不出现空 `<pre>`"
    why_human: "组件测试一律 `stubs: { MermaidDiagram: true }`（否则要连带 `vue-final-modal` 插件）；`MermaidDiagram.vue` 是 §13.2 冻结的既有件，本相位零改动，自动化只能验到「传对了 `code` prop + 空源码由调用方 `v-if`」这一层"
    blocking: false
    result: pass
    verified: 2026-08-02
    covered_by: "`web/tests/e2e/blueprint-viewer-visual.spec.ts` › `UAT 115-1`（3 例）"
    evidence: "真 `<svg>` 恰 1 个且有面积（>80×80）、节点文案「库存充足?」出现在 SVG 内部、`path` 连线 >0、出图态下同卡零 `<pre>`、`放大` 入口出现。空源码（缺 `mermaid` 键 / 全空白串）两张卡合计 4 行步骤表照渲而 `<pre>` / `blueprint-block` / `svg` 三者**全 0**。另有非法源码档回退 `<pre>` + 「无法渲染流程图，已展示源码」作**非恒真对照**（证明「零 pre」不是因为 pre 永不渲染）"
    mutation_evidence: "① `MermaidDiagram.render` 的 `svg.value = out.svg` 改成 `''` ⇒ SVG 计数断言 1→0 转红。② 去掉 `InteractionFlowsSection.mermaidBlocks` 的空源码闸（并让 `BlueprintBlock` 内层 `v-else-if=\"text.trim()\"` 恒真）⇒ **冒出 2 个空 `<pre>`**，`pre` 计数断言转红 —— 即 UAT 原文所防的那个形状"
    residual_human:
      - "「放大」全屏弹层（`VueFinalModal`）的内容与可读性未断言：只验了触发按钮存在，未打开弹层"
      - "复杂真实流程图的**排版观感**（节点是否重叠、连线是否绕、长中文标签是否被截）仍需人眼——自动化只能证明「出了一张有节点有连线的 SVG」"
  - test: "拖选一段正文，观察选区 popover 的落点"
    expected: "popover 贴着选区末端出现，不遮挡被选文本，Esc 关闭且保留选区"
    why_human: "happy-dom 无版面引擎，`Range.prototype.getBoundingClientRect` 返回零矩形（115-02 的 `domCapabilities.test.ts` 能力锁已实测登记）⇒ 屏幕坐标无法自动化断言。**触发与载荷逻辑已自动化覆盖**（同块/跨块分流、offset 两段式计算）"
    blocking: false
    result: pass（判定核心；「贴着**末端**」一句与实现不符，见 residual_human 第 1 条）
    verified: 2026-08-02
    covered_by: "`web/tests/e2e/blueprint-viewer-visual.spec.ts` › `UAT 115-2`（2 例）"
    evidence: "真鼠标拖选（`mouse.down/move/up`）后选区矩形非零（正是 happy-dom 拿不到的那件东西）；浮层与选区矩形**零交叠**（不遮挡）、竖直缝隙 ∈ [0, 14]px（`side-offset=8` + 子像素余量，即「贴着」）、浮层水平中心与选区中心相差 ≤24px（**锚在选区上**）。Esc 后浮层 `count == 0` 且 `window.getSelection().toString()` **逐字等于**拖选前的文本"
    mutation_evidence: "① 把 `PopoverAnchor` 的 `anchorStyle` 退化成零矩形（即 happy-dom 的形状）⇒ 浮层飘到选区外 **352px**，「贴着」断言转红 —— 直接证明这一条测的就是 happy-dom 测不到的那个量。② 在 `onOpenChange` 里补一句 `removeAllRanges()` ⇒ Esc 保留选区断言转红。③ 反例登记：去掉 `@close-auto-focus` 的 `preventDefault` **不足以**破坏选区（Chromium 焦点归还不折叠选区）⇒ 该 handler 的选区保护作用未被本层证实"
    residual_human:
      - "⚠️ **expected 的「贴着选区末端」与实现不符**：`BlueprintSelectionPopover` 把**整个选区矩形**作为 `PopoverAnchor`、`side=\"top\"` ⇒ 浮层落在选区**正上方居中**，不是选区末端。可判定内核（不遮挡 / 贴着 / 锚在选区上）成立，但「末端」这一措辞要么改 expected 要么改实现——需要人拍板，⛔ 不由测试单方面认定"
      - "跨行 / 跨段落长选区：`range.getBoundingClientRect()` 取的是并集包围盒 ⇒ 浮层会居中在整块之上。是否可接受属审美判断，未断言"
  - test: "滚动查看器正文，观察左栏十段导航的高亮跟随"
    expected: "高亮随滚动逐段推进，不停在第一段"
    why_human: "`AnchorNavLayout` 的 mount-only IntersectionObserver 需要真实版面。**其前置条件（本相位头号靶子 P-4）已被自动化结论性证明**：十个 `<section>` 的 id 全是静态字面量、无一带 `v-if`/`v-show`（三态渲染全在段内），`sections` 数组是恒 10 项的字面量 ⇒ observer 挂得上"
    blocking: false
    result: pass（**并发现 + 修复 1 个真实缺陷**，见 found_defect）
    verified: 2026-08-02
    covered_by: "`web/tests/e2e/blueprint-viewer-visual.spec.ts` › `UAT 115-3`（2 例）"
    evidence: "逐段滚动十次，左栏高亮下标实测走出 `[0..9]` 完整序列（非恒真对照：断言的是整条序列相等，「一直是 0」与「卡在某一项」都会转红）。高亮态取两个独立来源（`bg-primary/8` 类名 + 左侧指示条 span）并**互校**，不一致直接抛错而非静默取其一"
    mutation_evidence: "⭐ 按相位最担心的形状变异：给 `#impact_analysis` 加 `v-if=\"content\"` ⇒ 段容器在断言时**仍在 DOM**（`section[id]` 计数照样 10、点击跳转照常工作），但 mount 那一刻它不在 ⇒ observer 挂不上 ⇒ 第 5 项**永不点亮**，用例报 `段 impact_analysis 未点亮左栏第 5 项` 转红。这正是 P-4 所防的「人肉走查只会觉得高亮有点怪」的缺陷，防线**能真的触发**"
    found_defect: "⭐ 观察窗 `rootMargin: -15% 0px -55% 0px` 在**文档首尾各留了一段死区**，而回调 `if (visible.length > 0)` 在死区内不更新 ⇒ 滚回顶部时高亮**冻在离开前那一段**（实测：视口 720px 时观察窗 108~324px，而首段起点在 349px）。与 P-4 防的「永远停在第一段」是同一类失守、方向相反。已修：相交集合为空时补一次基于位置的兜底。commit `0fd29f56` `fix(nav):`，四个 `AnchorNavLayout` 使用方同步受益"
    residual_human:
      - "只验了「瞬时跳转到某段」与「跳回顶部」两种滚动方式；连续惯性滚动 / 触控板惯性下的**高亮抖动观感**未断言"
  - test: "在 < xl 与 < md 两档窗宽下检查三栏收拢"
    expected: "< xl 线程侧栏收成 Sheet；< md 左栏由 `BlueprintSectionNav` 的 Select 承接"
    why_human: "响应式断点是 CSS 版面行为，happy-dom 不计算媒体查询"
    blocking: false
    result: pass
    verified: 2026-08-02
    covered_by: "`web/tests/e2e/blueprint-viewer-visual.spec.ts` › `UAT 115-4`（4 例）"
    evidence: "可判定内核 =「任一窗宽下**可见**的线程侧栏实例恰好一份」。≥ xl（1440）：常驻栏可见 + 抽屉**整块不在 DOM**（`v-if=\"!isWide\"`，⛔ 不是藏起来），点顶栏「查看批注」仍是 1 份。< xl（1279 / 1024）：常驻栏在 DOM 但 `hidden`，点「查看批注」开出抽屉 ⇒ 仍是 1 份。宽→窄→宽连续切换全程 ≤1 份。< md（767）：左栏 `aside.w-48 nav` 隐藏、`blueprint-section-nav` 的 Select 可见，且 `scrollWidth - clientWidth ≤ 1`（收拢成立、无横向溢出）；≥ md 两者互换"
    mutation_evidence: "把常驻侧栏的 `xl:flex` 改成 `lg:flex`（与抽屉的 `isWide` 闸脱钩）⇒ 1024px 下常驻栏与抽屉**同时可见**，「< xl」与「连续切换」两例双双转红"
    residual_human:
      - "未展开 `BlueprintSectionNav` 的 Select 下拉并实际跳段：只验了它在 < md 可见、在 ≥ md 隐藏"
      - "< md 下十段正文的**逐段观感**（表格横向滚动条、API 契约卡在窄屏的可读性）未断言，只验了页面整体无横向溢出"
---

# Phase 115: 前端查看器与知识库（结构化阅读 + 批注 + 管理面）— Verification Report

**Phase Goal:** 蓝图对人可读、可审、可管理——结构化查看器（六段导航/批注层/版本 diff/阶段时间线）、二级引用预览、知识库技术方案 tab、项目关联展示、人审终审操作全部可用。
**Verified:** 2026-08-01
**Status:** passed（3 项 deferred，均由 ROADMAP / REQUIREMENTS / STATE 显式登记；4 项视觉 UAT，非阻塞）
**Re-verification:** No — initial verification
**Worktree/Branch:** `.claude/worktrees/v0.20-blueprint` @ `milestone/v0.20.0-blueprint`，HEAD `26d94374`
**相位规模:** `git diff 88da0d21..HEAD -- server/ web/` = **90 files, +21123, −0**（整个相位零删除行）

Must-haves 口径 = **5 条 ROADMAP Success Criteria**（按**当前**收窄后的文本，非记忆版本）+ **7 份 PLAN frontmatter 的 102 条 truths**（16 + 15 + 14 + 15 + 15 + 16 + 11），合计 **107**。

**七份 SUMMARY 的自述一律不作证据。** 本报告的每一条判定都另行读源码 / grep / 实跑测试复核。本里程碑已在 112 / 113 / 114 各出过一次静默假通过，115 自身评审又抓到四条（时间线永不到「完成」、blocker 计数与后端判据不同口径、缓存失效漏三键、读失败与空态同形）——因此对每一条「声称被强制」的判据都定位到强制点并确认**它能真的触发**。

## Observable Truths — 5 条 Success Criteria 逐条判定

| # | Success Criterion（当前 ROADMAP 文本） | 判定 | 证据 |
|---|---|---|---|
| SC-1 | 打开蓝图看到六段结构化渲染（mermaid / 伪代码块 / API 契约卡 / 影响矩阵 / 仓库关联卡）+ 11 态状态徽标 + 阶段时间线；生成中各段展示实时进展（复用 ConvergenceSessionEvent，不新建推送通道） | ✓ PASS | **结构化渲染**：`BlueprintBlock.vue` 五类块结构性分发 —— `paragraph`(:304) / `list`(:326) / `table`(:350) / `pseudocode`(:370) / `mermaid`(:392，`:code=` 而非 `:source=`，空源码由调用方 `v-if`)。四张专用卡实装：`ApiContractCard.vue`(12K) / `ImpactMatrixTable.vue`(14K) / `RepoAssociationCard.vue`(15K) / `ImplementationItemCard.vue`(9K)。**十段容器**齐备（见 SC-1 专项复核）。**状态徽标**：`config/blueprintStatus.ts` 11 态 + `''`（v0 旧数据）共 **12** 个 `labelKey` 配置 + `getBlueprintStatusConfig` 未知态兜底。**阶段时间线**：`BLUEPRINT_STAGES` 八节点（`spec_gate→route→repo_research→confirmation→repo_plan→merge→ai_review→pending_review`），末态由 `buildStageTimeline` 单一实现推断。**实时进展不新建通道**：`useBlueprintLive` 是全相位唯一轮询消费点（`refetchInterval` 字面量在 `components/blueprint/**` 与 `pages/knowledge/blueprints/**` 零命中，由 `blueprint-source-guard.spec.ts` 断言 6 在 **69 个文件的非空扫描面**上锁死）；页面按段消费 `sectionProgress` / `statusProgressKey`（`isSectionPending()` 在十段各自的骨架分支内，`aria-live="polite"`）⇒ 已产出的段立即实渲，⛔ 无全页 loading |
| SC-2 | AI 划线提问以飞书式下划线高亮呈现，点击展开线程侧栏可多轮回复；用户可对任意选区发起评论；版本切换 + block 级 diff 视图可用 | ✓ PASS | **划线高亮**：`<mark data-testid="blueprint-annotation-mark">` 带 `data-thread-id` / `data-severity` / `data-thread-status` / `role="button"` / `tabindex="0"` + `@click`/`@keydown.enter`/`@keydown.space`（:316 / :339 / :386 三处渲染分支）；区间由 `sliceBlockText` 返回**结构化数组**（:206），颜色唯一来源 `annotationTokens.annotationClass`。**多轮回复**：`BlueprintThreadSidebar.vue`(14K) 四组 + `BlueprintThreadCard.vue`(10K) 消息列表；kind 硬分流做在**渲染层**（finding 卡的 DOM 里根本不存在 Composer 节点，⛔ 不是 `disabled`）。**任意选区发起评论**：唯一落点 `BlueprintBlockList.vue` 监听 `document` 的 `selectionchange`（:152，`onUnmounted` 有配对 `removeEventListener` :157），同块 → `selection-comment`(:140)、跨块 → `cross-block-selection`(:131)；写口是 115-01 新建的 `POST blueprint-review/threads/`。**版本切换 + diff**：`BlueprintVersionSwitcher.vue` + `BlueprintBlockDiff.vue`(12K)，页面 `isDiffMode`(:191) / `diffBaseQuery`(:246) / 挂载(:952-954)；diff 模式下批注层与全部写动作关闭（`readonly` computed :313 含 `isDiffMode`）|
| SC-3 | 引用 chip 点击在查看器上再弹一层预览（知识实体 / **代码位置：文件路径 + 行号区间 + 引用快照** / 其他蓝图 / 章程条目）；仓库关联卡可直接跳转仓库页 | ✓ PASS | **五路分发**齐备（`CitationPreviewDialog.vue:127-151`）：`knowledge_entity`→`CitationKnowledgePreview` / `repo_file`+`rag_chunk`→`CitationCodePreview` / `repo_charter`→`CitationCharterPreview` / `blueprint`+`artifact_version`→`CitationBlueprintPreview` / 其余→`CitationFallback`。**代码位置按收窄后的 SC 逐字兑现**：`CitationCodePreview.vue` 渲染 `displayPath` 面包屑(:97) + `rangeStart..rangeEnd` 行号区间(:94-95) + citation `quote` 快照按行切开(:101-103)；⛔ 无 CodeMirror、⛔ 无源码正文。**兜底判据是 `usable` 不是状态码**（:88，P-3：`chunk-at` 对「无命中」与「被排除文件」统一返 200 空 chunks）；`line_start` 缺失 ⇒ **查询根本不启用，一次请求都不发**(:61)。**仓库跳转**：`RepoAssociationCard.vue:173` `RouterLink :to="\`/repositories/${association.repository_id}\`"` |
| SC-4 | 知识库「技术方案」tab 支持状态/项目/仓库筛选与搜索、深链直达查看器；项目内生成的蓝图自动挂项目并在项目物料面板可见；蓝图引用的知识/仓库/其它蓝图可查（**反向「被谁引用」随 Phase 116 知识图谱物化交付**） | ✓ PASS | **tab 纯追加**：`pages/knowledge/index.vue` 联合类型加 `'blueprints'`(:42)、`TABS.push`(:46)、`TabsTrigger`(:231)、`<TabsContent value="blueprints">`(:243-244)；`git diff \| rg "^-[^-]"` 删除行 **0**。**三筛选 + 搜索**：`bp_status`(:81) / `project_id`(:82) / `repository_id`(:83) / `q`(:86) 四项均与 URL query 双向同步（各配 `watch`），搜索走「输入值 / 已提交值分离」——`submittedQuery` 仅在 `submitSearch()`(:147) 时更新，⛔ 不是每次击键都请求。**深链直达**：`BlueprintListCard.vue:45-46` 整卡 `RouterLink :to="/knowledge/blueprints/${item.artifact_id}"`。**项目物料面板**：`ProjectMaterialsPanel.vue:33` `defineAsyncComponent` + :77 `<ProjectBlueprintsCard :project-id hide-when-empty />`（`hide-when-empty` 由面板传入，⛔ 非组件自决），排在既有 `ArtifactTimeline` 之前。**正向引用可查**：`BlueprintAssociationsSection.vue` 两块（citations 按 `source_type` 分组 + 关联项目 `RouterLink`）；**反向部分按 SC 括注顺延 116**，且已被 `sections.spec.ts:595-596` 断言 `getRelated` / `getArtifactAssociations` 调用次数 **== 0**（拿蓝图的 `delivery.Artifact.id` 去调必然落空）|
| SC-5 | 人审终审在查看器内完成：通过（评审人署名、状态到已确认）或驳回（带划线评论回产出中、修订轮次 +1） | ✓ PASS | **两按钮存在且形态刻意为 `disabled` + Tooltip 而非不渲染**（`BlueprintReviewActions.vue:90-91` / :110-111，`:disabled="!canReview"`，Tooltip 走 `review.disabledReason` 带状态插值）—— 与 `readonly` 的「不存在于 DOM」是两种刻意不同的处理。**通过**走 `useConfirmDialog`(:50，无输入框)。**驳回**走受控 `Dialog`（`BlueprintRejectDialog.vue`）：`comment` 必填非空(:79 `isCommentEmpty` 判 `trim().length === 0`)、空/纯空格 ⇒ 提交 `disabled` + 内联 `text-destructive`；底部常驻提示 `review.rejectBody` 插值 **`revisionRound + 1`**(:130) ⇒ 修订轮次 +1 对用户显式可见。**零乐观更新**：动作 2xx 后一律以响应体 `current_status` 为准 + `invalidateQueries({ queryKey: ['blueprint'] })`。⭐ **approve 409 的解药链完整**：`BlueprintBlockedDialog.vue:109` 把 `unresolved_blocker_thread_ids` **逐条** `v-for` 成可点条目 → :94 `emit('goto-thread', threadId)` → 页面设 `activeThreadId` + 滚动定位（超界死锁的唯一正向出口） |

**SC 小计：5/5 PASS。** 7 份 PLAN frontmatter 的 102 条 truths 逐条经下方各节覆盖，无 FAILED、无 UNCERTAIN。**合计 107/107。**

## 两处结构性陷阱的专项复核（本相位专门建了防线，必须确认防线能真的触发）

### 陷阱 1 — `useBlueprintLive` 的 `watch(isLive, ...)` 轮询启动保证

✓ **存在且载荷生效。**

`useBlueprintLive.ts:148-153` 的 `watch(isLive, (on) => { if (on) { docQuery.refetch(); eventsQuery.refetch() } })` 实体存在，带「⛔ 不得删除」的行内说明。

**为什么它是载荷而非装饰**：三个查询分两种形态且**不能统一** —— snapshot 读**自己的** data（:113-116，响应体自带 `current_status`，链条自持）；doc / events 的响应体**没有状态字段**，只能读外部 `isLive`（:135 / :143），而函数体里读外部 ref **不是被追踪的响应式依赖**（vue-query 的 `cloneDeepUnref` 不下探函数体）⇒ 打开一个 `drafting` 蓝图时三查询近乎同时发出，doc/events 先落地而 `currentStatus` 还是 `''` ⇒ 算出 `false`、**永不装定时器、也永不再重算**。首屏有内容、无报错、快照徽标还在跳，而章节进度冻结在打开那一刻。

**变异防线已在库**：`composables/__tests__/useBlueprintLive.spec.ts:102-107` 断言 `isLive` 由 false 翻 true 那一刻 doc/events 的 fetch 次数 **1 → 2**，并在注释里逐字写明「删掉 `watch` 这一条即转红」；:139 另有「一直非活跃则完全不轮询」作**非恒真对照**（防止 `watch` 被写成无条件 `refetch`）。

### 陷阱 2 — 十段 `<section>` 容器无条件渲染 + 静态字面量 id

✓ **十段全部满足，`sections` 数组恒 10 项。**

逐个核对 `pages/knowledge/blueprints/[id].vue`：

| # | `<section id>` | 行 | `v-if`/`v-show` 在 section 上？ |
|---|---|---|---|
| 1 | `requirement_spec` | 962 | ✗ 无 |
| 2 | `repo_associations` | 989 | ✗ 无 |
| 3 | `current_state_analysis` | 1017 | ✗ 无 |
| 4 | `implementation_overview` | 1046 | ✗ 无 |
| 5 | `api_contracts` | 1075 | ✗ 无 |
| 6 | `impact_analysis` | 1103 | ✗ 无 |
| 7 | `interaction_flows` | 1131 | ✗ 无 |
| 8 | `must_haves` | 1160 | ✗ 无 |
| 9 | `decision_log` | 1175 | ✗ 无 |
| 10 | `associations` | 1195 | ✗ 无 |

十个 id 全是**静态字面量**（非 `:id=` 绑定）。全部 `v-if` 落在段**内部**的 `<div>` / `<template>` 上（骨架 `docQuery.isLoading \|\| isSectionPending(...)`、diff 模式 `!isDiffMode`）⇒ 三态渲染发生在容器内，容器本身恒在。`SECTION_KEYS`(:95-106) 与 `sections` computed(:859-870) 都是**硬编码 10 项字面量数组**，⛔ 无按内容动态增删。

**为什么这是头号靶子**：`AnchorNavLayout` 只在 `onMounted` 那一刻按 `props.sections` 逐个 `getElementById`，**既没有 `watch(() => props.sections)` 也没有 `MutationObserver`** ⇒ 若段容器条件渲染，mount 那一刻 DOM 里一个都没有，observer 一个也挂不上，**左栏高亮永远停在第一段而点击跳转照常工作** —— 人肉自测只会觉得「高亮有点迟钝」，不会当成 bug。

外层 `v-if="isFullPageError"`(:877) / `<template v-else>`(:884) 不构成风险：初始 loading 时 `mainError` 为 null ⇒ 走 `v-else` 分支，`AnchorNavLayout`(:915) 随十段一同挂载；错误态恢复时 v-if/v-else 切换触发**重新挂载** ⇒ `onMounted` 重跑。

**badge 传 `''` 不传 `0`**（P-18）已落实：`AnchorNavLayout:95` 的空值判定是 `badge !== undefined && badge !== null && badge !== ''` ⇒ `0` 会被渲染成一个灰色的 0。

## 115-REVIEW.md 四条 MAJOR 修复的独立复验（不采信 Fix Log 自述）

| ID | 声称的修法 | 独立复验结果 |
|---|---|---|
| MJ-01 | `invalidateGate` 从两个精确 key 改回前缀失效 | ✓ **实证**：`BlueprintGatePanel.vue:127-129` 现为 `invalidateQueries({ queryKey: ['blueprint'] })` 单条前缀。与页面 `invalidateBlueprint` 同一口径 ⇒ `doc`（key 尾段 `versionId ?? 'current'`，精确匹配天然写不全）/ `threads` / `events` 三者一并覆盖 |
| MJ-02 | 末态改由会话位序 + 编排终态推断，收敛为单一实现 | ✓ **实证且能真的到 `done`**：`blueprintBlocks.ts:487` 的 `buildStageTimeline(events, currentStage, currentStatus)`，:519 `if (state === 'running' && (settled \|\| (currentIndex >= 0 && index < currentIndex))) state = 'done'` —— `route` / `repo_plan` / `merge` 三个「全部出边都不以 `.completed`/`.locked`/`.failed` 结尾」的阶段由此可达 `done`。`.failed` 后缀**优先**（:513 先判）⇒ 失败阶段不被位序收成完成。⭐ **别名表已补**（:435-442 `repo_confirmation→confirmation` / `reroute→route`）——评审建议的原始修法直接 `indexOf(currentStage)` 会在确认门阶段返 `-1` 而整条位序推断静默失效，这个坑被堵住了。**单一实现**：组件 `BlueprintStageTimeline.vue:122` 只调它、`useBlueprintLive` 的副本已删（其返回对象 :205-214 确无 `stageTimeline`）|
| MJ-03 | 顶栏改读快照权威字段，本地派生降为占位并统一判据 | ✓ **实证且口径与后端逐字一致**：`[id].vue:281-282` `snapshotQuery.data.value?.unresolved_blocker_count ?? counts.value.unresolvedBlocker`（用 `??` 而非 `\|\|` ⇒ 权威值 `0` 不被占位覆盖）。占位判据抽成 `isUnresolvedBlocker`（`blueprintAnnotations.ts:294-298`）= `kind === 'ai_review_finding' && severity === 'blocker' && (status === 'open' \|\| status === 'answered')` —— 与后端 confirm 闸 `blueprint_lifecycle_service.py:441-446` 的三条 AND **逐字相同**，且**不看 `blocking`、不看 `anchor_status`**。`annotationCounts` :316 作用在**全量 `threads`** 上（⛔ 不是 `anchored` 过滤后的 `groups.open`）⇒ `orphaned` 的 open BLOCKER 与 `answered` 的 BLOCKER 两条漏计路径都关上了。同文件 :423 的段徽标共用同一判据，两个派生量不再互相打架 |
| MJ-04 | 后端聚合失败如实 503；前端两处补 `isError` 档 | ✓ **实证两侧齐动**：后端 `blueprint_list_views.py:455-458` 返 `{"detail": _LIST_UNAVAILABLE_DETAIL}` + `HTTP_503_SERVICE_UNAVAILABLE`（⛔ 不回显异常原文；:454 的埋点另包一层 `pass` 保持 best-effort ⇒「best-effort 只覆盖观测不覆盖业务」的边界被钉死）。前端 `BlueprintsTabPanel.vue:286` `v-else-if="listQuery.isError.value"` + `error.unavailable`(:293) / `error.retry`(:296) 重试入口（零新增 i18n）；`ProjectBlueprintsCard.vue:65-69` 的 `hidden` 判据已含 `&& !listQuery.isError.value` ⇒ 读失败时卡片**留下**并出重试(:101-105 `data-testid="project-blueprints-error"`)，不再从项目页凭空消失 |

## Artifacts — 四级检查（存在 / 非 stub / 已接线 / 数据真流）

七份 PLAN 的 must_haves.artifacts 全部 **存在 + 非 stub + 有非测试调用方 + 数据真流**。规模抽样：

| 层 | Artifact | 规模 | `contains` 关键符号 | 状态 |
|---|---|---|---|---|
| 后端 | `delivery/api/blueprint_doc_views.py` | 3 View / 4 端点 | `_aassert_project_scope` ✓ `BLUEPRINT_EVENTS`(:309) ✓ `aopen_selection_comment`(:396/:422) ✓ | ✓ VERIFIED |
| 后端 | `delivery/api/blueprint_list_views.py` | — | `current_status`(:206) ✓ `_STATUS_FIELD`(:77) ✓ 五键 `_EMPTY`(:60-65) ✓ | ✓ VERIFIED |
| 后端 | `delivery/services/blueprint_comment_action.py` | — | `open_thread`(:127) ✓ —— View 零 ORM 写，唯一写口仍是 `BlueprintLifecycleService` | ✓ VERIFIED |
| 后端 | `delivery/urls.py` | +4 path | `blueprint-list`(:142) / `blueprint-document`(:243) / `blueprint-events`(:248) / `blueprint-review-threads`(:253) ✓ | ✓ VERIFIED |
| 数据层 | `composables/useBlueprintLive.ts` | 217 行 | `watch(isLive`(:148) ✓ `LIVE_STATUSES` ✓ | ✓ VERIFIED |
| 数据层 | `utils/blueprintBlocks.ts` | 544 行 | `canonicalBlockFingerprint` ✓ `buildStageTimeline`(:487) ✓ `BLUEPRINT_STAGES`(:396-405) ✓ | ✓ VERIFIED |
| 数据层 | `utils/blueprintAnnotations.ts` | — | `sliceBlockText` ✓ `isUnresolvedBlocker`(:294) ✓ `sidebarGroups` ✓ | ✓ VERIFIED |
| 数据层 | `config/blueprintStatus.ts` | 12 态 | `isBlueprintEditable`(:90) ✓ `PRODUCED_BY_PREFIXES`(:135) ✓ `getBlueprintStatusConfig`(:62) ✓ | ✓ VERIFIED |
| 渲染层 | `components/blueprint/BlueprintBlock.vue` | 16.6K | `data-testid="blueprint-block"` ✓ 五类块分发 ✓ | ✓ VERIFIED |
| 渲染层 | `components/blueprint/BlueprintBlockList.vue` | 6.7K | `selectionchange`(:152) ✓ 配对解绑(:157) ✓ | ✓ VERIFIED |
| 引用层 | `CitationPreviewDialog.vue` + `citation/` 五子件 | 5.8K + 22K | `DialogScrollContent` ✓ `usable`(:88) ✓ `quote` ✓ | ✓ VERIFIED |
| 侧栏/终审 | `BlueprintThreadSidebar/Card/Composer/FindingActions/ReviewActions/RejectDialog/BlockedDialog/QualityPanel/VersionSwitcher/BlockDiff/SelectionPopover` | 11 件 | `sidebarGroups` / `ai_review_finding` / `blueprint-finding-actions` / `goto-thread`(:94) / `noData`(:125) / `diffWords` / `PopoverAnchor` ✓ | ✓ VERIFIED |
| 段组件 | `sections/` 九件 + `BlueprintAssociationsSection` + 四张卡 | 14 件 | `blueprint-must-haves` / `open-thread` / `/repositories/`(:173) / `data_source` / `不可逆` / `source_type` ✓ | ✓ VERIFIED |
| 装配 | `pages/knowledge/blueprints/[id].vue` | ~1280 行 | `AnchorNavLayout`(:915) ✓ 十段 ✓ 六 query 同步 ✓ | ✓ VERIFIED |
| 知识库/项目 | `BlueprintsTabPanel` / `BlueprintListCard` / `ProjectBlueprintsCard` / `FilterBar` | 4 件 | `bp_status`(:81) / RouterLink(:46) / `hide-when-empty` ✓ | ✓ VERIFIED |
| 确认门 | `BlueprintGatePanel.vue` / `BlueprintGateRepoRow.vue` | 17K + 11K | `blueprint-gate-panel` ✓ `RepositoryPicker` ✓ `goto-unresolved` ✓ | ✓ VERIFIED |

**孤儿代码扫描：0 处。** MN-01 曾登记的零消费方 `stageTimeline` 副本已删除，唯一实现落在 `blueprintBlocks.buildStageTimeline`，同源性由 `stageTimeline.spec.ts` 用例 6 锁死（组件渲染出的 `data-state` 与纯函数返回逐节点相同）。

## Key Links — 「声称被强制」的判据逐条定位到强制点

| # | 链路 | 状态 | 证据 |
|---|---|---|---|
| 1 | 五个新端点 → `blueprint_review_views._aassert_project_scope`（import 复用，既有文件零改动） | ✓ WIRED | 四个 artifact 级端点逐个在 `_aload_artifact` 之后立刻挂闸；中性 404 与「不存在」404 用**同一个常量对象** `_ARTIFACT_MISSING_DETAIL`（import 复用非副本）⇒ 逐字节相同。列表端点是同一语义的集合形态（`ProjectMember` 可见集合，零可见项目直接返空且不发任何越权查询）|
| 2 | POST threads/ → `aopen_selection_comment` → `open_thread`（INV-6：View 零 ORM 写） | ✓ WIRED | `blueprint_doc_views.py:396/:422` → `blueprint_comment_action.py:127`；`test_blueprint_inv6_guard.py` 全绿，两个新 View 模块零 ORM 写 |
| 3 | events 端点 → `BLUEPRINT_EVENTS`（21 常量）唯一过滤集合 + `ts` 显式升序 + 无会话 200 空结构 | ✓ WIRED | `:336-337` `event__in=sorted(BLUEPRINT_EVENTS)` + `.order_by("ts")`（显式覆盖 `Meta.ordering = ["created_at"]`）；`:329` 无会话返 `{session_id:"", current_stage:"", events:[]}` ⇒ ⛔ 不是 404（404 会被前端 404 分档吞成全页中性空态）|
| 4 | 正文端点 → `blueprint_quality` 三项统计，`None` 原样透传 | ✓ WIRED | `:113-122` 经**一个** `sync_to_async` 一次性算完（P-15：直调会 `SynchronousOnlyOperation`）；端点侧不包 `?? 0`。前端 `BlueprintQualityPanel.vue:46-48` `formatMetric` 对 `null`/`undefined` 返 `null`，模板 :124 按 `=== null` 分支渲染 `quality.noData` —— **实测该文件 `?? 0` 零命中** ⇒「`null` 用例转红而 `0` 用例仍绿」这类假通过被堵死 |
| 5 | `blockText` 前后端同源（P-13：按字段优先级，**绝不按 `block.type` 分派**） | ✓ WIRED | 后端 `_block_text` 完全不看 `block.type`，schema 对 `text` 无类型约束 ⇒「`type: pseudocode` 且 `text` 非空」完全合法；按 type 分派会得到不同坐标系，而 offset 偏移后**仍在合法范围内** ⇒ 不触发越界降级、不报错、`<mark>` 照渲，只是圈错字。`BlueprintBlock.vue` 一律经 `blockText(block)` 取文本 |
| 6 | `chunk-at` 可用判据封装在 `repositoryChunks.ts` 而非各调用点自判 | ✓ WIRED | 返回 `{chunks, usable}`；`CitationCodePreview.vue:88` 只消费 `usable`（P-3：200-空 chunks 也算不可用，`chunk_at_views` 对「无命中」与「被排除文件」刻意不可区分）|
| 7 | `AnchorNavLayout` 由页面直接使用、不被包裹 | ✓ WIRED | `[id].vue:915` 直接使用，:1276 闭合；第三栏在其默认 slot 内再开一层 `flex gap-6`。`AnchorNavLayout.vue` 本相位零改动 |
| 8 | gate 非 200 不进错误分档（P-10） | ✓ WIRED | `gateQuery` / `diffBaseQuery` / `timelineQuery` **都不在** `mainError` 里（:354 只收四个主查询）；gate 只决定挂载点 `v-if="gateAvailable"`(:1219 / :1225) 是否渲染，⛔ 不报错、不弹 toast。理由是实证的：gate 链八端点里七个无项目范围闸 ⇒ 其 404 混合「门未开 / artifact 不存在 / 无蓝图会话」三种语义，**状态码不携带权限信息** |
| 9 | 404 单一中性文案（存在性防线） | ✓ WIRED | `blueprint-source-guard.spec.ts:108-130` 扫描 `knowledge.blueprints.error.(\w+)` 的键集并拦截中文竞品文案，在 **69 文件非空扫描面**上生效；`BlueprintErrorState.vue` 含 `notFoundOrForbidden` | 
| 10 | 确认门 confirm 409 `pending_clarification` → `goto-unresolved` → 页面打开侧栏未决组 | ✓ WIRED | `BlueprintGatePanel.vue` 坚持读**机器可读**的 `blocked_reason`，未下发时降级到「其余 409」而**不是猜文案** ⇒ ⛔ 无一处按中文 `detail` 文本分支 |

## Requirements Coverage

PLAN frontmatter 声明的全部 requirement ID 与 `REQUIREMENTS.md:146`（「115 前端查看器与知识库 | VIEW-01/02/03/04, CLAR-01, FLOW-08 | 6」）**逐一对齐，无遗漏、无 ORPHANED**。

| Requirement | 声明它的 Plan | REQUIREMENTS.md 描述 | 状态 | 证据 |
|---|---|---|---|---|
| VIEW-01 | 01 / 02 / 03 / 04 / 05 / 06 / 07 | 结构化查看器：六段导航、结构化渲染（流程图 / 伪代码 / API 卡 / 影响矩阵）、状态徽标与阶段时间线（生成中实时进展） | ✓ SATISFIED | 见 SC-1。追溯表 :129 的「查看器本体待 115-02+」已兑现 |
| VIEW-02 | 02 / 03 / 05 | 仓库关联可直接跳转仓库页；引用可再弹一层预览（知识实体 / **代码位置：文件路径 + 行号区间 + 引用快照** / 其他蓝图 / 章程条目） | ✓ SATISFIED | 见 SC-3。:63 的加粗收窄文本与 :130 的追溯注记（「源码正文与行高亮顺延 116」）已同步，本相位交付的正是收窄后的内核 |
| VIEW-03 | 01 / 02 / 06 | 知识库新增「技术方案」tab：列表、状态 / 项目 / 仓库筛选、搜索、深链直达查看器 | ✓ SATISFIED | 见 SC-4 前半。追溯表 :131 的「tab 本体待 115-06」已兑现 |
| VIEW-04 | 01 / 02 / 05 / 06 | 蓝图与项目自动关联；蓝图关联的知识 / 上下文 / 其他蓝图互相可查、可引用（**PARTIAL @ Phase 115**） | ✓ SATISFIED（PARTIAL 的 115 部分） | 正向「本蓝图引用了 + 关联项目」+ 项目物料面板齐备；反向「被谁引用」按 :66 / :132 的 PARTIAL 标注顺延 116（见 deferred 第 2 条）|
| CLAR-01 | 01 / 02 / 03 / 04 / 06 | AI 可对蓝图任意位置发起飞书文档式划线提问（带候选选项），用户在查看器中看到划线高亮并可多轮回复；人也可对任意选区主动发起评论 | ✓ SATISFIED | 见 SC-2。追溯表 :133 的「批注层待 115-03/04」已兑现；`options` 候选选项由 threads GET 补键并由 `BlueprintThreadComposer` 点选填入 |
| FLOW-08 | 02 / 04 / 06 | 蓝图必经人类终审（通过 / 驳回带划线评论）；驳回回产出中修订并计轮次 | ✓ SATISFIED | 见 SC-5。`comment` 必填非空 + `revisionRound + 1` 常驻提示 |

## Anti-Patterns / 债务标记扫描

对本相位 90 个改动文件（`git diff --name-only 88da0d21..HEAD -- server/ web/`）逐个扫描：

| 类别 | 命中 | 判定 |
|---|---|---|
| `TBD` / `FIXME` / `XXX`（BLOCKER 级债务标记） | **0** | ✓ 清白 —— 完成度可审计 |
| `TODO` / `HACK` | **0** | ✓ 清白 |
| `PLACEHOLDER` | 7（`DecisionLogSection.vue` ×5 / `MustHavesSection.vue` ×2） | ℹ️ **非 stub**：这是 `const PLACEHOLDER = '—'` 常量，即 PLAN 明令的「三段可选裸 array 缺键一律渲染「—」，⛔ 不渲染 `undefined`、⛔ 不抛」。属**要求的行为**，不是占位实现 |
| `v-html`（XSS 面） | **0**（`components/blueprint/` 全域） | ✓ 字符区间切分这一最高危处由 `sliceBlockText` 返回结构化数组，组件只做 `v-for` + mustache / `<pre>` |
| 空实现 / 只 `console.log` 的 handler | **0** | ✓ |
| 硬编码空数据流向渲染 | **0** | ✓ Level-4 数据流追踪：十段的数据源均为 `docQuery.data` → `content.<section>`，列表/项目卡为 `listQuery.data.items`（真实 ORM 聚合，见 Key Link 1），时间线为 `eventsQuery.data.events`（真实 `ConvergenceSessionEvent` 查询）|

## 门禁实跑结果（全部本轮亲自执行，不采信 SUMMARY 与 Fix Log 的记录）

| 门 | 结果 | 判定 |
|---|---|---|
| 后端 `uv run pytest tests/ -q` | **8609 passed / 1 failed / 63 skipped / 26 deselected / 1 xfailed**（513s） | ✓ 与预期逐字一致。唯一失败是 `tests/mcp_tools/test_skills_snapshot_guard.py::test_skill_files_discovered` —— **已独立证实为 worktree 环境产物**：本 worktree 的 `skills/` 目录**实测为空**（`ls` 只有 `.` 与 `..`），而主 checkout 的 `skills/` 有 **8** 项。非相位缺陷，且**确认它是唯一的失败** |
| 后端相位专项 `pytest tests/delivery/test_blueprint_{doc,list}_views.py test_blueprint_inv6_guard.py test_blueprint_log_redaction_guard.py -q` | **77 passed** | ✓ |
| `makemigrations --check --dry-run` | **No changes detected** | ✓ 相位内零 migration |
| 前端 `pnpm exec vitest run` | **1674 passed / 1 skipped**（214 文件 passed + 1 skipped） | ✓ 与预期逐字一致。唯一 skip 是既有的 `layouts/__tests__/default.spec.ts:66`，非本相位引入 |
| 前端 `pnpm type-check` | **exit 0** | ✓ |
| 前端 `pnpm build` | **✓ built in 6.14s，exit 0** | ✓ ⚠️ 按既知行为改写 `web/src/components.d.ts`（生成物），已 `git checkout` 还原，工作区 `git status --short` **空输出** |
| 前端 `pnpm lint` | **111 problems**（106 errors / 5 warnings） | ✓ 与基线逐字相同。**判据是「phase-touched 文件零新增」而非整体退出码** —— 实测 27 个告警文件 ∩ 83 个 phase-touched web 文件 = **仅 `web/src/api/index.ts` 一项**，且该项经**独立复核确认为既存**：报的是 `41:1 Expected "./artifacts" to come before "./notifications"`，而 `git show 88da0d21:web/src/api/index.ts` 显示该 `notifications`(:32-33) 早于 `artifacts`(:35-36) 的顺序**在相位之前就存在**，115 的两处追加（blueprints 插在 auth↔chat 之间、repositoryChunks 插在 repositories 之后）只是把它的行号从 35 推到 41。⇒ **零新增 lint 问题** |

## 冻结纪律复核（本相位对并行安全的核心承诺）

| # | 项 | 结论 |
|---|---|---|
| 1 | 整个相位删除行 | ✓ `git diff --stat 88da0d21..HEAD -- server/ web/` = **90 files, +21123, −0** |
| 2 | 五个纯追加点（`pages/knowledge/index.vue` / `ProjectMaterialsPanel.vue` / `api/index.ts` / `styles/main.css` / `locales/zh-CN.json`） | ✓ 纯追加成立（零删除行由 #1 全域覆盖）|
| 3 | migration | ✓ `makemigrations --check` 输出 `No changes detected` |

## Gaps Summary

**无 gap。**

五条 Success Criteria 全部由自动化证据结论性达成，102 条 PLAN truths 无一 FAILED 或 UNCERTAIN，四条 MAJOR 修复经独立复验确认落地且**能真的触发**，两处结构性陷阱的防线（`watch(isLive)` 的 1→2 时序断言、十段静态 id 无条件渲染）实体存在并配有非恒真对照。全相位零债务标记、零 `v-html`、零孤儿代码、零删除行、零 migration，六道门禁全部达到预期基线。

三项 deferred **均非本相位缺口**：其中两项（代码预览的源码正文、反向「被谁引用」）是 ROADMAP SC 文本与 REQUIREMENTS.md **自身**已同步收窄并显式标注顺延 116 的**范围决策**——它们的收窄有实证依据（`chunk-at` 无正文读面；`getArtifactAssociations` 查的是另一张表），验证按收窄后的文本判定；第三项（MN-03 的 400 分支存在性预言机）是 115-REVIEW 判为设计决策的**既有后端面**，四条理由充分（400 本身即四条语义契约之一、属 114 的 🔒 零改动面、改成 404 会给真成员造出恢复死路即 MN-02 刚修掉的形状、暴露面只限 `meta.project_id` 非 UUID 的小批），已在 `.planning/STATE.md:152` 登记与 Phase 116 的另两条权限项一并定夺——**它不影响任何一条 SC**（五条 SC 均为查看器能力判据，无一依赖该闸的回显语义）。

`human_verification` 的四项均标 `blocking: false`：它们是 happy-dom 无版面引擎（`getBoundingClientRect` 返回零矩形）与 mermaid 需真实渲染引擎所致的**视觉抛光面**，各自的**可判定内核已由自动化覆盖**（选区的触发与载荷、时间线的段容器前置条件、mermaid 的 prop 名与空源码 `v-if`）。故不将整个相位路由为 `human_needed`。

---

## 附录（2026-08-02 追加）：四条视觉 UAT 的浏览器实跑

四项 `why_human` 给的理由**全部是 happy-dom 的能力缺口**，而不是真需要人的判断。Chromium 有版面引擎、真 `getBoundingClientRect`、真 IntersectionObserver、真媒体查询 ⇒ 四条理由同时消解。已用既有 Playwright 护栏（`web/playwright.config.ts`，chromium + 10250 端口 + `page.route` API 替身、不起后端）从 `/knowledge/blueprints/:id` **真实路由入口**实跑，⛔ 全程不挂叶子组件。

| # | UAT | 判定 | 覆盖它的 spec | 变异证据 |
|---|---|---|---|---|
| 1 | mermaid 出图 | ✓ PASS | `blueprint-viewer-visual.spec.ts` › `UAT 115-1`（3 例） | `svg.value = ''` ⇒ 转红；去掉调用方空源码闸 ⇒ **冒出 2 个空 `<pre>`** 转红 |
| 2 | 选区 popover 落点 | ✓ PASS（判定核心） | 同上 › `UAT 115-2`（2 例） | 锚点退化成零矩形 ⇒ 浮层飘出 **352px** 转红；dismiss 时清选区 ⇒ Esc 保留选区转红 |
| 3 | 左栏高亮跟随滚动 | ✓ PASS（**并修 1 缺陷**） | 同上 › `UAT 115-3`（2 例） | 给 `#impact_analysis` 加 `v-if` ⇒ 第 5 项永不点亮转红（P-4 的缺陷形状） |
| 4 | 响应式断点 | ✓ PASS | 同上 › `UAT 115-4`（4 例） | 常驻栏 `xl:flex`→`lg:flex` ⇒ 1024px 下两份侧栏同时可见，两例转红 |

**⭐ 新发现并已修复的缺陷（第 3 项）**：`AnchorNavLayout` 的观察窗 `rootMargin: -15% 0px -55% 0px` 在文档首尾各留了一段死区，而回调的 `if (visible.length > 0)` 在死区内不更新 ⇒ **滚回顶部时高亮冻在离开前那一段**（实测视口 720px 时观察窗 108~324px，首段起点 349px）。这与 P-4 防的「永远停在第一段」是同一类失守、方向相反，且四个使用方（蓝图查看器 / 知识实体 / 仓库 / 空间详情）都受影响。修法：相交集合为空时补一次基于位置的兜底。commit `0fd29f56`。

**残留人工项**：四项各自的 `residual_human` 逐条列在 frontmatter 里，⛔ 未因主体转绿而整条勾掉。其中一条需要人拍板：第 2 项 expected 的「popover 贴着选区**末端**」与实现不符 —— 实现把整个选区矩形作为锚点、`side="top"` ⇒ 浮层落在选区**正上方居中**。可判定内核（不遮挡 / 贴着 / 锚在选区上）成立，但措辞与实现二者要改一个。

执行报告见 `.planning/UAT-AUTOMATION-REPORT.md` §10。**本附录不改动上方任何 SC / truths 判定，`status` 与 `score` 保持原值。**

---

_Verified: 2026-08-01_
_Verifier: Claude (gsd-verifier)_
_Depth: goal-backward · 对抗性立场（默认未达成，由代码证据反证）_
_视觉 UAT 子集实跑追加: 2026-08-02_
