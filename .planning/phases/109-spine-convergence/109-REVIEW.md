---
phase: 109-spine-convergence
reviewed: 2026-07-31T01:50:00Z
status: findings
depth: standard
diff_base: 256899d5
branch: milestone/v0.19.0-plan-trust
files_reviewed: 22
findings:
  blocker: 1
  high: 2
  medium: 6
  low: 5
tests_executed:
  backend: "140 passed（tests/test_coding_tools + test_plan_projection_service + test_plan_projection_api + test_coding_session_service + test_spa_coding_chain_e2e + tests/agents/test_coding_tools_schema_guard + tests/mcp_tools/test_bridge_session + test_coding_plan_exporter）"
  frontend: "115 passed（OrchestratedPlanCard.spec + TechPlanCard.spec + chatMessageBubble.parts.spec + useToolDisplay.spec）；vue-tsc --noEmit 通过"
  lint: "ruff check / ruff format 的全部告警均落在本 phase 未触及的既有代码（chat/services.py、migrations/0014、coding_session_service.py 旧段），109 新增代码零告警"
  probes: "① 按中间件真实绑定（user_id=\"system\"）调 agents.tools.coding_tools._context_user_id() → 返回 ''（BL-01 实测）；② Repository.objects.filter(id__in=['not-a-uuid']) → ValidationError（MN-03 实测）"
files_reviewed_list:
  - server/agents/intent_router.py
  - server/agents/tools/chat_tools.py
  - server/agents/tools/coding_tools.py
  - server/agents/tools/repository_relevance.py
  - server/chat/coding_session_service.py
  - server/chat/config.py
  - server/chat/conversation_service.py
  - server/chat/migrations/0033_codingplan_provenance_and_source.py
  - server/chat/models.py
  - server/chat/plan_projection_service.py
  - server/chat/serializers.py
  - server/chat/urls.py
  - server/chat/views.py
  - server/feishu/cards/bot_cards.py
  - server/feishu/coding_plan_exporter.py
  - web/src/api/chat.ts
  - web/src/components.d.ts
  - web/src/components/chat/ChatMessageBubble.vue
  - web/src/components/chat/OrchestratedPlanCard.vue
  - web/src/components/chat/TechPlanCard.vue
  - web/src/composables/useToolDisplay.ts
  - web/src/stores/chat.ts
findings_index:
  - id: BL-01
    severity: BLOCKER
    origin: new
    file: server/agents/tools/coding_tools.py:433
    summary: update_coding_plan 在生产恒失败——归属主体只取 contextvars user_id，而全仓无任何视图挂 LogContextMixin，该值永远是 "system" 并被 helper 归一为空串
  - id: HI-01
    severity: HIGH
    origin: new
    file: web/src/components/chat/OrchestratedPlanCard.vue:142
    summary: 内嵌 TechPlanCard 未传 available-repositories，「进入编码」后的选仓面为空（"未找到匹配的仓库"），SC-1 第一步在界面上不可用；测试用 stub 掩盖
  - id: HI-02
    severity: HIGH
    origin: new
    file: web/src/components/chat/ChatMessageBubble.vue:1206
    summary: SPINE-02 后非最新 plan 的方案卡正文与 provenance 双双取不到——旧卡显示「（暂无方案正文）」并被误挂「未经代码调研」横幅
  - id: MN-01
    severity: MEDIUM
    origin: new
    file: server/mcp_tools/execution_service.py:109
    summary: MCP 桥接建的 chat CodingPlan 落 provenance=draft，编排产出被误标「未经代码调研」，且 dispatch payload 的 unresearched 恒 true
  - id: MN-02
    severity: MEDIUM
    origin: new
    file: server/chat/plan_projection_service.py:466
    summary: arebind 非原子——aupdate_plan 先写正文，随后 asave 失败会留下「正文来自新版本、来源指针仍指旧版本」的混合态，且对用户报失败
  - id: MN-03
    severity: MEDIUM
    origin: new
    file: server/agents/tools/coding_tools.py:321
    summary: projected 分支把半可信 LLM 产出的 repository_id 直接喂 UUID 查询，非法字面量抛 ValidationError（已实测），投影已落库却报工具失败
  - id: MN-04
    severity: MEDIUM
    origin: new
    file: server/agents/tools/coding_tools.py:467
    summary: legacy session_id 分支在归属判定之前就建 CodingPlan 并改写他人 CodingSession.coding_plan FK（write-before-authz），当前被 BL-01 挡住、修完即活
  - id: MN-05
    severity: MEDIUM
    origin: pre-existing-newly-load-bearing
    file: web/src/components/chat/TechPlanCard.vue:106
    summary: sessions / hasSessions / existingActiveRepoIds / visibleTargetRepositories 消费 runtime.coding_plan 但无 plan_id 守卫，投影后轮询窗口内内嵌卡片会显示别的 plan 的 session 行
  - id: MN-06
    severity: MEDIUM
    origin: new
    file: server/chat/coding_session_service.py:95
    summary: 草稿 gate 的确认/拒绝留痕 user_id 恒为 system，RELY-01 想立的「谁用草稿送了编码」不可追溯（与 BL-01 同根因）
  - id: LO-01
    severity: LOW
    origin: new
    file: web/src/components/chat/TechPlanCard.vue:395
    summary: gate 拒绝后重开的弹层其 promise 无人 await，用户重新勾选并确认后什么都不会发生（死胡同）
  - id: LO-02
    severity: LOW
    origin: new
    file: web/src/components/chat/ChatMessageBubble.vue:791
    summary: orchestratedPlanData 用 toolCalls.find，同消息内两次编排工具调用时两张卡片都拿第一次的 artifact_version_id
  - id: LO-03
    severity: LOW
    origin: new
    file: server/agents/tools/coding_tools.py:293
    summary: create_coding_plan 的 conversation_id 已不决定投影落点却仍必填且不校验一致性，跨会话 artifact 会把 plan 建到别的会话下
  - id: LO-04
    severity: LOW
    origin: new
    file: server/feishu/coding_plan_exporter.py:46
    summary: _DRAFT_NOTICE 插在 _STATUS_LABEL 的注释块与定义之间，注释与它描述的常量被隔开
  - id: LO-05
    severity: LOW
    origin: new
    file: .planning/ROADMAP.md
    summary: ROADMAP 与 109-02 仍写「条件唯一约束」，实现是无条件唯一约束（实现的理由是对的，文档没跟上）
---

# Phase 109: 代码评审报告

**评审范围:** `256899d5..HEAD` 中 `server/` 与 `web/` 的 22 个在册源码文件（另核对 15 个新增/改动测试文件与 4 个被牵连的既有模块）
**深度:** standard（逐文件 + 消费方追踪 + 两处运行时实测 + 实跑后端 140 / 前端 115 条相关用例）
**结论:** `findings` —— 1 个 BLOCKER、2 个 HIGH、6 个 MEDIUM、5 个 LOW

