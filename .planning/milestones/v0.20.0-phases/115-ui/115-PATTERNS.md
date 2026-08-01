---
phase: 115
slug: ui
kind: patterns
mapped: 2026-07-31
worktree: .claude/worktrees/v0.20-blueprint
branch: milestone/v0.20.0-blueprint
upstream:
  - .planning/phases/115-ui/115-UI-SPEC.md
  - .planning/phases/115-ui/115-RESEARCH.md
  - .planning/phases/115-ui/115-CONTEXT.md
  - .planning/STATE.md
  - .planning/phases/114-ai/114-PATTERNS.md
new_files: 64          # 后端 5（含 2 测试）+ 前端 57 + 前端测试若干（PLAN 定）
append_points: 6       # 前端 5（STATE §13.2 穷举）+ 后端 urls.py 1（另加 1 个守卫清单）
analogs_found: 57
no_analog: 7
valid_until: "111–114 模块与 web/src 既有件在 rebase 中改动即需重核行号"
---

# Phase 115: 前端查看器与知识库 - Pattern Map

**Mapped:** 2026-07-31
**Files analyzed:** 64 类新建文件 + 6 处纯追加点
**Analogs found:** 57 / 64（7 项无近似先例，见 No Analog Found）

> 与 `115-RESEARCH.md` 的分工：RESEARCH 回答「**能不能做、会不会踩坑**」（五端点必要性核验 + 18 条 Pitfalls + 可复用件速查表），本文件回答「**照着哪个文件写、抄它的哪一段、哪里必须不一样**」。凡 RESEARCH 已实读的契约（`AnchorNavLayout` 的 mount-only 观察、`MermaidDiagram` 的 prop 名、`chunk-at` 的 200-空 chunks、INV-6 三条正则…）本文件**不复述结论**，只在对应文件的「必须 DIFFER」栏引用其编号（P-1 … P-18）。

---

## §0 边界纪律（先读这一节，否则 analog 抄对了边界也会破）

### 0.1 前端 CREATE-ONLY —— 六处追加穷举（第七处 = 计划不通过）

| # | 文件 | 允许的追加 | 抄谁的形状 |
|---|---|---|---|
| 1 | `web/src/pages/knowledge/index.vue` | `KnowledgeTab` 联合类型（`:40`）+ `TABS` 数组（`:41`）+ `TabsTrigger` 内联 `as const` 数组（`:220-234`）+ 一个 `TabsContent` | 该文件自身的既有四项，逐字同构 |
| 2 | `web/src/components/project/warroom/ProjectMaterialsPanel.vue` | 一行 `defineAsyncComponent`（`:27-30` 四行的第五行）+ 分区流里一处使用 | `:52` `<HumanTaskInbox :project-id hide-when-empty />` |
| 3 | `web/src/api/index.ts` | 两组 `export { default as xxxApi } from './x'` + `export * from './x'` | `:25-27` knowledge 组 |
| 4 | `web/src/styles/main.css` | `@source inline(...)` 追加行（`:10-20` 的第 N+1 行） | `:13` `icon-[lucide--file-text] icon-[lucide--lock] …` |
| 5 | `web/src/locales/zh-CN.json` | `knowledge.blueprints.*` 子树 + `knowledge.tabs.blueprints` | 既有 `knowledge.tabs`（`:227-233`） |
| 6 | `server/delivery/urls.py` | 四条 `path(...)` + 一个分组注释 | `:187-190` 的 blueprint-review 分组注释纪律 |

⚠️ **第 7 处（非 §13.2 归属面，但仍是既有文件修改，PLAN 必须显式登记）**：`server/tests/delivery/test_blueprint_log_redaction_guard.py:27-37` 的 `_SCANNED_MODULES` —— 该文件 `:14` docstring 逐字写明「新增蓝图模块请一并加进」。**不加 = 新模块的 `error=str(exc)` 裸写不被守卫覆盖**（P-16）。

### 0.2 三条会静默让绿测转红的守卫（新建后端文件必须先读）

| 守卫 | 扫描面 | 本相位的撞车点 | 规避（照抄既有解法） |
|---|---|---|---|
| INV-6 字段写 (`test_blueprint_inv6_guard.py:57,61`) | 整个 `server/`（除 writer/tests/migrations） | 列表端点的 `filter(blueprint_status=…)` 与响应键 `{"blueprint_status": …}` | 响应键改 **`current_status`** —— 逐字照 `blueprint_review_action._current_status`（`:141-150`，它的 docstring **就是**这条规避的说明书）；ORM 过滤走模块常量 `_STATUS_FIELD = "blueprint_status"` + `filter(**{_STATUS_FIELD: value})` |
| INV-6 写入口 (`_RE_ORM_WRITE` / `_RE_INSTANTIATE`) | 同上 | `POST threads/` 若 `BlueprintThread.objects.create(...)` 或裸 `BlueprintThread(...)` | 唯一合法写口 `BlueprintLifecycleService.open_thread`；View 零 ORM 写，走新 service（见 §2） |
| TOCTOU 扫描 (`test_blueprint_review_threads.py:365-392`) | `delivery/api/` **整目录** | 列表端点若 `import aunresolved_blocker_count` **且**同文件出现 `BlueprintStatus.CONFIRMED` | 计数一律 ORM `annotate(Count(...))` 自算（本来就该这样，逐条调 async 函数是 N+1） |

---

## File Classification

### A. 后端（`server/`）

| # | 新建/追加文件 | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|---|
| A1 | `delivery/api/blueprint_doc_views.py`（正文 / events / threads GET+POST 四端点） | view (adrf) | request-response | `delivery/api/blueprint_review_views.py`（114-05，七端点 + 范围闸 + `_log`） | exact |
| A2 | 同文件内 `_aassert_project_scope` 复用 | authz helper | guard | `blueprint_review_views.py:254-281` 及其三个依赖 helper | exact（**import 复用，不造第三份**） |
| A3 | `delivery/api/blueprint_list_views.py`（`GET /delivery/blueprints/`） | view (adrf) | batch + 分页 | `knowledge/api/artifact_overview.py`（「先聚合再切片」的异步手写分页） | exact |
| A4 | `delivery/services/blueprint_comment_action.py`（选区评论建线程） | service | CRUD（事务） | `blueprint_review_action._aopen_reject_comment`（`:427-463`，全仓唯一「人工评论开线程」实现） | exact |
| A5 | `delivery/urls.py` 追加四路由 | config table | — | `urls.py:187-225`（blueprint-review 分组） | exact |
| A6 | `tests/delivery/test_blueprint_doc_views.py` / `test_blueprint_list_views.py` | test | — | `tests/delivery/test_blueprint_review_views.py`（「守十四件事」+ 范围闸工厂） | exact |

### B. 前端 —— 数据层与配置（先建，其余全部依赖它）

| # | 新建文件 | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|---|
| B1 | `web/src/api/blueprints.ts` | api module | request-response | `web/src/api/deliveryArtifacts.ts`（同域、只读、`get` 薄封装 + `export default`） | exact |
| B2 | `web/src/api/repositoryChunks.ts` | api module | request-response | 同上 | exact |
| B3 | `web/src/types/blueprint.ts` | types | — | `web/src/types/prompts.ts` | exact |
| B4 | `web/src/config/blueprintStatus.ts` | config table | — | `web/src/config/status.ts`（`StatusConfig` + `Record<string, StatusConfig>` + `getXxxConfig` 兜底） | exact |
| B5 | `web/src/utils/blueprintBlocks.ts`（前端 `iter_blocks` + diff 分类 + `blockText`） | pure functions | transform | `web/src/utils/variableRef.ts`（契约型 JSDoc + 零依赖纯函数） | role-match |
| B6 | `web/src/utils/blueprintAnnotations.ts`（区间切分 + offset 计算） | pure functions | transform | 同上（**算法本体零先例**，见 No Analog #1） | role-match |
| B7 | `web/src/stores/useBlueprintViewerStore.ts` | pinia store | client state | `web/src/stores/analyticsFilters.ts`（25 行 setup store） | exact |
| B8 | `web/src/composables/useBlueprintLive.ts` | composable | polling | `components/project/workbench/DocsSection.vue:73` + `components/repository/ReconcilePanel.vue:59` 的**函数式 `refetchInterval`** | role-match |
| B9 | `web/src/composables/useBlueprintAnnotations.ts` | composable | client state | `composables/useConfirmDialog.ts`（模块级单例 + 返回受控 API） | partial |
| B10 | `web/src/composables/useCitationPreview.ts` | composable | client state | `pages/knowledge/index.vue:165-191`（受控 Dialog 的 open/loading/data 三 ref 范式） | exact |

### C. 前端 —— 页面与查看器骨架

| # | 新建文件 | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|---|
| C1 | `pages/knowledge/blueprints/[id].vue` | page | request-response | `pages/knowledge/entities/[id].vue`（类型化 route + `useHead` + `AnchorNavLayout` + 三 query + `is404`） | exact |
| C2 | `components/blueprint/BlueprintViewerHeader.vue` | component | props/emits | `pages/executions/components/ExecutionHeader.vue`（顶栏 + 动作区 + `defineEmits<{}>`） | role-match |
| C3 | `components/blueprint/BlueprintStatusBadge.vue` | component | — | `components/common/StatusBadge.vue`（`withDefaults` + `icon-[${config.icon}]`）+ `components/spec/SddSpecStatusBadge.vue`（`data-testid` + i18n label） | exact |
| C4 | `components/blueprint/BlueprintStageTimeline.vue` | component | — | `components/repository/IndexProgressTimeline.vue`（分组 + `StatusBadge` + `.card`/`px-5 py-3.5`/`p-5` 骨架） | role-match |
| C5 | `components/blueprint/BlueprintSectionNav.vue` | component | props/emits | `components/analytics/TimeRangeSelector.vue`（`Select` + 单 emit） | role-match |
| C6 | `components/blueprint/BlueprintErrorState.vue` | component | — | `components/common/CompactEmptyState.vue` 的**调用方**（`pages/repositories/[id]/index.vue:498`，传裸图标名 + 默认 slot 放按钮） | exact |

