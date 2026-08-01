---
phase: 115
slug: ui
kind: research
researched: 2026-07-31
domain: "Vue 3 前端查看器（批注层 / 版本 diff / 引用预览 / 知识库管理面）+ delivery 侧五个只读/轻写 REST 端点"
confidence: HIGH
evidence: "全部结论来自本 worktree（.claude/worktrees/v0.20-blueprint，分支 milestone/v0.20.0-blueprint）源码逐行核对，附 file:line；零外部依赖查询、零新增运行时依赖"
upstream:
  - .planning/phases/115-ui/115-CONTEXT.md
  - .planning/phases/115-ui/115-UI-SPEC.md
  - .planning/phases/114-ai/114-05-SUMMARY.md
  - .planning/phases/114-ai/114-REVIEW.md
  - .planning/STATE.md
  - .planning/technical-blueprint/DESIGN.md
requirements: [VIEW-01, VIEW-02, VIEW-03, VIEW-04, CLAR-01, FLOW-08]
scope: "只覆盖『后端五端点怎么建』+『前端七类机制怎么做』+ Pitfalls。不覆盖组件切分、Tailwind 令牌、i18n key 层级（UI-SPEC 已定稿或属 Discretion）"
---

# Phase 115: 前端查看器与知识库 - Research

**Researched:** 2026-07-31
**Domain:** `web/src` 全绿地蓝图前端 + `server/delivery/api` 五个新端点
**Confidence:** HIGH（判据全部实读；唯一 MEDIUM 项是 `@floating-ui/vue` 的 API 形状——它在依赖清单里但**全仓零调用点**，见 §B.2）

## Summary

UI-SPEC 关于**五个新端点必要性**的五条主张，本次逐条核验：**五条全部成立**，且核到两处 UI-SPEC 自身的口径偏差与三处它没写的**硬守卫**。前端侧的判断也基本成立，但 UI-SPEC 依赖的三个「既有可复用件」实测有坑：`AnchorNavLayout` 的 IntersectionObserver **只在 mount 那一刻注册**（异步数据到达后新出现的段永不被观察）、`CompactEmptyState` 的 `icon` prop 在仓内被**两种互斥写法**混用（半数调用点实际渲染不出图标）、`knowledgeApi.getArtifactAssociations` 查的是 **`initiatives.Artifact`** 而不是蓝图所在的 `delivery.Artifact`（对蓝图 id **必然 404**）。

本相位真正的技术风险不在选型（零新增依赖），而集中在三处**会静默假通过**的形状：

1. **后端源码扫描守卫**：`server/tests/delivery/test_blueprint_inv6_guard.py:57,61` 的两条正则会把 `filter(blueprint_status=…)` 与 `{"blueprint_status": …}` **一律判为 INV-6 旁路写** —— 而 UI-SPEC §3.3 的列表端点契约同时需要这两者（状态筛选 + 响应键）。不先知道这条，列表端点写完必然让一条既有绿测转红，且报错信息指向「旁路写状态字段」这个完全无关的方向。
2. **`chunk-at` 的失败不是非 2xx**：`repositories/chunk_at_views.py:60` 对「无命中」与「被排除文件」统一返回 **200 `{"chunks": []}`**（刻意不泄露存在性）。UI-SPEC §10.1 把兜底判据定为「任何非 2xx」，正好**漏掉最常见的那一档** —— 代码预览会渲染一个空壳而不是快照兜底。
3. **`AnchorNavLayout` 的观察时机**：`components/layout/AnchorNavLayout.vue:35-39` 在 `onMounted` 里按 `props.sections` 逐个 `getElementById`。十段正文若是 `v-if="doc"` 才渲染，mount 时全部取不到 → 观察者一个也没挂上 → 左栏高亮永远停在第一段，而点击跳转照常工作（`scrollTo` 是点击时才查 DOM），**看起来像"只是高亮有点迟钝"**。既有的 `pages/knowledge/entities/[id].vue` 已经踩了这个坑的弱化版（第 4 个条件段永不被观察）。

**Primary recommendation:** 后端新建**两个**文件而不是一个 —— `delivery/api/blueprint_doc_views.py`（正文 / 事件 / 线程 GET+POST 四端点，挂在 `artifacts/<uuid>/` 前缀下）与 `delivery/api/blueprint_list_views.py`（`/delivery/blueprints/` 列表，它的项目可见性口径与前四者不同，见 §A.5）；两者复用 `blueprint_review_views._aassert_project_scope` 的**同源实现**（提取到共享 helper 或直接 import，不要复制第三份）。前端把批注区间切分（§B.1）、选区取 offset（§B.2）、前端版 `iter_blocks`（§B.4）三块**纯函数化到 `web/src/utils/`**，它们是本相位唯一能被 vitest 廉价而彻底覆盖的部分 —— 组件层测试受限于 happy-dom（无布局、无 IntersectionObserver 真实行为、mermaid 必然回退），只能做「渲染/不渲染」级断言。

---

## User Constraints (from CONTEXT.md)

### Locked Decisions

**信息架构与查看器骨架**

- 入口形态取「独立路由页」为唯一权威渲染面：新增 `web/src/pages/knowledge/blueprints/[id].vue`（`/knowledge/blueprints/:artifactId`），所有入口一律 `RouterLink` 深链跳过来，**不做「全屏 Dialog 形态」的第二套实现**。
- 三栏布局：左「六段目录导航」+ 中「结构化正文」+ 右「线程侧栏」（可折叠）。窄屏（<1280px）右栏收成抽屉（复用 `components/ui/sheet/`）；左栏收成顶部下拉。
- 锚定坐标系双键、且与后端同源：块级 DOM `id` 用 `block_id`，段级导航 key 用段名；`section_path` **只作降级定位与失锚回显文案**，不另立第三套坐标。
- 确认门（阶段 1）UI 纳入本相位，作为查看器内的 `BlueprintGatePanel`（消费既有 `blueprint-gate/` 快照 + 七动作端点）。**显式登记这是相对 ROADMAP SC 的范围增量** —— 若 plan-checker 判定超载，拆成本相位最后一个可独立顺延的 plan，不得混进查看器主干 plan。

**批注层与线程交互**

- 划线粒度 = block 内字符区间；`<mark>` 包裹；offset 越界 / block 不存在 ⇒ 降级为整块左侧色条。**不引入 tiptap/ProseMirror 只读实例**。
- 线程以右侧侧栏为主，不做 inline 气泡；选区评论用 floating popover（`@floating-ui/vue` 已在依赖）。
- **⛔ 线程动作按 `kind` 硬分流（本相位最不能错的一条，来自 114 CR-01）**：`ai_review_finding` 的侧栏**不渲染「回复」输入框**，只给「已修复」/「误报忽略」（各自必填 `reason`）；只有 `ai_clarification` / `human_comment` / `repo_confirmation` 走 `answer/`。分流做在**渲染层**而非提交层。approve 返回 409 时 `unresolved_blocker_thread_ids` 要渲染成**可点击跳转**的清单。
- 未决 / 失锚常驻可见；失锚线程**直接渲染快照的 `orphaned_threads` 不再前端过滤**。

**数据面、版本 diff 与实时生成态**

- 新增只读「蓝图正文」端点 `GET /api/delivery/artifacts/<uuid:artifact_id>/blueprint/`（可选 `?version_id=`），必须**照挂 114 的 `_aassert_project_scope`**；`quality` 键顺带消费三项 DB 统计，**无数据回 `None` ⇒ UI 显示「暂无数据」而不是 0**。
- 版本列表复用既有 `getArtifactTimeline`，**diff 在前端算**；块内文本用已在依赖的 `diff`（`diffWords`），范式对齐 `PromptVersionDiff.vue`。**不为 diff 新增后端端点**。
- 实时进展走「只读事件端点 + 状态驱动轮询」，**绝不新建推送通道**；新增 `GET .../blueprint/events/` 只取 `blueprint_*` 事件类型；消费点收敛到**一个** composable。
- 加载 / 空 / 错误四态：生成中**按段渲染骨架屏**；错误态全部读 `ApiError.status`；**404 一律渲染中性的「无权限或不存在」**；409 渲染带解药的提示；400 原样回显后端 `detail`。

**知识库 tab、引用预览与人审终审**

- tab 落位复用 `pages/knowledge/index.vue` 既有机制（**纯追加零新机制**）。
- 列表另起独立只读端点 `GET /api/delivery/blueprints/`，**不改 `ArtifactListView`**；**不用 `searchDeliveryKnowledge`**。
- 项目关联双向可查：`ProjectMaterialsPanel` 新增一张**只读**「技术方案蓝图」卡。
- 引用预览统一走一个 `CitationPreviewDialog`，按 `source_type` 分发到已有读取面；**兜底不留白**。
- 人审终审防误触：视觉分离 + 二次确认；**驳回的 `comment` 必填非空**；按钮可用性由 `current_status` 驱动。
- 可编辑状态白名单前置到 UI（114 MJ-04）；**前端不自建权限判断**（一律以后端状态码为准）；**动作后的状态一律以响应体 `current_status` 为准并重取快照**。

### Claude's Discretion

- 组件文件切分与命名、Tailwind 类与颜色令牌选取、图标选择、i18n key 层级、TanStack Query 的 queryKey 结构与缓存时长、骨架屏形状、测试组织与 `data-testid` 命名。
- 新增只读端点的序列化器切分、查询优化（`select_related` / `annotate` 批注数）、以及它们的测试组织。

### Deferred Ideas (OUT OF SCOPE)

- 既有触点升级（`ArtifactTimeline` / `TechPlanCard` / `NodeDataTab`）→ Phase 116，同步点 2 之后。
- 飞书导出 + 未确认水印（VIEW-05）→ Phase 116。
- 澄清提醒的渠道投递 → 通知面，同步点 1 之后。
- 蓝图列表的语义搜索（向量召回）→ Future。
- **block 正文编辑（`edit-blocks/` 的前端面）→ Phase 116**；本相位写路径穷举为三条（澄清/评论作答、选区评论建线程、finding 处置）+ 终审两动作 + 确认门七动作。
- `content.execution_plan` 段的呈现 → 116+。
- 母子蓝图编排拆分 / 段级细粒度编辑权限 / golden set 弱标签扩样。

---

## Part A —— 后端：五个新端点

### A.0 UI-SPEC 五条主张逐条核验