## 摘要

**先说做对的部分（这些是本 phase 最容易做坏而实际做对了的地方）：**

- **SPINE-02 的「结构上不可能」是真的成立。** `create_coding_plan` / `update_coding_plan` 两个门都收窄了，`tech_plan` / `affected_files` 在 **schema 与函数签名两侧**都不存在（`test_coding_tools_schema_guard.py` 用具名否定断言 + `properties` 键集合枚举相等断言双保险，后者能挡住「换个名字的正文入参」）。我另行 grep 了全部替代写路径：`aget_or_create_for_conversation` 的生产调用方只剩迁移命令与 `update_coding_plan` 的 legacy 补 FK 分支（正文取自 session 既有值，不是模型入参）；`aupdate_plan` 的唯一生产调用方是 `plan_projection_service.arebind`；`CodingPlan.objects.create` 的唯一生产调用方是 MCP 桥接。**没有留下第二个徒手创作口子。**
- **MCP 桥接零回归成立（字段形状层面）。** 新增两列都带 default，裸 `objects.create()` 不崩，唯一约束因 `source_artifact_version_id` 为 NULL 而不阻塞重复桥接（`test_bridge_session.py` 三条用例都覆盖了，含「连建两次不被唯一约束拦」）。但**语义层面被误标**，见 MN-01。
- **唯一约束刻意不带 `condition=` 这个判断是对的，而且理由写对了。** `models.py:311-325` 的注释说明：带 `condition` 时 `_unique_supported()` 会因 MySQL `supports_partial_indexes = False` 而**静默跳过** `AddConstraint`，MySQL 部署上约束根本不存在；而三种 DB 的唯一索引都把 NULL 视为互不相等，草稿行天然多行共存，无需 condition。幂等三件套（DB 约束 + `aget_or_create` + `except IntegrityError` 重新 `aget`）齐备，缺任何一件都会退化成「并发下产重复行」或「并发下给用户 500」。
- **投影端点的 owner gate 分层与措辞纪律到位。** `aresolve_conversation` 是只读前置解析（越权请求不会先在他人会话下建出 `CodingPlan` 再被拒）；真正的门在 service 内（`_assert_owner`，`actor_user_id` **必填无默认值**——带默认值会让漏传的调用方静默拿到 `"system"` 身份，那正是 109-03 遗留 blocker 的形状）；`_assert_owner` 严格早于 `map_merged_plan_to_coding_plan`（判定晚一步就等于跨会话读取他人完整方案正文）；`artifact_version_not_found` 与 `artifact_version_forbidden` 同形映射 404 且 detail 逐字一致，不泄漏存在性。
- **RELY-01 的三处判定都是允许清单，无一例外。** 界面 `isUnresearched = resolvedProvenance !== 'orchestrated'`（`TechPlanCard.vue:297`）、服务端 gate `_plan_requires_unresearched_confirm`（`coding_session_service.py:88`）、导出 `str(provenance or "") != ORCHESTRATED`（`coding_plan_exporter.py:207`）——三处都是**不等于**比较，`draft` / 未知取值 / 空值 / `undefined` 全部落进标注侧。我逐条验证了 `undefined` 路径确实是纯字面量比较、不对 `undefined` 做属性访问。
- **`acknowledge_unresearched` 的前端来源确实唯一。** `ensureUnresearchedAcknowledged`（`TechPlanCard.vue:371`）是 `true` 在前端的唯一产生点，返回值刻意是三态而非裸布尔；`acknowledged` 是组件本地 `ref`、每次 `openUnresearchedDialog` 重置为 `false`、不写 store 不入 localStorage；`submitRepoMultiSelector` 只在 `=== true` 时才把键放进 payload（编排方案是**不发字段**而非发 `false`）；`retrySingleRepository` 原样转发不补值，调用点还刻意避免把 `undefined` 当第三参显式传入。创建态 / 追加态共用 `handleMultiConfirm` 天然都过闸门，单仓重试单独过闸门。**三条路径都不存在「前端自行签名」的形状。**
- **服务端 gate 是 fail-closed 且拒绝时 DB 零写入。** gate 在 `create_sessions_for_plan` 函数首部、任何 session 创建之前；判定写成 `is not True`（truthy 字符串/数字不算确认）；serializer `default=False`；异常而非返回值（塞进 `failed` 会让它看起来像 per-repo 失败、调用方可能继续往下走）；拒绝响应带稳定机器码 `draft_requires_explicit_confirm` 双键，前端 `isDraftGateRejection` 读 `ApiError.body.code`、**不匹配 detail 文案**。绕过面也堵住了：直接打端点与直调 service 两条路径共享同一道门。
- **`plan_id` 串态守卫在本 phase 新增的三个消费点上都在位。** `resolvedTechPlan` / `resolvedAffectedFiles` / `resolvedProvenance` 都过 `runtime.plan_id === props.codingPlanId`，注释还写明了「标志串了比正文串了更严重」。（但 `sessions` 这个既有消费点没有守卫，见 MN-05。）
- **`create → add` 这个静默失守点被显式处置了。** `_ACTION_TO_CHANGE_TYPE` 是唯一防线，未知/缺失 action 保守回退 `modify`（不会把「改一行」误报成「新增文件」），前端按 UI-SPEC §B.4 裁定**不做**兼容映射以免掩盖后端缺陷。
- **迁移 additive、无 `RunPython`、可逆**；`default="draft"` 让存量行全部落进保守分支，这在事实层是对的（存量 `coding_plans` 确实全是 SPINE-02 之前徒手创作的产物），且不破坏任何既有查询——`provenance` 只被新代码读，`CodingPlanSerializer` 的新字段全是 `read_only`（客户端无法把 `draft` 伪造成 `orchestrated`）。
- **导出侧告示能真的落成飞书块。** 我核到 `markdown_to_blocks` 的 `block_quote → block_type 15 (quote)` 分支存在，且 `_DRAFT_NOTICE` 尾部 `\n` 与 `"\n".join(parts)` 合起来在告示与 `## 技术方案` 之间留了空行，blockquote 不会把下一个标题吞进去。
- **观测埋点基本合规**：`plan_projection_started/completed/failed` 三态齐全、带 `category="caller"` / `component="chat"` / `duration_ms`，失败 `reason` 过了 `redact_secrets_in_text`，全部包在 `try/except: pass` 里不反噬业务；`_log_authoring_rejected` 同款。
- **ruff / vue-tsc / 相关测试全绿**：后端 140 passed、前端 115 passed、`vue-tsc --noEmit` 通过；ruff 的 4 条 `I001` 与 4 个待格式化文件全部落在本 phase 未触及的既有代码段（我逐条比对了 `ruff format --diff` 的位置）。

**问题集中在三处：**

