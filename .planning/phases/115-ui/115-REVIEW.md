---
phase: 115-ui
status: findings
reviewed: 2026-08-01
findings_total: 7
critical: 0
major: 4
minor: 3
depth: deep
---

# Phase 115 Code Review — 蓝图查看器前端面（阶段 5）

**审查基线：** `88da0d21` → `HEAD`（`milestone/v0.20.0-blueprint` worktree）
**审查范围：** `git diff 88da0d21..HEAD -- server/ web/` 的 88 个文件（源 66 / 测试 22），**+20153 / −0**；`.planning` 文档不审
**深度：** deep（跨模块调用链：REST 端点 → TS 契约 → composable → 组件树 → 失效链；后端判据 ↔ 前端派生的逐项比对）
**立场：** 对抗性复核。七份 SUMMARY 自述的变异验证已覆盖 `watch(isLive)` 启动保证、十段容器无条件渲染、`blockText` 字段优先级、finding/作答通道渲染层分流等**单文件内**的失效模式，本轮逐条复验后不复算它们（结论见文末「复核过、确认干净的面」），主打的是**跨文件语义漂移**：一侧的「正确实现」如何与另一侧的判据悄悄对不上。

**结论：0 CRITICAL / 4 MAJOR / 3 MINOR。** 授权面、XSS 面、冻结纪律、INV-6 与脱敏守卫**全部干净**（见文末两节）。

四条 MAJOR 里 **两条经真实代码路径实测复现**（探针已删除，`git status --short` 空输出）：

| # | 实测结果 |
|---|---|
| MJ-02 | 造一份「每个能发终态事件的阶段都发了」的完整事件流 + `currentStatus='confirmed'` → 挂载 `BlueprintStageTimeline` → 实测 `{"spec_gate":"done","route":"running","repo_research":"done","confirmation":"done","repo_plan":"running","merge":"running","ai_review":"done","pending_review":"idle"}`，页面上**三个 `animate-spin` 转圈**永不停 |
| MJ-03 | 一条 `orphaned` 的 open BLOCKER finding → `annotationCounts().unresolvedBlocker === 0`；一条 `answered` 的 BLOCKER finding → **同样 0**；对照组（`anchored` + `open`）→ `1`（证明判据非恒假） |

---

## MAJOR

### MJ-01：确认门七个动作只失效 `gate` + `snapshot` 两个 key，正文/线程/事件三个查询永不重取 —— 点完「确认锁定」后仓库关联段停在锁定前的内容

**文件：** `web/src/components/blueprint/BlueprintGatePanel.vue:115-118`（`invalidateGate`）、`:137`/`:153`（七个动作与 409 分支的唯一失效点）；对照 `web/src/pages/knowledge/blueprints/[id].vue:554-556`；`web/src/composables/useBlueprintLive.ts:143`（`docQuery` 的 `staleTime: 30_000`）

**问题：**

面板自持七个动作，全部经同一条通道收尾，而那条通道只失效两个**精确 key**：

```115:118:web/src/components/blueprint/BlueprintGatePanel.vue
function invalidateGate(): void {
  queryClient.invalidateQueries({ queryKey: ['blueprint', 'gate', props.artifactId] })
  queryClient.invalidateQueries({ queryKey: ['blueprint', 'snapshot', props.artifactId] })
}
```

文件头的设计说明写的是「⭐ **双 invalidate**（`['blueprint','gate',id]` 与 `['blueprint','snapshot',id]` —— 确认门动作会同时改蓝图状态与线程）」。**「线程」那半句没有兑现**：侧栏的线程数据源是页面自建的 `threadsQuery`，key 是 `['blueprint','threads',artifactId]`（`[id].vue:210`），**不在这两个 key 里**。正文同理（`['blueprint','doc',…]`），阶段事件同理（`['blueprint','events',…]`）。

而这三个查询确实会被确认门动作改掉：

- `confirm/` 的 docstring 逐字写着「由 `BlueprintConfirmGateAdapter.alock` **落蓝图新版本**（`confirmed_at_gate` / `decided_by=human` / `responsibility` + `decision_log`）」（`server/delivery/api/blueprint_gate_views.py:224-226`）⇒ `doc` 过期；
- `remove_repo` / `add_repo` / `reclassify_role` / `edit_responsibility` 都改 `repo_associations` 并各自接 `aresume_after_gate_action` ⇒ `doc` 与 `events` 都过期；
- 确认门线程（`kind=repo_confirmation`）随动作开合 ⇒ `threads` 过期。