### D. 前端 —— 内容渲染（17 件）

| # | 新建文件 | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|---|
| D1 | `BlueprintBlock.vue`（批注 + 引用唯一实现点） | component | transform | **无整体 analog**：块类型分发抄 `PromptVersionDiff.vue` 的 `v-for` + `<pre>` mustache；`<mark>` 切分零先例（No Analog #1） | partial |
| D2 | `BlueprintBlockList.vue` | component | — | `IndexProgressTimeline.vue` 的「分组 + `v-if` 空态 + Skeleton」 | role-match |
| D3 | `BlueprintCitationChip.vue` | component | — | `components/knowledge/EntityKindBadge.vue` / `SddSpecStatusBadge.vue`（映射表 + `data-testid`） | role-match |
| D4-D12 | `sections/*.vue`（9 段） | component | — | `pages/knowledge/entities/[id].vue:117-162` 的 `<section :id>` + `Skeleton`/实渲/`CompactEmptyState` 三分支 | exact |
| D13 | `BlueprintAssociationsSection.vue` | component | request-response | `components/knowledge/EntityAssociationsCard.vue` | role-match（**数据源必须换，见 P-5**） |
| D14-D17 | `RepoAssociationCard` / `ImplementationItemCard` / `ApiContractCard` / `ImpactMatrixTable` | component | — | `components/knowledge/EntityMetadataCard.vue` + `~/components/ui/table`（`web/DESIGN.md` 标准卡片 `.card` + `px-5 py-3.5` + `p-5`） | role-match |

### E. 前端 —— 批注与线程（6 件）

| # | 新建文件 | Role | Closest Analog | Match |
|---|---|---|---|---|
| E1 | `BlueprintThreadSidebar.vue` | component | `components/delivery/HumanTaskInbox.vue`（分组收件箱 + `hide-when-empty`） | role-match |
| E2 | `BlueprintThreadCard.vue` | component | `components/knowledge/EntityRelationTree.vue` 的行卡 + `defineEmits<{}>` | role-match |
| E3 | `BlueprintThreadComposer.vue` | component | `components/feedback/MarkdownField.vue`（`Textarea` + `defineEmits<{}>`） | role-match |
| E4 | `BlueprintFindingActions.vue` | component | `components/accessTokens/AccessTokenRevealDialog.vue`（受控 `Dialog` + 必填输入 + `update:open`） | role-match |
| E5 | `BlueprintSelectionPopover.vue` | component | **零先例**（No Analog #2） | none |
| E6 | `annotationTokens.ts` | config table | `web/src/config/status.ts` + `components/knowledge/artifactDisplay.ts`（`ARTIFACT_BADGE_CLASS`） | exact |

### F. 前端 —— 版本 / diff / 人审 / 确认门（8 件）

| # | 新建文件 | Closest Analog | Match |
|---|---|---|---|
| F1 | `BlueprintVersionSwitcher.vue` | `components/knowledge/EntityVersionTimeline.vue` + `~/components/ui/select` | role-match |
| F2 | `BlueprintBlockDiff.vue` | `components/prompts/PromptVersionDiff.vue`（**逐字级 analog**） | exact |
| F3 | `BlueprintReviewActions.vue` | `pages/specs/[id].vue` 的状态流转动作区 + `useConfirmDialog` | exact |
| F4 | `BlueprintRejectDialog.vue` | 同 E4 | role-match |
| F5 | `BlueprintBlockedDialog.vue` | 同 E4（**内容形状零先例**：可点清单 → 跳线程） | partial |
| F6 | `BlueprintQualityPanel.vue` | `components/common/StatCard.vue` | role-match |
| F7 | `BlueprintGatePanel.vue` | `components/project/warroom/ContextLinksCard.vue`（行列表 + 行内多动作 + 二次确认） | role-match |
| F8 | `BlueprintGateRepoRow.vue` | 同上的行组件 | role-match |

### G. 前端 —— 引用预览（6 件）与知识库 / 项目侧（4 件）

| # | 新建文件 | Closest Analog | Match |
|---|---|---|---|
| G1 | `CitationPreviewDialog.vue` | `pages/knowledge/index.vue:23-29,165-191`（`Dialog` + `DialogScrollContent` + 受控 open/loading/data） | exact |
| G2 | `citation/CitationKnowledgePreview.vue` | `pages/knowledge/entities/[id].vue` 的 `EntityMetadataCard` + `MarkdownRenderer` | role-match |
| G3 | `citation/CitationCodePreview.vue` | **无只读 CodeMirror 封装**（No Analog #3） | none |
| G4 | `citation/CitationCharterPreview.vue` | `pages/repositories/[id]/index.vue` 的章程分区 | role-match |
| G5 | `citation/CitationBlueprintPreview.vue` | 复用本相位的 `BlueprintBlockList`（`readonly`、无批注） | self |
| G6 | `citation/CitationFallback.vue` | `CompactEmptyState.vue` 的调用形态 | role-match |
| G7 | `components/common/FilterBar.vue` | **契约在 `web/DESIGN.md:198-211`、仓内零实现**（No Analog #4） | none |
| G8 | `components/knowledge/BlueprintsTabPanel.vue` | `components/knowledge/KnowledgeDashboard.vue`（筛选 + 网格 + `ui/pagination`，`:801-808`） | exact |
| G9 | `components/knowledge/BlueprintListCard.vue` | `components/knowledge/DeliveryDocsTree.vue` 的条目卡 + `.card .card-interactive` | role-match |
| G10 | `components/project/warroom/ProjectBlueprintsCard.vue` | `components/delivery/HumanTaskInbox.vue`（`hide-when-empty` prop）+ `ProjectMaterialsPanel` 的 `.flat-section`/`.flat-header`（`:57-66`） | exact |

---

## Pattern Assignments

### A1/A2. 四个 artifact 级端点 → `delivery/api/blueprint_doc_views.py`

**Analog:** `server/delivery/api/blueprint_review_views.py`（794 行，114-05）

**结构要点（逐条照抄）：**

- **模块 docstring = 契约书**（`:1-56`）：端点清单 → 授权判据（⭐ 段）→ 「为什么新建文件而不塞进既有文件」→ 写入纪律（INV-6）→ 观测口径（末段逐字：「**评论正文、block 正文、答案正文、处置理由正文一律不进日志**」）。
- **基类 `from adrf.views import APIView`**（`:64`），**不是** `rest_framework.views.APIView`；`permission_classes = [IsAuthenticated]` 逐 View 声明。
- **模块级常量三类**：`_COMPONENT`（`:72`）、中性 404 文案 dict（`:75-77`）、上界常量（`:94`）。
- **只读 helper 全部懒 import 模型**：

```100:127:server/delivery/api/blueprint_review_views.py
async def _aload_artifact(artifact_id: Any) -> Any:
    from delivery.models import Artifact

    return await Artifact.objects.filter(id=artifact_id).afirst()


async def _aload_session(artifact_id: Any) -> Any:
    """按 artifact 反查其**蓝图**编排会话（取最近一条）。

    ``process_type="technical_blueprint"`` 过滤**不可省**：蓝图链刻意复用
    ``technical_plan`` 这个 ``artifact_type``，同一 artifact 上完全可能同时挂着
    ``technical_plan`` 与 ``technical_blueprint`` 两条会话。
    """
```

- **取基线版本的唯一口径**（`:162-171`，`order_by("-version_no")`，非 dict 回 `{}`）：

```162:171:server/delivery/api/blueprint_review_views.py
async def _alatest_content(artifact: Any) -> dict:
    from delivery.models import ArtifactVersion

    content = await (
        ArtifactVersion.objects.filter(artifact_id=artifact.id)
        .order_by("-version_no")
        .values_list("content", flat=True)
        .afirst()
    )
    return content if isinstance(content, dict) else {}
```

- ⭐ **行级序列化 = 手写 dict builder，不是 DRF serializer**（本文件全域零 serializer）：

```174:186:server/delivery/api/blueprint_review_views.py
def _thread_row(thread: Any) -> dict:
    """线程 → 快照条目。**带 ``thread_id``**：前端据此直接调处置/作答端点。"""
    return {
        "thread_id": str(thread.id),
        "kind": str(thread.kind or ""),
        ...
        "created_at": thread.created_at.isoformat() if thread.created_at else "",
    }
```

  逐值 `str(x or "")` / `bool(x)` / `isinstance(...) else None` 归一 —— 半可信字段一律不裸传。

- **范围闸四语义**（`:254-281`）：superuser 直通 → `meta.project_id` 取范围 → 非 UUID/缺失 **400**（fail-closed）→ 非成员**中性 404** → 放行返 `None`。
- **端点埋点统一 helper**（`:284-294`）：

```284:294:server/delivery/api/blueprint_review_views.py
def _log(event: str, request: Any, artifact_id: Any, started: float, **fields: Any) -> None:
    """端点级 caller 事件（只记标量与关联键；**任何用户正文都不进来**）。"""
    logger.info(
        event,
        category="caller",
        component=_COMPONENT,
        artifact_id=str(artifact_id),
        initiated_by_user_id=str(getattr(request.user, "id", "") or "system"),
        duration_ms=round((time.monotonic() - started) * 1000, 2),
        **fields,
    )
```

- **共用前置三元组 helper**（`:325-337`）：`(error_response | None, artifact, session)`，闸在里面，View 只 `if error is not None: return error`。
- **只读 GET 也记 caller 事件**（`:406-413`，`blueprint_review_snapshot_read` 带 `thread_count` / `orphaned_count`）。
- **`started = time.monotonic()` 放在 helper 之前第一行**（`:361`）。