1. **一个工具彻底不能用。** `update_coding_plan` 把归属主体收窄成「只取 contextvars 的 `user_id`」，但这个值在生产里**永远是中间件写的 `"system"` 占位**——`LogContextMixin`（唯一会 `rebind_user` 的地方）全仓零使用。helper 又把 `"system"` 归一为空串，于是每次调用都命中 `actor_user_unresolved` 早退。工具仍挂在 `_get_tool_names` 白名单里，模型会反复调、反复失败（BL-01，已实测）。
2. **SPINE-01 的头条入口在界面上走不完。** 「进入编码」投影成功了、卡片交棒了，但内嵌的 `TechPlanCard` 没拿到 `available-repositories` → 选仓面渲染成「未找到匹配的仓库」。测试用 stub 顶掉了真实 `TechPlanCard`，所以这个缺口在 240 行的新 spec 里完全不可见（HI-01）。
3. **SPINE-02 砍掉 tool input 之后，「非最新那份方案」的卡片同时失去正文和来源标志。** 正文变成「（暂无方案正文）」，`provenance` 落到保守分支被挂上「未经代码调研」——RELY-01 的告警在最普通的多方案会话里就开始误报，反过来削弱了这个信号的可信度（HI-02）。

---

## BLOCKER

### BL-01：`update_coding_plan` 在生产环境恒失败——归属主体取的 contextvars 永远是 `"system"`

**文件:** `server/agents/tools/coding_tools.py:430-439`（`actor_user_id = _context_user_id()`）、`server/agents/tools/coding_tools.py:45-53`（`_context_user_id`）

**问题:**

`update_coding_plan` 刻意不给归属主体留退路：

```430:439:server/agents/tools/coding_tools.py
    # 归属主体只取请求上下文 —— update 的 plan 定位入参（coding_plan_id /
    # session_id）**由模型提供**，若退回「被改写 plan 的会话创建者」等于让攻击者
    # 通过挑选他人 plan_id 自选身份（EoP）。取不到即拒绝，绝不用哨兵身份放行。
    actor_user_id = _context_user_id()
    if not actor_user_id:
        _log_authoring_rejected(conversation_id="", reason="actor_user_unresolved")
        return ToolResult(
            success=False,
            error="无法确定当前操作用户，拒绝改写编码方案。",
        )
```

安全推理本身是对的（EoP 面确实存在，见 MN-04），但它依赖的那个 contextvar **在生产里从来没有真实值**：

- `RequestLogContextMiddleware._bind` 是唯一在 HTTP 入口写 `user_id` 的地方，它写的是硬编码占位 `user_id="system"`（`common/middleware.py:129-134`）。
- 真实用户 id 只由 `common/log_context.py::rebind_user` 补绑，而 `rebind_user` 的唯一调用方是 `common/mixins.py::LogContextMixin.initial`。
- **`LogContextMixin` 在全仓没有任何视图继承**——`rg -n "LogContextMixin" --glob '*.py' -l` 只命中定义（`common/mixins.py`）、两处文档提及（`common/middleware.py` docstring、`friday/settings.py` 注释）与它自己的单测。`chat/` 目录零命中，`ChatStreamView` 直接 `class ChatStreamView(APIView)`。
- `_context_user_id` 又把 `"system"` 显式归一为空串（`coding_tools.py:52`：`return "" if raw in ("", "system") else raw`）。

实测（在本仓 venv 里按中间件的真实绑定复现）：

```
bind_request_context(request_id='r', source=LogSource.REST, trace_id='t', user_id='system')
_context_user_id()  ->  ''
```

⇒ **每一次 `update_coding_plan` 调用都在第 434 行早退。** 而 `conversation_service._get_tool_names` 仍把 `update_coding_plan` 挂进白名单（`conversation_service.py:436`），系统提示词还专门教模型「用户要求换一份方案时…再调 `update_coding_plan` 把编码方案重新指向新的方案版本」（`conversation_service.py:222-223`）。用户可见后果：让 AI「换一份方案」时，AI 会调工具、拿到「无法确定当前操作用户，拒绝改写编码方案。」，然后向用户复述一个无从解释的内部错误——而这条路径在 Phase 109 之前是能用的（原实现只是 `plan.aupdate_plan(tech_plan=..., affected_files=...)`）。这是一次完整的功能回归。

**这条缺口为什么没被测试抓住：** `tests/test_coding_tools.py:164` 与 `:492` 两处都用 `structlog.contextvars.bind_contextvars(user_id=...)` **手工**注入身份。手工注入让 service 内的归属判定得到了很好的覆盖，但整套用例里没有一条断言「按生产的绑定形态（`user_id="system"`）调用时会发生什么」，于是这条路径的可用性无人验证。

顺带说明：`create_coding_plan` **不受影响**——它有第二个来源（`actor_user_id = _context_user_id() or str(conversation.created_by_id or "")`，`coding_tools.py:214`），而 `conversation_id` 是 chat_runner 闭包注入、模型改不了的，这个退路成立。所以 BL-01 只打掉 update 这一个门。

**修复建议（二选一，都必须补一条按生产绑定形态跑的用例）：**

- **（推荐）先把身份链路接通**：让 chat 视图真正拿到真实 `user_id`——给 `ChatStreamView`（及其它需要归因的 chat 视图）加 `LogContextMixin`，或在 `ChatStreamView.post` 里显式 `rebind_user(resolve_user_id(request))`（它已经在同一处调了 `bind_source` / `set_call_source`，加一行同源调用改动面最小）。注意 `_stream_events` 是在中间件 `finally` 的 `clear_request_context()` 之后被消费的，若实测发现绑定不跨到生成器，就在 `_stream_events` 入口用 `structlog.contextvars.bound_contextvars(user_id=..., source=...)` 包住整个生成体（与 107 的 MN-05 同款处置）。
- **或给 update 一条与 create 同强度的退路**：用**服务端注入**的会话身份而不是模型入参身份。具体做法：让 `update_coding_plan` 也接收 chat_runner 闭包注入的 `conversation_id`，用它解析 `created_by_id` 作为 actor，并**额外校验** `plan.conversation_id == 注入的 conversation_id`——这样既不会让模型通过挑 `plan_id` 自选身份（MN-04 的 EoP 面同时被关掉），又不依赖一个当前恒空的 contextvar。

无论走哪条，都请补一条「用 `bind_request_context(..., user_id="system")` 这一真实入口形态调用 `update_coding_plan`」的用例——这正是当前 785 行新测试里缺的那条。

---

## HIGH

### HI-01：「进入编码」后的选仓面是空的——内嵌 `TechPlanCard` 未传 `available-repositories`

**文件:** `web/src/components/chat/OrchestratedPlanCard.vue:142-153`

**问题:**

交棒时传下去的 props 是：

```142:153:web/src/components/chat/OrchestratedPlanCard.vue
    <TechPlanCard
      v-if="localCodingPlanId"
      :plan-id="localCodingPlanId"
      :coding-plan-id="localCodingPlanId"
      :title="localTitle"
      :tech-plan="localTechPlan"
      :affected-files="localAffectedFiles"
      :provenance="localProvenance"
      :recommended-repository-ids="localRecommendedRepositoryIds"
      status="draft"
      :is-confirming="false"
    />
```