| # | UI-SPEC 主张 | 核验结果 | 证据 |
|---|-------------|---------|------|
| 1 | 人审快照**不返回 content**，`ArtifactTimelineView` 只给 markdown 串 ⇒ 做不了 block 锚定与 diff | ✅ **成立** | 快照 payload 十二键（`blueprint_review_views.py:382-405`）无 `content`；`_alatest_content`（`:162`）只在内部被 `_ablueprint_project_id`（`:233`）用来取 `meta.project_id`。`ArtifactTimelineSerializer` 出 `current_version_markdown`（`api/deliveryArtifacts.ts` 的 `ArtifactTimeline` 接口逐字对应） |
| 2 | 快照的 `_thread_row` 九字段，**无 `options`、无任何消息** ⇒ 多轮回复无法呈现 | ✅ **成立** | `_thread_row`（`blueprint_review_views.py:174-186`）逐字九键；`BlueprintThread.options`（`models/blueprint_thread.py:101`）与 `BlueprintThreadMessage`（`:133`）均未进快照。**UI-SPEC 漏了一项**：`last_reminded_at`（`:118`）也不在 `_thread_row` 里，而 UI-SPEC §0.2 判定 4 的「已提醒 N 次 / 上次提醒时间」要它 |
| 3 | 全仓无「按选区新开 `human_comment` 线程」的入口，唯一创建路径是 `reject/` 的副作用 | ✅ **成立** | `delivery/urls.py:191-225` 七条 `blueprint-review/` 路由无 threads 集合路由；`BlueprintReviewRejectView`（`:477`）的 `comment` 非空时开一条 `human_comment`。**开线程唯一合法 writer 是 `BlueprintLifecycleService.open_thread`**（INV-6，见 §A.7） |
| 4 | `ConvergenceSessionEvent` 无 REST 无 WS | ✅ **成立** | 模型 `models/convergence_session_event.py:21`；全仓无以它为主体的 View/Serializer（唯一读点是 `blueprint_quality.ai_rejection_rate:127` 的统计查询） |
| 5 | `ArtifactListView` 不可复用（挂闸会改既有面行为） | ✅ **成立且更强** | `ArtifactListView`（`artifact_views.py:58-98`）只有 `IsAuthenticated` + 三个过滤参数，**无任何项目可见性过滤**，已被 `web/src/components/delivery/ArtifactTimeline.vue:43` 以 `space_id + artifact_type` 消费。另外它返回 `list[]` 裸数组、无分页 —— 就算不谈闸，也承不住 UI-SPEC §3.3 的分页契约 |

**两处需要订正 UI-SPEC 的口径：**

- UI-SPEC §3.1 注 `blueprint_quality.py:76` 分母为 0 返回 1.0 —— 实际在 **`:77`**（函数 `citation_coverage` 定义在 `:68`）。结论不变。
- UI-SPEC §3.6 / §10.1 说 `chunk-at` 失败「回显 `detail` 会得到空串」—— 实际 `api/client.ts:237,242` 的 `detail` 有默认值 `'请求失败'`，拿到的是这句无意义中文而不是空串。结论（不走 `detail` 分档）不变，但**「空串」这个判据本身是错的**，别据它写断言。

### A.1 端点 1：`GET artifacts/<uuid:artifact_id>/blueprint/`（正文 + quality）

**取版本**：`ArtifactVersion.objects.filter(artifact_id=…)`；`?version_id=` 缺省时**取 `order_by("-version_no").afirst()`**，⛔ **不要读 `Artifact.current_version`**。理由是 114 立的纪律（STATE，Phase 114 / 114-04）：「基线一律 `order_by("-version_no").afirst()`，绝不读 `session.current_artifact_version`（会把上游成果覆盖回旧内容）」；`_alatest_content`（`blueprint_review_views.py:162-171`）正是这个口径的既有落点，照抄它。

`is_current` 的判定用 `artifact.current_version_id == version.id`（`models/artifact.py:93` 的循环 FK），不要用「version_no 最大」二次推断 —— 两者在并发落版本时会短暂不一致，而 UI 的「回到当前版本」按钮依赖它。

**响应键**（对齐 UI-SPEC §3.1）：`version_id / version_no / is_current / produced_by_ref / created_at / content / quality`。字段来源 `models/artifact.py:130-164`（`ArtifactVersion`：`content` `:149`、`content_hash` `:151`、`produced_by_ref` `:156`、`created_at` `:164`）。

**`quality` 四项**（`services/process_runtime/blueprint_quality.py`）：

| 键 | 函数 | 签名 | 返回 |
|---|------|------|------|
| `citation_coverage` | `citation_coverage(blueprint: dict) -> float` `:68` | **同步纯函数**，入参是 content dict | 恒有值；分母为 0 → `1.0`（`:77`） |
| `ai_rejection_rate` | `ai_rejection_rate(artifact_id: str) -> float \| None` `:127` | **同步 + 函数内懒 import ORM** | 零事件 → `None` |
| `human_edit_volume` | `human_edit_volume(artifact_id: str) -> int \| None` `:157` | 同上 | 零版本 → `None`；有版本零人工编辑 → `0` |
| `clarification_rounds` | `clarification_rounds(artifact_id: str) -> int \| None` `:182` | 同上 | 零线程 → `None`；有线程无人作答 → `0` |

⚠️ **后三项是同步函数且内部直接查 ORM**（`:139` / `:167` / `:190`），在 adrf 异步 View 里**必须 `sync_to_async` 包裹**，否则 `SynchronousOnlyOperation`。三者可以合成一个 `@sync_to_async def _collect_quality(artifact_id)` 一次性算完（三次查询本来就要串行）。

它们内部已 `try/except` 全兜（`:150` / `:172` / `:196` 各自 `except Exception` → `_log_stat_failure`），端点侧**不要再包一层 try 把 None 改写成 0**。

### A.2 端点 2/3：`GET` / `POST artifacts/<uuid>/blueprint-review/threads/`

**路由顺序**：字面段 `threads/` 与既有 `threads/<uuid:thread_id>/<动作>/` 互不遮挡（Django `path()` 是整段精确匹配，`delivery/urls.py:189-190` 的注释已声明该纪律）。追加到 `urlpatterns` 任意位置都可，建议紧贴 `blueprint-review-snapshot` 之后以保持前缀分组可读。

**GET 的形状**（UI-SPEC §3.4）在 `_thread_row` 九键之上补三项，来源全部实读确认：

| 补充键 | 来源 | 备注 |
|-------|------|------|
| `options` | `BlueprintThread.options`（`models/blueprint_thread.py:101`，`JSONField(default=list)`，注释形状 `[{label, value, note}]`） | **半可信**：`default=list` 但无 schema 校验，序列化时逐项 `.get` 防御 |
| `last_reminded_at` | `BlueprintThread.last_reminded_at`（`:118`，`null=True`） | UI-SPEC §0.2 判定 4 要它，但没登记在 §3.4 之外任何地方 —— 别漏 |
| `messages[]` | `BlueprintThreadMessage`（`:133-164`），`related_name="messages"`，`Meta.ordering = ["created_at"]`（`:161`） | `author` 是 `SET_NULL` FK（`:146`）⇒ **`author_display` 必须容忍 `None`**（用户被删/AI 作者） |

**N+1 防线**：`BlueprintThread.objects.filter(artifact_id=…).prefetch_related("messages")` + 消息侧 `Prefetch(queryset=BlueprintThreadMessage.objects.select_related("author"))`。⚠️ `BlueprintThread.Meta`（`:120-127`）**无 `ordering`** —— 必须显式 `.order_by("created_at")`（既有 `_load_thread_rows`（`blueprint_review_views.py:190-196`）就是这么做的；STATE 里 114 MN-01 专门为「无 ORDER BY 的 LIMIT」立过一条纪律）。

**POST 的写入口**：⛔ **绝不 `BlueprintThread.objects.create(...)`**。`server/tests/delivery/test_blueprint_inv6_guard.py:42-54` 三条正则（`_RE_ORM_WRITE` / `_RE_INSTANTIATE` / `_RE_INSTANCE_SAVE`）扫全 `server/`，唯一豁免模块是 `delivery/services/blueprint_lifecycle_service.py`（`:39` `_ALLOWED_WRITER`）。⚠️ 注意 `_RE_INSTANTIATE`（`:48-50`）连**裸实例化**都逮 —— 连 `BlueprintThread(...)` 这种形态都不能出现在新文件里。

唯一合法路径是 `BlueprintLifecycleService.open_thread(...)`（`delivery/services/blueprint_lifecycle_service.py:365`，线程行 + 首条消息同事务）。反过来说，**POST 端点的实现应当是一个 `delivery/services/blueprint_comment_action.py` 薄 service**（照 `blueprint_review_action.py` 范式），View 零 ORM 写（`blueprint_review_views.py:25-28` 的 banner 明写这条）。

**状态闸**：UI-SPEC §3.5 要求「蓝图状态 ∉ 可编辑白名单 → 400（与 `answer` 同闸）」。判据函数 `is_blueprint_editable(artifact)` 与文案常量 `NOT_EDITABLE_DETAIL` 都在 `blueprint_lifecycle_service`，既有用法逐字见 `blueprint_review_views.py:636-649`。

### A.3 端点 4：`GET artifacts/<uuid>/blueprint/events/`

**过滤集合**：`from delivery.services.event_taxonomy import BLUEPRINT_EVENTS`（`server/delivery/services/event_taxonomy.py:185-208`，**21 个常量**，`server/tests/delivery/test_blueprint_event_taxonomy_112.py:111` 用 `len(...) == 21` 锁死）。UI-SPEC §8.1 的 21 行映射表与它逐字对应，已核。

**查询**：`ConvergenceSessionEvent.objects.filter(session=<该 artifact 的蓝图会话>, event__in=BLUEPRINT_EVENTS).order_by("ts")`。

三条实测约束：

1. **反查会话必须带 `process_type` 过滤**。`_aload_session`（`blueprint_review_views.py:106-126`）的 docstring 逐字记了这条 CRITICAL：同一 artifact 上可能同时挂 `technical_plan` 与 `technical_blueprint` 两条会话，不过滤就会读到旧链会话的事件流。常量是 `services.process_runtime.blueprint_resume.BLUEPRINT_PROCESS_TYPE`。
2. **`Meta.ordering = ["created_at"]`**（`models/convergence_session_event.py:49`）而索引是 `(session, ts)`（`:51`）。UI-SPEC §3.2 要求 `ts` 升序 —— 显式 `.order_by("ts")` 会覆盖 Meta 默认序并走上索引，两全。别依赖默认序（`created_at` 与 `ts` 可以不同：`ts` 允许 emit 端传入，`:41` `default=timezone.now`）。
3. **`payload` 是自由 `JSONField`**（`:39`）。UI-SPEC §8.1 的进度文案里插值了 `question_count` / `repository_name` / `fitness_verdict` / `candidate_count` / `round` / `seq` / `to_key` / `satisfied_count` / `attempt` / `decision_log_count` 十个键 —— **这些键由各 emit 点自行决定，schema 层零保证**。端点原样透传 payload，前端插值时**每一个都要有缺省文案**（见 P-8）。

**`session_id` / `current_stage`**：`ConvergenceSession` 上取；会话不存在时（蓝图还没跑过编排）返回 `{session_id: "", current_stage: "", events: []}` **200**，⛔ 不要 404 —— 这是正常态，404 会被前端 §8.2 的 404 分档吞成全页空态。

### A.4 端点 5：`GET /delivery/blueprints/`（列表）

这是五个端点里**最容易撞守卫**的一个，见 P-1（必读）。

