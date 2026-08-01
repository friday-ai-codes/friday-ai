---
phase: 116-entry
plan: 05
subsystem: delivery-artifacts + blueprint-render + feishu-export + blueprint-ui
tags: [blueprint, markdown-render, feishu-export, watermark, observability, view-05]
requires: ["116-04"]
provides:
  - "render_blueprint_markdown(content, *, blueprint_status)：blueprint/v1 → markdown 的唯一渲染器（十段全量 + 决策记录附录 + 引用脚注）"
  - "blueprint_status_of(artifact)：两个权威面共用的状态读法（纯读，零写）"
  - "_SUPPRESS_WATERMARK_STATUSES 闭合白名单（confirmed / implementing / implemented）"
  - "builtin_types._render_technical_plan 的 blueprint/v1 判别分支（注册表分支传 \"\" ⇒ fail-safe 当作未确认）"
  - "ArtifactTimelineSerializer.current_version_markdown 的蓝图特判（绕过注册表传真实状态，空壳一并修掉）"
  - "POST /api/delivery/artifacts/<uuid>/blueprint/export-feishu/（name=blueprint-export-feishu）"
  - "GET /api/delivery/artifacts/<uuid>/blueprint/export-feishu/availability/（name=blueprint-export-feishu-availability）"
  - "web blueprintsApi.getBlueprintExportAvailability / exportBlueprintToFeishu"
  - "BlueprintViewerHeader 的 exportAvailable / exporting props 与 export emit + 常驻「未经确认」横幅"
affects: [116-06]
tech-stack:
  added: []
  patterns:
    [required-keyword-only-invariant, closed-whitelist-fail-safe, signature-assertion-guard, falsifiable-mutation-test, import-reuse-scope-gate, upstream-error-tiering, ledger-side-trace]
key-files:
  created:
    - server/services/process_runtime/blueprint_render.py
    - server/delivery/api/blueprint_export_views.py
    - server/tests/services/process_runtime/test_blueprint_render.py
    - server/tests/delivery/test_blueprint_export_views.py
    - web/src/components/blueprint/__tests__/viewerHeaderExport.spec.ts
  modified:
    - server/delivery/artifacts/builtin_types.py
    - server/delivery/api/artifact_serializers.py
    - server/delivery/urls.py
    - server/tests/delivery/test_blueprint_log_redaction_guard.py
    - server/tests/delivery/test_blueprint_inv6_guard.py
    - web/src/api/blueprints.ts
    - web/src/components/blueprint/BlueprintViewerHeader.vue
    - web/src/pages/knowledge/blueprints/[id].vue
    - web/src/locales/zh-CN.json
decisions:
  - "⭐ 「未经确认」标注的不变量落在**签名 + 闭合白名单**上而不是「只有一个调用点」：blueprint_status 必填 keyword-only 无默认值、抑制集合是闭合白名单（空串与未知串都渲染标注）、⛔ 零布尔开关参数；唯一可机器验的形式是 inspect.signature 参数名集合断言"
  - "⭐ 状态读法收敛为 blueprint_render.blueprint_status_of(artifact) —— 两个权威面各写一份 getattr 归一迟早会在「None 算不算未确认」上分叉；同时它让调用点能写成单行，绕开 INV-6 守卫的多行 kwarg 误判（见 D-1）"
  - "块取文本**委托** delivery.services.blueprint_anchor._block_text 而不是复制（116-04 normalizer 同款分工）：按块类型分派会与批注锚点坐标系分叉"
  - "上游异常分档取 isinstance 判别而非错误码解析：PermissionDeniedError / DocumentNotFoundError / ValueError（凭证缺失）⇒ 400；RateLimitError 与其余 FeishuDocAPIError ⇒ 502。错误码集合（PERMISSION_CODES / NOT_FOUND_CODES）已在 feishu_doc 内部转成这三个异常类，再解析一次等于复制一份会漂移的映射"
  - "availability 的 space 从 meta.project_id → Project.space 反查（⛔ 不接受调用方可控的 ?space_id=）：范围闸认的就是这个 project_id，两者不同源会出现「闸放行项目 A、文档写进空间 B」"
  - "导出留痕落 Interaction Ledger（source=\"blueprint_export\"）+ 一条独立 caller 事件；⛔ 不写 ArtifactVersion.content、⛔ 不进 BLUEPRINT_EVENTS、⛔ 不产 ConvergenceSessionEvent"
metrics:
  duration: "~2.5h"
  completed: 2026-08-01
---

# Phase 116 Plan 05: 蓝图导出与不可关闭的「未经确认」标注 Summary

**One-liner:** 让蓝图**可导出到飞书**，并把「未经确认」做成**结构上关不掉**的东西 —— 不是加一个默认开着的开关，而是把开关物理删掉：`blueprint_status` 必填 keyword-only、抑制集合是**闭合白名单**（空串与未知串都渲染标注）、⛔ 零布尔开关参数，两侧各配一条**实跑过的变异用例**；顺带把 `ArtifactTimelineView.current_version_markdown` 对蓝图恒为 v0 空壳的**结构性问题**一并修掉 —— 它与导出物共用同一个渲染器，这是有意为之。

## PHASE_BASE

`e865d63f3ea9c3e25f865e5ed60ecae2c2341341`

本 plan 内所有冻结面 / 删除行 / 边界核算一律 `git diff e865d63f -- <file>`（逐 Task 原子提交之后裸 `git diff` 恒空，断言会静默恒真，B5）。

## 提交