**没有 `available-repositories`，也没有 `target-repositories`**，两者在 `TechPlanCard` 里都 `withDefaults` 成 `[]`。后果沿着两条链传下去：

1. `showInlineSelector` 为真（`codingPlanId` 有值、`sessions` 为空）⇒ 渲染 `RepoMultiSelector :repositories="availableRepositories"`，即 `[]`。`RepoMultiSelector` 的 `filtered` 为空 ⇒ `CommandList` 里只剩 `<CommandEmpty>未找到匹配的仓库</CommandEmpty>`（`RepoMultiSelector.vue:103`）。用户在「请在下方选择目标仓库」的提示下面看到的是「未找到匹配的仓库」。
2. `visibleTargetRepositories` 走到第三级 `availableRepositories.filter(repo => recommendedRepositoryIds.includes(repo.id))` = `[]` ⇒ 「目标仓库」徽标区整块不渲染，用户连「AI 推荐了哪几个仓」都看不到。

**能不能提交？** 侥幸能，但方式很脆：`RepoMultiSelector` 的 `onMounted` 会把 `recommendedIds` 合并进 `modelValue`（`RepoMultiSelector.vue:53-59`），所以「已选 N / 20」会显示 N>0、「确认编码」按钮可点，`handleMultiConfirm` 拿到的是那批推荐 id。也就是说：**用户在一个显示「未找到匹配的仓库」的空列表下面，点一个不知道选了什么的「确认编码」**。而且 `toggle()` 只对已渲染的行生效，用户**无法取消**任何一个推荐仓，也无法加别的仓。若编排产出的 `execution_plan[]` 里没有 `repository_id`（`map_merged_plan_to_coding_plan` 会聚合出空列表），`modelValue` 为空 ⇒ 按钮 `disabled` ⇒ **彻底走不下去**。

这直接打在 SC-1 上：「用户在编排产出方案后可直接进入选目标仓 → 配置分支 → 确认编码 → 飞书导出」——第一步「选目标仓」在界面上不成立。

**这条缺口为什么没被测试抓住：** `OrchestratedPlanCard.spec.ts:45-46` 用 `StubTechPlanCard` 顶掉了真实组件，只断言 props 透传，因此「透传的 props 够不够真实 `TechPlanCard` 跑完四步」这件事没有任何用例覆盖。240 行新 spec 全绿，缺口纹丝不动。

**修复建议:**

让投影响应把仓库**名字**一并带回来，再喂给两个 props（只传 id 无法渲染名字，这也是当前只传 `recommended_repository_ids` 的根因）：

1. 后端 `ProjectPlanToCodingResponseSerializer` 加 `recommended_repositories: [{id, name}]`（`create_coding_plan` 的 ToolResult 早就有这个键，照抄它的组装即可，注意按 `plan.conversation.space` 过滤——见 MN-03 的同类问题）。
2. `OrchestratedPlanCard` 把它同时作为 `:available-repositories` 与 `:target-repositories` 传下去（`ChatMessageBubble` 对既有 `TechPlanCard` 就是这么传的：`:available-repositories="codingPlanData.targetRepositories"`，`ChatMessageBubble.vue:1216-1218`）。
3. `OrchestratedPlanCard.spec.ts` 里**至少留一条不 stub `TechPlanCard`** 的用例，断言选仓列表渲染出 ≥1 个可勾选行——只要有这一条，本缺口在提交前就会红。

### HI-02：SPINE-02 后非最新 plan 的方案卡同时丢正文与来源标志——旧卡变空 + 被误挂草稿横幅

**文件:** `web/src/components/chat/ChatMessageBubble.vue:1206-1220`（`TechPlanCard` 调用点）、`web/src/components/chat/TechPlanCard.vue:235-278`（三级优先解析）

**问题:**

`TechPlanCard` 的正文与来源标志各有三级优先，第 1 级是 props、第 2 级是 `runtime.coding_plan` 且**必须** `runtime.plan_id === props.codingPlanId`。而 `ChatMessageBubble` 这个调用点：

- `:tech-plan="codingPlanData.techPlan"` 取自 tool input，**SPINE-02 收窄 schema 后新消息的 input 里没有 `tech_plan`** ⇒ 恒为空串（`ChatMessageBubble.vue:824-830` 的注释自己写明了这一点）。
- **完全不传 `:provenance`** ⇒ 第 1 级恒空。
- `create_coding_plan` 的 ToolResult 也不带 `tech_plan` / `provenance`（`coding_tools.py:337-355` 的 output 键只有 `coding_plan_id` / `coding_session_id` / `session_id` / `repository_id` / `repository_name` / `status` / `branch_name` / `recommended_*` / `message`）。

⇒ 两者都只能靠第 2 级。但 `activeCodingPlan` 的语义是「**对话内最近**一条 `CodingPlan`」（`conversation_service.py:2660` 附近取 `latest_plan`）。于是：

| 场景 | 正文 | provenance | 用户看到 |
|---|---|---|---|
| 会话内只有 1 份 plan、runtime 已刷新 | runtime 命中 | runtime 命中 | 正常 |
| 工具刚返回、runtime 还没刷新 | 空 | undefined | 短暂「（暂无方案正文）」+「未经调研」横幅闪现 |
| **会话内有 ≥2 份 plan（旧卡）** | **空** | **undefined** | **「（暂无方案正文）」+「本方案未经代码调研」横幅 + 头部常驻「未经调研」徽标** |

第三行是普通流程，不是边缘场景：用户先让 AI 出一份方案（plan #1，卡片有正文），后面又提一个改动、再走一次编排产出 plan #2 —— 此刻**滚动回去看 plan #1 的卡片，正文没了，还多了一条「本方案未经代码调研」**。而 plan #1 明明是编排产出的（`provenance` 在库里就是 `orchestrated`）。

两重代价：

1. **内容丢失回归。** SPINE-02 之前，正文由 tool input 承载，每张历史卡片都有正文且与该卡一一对应。现在只有「最近那一份」有正文。UI-SPEC §E 把 tool input 定位成「历史消息兜底」是对的，但漏算了「SPINE-02 之后产生的、但已不是最新的」那批消息——它们既没有 input 里的正文，也匹配不上 runtime。
2. **RELY-01 误报，削弱信号本身。** 「保守默认」的方向选择是对的（把 `undefined` 当可信才是安全缺陷），但当误报发生在**主路径的常见形态**上时，用户很快就会学会忽略这条横幅——RELY-01 想立的「看到这条就该警惕」的心智被自己的噪声拆掉。而且草稿确认弹层会在这些编排方案上照样弹（`isUnresearched` 为真），用户每次送编码都要多勾一次「我已了解风险」，勾的还是一份其实经过调研的方案。