**沿用（四端点各自的形状）：**

| 端点 | 抄哪一段 | 必须 DIFFER |
|---|---|---|
| `GET blueprint/` | `BlueprintReviewSnapshotView.get`（`:357-414`）整段骨架：`started` → `_aload_artifact` → 404 → `_aassert_project_scope` → 装配 payload → `_log` → `Response` | `?version_id=` 指定版本时**不能**用 `_alatest_content`（它只取最新），需新写 `_aload_version(artifact_id, version_id)`；`is_current` 判据用 `artifact.current_version_id == version.id`（RESEARCH §A.1），**不用 version_no 最大**；`quality` 三项是**同步函数 + 内部 ORM** ⇒ 合成一个 `@sync_to_async def _collect_quality(artifact_id)`（P-15），⛔ 端点侧不再包 try 把 `None` 改写成 0 |
| `GET blueprint/events/` | 同上骨架 + `_aload_session`（`:106-126`，**必带 `process_type`**） | 会话不存在**回 200 空结构**（`{session_id:"", current_stage:"", events:[]}`），⛔ 不 404 —— 404 会被前端 §8.2 分档吞成全页空态（RESEARCH §A.3）；`.order_by("ts")` 显式覆盖 `Meta.ordering` |
| `GET blueprint-review/threads/` | `_thread_row`（`:174`）+ `_load_thread_rows`（`:189-196`，`@sync_to_async` + 显式 `order_by("created_at")`） | ⭐ **在 `_thread_row` 九键之上扩写一个 `_thread_detail_row`（同款手写 dict），绝不引入 DRF serializer** —— 本文件家族零 serializer，混进来会让同一响应里出现两套 None/空串口径。补 `options`（逐项 `.get` 防御）/ `last_reminded_at` / `messages[]`；`messages` 的 `author` 是 `SET_NULL` FK ⇒ `author_display` 必须容忍 `None`；N+1 走 `prefetch_related(Prefetch("messages", queryset=...select_related("author")))` |
| `POST blueprint-review/threads/` | `BlueprintReviewThreadAnswerView.post`（`:633-716`）的前六行：`_aload_action_context` → `is_blueprint_editable(artifact)` 不过 **400 且 DB 一字未动** → body 取值 → 空串 400 | 写入委托新 service（A4），View 零 ORM 写；成功后接 `_aresume(session, request)`（`:297-310`，⛔ 不重复包 try、不因续驱失败改响应码） |

**避免：** 同步 `rest_framework.views.APIView`；View 内 `BlueprintThread.objects.create`；把 `content` 内联进 `blueprint-review/` 快照（快照要被高频重取）；为 `quality` 的 `None` 补 0；复制第三份 `_aassert_project_scope`（**要么提到 `delivery/api/blueprint_scope.py` 并把 `blueprint_review_views.py` 改成 import —— 这是对既有文件的修改，PLAN 要显式登记；要么直接 `from delivery.api.blueprint_review_views import _aassert_project_scope` 并注释说明**，RESEARCH §A.5）。

---

### A3. 列表端点 → `delivery/api/blueprint_list_views.py`

**Analog:** `server/knowledge/api/artifact_overview.py`（250 行，KDEP-03；全仓唯一「adrf + 先聚合再切片 + 手写分页」）

**结构要点：**

- **两个 clamp 纯函数 + 一个 `_EMPTY` 常量**：

```46:62:server/knowledge/api/artifact_overview.py
def _parse_page(raw: str | None) -> int:
    """?page= 解析，clamp 到 >=1；非法值 fail-soft 取 1。"""
    try:
        return max(1, int(raw)) if raw is not None else 1
    except (TypeError, ValueError):
        return 1


def _parse_page_size(raw: str | None) -> int:
    """?page_size= 解析，clamp 到 [1, _MAX_PAGE_SIZE]；非法值 fail-soft 取默认。"""
    if raw is None:
        return _DEFAULT_PAGE_SIZE
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_PAGE_SIZE
    return max(1, min(value, _MAX_PAGE_SIZE))
```

- **纯同步聚合函数 + `sync_to_async` 单点调用**（`_aggregate:131`，`await sync_to_async(_aggregate)(...)` `:226`）—— 全部 ORM 在一个同步函数内，View 里零 ORM。
- **响应五键**（`:181-188`）：`{total, items, page, page_size, has_next}`，`has_next = offset + len(items) < total`。
- **权限 fail-closed 短路**（`:211-223`）：可见集合为空 → 直接返 `dict(_EMPTY)` + completed 日志，**零 DB 越权**。
- **聚合整体 `try/except` 返回空结构不 500**（`:229-238`，「聚合/观测永不反噬请求」）。
- **started/completed 两条 caller 日志**（`:202-209` / `:240-248`），只记计数与参数。
- **UUID query param 前置 400** 用 `artifact_views._parse_uuid_param`（`:45-55`）范式（返 `(值|None, 是否合法)` 二元组）。

**沿用：**

- 可见性口径 = 先算「我是成员的 project id 集合」（`initiatives.models.ProjectMember.objects.filter(user=request.user)`，与 `blueprint_review_views._ais_project_member`（`:244-251`）同源）+ superuser 直通（与 `_aassert_project_scope:274` 对称）。
- 候选收窄走索引：`artifact_type="technical_plan"` + `blueprint_status != ""`（`models/artifact.py:123` 的复合索引），`select_related("current_version")` 后在 Python 侧按 `content["meta"]["project_id"] ∈ allowed` / `?q=` 摘要 / `?repository_id=` 过滤，**过滤之后**再切片。
- `thread_count` / `unresolved_blocker_count` 走 ORM `annotate(Count(...))`（`BlueprintThread` 有 `Index(["artifact","status","blocking"])`）。

**必须 DIFFER（三条，PLAN 逐条写死）：**

1. ⛔ **`resolve_allowed_project_ids` 不能直接用** —— 它返回的是**可见 Space id** 不是 project id（`artifact_overview.py:7,26` docstring 逐字）。analog 的这一行是本相位唯一不能照抄的行。
2. ⛔ **响应键 `current_status` 而非 `blueprint_status`**，ORM 过滤走 `_STATUS_FIELD` 常量（§0.2 / P-1）。**同步订正 UI-SPEC §3.3 的 TS 接口与前端消费点**。
3. **与 UI-SPEC §3.3「DRF 分页体」的分歧由 PLAN 定夺**：方案 A 需要 Python 侧过滤后切片 ⇒ DRF `paginate_queryset` 用不上。建议取 `artifact_overview` 五键并订正 UI-SPEC；⛔ 不发明第三套分页体。

**避免：** 改 `ArtifactListView`（`artifact_views.py:58-98`，无项目可见性过滤、返裸数组无分页，已被 `ArtifactTimeline.vue:43` 消费）；用 `searchDeliveryKnowledge`；对 N 条候选逐条跑 `_aassert_project_scope`；`import aunresolved_blocker_count`（§0.2 第三条）。

---

### A4. 选区评论建线程 → `delivery/services/blueprint_comment_action.py`

**Analog:** `server/delivery/services/blueprint_review_action.py:427-463`（`_aopen_reject_comment`，全仓唯一「人工评论 → `human_comment` 线程」实现）

```443:452:server/delivery/services/blueprint_review_action.py
        thread = await lifecycle.open_thread(
            artifact,
            kind=ThreadKind.HUMAN_COMMENT,
            blocking=False,
            question=body,
            anchor=anchor if isinstance(anchor, dict) else None,
            created_on_version=version,
            initiated_by_user_id=initiated_by_user_id,
            return_stage=BlueprintStatus.DRAFTING,
        )
```

**结构要点：**

- 模块 docstring 首段声明 **INV-6**：「视图零 ORM 写……全部落库都在本模块经 `BlueprintLifecycleService` 完成」（`:3-5`）。
- `__all__` 显式列公开函数（`:72-79`）；`_COMPONENT` 常量（`:81`）。
- 三个共用 helper：`_user_id`（`:131`，回落 `"system"`）、`_detail`（`:136`，`redact_secrets_in_text` + 截断 500）、`_alatest_version`（`:153`，⛔ 绝不读 `session.current_artifact_version`）。
- **恒定键返回 dict**（`{status, thread_id, detail, ...}`），`status` 是闭集，端点只做 status → HTTP 码映射。
- **`kind` 用 `ThreadKind` 枚举常量，不是字面量**；`blocking=False`、`severity=""` ⇒ 评论不受 finding 不变式约束、不把蓝图钉死。
- **正文只进 `question=`，绝不进日志**（`:438` docstring 逐字），日志只记 `has_comment` / `reason_len` 这类标量。
- 收尾一条 `logger.info` 五件套：`category="caller"` + `component` + `artifact_id` + `initiated_by_user_id` + `duration_ms=round((time.monotonic()-started)*1000, 2)`。

**必须 DIFFER：**

- analog 是**驳回的副作用**（best-effort，开不出线程也返空串不上抛）；本相位的 `POST threads/` 是**主动作** ⇒ 开线程失败必须如实回错（`status="invalid"` + `_detail(exc)`），⛔ 不吞。
- `created_on_version` 传**当前最新版本**（`_alatest_version`），它回答「这条评论是针对哪一版提的」。
- `return_stage` 取值需与 UI-SPEC §3.5 对齐；`max_length=16`，超长会被 service 截断 + warning。
- 新模块必须加进 `test_blueprint_log_redaction_guard._SCANNED_MODULES`（§0.1 第 7 处）。

---

### A5. 路由追加 → `delivery/urls.py`

**Analog:** `urls.py:187-225`（114-05 的 blueprint-review 分组）