**可见性口径**：与前四个端点不同。前四者是「拿着一个 artifact_id 问能不能看」（`_aassert_project_scope` 逐个判）；列表是「列出我能看的全部」。两种口径不能互相套用：对 N 条候选逐条跑 `_aassert_project_scope` 会是 N 次 `meta.project_id` 提取 + N 次 `ProjectMember.aexists()`。

正确形态 = 先算出「我是成员的项目 id 集合」，再用它过滤。⚠️ **但蓝图的项目归属存在 `ArtifactVersion.content["meta"]["project_id"]` 里，不是 DB 列** —— 无法直接 `filter(project_id__in=...)`。三条可选路径，planner 择一并在 PLAN 里写死：

| 方案 | 做法 | 代价 |
|------|------|------|
| A（推荐） | 先按 `artifact_type="technical_plan"` + `blueprint_status != ""` 收窄到蓝图集合（有索引：`models/artifact.py:123` `Index(fields=["artifact_type", "blueprint_status"])`），`select_related("current_version")` 后在 Python 里按 `content["meta"]["project_id"] ∈ allowed` 过滤，再分页 | 蓝图总量小（一项目一份活跃蓝图，DESIGN §12 ①），可接受；分页要在过滤**之后**切片 |
| B | 走 `Artifact.work_item__space_id`（`ArtifactListView:90` 既有路径） | ⛔ **口径不同**：space ≠ project，且蓝图的 `work_item` 可空（`models/artifact.py:76-82` `null=True`）⇒ 会漏 |
| C | 新增 migration 把 `meta.project_id` 提成 DB 列 | 违反「本相位只加读面」的边界，且 STATE §13.2 第 5 条对 migration 有 rebase 纪律 |

「我是成员的项目 id 集合」的既有取法：`initiatives.models.ProjectMember.objects.filter(user=request.user)`（判据与 `blueprint_review_views._ais_project_member`（`:244-251`）同源）。⚠️ `knowledge.access_scope.resolve_allowed_project_ids` **不能直接用** —— 它返回的是**可见 Space id**（`knowledge/api/artifact_overview.py:7,26` 的 docstring 逐字：「返回**可见 Space id**（membership ∪ public_org）」），不是 project id。

**superuser 直通**：`_aassert_project_scope:274` 有 `is_superuser` 直通，列表侧保持对称（superuser 见全部）。

**分页范式**：仓内有两套。

- DRF `PageNumberPagination` + `sync_to_async(self.paginate_queryset)`（`runners/views.py:241,300` / `codegraph/views.py:873` / `subagent/views.py:22`）。
- 手写 offset 分页 + 自定义响应体（`knowledge/api/artifact_overview.py:46-62,160-188`：`_parse_page` / `_parse_page_size` clamp 到 `[1, 100]`，响应 `{total, items, page, page_size, has_next}`）。

方案 A 需要在 Python 侧过滤后再切片 ⇒ **DRF 的 `paginate_queryset` 用不上**（它要 queryset）。取 `artifact_overview` 那套手写范式（同为 adrf 异步 + 同为「先聚合再切片」形状），响应体键沿用它的五键，**不要**发明第三套。UI-SPEC §3.3 写的是「DRF 分页体」—— 这是本文与 UI-SPEC 的一处分歧，PLAN 需显式定夺（建议取 `artifact_overview` 范式并在 §3.3 的 TS 接口上同步改键）。

**`?q=` 搜索面**：UI-SPEC 说「标题 + 摘要 icontains」。`Artifact.title`（`models/artifact.py:84`）是 DB 列可 `icontains`；**「摘要」在 `content["meta"]["summary"]` 里是 `Block[]`**（`blueprint_schema.py` `meta.summary: block_list`），JSON 内检索跨 PG/MySQL/SQLite 行为不一。方案 A 既然已经把候选拉进 Python，摘要匹配就在 Python 侧做（对齐 `_rank`/`_rank_case` 那种「Python 与 DB 双实现同序」的既有妥协）。

**`?repository_id=`**：来源是 `content["repo_associations"][].repository_id`，同样只能 Python 侧过滤。

**`thread_count` / `unresolved_blocker_count`**：可以走真 ORM `annotate`（`BlueprintThread` 有 `artifact` FK 与 `Index(fields=["artifact","status","blocking"])`，`models/blueprint_thread.py:126`）。⚠️ 见 P-1 第二条：`unresolved_blocker_count` 这个**变量名/键名本身安全**，但若为算它而 `from ... import aunresolved_blocker_count` 并且同文件里出现 `BlueprintStatus.CONFIRMED`，会撞 TOCTOU 扫描守卫。

### A.5 项目范围闸：复用而不是复制

`_aassert_project_scope`（`blueprint_review_views.py:254-281`）的四条语义（MJ-03）：

```
superuser 直通 (:274)
→ 从蓝图最新版本 meta.project_id 取范围 (_ablueprint_project_id :233-241)
→ 非 UUID / 缺失 ⇒ 400  fail-closed (:277-278)
→ 非 ProjectMember ⇒ 中性 404（不是 403，避免枚举存在性）(:279-280)
→ 放行返回 None
```

它依赖 `_is_uuid`（`:223`）、`_ais_project_member`（`:244`）、`_alatest_content`（`:162`）。**全仓已有两份近似实现**：`blueprint_gate_views._ablueprint_project_id`（`:511`）是第二份，但它**只在 `BlueprintRejectedToBoundaryView`（`:385`）里被用了一次** —— 也就是说 `blueprint-gate/` 的快照与七动作端点**至今没有项目范围闸**（只有 `IsAuthenticated`）。

对本相位的两条推论：

1. 新增四个 artifact 级端点**照挂**（CONTEXT 与 STATE 的明令），别再造第三份 —— 建议把 `_aassert_project_scope` 及其三个 helper 提到 `delivery/api/blueprint_scope.py`，`blueprint_review_views.py` 改为 import（**这是对既有文件的修改**，PLAN 要显式登记；若判定不可动，就 `from delivery.api.blueprint_review_views import _aassert_project_scope` 直接复用私有符号并注释说明）。
2. **前端不得把 `blueprint-gate/` 的 404 当作权限信号** —— 那条链没闸，它的 404 只表示「门未开 / artifact 不存在 / 无蓝图会话」（`blueprint_gate_views.py:53,174,176,179,211,213`）。UI-SPEC §8.2 例外一的结论（gate 非 200 ⇒ 不渲染面板、不报错）**恰好是对的**，但理由要换成这条。

### A.6 五个端点的 URL 与命名（建议，对齐既有分组注释纪律）

```python
# delivery/urls.py 纯追加
path("blueprints/", BlueprintListView.as_view(), name="blueprint-list"),                    # 字面段，须在 artifacts/ 分组之外
path("artifacts/<uuid:artifact_id>/blueprint/", BlueprintDocumentView.as_view(),  name="blueprint-document"),
path("artifacts/<uuid:artifact_id>/blueprint/events/", BlueprintEventsView.as_view(), name="blueprint-events"),
path("artifacts/<uuid:artifact_id>/blueprint-review/threads/", BlueprintReviewThreadsView.as_view(), name="blueprint-review-threads"),
```

`blueprint/` 与 `blueprint/events/` 是两个整段精确匹配，互不遮挡；两者与既有 `blueprint-gate/` `blueprint-review/` 同级。`threads/` 集合路由与 `threads/<uuid>/…/` 三条动作路由整段不同，顺序无关（但**照 `delivery/urls.py:189` 的注释纪律把字面段写在前面**，保持读者预期一致）。

`name` 全部走 `reverse()` 可解析 —— 114-05 的测试范式是 `reverse("blueprint-review-thread-resolve")`，新端点测试照抄。

### A.7 观测埋点（`.cursor/rules/observability-logging.mdc` 强制）

照抄 `blueprint_review_views._log`（`:284-294`）的形状：`category="caller"`、`component=<新常量>`、`artifact_id`、`initiated_by_user_id`、`duration_ms`。

三条本相位特有的：

- **正文绝不进日志**。114 立的 T-114-36（`blueprint_review_views.py:55` banner）：「评论正文、block 正文、答案正文、处置理由正文一律不进日志」。新的 POST threads 端点的 `body` 与列表端点的 `?q=` 同理 —— `q` 可记**长度**不记内容。
- **`error=str(exc)` 一律过 `redact_secrets_in_text`**。AST 守卫 `server/tests/delivery/test_blueprint_log_redaction_guard.py` 的 `_SCANNED_MODULES`（`:27-37`）当前九个模块，**新增的蓝图 API/service 模块必须加进去**（该文件 `:14` 的 docstring 明写这条）。允许的脱敏出口只有 `redact_secrets_in_text` / `redact_credentials` / `_detail` / `redact_for_ledger`（`:41`），审的 kwarg 只有 `error`（`:44`）。
- 只读 GET 端点也记 caller 事件（既有 `blueprint_review_snapshot_read` `:407` 就是先例）。

---

## Part B —— 前端：七类机制

### B.1 字符区间高亮（`<mark>` 切分）

**仓内零先例**：`rg "window.getSelection|selectionchange|createTreeWalker"` 在 `web/src` **零命中**（唯一 `setSelectionRange` 命中是 `ChatInput.vue:74` / `ChatMessageBubble.vue:106` 的 textarea 光标复位，与富文本区间无关）。这一块是完全从零写。

**切分算法应当是纯函数**，签名建议：

```ts
// web/src/utils/blueprintAnnotations.ts（新建）
interface AnnotationRange { start: number, end: number, threadIds: string[] }
export function sliceBlockText(text: string, anchors: Array<{threadId: string, start: number, end: number}>):
  Array<{ text: string, threadIds: string[] }>
```

这样 vitest 可以廉价覆盖全部边界（越界 / 反序 / 重叠 / 非整数 / 空数组 / 全覆盖），而不必挂载组件。UI-SPEC §7.1 的四步算法已定稿，直接实现即可。

**坐标系必须与后端 `_block_text` 逐字同源**（`server/delivery/services/blueprint_anchor.py:34-64`，**注意路径是 `delivery/services/` 不是 `process_runtime/`**）。实读的四分支优先级（顺序不可换）：

```python
text 是非空 str            → 直取                      # paragraph / mermaid
text 是 list               → "\n".join(str(item) …)    # list 型：连接符确认为 \n ✅
code.source 是非空 str     → 取它                      # pseudocode
rows 是 list               → 逐行逐格扁平后 "\n".join  # table
其余                        → ""
```

⇒ UI-SPEC §6.2 的「`list` 条目间用 `\n` 连接」**已验证正确**。三条派生结论：

- `pseudocode` 的坐标系是 `code.source` 原文 ⇒ 前端 `<pre>{{ code.source }}</pre>` 的字符 offset **天然对齐**，可以做字符级划线（UI-SPEC §7.3 只把 `table` / `mermaid` 列为强制降级，正确）。
- `table` 的后端坐标系是「所有单元格扁平后 `\n` 连接」，前端渲染的是 `<table>` ⇒ offset **无法映射**，强制整块色条（UI-SPEC 正确）。
- ⚠️ **优先级陷阱**：`text` 分支在最前。一个同时带非空 `text` 与 `code` 的 `pseudocode` 块，后端取 `text`、前端若按 `type` 取 `code.source` ⇒ 两套坐标。前端 `blockText()` 必须**按同样的四分支顺序**实现，**不要按 `block.type` 分派**。