**修复建议（推荐 1，1+2 一起做最稳）：**

1. **让工具结果自带这两个事实**：`create_coding_plan` 的 ToolResult output 补 `tech_plan` / `affected_files` / `provenance`（三者都已在手，`plan` 就是 `aproject` 返回的实例，零额外查询），`ChatMessageBubble` 把 `codingPlanData.provenance` 透给 `:provenance`、正文优先取 result 再回退 input。这是一行 schema + 一行传参的缺口，与投影端点「响应直接带正文，不要求前端二次拉取」是同一条纪律——只是漏在了工具这条出口。
2. **或按 plan 拉详情**：`GET /api/chat/coding-plans/{plan_id}/` 的 `CodingPlanSerializer` 本 phase 已经透出 `tech_plan` / `provenance` / `affected_files` / `recommended_repository_ids`，前端可在卡片挂载时按 `codingPlanId` 拉一次（历史消息也一并修好）。代价是一次往返。
3. 无论走哪条，`chatMessageBubble.parts.spec.ts` 里补一条「会话内有两份 plan 时，旧卡仍有正文且**不**渲染 `unresearched-banner`」的用例——现有用例只覆盖了「`plan_id` 不匹配时不采用 runtime」这半边（守卫本身），没有覆盖「不采用之后拿什么」这半边。

---

## MEDIUM

### MN-01：MCP 桥接产出的 chat `CodingPlan` 被标成 `draft`，编排产出被误标「未经代码调研」

**文件:** `server/mcp_tools/execution_service.py:109-115`（未改，但被 109-02 的 `default="draft"` 波及）

`_create_bridge_session` 用裸 ORM 建 chat `CodingPlan`，不传 `provenance` ⇒ 落 DB default `draft`：

```109:115:server/mcp_tools/execution_service.py
            chat_plan = CodingPlan.objects.create(
                conversation=conversation,
                title=plan.title[:200],
                tech_plan=tech_plan,
                affected_files=affected_files,
                recommended_repository_ids=[str(plan.repository_id)],
            )
```

但这条链的正文 `_plan_body_to_markdown(version)` 来自 `McpCodingPlanVersion`，而 MCP 的 `create_coding_plan` 端点**早在 Phase 94 就 delegate 到统一编排**（`mcp_tools/orchestration_delegate.py::map_canonical_to_coding_plan` 从 canonical §7 `MergedPlan` content 映射）——**它是编排产出，不是草稿**。三处后果：

1. `_create_bridge_session` 建的 `Conversation`（`MCP execution: <title>`）是真实会话，会出现在 SPA 会话列表里。用户点进去看到的方案卡带「本方案未经代码调研」横幅与「未经调研」徽标。
2. 从该会话导出到飞书，文档正文顶部会插入 `_DRAFT_NOTICE`——一份经过完整编排的方案，导出物上写着「由对话直接生成，未经仓库路由、代码召回与并行调研」。
3. **新的执行契约字段被写反**：`build_coding_execution_spec` 按 `provenance != orchestrated` 算出 `unresearched=True`，经 `env_metadata["execution_spec"]` 随 dispatch 下发（`coding_session_service.py:277-280`）。MCP 链走的正是同一个 `dispatch_coding_task`，所以**所有 MCP 执行的编码任务都会带 `unresearched: true`**。容器侧本 phase 还没消费这个标志，但它是留给下游「据此调整策略」的契约，一上线就是错的。

`test_bridge_session.py:178` 用 `assert chat_plan.provenance == CodingPlanProvenance.DRAFT` 把当前行为**锁成了预期**，109-07-SUMMARY 也没讨论这条链。CONTEXT 明确写「标注载体是数据层来源标志…避免新增产出路径时漏标」——这里是反过来：一条既有的**编排**路径被漏设标志、掉进保守分支。

**修复建议:** `_create_bridge_session` 显式传 `provenance=CodingPlanProvenance.ORCHESTRATED`（这条链的来源是 canonical `PlanVersion`，语义上就是编排产出）。若还想保留追溯，可同时把 `DelegateResult.plan_version_id` 记进 `source_artifact_version_id`——但注意那是 canonical `PlanVersion.id` 而非 `ArtifactVersion.id`，且会与唯一约束交互（同一 version 只能有一份投影，MCP 链允许重复桥接），所以**只改 `provenance`、不填来源列**是改动面最小且安全的做法。并把 `test_bridge_session.py:178` 的断言翻成 `ORCHESTRATED`，同时补一条「MCP 链的 `execution_spec.unresearched is False`」的用例。

### MN-02：`arebind` 非原子——正文与来源指针可以分裂

**文件:** `server/chat/plan_projection_service.py:466-490`

```466:484:server/chat/plan_projection_service.py
            try:
                # aupdate_plan 负责 tech_plan / affected_files 的原子更新与知识库重摄取。
                await plan.aupdate_plan(
                    tech_plan=payload["tech_plan"],
                    affected_files=payload["affected_files"],
                )
                plan.title = payload["title"][:200] or plan.title
                plan.recommended_repository_ids = payload["recommended_repository_ids"]
                plan.provenance = CodingPlanProvenance.ORCHESTRATED
                plan.source_artifact_version_id = av.id
                await plan.asave(
                    update_fields=[
                        "title",
                        "recommended_repository_ids",
                        "provenance",
                        "source_artifact_version_id",
                        "updated_at",
                    ]
                )
```

两次独立写库、外面没有 `transaction.atomic`。`aupdate_plan` 已经把**新正文**落库，之后 `asave` 若失败（唯一约束并发窗口就是设计上预期会发生的那种失败，`:485-490` 专门接了 `IntegrityError`），留下的状态是：

- `tech_plan` / `affected_files` = **新版本 Y 的内容**
- `source_artifact_version_id` = **旧版本 X**、`provenance` 可能仍是 `draft`

而工具对用户报的是「无法把编码方案重新指向方案版本 Y…请确认该方案版本…未被其它编码方案占用」——**用户以为什么都没变，实际正文已经换了**。追溯链（`source_artifact_version_id → ArtifactVersion → Artifact → WorkItem`，模块 docstring 声称的「追溯最小完备集」）从此指向一个与正文无关的版本，这类不一致不会报错、只能靠人肉比对发现。

注意这不只是并发问题：`asave` 的任何失败（DB 连接抖动、字段校验）都会落进同一个混合态。

**修复建议:** 把两次写包进同一个事务。`aupdate_plan` 内部还带知识库重摄取，直接套 `transaction.atomic` 可能把 IO 拖进事务，所以更稳的做法是**调换顺序 + 单事务**：