**为什么这不是「下一次轮询会自愈」**：`docQuery` 的 `staleTime` 是 **30 秒**，而 `confirm` 成功后蓝图落 `confirmed` ⇒ `isLive` 为假 ⇒ `refetchInterval` 返回 `false`，**轮询本来就停了**。于是正文停在锁定前那一版，直到用户手动刷新或窗口重新聚焦。可观察症状很具体：状态徽标（走 `snapshot`，已失效）立刻翻成「已确认」，而正下方 `repo_associations` 段的 `RepoAssociationCard` **仍然不带「确认门已确认」徽标、职责仍是旧文本**。用户看到的是「确认成功了，但仓库那块没变」——最容易被读成「确认没生效，再点一次」。

同一页面自己那一半反而是对的（前缀失效，全域覆盖）：

```554:556:web/src/pages/knowledge/blueprints/[id].vue
function invalidateBlueprint(): void {
  queryClient.invalidateQueries({ queryKey: ['blueprint'] })
}
```

面板刻意从前缀收窄成两个精确 key，收窄时漏了三个。

**建议修法：** 与页面统一走前缀失效——本页只有一个 artifact，全域失效无副作用，这也正是页面侧已经采纳的理由：

```ts
function invalidateGate(): void {
  queryClient.invalidateQueries({ queryKey: ['blueprint'] })
}
```

若坚持精确 key（例如为了不打扰知识库 tab 的 `['blueprint','list',…]`），那必须补齐五个：`gate` / `snapshot` / `doc` / `threads` / `events`。⚠️ 注意 `doc` 的 key 尾段是 `versionId ?? 'current'`，精确匹配写不全，这本身就是应该用前缀的理由。

补一条断言：`confirm` 成功后 `invalidateQueries` 覆盖了 `['blueprint','doc',id,'current']` 与 `['blueprint','threads',id]`（用 `queryClient.getQueryState(...).isInvalidated` 断言，⛔ 不断言调用次数——那不能证明覆盖面）。

---

### MJ-02：阶段时间线的 `route` / `repo_plan` / `merge` **在语义上永远到不了 `done`**，蓝图跑完之后三个阶段永久转圈

**文件：** `web/src/utils/blueprintBlocks.ts:374-392`（`EVENT_STAGE_MAP`）、`web/src/components/blueprint/BlueprintStageTimeline.vue:131-140`（末态判据）与 `:188-190`（`animate-spin` 渲染）；同一份判据在 `web/src/composables/useBlueprintLive.ts:183-189` 还有一份副本（见 MN-01）

**问题：**

末态判据是**按事件名后缀**推断的：

```131:140:web/src/components/blueprint/BlueprintStageTimeline.vue
    let state: StageState = 'idle'
    if (latest) {
      if (latest.event.endsWith('.failed'))
        state = 'failed'
      else if (latest.event.endsWith('.completed') || latest.event.endsWith('.locked'))
        state = 'done'
      else state = 'running'
    }
```

把 `EVENT_STAGE_MAP` 按 stage 摊开，逐个看有没有一条出边能命中 `.completed` / `.locked` / `.failed`：

| stage | 映射到它的全部事件 | 能否 `done` |
|---|---|---|
| `spec_gate` | `spec_gate.scored` / `.clarification_asked` / **`.locked`** | ✅ |
| `route` | `route.scored` / `reroute.triggered` | ❌ **恒 running** |
| `repo_research` | `.started` / **`.completed`** / `.failed` | ✅ |
| `confirmation` | `confirmation.opened` / `.action` / **`.locked`** | ✅ |
| `repo_plan` | `context.entry_appended` | ❌ **恒 running** |
| `merge` | `context.waiter_registered` / `.waiter_satisfied` | ❌ **恒 running** |
| `ai_review` | `review.started` / **`.completed`** / `.failed` | ✅ |
| `pending_review` | （无事件，靠 `currentStage` 兜底） | — |