**安全**：全程 mustache + `v-for`，禁 `v-html`。这与既有 `PromptVersionDiff.vue:10-11` 的自述纪律一致。

### B.2 选区 → popover（`@floating-ui/vue`）

**依赖状态**：`web/package.json:34` `"@floating-ui/vue": "catalog:"` → `web/pnpm-workspace.yaml:24` `^1.1.11`，lock 里解析到 `1.1.11`（`web/pnpm-lock.yaml:1169,5959`）。**但 `rg "@floating-ui/vue|useFloating" web/src` 零命中** —— 装了没用过。它当前是 `reka-ui` / `tiptap` 的传递依赖被提到直接依赖位。

⚠️ 本 worktree **没有 `web/node_modules`**（未 install），所以本次无法实跑验证 API 形状。`useFloating(reference, floating, options)` 返回 `{ floatingStyles, placement, middlewareData, update }` 是 `@floating-ui/vue` v1 的公开形状 `[ASSUMED]`，PLAN 应把「首次使用前跑一次 `pnpm install && pnpm test:unit`」当作 Wave 0 的一步。

**替代方案（若 floating-ui 形状不合）**：`~/components/ui/popover`（reka-ui）已在仓内且被多处使用，但它是 trigger 驱动的；选区 popover 需要**虚拟参考元素**（`Range.getBoundingClientRect()`），reka-ui 的 Popover 支持 `PopoverAnchor` 可以承接。两条路都通，PLAN 选一条写死，别让执行者临场选。

**取 offset 的算法**同样纯函数化：给定 `Range` 与 block 根元素，用 `TreeWalker` 累加前序文本节点长度。⚠️ happy-dom 对 `TreeWalker` / `Range` 的支持度未验证 `[ASSUMED]` —— 若测试环境不支持，该函数的单测要 mock DOM 或改为「接收扁平文本节点数组」的更纯签名。

### B.3 Mermaid：`MermaidDiagram.vue` 契约（实读）

`web/src/components/project/warroom/MermaidDiagram.vue`，103 行，逐条契约：

| 项 | 实测 |
|---|------|
| **prop 名** | `code: string` —— **不是 `source`**（`:7` `defineProps<{ code: string }>()`）。UI-SPEC §6.8「`flow.mermaid` 直接给 `MermaidDiagram.vue`」要写成 `:code="flow.mermaid"` |
| 初始化 | 组件实例内 `initialized` 惰性开关（`:9-21`）；`securityLevel: 'strict'`、`startOnLoad: false`、`flowchart: {useMaxWidth: true, htmlLabels: true}` |
| 主题 | `document.documentElement.classList.contains('dark')`（`:13`）—— 全站无 `.dark` 块，恒 `'default'` |
| 失败回退 | `catch` 里清空 `svg` + `error = true`（`:42-46`），模板 `v-else` 渲染 `<pre>{{ props.code }}</pre>`（`:72-75`）+ 一行「无法渲染流程图，已展示源码」（`:76-78`）。**回退是自动的，调用方零处理** |
| 空源码 | `code.trim()` 为空 → `svg=''` 且 `error=false`（`:29-33`）⇒ 渲染一个**空 `<pre>`** 且无提示。UI-SPEC §6.8「`mermaid` 为空时不渲染容器」**必须由调用方 `v-if` 实现**，组件自己不管 |
| 重渲 | `watch(() => props.code, render)`（`:50`），非深监听，字符串 prop 足够 |
| 放大 | 用 **`VueFinalModal`**（`vue-final-modal`，`:4,80`），**不是** `~/components/ui/dialog` |
| XSS | `v-html="svg"`（`:71,100`），靠 `securityLevel:'strict'` 兜底。既有面，本相位不改 |
| 文案 | 内联中文（`:59,67,77,89`），**未走 i18n** |

⚠️ **两条对本相位的直接影响**：

1. `VueFinalModal` 的 zoom 层与 UI-SPEC §5.3 的 z-index 分层（`Dialog` z-50）**是两套栈**。`vue-final-modal` 在 `main.ts:6,17` 全局注册（`createVfm()` + `style.css`）。在 `CitationPreviewDialog`（reka-ui `Dialog`）**内部**渲染 `MermaidDiagram` 并点「放大」，会出现 vfm 层与 reka-ui 层的叠放竞争 —— UI-SPEC §10.1 的 `CitationBlueprintPreview` 是「迷你只读渲染」，PLAN 应明确**预览弹层内不渲染 mermaid 块**（只渲染被引块，若被引块恰是 mermaid 则退化为源码 `<pre>`）。
2. 测试里挂载任何含 `MermaidDiagram` 的组件都要 `stubs: { MermaidDiagram: true }`，否则要连带 vfm 插件。

### B.4 block 级 diff：`PromptVersionDiff.vue` 范式（实读）

`web/src/components/prompts/PromptVersionDiff.vue`，137 行：

- `import { diffLines } from 'diff'`（`:19`），`import type { Change } from 'diff'`（`:17`）。`diff` 在 `web/package.json:78` catalog 中；`PromptVersionDiff` 的注释写 `diff@8.0.4`（`:5`）。`diffWords` 是同包同 API 形状的兄弟函数 `[ASSUMED: 未在仓内使用过]`。
- **`shallowRef<Change[]>`**（`:20,28`）避免深响应式 —— UI-SPEC §9.2「性能」条逐字来自这里。
- ⚠️ `watch(..., { deep: true })`（`:30-36`）配 `shallowRef` 是**既有的一处自相矛盾**（deep watch 两个 prop 对象，然后整体替换 shallowRef）。新组件监听 `versionId` 这类标量即可，别照抄 `deep: true`。
- 颜色令牌是 `<style scoped>` 里的 `.diff-added` / `.diff-removed` / `.diff-unchanged`（`:119-137`），**scoped ⇒ 无法跨组件复用**。UI-SPEC §9.2 说「逐字沿用」——那意味着**在新组件里重写一遍这三条 CSS**（值逐字相同），不是 import。PLAN 要写清楚这一点，否则执行者会去找一个不存在的共享令牌文件。
- `aria-live="polite"` 摘要行（`:74-81`）。

**前端版 `iter_blocks`**：必须与 `server/services/process_runtime/blueprint_schema.py:919-1036` 的走查顺序**逐段对齐**。实读的完整落位清单（13 处 `collect`）：

```
meta.summary
requirement_spec.goal / .background / .feature_points[<id>].description
repo_associations[<repository_id>].rationale.text / .responsibility / .fitness.reasons
                                   / .planned_change_summary / .support_needed
current_state_analysis[<repository_id>].summary / .findings[<id>].text
implementation_overview.requirement_narrative
                       .modules[<id>].narrative
                       .items[<id>].how / .existing_integration / .test_strategy
api_contracts[<id>].description / .data_source.notes
impact_analysis.business_impact / .affected_features[<feature>].description
               / .compat_risks / .rollback_plan
interaction_flows[<id>].steps[<seq>].note
```

⚠️ **`must_haves` / `decision_log` / `deferred_ideas` / `execution_plan` 不在走查里** —— UI-SPEC §6.9 已据此正确判定「`must_haves` 不接批注层」，但**它没提 `decision_log` 与 `deferred_ideas` 也同样无 block**。UI-SPEC §13.3 却给 `DecisionLogSection.vue` 派了 `emits: ['open-thread']` 并把它列在正文段里 —— PLAN 要么给它同样的「不接批注」注释，要么核对 schema 后确认 `decision_log` 的条目形状（`blueprint_schema.py` 里 `decision_log` 是 optional，见 `:123-135` 的 required 列表**不含它**）。

`_item_key`（`:906-912`）的语义：优先取标识字段值，缺失回退**位置下标**（字符串化）。前端版必须同款，否则 `section_path` 对不上。

**diff 判据**：后端 `diff_blueprint_blocks`（`:1045-1060`）用 `_block_fingerprint = json.dumps(block, sort_keys=True, ensure_ascii=False)`（`:1039-1040`）。前端 `JSON.stringify` **不保证键序** ⇒ 前端要自己做 canonical 序列化（递归排序键），否则「块内容未变但键序不同」会被误判 `modified`。UI-SPEC §9.2 只写了「规范化 JSON 不等」，没说规范化怎么做 —— 这是执行期必然发生的分歧点。

### B.5 TanStack Query 惯例（实读）

**`refetchInterval` 的既有写法**（10 处命中，全部是「函数式、按 data 决定」）：

```ts
// web/src/components/project/workbench/DocsSection.vue:73
refetchInterval: query => (query.state.data?.sync_status === 'syncing' ? 2000 : false),
// web/src/components/repository/ReconcilePanel.vue:59
refetchInterval: query => (query.state.data?.status === 'running' ? 2000 : false),
// web/src/pages/admin/observability/index.vue:83
refetchInterval: () => (autoRefresh.value ? AUTO_REFRESH_MS : false),
```

⇒ UI-SPEC §8.3 把 `refetchInterval` 写成 `computed(() => isLive ? 5_000 : false)` 再传值，与既有「传函数」范式不同但**两种 TanStack Query 都支持**。传函数的好处是能读到 `query.state.data` 里的最新 `current_status`，避免「用上一轮的状态决定这一轮要不要轮询」的一拍延迟（见 P-9）。建议 PLAN 取函数式。

`composables/usePolling.ts` 是**另一套东西**（`useIntervalFn` 手动 start/stop，`onUnmounted` 自停），与 TanStack Query 无关，本相位不用它 —— CONTEXT 说「节奏对齐既有 `usePolling.ts` 惯例」指的只是**间隔量级**（它默认 2000ms）。

**queryKey 惯例**：`computed(() => [...])` 包裹以获得响应式（`pages/knowledge/entities/[id].vue:48,54,63`；`pages/knowledge/index.vue:143`）。`staleTime: 30_000` 是页面级默认（三处逐字）。

**invalidate 惯例**：`queryClient.invalidateQueries({ queryKey: ['knowledge'] })`（前缀匹配，`entities/[id].vue:40,44`）。UI-SPEC §3.7 的「`predicate: 命中该 artifactId`」在仓内**无先例** —— 简单做法是 `invalidateQueries({ queryKey: ['blueprint'] })` 全域失效（本页只有一个 artifact，无副作用）。

**错误分档基础**：`entities/[id].vue:93` 的 `is404` 是仓内唯一先例，逐字可抄：

```ts
const is404 = computed(() => q.error.value instanceof ApiError && q.error.value.status === 404)
```

`ApiError` 三字段（`api/client.ts:18-30`）：`status` / `detail` / `body`。⚠️ `detail` 在响应体无 `detail` 键时**回落成 `'请求失败'`**（`:237,242`），不是空串。

### B.6 代码片段预览：`chunk-at` 的真实响应形状

`server/repositories/chunk_at_views.py`（60 行，全文实读）：