```187:195:server/delivery/urls.py
    # 阶段 4 人审（114-05，FLOW-07 / CLAR-03 / CLAR-04）：1 个只读快照 + 6 个动作端点
    # （含 B2 的 finding 处置两端点），前缀 blueprint-review/ 与阶段 1 的 blueprint-gate/
    # 区分。字面段 threads/ 在 <uuid:thread_id> 之前；三个 threads/<uuid>/<动作>/ 路由的
    # 动作段互不重叠，与 artifact-timeline 的整段精确匹配同样互不遮挡。
    path(
        "artifacts/<uuid:artifact_id>/blueprint-review/",
        BlueprintReviewSnapshotView.as_view(),
        name="blueprint-review-snapshot",
    ),
```

**沿用：** 分组注释先声明「几个端点 + 前缀语义 + 字面段/uuid 段的顺序纪律」；`name=` 全部 `reverse()` 可解析（测试范式 `reverse("blueprint-review-thread-resolve")`）；字面段写在 uuid 段之前（`threads/` 在 `threads/<uuid>/…` 前，即使 Django 整段精确匹配无所谓 —— **保持读者预期一致**）。

**必须 DIFFER：** `blueprints/` 是**顶层字面段**，不在 `artifacts/` 分组内，须与 `artifacts/`（`:133`）同级并单列注释。

---

### A6. 后端测试 → `tests/delivery/test_blueprint_doc_views.py` / `test_blueprint_list_views.py`

**Analog:** `server/tests/delivery/test_blueprint_review_views.py`（1102 行）

**结构要点：**

```1:12:server/tests/delivery/test_blueprint_review_views.py
"""阶段 4 人审七端点 REST 测试（Phase 114-05 Task 3，FLOW-07 / CLAR-03 / CLAR-04）。

守十四件事（断言一律**从 DB 重读**，不信响应体）：

1. ⭐ **鉴权第一条**：七端点未认证一律拒（401/403），无一例外（参数化七条）。
2. **只读快照**：无 artifact → 中性 404；有数据 → 200 且含 findings 分级分组（每条带
   ``thread_id``）/ 澄清线程 / **失锚列表** / 未决清单 / ``revision_round``。GET
   **不接续驱**，且 ⭐ **不触发提醒**（伪挂载点已移除）。
```

- **docstring「守 N 件事」编号清单**，每条把可证伪断言写进条目本身。
- `pytestmark = pytest.mark.django_db(transaction=True)`（`:67`）—— async service 跨线程写库必须 `transaction=True`；REST client 是同步的 ⇒ 同步用例 + `async_to_sync` 装配（`:33-34`）。
- **源码扫描断言**：`_VIEWS_REL = "delivery/api/blueprint_review_views.py"`（`:70`）+ `SERVER_DIR = Path(__file__).resolve().parents[2]`（`:69`）。
- **范围闸工厂**：`_SCOPE_PROJECT_ID` / `_OTHER_PROJECT_ID`（`:83-84`）+ `_make_project(project_id, member=...)`（`:87`）—— 本相位五端点的闸测试逐字复用。
- 懒 import 的 patch 目标要指向**来源模块**（`:73-75` 的注释：「视图内是函数级懒 import ⇒ 必须 patch **来源模块**的属性」）。

**沿用（本相位守护点）：**

| 文件 | 守护点 |
|---|---|
| `test_blueprint_doc_views.py` | 四端点未认证一律拒；⭐ **非成员 → 中性 404 且响应体与「不存在」逐字相同**（正反并列：成员 200 / 非成员 404 / superuser 200）；`meta.project_id` 缺失 → 400；`?version_id=` 取历史版本且 `is_current == False`；⭐ **`quality.ai_rejection_rate` 无数据回 `null` 不是 0**（三态并列 `null`/`0`/正值）；events 端点**无会话回 200 空结构不是 404**；events 按 `ts` 升序且只含 21 个 `BLUEPRINT_EVENTS`；threads GET 含 `options` / `last_reminded_at` / `messages[]` 且 `author` 为 None 时 `author_display` 不炸；⭐ **threads POST 在不可编辑状态下 400 且线程数不变**；body 空 400；视图零 ORM 写源码扫描 |
| `test_blueprint_list_views.py` | 未认证拒；⭐ **只列「我是成员的项目」的蓝图**（造两个项目正反并列）；superuser 见全部；`blueprint_status == ""` 的旧 artifact 不出现；分页五键与 `has_next` 边界；`?q=` 命中标题与摘要各一例；⭐ **响应键是 `current_status`**（防回归：若改回 `blueprint_status`，INV-6 守卫转红——本条与守卫互为双保险） |

**避免：** class 风格 `TestCase`；只断言响应体不重读 DB；漏鉴权/越权的负向用例；async service 测试忘 `transaction=True`。

---

### B1/B2. API 模块 → `web/src/api/blueprints.ts` / `repositoryChunks.ts`

**Analog:** `web/src/api/deliveryArtifacts.ts`（128 行，同域、只读）

```1:10:web/src/api/deliveryArtifacts.ts
/**
 * Delivery Artifact 版本轨 / 时间线 API（Chassis v2 · P7，只读）。
 *
 * 对接后端 `delivery/api/artifact_views.py`：列交付物 + 当前版本摘要、单交付物版本时间线、
 * 某版本的下游引用聚合（RepoCodingTask / SddSpec / ArchitectMerge）。
 *
 * 注意：与 `~/api/artifacts`（initiatives 项目工件）是不同领域对象，勿混用。
 */

import { get } from './client'
```

**结构要点：**

- 模块 docstring：「对接后端 `<后端文件路径>`」+ 易混淆对象的显式辨析（本相位必须写：**`~/api/deliveryArtifacts` 是通用 artifact 面，`~/api/blueprints` 只覆盖 `blueprint_status != ""` 的蓝图**）。
- `import { get } from './client'`（按需具名导入，不 import default）；写路径用 `post`（`client.ts:267`）。
- **每个响应体一个导出 `interface`**，字段名与后端**逐字同名**（snake_case 不转驼峰），每个非显然字段一行 `/** */`。
- 查询参数拼装：`const query: Record<string, string> = {}` + 逐个 `if (params.x) query.x = params.x`（`:95-102`）—— 空值不进 query。
- 每个函数 `export async function xxx(...): Promise<T>` + 顶部一行 JSDoc；文件末 `export default { ...全部函数 }`（`:123-127`）。

**沿用：** `blueprints.ts` 覆盖五个新端点 + 复用端点的转发（`getArtifactTimeline` 直接 re-export 或在页面层直接用 `deliveryArtifacts`，PLAN 选一条写死）；`repositoryChunks.ts` 覆盖 `chunk-at` 与 `charter`。

**必须 DIFFER：**

- ⚠️ **`chunk-at` 的失败判据不是状态码**：`!ok || (chunks?.length ?? 0) === 0` 一律走兜底（P-3，「无命中/被排除」是 **200 `{"chunks": []}`**）。该判据应封装进 `repositoryChunks.ts` 的返回类型（如返 `{ chunks, usable: boolean }`），⛔ 不让每个调用点各自判。
- ⚠️ `ApiError.detail` 在响应体无 `detail` 键时回落 `'请求失败'`（`client.ts:237,242`），**不是空串** —— UI-SPEC §3.6 / §10.1 的「空串」判据是错的，⛔ 不据它写断言。
- barrel 追加（追加点 #3）：`export { default as blueprintsApi } from './blueprints'` + `export * from './blueprints'`，形状抄 `api/index.ts:25-27`。

---

### B4. 11 态配置 → `web/src/config/blueprintStatus.ts`

**Analog:** `web/src/config/status.ts`（103 行）

```1:6:web/src/config/status.ts
export interface StatusConfig {
  label: string
  icon: string
  variant: 'success' | 'warning' | 'info' | 'destructive' | 'muted' | 'default' | 'secondary' | 'outline'
  animate?: boolean
}
```

```88:102:web/src/config/status.ts
export function getStatusConfig(
  type: 'execution' | 'runner' | 'codingTask' | 'index' | 'triggerLog' | 'graph' | 'codingSession',
  status: string,
): StatusConfig {
  ...
  return configMap[type][status] ?? { label: status, icon: 'lucide--help-circle', variant: 'muted' as const }
}
```

**沿用：** `Record<string, StatusConfig>` 常量 + `getBlueprintStatusConfig(status)` 带兜底返回；**icon 存裸名**（`lucide--pen-line`，与 status.ts 全域一致）；每组配置上方一段中文注释说明「与后端哪个枚举同步」。

**必须 DIFFER：**

- ⛔ **不改 `getStatusConfig` 的 `type` 联合**（CREATE-ONLY），只 `import type { StatusConfig } from '~/config/status'` 复用类型（UI-SPEC §0.2 判定 3）。
- `label` 走 `t('knowledge.blueprints.status.*')` 而非中文字面量（status.ts 是内联中文的老面，新页面走 i18n）—— ⇒ 配置里存 **i18n key** 或存 `labelKey` 字段，由组件 `t()`，PLAN 写死一种。
- 本模块同时导出 `EDITABLE_BLUEPRINT_STATUSES` / `isBlueprintEditable` / `PRODUCED_BY_PREFIXES`（UI-SPEC §7.9 / §9.1）。
- **`config/__tests__/status.spec.ts` 已有先例** ⇒ `config/__tests__/blueprintStatus.spec.ts` 照写：11 态各一断言 + 未知态兜底 + `isBlueprintEditable` 的白名单内外正反并列（含 `''`）。

**⭐ safelist 交割清单（追加点 #4，PLAN 直接抄这一行）：** `main.css:10-20` 现有 safelist 已含 `scan-eye` `shield-check` `help-circle` `user-check` `check-circle` `x-circle` `loader-2` `file-x` `file-text` `undo-2` `sparkles` `shield` `external-link` `file-code` `workflow` `link`。**本相位需新增**（全部为运行期拼接：状态徽标 / `change_type` / citation `source_type` / `produced_by_ref` 前缀）：