| # | commit | 内容 |
|---|--------|------|
| 1 | `6346eb5c` | Task 1：`blueprint_render.py` + `builtin_types` 判别分支 + serializer 蓝图特判 + 两处守卫清单 + 35 条渲染器用例 |
| 2 | `87ed1598` | Task 2：`blueprint_export_views.py` 两端点 + `urls.py` 两条路由 + 守卫清单 + 34 条端点用例 |
| 3 | `7ad94c5f` | Task 3：前端常驻横幅 + 导出按钮 + api 两函数 + i18n + 21 条组件用例 |

---

## ⭐ 1. `render_blueprint_markdown` 的逐字签名、三条不变量与四个调用点

```python
def render_blueprint_markdown(content: dict, *, blueprint_status: str) -> str:
```

| 不变量 | 落地形态 | 机器验断言 |
|---|---|---|
| ① `blueprint_status` **必填 keyword-only、无默认值** | 调用方在物理上无法省略 | `test_blueprint_status_is_required_keyword_only`（`kind is KEYWORD_ONLY` 且 `default is Parameter.empty`） |
| ② 抑制集合是**闭合白名单** | `str(blueprint_status or "") not in _SUPPRESS_WATERMARK_STATUSES` ⇒ **无条件**写第一行 | `test_every_other_status_renders_the_watermark`（11 参数：其余八态 + `""` + `"totally_unknown"` + `None`） |
| ③ ⛔ **零布尔开关参数** | 签名里没有第三个参数 | `test_signature_parameter_names_are_exactly_content_and_status`（集合恰为 `{content, blueprint_status}`）+ `test_no_boolean_switch_parameter_exists`（四个候选名源码零命中） |

⭐ **关键不变量是「没有任何取值能关掉标注」，而不是「只有一个调用点」** —— 注册表契约 `ContentRenderer = Callable[[dict], str]`（`registry.py:16`）根本拿不到 `Artifact.blueprint_status`（它不在 content 里），所以「只有一个调用点」这条要求与既有契约不兼容；改契约会波及所有 artifact_type。

**四个调用点清单**（后来者据此一眼看出哪些面拿得到真实状态）：

| # | 调用点 | 传什么 | 拿得到真实状态？ |
|---|---|---|---|
| 1 | `delivery/artifacts/builtin_types._render_technical_plan`（注册表分支） | `blueprint_status=""` | ❌ 签名截断 ⇒ **fail-safe 当作未确认**（`"" ∉ 白名单`） |
| 2 | `delivery/api/artifact_serializers.ArtifactTimelineSerializer.get_current_version_markdown` | `blueprint_status_of(obj)` | ✅ `obj` 是 `Artifact` |
| 3 | `delivery/api/blueprint_export_views.BlueprintExportFeishuView.post` | `blueprint_status_of(artifact)` | ✅ |
| 4 | `tests/services/process_runtime/test_blueprint_render.py` | 参数化全量取值 | —（用例） |

## ⭐ 2. 抑制白名单两份清单逐字对照 + 两侧变异实跑记录

| 侧 | 位置 | 清单 |
|---|---|---|
| 后端 | `server/services/process_runtime/blueprint_render.py` `_SUPPRESS_WATERMARK_STATUSES: frozenset[str]` | `"confirmed"` / `"implementing"` / `"implemented"` |
| 前端 | `web/src/components/blueprint/BlueprintViewerHeader.vue` `CONFIRMED_STATUSES` | `'confirmed'` / `'implementing'` / `'implemented'` |

两份清单**逐字相同**，且各有机器验：后端 `test_whitelist_literals_match_blueprint_status_enum` 断言 frozenset 恰等于 `{BlueprintStatus.CONFIRMED/IMPLEMENTING/IMPLEMENTED}.value`；前端 `⭐ 前后端白名单逐字对齐` 用例**读后端源码提取成员**再比对。

⭐ **后端变异实跑**（从 frozenset 里去掉 `"implementing"`）：

```
红：tests/services/process_runtime/test_blueprint_render.py:174: in test_whitelist_literals_match_blueprint_status_enum
    E   AssertionError: assert frozenset({'c...implemented'}) == frozenset({'c...mplementing'})
    （连带 test_confirmed_statuses_have_no_watermark[implementing] 也转红：
     E   AssertionError: assert '未经确认' not in '> ⚠️ 未经确认 —…'）
绿：还原后 35 passed
```

⭐ **前端变异实跑**（从 `CONFIRMED_STATUSES` 里去掉 `'implementing'`）：

```
红：FAIL viewerHeaderExport.spec.ts > 「未经确认」常驻横幅 > 已确认态 implementing 不出横幅
    AssertionError: expected true to be false // Object.is equality
    （连带「前后端白名单逐字对齐」也转红：expected '<script setup…' to contain '\'implementing\''）
绿：还原后 21 passed
```

## ⭐ 3. 水印首行的**实际原文**与版本片段的登记（NOTE）

实测渲染出的第一行**逐字**是：

```
> ⚠️ 未经确认 —— 本方案尚未经人工终审（当前状态：pending_review）
```

⭐ **「· 版本 vN」片段按实际 schema 省略**：`version_no` **不在 `blueprint/v1` 的 `meta` 段内**（`blueprint_schema.py:142-166` 的 `meta` 只有 `title` / `summary` / `project_id` / `space_id` / `requirement_refs` / `language` / `revision_round`）。渲染器仍会读 `meta.version_no`，取不到则**整段省略**——⛔ 不编造、⛔ 不为它改 schema。CONTEXT / ROADMAP 的文案承诺了版本号，这条差异在此显式登记。

⚠️ **这条差异与「水印不可关闭」这条不变量无关**：断言只锁「首行是 `> ⚠️ 未经确认`」与「白名单外一律有、白名单内一律无」，⛔ 没有任何断言依赖版本片段。