| 情形 | 状态码 | 体 |
|------|-------|---|
| 仓库不存在 / 已删 | **404**（`aget_object_or_404`，`:30`） | DRF 默认 `{"detail": "No Repository matches..."}` |
| 缺 `path` | 400 | `{"error": "缺少必填参数 path"}`（`:35`） |
| 缺 `line` / 空串 | 400 | `{"error": "缺少必填参数 line"}`（`:41`） |
| `line` 非整数 / < 1 | 400 | `{"error": "line 必须为正整数"}`（`:47,51`） |
| **无命中 / 文件被排除** | **200** | `{"path", "line", "chunks": []}`（`:60`）—— **刻意不可区分**（`:5-9` docstring 的 T-25-05） |
| 命中 | 200 | `chunks[]`，每项 `{chunk_id, file_path, line_start, line_end, chunk_index}`（`services/chunk_lookup.py:49`），按覆盖区间宽度升序（最具体优先，`:44`） |

⚠️ **两条 UI-SPEC 需要修正的**：

1. UI-SPEC §10.1 的兜底判据「任何非 2xx」**漏掉 200-空 chunks**。正确判据是 `!res.ok || (res.chunks?.length ?? 0) === 0`。这是本相位最容易出的一个静默空壳（见 P-3）。
2. `chunks[]` 里**没有代码正文** —— 只有 `chunk_id` 与行号区间。UI-SPEC §10.1 说「CodeMirror 只读实例 + 行高亮」，但**正文从哪来没有交代**。全仓需再找一个「按 chunk_id / 按 path+行区间取源码」的读面；若不存在，`CitationCodePreview` 就只能渲染「文件路径 + 行号区间 + citation 的 `quote` 快照」。**PLAN 必须先解决这个缺口**（要么找到取源码的端点，要么把该来源类型的预览降级为「路径 + 行号 + quote」并在 UI-SPEC §10.1 上登记订正）。

**`locator.line_start` 缺失**：UI-SPEC §10.1 的「直接不发请求、立刻走兜底」是对的（`line` 必填，缺了稳定 400）。

**CodeMirror 只读封装**：`~/components/codemirror/fridayLightTheme.ts` 存在；仓内的只读展示先例是 **`components/execution/JsonViewer.vue`**，而它的注释（`:4-7`）明写「**替代 CodeMirror 的只读 JSON 展示**」—— 也就是说**仓内并没有一个现成的「CodeMirror 只读代码块」组件**，`PromptBodyEditor` / `MarkdownSourceEditor` / `JsonEditor` 都是可编辑实例。UI-SPEC §3.6 的「代码渲染复用既有 CodeMirror 只读封装」**指向一个不存在的东西**。选项：新建一个薄只读封装，或直接 `<pre class="font-mono">` + 行号 + 高亮行背景（与 `pseudocode` 块同一套渲染，省一个依赖面）。

### B.7 知识库 tab 宿主：`pages/knowledge/index.vue`（实读）

追加点逐字（该文件 485 行）：

| 位置 | 现状 | 追加 |
|------|------|------|
| `:40` | `type KnowledgeTab = 'overview' \| 'tree' \| 'ingest' \| 'search'` | 加 `\| 'blueprints'` |
| `:41` | `const TABS: KnowledgeTab[] = ['overview', 'tree', 'ingest', 'search']` | 数组加一项 |
| `:43-45` | `normalizeTab` 用 `TABS.includes` 兜底到 `'overview'` | **不改** |
| `:51-60` | `?tab=` 双向同步两个 `watch`（`router.replace({ query: {...route.query, tab: v} })`） | **不改** |
| `:220-233` | `TabsTrigger` 的 `v-for` 走一个**内联 `as const` 数组**（`{value, icon}`），标题走 `t(\`knowledge.tabs.${tab.value}\`)` | 数组加一项 |
| `:236-434` | 四个 `TabsContent` | 加一个 |

⚠️ **i18n 键必须同步加**：`web/src/locales/zh-CN.json:227-233` 的 `knowledge.tabs` 现有五键（`overview`/`search`/`ingest`/`release`/`tree`）—— 注意里面**已有一个 `release` 但 `TABS` 数组里没有**（历史残留）。加 `blueprints` 即可。**仓内只有 `zh-CN.json` 一个 locale 文件**（1364 行），无需同步英文。

`?tab=` 同步用 `router.replace({ query: { ...route.query, tab: v } })` ⇒ **其它 query 会被保留**，UI-SPEC §4.2 的 `bp_status` / `project_id` / `page` 等自然共存，无需额外机制。

### B.8 项目物料面板：`ProjectMaterialsPanel.vue`（实读）

- 分区流是**扁平堆叠**（`:44` `<div class="materials flex-1 min-h-0 overflow-y-auto">`），子件按顺序排列，无网格。
- 懒加载四件走 `defineAsyncComponent`（`:27-30`）。追加一行 import + 一处使用即可（UI-SPEC §0.1 追加点 #2）。
- 「无数据整块不渲染」的先例是 `<HumanTaskInbox :project-id="…" hide-when-empty />`（`:52`）—— 是一个 **prop**，不是组件自决。UI-SPEC §12.2 说「无数据时整块不渲染（对齐 `HumanTaskInbox` 的 `hide-when-empty` 习惯）」⇒ 新卡应当同样暴露一个 `hide-when-empty` prop 并由面板传入，而不是硬编码。
- 分区头范式：`<section class="flat-section"><header class="flat-header"><span class="section-chip">…</span><h3>…</h3></header><div class="p-5">…</div></section>`（`:57-66`）。
- ⚠️ **该面板已经在 `:76` 渲染了 `<ArtifactTimeline :space-id="project.space_id" artifact-type="technical_plan" />`** —— 蓝图与旧 technical_plan 共用 `artifact_type="technical_plan"`（`blueprint_review_views.py:112` 的注释明写这条），所以**新卡与它会列出重叠的条目**。这不是 bug，但 UI 上要能区分（新卡按 `blueprint_status != ""` 过滤 ⇒ 只出蓝图）。PLAN 应在文案上把两者区分清楚，避免用户以为重复。

### B.9 `AnchorNavLayout` 的真实契约（实读，含一个陷阱）

`web/src/components/layout/AnchorNavLayout.vue`，110 行：

- 导出 `NavSection` 接口（`:4-10`）：`{ id, label, icon?, badge?: string|number, badgeTone?: 'primary'|'success'|'warning'|'danger'|'muted' }`。UI-SPEC §6.1 的 badge/tone 用法与之逐字吻合。
- 结构（`:71-110`）：`<div class="flex gap-8">` 包 `<aside class="hidden md:block w-48 shrink-0">`（内含 `<nav class="sticky top-22">`）+ `<div class="flex-1 min-w-0 space-y-6"><slot /></div>`。UI-SPEC §5.1 的 DOM 归属描述逐字正确。
- `scrollTo`（`:46-53`）是**私有函数**，偏移常量 `88`（`:50`），`window.scrollTo({behavior:'smooth'})`。零 emit、零 expose。UI-SPEC §13.2 关于「不能把它嵌进 `BlueprintSectionNav`」的论证成立。
- badge 空值判定（`:95`）：`badge !== undefined && badge !== null && badge !== ''` ⇒ **`0` 会被渲染出来**。UI-SPEC §6.1 的「批注数」badge 若传 `0` 会显示一个灰色的 `0` —— 想不显示就传 `''`。

⚠️ **陷阱（P-4 详述）**：`onMounted`（`:19-40`）里 `props.sections.forEach(s => { const el = document.getElementById(s.id); if (el) observer?.observe(el) })`。**没有 `watch(() => props.sections)`**，也没有对 slot DOM 变化的重新观察。既有 `pages/knowledge/entities/[id].vue:149-153` 的第 4 个条件段（`v-if="showAssociations"`）就是这个 bug 的实例 —— 它永远不会被观察到。

`activeSection` 初值 `props.sections[0]?.id ?? ''`（`:16`），同样只取一次。

### B.10 前端测试设施（实读）

| 项 | 实测 |
|---|------|
| 配置 | `web/vitest.config.ts`（mergeConfig 自 `vite.config.ts`），`environment: 'happy-dom'`，`include: ['src/**/*.{test,spec}.{js,ts}']`，`setupFiles: ['./src/test/setup.ts']` |
| setup 内容 | **只有 localStorage / sessionStorage 的 MemoryStorage 垫片**（`src/test/setup.ts`，37 行）。无 i18n、无 router、无 fetch mock、无 IntersectionObserver 垫片 |
| 命令 | `pnpm test:unit`（`package.json:14`，即 `vitest`） |
| 现有用例分布 | ~50 个 spec：`stores/__tests__`（最多）、`composables/__tests__`、`api/__tests__`、`config/__tests__`、`utils/__tests__`、`lib/__tests__`；**页面/组件级只有个位数**（`pages/knowledge/__tests__/entity-detail.spec.ts`、`pages/specs/__tests__`、`pages/executions/__tests__`、`pages/repositories/__tests__`、`pages/workflows/__tests__`、`components/__tests__/node-data-tab.test.ts`、`components/prompts/__tests__/*`、`components/project/workbench/__tests__/DocsSection.spec.ts`） |

**页面级测试的既有范式**（`pages/knowledge/__tests__/entity-detail.spec.ts`，68 行，逐字可抄）：

```ts
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { id: '…' } }) }))
vi.mock('~/api', () => ({ knowledgeApi: { getEntity: vi.fn().mockResolvedValue({…}), … } }))
const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': { /* 手写最小键树 */ } } })
mount(Page, { global: {
  plugins: [i18n, [VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }]],
  stubs: { AnchorNavLayout: { template: '<div><slot /></div>' }, PageContainer: { template: '<div><slot /></div>' }, CompactEmptyState: true, EntityDetailToolbar: true },
} })
await new Promise(r => setTimeout(r, 50))   // 等 query resolve
expect(wrapper.html()).toContain('测试实体')
```

⚠️ **这套范式对本相位的可达性上界**：

- i18n 消息要**手写**（不 import `zh-CN.json`）⇒ UI-SPEC §20 断言 4「404 只有一句文案 / i18n 只有 `error.notFoundOrForbidden` 一个键被用于 404 分支」在组件测试里不好断，**改成源码扫描测试**更可靠（与断言 6 / 断言 10 同一形态）。
- `AnchorNavLayout` 被 stub 掉 ⇒ 十段导航的 badge/tone 逻辑要**在 computed 层单测**（把 `sections` 的计算提成纯函数或 composable）。
- happy-dom 无真实布局 ⇒ `IntersectionObserver`、`Range.getBoundingClientRect`、`window.scrollTo` 行为**都不可信**。滚动同步（UI-SPEC §7.6）无法自动化验证，只能列 UAT。
- mermaid 在 happy-dom 下必然走 catch 回退 ⇒ 若不 stub，交互流程段的测试只会看到 `<pre>` 源码。

**结论给 PLAN**：本相位的自动化测试预算应当这样分配 ——