```
icon-[lucide--pen-line] icon-[lucide--hammer] icon-[lucide--check-check] icon-[lucide--archive]
icon-[lucide--file-plus] icon-[lucide--file-pen-line] icon-[lucide--file-cog]
icon-[lucide--book-open] icon-[lucide--scroll-text] icon-[lucide--list-checks]
icon-[lucide--user-pen] icon-[lucide--refresh-cw]
```

⚠️ **区分两种 icon 契约（抄错就出不来图标）**：`CompactEmptyState`（`:17` `:class="\`icon-[${icon}]\`"`）与 `StatusBadge`（`:38` 同款）收**裸名**；而 `AnchorNavLayout` 的 `NavSection.icon`（`:91` `:class="[section.icon, …]"`）收**完整类名** `icon-[lucide--target]`。UI-SPEC §6.1 的导航图标写全名、§13.9 的状态图标写裸名 —— **两者都对，不要统一**。

---

### B5/B6. 前端纯函数 → `utils/blueprintBlocks.ts` / `utils/blueprintAnnotations.ts`

**Analog（模块形状）:** `web/src/utils/variableRef.ts`（65 行）—— 契约型模块 docstring（「统一格式契约……禁止生成 X 形式」+ 列出全部调用点 + 「杜绝各处手写拼接」）+ 每个导出函数一段 JSDoc 带 `@example`。

**Analog（测试形状）:** `web/src/utils/__tests__/variableRef.test.ts`（仓内唯一 utils 单测）。

**沿用：** 本相位**唯一能被 vitest 廉价而彻底覆盖的部分**（RESEARCH §B.10）⇒ 区间切分、offset 计算、`blockText`、`iter_blocks` 走查、diff 分类、`produced_by_ref` 前缀映射、21 事件 → 段 key 映射全部纯函数化到 `utils/`，组件只做渲染。

**必须 DIFFER（三条硬约束，来自 RESEARCH）：**

1. ⭐ **`blockText(block)` 按 `text → code.source → rows` 的字段优先级实现，⛔ 不按 `block.type` 分派**（P-13）—— 坐标系不一致的后果是 offset 仍在合法范围内、不触发降级、`<mark>` 照渲，**只是圈错了字**，全相位最难逮的一类错。落一条「同一 fixture block 前后端取文本一致」断言（后端期望值手抄进 fixture）。
2. **前端 `iter_blocks` 的走查顺序与 `_item_key` 回退（缺标识 → 位置下标字符串化）逐段对齐** `blueprint_schema.py:919-1036` 的 13 处 `collect`（RESEARCH §B.4 已列全清单）；⛔ `must_haves` / `decision_log` / `deferred_ideas` / `execution_plan` 不在走查里。
3. **diff 判据要自己做 canonical 序列化（递归排序键）**：后端用 `json.dumps(sort_keys=True)`，前端 `JSON.stringify` **不保证键序** ⇒ 不做 canonical 会把「内容未变、键序不同」误判 `modified`（RESEARCH §B.4，UI-SPEC §9.2 只写了「规范化 JSON 不等」没说怎么规范化）。

---

### B7. 客户端态 → `stores/useBlueprintViewerStore.ts`

**Analog:** `web/src/stores/analyticsFilters.ts`（25 行，全仓最小 setup store）

```1:25:web/src/stores/analyticsFilters.ts
/**
 * Analytics 页面筛选状态 Pinia Store（ — ）
 *
 * 职责：持有 Analytics 页面的分组维度 grouping，供 KpiCards / TokenCostChart / Selector 共享。
 *
 * 设计：
 * - 简单 setup store（参考 providerCredential.ts 模板）
 * - 不持久化到 sessionStorage（切 tab 重置为默认 none，符合 "分组是查询语境而非用户偏好" 语义）
 * - 仅一个 ref + 一个 setter，无复杂缓存
 */
export const useAnalyticsFiltersStore = defineStore('analyticsFilters', () => {
  const grouping = ref<AnalyticsGrouping>('none')
  ...
})
```

**沿用：** docstring 三段式（职责 / 设计 / **是否持久化及其理由**）；`defineStore('<name>', () => {...})` setup 风格；只放 `sidebarCollapsed` / `showClosedAnnotations` / `kindFilters` 三项客户端偏好。

**必须 DIFFER：** analog 明确**不持久化**；本 store 的 `sidebarCollapsed` 按 UI-SPEC §5.2 要 `useLocalStorage`（`@vueuse/core`）持久化 ⇒ docstring 里把「为什么这三项要持久化而 analog 不」写清楚（它们是**用户偏好**，不是查询语境）。⛔ 服务端态（doc / threads / snapshot）一律不进 store，走 TanStack Query。

---

### B8. 唯一轮询消费点 → `composables/useBlueprintLive.ts`

**Analog:** `components/project/workbench/DocsSection.vue:73` / `components/repository/ReconcilePanel.vue:59`（仓内 10 处 `refetchInterval` **全部是函数式**）

```ts
// DocsSection.vue:73
refetchInterval: query => (query.state.data?.sync_status === 'syncing' ? 2000 : false),
```

**沿用：** 函数式 `refetchInterval`；`queryKey` 用 `computed(() => [...])` 包裹取响应式（`pages/knowledge/entities/[id].vue:48,54,63`）；`staleTime: 30_000` 是页面级默认。

**必须 DIFFER（P-9，PLAN 写死）：**

- ⛔ **不用 UI-SPEC §8.3 的 `computed(() => isLive ? 5_000 : false)` 传值写法**，改函数式 —— 函数式能读到 `query.state.data` 的最新 `current_status`，省掉「用上一轮状态决定这一轮」的一拍延迟。**更要命的是**：若被实现成非响应式普通值，生成中的蓝图**永远不刷新而页面看起来完全正常**（首屏有内容、无报错）—— 典型静默假通过。
- ⛔ **删掉 UI-SPEC §8.3 的 `useDocumentVisibility()` 那条** —— TanStack Query 内建 `refetchIntervalInBackground: false`（默认），仓内 10 处先例都没写。
- ⛔ **不用 `composables/usePolling.ts`** —— 那是 `useIntervalFn` 手动 start/stop 的另一套，与 TanStack Query 无关；CONTEXT 说的「对齐它的惯例」只指**间隔量级**。
- ⭐ 契约断言（UI-SPEC §20 第 6 条）：`refetchInterval` 字面量**只出现在本文件** ⇒ 源码扫描测试（前端零先例，见 No Analog #7）。

---

### C1. 查看器路由页 → `pages/knowledge/blueprints/[id].vue`

**Analog:** `web/src/pages/knowledge/entities/[id].vue`（166 行，全仓唯一「类型化 route + `useHead` + `AnchorNavLayout` + 多 query + `is404`」页面）

**结构要点：**

```20:24:web/src/pages/knowledge/entities/[id].vue
const route = useRoute('/knowledge/entities/[id]')
const queryClient = useQueryClient()
const { t } = useI18n()

const entityId = computed(() => String(route.params.id))
```

```87:93:web/src/pages/knowledge/entities/[id].vue
useHead({
  title: computed(() => entityQuery.data.value
    ? `${entityQuery.data.value.title} - ${t('knowledge.entity.pageTitle')} - Friday AI`
    : `${t('knowledge.entity.pageTitle')} - Friday AI`),
})

const is404 = computed(() => entityQuery.error.value instanceof ApiError && entityQuery.error.value.status === 404)
```

- **`sections` 是 `computed<NavSection[]>`**（`:76-85`），label 走 `t()`。
- **段容器形状**（`:117-132`）：`<section :id class="space-y-4">` 内三分支 `Skeleton` → 实渲组件 → `CompactEmptyState`。
- **`is404` 时整页替换**（`:103-109`），`v-else` 包住全部正常内容。
- **query ↔ ref 双向同步 + `normalize*` 兜底**抄同目录的 `pages/knowledge/index.vue:43-60`：

```43:60:web/src/pages/knowledge/index.vue
function normalizeTab(value: unknown): KnowledgeTab {
  return TABS.includes(value as KnowledgeTab) ? (value as KnowledgeTab) : 'overview'
}
const activeTab = ref<KnowledgeTab>(normalizeTab(route.query.tab))
watch(() => route.query.tab, (v) => { ... })
watch(activeTab, (v) => {
  if (route.query.tab !== v)
    router.replace({ query: { ...route.query, tab: v } })
})
```

  ⭐ `router.replace({ query: { ...route.query, X: v } })` 的展开写法**保留其它 query** ⇒ UI-SPEC §4.1 的六个 query（`version`/`diff`/`diff_mode`/`section`/`thread`/`panel`）天然共存，无需额外机制。

**必须 DIFFER（四条，全部来自 RESEARCH 对该 analog 的实读缺陷）：**

1. ⭐ **十段 `<section :id>` 容器无条件渲染**（骨架/空态在容器内），⛔ 不写 `v-if="doc"` —— analog 的 `:149-153` 第 4 段正是踩了这个坑（`v-if="showAssociations"` ⇒ 永不被 `AnchorNavLayout` 的 mount-only observer 观察）。P-4，也与 UI-SPEC §8.1「按段骨架、增量填充」天然一致。若 `sections` 长度仍会变（`must_haves`/`decision_log` 可缺），补一个 `watch(() => sections.value.map(s => s.id).join(), ...)` 的重挂逻辑，或干脆十段全部无条件渲染。
2. ⛔ **`CompactEmptyState` 传裸图标名**（`icon="lucide--lock"`），analog 的 `:105` 传的是 `icon="icon-[lucide--file-x]"` —— **渲染成 `icon-[icon-[lucide--file-x]]`，图标出不来**（P-6，同目录 `index.vue:309,317` 也是错的那一派）。
3. ⛔ **`CompactEmptyState` 没有 `action-label` prop 也没有 `@action` emit**，analog 的 `:107-108` 是死写法 —— 「返回知识库」按钮必须放**默认 slot**（`CompactEmptyState.vue:28-30`）。
4. **`AnchorNavLayout` 由页面直接使用**（`:116` 的位置），第三栏在其默认 slot 内再开一层 `flex gap-6`（UI-SPEC §5.1）；⛔ 不把它嵌进 `BlueprintSectionNav`（`scrollTo:46-53` 是私有函数、零 emit、零 expose）。
5. **`AnchorNavLayout` 的 badge 传 `''` 而不是 `0`**（`:95` 的空值判定不排除 `0`，会渲染出一个灰 `0`，P-18）。