`status_label` 用状态字面量本身（⛔ 不引前端 i18n）；`blueprint_status == ""` 时降级为 `未知`（`test_watermark_absent_status_falls_back_to_unknown_label`）——⛔ 不留白，否则首行会出现「当前状态：）」这种残句。

## ⭐ 4. 十段 + 附录的 markdown 版式说明

实测渲染出的 heading 树（`## 决策记录` 与 `## 引用清单` 是两个附录）：

```
# {meta.title}
## 需求规格      → ### 目标 / ### 背景 / ### 功能点
## 仓库关联
## 现状分析      → ### 仓库 {repository_id}（逐仓一节）
## 实现概述      → ### 需求叙事 / ### 功能模块 / ### 实现项 / ### 实现项详情
## API 契约      → ### 契约说明
## 影响范围      → ### 业务影响 / ### 受影响功能 / ### 回归范围 / ### 兼容风险与回滚
## 交互流程      → ### {flow.name}（{flow.id}）（逐流程一节）
## 验收锚点      → ### 可观察行为断言 / ### 必须存在的产物 / ### 关键链接
## 决策记录
## 引用清单
```

`meta.summary` 非空时另出一节 `## 执行摘要`（空则整节不渲染，⛔ 不留空标题）。

**版式保守三条**（`[MEDIUM]` §C.4 A2，`markdown_to_blocks` 表达力上界未逐行核过）：

| 约束 | 落地 | 断言 |
|---|---|---|
| heading **≤3 级** | 最深是 `###` | `test_headings_never_exceed_level_three` 逐行数 `#` |
| 表格**不嵌套** | 每个表格一个 `_build_*_table`，cell 一律经 `_md_escape`（`\|` → `\\\|`、换行 → 空格） | 同上用例断言 `[^` 零命中 |
| 脚注用**普通列表** | `**本段引用**` + `- …` 列表，⛔ 不用 `[^n]` 语法 | `test_citation_footnotes_use_plain_list_per_section` |

**表格列序**（导出物与外部消费方的契约）：

| 段 | 列 |
|---|---|
| 功能点 | 功能点 id / 标题 / 意图 / 验收标准 |
| 仓库关联 | 仓库 / 角色 / 职责 / 选仓理由 |
| 现状分析 findings | 结论 id / 类型 / 主题 / 结论 |
| 功能模块 | 模块 id / 模块名 / 覆盖功能点 / 涉及仓库 |
| 实现项 | 实现项 id / 标题 / 功能点 / 仓库 / 变更类型 / 波次 |
| API 契约 | 契约 id / 名称 / 接口类型 / 方向 / 方法 / 路径 / 归属仓库 |
| 受影响功能 | 既有功能 / 影响类型 / 涉及仓库 / 影响描述 |
| 回归范围 | 回归区域 / 回归级别 / 理由 |
| 交互流程 steps | 序号 / 执行方 / 动作 / 组件 / 接口 / 输入数据 / 输出数据 |
| 必须存在的产物 | 产物路径 / 提供什么 |
| 关键链接 | 从 / 到 / 经由 |
| **决策记录** | 问题 / 结论 / 决策人 / 生效版本 |

**零行一律补一行 `| — | … |`**（analog `coding_plan_exporter._build_affected_files_table:215-217`）；缺字段一律降级 `—`，⛔ 不留白。

### `decision_log` 的防御口径

`decision_log` 是**零约束裸 array**（`blueprint_schema.py:733-736`：不在顶层 `required`、不进 `iter_blocks`）⇒ 114-04 写入的那组键（`blueprint_reflow.DECISION_LOG_KEYS`：`thread_id` / `question` / `answer` / `decided_at` / `decided_by` / `applied_in_version`）是**约定不是契约**。逐项 `.get` 防御、缺键渲染 `—`（`test_decision_log_missing_keys_degrade_to_placeholder`，只有 `question` 的记录**不抛**）；⭐ **特别保 `answer` 与 `applied_in_version`**（`test_decision_log_keeps_answer_and_applied_in_version`）—— §3.13 的存在意义就是「文档自包含、导出不丢决策」，丢了这两个键等于把结论和它生效的版本一起丢了。

### 引用脚注

每段末尾以**普通列表**给出该段引用的 `title` + 来源类型 + 可点链接。链接取值链：`citation.url` → `locator.url` → `locator.link` → `source_id`（必须以 `http(s)://` 开头）。⭐ **取不到链接就落 `title` / `quote` 快照（≤120 字），⛔ 不留白**（`test_citation_without_link_falls_back_to_quote_snapshot`）。段末脚注只收集**该段子树**里的 `citations` id（`_collect_citation_ids` 递归、去重保序）；文末 `## 引用清单` 再给**全量引用池**，含没被任何块引用的条目。

### ⛔ 批注不导出是天然满足的

`BlueprintThread` 本就不在 content 里（DESIGN §6.2），渲染器只读 content ⇒ **⛔ 零过滤代码**。`test_threads_never_appear_and_there_is_no_filter_dead_code` 用 AST 剥掉模块 docstring 后断言 `BlueprintThread` 在代码里零命中 —— ⭐ **逐条人工核对结论**：`rg "BlueprintThread|thread" blueprint_render.py` 的**全部命中只有 1 处**，落在模块 docstring 第 (d) 段那句「批注不导出是天然满足的 ⇒ 不写过滤代码」，代码区零命中。

## ⭐ 5. 块取文本与锚点坐标系同源

`_block_text` **委托** `delivery.services.blueprint_anchor._block_text`（⛔ 零副本，与 116-04 normalizer 同款分工）：字段优先级 `text`（str 直取 / list 逐条 join）→ `code.source` → `rows` 扁平 join，**完全不看块自身的类别字段**。