三个阶段的全部出边都不以那三个后缀结尾 ⇒ 只要它们发过**任何一条**事件，`state` 就永久钉在 `running`。

**实测复现**（探针：造齐上表里每个阶段能发的终态事件 + `currentStatus='confirmed'`，挂载组件读 `li[data-stage]` 的 `data-state`）：

```
{"spec_gate":"done","route":"running","repo_research":"done","confirmation":"done",
 "repo_plan":"running","merge":"running","ai_review":"done","pending_review":"idle"}
→ wrapper.findAll('.animate-spin').length === 3
```

即一份**已经 confirmed、编排早已结束**的蓝图，时间线上依然有三个阶段挂着 `icon-[lucide--loader-2] animate-spin` 与「进行中」徽标。这是典型的静默假通过：不报错、不空白、看着还很「活」，只是永远不对。

**为什么没有通用的 stage 完成事件可用**：`blueprint.stage.started` / `.completed` / `.failed` 三个常量虽在 `BLUEPRINT_EVENTS` 里，但 `event_taxonomy.py:133` 自述「供 112+ 编排阶段消费（**本相位仅定义常量**）」，全仓 `rg` 确认**零 emit 点**。所以前端把它们排除在 `EVENT_STAGE_MAP` 外是对的——问题在于排除之后没有替代的完成信号。

**建议修法：** 完成信号其实已经在手上——组件已经收了 `current-stage`（页面传 `eventsQuery.data.value?.current_stage`），只是仅用于 `idle → running` 的兜底。改成按 `BLUEPRINT_STAGES` 的顺序推断即可，不需要后端补事件：

```ts
const currentIndex = BLUEPRINT_STAGES.indexOf(props.currentStage)
// …在按后缀判完之后：
if (state === 'running' && currentIndex >= 0 && BLUEPRINT_STAGES.indexOf(stage) < currentIndex)
  state = 'done'          // 会话已经走过这个阶段
```

并对终态状态（`confirmed` / `implementing` / `implemented` / `archived`）把所有发过事件的阶段一律收成 `done`（`__done__` 时 `indexOf` 返回 `-1`，需单独短路）。⚠️ **两处都要改**（组件与 composable，见 MN-01），否则修一半。

补一条断言：给定上面那份完整事件流 + `confirmed`，八个 stage 里 `running` 的数量为 **0**；再并列一条「`repo_research.started` 之后没有 `.completed` ⇒ 该 stage 仍 `running`」作非恒真对照。

---

### MJ-03：侧栏与顶栏的「未决 BLOCKER」计数与后端 confirm 判据不是同一口径 —— 失锚的与已作答的 BLOCKER 一律漏计，而权威字段就在响应体里没人用

**文件：** `web/src/utils/blueprintAnnotations.ts:279-281`（`annotationCounts`）与 `:257`（`anchored` 前置过滤）；消费点 `web/src/pages/knowledge/blueprints/[id].vue:849`；后端判据 `server/delivery/services/blueprint_lifecycle_service.py:441-446`

**问题：**

后端「未决 BLOCKER」的口径是三条 `AND`，**既不看 `blocking`、也不看 `anchor_status`**：

```441:446:server/delivery/services/blueprint_lifecycle_service.py
        return await BlueprintThread.objects.filter(
            artifact=artifact,
            kind=ThreadKind.AI_REVIEW_FINDING,
            severity=ThreadSeverity.BLOCKER,
            status__in=[ThreadStatus.OPEN, ThreadStatus.ANSWERED],
        ).acount()
```

前端算的是另一件事：

```279:281:web/src/utils/blueprintAnnotations.ts
    unresolvedBlocker: groups.open.filter(
      thread => thread.severity === 'blocker' && thread.blocking,
    ).length,
```

`groups.open` 的定义是 `anchored.filter(status === 'open')`，而 `anchored = list.filter(t => t.anchor_status !== 'orphaned')`（`:257`、`:263`）。两处差异叠加：

1. **`status === 'answered'` 的 BLOCKER 被漏掉**（后端明确算未决）；
2. **`anchor_status === 'orphaned'` 的 BLOCKER 被漏掉**——这一条完全可达：一条锚在某 block 上的 BLOCKER finding，只要那个 block 在后续版本里被删/改到重锚失败，`areanchor_threads` 就会把它落 `orphaned`，而它的 `status` 仍是 `open`、仍然挡 confirm。