---

### C3. 状态徽标 → `components/blueprint/BlueprintStatusBadge.vue`

**Analog:** `web/src/components/common/StatusBadge.vue`（43 行）+ `components/spec/SddSpecStatusBadge.vue`（36 行）

```34:42:web/src/components/common/StatusBadge.vue
  <Badge :variant="config.variant" :class="sizeClass">
    <span
      v-if="showIcon"
      :class="[`icon-[${config.icon}]`, iconSizeClass, config.animate ? 'animate-spin' : '']"
    />
    <span v-if="showLabel">{{ config.label }}</span>
  </Badge>
```

**沿用：** `withDefaults(defineProps<{...}>(), {...})`（`:7-17`）；三档 `sizeClass` / `iconSizeClass` 映射对象（`:21-31`）；`config.animate → animate-spin`；`Badge :variant` 承载全部颜色，⛔ **禁止在 Badge 上用 `:class` 追加颜色类**（UI-SPEC §15）。从 `SddSpecStatusBadge` 抄两件：`data-testid="..."`（`:28`）与 `t(\`specs.status.${props.status}\`)`（`:22`）的 i18n label 取法。

**必须 DIFFER：** 配置源是 `~/config/blueprintStatus`（B4），不是 `getStatusConfig`；label 走 i18n（analog 的 label 是配置里的中文字面量）；`''`（v0 旧数据）也是合法输入，兜底分支必须命中它而不是走 unknown 分支。

---

### D. 内容渲染 —— 段组件与块渲染

**Analog（段容器）:** `pages/knowledge/entities/[id].vue:117-162` 的三分支段（见 C1）。
**Analog（块内 mustache + `<pre>`）:** `PromptVersionDiff.vue:90-97`（`v-for` + `:class` + `<pre class="font-mono text-xs leading-6 whitespace-pre-wrap px-3 py-1">{{ seg.text }}</pre>`）。
**Analog（卡片骨架）:** `IndexProgressTimeline.vue:31-41`（`.card` → `px-5 py-3.5 border-b` 头 → `p-5` 体）+ `:43-46` 的行内空态。

**沿用：**

- 段组件签名统一 `props: { <段数据>, ...blockCtx }`，`blockCtx = { threads, citations, readonly, activeThreadId }` 原样透传给 `BlueprintBlockList`，⛔ **段组件内不自行处理批注**（UI-SPEC §13.3）。
- 每个段一个 `data-testid="blueprint-<段>"`，块根 `data-testid="blueprint-block"`（`data-*` 属性用于测试查询的先例：`PromptVersionDiff.vue:85` 的 `data-diff-column` + 其测试 `:68` `wrapper.findAll('[data-diff-column]')`）。
- 表格一律 `~/components/ui/table` 语义 `<table>`/`<th scope="col">`。

**必须 DIFFER：**

- `MustHavesSection.vue` **不收 `blockCtx`、不复用 `BlueprintBlockList`**（`must_haves` 无 `block_id`，UI-SPEC §6.9），组件内注释写明原因。
- ⭐ **`DecisionLogSection.vue` 同样不接批注层**（P-14：`decision_log` / `deferred_ideas` 也不在 `iter_blocks` 里，且是**零 items 约束的裸 array**）—— UI-SPEC §13.3 给它派的 `emits: ['open-thread']` 必须澄清语义（若是「跳到该决策对应的线程」则保留，否则是死码）。三段的字段访问逐项 `.get`/可选链，缺键渲染「—」而非 `undefined`；特别保 `answer` 键（唯一有下游消费方）。
- `InteractionFlowsSection` 传 mermaid 用 **`:code="flow.mermaid"`**，prop 名是 `code` 不是 `source`（P-12）；空源码由**调用方 `v-if`**（组件自己不管，会渲一个空 `<pre>`）。

---

### E. 批注层与线程

**Analog（受控 Dialog + 必填输入）:** `components/accessTokens/AccessTokenRevealDialog.vue`（`defineEmits<{}>` + `update:open`）。
**Analog（分组收件箱）:** `components/delivery/HumanTaskInbox.vue`（`hide-when-empty` prop + 分组）。
**Analog（emits 类型风格，仓内 20+ 处一致）:**

```ts
const emit = defineEmits<{
  (e: 'navigate', tab: KnowledgeTab): void
}>()
```
（`components/knowledge/KnowledgeDashboard.vue:41-43`；另有 `defineEmits<{ done: [], skip: [] }>()` 的元组简写，`components/setup/SetupFeishuStep.vue:18`。**两种都在用，PLAN 选一种在 `components/blueprint/**` 内统一**。）

**沿用：** `annotationTokens.ts` 的形状抄 `components/knowledge/artifactDisplay.ts` 的 `ARTIFACT_BADGE_CLASS`（模块级 `Record` 常量 + 一个查表函数），⭐ **组件内不得再写颜色字面量**（UI-SPEC §15）。

**必须 DIFFER（三条，都是本相位最容易做错的）：**

1. ⭐ **`kind` 硬分流做在渲染层**（UI-SPEC §7.8 / 114-CR-01）：`ai_review_finding` 的线程卡**根本不渲染** `BlueprintThreadComposer`。后端 `blueprint_review_views.py:653-657` 对 finding 走 answer 一律 400 —— UI 给统一输入框再按 kind 切端点必然稳定撞 400。
2. ⭐ **`readonly` 是「不存在于 DOM」不是 `disabled`**（UI-SPEC §7.9）：composer 与选区 popover 的「发起评论」按钮 `v-if` 掉；**但 finding 处置按钮不受该闸约束**（那是死锁出口，后端未加状态闸）。与之相对，**终审按钮是 `disabled` + tooltip**（UI-SPEC §11.1）—— 两种处理刻意不同，不要统一。
3. ⭐ **三态别合并**（P-7）：`anchored + 越界`（前端概念，整块色条，仍在 status 三组）≠ `orphaned`（后端 `areanchor_threads` 判定，正文完全不渲染，第四组）≠ `anchor === null` 的系统线程（`anchor_status` 仍是 `anchored`，侧栏按 status 分组、正文无标记）。侧栏前三组的 `&& anchor_status !== 'orphaned'` 不可省；`orphaned_threads` 直接渲染**不再前端过滤**。

---

### F2. block 级 diff → `BlueprintBlockDiff.vue`

**Analog:** `web/src/components/prompts/PromptVersionDiff.vue`（137 行，逐字级 analog）

```1:20:web/src/components/prompts/PromptVersionDiff.vue
/**
 * PromptVersionDiff.vue — side-by-side 版本对比视图
 * ...
 * 安全：diffLines 返回纯字符串，本组件完全走 Vue mustache `{{ seg.text }}`
 * 经 <pre> 渲染，未使用 v-html，确保 XSS 面 = 0（Threat T-215-01 mitigate）。
 *
 * 性能：使用 shallowRef<Change[]> 避免对 diffLines 输出做深响应式；
 */
import type { Change } from 'diff'
import { diffLines } from 'diff'
import { shallowRef } from 'vue'
```

```119:131:web/src/components/prompts/PromptVersionDiff.vue
.diff-added {
  background: hsl(142 71% 45% / 0.12);
  color: hsl(142 71% 20%);
  border-left: 3px solid hsl(142 71% 45%);
}
.diff-removed {
  background: hsl(0 72% 51% / 0.1);
  color: hsl(0 72% 30%);
  border-left: 3px solid hsl(0 72% 51%);
}
```

**沿用：** 模块 docstring 的「安全 / 性能」两段（本相位逐字适用）；`shallowRef<Change[]>`；`aria-live="polite"` 摘要行（`:74-81`）；`data-diff-column` 式的测试锚点；左右栏 `filter(c => !c.added)` / `filter(c => !c.removed)` 的视角切分。

**必须 DIFFER：**

- ⚠️ **`.diff-*` 是 `<style scoped>`（`:119-137`），无法跨组件复用** ⇒ UI-SPEC §9.2「逐字沿用」的实现是**把这三条 CSS 原样复制进新组件的 scoped style**，不存在可 import 的共享令牌文件（P-11）。⛔ 别让执行者去找。
- ⛔ **不照抄 `watch(..., { deep: true })`**（`:30-36`）—— 那是既有的一处自相矛盾（deep watch 配 shallowRef）。新组件监听 `versionId` 这类标量即可。
- 默认形态是**单栏 inline**（analog 是固定双栏），`?diff_mode=split` 才切双栏。
- 用 `diffWords` 而非 `diffLines`（同包同族 API，`[ASSUMED]` 返回同构 `Change[]`，A3）；块级增删走 `block_id` 集合运算，只有 `modified` 的块才进 `diffWords`。
- diff 模式下批注层与所有写动作**关闭**。

---

### G1. 引用预览 → `CitationPreviewDialog.vue`

**Analog:** `web/src/pages/knowledge/index.vue`（工件查看弹窗）

```165:191:web/src/pages/knowledge/index.vue
const viewOpen = ref(false)
const viewLoading = ref(false)
const viewData = ref<ArtifactView | null>(null)
const viewTitle = ref('')
...
async function openArtifactView(item: KnowledgeSearchResultItem) {
  ...
  try {
    viewData.value = await artifactsApi.view(...)
  }
  catch (e: unknown) {
    handleError(e, t('projects.artifacts.viewFailed'))
    viewOpen.value = false
  }
  finally {
    viewLoading.value = false
  }
}
```