1. **纯函数单测（高价值、易写）**：区间切分、offset 计算、前端 `iter_blocks` + diff 分类、`produced_by_ref` 前缀映射、`isBlueprintEditable`、进度文案映射（21 事件 → 段 key）、`quality` 三态渲染判据。
2. **组件级「渲染/不渲染」断言（中价值）**：UI-SPEC §20 的断言 1 / 2 / 3 / 5 / 8 / 9 / 11 —— 全部是「某个 `data-testid` 存在或不存在 / 条目计数」，happy-dom 完全够用。
3. **源码扫描断言（低成本、防回归）**：UI-SPEC §20 的断言 4 / 6 / 10（`refetchInterval` 只出现在一个文件、`edit-block` 零命中、404 文案单键）。仓内后端已有大量此形态先例可抄（`test_blueprint_inv6_guard.py`）。
4. **UAT（不自动化）**：滚动定位、mermaid 实渲、三栏断点、焦点管理、颜色对比度。

---

## Part C —— Pitfalls（会静默假通过的部分优先）

### P-1 ⛔ `blueprint_status=` 与 `"blueprint_status":` 会被 INV-6 守卫判为旁路写

**最重要的一条。** `server/tests/delivery/test_blueprint_inv6_guard.py` 扫**整个 `server/`**（`_iter_py_files:68-75`，只剪 venv/缓存），豁免只有三项：唯一 writer `delivery/services/blueprint_lifecycle_service.py`（`:39`）、`tests/`、`migrations/`（`_is_scanned:78-91`）。

三条字段级正则（`:56-62`）：

```python
_RE_FIELD_WRITE     = re.compile(r"\bblueprint_status\s*=\s*[^=]")          # :57
_RE_FIELD_SETATTR   = re.compile(r"setattr\([^,]+,\s*['\"]blueprint_status['\"]")  # :60
_RE_FIELD_DICT_KEY  = re.compile(r"['\"]blueprint_status['\"]\s*:")         # :61
```

唯一逐行豁免是字段定义行 `blueprint_status = models.*`（`_RE_FIELD_DEFINITION:65`，`:139-140`）。

**UI-SPEC §3.3 的列表端点契约同时踩中前两条：**

| 写法 | 命中 | 后果 |
|------|------|------|
| `Artifact.objects.filter(blueprint_status=value)` | `_RE_FIELD_WRITE` | `test_inv6_no_bypass_blueprint_status_field_write` **转红** |
| 响应体 `{"blueprint_status": …}`（UI-SPEC §3.3 的 `BlueprintListItem` 键名） | `_RE_FIELD_DICT_KEY` | 同上 |
| `request.query_params.get("blueprint_status")` | **不命中**（后面既无 `=` 也无 `:`） | 安全，query 参数名可以保留 |
| `if artifact.blueprint_status == X` | 不命中（`[^=]` 排除比较） | 安全 |

守卫的 docstring（`:9-11`）明说这是**有意的**：「``filter(blueprint_status=...)`` 条件——后者虽是读路径，但出现在 writer 之外通常……」。STATE 也立了纪律：「**绝不为迁就命名去豁免守卫**」（Phase 114-05 条目）。

**114-05 的既有解法可直接抄**：`aapprove_blueprint` / `areject_blueprint` 的返回键从 `blueprint_status` **改名 `current_status`**（`114-05-SUMMARY.md` Fix #5 逐字记录了理由）。

⇒ **PLAN 必须写死两条**：
- 列表端点响应键用 **`current_status`**（不是 `blueprint_status`），并同步订正 UI-SPEC §3.3 的 TS 接口与前端消费点；
- ORM 过滤**不能出现字面 `blueprint_status=`**。可行写法：模块常量 `_STATUS_FIELD = "blueprint_status"`（这一行两条正则都不命中：`blueprint_status` 后面是 `"` 不是 `=` 或 `:`）+ `queryset.filter(**{_STATUS_FIELD: value})`。PLAN 要在该常量处写注释说明为何绕这一圈，否则后人会「顺手改直白」再把测试搞红。

### P-2 ⛔ 列表端点若同时出现 `aunresolved_blocker_count` 与 `BlueprintStatus.CONFIRMED` ⇒ TOCTOU 守卫转红

`server/tests/delivery/test_blueprint_review_threads.py:365-392` 扫 **`delivery/api/` 整个目录**（`:370`）：任一 `.py` 文件只要**同时**含字符串 `aunresolved_blocker_count` 与（`BlueprintStatus.CONFIRMED` 或 `to_status="confirmed"`），即判为「事务外先查 BLOCKER 再 transition」。

本相位的真实撞车路径：列表端点要出 `unresolved_blocker_count`（UI-SPEC §3.3），若为省事 `from delivery.services.blueprint_lifecycle_service import ...aunresolved_blocker_count`，同时又在同一文件里为 `?blueprint_status=` 校验或 quality 面板条件写了 `BlueprintStatus.CONFIRMED` —— 红。

**规避**：列表端点用 ORM `annotate(Count(...))` 自算计数（本来就该这样，逐条调 async 函数是 N+1），不 import 那个符号。

### P-3 ⛔ `chunk-at` 的「无命中」是 200 而不是错误 —— UI-SPEC 的兜底判据漏了它

`repositories/chunk_at_views.py:56-60`：被排除文件与无命中**统一返回 200 `{"chunks": []}`**，刻意不可区分（T-25-05 存在性泄露防线）。

UI-SPEC §10.1 把兜底判据定为「任何非 2xx」⇒ 这一档落不进兜底，`CitationCodePreview` 会渲染一个**空的代码区**而不是 citation 快照。而这恰恰是**最常见**的一档（文件被 exclusion 规则排除、chunk 未回填行号、分支名不匹配都会走到这里）。

**正确判据**：`!ok || chunks.length === 0` 一律走兜底。

**次生问题**：`chunks[]` 只有 `{chunk_id, file_path, line_start, line_end, chunk_index}`（`services/chunk_lookup.py:49`），**没有源码正文**。UI-SPEC §10.1 承诺的「CodeMirror 只读 + 行高亮」缺一个取正文的读面 —— PLAN 必须先定夺（找端点 / 降级为「路径 + 行号 + `quote` 快照」）。

### P-4 ⛔ `AnchorNavLayout` 只在 mount 时观察 —— 异步渲染的十段一个也观察不到

`components/layout/AnchorNavLayout.vue:19-40`：`onMounted` 里遍历 `props.sections` 逐个 `document.getElementById`；无 `watch(() => props.sections)`、无 `MutationObserver`。

蓝图正文由 TanStack Query 异步取回。若各段写成 `<section v-if="doc" id="repo_associations">`，mount 那一刻 DOM 里一个都没有 ⇒ `observer.observe` 一次都不执行 ⇒ **左栏高亮永远停在第一段，且 badge tone 的"当前段"逻辑失效**；而点击跳转**照常工作**（`scrollTo:47` 是点击时才 `getElementById`）—— 所以人肉自测会觉得「只是高亮有点怪」，不会当成 bug。

既有先例已经踩过弱化版：`pages/knowledge/entities/[id].vue:149-153` 的第 4 段是 `v-if="showAssociations"`，永不被观察。

**两条可行修法**（PLAN 择一）：

1. **段容器无条件渲染**：`<section id="repo_associations">` 始终存在，只有内部内容随 `doc` 变化（骨架 → 实渲 → 空态）。这与 UI-SPEC §8.1「按段渲染骨架屏、增量填充」**天然一致** —— 骨架本来就要在段容器里。**推荐**。
2. 用 `v-if` 延迟整个 `AnchorNavLayout` 的挂载（`<AnchorNavLayout v-if="doc" :sections="…">`），代价是首屏骨架期左栏空白，与 UI-SPEC §8.1 的「左栏 10 条 `Skeleton h-8`」冲突。

UI-SPEC §6.9 又要求「`must_haves` 三个子块全空时整段与导航项**都不渲染**」、§6.1 说 `decision_log` 是 optional —— 这意味着 `sections` 数组**长度会变**。配合修法 1，`sections` 变化时新段的 DOM 存在但 observer 没挂上。**PLAN 应要求新页面自己补一个 `watch(() => sections.value.map(s => s.id).join(), …)` 的重挂逻辑，或干脆让十段全部无条件渲染、由段内部决定是否出内容。** 后者更简单，且 UI-SPEC 的「不渲染空态卡」可以退化成「段容器高度为 0」。

### P-5 ⛔ `getArtifactAssociations` / `getRelated` 对蓝图 artifact_id 必然 404

UI-SPEC §3.6 / §10.2 把「关联」区建在 `knowledgeApi.getRelated` + `knowledgeApi.getArtifactAssociations` 上。实读：

- `server/knowledge/artifact_associations.py:75`：`entity_id = generate_entity_id(EntityKind.DOCUMENT, "artifact", str(artifact_id))`，随后 `KnowledgeEntity.objects.filter(id=entity_id).afirst()`；取不到 → `return None` → 端点 **404**（`knowledge/api/artifact_associations.py:46-47`）。
- 谁往图谱里投影 `("artifact", id)` 实体？只有 `server/knowledge/sources/artifact.py` 与 `server/initiatives/services/artifact_service.py` —— 两者操作的都是 **`initiatives.Artifact`**（项目工件），不是 `delivery.Artifact`（蓝图所在的模型）。
- `knowledgeApi.getRelated(id)`（`web/src/api/knowledge.ts:193`）打的是 `/knowledge/related/<entity_id>/` —— 入参是 **KnowledgeEntity id**，不是任何 artifact id。

⇒ 拿蓝图的 `delivery.Artifact.id` 去调这两个，**永远 404 / 空**。而「知识图谱物化」明确是 **Phase 116** 的事（ROADMAP:42 「MCP 异步澄清协议 + 全入口统一走蓝图编排 + 飞书导出升级 + **知识图谱物化** + 触点升级」）。

**PLAN 必须定夺**：`associations` 段（UI-SPEC §6.1 第 9 项 + §10.2）本相位只能兑现**两块**——「本蓝图引用了」（`content.citations` 引用池，纯前端聚合，零端点）与「关联项目」（`meta.project_id` + `RouterLink`）；「引用了本蓝图 / 关联知识」这一块**要么顺延 116，要么改成基于 `citations[].source_type ∈ {blueprint, artifact_version}` 的反向扫描**（但那需要跨蓝图查询，超出本相位读面）。SC-4 的「蓝图互引与知识关联双向可查」因此**在本相位只能部分兑现** —— 这是必须显式登记的范围收窄，不能靠 404 兜底糊过去。

### P-6 ⛔ `CompactEmptyState` 的 `icon` prop 在仓内被两种互斥写法混用

`web/src/components/common/CompactEmptyState.vue`：`withDefaults(defineProps<{icon?: string}>(), { icon: 'lucide--inbox' })`，模板 `:class="\`icon-[${icon}]\`"` ⇒ **期望裸图标名**。

实测调用点分成两派：