```python
from asgiref.sync import sync_to_async
from django.db import transaction

@sync_to_async
def _rebind_atomic() -> None:
    with transaction.atomic():
        # 先写来源指针（会撞唯一约束的那一步放在最前），成功后再写正文
        CodingPlan.objects.filter(pk=plan.pk).update(
            title=payload["title"][:200] or plan.title,
            recommended_repository_ids=payload["recommended_repository_ids"],
            provenance=CodingPlanProvenance.ORCHESTRATED,
            source_artifact_version_id=av.id,
            tech_plan=payload["tech_plan"],
            affected_files=payload["affected_files"],
        )

await _rebind_atomic()
# 事务提交后再单独触发知识库重摄取（best-effort，失败不回滚）
```

关键点有两个：(1) **会撞唯一约束的那一列先写**，让 `IntegrityError` 发生在任何正文变更之前；(2) 知识库重摄取移到事务之后、best-effort。补一条用例：mock `asave`/`update` 抛 `IntegrityError`，断言 `plan.tech_plan` **未变**。

### MN-03：`projected` 分支把半可信 LLM 产出的 `repository_id` 直接喂 UUID 查询

**文件:** `server/agents/tools/coding_tools.py:315-323`

```315:323:server/agents/tools/coding_tools.py
    else:
        projected_ids = [str(r) for r in (plan.recommended_repository_ids or [])]
        if projected_ids:
            final_recommended = projected_ids
            recommended_repositories = [
                {"id": str(r.id), "name": r.name}
                async for r in Repository.objects.filter(id__in=projected_ids)
            ]
            recommended_source = "projected"
```

`projected_ids` 的来源是 `map_merged_plan_to_coding_plan` 从 `execution_plan[].repository_id` 聚合的值，而那里只做 `str(task.get("repository_id") or "")`、**不校验 UUID 形状**（模块 docstring 明确声称「半可信输入恒不抛」——映射层确实不抛，抛的是消费方）。实测：

```
Repository.objects.filter(id__in=['not-a-uuid'])  ->  ValidationError: ['“not-a-uuid”不是一个有效的UUID']
```

这个异常在 `@tool` 装饰器里没有兜底（`agents/tools/base.py` 的 wrapper 只是 `return await func(...)`），会一路上抛到 agent 循环。用户可见后果：编排产出里只要有一个仓 id 写歪（LLM 产物，`execution_plan` 的 schema 没有强约束），`create_coding_plan` 就以未处理异常收场——**而 `aproject` 已经在第 293 行把 `CodingPlan` 落库了**，用户看到的是「失败」，DB 里却多了一条投影（下次重试靠幂等命中，倒不会重复，但状态与提示不一致）。

同一段还有一个次要问题：`Repository.objects.filter(id__in=projected_ids)` **没有按 `plan.conversation.space` 过滤**，而上面 LLM 显式传 id 的那条分支是过滤了的（`:236` 附近按 space 校验）。来源虽然是用户自己会话的编排产出、风险低，但两条分支的可见性口径不一致，日后很容易被当成「这里不需要过滤」的先例。

**修复建议:**

```python
import uuid as uuid_mod

def _valid_uuids(values: list[str]) -> list[str]:
    """半可信来源的 id 过筛：非 UUID 字面量直接丢，绝不带进 ORM 查询。"""
    out: list[str] = []
    for v in values:
        try:
            out.append(str(uuid_mod.UUID(str(v))))
        except (ValueError, AttributeError, TypeError):
            continue
    return out
```

`projected_ids = _valid_uuids(plan.recommended_repository_ids or [])`，并把查询改成 `project.repositories.filter(id__in=projected_ids)`（与 LLM 显式传参分支同一口径）。补一条用例：`execution_plan[].repository_id` 含 `"not-a-uuid"` 时工具仍 `success=True`、`recommended_repository_ids` 只含合法 id。

### MN-04：`update_coding_plan` 的 legacy `session_id` 分支在归属判定之前就写库

**文件:** `server/agents/tools/coding_tools.py:454-475`

`session_id` 是**模型提供**的入参。该分支在拿到 session 后、在 `arebind` 的 `_assert_owner` 之前就动了两次写：

```464:475:server/agents/tools/coding_tools.py
        if session.coding_plan_id is None:
            # 旧数据未迁移：临时建/拿 plan 并把反向 FK 补回去。正文沿用 session 的
            # 既有值（不是模型入参）—— 真正的新正文由下方 arebind 从来源版本渲染。
            plan, _created = await CodingPlan.aget_or_create_for_conversation(
                conversation=session.conversation,
                tech_plan=session.tech_plan,
                affected_files=session.affected_files or [],
                title="",
            )
            session.coding_plan = plan
            await session.asave(update_fields=["coding_plan", "updated_at"])
```

`session` 的归属完全没查。模型报一个属于**他人会话**的 `session_id`（且该 session 未迁移、`coding_plan_id` 为 NULL）⇒ 在他人会话下建出一条 `CodingPlan`、并改写他人 `CodingSession.coding_plan` FK，之后 `arebind` 才因 `artifact_version_forbidden` 拒绝。净效果是「拒绝了，但数据已经被污染」。

这正是投影端点刻意用只读 `aresolve_conversation` 前置解析所要避免的形状——`views.py:2749` 的注释写得很清楚：「若把 gate 放到投影之后，越权请求会先在他人会话下建出 `CodingPlan` 再被拒（垃圾对象 + 数据污染）」。工具路径没有沿用这条纪律。

**当前可达性:** 不可达——BL-01 让函数在第 434 行就早退。所以这是一条**修完 BL-01 立刻变活**的潜伏缺陷，必须与 BL-01 一起处置，否则修好 BL-01 的那次提交会同时打开这个面。

**修复建议:** 把归属判定提到任何写之前。最小改法：

```python
# legacy 分支：先判 session 所属会话的归属，再补 FK（写在授权之后）
if str(session.conversation.created_by_id or "") != actor_user_id:
    _log_authoring_rejected(conversation_id="", reason="artifact_version_forbidden")
    return ToolResult(success=False, error="CodingSession not found: " + session_id)  # 同体同文，不泄漏存在性
```

（措辞与「不存在」一致，沿用 `_assert_owner` 已建立的不泄漏存在性纪律。）若采纳 BL-01 修复建议的第二条（注入 `conversation_id` + 校验 `plan.conversation_id` 一致），这个面会被一并关掉。

### MN-05：`runtime.coding_plan` 还有四个消费点没有 `plan_id` 守卫

**文件:** `web/src/components/chat/TechPlanCard.vue:106-131`

本 phase 给 `tech_plan` / `affected_files` / `provenance` 都补上了 `runtime.plan_id === props.codingPlanId` 守卫，注释还专门写了「标志串了比正文串了更严重」。但同一个 runtime 对象的另外四个消费点是裸的：

```106:118:web/src/components/chat/TechPlanCard.vue
const sessions = computed(() => codingPlanRuntime.value?.sessions ?? [])
const hasSessions = computed(() => sessions.value.length > 0)
...
const existingActiveRepoIds = computed(() =>
  sessions.value
    .filter(s => ACTIVE_STATUSES.has(s.status))
    .map(s => s.repository_id),
)
const showInlineSelector = computed(
  () => !!props.codingPlanId && !hasSessions.value,
)
```