**沿用：** `Dialog` + `DialogScrollContent` + `DialogHeader` + `DialogTitle`（`:23-29` 的 import 组，`DialogTitle` 必填否则 reka-ui 报 a11y 警告）；open/loading/data/title 四 ref 的受控形态（提到 `composables/useCitationPreview.ts` 里）。

**必须 DIFFER（⭐ 与 analog 的 catch 分支完全相反）：**

- analog 失败时 **`viewOpen.value = false` 把弹窗关掉 + toast**；本相位 UI-SPEC §10.1 明令**兜底不留白** —— 任何失败一律渲染 citation 自带的 `title` / `quote` 快照 + 一行「原始来源不可达，以下为引用时的快照」，⛔ **不关弹窗、不回显后端错误体**。
- **`chunk-at` 的兜底判据是 `!ok || chunks.length === 0`**（P-3），⛔ 不是「非 2xx」；`locator.line_start` 缺失时**直接不发请求**立刻走兜底。
- ⭐ **预览弹层内不渲染 mermaid 块**（P-12 次生）：`MermaidDiagram` 的放大层是 `vue-final-modal`（`:4,80`，`main.ts:6,17` 全局注册），与 reka-ui `Dialog` 是两套模态栈 ⇒ 在 Dialog 内点放大会叠放竞争。被引块恰是 mermaid 时退化为源码 `<pre>`。
- 预览内的 citation chip **不开第二层弹层**，改「打开完整蓝图」`RouterLink`（UI-SPEC §18.2）。

---

### G7. 筛选栏 → `components/common/FilterBar.vue`

**Analog:** 无实现（契约在 `web/DESIGN.md:198-211`）。**最近的结构模板**是 `components/knowledge/KnowledgeDashboard.vue` 的筛选区 + `pages/knowledge/index.vue:112-135` 的「输入值 / 已提交值分离」：

```111:135:web/src/pages/knowledge/index.vue
// 输入框当前值与「已提交」查询词分离：仅点击搜索 / 回车时提交，避免输入即触发请求。
const queryInput = ref('')
const submittedQuery = ref('')
...
function onSearch() {
  submittedQuery.value = queryInput.value.trim()
  ...
}
```

**沿用：** `props: { showClear?: boolean }` + `emits: ['clear']` + 默认 slot 承载控件（DESIGN 契约逐字）；容器 `.card` + `p-4` + `flex flex-wrap items-center gap-3`，清除按钮 `variant="ghost" size="sm"` 靠右；分页抄 `KnowledgeDashboard.vue:801-808` 的 `<Pagination :page :total :items-per-page :sibling-count="1" show-edges @update:page>`。

**必须 DIFFER：** 它是**通用件放 `common/`**，⛔ 不得引入任何蓝图专属 prop —— 否则下一个页面复用不了，DESIGN 里那份契约白写。

---

### G10. 项目物料卡 → `ProjectBlueprintsCard.vue`

**Analog:** `components/project/warroom/ProjectMaterialsPanel.vue:52` 的 `HumanTaskInbox` 用法 + `:57-66` 的 `.flat-section` / `.flat-header` 分区头。

```57:66:web/src/components/project/warroom/ProjectMaterialsPanel.vue
      <section class="flat-section">
        <header class="flat-header">
          <span class="section-chip"><span class="icon-[lucide--list-checks]" /></span>
          <h3>{{ t('projects.tabs.workItems') }}</h3>
        </header>
        <div class="p-5">
```

**沿用：** 「无数据整块不渲染」是一个 **`hide-when-empty` prop 由面板传入**（`:52`），⛔ 不是组件自决 —— UI-SPEC §12.2 的措辞容易被读成后者。

**必须 DIFFER：** ⚠️ 该面板 `:75` **已经渲染了** `<ArtifactTimeline :space-id artifact-type="technical_plan" />`，而蓝图与旧 technical_plan **共用同一 `artifact_type`** ⇒ 新卡会与它条目重叠（P-17）。新卡按 `blueprint_status != ""` 过滤即可分开，但**文案必须把两者区分清楚**，且建议排在 `ArtifactTimeline` **之前**（蓝图是更新的形态）。

---

### H. 前端测试

**Analog A（页面级）:** `web/src/pages/knowledge/__tests__/entity-detail.spec.ts`（70 行，仓内唯一页面测试范式）

```53:69:web/src/pages/knowledge/__tests__/entity-detail.spec.ts
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = mount(EntityDetailPage, {
      global: {
        plugins: [i18n, [VueQueryPlugin, { queryClient }]],
        stubs: {
          AnchorNavLayout: { template: '<div><slot /></div>' },
          PageContainer: { template: '<div><slot /></div>' },
          CompactEmptyState: true,
          EntityDetailToolbar: true,
        },
      },
    })
    await new Promise(r => setTimeout(r, 50))
    expect(wrapper.html()).toContain('测试实体')
```

- `vi.mock('vue-router', ...)`（`:7-9`）+ `vi.mock('~/api', ...)`（`:11-26`）；i18n 消息**手写最小键树**（`:28-51`），⛔ 不 import `zh-CN.json`。
- 等 query resolve 用 `await new Promise(r => setTimeout(r, 50))`。

**Analog B（组件级，最规范）:** `components/prompts/__tests__/PromptVersionDiff.test.ts`（113 行）—— 顶部「覆盖路径」编号清单；`makeVersion(overrides)` 工厂；**正/负向成对断言**（`expect(leftHtml).not.toContain('diff-added')`）；`wrapper.findAll('[data-diff-column]')` 按 `data-*` 定位；`setProps` 验 watch；**真实 import `diff` 不 mock**。

**沿用（本相位测试预算分配，RESEARCH §B.10 的结论）：**

| 层 | 文件 | 守护点 |
|---|---|---|
| 纯函数（高价值） | `utils/__tests__/blueprintAnnotations.test.ts` / `blueprintBlocks.test.ts` / `config/__tests__/blueprintStatus.spec.ts` | 区间切分六类边界（越界/反序/重叠/非整数/空/全覆盖）；⭐ **`blockText` 四分支优先级与后端 fixture 逐字一致**（P-13）；`iter_blocks` 走查顺序 + `_item_key` 回退；canonical 序列化键序无关；21 事件 → 段 key 映射穷举；`produced_by_ref` 五档映射；`isBlueprintEditable` 白名单内外 |
| 组件（中价值） | `components/blueprint/__tests__/*.spec.ts` | UI-SPEC §20 的断言 1/2/3/5/8/9/11 —— 全是「某 `data-testid` 存在/不存在 + 条目计数」，happy-dom 够用 |
| 源码扫描（低成本防回归） | 新建一个 `src/__tests__/blueprint-source-guard.spec.ts` | UI-SPEC §20 的断言 4/6/10（404 文案单键 / `refetchInterval` 单文件 / `edit-block` 零命中）。**后端有大量此形态先例可抄**（`test_blueprint_inv6_guard.py`），前端零先例（No Analog #7） |
| UAT（不自动化） | — | 滚动定位、mermaid 实渲、三栏断点、焦点管理、颜色对比度 |

**必须 DIFFER / 注意：**

- **stub 清单必加 `MermaidDiagram: true`** —— 否则要连带 `vue-final-modal` 插件（P-12）。
- `AnchorNavLayout` 被 stub ⇒ 十段导航的 badge/tone 逻辑**必须在 computed 层可单测**（把 `sections` 计算提成纯函数或 composable）。
- happy-dom `^20.10.2`（`pnpm-workspace.yaml:92`）**无真实布局** ⇒ `Range.getBoundingClientRect()` / `IntersectionObserver` / `window.scrollTo` 行为不可信；`document.createTreeWalker` / `Range` 的 API 存在性**必须在 Wave 0 用一条探针测试确认**（A2 假设未解除）。
- ⭐ **UI-SPEC §20 断言 4「i18n 只有 `error.notFoundOrForbidden` 一个键被用于 404 分支」在组件测试里不好断**（i18n 消息是手写的）—— **改成源码扫描**更可靠。

---

## Shared Patterns（跨文件通用）

### S1. 观测五件套（后端新增面强制）
**Source:** `blueprint_review_views._log`（`:284-294`）、`blueprint_review_action`（`:237-246` / `:586-596`）、`artifact_overview`（`:202-209`/`:240-248`）
事件名 snake_case（`xxx_started/completed/failed`）+ `category="caller"`（本相位五端点全是用户可归因调用）+ `component=<新常量>` + `artifact_id` + `initiated_by_user_id=... or "system"` + `duration_ms=round((time.monotonic()-started)*1000, 2)`。
⚠️ **只读 GET 也记 caller 事件**（`blueprint_review_snapshot_read` `:407` 是先例）。
⛔ **正文一律不进日志**（T-114-36）：`POST threads/` 的 `body`、列表端点的 `?q=` 只记**长度**。

### S2. 脱敏不可绕过
**Source:** `blueprint_review_action._detail`（`:136-138`）、`test_blueprint_log_redaction_guard.py:41`
任何 `error=` 实参必须经 `redact_secrets_in_text` / `redact_credentials` / `_detail` / `redact_for_ledger` 之一（AST 守卫强制）。**新模块加进 `_SCANNED_MODULES`**。

### S3. best-effort 不反噬业务
**Source:** `artifact_overview.py:229-238`、`blueprint_review_action._aadd_reviewer`（`:165-181`）、`_aopen_reject_comment`（`:453-462`）
聚合/名单 upsert/评论开线程/续驱一律 `except Exception` 吞 + `logger.warning` + 返回降级值。**唯一例外**：范围闸是 fail-closed 拒绝（安全边界不降级）。