- 源码扫描：`def _block_text` 起 900 字符内 `"type"` / `'type'` **零命中**（验收脚本输出 `block text priority OK`）。
- ⭐ **证伪用例** `test_block_text_does_not_dispatch_on_block_type`：类别是 `pseudocode` 但 `text` 非空 ⇒ **仍按 `text` 取**，且 `code.source` 的内容**不出现**在输出里。

## ⭐ 6. 两个端点的契约表

| 项 | 导出 | availability |
|---|---|---|
| URL | `/api/delivery/artifacts/<uuid:artifact_id>/blueprint/export-feishu/` | `…/blueprint/export-feishu/availability/` |
| `name` | `blueprint-export-feishu` | `blueprint-export-feishu-availability` |
| 方法 | `POST` | `GET` |
| 权限 | `IsAuthenticated` + `_aassert_project_scope` | 同左 |
| 入参 | 可选 body `{"version_id": "<uuid>"}`（缺省最新一版） | 无 |
| 响应键 | `document_id` / `url` / `version_no` / `exported_at` | `available` / `reason`（⭐ **两键逐字**） |
| 200 | 导出成功 | 恒 200（可用性在 body 里） |
| 400 | `version_id` 非 UUID／`meta.project_id` 读不到（闸 fail-closed）／availability 不满足／上游配置权限类 | `meta.project_id` 读不到（闸 fail-closed） |
| 404 | artifact 不存在／**非成员**（逐字相同）／version 不属于该 artifact | artifact 不存在／**非成员**（逐字相同） |
| 401/403 | 未认证 | 未认证 |
| 502 | 上游限流／超时／其它 `FeishuDocAPIError` | — |

## ⭐ 7. 400 vs 502 分档对照表（`[MEDIUM]` 假设在此解除）

逐类核过 `server/services/feishu_doc.py:27-53` 后定案：

| 上游形态 | 异常类（`feishu_doc.py`） | 触发条件 | 状态码 | `detail` |
|---|---|---|---|---|
| 无权限 | `PermissionDeniedError`（`FeishuDocAPIError` 子类） | `PERMISSION_CODES = {91003, 91004, 91204, 95008, 95009, 99991672}` 或 msg 含 `forbidden` | **400** | `_EXPORT_CONFIG_DETAIL` |
| 资源不存在（文件夹/文档） | `DocumentNotFoundError` | `NOT_FOUND_CODES = {1002, 18066, 91402, 95006, 95007}` | **400** | `_EXPORT_CONFIG_DETAIL` |
| 凭证缺失 | `ValueError`（`create_feishu_doc_client_for_project` 抛） | 空间级与系统级凭证都拿不到 | **400** | `_EXPORT_CONFIG_DETAIL` |
| 限流 | `RateLimitError` | code `99991400` 或 msg 含 `rate limit`（tenacity 已重试 3 次仍失败） | **502** | `_UPSTREAM_UNAVAILABLE_DETAIL` |
| 其它上游错误 / 超时 / 无 `document_id` | `FeishuDocAPIError` 与任何未预期异常 | 兜底 | **502** | `_UPSTREAM_UNAVAILABLE_DETAIL` |

**判据取 `isinstance` 而非重新解析错误码**：`feishu_doc` 内部已经把 `PERMISSION_CODES` / `NOT_FOUND_CODES` / `99991400` 转成了这三个异常类，端点再解析一次等于复制一份会漂移的映射。

两档的 `detail` 都是**中性常量**：

- `_EXPORT_CONFIG_DETAIL = {"detail": "飞书导出不可用：请检查空间的导出文件夹与飞书应用凭证配置"}`
- `_UPSTREAM_UNAVAILABLE_DETAIL = {"detail": "飞书文档服务暂时不可用，请稍后重试"}`

⭐ **异常原文只经 `redact_secrets_in_text(str(exc))[:500]` 进日志、⛔ 绝不进响应体**：用例构造含 `secret-token-xyz` 的上游错误文本，四个参数化档位（`PermissionDeniedError` / `DocumentNotFoundError` / `RateLimitError` / `FeishuDocAPIError`）都断言它**不出现在 `resp.content` 里**。⭐ 这一段的 `try/except` 是**为了分档回错、不是为了吞掉**（115-MJ-04）：`test_upstream_failure_is_never_a_silent_200` 是它的反面对照。

## ⭐ 8. availability 三判据的判据链与 space 反查

| # | 判据 | `reason` |
|---|---|---|
| ① | 蓝图 `meta.project_id` → `initiatives.Project` → `Project.space` 反查不到 | `no_space` |
| ② | `space.feishu_doc_folder_token` 为空 | `no_folder_token` |
| ③a | `space.feishu_app_id` **且** `space.feishu_app_secret_encrypted` 都非空 | `null`（`available: true`） |
| ③b | 否则 `_aget_system_feishu_credentials_for_doc()` 可得系统级凭证 | `null`（`available: true`） |
| ③c | 两级凭证都拿不到 | `no_credentials` |

⭐ **与 `chat/views.py:1740-1781` analog 的两处必须差异**：