- 传裸名（正确，11 处）：`repositories/[id]/index.vue:498,591`、`WorkItemsTab.vue:131`、`ProjectGalaxyCard.vue:152`、`KnowledgeDashboard.vue:699`、`EntityAssociationsCard.vue:76`、`FeatureBoard.vue:168`、`BatchIngestPanel.vue:304`、`DeliveryDocsTree.vue:177,200,232`、`ContextLinksCard.vue:295`、`ProjectApiListCard.vue:129`
- 传完整类名（**渲染成 `icon-[icon-[lucide--x]]`，图标出不来**，4 处）：`pages/knowledge/entities/[id].vue:105`、`pages/knowledge/index.vue:309,317`、`KnowledgeDashboard.vue:424`

UI-SPEC §6.1 / §8.2 / §12.1 都写「传裸名」—— **判断正确**，但 planner 要知道：新页面若照抄 `pages/knowledge/index.vue`（它就在同一目录、是 tab 宿主）**会抄到错的那一派**。

另一条：`entities/[id].vue:107-108` 给它传了 `:action-label` 与 `@action` —— **`CompactEmptyState` 既无该 prop 也无该 emit**（它只有默认 slot）。UI-SPEC §8.2 的 404 全页空态「+「返回知识库」按钮」**必须用默认 slot**：

```vue
<CompactEmptyState icon="lucide--lock" :title="…"><Button …>返回知识库</Button></CompactEmptyState>
```

safelist 已含 `icon-[lucide--lock]` / `icon-[lucide--file-x]` / `icon-[lucide--file-text]`（`web/src/styles/main.css:13`），UI-SPEC 的引用正确。

### P-7 ⛔ 「无 anchor」≠「失锚」≠「offset 越界」—— 三态别混

三个不同来源，UI-SPEC §7.3 / §7.7 已分清，但极易在实现时合并：

| 态 | 判定方 | 数据源 | 正文呈现 | 侧栏归属 |
|---|-------|-------|---------|---------|
| **anchored + offset 合法** | 前端 | `threads/` | `<mark>` 字符区间 | 按 `status` 三组 |
| **anchored + offset 越界/块类型不支持** | **前端** | `threads/` | 整块左侧色条 | 按 `status` 三组（**不是失锚组**） |
| **orphaned** | **后端** `areanchor_threads` | 快照 `orphaned_threads` | **完全不渲染** | 失锚组（第四组，不看 `status`） |

`ThreadAnchorStatus` 只有两个值（`models/blueprint_thread.py:22-26`：`anchored` / `orphaned`），没有第三态 —— 越界完全是前端概念。

⚠️ 且「无 anchor 的系统线程」（`anchor` 为 `null`，模型 `:84` 允许）**既不是 anchored 显示也不是 orphaned**：114-REVIEW MJ-02 让批量重锚对无定位线程判 `skipped` 并**保持 `anchor_status` 原值**（多为 `anchored` 默认值，`:88`）。⇒ 前端会拿到一批 `anchor_status === 'anchored'` 但 `anchor === null` 的线程（规格门 / 确认门 / 无划线的驳回评论）。**它们必须出现在侧栏（按 status 分组）但正文无任何标记** —— UI-SPEC §7.1 第 1 步的过滤（「只取 `anchor.block_id === block.block_id`」）自然把它们排除出正文，但**侧栏分组的四条判据不能把它们漏掉**。UI-SPEC §7.7 的四组判据（三组 `status ∧ ¬orphaned` + 一组 `orphaned`）对它们是覆盖的 ✅，但 §20 断言 11「四组条目总数 == 线程总数」的测试数据里**要包含这一类**，否则测不出。

### P-8 事件 payload 的键零 schema 保证 —— 进度文案必须每键有缺省

`ConvergenceSessionEvent.payload` 是自由 `JSONField`（`models/convergence_session_event.py:39`）。UI-SPEC §8.1 的 21 行进度文案插值了十个 payload 键。这些键由各 emit 点自行写入，`event_taxonomy.py:141-183` 的注释记了各自的**预期**键，但**无任何运行期校验**。

⇒ `t('...progress.repoResearchStarted', { repository_name: e.payload.repository_name })` 在键缺失时会渲染成 `正在调研 undefined…`（vue-i18n 对缺失参数不抛错）。每处插值都要 `?? ''` 或走「有键用具名文案、无键用通用文案」的二分支。

### P-9 状态驱动轮询的一拍延迟：用 `computed` 会比用函数慢一轮

UI-SPEC §8.3 的写法是 `refetchInterval: computed(() => isLive(currentStatus.value) ? 5000 : false)`，而 `currentStatus` 来自**另一个 query 的 data**。当蓝图从 `ai_reviewing` 进入 `pending_review` 时：本轮 refetch 拿回新状态 → computed 重算 → 停轮询。这是对的。反向（进入 live 态）也对。

真正的坑在**初次挂载**：三个 query 并行发起，`currentStatus` 在第一次响应回来前是 `undefined` ⇒ `isLive === false` ⇒ `refetchInterval = false`。TanStack Query 的 `refetchInterval` 是响应式的，值变化会重启定时器，所以**最终会启动** —— 但若把 `refetchInterval` 写成**非响应式的普通值**（在 setup 里 `const interval = isLive.value ? 5000 : false`），就会永久停在 `false`，**生成中的蓝图永远不刷新，而页面看起来完全正常**（首屏有内容、无报错）。这是一个典型的静默假通过。

既有 10 处 `refetchInterval` **全部用函数式**（`query => …`），函数式天然响应式且能读到 `query.state.data` 最新值。**PLAN 应写死用函数式**并把「首屏 → live 态能自动起转」列成断言（可用 fake timers + 两次 mock 响应）。

另一条：UI-SPEC §8.3 说「页面不可见时暂停：`useDocumentVisibility()` 为 `hidden` 时 `refetchInterval = false`」。TanStack Query 有内建的 `refetchIntervalInBackground: false`（默认即 false）⇒ **这条是重复造轮子**。仓内 10 处先例都没写可见性判断。建议删掉这条，靠默认行为。

### P-10 `blueprint-gate/` 没有项目范围闸 —— 前端不得据其 404 做权限推断

见 §A.5。`blueprint_gate_views.py` 里 `_ablueprint_project_id`（`:511`）**只在 `BlueprintRejectedToBoundaryView`（`:385`）用了一次**，八个 gate 端点的其余七个只有 `IsAuthenticated`。

UI-SPEC §8.2 例外一的**结论**（gate 非 200 ⇒ 只决定面板是否渲染，不进错误分档）正确，但理由要改成：**gate 的 404 混合了「门未开」「artifact 不存在」「无蓝图会话」三种语义，且该链无成员闸 ⇒ 它的状态码不携带任何权限信息**。页面的权限判定必须由**四个主查询**（正文 / 快照 / threads / events，全部有闸）承担。

（这是一处既有后端缺口。本相位边界是「只加读面」，不修它；但 PLAN 应把它记进 STATE 的 Pending Todos，避免被当成本相位引入的问题。）

### P-11 `PromptVersionDiff` 的颜色令牌是 `scoped` —— 「沿用」= 重写一遍

`PromptVersionDiff.vue:119-137` 的 `.diff-added` / `.diff-removed` / `.diff-unchanged` 在 `<style scoped>` 里。UI-SPEC §9.2「颜色 … **逐字沿用 `PromptVersionDiff.vue`**」在实现上意味着**把三条规则原样复制进新组件的 scoped style**。不存在可 import 的共享令牌。别让执行者去找。

（同理 UI-SPEC §15「Phase-Local 语义色 … 复用 `PromptVersionDiff.vue` 的 `.diff-*`」也要按「复制」理解。）

### P-12 `MermaidDiagram` 的 prop 是 `code`，空源码不自处理，放大层是 vue-final-modal

见 §B.3 表。三条各自都会导致一个具体错误：写 `:source=` 传不进去（Vue 不报错，只是渲染空 `<pre>`）；不 `v-if` 空源码会出一个空框；在 reka-ui `Dialog` 里点放大会出现两套模态栈叠放。

### P-13 前端 `blockText()` 必须复刻 `_block_text` 的**四分支优先级**，不能按 `block.type` 分派

后端取文本口径实读见 §B.1（`server/delivery/services/blueprint_anchor.py:34-64`）。`list` 的 `\n` 连接符**已验证与 UI-SPEC 一致**，A4 解除。剩下的真实风险是**分派方式**：

`_block_text` 按 **`text` → `code.source` → `rows`** 的字段优先级取，**完全不看 `block.type`**。前端若按 `type` 分派（`type === 'pseudocode' ? code.source : text`），对一个「`type: pseudocode` 且 `text` 非空」的块就会得到与后端不同的坐标系 —— 而 schema 对 `text`（`blueprint_schema.py:63-65`）**没有任何类型约束**（`"text": {"description": …}`，无 `type` 键），这种块完全合法。

坐标系不一致的后果是本相位最难被逮到的一类错：offset 偏移后**仍在合法范围内** ⇒ 不触发越界降级、不报错、`<mark>` 照渲，只是**圈错了字**。

**PLAN 要求**：前端 `blockText(block)` 逐字复刻四分支（含 `str(item)` 的字符串化与「非空才取」的判定），并落一条「同一 fixture block 前后端取文本结果一致」的断言 —— 后端期望值手抄进 fixture。

### P-14 `decision_log` / `deferred_ideas` 是**零约束裸 array**，且同样不在 `iter_blocks` 里

UI-SPEC §6.9 只为 `must_haves` 写了「不接批注层」的例外。实读三处确认它们该同款处理：

```python
# blueprint_schema.py:733-744 —— 三个可选段全是无 items 约束的裸 array
"decision_log":  {"type": "array", "description": "已解决澄清线程的决策快照（可选；DESIGN §3.13）"}
"deferred_ideas":{"type": "array", "description": "scope 外想法（可选，防扩 scope）"}
"execution_plan":{"type": "array", "description": "确认后确定性派生的执行计划段（可选…）"}
```

- 三者均**不在顶层 `required`**（`:123-135` 十一键，不含它们）。
- `iter_blocks`（`:919-1036`）对三者**零 `collect` 调用** ⇒ 后端锚定走查永远看不到它们内部的任何 `block_id` ⇒ **后端不会往那里挂线程**。
- 条目形状**零 schema 约束** ⇒ 运行期是什么都有可能（114-04 的 `decision_log` 物化写入 `{thread_id, question, answer, decision, decided_by, decided_at, applied_in_version}` 是**约定不是契约**）。

⇒ 两条对 PLAN 的要求：

1. `DecisionLogSection.vue` **不接批注层**（UI-SPEC §13.3 给它派的 `emits: ['open-thread']` 是死码，除非它只用于「跳转到该决策对应的线程」这一层语义 —— PLAN 要澄清这个 emit 到底是哪个意思）。
2. 三段的所有字段访问**逐项 `.get` / 可选链防御**，缺键渲染成「—」而不是 `undefined`。特别是 114-04 明确保留的 `answer` 键（STATE 有专条）——它是唯一有下游消费方的键。

### P-15 `blueprint_quality` 后三项是同步函数 + 内部 ORM