### S4. async ORM 防裸 lazy-FK
**Source:** `blueprint_review_views` 全域、`artifact_views.py:95-97`
用 `.values_list()` / `.aexists()` / `.afirst()` / async 迭代；必须取 FK 对象时 `select_related` 预取或走 `@sync_to_async` 私有函数；serializer `.data` 一律 `sync_to_async` 包裹（本相位若不用 serializer 则不涉及）。

### S5. 前端 XSS 面 = 0
**Source:** `PromptVersionDiff.vue:10-11` 的自述纪律
蓝图正文、线程消息、citation `quote`/`title`、JSON 示例、diff 段**一律 mustache + `<pre>`**，⛔ 禁 `v-html`。唯一 `v-html` 是 `MermaidDiagram.vue:71` 的既有 SVG 注入（`securityLevel:'strict'`，既有面不改）。

### S6. TanStack Query 三惯例
**Source:** `pages/knowledge/entities/[id].vue:47-66`、`:40,44`
`queryKey: computed(() => [...])` 取响应式；`staleTime: 30_000` 页面级默认；invalidate 走**前缀匹配** `invalidateQueries({ queryKey: ['blueprint'] })`（UI-SPEC §3.7 的 `predicate` 写法仓内零先例，本页只有一个 artifact ⇒ 全域失效无副作用，取简单写法）。

### S7. 前端错误分档基础
**Source:** `pages/knowledge/entities/[id].vue:93`（仓内唯一 `is404` 先例）+ `api/client.ts:236-247`
`err instanceof ApiError && err.status === 404`；`ApiError` 三字段 `status` / `detail`（**缺省 `'请求失败'`**）/ `body`（完整 JSON，409 的 `unresolved_blocker_thread_ids` 从这里取）。

### S8. 受限/追加面的纯追加纪律
**Source:** 114-PATTERNS §受限面 + STATE §13.2
六个追加点验收：`git diff <file> | rg "^-[^-]"` **必须为空**；受限文件只跑 `ruff check` / `eslint --fix` 的**格式化不得扩散到既有行**（前端注意 `@antfu/eslint-config` 的自动重排会误伤 `api/index.ts` 的既有导出顺序 —— 追加时保持既有分组不动，新组追加在末尾）。

---

## No Analog Found

| # | 内容 | 说明与最近的结构模板 |
|---|---|---|
| 1 | **字符区间 `<mark>` 切分 + `Range`/`TreeWalker` 取 offset** | `rg "window.getSelection\|selectionchange\|createTreeWalker" web/src` **零命中**（唯一 `setSelectionRange` 是 textarea 光标复位，无关）。**完全从零写。** 结构模板：`utils/variableRef.ts` 的纯函数模块形态 —— 签名做成 `sliceBlockText(text: string, anchors: Array<{threadId,start,end}>): Array<{text, threadIds}>`，让 vitest 不挂载组件就能覆盖全部边界。**实现者必须自己发明的**：重叠区间「不合并、切成不相交子段、每段携带 threadId 集合」的切点算法（UI-SPEC §7.1 第 3 步）与优先级着色（§7.5）。PLAN 应给这一项**独立的 task 与验收断言**，不要塞进 `BlueprintBlock.vue` 的实现任务里 |
| 2 | **`@floating-ui/vue` 的选区 popover** | 依赖已声明（`package.json:34` → `pnpm-workspace.yaml:24` `^1.1.11`）但 `rg "@floating-ui/vue\|useFloating" web/src` **零命中**，且本 worktree 无 `node_modules` ⇒ API 形状 `[ASSUMED]`（A1）。**PLAN 必须二选一写死**：(a) `useFloating` + 虚拟参考元素（`Range.getBoundingClientRect()`）；(b) 复用 `~/components/ui/popover` 的 `PopoverAnchor` 承接虚拟锚点。⛔ 不让执行者临场选。**Wave 0 先跑一次 `pnpm install && pnpm test:unit`** |
| 3 | **只读 CodeMirror 代码预览 + 代码正文来源** | 仓内**没有**只读 CodeMirror 封装：`components/execution/JsonViewer.vue:4-7` 的注释自承「**替代 CodeMirror 的只读 JSON 展示**」，`PromptBodyEditor` / `MarkdownSourceEditor` / `JsonEditor` 全是可编辑实例。UI-SPEC §3.6「复用既有 CodeMirror 只读封装」**指向一个不存在的东西**。更硬的问题：`chunk-at` 的 `chunks[]` 只有 `{chunk_id, file_path, line_start, line_end, chunk_index}`，**没有代码正文**（P-3 次生）。**PLAN 必须先定夺**：找到取源码的读面，或把该来源类型降级为「路径 + 行号区间 + `quote` 快照」（与 `pseudocode` 块同一套 `<pre>` + 行号渲染，省一个依赖面）并在 UI-SPEC §10.1 上登记订正 |
| 4 | **`components/common/FilterBar.vue`** | 契约写在 `web/DESIGN.md:198-211`，`rg FilterBar web/src` **零命中**。属 CREATE-ONLY 新建、非改造。最近模板见 §G7 |
| 5 | **`associations` 段的反向关联** | `knowledgeApi.getRelated` / `getArtifactAssociations` 查的是 **`initiatives.Artifact`** 投影的 KnowledgeEntity（`knowledge/artifact_associations.py:75`），而蓝图在 **`delivery.Artifact`** ⇒ 拿蓝图 id 去调**必然 404/空**（P-5）。知识图谱物化明确是 **Phase 116**。**本相位只能兑现两块**：「本蓝图引用了」（`content.citations` 纯前端聚合，零端点）+「关联项目」（`meta.project_id` + `RouterLink`）。**SC-4 的范围收窄必须显式登记进 PLAN 与 STATE**，⛔ 不靠 404 兜底糊过去 |
| 6 | **前端 canonical JSON 序列化** | 后端 `_block_fingerprint = json.dumps(block, sort_keys=True, ensure_ascii=False)`（`blueprint_schema.py:1039-1040`）；前端 `JSON.stringify` 不保证键序，仓内无递归排序序列化的先例。需在 `utils/blueprintBlocks.ts` 内自写并单测（同一对象不同键序 → 同一指纹） |
| 7 | **前端源码扫描断言** | 后端有成熟先例（`test_blueprint_inv6_guard.py` 的正则扫描 + `test_blueprint_log_redaction_guard.py` 的 AST 遍历 + `test_blueprint_review_views.py:69-70` 的 `Path(__file__).resolve().parents[2]` 定位），**前端 vitest 侧零先例**。UI-SPEC §20 的断言 4/6/10 依赖它 ⇒ 需新建一个用 `node:fs` + `import.meta.dirname` 遍历 `src/components/blueprint/**` 的 spec，形态可从后端那两个文件平移 |

---

## 后端与 UI-SPEC 的三处口径分歧（PLAN 必须逐条定夺）

| # | UI-SPEC 写的 | 实测/守卫要求的 | 建议 |
|---|---|---|---|
| 1 | §3.3 `BlueprintListItem.blueprint_status` + 「DRF 分页体」 | INV-6 守卫判 `{"blueprint_status": …}` 为旁路写（P-1）；方案 A 的 Python 侧过滤用不了 `paginate_queryset` | 键改 **`current_status`**；分页取 `artifact_overview` 五键 `{total, items, page, page_size, has_next}`。**同步订正 UI-SPEC §3.3 与前端 TS 接口** |
| 2 | §10.1「任何非 2xx 走兜底」 | `chunk-at` 的「无命中/被排除」是 **200 `{"chunks": []}`**（P-3），是最常见的一档 | 判据改 `!ok \|\| chunks.length === 0` |
| 3 | §8.3 `refetchInterval: computed(...)` + `useDocumentVisibility` | 仓内 10 处全是函数式；`refetchIntervalInBackground` 默认已 false（P-9） | 改函数式；删可见性判断 |

（另有两处 RESEARCH 已订正的行号/文案偏差：`blueprint_quality.py` 分母为 0 的返回在 `:77` 不是 `:76`；`ApiError.detail` 缺省是 `'请求失败'` 不是空串 —— 后者别据以写断言。）

---

## Metadata

**Analog search scope:**
- 后端：`server/delivery/{api,services}/`、`server/knowledge/api/`、`server/tests/delivery/`
- 前端：`web/src/{api,pages,components,composables,stores,utils,config,types,styles}/`，重点 `pages/knowledge/**`、`components/{common,knowledge,prompts,layout,project/warroom,repository,spec}/`

**Files scanned:** 约 45 个候选路径；**精读 21 个 analog**（`blueprint_review_views.py` 与 `client.ts` 为**非重叠**定向切片）：
`blueprint_review_views.py` / `blueprint_review_action.py` / `artifact_views.py` / `artifact_overview.py` / `delivery/urls.py` / `test_blueprint_review_views.py` / `test_blueprint_log_redaction_guard.py` /
`deliveryArtifacts.ts` / `api/index.ts` / `api/client.ts` / `config/status.ts` / `stores/analyticsFilters.ts` / `composables/useConfirmDialog.ts` / `utils/variableRef.ts` /
`pages/knowledge/entities/[id].vue` / `pages/knowledge/index.vue` / `PromptVersionDiff.vue` / `StatusBadge.vue` / `SddSpecStatusBadge.vue` / `CompactEmptyState.vue` / `AnchorNavLayout.vue` / `IndexProgressTimeline.vue` / `ProjectMaterialsPanel.vue` /
测试：`entity-detail.spec.ts` / `PromptVersionDiff.test.ts`

**上游输入：** `115-UI-SPEC.md`（§13 组件清单为权威）、`115-RESEARCH.md`（P-1…P-18 与可复用件速查表已实读核对）、`115-CONTEXT.md`、`.planning/STATE.md` §13.2、`114-PATTERNS.md`（house style）

**Pattern extraction date:** 2026-07-31
**Valid until:** 111–114 后端模块或 `web/src` 既有件在 rebase 中改动即需重核行号