**实测复现**（三条并列，第三条是非恒假对照）：

```
orphaned + open + blocker + blocking  → unresolvedBlocker = 0   （后端算 1）
anchored + answered + blocker         → unresolvedBlocker = 0   （后端算 1）
anchored + open + blocker             → unresolvedBlocker = 1   ✓
```

后果落在 `[id].vue:849`：顶栏的批注计数条与「未决 BLOCKER」徽标全部取这个值。于是人审看到「0 条未决 BLOCKER」，点「确认」却吃 **409**。虽然 `BlueprintBlockedDialog` 会把 409 响应体里的 `unresolved_blocker_thread_ids` 逐条列出来（那条解药链路是对的，也是本相位做得好的地方），但**点击之前的信息面是错的**——顶栏在鼓励用户去点一个必然失败的按钮。

同一页面里 `sectionTones`（`[id].vue:385`）用的是 `status === 'open' || status === 'answered'`，**与后端一致**——所以两个派生量在同一个文件里就已经互相打架：左栏段徽标标红，顶栏计数说 0。

**更直接的问题是权威值明明已经在手上**：人审快照响应体带 `unresolved_blocker_count`（`web/src/types/blueprint.ts:547`，后端 `blueprint_review_views.py:401` 由上面那个方法产出），页面已经在查这个快照，却拿它当没有。

**建议修法：** 顶栏计数改读快照的权威字段，前端派生只用于「哪几条要高亮」这类纯呈现：

```ts
:counts="{
  blocker: snapshotQuery.data.value?.unresolved_blocker_count ?? counts.unresolvedBlocker,
  …
}"
```

若坚持前端自算（例如快照未就绪时的占位），也必须把口径对齐：判据改成「`kind === 'ai_review_finding' && severity === 'blocker' && (status === 'open' || status === 'answered')`」，且**在 `anchored` 过滤之前**从全量 `threads` 上算——失锚是锚定维度，与「挡不挡确认」正交（这正是 `sidebarGroups` 自己文件头写明的那条纪律，`annotationCounts` 没跟上）。

补两条断言：① 一条 `orphaned` 的 open BLOCKER ⇒ 计数为 1；② 一条 `answered` 的 BLOCKER ⇒ 计数为 1；并保留「resolved 的 BLOCKER ⇒ 0」作对照。

---

### MJ-04：列表端点把聚合异常吞成 200 空结构，两个消费方又把空结果渲染成「暂无技术方案」—— 整表读失败与真的没数据在界面上完全同形

**文件：** `server/delivery/api/blueprint_list_views.py:410-428`（`_aggregate` 整体 try/except → 返空结构）；消费方 `web/src/components/knowledge/BlueprintsTabPanel.vue:270-299`（无 `isError` 分支）、`web/src/components/project/warroom/ProjectBlueprintsCard.vue:57`（`hidden` 判据不含错误态，且 `retry: false`）

**问题：**

后端把**整个聚合**（不只是观测）包在一个 `except Exception` 里，失败时返回 200 + 空结构：

```418:428:server/delivery/api/blueprint_list_views.py
        except Exception as exc:  # noqa: BLE001 — 聚合/观测永不反噬请求（返空结构不 500）
            logger.warning(
                "blueprint_list_read_failed",
                …
            )
            return Response({**_EMPTY, "page": page, "page_size": page_size})
```

`.cursor/rules/observability-logging.mdc` 的「观测代码 best-effort，失败吞掉，绝不打断主流程」约束的是**观测代码**；这里被包住的 `_aggregate` 是**业务主体本身**（queryset + 可见性过滤 + 行装配 + `_load_names` 两次查询）。任何一处出问题——DB 抖动、`Repository` 表查询失败、半可信 `content` 触发未预期的类型错误——都会被翻译成「该用户一份蓝图都没有」，而 HTTP 层完全无从分辨。

前端两个消费方把这个歧义坐实：