1. **权限类换掉**：analog 用 `ChatAuthPermission` + `OptionalJWTAuthentication`；本端点是 `IsAuthenticated` + `_aassert_project_scope`。
2. ⭐ **space 来源换掉**：analog 从 `?space_id=` 取（**调用方可控**）；本端点**只从蓝图自身的 `meta.project_id` 反查**。范围闸认的就是这个 project_id，两者不同源会出现「闸放行项目 A、文档写进空间 B」。
   - ⚠️ 推论：`Project.space` 是**非空 FK** ⇒ 只要项目存在，空间必然存在 ⇒ `no_space` 只在「`meta.project_id` 不是合法 UUID 或项目不存在」时出现，而那两种情形对普通成员**已被范围闸拦成 400/404**。⇒ `no_space` 的**唯一可达路径是 superuser 直通**，用例 `test_availability_no_space_when_project_unresolved` 就是照这条路径写的。analog 的 `space_not_found` 这个第四 reason 在本端点**不可达**，故不实现（⛔ 不留死分支）。

`{available, reason}` **两键逐字**由 `test_availability_returns_exactly_two_keys`（`set(body) == {"available", "reason"}`）锁死 —— 前端据此**隐藏按钮**，键名一改按钮就会在不可用时照样渲染。

## ⭐ 9. 留痕落点清单与「不污染任何既有面」的核算证据

| 落点 | 内容 |
|---|---|
| **Interaction Ledger** `InteractionRun` | `source="blueprint_export"`、`token_fingerprint=f"user:{id}"`（JWT 路径无 `token_hash`，与 `interactions/entry.py:72-76` 同款降级）、`request_id` 取 `X-Request-ID`、`raw_request={method, path}`、`status=COMPLETED` |
| **Interaction Ledger** `InteractionEvent`（`TOOL_RESULT`） | `{event: "blueprint_exported_to_feishu", artifact_id, version_no, document_id, url, exported_by, exported_at}`（写库前经 `redact_for_ledger`） |
| **caller 结构化事件** `blueprint_exported_to_feishu` | `category="caller"` / `component="blueprint_export_api"` / `artifact_id` / `initiated_by_user_id` / `duration_ms` / `version_no` / `document_id` / `url` / `status_label` / `markdown_len`（⛔ 只记长度，蓝图正文不进日志） |
| **caller 事件** `blueprint_export_availability_read` | `available` / `reason` |
| **caller 事件** `blueprint_export_feishu_failed` | `stage`（`availability` / `upstream`）/ `status_code` / `error`（经 `redact_secrets_in_text` 截断 500 字） |

⭐ **留痕是 best-effort（`_arecord_export_ledger` 包 `try/except: pass`），业务主体不是** —— 记不上账不能让一次已经成功的导出回错。

**核算证据**：

| 禁区 | 证据 |
|---|---|
| ⛔ 不写 `ArtifactVersion.content` | `test_export_does_not_create_a_new_artifact_version`：导出前后**版本计数不变**、`current_version_id` 不变、`content_hash` 不变；AST 扫描断言模块标识符里无 `add_version` |
| ⛔ 不进 `BLUEPRINT_EVENTS` | `test_export_event_is_not_in_blueprint_events`：`"blueprint_exported_to_feishu" not in BLUEPRINT_EVENTS` 且 `len(BLUEPRINT_EVENTS) == 21`；`git diff $PHASE_BASE -- server/delivery/services/event_taxonomy.py` **为空** |
| ⛔ 不产 `ConvergenceSessionEvent` | 同一用例断言导出前后计数不变；AST 扫描断言标识符里无 `ConvergenceSessionEvent` |
| 正向对照（⛔ 不是「哪都没记」） | `test_export_writes_an_interaction_ledger_run`：从 DB 重读 `InteractionRun(source="blueprint_export")` 与其 `InteractionEvent.payload` |

⭐ AST 扫描而非字符串扫描是刻意的：模块 docstring 与分节注释里**逐字写着这些禁令**，文本判据会把「写清楚为什么不做」判成「做了」（首轮实跑就是这么转红的）。

## 10. 前端两处改动的 props/emits 与 toast 分档

| 项 | 逐字 |
|---|---|
| 新增 prop | `exportAvailable?: boolean`（默认 `false`）、`exporting?: boolean`（默认 `false`） |
| 新增 emit | `'export': []` |
| 横幅 testid | `blueprint-unconfirmed-banner` |
| 按钮 testid | `blueprint-header-export` |

**导出按钮的三条纪律**：

1. ⭐ `exportAvailable !== true` ⇒ 按钮**不存在于 DOM**（⛔ 不是 disabled + tooltip）。用例断言的是 `.exists()).toBe(false)`。
2. `disabled` **只表达「导出在途」**（`exporting`），⛔ 不表达「不可用」——`test disabled 只表达「导出在途」` 把两者并列钉死。
3. ⭐ **组件只 emit、不发请求**：点击 ⇒ `emitted('export')` 恰 1 次，两个 api 函数 mock **零调用**；另加源码扫描断言组件里 `exportBlueprintToFeishu` / `getBlueprintExportAvailability` 零命中。

**横幅不可关闭的核算**：`rg "dismiss|close|v-if=\"!dismissed\"" BlueprintViewerHeader.vue` —— ⭐ **逐条人工核对结论：横幅段零命中**（全文件的 `close` 命中只有既有的 `icon-[lucide--panel-left-close]` 侧栏折叠图标，与横幅无关）；用例另断言 `${BANNER} button` 与 `${BANNER} [aria-label*="关闭"]` 都不存在。

**页面侧 toast 分档表**：

| 状态码 | 行为 |
|---|---|
| **200** | `toast.toast.success(t('…export.success'), { description: url, action: { label: t('…export.openDoc'), onClick: () => window.open(url, '_blank', 'noopener') } })` —— ⭐ 给**可点**文档链接 |
| **400** | `toast.error(error.detail)`（原样回显后端中性 detail，与页面既有 `reportFailure` 的 400 分支同口径） |
| **502 / 其它** | `toast.error(t('…export.unavailable'))`（「飞书文档服务暂时不可用，请稍后重试」） |