见 §A.1。在 adrf 异步 View 里直接调 ⇒ `SynchronousOnlyOperation`。它们内部的 `try/except`（`:150,172,196`）**只兜 ORM 异常，不兜异步上下文错误**（那是在函数调用点抛的）—— 所以不会被吞成 `None`，会直接 500。必须 `sync_to_async`。

### P-16 新蓝图模块要加进两个守卫清单

- `server/tests/delivery/test_blueprint_log_redaction_guard.py:27-37` 的 `_SCANNED_MODULES`（该文件 `:14` docstring 明写「新增蓝图模块请一并加进」）。
- （若新建 service）`test_blueprint_inv6_guard.py` 的 `_ALLOWED_WRITER` **不要加** —— 唯一 writer 必须保持是 `blueprint_lifecycle_service.py`。新 service 走它。

### P-17 `ProjectMaterialsPanel` 已有 `ArtifactTimeline`，新卡会与它条目重叠

见 §B.8。蓝图与旧 technical_plan 共用 `artifact_type="technical_plan"`。新卡按 `blueprint_status != ""` 过滤即可分开，但**面板上会出现两块内容相近的区域** —— 文案需明确区分，并考虑排序位置（建议新卡放在 `ArtifactTimeline` 之前，蓝图是更新的形态）。

### P-18 `AnchorNavLayout` 的 badge 会把 `0` 渲染出来

`:95` 的空值判定不排除 `0`。UI-SPEC §6.1 说 badge 是「该段锚定线程总数」—— 零批注的段会显示一个灰 `0`。UI-SPEC §16 对顶栏「批注 {n}」明确规定 `n === 0` 时不显示 0，导航 badge 应同口径 ⇒ **传 `''` 而不是 `0`**。

---

## Part D —— 可复用件速查（全部实读确认存在）

| 用途 | 符号 / 路径 | 关键契约 |
|------|------------|---------|
| 项目范围闸 | `delivery/api/blueprint_review_views.py:254` `_aassert_project_scope` | superuser 直通 / 无 `meta.project_id` → 400 / 非成员 → 中性 404 |
| 取最新 content | 同上 `:162` `_alatest_content` | `order_by("-version_no").afirst()`，非 dict 回 `{}` |
| 取蓝图会话 | 同上 `:106` `_aload_session` | **必带 `process_type=BLUEPRINT_PROCESS_TYPE`** |
| 端点 caller 埋点 | 同上 `:284` `_log` | `category` / `component` / `artifact_id` / `initiated_by_user_id` / `duration_ms` |
| 可编辑白名单 | `delivery/services/blueprint_lifecycle_service.py` `is_blueprint_editable` / `EDITABLE_BLUEPRINT_STATUSES` / `NOT_EDITABLE_DETAIL` | 含 `""`（v0 兼容） |
| 开线程唯一入口 | 同上 `:365` `open_thread` | 线程行 + 首条消息同事务 |
| 21 个蓝图事件 | `delivery/services/event_taxonomy.py:185` `BLUEPRINT_EVENTS` | frozenset，`len == 21` 有测试锁 |
| block 走查 | `services/process_runtime/blueprint_schema.py:919` `iter_blocks` | 13 处 `collect`，`section_path` = 点分 + `[标识]` |
| block diff | 同上 `:1045` `diff_blueprint_blocks` | canonical `json.dumps(sort_keys=True)` |
| 引用覆盖率 | `services/process_runtime/blueprint_quality.py:68` | 纯函数，分母 0 → 1.0 |
| 三项 DB 统计 | 同上 `:127` / `:157` / `:182` | **同步函数**，无数据 → `None` |
| 异步分页范式 | `knowledge/api/artifact_overview.py:46,54,160` | `_parse_page` / `_parse_page_size` clamp `[1,100]` + `{total,items,page,page_size,has_next}` |
| 版本轨（前端） | `web/src/api/deliveryArtifacts.ts` `getArtifactTimeline` | `ArtifactTimeline` 含 `versions[]`（`version_no` / `produced_by_ref` / `supersedes_id` / `is_current`） |
| API 错误 | `web/src/api/client.ts:18` `ApiError` | `status` / `detail`（缺省 `'请求失败'`）/ `body`（完整 JSON） |
| 404 判定先例 | `web/src/pages/knowledge/entities/[id].vue:93` | `err instanceof ApiError && err.status === 404` |
| 段导航布局 | `web/src/components/layout/AnchorNavLayout.vue` | `NavSection` 接口导出；两栏容器；偏移 88；**mount 时一次性观察**（P-4） |
| 页面标题 | 同上 `:4,87` `useHead` from `@vueuse/head` | ⛔ 不用 `definePage({meta:{title}})`（`layouts/default.vue:21-25` 原样渲染，不过 `t()`） |
| diff 范式 | `web/src/components/prompts/PromptVersionDiff.vue` | `shallowRef<Change[]>`；`.diff-*` 是 **scoped**（P-11） |
| mermaid | `web/src/components/project/warroom/MermaidDiagram.vue` | prop 名 **`code`**；自动回退源码；放大用 vue-final-modal（P-12） |
| 空态 | `web/src/components/common/CompactEmptyState.vue` | `icon` 传**裸名**；无 `action-label`/`@action`，用默认 slot（P-6） |
| 二次确认 | `web/src/composables/useConfirmDialog.ts` | `confirm({title,description,confirmText,cancelText,variant})` → `Promise<boolean>`；全局单例状态 |
| Badge 变体 | `web/src/components/ui/badge/index.ts` | `default/secondary/destructive/outline/success/warning/info/muted` —— UI-SPEC 用到的全都有 |
| 状态配置类型 | `web/src/config/status.ts:1` `StatusConfig` | `{label, icon, variant, animate?}`；`getStatusConfig:88` 的 `type` 联合是既有面（新增走新模块） |
| tab 宿主 | `web/src/pages/knowledge/index.vue:40,41,220,236` | 五处纯追加点；`?tab=` 同步保留其它 query |
| 物料面板 | `web/src/components/project/warroom/ProjectMaterialsPanel.vue:27-30,52` | `defineAsyncComponent` + `hide-when-empty` prop 范式 |
| UI 原语 | `web/src/components/ui/` | UI-SPEC §21 列的 17 个原语**全部存在**（dialog/sheet/skeleton/tabs/badge/popover/tooltip/scroll-area/table/pagination/select/input/textarea/button/collapsible/separator/alert-dialog）✅ |
| 前端测试 | `web/vitest.config.ts` + `web/src/test/setup.ts` + `pages/knowledge/__tests__/entity-detail.spec.ts` | happy-dom；setup 只有 storage 垫片；页面测试范式见 §B.10 |

**新增运行时依赖：零。** `mermaid@^11.16.0`（`package.json:90`）/ `diff`（`:78`）/ `@floating-ui/vue@^1.1.11`（`:34`）/ `codemirror`（`:76`）/ `@tanstack/vue-query`（`:39`）/ `@vueuse/head`（`:73`）全部已在 `web/package.json`。

---

## Confidence 与残留不确定项

| 面 | 级别 | 依据 |
|----|------|------|
| 五个端点的必要性与形状 | **HIGH** | 逐条实读 views / urls / models / schema，五条主张全部坐实 |
| 后端守卫（P-1 / P-2 / P-16） | **HIGH** | 三条正则与两个扫描测试全文实读，正则形态可手工验算 |
| `chunk-at` / `getArtifactAssociations` 的行为（P-3 / P-5） | **HIGH** | View + service 全文实读，含 docstring 的意图声明 |
| `AnchorNavLayout` / `CompactEmptyState` / `MermaidDiagram` 契约（P-4 / P-6 / P-12） | **HIGH** | 三个组件全文实读（110 / 33 / 103 行） |
| TanStack Query 惯例 | **HIGH** | 10 处 `refetchInterval` + 4 处 queryKey 先例实读 |
| 前端测试可达上界 | **HIGH** | vitest 配置 + setup + 唯一页面级范式全文实读 |
| `@floating-ui/vue` 的 API 形状 | **MEDIUM** `[ASSUMED]` | 依赖已声明（`package.json:34` / lock `1.1.11`）但**仓内零调用点**且本 worktree 无 `node_modules`，无法实跑。`useFloating(ref, floating, opts) → {floatingStyles,…}` 来自训练知识 |
| happy-dom 对 `Range` / `TreeWalker` / `IntersectionObserver` 的支持度 | **LOW** `[ASSUMED]` | 未实跑；直接影响 §B.2 与 P-4 的可测性。**Wave 0 应先跑一次探针测试确认** |
| `diffWords` 的返回形状 | **MEDIUM** `[ASSUMED]` | 同包（`diff`）的 `diffLines` 已在仓内使用并有 `Change[]` 类型；`diffWords` 同族 API 但仓内零使用 |
| `decision_log` / `deferred_ideas` / `execution_plan` 的形状 | **HIGH** | `blueprint_schema.py:733-744` 实读：三者都是**零 items 约束的裸 array**、都不在顶层 `required`、都不在 `iter_blocks`（P-14） |
| `_block_text` 的取文本口径 | **HIGH** | `delivery/services/blueprint_anchor.py:34-64` 全文实读；`list` 的 `\n` 连接确认与 UI-SPEC 一致，真实风险转为「分派方式」（P-13） |

**Assumptions Log（需 PLAN 或执行期确认，不得当既定事实）**

| # | 假设 | 出处 | 错了会怎样 |
|---|------|------|-----------|
| A1 | `@floating-ui/vue` 的 `useFloating` 返回 `{floatingStyles, placement, middlewareData, update}` | 训练知识 | 选区 popover 定位写法要重来（有 reka-ui `PopoverAnchor` 兜底） |
| A2 | happy-dom 支持 `document.createTreeWalker` 与 `Range.getBoundingClientRect` | 训练知识 | §B.2 的 offset 函数无法单测，要改成更纯的签名 |
| A3 | `diffWords` 返回与 `diffLines` 同构的 `Change[]`（`{value, added?, removed?, count}`） | 同包类推 | diff 渲染层要调整 |
| ~~A4~~ | ~~`list` 块的后端取文本用 `"\n".join(items)`~~ | **已实读证实**（`blueprint_anchor.py:47`），假设解除 | —— |

---

## 给 PLAN 的五条硬要求（不写进去执行期必踩）

1. **列表端点响应键用 `current_status`、ORM 过滤不出现字面 `blueprint_status=`**（P-1），并同步订正 UI-SPEC §3.3 的 TS 接口。
2. **`chunk-at` 兜底判据改为 `!ok || chunks.length === 0`**，且先定夺「代码正文从哪来」（P-3）。
3. **十段的 `<section id>` 容器无条件渲染**（骨架/空态在容器内），否则 `AnchorNavLayout` 的高亮全程失效（P-4）。
4. **`associations` 段本相位只做「本蓝图引用了」+「关联项目」两块**，「引用了本蓝图 / 关联知识」顺延 116 并显式登记 SC-4 的范围收窄（P-5）。
5. **前端 `blockText()` 按 `text → code.source → rows` 的字段优先级实现（不按 `block.type` 分派）**，并落一条前后端取文本一致性断言（P-13）。