- `BlueprintsTabPanel`：`v-if isLoading` → `v-else-if items.length` → **`v-else` 直接是 `CompactEmptyState`「暂无技术方案」**（`:294-299`）。全文件没有一处读 `listQuery.isError` / `.error`。所以 400（手改 URL 传了非 UUID 的 `project_id`）、500、网络断线，一律显示「暂无技术方案」。
- `ProjectBlueprintsCard`：更糟一档。`hidden = hideWhenEmpty && !isLoading && items.length === 0`（`:57`）——错误态满足这个式子，而宿主 `ProjectMaterialsPanel` 正是传 `hide-when-empty` 用的。⇒ 一次请求失败（`retry: false`，**不重试**），整张「技术方案蓝图」卡**从项目页上消失**，无任何痕迹。

这是本轮最典型的「silent false-pass」形状：三层设计各自都「不反噬主流程」，合起来就是数据读失败对用户完全不可见，且与正常空态像素级相同。

**建议修法（两侧都要动，只改一侧仍会漏）：**

① 后端把 except 收窄到真正该兜的面，聚合失败如实 5xx（观测仍 best-effort）：

```python
except Exception as exc:
    logger.warning("blueprint_list_read_failed", …)
    return Response(
        {"detail": "蓝图列表暂时读取不到，请稍后重试"},
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )
```

若产品上确实要保「列表端点永不 5xx」，那至少要在 200 响应体里加一个机器可读的 `degraded: true`，让前端能把「读失败」与「没数据」分开——⛔ 不能只靠日志，日志不在用户的界面上。

② 前端两处各补一个 `isError` 分支：tab 面板走「暂时读取不到 + 重试」（`knowledge.blueprints.error.unavailable` / `.retry` 两个键已存在，无需新增 i18n）；`ProjectBlueprintsCard` 的 `hidden` 判据加 `&& !listQuery.isError.value`，让失败时卡片**留下**并显示重试，而不是凭空消失。

补两条断言：① `listBlueprints` reject ⇒ tab 面板出现重试按钮且**不出现**「暂无技术方案」；② `ProjectBlueprintsCard` 在 `hideWhenEmpty` 且请求失败时 `data-testid="project-blueprints-card"` **仍然存在**。

---

## MINOR

### MN-01：`useBlueprintLive.stageTimeline` 零消费方，同一段派生逻辑在组件里另有一份副本

**文件：** `web/src/composables/useBlueprintLive.ts:168-195`（定义）与 `:252`（导出）；副本在 `web/src/components/blueprint/BlueprintStageTimeline.vue:115-160`

115-02 SUMMARY 把 `stageTimeline` 写进了 composable 的返回契约（§3「115-03/04/06 逐字消费」），但 `rg 'stageTimeline' src/` 全仓命中只有**它自己的定义、它自己的导出、以及一句提到它的测试注释**。页面在 `[id].vue:197-207` 解构 `useBlueprintLive()` 时**没有取它**，而是把原始 `events` 传给 `BlueprintStageTimeline`，由组件用一段**逐字重复**的 `buckets` + `BLUEPRINT_STAGES.map` + 后缀判末态重新算一遍。

两处唯一的差别是 `idle` 兜底：composable 用 `stage === 'pending_review' && currentStatus === 'pending_review'`，组件用 `stage === props.currentStage`。也就是说副本不仅重复，还已经开始漂移。

行为上今天无害（消费方只有一个），但它让 MJ-02 那类修复必须**记得改两个地方**，而只改 composable 那份会「看起来修好了」（单测绿）而界面纹丝不动。

**建议修法：** 二选一，别留两份。要么页面改成 `const { stageTimeline } = useBlueprintLive(...)` 并把 `:nodes="stageTimeline"` 传进组件（组件退化为纯呈现）；要么把 composable 里那段连同 `StageTimelineNode` 一起删掉，在 `blueprintBlocks.ts` 里留一个纯函数 `buildStageTimeline(events, currentStage)` 供组件调用。后者更贴合本相位「纯函数集中在 utils」的既有分层。

---

### MN-02：`?version=` 指向不存在/不属于本 artifact 的版本时，整页被替换成「无权访问或该蓝图不存在」，且没有回到当前版本的出口

**文件：** `server/delivery/api/blueprint_doc_views.py:253-255`（`_VERSION_MISSING_DETAIL` 走 404）；`web/src/pages/knowledge/blueprints/[id].vue:313-341`（`mainError` 含 `docQuery` → `isFullPageError`）