这段是既有代码（守卫缺失是 pre-existing），但 Phase 109 让它**开始承重**：`OrchestratedPlanCard` 投影完成后立刻内嵌 `TechPlanCard`，而 `projectPlanToCodingPlan` 只排了一次 `scheduleRuntimePoll(currentConversationId, 3000)`（`stores/chat.ts:2665`）。在那 3 秒（轮询失败则永久）里 `activeCodingPlan` 仍指向**投影之前**那份 plan。若那份 plan 已有 sessions：

- `hasSessions` 为真 ⇒ `showInlineSelector` 为假 ⇒ **选仓面根本不渲染**（与 HI-01 叠加，「进入编码」后什么可操作的东西都没有）；
- 卡片里列出的是**别的 plan 的 session 行**（仓库名、状态、PR 链接全是别人的）；
- 用户在这些行上点「重试」⇒ `handleSessionRowRetry` 用 `props.codingPlanId`（新 plan）+ `session.repository_id`（旧 plan 的仓）调 `retrySingleRepository` ⇒ **在新 plan 上建了一条本不该有的 session**。

`visibleTargetRepositories` 的第二级（`sessions.value.map(...)`）同理。

**修复建议:** 把守卫下沉到 runtime 的入口，让后续所有消费自动继承，而不是每个消费点各写一遍（这正是本 phase 已经踩了三次的重复形状）：

```ts
/**
 * 本卡对应的 runtime。🔴 plan_id 不匹配一律视为「没有」——activeCodingPlan 只指向
 * 「对话内最近 CodingPlan」，不匹配就采用会把别的 plan 的状态渲染到本卡上。
 */
const codingPlanRuntime = computed<CodingPlanRuntime | null>(() => {
  const runtime = activeCodingPlan.value
  if (!runtime)
    return null
  if (props.codingPlanId && runtime.plan_id !== props.codingPlanId)
    return null
  return runtime
})
```

改成这样之后 `resolvedTechPlan` / `resolvedAffectedFiles` / `resolvedProvenance` / `feishuDocUrl` 里的四段重复守卫都可以简化（保留注释说明为什么）。补一条用例：`activeCodingPlan.plan_id !== codingPlanId` 且该 runtime 有 sessions 时，本卡**不**渲染 session 行、**仍**渲染内嵌 selector。

另外建议 `projectPlanToCodingPlan` 把 `scheduleRuntimePoll` 的延迟压到 0 或立即拉一次——3 秒是这个串态窗口的直接来源。

### MN-06：草稿 gate 的留痕 `user_id` 恒为 `system`，RELY-01 的可追溯性没有立起来

**文件:** `server/chat/coding_session_service.py:95-101`（`_context_user_id`）、`:104-124`（`_log_draft_coding_gate`）

`_log_draft_coding_gate` 的 docstring 把目标写得很明确：「只记拒绝会让『谁在什么时候用草稿送了编码』不可追溯（RELY-01 的 Repudiation 面）」。但它取用户 id 的方式与 BL-01 同源：

```95:101:server/chat/coding_session_service.py
def _context_user_id() -> str:
    """从请求 / 任务上下文取触发用户 id；取不到记 `system`。"""
    try:
        raw = str(structlog.contextvars.get_contextvars().get("user_id") or "").strip()
    except Exception:  # noqa: BLE001 — 取上下文绝不反噬业务
        return "system"
    return raw or "system"
```

由于 `LogContextMixin` 全仓零使用（见 BL-01 的取证），contextvars 里的 `user_id` 永远是中间件写的 `"system"` 占位 ⇒ **`draft_plan_coding_confirmed` / `draft_plan_coding_rejected` 两条事件的 `user_id` 恒为 `system`**。RELY-01 想立的那条审计线（谁签了名、什么时候签的）实际上一条也记不下来，而这两条事件正是「草稿是有防护的应急路径」这个设计里唯一的问责凭据。

这也直接违反 `.cursor/rules/observability-logging.mdc` 的「绑定触发用户：每条日志/调用记录都要能回答『谁触发的』」——`CodingPlanSessionsBatchCreateView` 是一个 REST 写入口，不是无触发用户的系统行为，记 `system` 属于降级而非如实记录。

**修复建议:** 与 BL-01 的推荐修复共用同一个根治动作（把 `LogContextMixin` 真正接到视图上，或在 `ChatStreamView` / fan-out 视图里显式 `rebind_user`）。在根治之前，本处可以先走一条不依赖 contextvars 的显式通路：`CodingPlanSessionsBatchCreateView.post` 已经持有 `request.user`，把 `actor_user_id=str(request.user.id)` 作为关键字参数传进 `create_sessions_for_plan`，`_log_draft_coding_gate` 优先用它、取不到才回退 contextvars。补一条用例断言事件里的 `user_id` 是真实用户 id 而不是 `system`。

---

## LOW

### LO-01：gate 拒绝后重开的弹层是个死胡同

**文件:** `web/src/components/chat/TechPlanCard.vue:391-396`

```391:396:web/src/components/chat/TechPlanCard.vue
/** gate 拒绝的兜底呈现：前端常量 toast + 重新打开弹层让用户走正规确认。 */
function handleDraftGateRejection(): void {
  toastError(DRAFT_GATE_REJECTED_MESSAGE)
  // 不自动补 ack、不静默重放请求：重放需要用户在新弹层里重新勾选。
  void openUnresearchedDialog()
}
```

`void` 把 promise 丢掉了。用户在这个重开的弹层里勾选 Checkbox、点「仍要送编码」⇒ `settleUnresearchedDialog(true)` 会 resolve 一个**没有任何 await 方**的 promise ⇒ 弹层关闭，**什么都不会发生**。用户以为自己已经确认了，界面却毫无反应，只能自己找回原来的「确认编码」按钮再点一遍。

「不静默重放请求」这个取舍本身可以理解，但那就不该重开弹层——一个点了没反应的确认按钮比不弹更糟（与 `OrchestratedPlanCard` 里「按钮不消失…一个点了没反应的按钮是坏体验」的裁定自相矛盾）。

**修复:** 二选一。(a) 不重开弹层，只发 toast，让用户走原入口（改动最小，行为自洽）；(b) 真的重放：把被拒的那次提交参数记下来，`await openUnresearchedDialog()`，确认后用新的 `acknowledge: true` 重新调一次提交。若选 (b) 注意重放路径也不得自行补 `true`。

### LO-02：`orchestratedPlanData` 用 `toolCalls.find`，同消息内多次编排调用会串 id

**文件:** `web/src/components/chat/ChatMessageBubble.vue:791`

```791:791:web/src/components/chat/ChatMessageBubble.vue
  const tool = toolCalls.value.find(tc => isOrchestrationTool(tc.name))
```