⛔ **零乐观更新**；⭐ **⛔ 不 invalidate `['blueprint']` 前缀** —— 导出不改任何蓝图状态，失效等于白刷五个查询（`no needless invalidate OK` 验收脚本已跑过）。

### ⭐ 两处额外前端改动的理由与删除行登记

| 文件 | 理由 | 删除行 |
|---|---|---|
| `web/src/pages/knowledge/blueprints/[id].vue` | 组件只 emit ⇒ availability 查询与导出 mutation 必须归页面（115-04 立的纪律）。纯追加：一个 `useQuery` + 一个 `exporting` ref + 一个 `onExportToFeishu` + 三行 props/emit 接线 | **0**（计划上界 4） |
| `web/src/locales/zh-CN.json` | 横幅 / 按钮 / 三档 toast 的文案（⛔ 组件内零中文硬编码）。新增 `knowledge.blueprints.export` 子树五键，插在 `viewer` 与 `mustHaves` 之间 ⇒ 无既有行需要补逗号 | **0** |

`availability` 查询走 **`gateQuery` 同款例外**：它的任何非 200 都**不进错误分档**——只决定按钮是否渲染，⛔ 不弹 toast、⛔ 不影响四个主查询驱动的页面状态。

## ⭐ 11. 存在性暴露口径分歧的登记（C5）

本 plan 的两个导出端点 **import 复用 `blueprint_review_views._aassert_project_scope`**（含它的 **400 分支**：读不到 `meta.project_id` 一律 400 fail-closed），而 116-01 给 `blueprint-gate/` 八端点用的是**更严变体**（两个失败分支同一中性 404）。

**取舍理由（逐字）**：

- **新端点走 400 变体是为「单一实现」**（MJ-03）：范围闸的四条语义**只能有一份实现**，⛔ 不造第四份可漂移的副本。代价是 115-MN-03 的暴露面从 11 个端点扩到 **13** 个。
- **gate 链走 404 变体**是因为它的 404 本就混合「门未开启」「artifact 不存在」「无蓝图编排会话」三种语义、且 115-07 前端按「非 200 只决定挂载点是否渲染」实现 ⇒ 在那条链上改 400 反而**新开**一种可区分状态。

⭐ **MN-03 的四语义契约整体改版仍是独立工作项**，不在本 plan 范围内。

⚠️ **本 plan 只登记「贡献 +2」，⛔ 不改 STATE 里 MN-03 那条 Pending Todo 的计数** —— 该计数由 116-06 一次改到位（11 → 15，含它自己的两个 MCP 工具），避免同一条 todo 被两个 plan 先后改成两个数。

## 12. 受限面删除行逐行核算

| 文件 | 计划上界 | 实测 | 说明 |
|---|---|---|---|
| `server/delivery/artifacts/builtin_types.py` | 3 | **2** | ✅ 模块 docstring 首行 + 「renderer 分支归 115/116」占位话术行 |
| `server/delivery/api/artifact_serializers.py` | 2 | **0** | ✅ 纯插入（既有 `return render_markdown(...)` 逐字保留为回落分支） |
| `server/delivery/urls.py` | 0 | **0** | ✅ |
| `server/tests/delivery/test_blueprint_log_redaction_guard.py` | 0 | **0** | ✅ 追加 2 行 |
| `web/src/api/blueprints.ts` | 1 | **0** | ✅ 两个新名字追加在 `export default` 末尾，无需重排 |
| `web/src/components/blueprint/BlueprintViewerHeader.vue` | 4 | **0** | ✅ |
| `web/src/pages/knowledge/blueprints/[id].vue` | 4 | **0** | ✅ |
| `web/src/locales/zh-CN.json` | 0 | **0** | ✅ |

**冻结面核算（`git diff $PHASE_BASE -- <file>` 逐个为空）**：`server/services/process_runtime/render.py`（§13.2 冻结六文件之一）、`server/delivery/artifacts/registry.py`、`server/delivery/api/blueprint_review_views.py`、`server/delivery/services/event_taxonomy.py`、`web/src/components/delivery/ArtifactTimeline.vue`、`web/src/components/chat/TechPlanCard.vue`、`web/src/components/chat/RoutingDecisionPanel.vue`、`web/src/components/execution/NodeDataTab.vue`、`server/codegraph/services/repo_router_v2.py` —— **输出全空**。

**相位边界**：`git diff $PHASE_BASE --name-only` 共 **14** 个文件 —— 计划声明的 13 个，外加 `server/tests/delivery/test_blueprint_inv6_guard.py`（见 Deviations D-1）。

**环境项核算**：`pnpm build` 重写了 `web/src/components.d.ts`（裁掉 29 条无关条目），已 `git checkout --` 还原；本 plan 未新建组件文件，该文件保持零变更。`web/pnpm-workspace.yaml` 本轮**未发生漂移**。`git status --porcelain web/pnpm-workspace.yaml web/src/components.d.ts` **为空**。

## 13. 门与基线比对

| 门 | 基线（116-04 后） | 本 plan | 结论 |
|---|---|---|---|
| `cd server && uv run pytest tests/ -q` | 8772 passed / 1 failed（`test_skills_snapshot_guard::test_skill_files_discovered`，worktree 环境产物） | **8844 passed / 1 failed**（同一条，且仍是唯一一条） | ✅ 无新增失败。+72 = 渲染器 35 + 端点 34 + 脱敏守卫参数化 +2 + INV-6 豁免反向对照 +1 |
| `makemigrations --check --dry-run` | exit 0 | **exit 0**（`No changes detected`） | ✅ 零 migration |
| `cd web && pnpm exec vitest run` | 1676 passed / 1 skipped | **1697 passed / 1 skipped**（新 spec 21 条） | ✅ 无新增失败 |
| `pnpm type-check` | exit 0 | **exit 0** | ✅ |
| `pnpm build` | 通过 | **通过**（`✓ built in 6.08s`） | ✅ |
| `pnpm exec eslint <触及的 4 个前端文件>` | 全仓 111 problems | 触及文件 **零输出**（exit 0） | ✅ 零新增 |
| `ruff check` / `ruff format --check`（新建与触及文件） | — | 通过 | ✅ |