正文端点对「版本不存在或不属于该 artifact」返回 **404**（这在后端是对的：带上 `artifact_id` 约束防跨项目读版本，见 115-01 偏差 5）。但前端的分档只看**状态码**：`docQuery` 的任何 404 都进 `isFullPageError` ⇒ 整页替换成 `BlueprintErrorState` 的中性档，文案是「无权访问或该蓝图不存在」，唯一动作是「返回知识库」。

于是一个带了失效 `?version=` 的分享链接（版本被 superseded 清理、或链接是手抄的），会让一份**用户完全有权限、且当前版本好好的**蓝图显示成「无权访问或不存在」，而页面上的「回到当前版本」按钮（`:891`）此刻已经跟着整页一起被替换掉了——用户只能手改 URL 或退回知识库重进。

这不是安全问题（版本不存在与无权限共用 404 是刻意的、也应该保持），是**恢复路径缺失**。风险低但触发即死路。

**建议修法：** 不动后端、不新增 404 文案键（那会破坏存在性防线）。在前端把「带着 `?version=` 时正文 404」单独归一档：既然此时 `snapshotQuery` / `threadsQuery` 都还是 200（它们不带 version 参数），说明权限没问题、只是那个版本号不对——可以直接**自动回落到当前版本**（`versionParam.value = ''` 并 refetch），或退一步只在错误态里追加一个「回到当前版本」按钮。判据是纯结构化的（`versionParam` 非空 且 `docQuery` 404 且 `snapshotQuery.isSuccess`），⛔ 不需要读 `detail` 文本。

---

### MN-03：范围闸的 400 fail-closed 分支先于成员判定，对「`meta.project_id` 不合法」的那批 artifact 仍构成存在性预言机

**文件：** `server/delivery/api/blueprint_review_views.py:274-281`（`_aassert_project_scope`，114 引入、115 原样复用到四个新端点）

闸的顺序是：superuser 直通 → 取 `meta.project_id` → **非 UUID 即 400** → 非成员 404。

```274:281:server/delivery/api/blueprint_review_views.py
    if getattr(request.user, "is_superuser", False):
        return None
    project_id = await _ablueprint_project_id(artifact)
    if not _is_uuid(project_id):
        return Response(_SCOPE_UNRESOLVED_DETAIL, status=status.HTTP_400_BAD_REQUEST)
    if not await _ais_project_member(request.user, project_id):
        return Response(_ARTIFACT_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND)
```

「非成员 404」与「artifact 不存在 404」确实**逐字相同**（同一个 `_ARTIFACT_MISSING_DETAIL` 常量对象，115-01 特意 import 复用而不自定义——这一条做得很对，本轮逐个端点核对过响应体一致）。但 **400 那一档没有参与这个等式**：一个未授权用户拿 artifact id 探测时，

- id 不存在 → **404**；
- id 存在、`meta.project_id` 缺失或非 UUID（历史数据里就有 `"proj-0001"` 这种形状，115-01 偏差 4 正是用它造的数）→ **400**。

⇒ 对这一子集，状态码差分直接泄露存在性。范围有限（只覆盖 project_id 不合法的那批蓝图），且这是 114-MJ-03 修复时引入、115 只是原样扩用到四个只读端点——**不是 115 新造的**，但 115 把暴露面从 7 个端点扩到 11 个，登记在此。

**建议修法：** 把 fail-closed 的**拒绝语义**保留、**回显语义**收敛——非 superuser 一律回中性 404，400 只留给 superuser（他们需要知道真实原因，且对他们不存在存在性问题）：

```python
    if not _is_uuid(project_id):
        return Response(_ARTIFACT_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND)
```

（superuser 已在上一行 return `None` 直通，所以这一行只影响普通用户，仍然是 fail-closed 拒绝。）⚠️ 这会翻掉 114/115 现有的 `test_*_fail_closed_*` 断言，改判据时要同步——那些用例断的是 400，改成断「与不存在同形的 404」语义更强。

---

## 冻结纪律与门禁复核（`git diff 88da0d21..HEAD`）