渲染分支是按 `item`（单个 tool timeline 项）触发的，但取数是按**整条消息的第一个**编排工具。一条消息里若出现两次编排调用（例如先 `start_plan_research` 后 `start_feature_solution`），两张 `OrchestratedPlanCard` 都会拿到第一次的 `artifact_version_id`，第二张卡的「进入编码」会投影出错误的方案版本。这个形状照抄了既有 `codingPlanData`（同款问题、pre-existing），实际概率低（编排工具是阻塞式，同轮多次调用少见），但代价是「投影出的是另一份方案」这类看不出来的错。

**修复:** 把取数改成按 `item` 解析（`orchestratedPlanDataFor(item)` 或把解析函数下沉到 `OrchestratedPlanCard`，让它接收 `result` 而不是已解析的 id）。

### LO-03：`create_coding_plan` 的 `conversation_id` 已不决定投影落点，却仍必填且不校验一致性

**文件:** `server/agents/tools/coding_tools.py:293-296`

`aproject` 的落点 conversation 是从 `ArtifactVersion.produced_by_session_id → ConvergenceSession.conversation_id` 反查的，与工具入参 `conversation_id` 无关，两者也不做一致性校验。同一用户在会话 B 里调工具、传会话 A 产出的 `artifact_version_id` ⇒ plan 建在**会话 A** 下（归属判定通过，因为都是本人）。会话 B 的方案卡拿到一个不属于本会话的 `coding_plan_id`，`activeCodingPlan`（会话 B 的最近 plan）永远匹配不上 ⇒ 正文空、`provenance` undefined、误挂草稿横幅（HI-02 的同一失效面，只是触发原因不同）。

`space_id` 同理：它现在只用于校验 `recommended_repository_ids` 的归属，不参与落点判定。schema 里两个入参仍是 `required`，但它们对结果的影响面已经和描述不符了。

**修复:** 在 `aproject` 成功后加一条一致性校验——`plan.conversation_id != conversation.id` 时按 `artifact_version_forbidden` 同款措辞拒绝（HTTP 端点第 3 步已经有这道纵深复核了，`views.py:2790`，工具路径照抄即可）。同时把 schema 里 `conversation_id` 的描述订正为「用于归属校验，不决定投影落点」。

### LO-04：`_DRAFT_NOTICE` 插在了 `_STATUS_LABEL` 的注释块与定义之间

**文件:** `server/feishu/coding_plan_exporter.py:46-60`

原本描述 `_STATUS_LABEL` 的三行注释（「CodingSession.Status → 飞书表格中的中文徽章文案 / 与 6 态枚举一一对应 / 缺省降级避免 KeyError」）现在被 `_DRAFT_NOTICE` 的定义与它自己的六行注释整块隔开，读者看到那三行时下面跟着的是一个完全无关的常量。纯可读性问题，无行为影响。

**修复:** 把 `_DRAFT_NOTICE` 及其注释整块移到 `_STATUS_LABEL` 定义**之后**（或移到 `__all__` 下方的常量区顶部），让每段注释紧贴它描述的常量。

### LO-05：文档仍写「条件唯一约束」，实现是无条件唯一约束

**文件:** `.planning/ROADMAP.md`（Phase 109 的 109-02 条目）

ROADMAP 写「`CodingPlan` 加 `provenance` / `source_artifact_version_id` + **条件唯一约束** + additive 迁移」，而实现刻意用的是**无条件** `UniqueConstraint`，`models.py:311-319` 的注释把理由写得比 ROADMAP 更对（带 `condition` 会在 MySQL 上被 `_unique_supported()` 静默跳过）。**实现是对的，文档没跟上。** 留着会让后续评审按错误前提去判断「约束是不是漏了 condition」。

**修复:** 把 ROADMAP 该条改成「无条件唯一约束（刻意不带 condition，避免 MySQL 静默跳过）」。

---

## 逐项回应高风险不变量

| # | 不变量 | 结论 |
|---|---|---|
| 1 | 草稿检测允许清单（RELY-01） | **通过。** 界面 / 服务端 gate / 导出三处判定全是 `!== 'orchestrated'` 形态，无拒绝清单、无 truthy 捷径；`draft` / 未知取值 / `null` / `undefined` / `''` 全部落进标注侧，且判定是纯字面比较（不对 `undefined` 做属性访问）。但**误报面**比预期大得多，见 HI-02 与 MN-01 |
| 2 | `acknowledge_unresearched` 来源 | **通过。** `ensureUnresearchedAcknowledged` 是前端唯一产生点；`acknowledged` 为组件本地 `ref`、每次打开重置、不入 store / localStorage；store 层只在 `=== true` 时放键（编排方案是**不发字段**）；`retrySingleRepository` 原样转发不补值。创建态 / 追加态 / 单仓重试三条路径逐条核过，均无缓存、记忆或默认 `true` |
| 3 | `plan_id` 串态守卫 | **部分通过。** 本 phase 新增的三个消费点（`tech_plan` / `affected_files` / `provenance`）守卫齐备；但 `sessions` / `hasSessions` / `existingActiveRepoIds` / `visibleTargetRepositories` 四个既有消费点**裸的**，且被本 phase 的就地交棒新变成承重路径（MN-05） |
| 4 | 服务端 fail-closed gate | **通过。** gate 在 `create_sessions_for_plan` 首部、任何 session 创建之前、拒绝时 DB 零写入；`is not True` 判定 + serializer `default=False`；单仓重试与追加态走的是同一端点同一 service，无绕过路径；拒绝带稳定机器码 `draft_requires_explicit_confirm`，前端按 `code` 分支不按 `detail`。留痕能力不完整（MN-06）；拒绝后的前端兜底是死胡同（LO-01） |
| 5 | 工具 schema 收窄（SPINE-02） | **通过。** 两个门一起收窄，schema 与函数签名两侧都干净，键集合枚举断言能挡住换名入参；全仓替代写路径逐条核过，无第二个徒手创作口子；MCP 桥接的字段形状零回归（但语义被误标，MN-01）。**代价是 `update_coding_plan` 整体不可用（BL-01）** |
| 6 | 投影幂等（SPINE-01） | **通过。** 无条件唯一约束（不带 `condition` 的理由正确且写在代码里）+ `aget_or_create` + `IntegrityError` 重新 `aget` 三件套齐备；端点 owner gate 分层正确（只读前置解析 + service 内 `_assert_owner` + 投影后纵深复核），`actor_user_id` 必填无默认值。`arebind` 的两次写不在同一事务里（MN-02） |
| 7 | 迁移安全 | **通过。** 三个 operation 全部 additive、无 `RunPython`、可逆；两个新列都带 default（裸 ORM 桥接不崩）；`default="draft"` 是有意的且在事实层正确（存量全是徒手产物）；未发现任何依赖 `provenance` 缺省的既有查询或序列化假设。文档口径与实现不符（LO-05） |

---

_Reviewed: 2026-07-31T01:50:00Z_
_Reviewer: gsd-code-reviewer_
_Depth: standard_