## ⭐ 14. 一次真实飞书导出验证（`[MEDIUM]` A2 的登记）

⚠️ **未具备飞书凭证，真实导出验证未执行 ⇒ 版式退化风险未消解**（⛔ 不默默跳过，此处显式登记）。

已做的替代核验（覆盖「渲染侧」，不覆盖「飞书 `markdown_to_blocks` 转换侧」）：

- heading 层级 ≤3 有逐行断言；`[^n]` 脚注语法零命中有断言；表格 cell 的 `|` 与换行经 `_md_escape` 转义。
- 端点用例经 patch **捕获传给 `create_document` 的 markdown 实参**并断言十段结构与水印都在 —— 即「送进飞书的那份字符串」本身是对的。

**残余风险**：`markdown_to_blocks` 对**多列表格**（最宽 7 列）、**表格 cell 内的转义竖线**、**heading 与列表混排**的表达力未逐行核过；退化只会影响版式呈现，⛔ **不影响正确性与标注**（水印是一行 `> ` blockquote，是 markdown 里表达力风险最低的形态之一）。建议 116-06 或首次生产导出后补一次观察记录。

## ⭐ 15. VIEW-05 的验收映射表

| VIEW-05 的分句 | 兑现用例 |
|---|---|
| **导出含六段全量 + 需求规格 + 验收锚点** | `test_all_sections_are_rendered`（11 个 heading + 8 个各段真实数据 token）；端点侧 `test_exported_markdown_carries_the_watermark_for_unconfirmed` 断言送进 `create_document` 的 markdown 含 `## 需求规格` |
| **导出含决策记录附录** | `test_decision_log_missing_keys_degrade_to_placeholder` / `test_decision_log_keeps_answer_and_applied_in_version`；端点侧同一用例断言含 `## 决策记录` |
| **导出含引用（脚注）** | `test_citation_with_link_renders_clickable_markdown_link` / `test_citation_without_link_falls_back_to_quote_snapshot` / `test_citation_footnotes_use_plain_list_per_section` |
| **批注不进导出物** | `test_threads_never_appear_and_there_is_no_filter_dead_code` |
| **未确认版本的「导出物」带标注** | `test_watermark_is_the_first_line` + `test_every_other_status_renders_the_watermark`（11 参数）+ 端点侧 `test_exported_markdown_carries_the_watermark_for_unconfirmed`（`pending_review` 有 / `confirmed` 无） |
| **未确认版本的「界面」带标注** | 前端 `已确认态 %s 不出横幅`（3 参数）+ `未确认态 %s 出横幅`（10 参数）+ `横幅不可关闭` |
| **两个面共用同一判据** | 后端 `test_whitelist_literals_match_blueprint_status_enum` + 前端 `前后端白名单逐字对齐`（读后端源码比对）+ 两侧变异实跑 |
| **`current_version_markdown` 的空壳修掉（P-4 第二个面）** | `test_timeline_serializer_passes_the_real_status`（两参数：`confirmed` 无水印 / `pending_review` 有水印，且两者都断言 `## 需求规格` 与 `## 交互流程` 在 ⇒ ⛔ 不是 v0 空壳）+ `test_registry_branch_passes_empty_status_and_keeps_the_watermark`（注册表路径出标注）+ `test_registry_branch_leaves_v0_content_untouched`（反向对照：v0 行为零变化） |
| **导出可用性驱动界面** | `test_availability_*` 五条 + 前端「按 availability 隐藏」三条 |

## Deviations from Plan

### D-1 [Rule 3] `blueprint_status=` kwarg 撞上 INV-6 字段守卫 ⇒ 加一条极窄的逐行豁免（额外文件 1 个）

**冲突**：`tests/delivery/test_blueprint_inv6_guard.py:57` 的 `_RE_FIELD_WRITE = r"\bblueprint_status\s*=\s*[^=]"` 把**任何** `blueprint_status=` 赋值/kwarg 判为旁路写。而本 plan 的 PLAN 明令：签名恰为 `(content, *, blueprint_status)`、`rg 'blueprint_status=""' builtin_types.py` **必须命中**。两条要求在计划内互相矛盾 —— 只要 renderer 的参数叫这个名字，调用点就必然写出 `blueprint_status=`。

**取舍**：守卫的靶子是「绕过 `BlueprintLifecycleService` 的 CAS 改状态」；把状态**读出来传进一个纯渲染函数**与它语义正交。⇒ 加 `_is_render_kwarg_line(line)` 逐行豁免，判据收得极窄：

- 同一行内**必须出现** `render_blueprint_markdown(`；
- 且**不得同时出现**任何写表形态（`setattr(` / `.objects` / `.update(` / `.save(`）。

新增「守护的守护」`test_inv6_render_kwarg_exemption_is_narrow`：先断言纯渲染调用行**本会**被字段级正则命中（证明豁免不是空转），再用三条**夹带写表形态的伪装行**（`setattr` + 注释、`.update(...)` + 注释、`x.blueprint_status = ...; save()` + 注释）断言它们**不被豁免**且仍被字段级正则命中。