| # | 项 | 结论 |
|---|---|---|
| 1 | 四个 §13.2 零改动组件（`chat/TechPlanCard.vue` / `chat/RoutingDecisionPanel.vue` / `execution/NodeDataTab.vue` / `delivery/ArtifactTimeline.vue`） | ✓ `--name-only` **零输出** |
| 2 | `codegraph/services/repo_router_v2.py` | ✓ 零输出 |
| 3 | 六个 legacy `technical_plan` process 文件 + 整个 `server/services/process_runtime/` | ✓ **整目录零输出** |
| 4 | `blueprint_review_views.py` / `artifact_views.py` / `blueprint_lifecycle_service.py` / `blueprint_anchor.py` / `event_taxonomy.py` | ✓ 全部零输出（`ConvergenceSessionEvent` 既有类型/字段未动，115 **未新增**任何事件常量） |
| 5 | 五个获批追加点（`pages/knowledge/index.vue` / `ProjectMaterialsPanel.vue` / `api/index.ts` / `styles/main.css` / `locales/zh-CN.json`） | ✓ `rg "^-[^-]"` **删除行 = 0**，纯追加成立 |
| 6 | migration | ✓ `git diff --name-only -- server/ \| rg migrations` **零命中**，相位内零 migration |
| 7 | 全 diff 形态 | ✓ **88 files, +20153, −0** —— 整个相位零删除行 |
| 8 | 后端门 | ✓ 实跑 `pytest tests/delivery/test_blueprint_{doc,list}_views.py test_blueprint_inv6_guard.py test_blueprint_log_redaction_guard.py -q` → **74 passed** |
| 9 | 前端门 | ✓ 实跑 `pnpm exec vitest run` → **1640 passed / 1 skipped（213 文件）**，唯一 skip 是既有的 `layouts/__tests__/default.spec.ts:66` |

## 复核过、确认干净的面（不计入 findings）