**连带取舍**：为让调用点能写成**单行**（多行 `ruff format` 会把 kwarg 拆到独立一行、独立行拿不到函数名 ⇒ 豁免失效），状态读法收敛为 `blueprint_render.blueprint_status_of(artifact)`（纯 `getattr` 归一，三条正则均不命中）。PLAN Task 1 ③ 给的逐字写法 `blueprint_status=str(getattr(obj, "blueprint_status", "") or "")` 语义**逐字保留**在该 helper 里，且两个权威面从此共用一份归一口径（⛔ 不各写一份）。

### D-2 [Rule 3] 三条源码扫描断言从「字符串扫描」改为「AST / 剥 docstring 后扫描」

PLAN 的验收脚本形态是 `rg -n "<token>" <file>` 零命中。实跑三处转红，**全部**是因为本模块的 docstring 与分节注释里**逐字写着那条禁令**：

| 断言 | 转红原因 | 改法 |
|---|---|---|
| `blueprint_render.py` 无批注过滤死码 | docstring 第 (d) 段写着「`BlueprintThread` 本就不在 content 里」 | AST 剥掉模块 docstring 后再扫 |
| `blueprint_export_views.py` 零 `BLUEPRINT_EVENTS` | docstring 与分节注释各写了一次「⛔ 不进 `BLUEPRINT_EVENTS`」 | 改为 AST 遍历取**真正被用到的标识符集合**（`Name.id` / `Attribute.attr` / `alias`）后比对 |
| `blueprint_render.py` 零布尔开关参数 | 首版 docstring 举例写了 `include_watermark` | 改写措辞为「『要不要加水印』之流」，字符串扫描保留 |

⭐ **判据强度不降反升**：AST 判的是「有没有真的用」，比字符串判的「有没有出现」更准，且不再惩罚「把为什么不做写清楚」。

### D-3 [Rule 3] `error=` 实参逐字内联脱敏，⛔ 不包 helper

首版写了 `error=_safe_error_text(exc)`（内部走 `redact_secrets_in_text`）。实跑 `test_blueprint_log_redaction_guard` **转红**：该守卫 AST 扫描 `error=` 实参的源码片段，判据是**片段里出现 `_REDACTORS` 之一的名字**，包一层 helper 会让守卫失明。⇒ 改为逐字内联 `error=redact_secrets_in_text(str(exc))[:_ERROR_TEXT_CHARS]`，并在旁边写明「⚠️ 逐字内联而不是包 helper，因为守卫认的是实参里出现脱敏函数名」。

### D-4 [Rule 3] 「读不到 `meta.project_id`」的用例形态改为**非 UUID 取值**

PLAN 用例 3 要求「读不到 `meta.project_id` ⇒ 400」。实跑发现 `meta.project_id` 在 `blueprint_schema.py:145` 是**必填**（`ArtifactService.create` 直接抛 `ArtifactContentInvalid`）⇒ 「缺失」这个形态**造不出来**。闸的判据是 `_is_uuid(project_id)`，缺失与非法**同归 fail-closed 400** ⇒ 用例改造成 `project_id = "not-a-project-uuid"`，语义等价且可达。

### D-5 [Rule 2] availability 不实现 analog 的第四个 reason `space_not_found`

`chat/views.py:1766` 有 `space_not_found`（`Space.objects.aget` 抛 `DoesNotExist`）。本端点的 space 是经 `Project.space` 反查的**非空 FK** ⇒ 「项目在但空间不在」在物理上不可能。实现它等于留一条永远走不到的死分支，还会让前端以为要处理四种 reason。⇒ 三 reason（`no_space` / `no_folder_token` / `no_credentials`），并在 §8 登记推论与 `no_space` 的唯一可达路径（superuser 直通）。

### D-6 [Rule 2] 上游异常兜底用 `except Exception` 而非只兜 `FeishuDocAPIError`

PLAN 只点名了 `FeishuDocAPIError` 系列。但 `create_feishu_doc_client_for_project` 在凭证缺失时抛的是 **`ValueError`**（`feishu_doc_tools.py:80`），不兜就会变成 500 + traceback（可能带凭证片段）。⇒ 兜 `Exception` 并交给 `_classify_upstream_error` 分档：`ValueError` 落 400（配置类），未预期异常兜底落 502。⭐ **这不违反「业务主体不包 best-effort」**：分档之后一律**如实回错**，⛔ 没有任何一条路径回 200。

### 无 Rule 4（架构决策）触发，无 checkpoint。

## Known Stubs

无。两个端点接的都是真实上游链路（单测经 mock client 注入），前端横幅与按钮消费的都是真实响应字段；`decision_log` / `citations` 的「—」是真实的「该条目缺这个键」，不是占位实现。

## Self-Check: PASSED

五个新建文件（`blueprint_render.py` / `blueprint_export_views.py` / 两个后端测试 / 一个前端 spec）与本 SUMMARY 均存在于磁盘；三个 commit（`6346eb5c` / `87ed1598` / `7ad94c5f`）均可在 `git log` 中定位。

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: network-egress | `server/delivery/api/blueprint_export_views.py` | 本 plan 新增了蓝图链**第一条对外出网写路径**（整份蓝图正文 → 飞书云文档）。已在 PLAN 的 T-116-40/41/44 内登记并逐条 mitigate（范围闸 + 中性 404 + 中性 detail + 异常脱敏 + 不静默 200）；此处另标出来是因为它把「越权读」的后果从「看到正文」升级为「正文落到攻击者可见的外部文档系统」，后续任何放宽范围闸的改动都必须重新评估这条 |

新增的两个 REST 入口均走既有 `IsAuthenticated` + 项目范围闸，未改 schema、未新增 migration、未新增运行时依赖。