- **授权（本轮重点靶子）**：四个 artifact 级端点（`blueprint/` / `blueprint/events/` / `threads/` GET / `threads/` POST）**逐个**在 `_aload_artifact` 之后立刻 `await _aassert_project_scope(...)`，四条语义齐全；中性 404 与「不存在」404 用的是**同一个常量对象**（`_ARTIFACT_MISSING_DETAIL` 经 import 复用，非副本）⇒ 逐字节相同，无法差分（唯一缺口是 MN-03 的 400 档）。列表端点是同一语义的集合形态：superuser 直通、非 superuser 取 `ProjectMember` 集合、**零可见项目直接返空且不发任何越权查询**（`:396-408`）。**新增的 POST（全仓第一个主动开线程入口）额外过了状态闸**（`is_blueprint_editable` + 复用 `NOT_EDITABLE_DETAIL`，`blueprint_doc_views.py:412-413`），闸在任何写之前、越界时 DB 一字未动；`?version_id=` 带 `artifact_id` 约束（`:94-96`），不能借自己的 artifact 读别人项目的版本正文。
- **P-4 十段容器（本相位头号靶子）**：十个 `<section>` 的 `id` **全部是静态字面量**、**无一带 `v-if`/`v-show`**，骨架/进度/实渲三态全部发生在容器内部（`v-if` 落在段内的 `<div>`/组件上）；`sections` 数组长度硬编码恒为 10。它们位于 `AnchorNavLayout` 默认 slot 内且随其一同挂载，`onMounted` 里的 `getElementById` 逐个命中 —— 左栏 IntersectionObserver 不会挂空。
- **BLOCKER-1 轮询启动保证**：`watch(isLive, …)` 确实存在（`useBlueprintLive.ts:158-163`）且带「⛔ 不得删除」的说明；三查询两形态与 SUMMARY 一致；`refetchInterval` 字面量在组件/页面侧零命中（源码守卫断言 2 覆盖）。
- **finding / 作答通道分流**：`BlueprintThreadCard.vue:245-259` 是**结构性** `v-if="isFinding"` / `v-else` 两条互斥分支——finding 分支的 DOM 里**根本不存在** `BlueprintThreadComposer` 节点，⛔ 不是 `disabled`、⛔ 不是 `v-show`。且 `BlueprintFindingActions` **不受 `readonly` 约束**（作答框才是 `v-if="!readonly"`），超界死锁的正向出口保住了。
- **XSS**：蓝图扫描面 **`v-html` 零命中**（源码守卫断言 6 + 本轮独立复扫）；字符区间切分（本相位最高危处）由 `sliceBlockText` 返回**结构化数组**，`BlueprintBlock.vue` 只做 `v-for` + mustache / `<pre>`；表格单元格、`quoted_text`、消息正文、citation `quote` 全部走文本插值。
- **`CompactEmptyState` 裸名契约 / Tailwind safelist**：本轮把新增代码里**全部**运行期拼接的图标名逐个对过 safelist —— 12 态徽标（含 unknown 兜底 `help-circle`）、5 档 `produced_by_ref`、4 档 `change_type`、9 类 citation `source_type`、以及 11 个经 `CompactEmptyState` 传裸名的空态图标，**无一遗漏**；`.vue` 里的字面量完整类名（`icon-[lucide--target]` 等）按 SUMMARY §8.2 的说明确实不需要 safelist。
- **错误分档**：`gateQuery` / `diffBaseQuery` / `timelineQuery` **都不在** `mainError` 里（`[id].vue:313-325` 只收四个主查询），gate 的 404 只让挂载点 `v-if="gateAvailable"` 不渲染、不报错不弹 toast；`?panel=gate` 深链在目标缺席时静默摘掉 query。全仓复扫确认**没有任何一处按中文 `detail` 文本分支**（gate 面板的 409 两档坚持读机器可读的 `blocked_reason`，未下发时降级到「其余 409」而不是猜文案）。
- **INV-6 / 命名守卫 / 脱敏守卫**：三个新模块全部进了 `test_blueprint_log_redaction_guard._SCANNED_MODULES`（`:28-31`）；`_STATUS_FIELD` 常量确实让 `_RE_FIELD_WRITE` / `_RE_FIELD_SETATTR` / `_RE_FIELD_DICT_KEY` 三条正则全部落空，响应键统一 `current_status`；两个新 View 模块零 ORM 写（唯一写路径 POST 委托 `blueprint_comment_action` → `open_thread`）。四条守卫实跑全绿。
- **async / ORM 纪律**：`_collect_db_quality` / `_load_thread_details` / `_aggregate` / `_load_member_project_ids` 全部 `@sync_to_async` 或经 `sync_to_async(...)` 调用；**手写「先聚合再切片」分页的全部 DB 工作（含 `_load_names` 的两次批量查询）都在 `_aggregate` 函数体内**，没有一处落在 async 上下文里；线程消息走 `Prefetch` + `select_related("author")` 防 N+1；`.order_by("created_at")` / `.order_by("ts")` 显式给足（`BlueprintThread.Meta` 无 `ordering`，114-MN-01 的纪律有跟上）。
- **观测**：五个新端点各有 `caller` 事件、`component` 齐全、`duration_ms` 到位；正文类实参**一律只记长度**（`body_len` / `q_len` / `citation_count` / `message_count`），本轮逐个 `logger.*` 调用核对，**未发现蓝图正文 / finding 正文 / 澄清问答 / citation quote 进日志**；异常文本全部经 `_detail`（`redact_secrets_in_text` + 截断 500）或 `redact_secrets_in_text`。
- **内存/监听**：蓝图面唯一的全局监听是 `BlueprintBlockList.vue:152` 的 `document.addEventListener('selectionchange', …)`，`onUnmounted` 有配对 `removeEventListener`（`:155-158`，同一个 `useDebounceFn` 引用，能真解绑）；扫描面内零 `setInterval`、零自建 observer。
- **块类型分发**：`BlueprintBlock.vue` 的五分支没有 `v-else` 兜底，但后端 schema 对 `type` 是 `enum: [paragraph, pseudocode, table, list, mermaid]` 的**闭集**（`blueprint_schema.py:57-61`）⇒ 未知 type 不可达，不构成缺陷。
- **事件常量对齐**：脚本比对后端 `BLUEPRINT_EVENTS`（21）与前端 `EVENT_SECTION_MAP` / `EVENT_PROGRESS_KEY` 的键集 —— **双向完全一致，零遗漏零多余**（`EVENT_STAGE_MAP` 少的四个是 `blueprint.stage.*` 三兄弟与 `status.transitioned`，前三者全仓零 emit、后者刻意不映射，属正确；由此暴露的是 MJ-02，不是对齐问题）。

---

_Reviewed: 2026-08-01_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
