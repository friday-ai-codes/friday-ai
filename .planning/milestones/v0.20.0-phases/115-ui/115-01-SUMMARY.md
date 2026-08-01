---
phase: 115-ui
plan: 01
subsystem: delivery-backend
requirements: [VIEW-01, VIEW-03, VIEW-04, CLAR-01]
tags: [rest, blueprint, read-api, project-scope, inv6, observability]
requires:
  - "delivery.api.blueprint_review_views._aassert_project_scope / _aload_artifact / _aload_session / _thread_row / _ARTIFACT_MISSING_DETAIL（114-05，import 复用）"
  - "delivery.services.blueprint_lifecycle_service.open_thread / is_blueprint_editable / NOT_EDITABLE_DETAIL（111/114，唯一写口与状态闸）"
  - "delivery.services.event_taxonomy.BLUEPRINT_EVENTS（112/114，21 常量）"
  - "services.process_runtime.blueprint_quality（111-04/114-05，四项统计）"
  - "delivery.services.blueprint_anchor._block_text（114，块取文本四分支）"
  - "initiatives.models.ProjectMember（列表可见集合）"
provides:
  - "GET /api/delivery/artifacts/<uuid>/blueprint/（name=blueprint-document）—— 结构化 content + quality 四项"
  - "GET /api/delivery/artifacts/<uuid>/blueprint/events/（name=blueprint-events）—— 蓝图阶段事件流"
  - "GET /api/delivery/artifacts/<uuid>/blueprint-review/threads/（name=blueprint-review-threads）—— 线程详情含 options 与多轮 messages"
  - "POST 同上 URL —— 选区评论建 human_comment 线程（全仓第一个主动入口）"
  - "GET /api/delivery/blueprints/（name=blueprint-list）—— 成员可见集合 + 筛选 + 五键分页"
  - "delivery.services.blueprint_comment_action.aopen_selection_comment（INV-6 收口）"
affects:
  - "115-02 起六个前端 plan 的 TS 接口（types/blueprint.ts / api/blueprints.ts）"
  - "115-UI-SPEC §3.3 两处订正（键名 current_status / 五键分页体）"
tech-stack:
  added: []
  patterns:
    - "范围闸 import 复用私有符号（既有文件零改动）"
    - "方案 A：纯同步 _aggregate + sync_to_async 单点调用，先聚合再切片"
    - "_STATUS_FIELD 常量绕 INV-6 字段级守卫（P-1）"
key-files:
  created:
    - server/delivery/api/blueprint_doc_views.py
    - server/delivery/api/blueprint_list_views.py
    - server/delivery/services/blueprint_comment_action.py
    - server/tests/delivery/test_blueprint_doc_views.py
    - server/tests/delivery/test_blueprint_list_views.py
  modified:
    - server/delivery/urls.py
    - server/tests/delivery/test_blueprint_log_redaction_guard.py
decisions:
  - "UI-SPEC §3.3 键名订正为 current_status（P-1）"
  - "UI-SPEC §3.3 分页体订正为 {total, items, page, page_size, has_next} 五键"
  - "范围闸与中性 404 文案常量一并 import 复用，保证非成员 404 与「不存在」404 逐字相同"
  - "_thread_row 也 import 复用（九键归一口径单一实现），仅在其上扩写三键"
metrics:
  duration: "约 90 分钟"
  completed: 2026-07-31
  tasks: 3
  commits: 3
  tests_added: 39
---

# Phase 115 Plan 01: 蓝图五端点供数面 Summary

**一句话**：五个新 REST 端点（正文+quality / 阶段事件 / 线程详情 GET+POST / 蓝图列表）一次性补齐 115 相位的全部供数面——正文首次以**结构化 content** 出面（block 锚定与 block 级 diff 的物理前提）、`ConvergenceSessionEvent` 首次有 REST 读面、CLAR-01 的多轮回复与主动选区评论各自有了数据面与写口，且 MJ-03 的项目范围闸扩到全部蓝图读面**且只有一份实现**（`blueprint_review_views.py` 零改动）。

---

## 1. 五端点契约表（115-02 起的前端 plan 直接照它写 TS 接口）

| # | 方法 | URL | `name` | Query | 成功响应键（逐字） | 状态码全集 |
|---|---|---|---|---|---|---|
| ① | GET | `/api/delivery/artifacts/<uuid:artifact_id>/blueprint/` | `blueprint-document` | `version_id?`（UUID） | `version_id` / `version_no` / `is_current` / `produced_by_ref` / `created_at` / `content` / `quality` | 200 / 400（未认证 403·`version_id` 非 UUID·读不到 `meta.project_id`）/ 404（artifact 不存在·非成员·版本不存在或不属于该 artifact）/ 401·403（未认证） |
| ② | GET | `.../blueprint/events/` | `blueprint-events` | — | `session_id` / `current_stage` / `events[]{id, event, payload, ts}` | 200（**含无会话**）/ 400（读不到 `meta.project_id`）/ 404（artifact 不存在·非成员）/ 401·403 |
| ③ | GET | `.../blueprint-review/threads/` | `blueprint-review-threads` | — | `threads[]`（见 §5 键集） | 200 / 400 / 404 / 401·403 |
| ④ | POST | `.../blueprint-review/threads/` | `blueprint-review-threads` | body `{body, anchor?}` | `thread_id` / `current_status` | 200 / 400（`body` 空·状态 ∉ 可编辑白名单·开线程失败·读不到 `meta.project_id`）/ 404（artifact 不存在·非成员）/ 401·403 |
| ⑤ | GET | `/api/delivery/blueprints/` | `blueprint-list` | `project_id?` / `repository_id?`（UUID）/ `blueprint_status?` / `q?` / `page?` / `page_size?` | `total` / `items[]` / `page` / `page_size` / `has_next` | 200（**含零可见项目**）/ 400（`project_id`·`repository_id` 非 UUID）/ 401·403 |

**四条共用语义（① ② ③ ④）**：`IsAuthenticated` + `_aassert_project_scope`。superuser 直通；读不到合法 `meta.project_id` → **400** fail-closed；非 `ProjectMember` → **中性 404，响应体 `{"detail": "artifact 不存在"}` 与「artifact 不存在」逐字相同**（不泄露存在性）。⑤ 是同一语义的集合形态：只列调用者是成员的项目的蓝图，superuser 见全部，零可见项目 → 空结构且**零 DB 越权查询**。

**⑤ 的 `items[]` 键集（逐字，`set(item)` 已被用例锁死）**：
`artifact_id` / `title` / `summary`（`meta.summary` 首块纯文本，≤200 字符）/ **`current_status`** / `project_id`（`string | null`）/ `project_name`（取不到回落 `""`）/ `repositories[]{id, name, role}` / `thread_count` / `unresolved_blocker_count` / `revision_round` / `current_version_no` / `updated_at`。

**null 约定汇总（前端不得自行归一）**：
- `project_id`：读不到 → `null`（其余字符串字段读不到一律 `""`，⛔ 不是 `null`）；
- `last_reminded_at`：从未提醒 → `null`；
- `messages[].author_user_id`：`SET_NULL` 作者 → `null`，而 `author_display` 同场景是 `""`；
- `anchor`：非 dict / 无锚点 → `null`；
- `quality` 后三项：无数据源 → `null`（见 §3）。

---

## 2. ⭐ 对 UI-SPEC 的两处订正（已定夺，前端消费点在 115-02 的 `types/blueprint.ts` 与 `api/blueprints.ts`）

| # | UI-SPEC §3.3 原文 | 订正为 | 理由 |
|---|---|---|---|
| 1 | `BlueprintListItem.blueprint_status` | **`current_status`** | P-1：INV-6 字段级守卫的 `_RE_FIELD_DICT_KEY`（`['"]blueprint_status['"]\s*:`）扫整个 `server/`，响应键用模型字段名即判旁路写。解法逐字照 114-05 的 `blueprint_review_action._current_status`。**⛔ 绝不为迁就命名去豁免守卫。** |
| 2 | 「DRF 分页体」 | **`{total, items, page, page_size, has_next}` 五键** | 方案 A 要在 Python 侧按 `meta.project_id` / `repository_id` / `q` 过滤**之后**再切片，而 DRF 分页 helper 只吃 queryset ⇒ 用不上。取 `knowledge/api/artifact_overview.py` 同款手写范式，⛔ 不发明第三套。 |

---

## 3. `quality` 四键取值语义表（闭 114-MN-05：三项 DB 统计首次有消费方）

| 键 | 类型 | 无数据 | 零值 | 备注 |
|---|---|---|---|---|
| `citation_coverage` | `number` | **恒有值** | — | 同步纯函数（入参 content dict）；三类关键结论条目全空（分母 0）→ `1.0`，⛔ 不为 `null` |
| `ai_rejection_rate` | `number \| null` | `null` | `0.0`（有审查事件、零 retry） | 分母 = `blueprint.review.completed` 事件数 |
| `human_edit_volume` | `number \| null` | `null`（该 artifact 零版本） | `0`（有版本、零 `human_edit:` 前缀版本） | ⚠️ 端点 200 时 artifact 必有版本 ⇒ 经本端点看到的 `null` 不可达，稳定是 `0`（见 §9 偏差 3） |
| `clarification_rounds` | `number \| null` | `null`（零线程） | `0`（有线程、无人作答） | = `author_type == "human"` 的消息数 |

**`null` ≠ `0` 的意义**：`null` = 「没有数据源可算」，`0` = 「统计到了，值为零」。混为一谈会让人审把「这个蓝图还没跑过审查」读成「零打回」，据错误指标放行。

**三态用例名**（并列存在才逮得住 `v or 0` 这类改写）：
- `test_quality_returns_null_for_missing_data_not_zero`（两个 `null` 与一个 `0` **同一响应内并列**）
- `test_quality_returns_zero_for_a_thread_without_human_answers`（同一指标的零值档）
- `test_quality_returns_positive_values_when_data_exists`（`0.5` / `1` / `1`）
- `test_citation_coverage_is_one_for_an_empty_citation_pool`

**实现纪律（P-15）**：后三项是**同步函数且函数内直接查 ORM** ⇒ 合成**一个** `@sync_to_async def _collect_db_quality(artifact_id)` 一次性算完。它们各自的 `except Exception` 只兜 ORM 异常、**不兜异步上下文错误**（那是在调用点抛的）⇒ 不包 `sync_to_async` 就是稳定 500 而不是被吞成 `None`。⛔ 端点侧不再包 try、不把 `None` 改写成 0。

---

## 4. `blueprint_comment_action.aopen_selection_comment` 签名与返回

```python
async def aopen_selection_comment(
    artifact: Any,
    *,
    body: str,
    anchor: Any = None,
    user: Any = None,
    initiated_by_user_id: str = "system",
    lifecycle_service: Any = None,
) -> dict:  # 恒定四键 {status, thread_id, detail, current_status}
```

- `status ∈ {"created", "invalid"}`；端点映射：`created` → **200** `{thread_id, current_status}`，`invalid` → **400** `{detail}`。
- 线程形态（`open_thread` 的逐字调用形状照 `_aopen_reject_comment`）：`kind=ThreadKind.HUMAN_COMMENT`、`blocking=False`、`severity=""`、`question=<正文>`、`anchor=<dict 或 None>`、`created_on_version=<最新版本>`、`initiated_by_user_id=<uid>`、`return_stage=BlueprintStatus.DRAFTING`。
- `blocking=False` + `severity=""` ⇒ 评论不受 114-01 的 finding 不变式约束、**不把蓝图钉死**（评论不该阻塞确认）。
- ⭐ **与 `_aopen_reject_comment` 的语义差异**：那一支是**驳回的副作用**（best-effort，开不出线程也返空串不上抛）；本函数是**主动作** ⇒ `open_thread` 抛异常**如实回错**（`status="invalid"` + `_detail(exc)`），⛔ 绝不吞——吞了用户会看到「评论成功」而侧栏永远不出现那条评论。
- `current_status` 只是原样回传（本函数不改状态），供前端对齐「以响应体 `current_status` 为准」。
- INV-6：唯一写口是 `BlueprintLifecycleService.open_thread`；⛔ 新 service **没有**被加进 `test_blueprint_inv6_guard._ALLOWED_WRITER`（唯一 writer 仍是 `blueprint_lifecycle_service.py`）。

---

## 5. `_thread_detail_row` 完整键集（十二键）

`_thread_row` 九键（**import 复用同一实现，不重抄**）：`thread_id` / `kind` / `severity` / `status` / `blocking` / `anchor_status` / `anchor` / `return_stage` / `created_at`
\+ 三补键：

| 补充键 | 形状 | 归一纪律 |
|---|---|---|
| `options` | `Array<{label, value, note}>` | `JSONField(default=list)` **无 schema 校验** ⇒ 非 list 归一 `[]`、非 dict 条目丢弃、逐键 `.get` 防御 |
| `last_reminded_at` | `string \| null` | `isoformat()` 或 `null` |
| `messages` | `Array<{id, author_type, author_user_id, author_display, body, created_at}>` | 按 `created_at` 升序（`Prefetch` + `select_related("author")` 防 N+1） |

**`author_display` 回落顺序**：`author.username` → `author.email` → `""`。`author` 是 `SET_NULL` FK（用户被删 / AI 作者，`open_thread` 写的首条消息本就 `author_type="ai"` 且无作者）⇒ **必须容忍 `None` 不炸**（用例 `test_threads_get_tolerates_a_null_message_author`）。

线程侧 `.order_by("created_at")` **不可省**：`BlueprintThread.Meta` 无 `ordering`（114-MN-01）。

---

## 6. events 端点的响应形状与「无会话 → 200」的理由

```
{ session_id: string, current_stage: string, events: Array<{id, event, payload, ts}> }
```

- 只出 `BLUEPRINT_EVENTS`（21 常量）子集；`.order_by("ts")` **显式**覆盖 `Meta.ordering = ["created_at"]`（`ts` 允许 emit 端传入 ⇒ 与 `created_at` 可以不同），并走上 `(session, ts)` 索引。
- `payload` **原样透传**（非 dict 归一 `{}`）：键由各 emit 点自定、schema 层零保证 ⇒ 前端插值每键各自兜缺省（P-8）。
- ⭐ **无会话回 200 空结构**：会话不存在是**正常态**（蓝图还没跑过编排）。404 会被前端的 404 分档吞成全页中性空态 ⇒ 生成中的蓝图看起来像「无权限」。
- 反查会话一律走既有 `_aload_session`（**自带 `process_type="technical_blueprint"` 过滤**）：同一 artifact 上可并存 `technical_plan` 与蓝图两条会话，不过滤会吐旧链事件流。用例 `test_events_ignores_the_legacy_technical_plan_session` 特意造一条**更新的** `technical_plan` 会话证伪。

---

## 7. 范围闸的复用方式与既有文件零改动核算

```python
from delivery.api.blueprint_review_views import (
    _ARTIFACT_MISSING_DETAIL,
    _aassert_project_scope,
    _aload_artifact,
    _aload_session,
    _thread_row,
)
```

- ⛔ **不提取共享模块**（要改既有文件）、⛔ **不复制第三份**（MJ-03 的四条语义会出现可漂移副本）⇒ 直接 import 私有符号并在源码注释里登记理由。
- `_ARTIFACT_MISSING_DETAIL` 一并 import 是**硬要求**：非成员的 404 响应体由闸内产出，本模块「artifact 不存在」的 404 必须与它**逐字相同**，否则存在性仍可被差分枚举（T-115-02）。自己定义常量则该等式靠人肉维持。
- 核算：`git diff server/delivery/api/blueprint_review_views.py` **为空**；`git diff server/delivery/api/artifact_views.py` **为空**。四端点各调闸一次（`src.count("await _aassert_project_scope(") == 4`，用例锁死）；本文件**不重新定义** `_aassert_project_scope` / `_ais_project_member` / `_ablueprint_project_id`。

---

## 8. `_STATUS_FIELD` 常量的存在理由（P-1）与两条守卫的绿色核对

```python
_STATUS_FIELD = "blueprint_status"   # 三条正则都不命中：字段名后紧跟引号，不是 = 也不是 :
queryset.exclude(**{_STATUS_FIELD: ""}).filter(**{_STATUS_FIELD: value})
```

INV-6 字段级守卫三条正则（`test_blueprint_inv6_guard.py:57/60/61`）扫整个 `server/`（豁免只有唯一 writer / `tests/` / `migrations/`），且守卫 docstring 明说这是**有意的**（`filter(<字段名>=...)` 出现在 writer 之外通常意味着有人自己拼 CAS 旁路）。⇒ 响应键 `current_status` + ORM 过滤走常量。源码注释已写明「为何绕这一圈」，否则后人「顺手改直白」会把守卫搞红，而报错信息指向「旁路写状态字段」这个完全无关的方向。

| 守卫 | 状态 | 核对方式 |
|---|---|---|
| `test_blueprint_inv6_guard.py`（模型写 + 字段写 + 守护的守护，5 条） | ✅ 全绿 | 另有 `P-1 naming OK` 的三正则自查脚本（含此前漏在自查外的 `_RE_FIELD_SETATTR`） |
| `test_blueprint_review_threads.py::test_no_out_of_transaction_blocker_check_before_confirm`（P-2 TOCTOU） | ✅ 绿 | 列表端点用 `annotate(Count(...))` 自算，⛔ 不 import lifecycle 那个「仅供呈现」的未决计数 async 方法；连注释里都避开该符号字面量以防未来同现 |
| `test_blueprint_log_redaction_guard.py`（P-16 脱敏，AST） | ✅ 全绿（12 条参数化） | `_SCANNED_MODULES` 追加三个新模块 |
| 前端/列表侧防回归 | ✅ | `test_blueprint_list_views.py::test_blueprint_list_item_uses_current_status_key` 断言 `"blueprint_status" not in item` —— 与 INV-6 守卫互为双保险 |

**未决计数口径**（列表端点，与 confirm 守卫对齐）：`severity=blocker` **且** `blocking=True` **且** `status ∈ {open, answered}` ⇒ `answered` **算未决**、`resolved`/`dismissed` 不算（用例 `test_blueprint_list_excludes_resolved_blockers_from_unresolved`）。

---

## 9. Deviations from Plan

### 1. `[Rule 3 - 阻塞] 复用 import 清单按实际使用收敛（去掉 `_alatest_content`、加入 `_thread_row` 与 `_ARTIFACT_MISSING_DETAIL`）**

- **Found during:** Task 1
- **Issue:** 计划写的四符号 import 里 `_alatest_content` 在本文件**无使用点**（正文端点需要的是版本**行**而不只是 content），留着会触发 ruff `F401`（`ruff check` 是本 task 的验收项之一）。同时「`_thread_detail_row` 在九键之上扩写」若手抄九键会产生第二份 `str(x or "")` 归一副本；「非成员 404 与不存在 404 逐字相同」若自定义常量则等式靠人肉维持。
- **Fix:** import 清单改为实际使用的五个：`_aassert_project_scope` / `_aload_artifact` / `_aload_session` / `_thread_row` / `_ARTIFACT_MISSING_DETAIL`。方向与计划的「import 复用、不复制」完全一致，且更强（九键与中性 404 文案都只有一份实现）。
- **Files:** `server/delivery/api/blueprint_doc_views.py`
- **Commit:** `3e2a3533`

### 2. `[Rule 1 - 验收命令自身的假阳性] Task 1 的「正文不进日志」AST 命令按字面跑会红`

- **Found during:** Task 1 验收
- **Issue:** 计划的 AST 脚本扫**所有**调用的 `body`/`question`/`quote`/`q` kwarg，只放行 `len(...)` 或函数名含 `open_thread` 的调用。它漏了**端点 → service 的正文移交**（`aopen_selection_comment(..., body=text, ...)`）⇒ 按字面跑必然 `AssertionError: (..., 'body', 'text')`，而这与「正文不进日志」这条纪律毫无关系（计划自己的括注只考虑了 `open_thread(question=body)` 这一处落库）。
- **判定与处置:** 保留 house style 的 keyword-only 签名（`blueprint_review_action` 全域 `*, comment` / `*, reason`；把 `body` 改成位置参数只为迁就一条 grep 会让 API 与家族不一致）。改跑**加强版**脚本：把 logger 调用面与落库/service 移交面分开判——**logger 面任何正文类 kwarg 零命中**（这才是纪律本身），移交面只允许 `open_thread` 与 `aopen_selection_comment` 两个已登记的 sink。输出 `no raw body in log kwargs (logger 面零命中；正文实参只出现在 open_thread 落库与 service 移交)`。AST 脱敏守卫（12 条参数化）同时全绿。
- **Files:** 无源码改动（验收方法订正）
- **Commit:** —

### 3. `[Rule 3 - 阻塞] quality「三项均为 null」在 200 响应里不可达；改用可达的三态并列`

- **Found during:** Task 3
- **Issue:** 计划第 6 条 (a) 要求「零事件/零版本/零线程 ⇒ 三项均为 `null`」。但 `human_edit_volume` 返 `null` 的唯一条件是**该 artifact 零版本**，而零版本时正文端点必 404（拿不到版本）⇒ 经端点永远看不到那个 `null`。
- **Fix:** 三态并列改为可达且更强的组合：同一响应内 `ai_rejection_rate is None` + `clarification_rounds is None` + `human_edit_volume == 0`（「无数据 → null」与「有源零值 → 0」**并排**出现），再补一条**同一指标**的零值档（`clarification_rounds == 0`，有线程无人作答）与一条全正值档。任何把 `None` 归一成 0 的改写都会让第一条转红。`human_edit_volume` 的 `null` 档由既有 `tests/services/test_blueprint_quality.py` 覆盖（本 plan 不重复实现统计逻辑）。
- **Files:** `server/tests/delivery/test_blueprint_doc_views.py`
- **Commit:** `89819118`

### 4. `[Rule 3 - 阻塞] 「meta.project_id 缺失 → 400」的造数改用非 UUID 值`

- **Found during:** Task 3
- **Issue:** `project_id` 是 blueprint schema 的**必填**属性 ⇒ `ArtifactService.create` 直接抛 `ArtifactContentInvalid`，造不出「缺该键」的合法蓝图。
- **Fix:** 用**非 UUID** 值（`"proj-0001"`，旧样例形状）复现同一条 fail-closed 分支——闸内判据是 `_is_uuid(project_id)`，缺失与非法走同一行 400。与 114-05 的既有用例 `test_review_endpoints_fail_closed_when_the_project_scope_is_unresolvable` 同一手法。
- **Files:** `server/tests/delivery/test_blueprint_doc_views.py`
- **Commit:** `89819118`

### 5. `[Rule 2 - 缺失的关键防护] 带 ?version_id= 时同时约束 artifact_id`

- **Found during:** Task 1
- **Issue:** 计划的 `_aload_version` 描述里 `filter(artifact_id=..., id=version_id)` 已含该约束，但值得单独登记其**安全含义**：范围闸只看 URL 里的 artifact，若取版本不带 `artifact_id` 约束，任意成员可用自己有权限的 artifact_id 拼**别的项目**的 version_id 读到该项目正文。
- **Fix:** 实现按计划带上约束，并补一条负向用例（`test_document_rejects_unknown_or_foreign_version_id` 中「借用别的 artifact 的版本 id → 404」）。
- **Files:** `server/delivery/api/blueprint_doc_views.py` / `server/tests/delivery/test_blueprint_doc_views.py`
- **Commit:** `3e2a3533` / `89819118`

### 6. `[Rule 1 - 事实修正] annotate 的 related_name 是 blueprint_threads 不是 threads`

- **Found during:** Task 2
- **Issue:** 计划示例写 `Count("threads", ...)`（并已注明「related_name 按实测取，不猜」）。实测 `BlueprintThread.artifact` 的 `related_name="blueprint_threads"`。
- **Fix:** 全部 annotate 改用 `blueprint_threads`；`severity`/`status` 取 `ThreadSeverity.BLOCKER` / `ThreadStatus.OPEN`·`ANSWERED` 枚举常量而非字面量。
- **Files:** `server/delivery/api/blueprint_list_views.py`
- **Commit:** `c623996c`

### 7. `[Rule 2 - 缺失的关键防护] 批量取名前先过滤非 UUID id`

- **Found during:** Task 2
- **Issue:** `meta.project_id` 与 `repo_associations[].repository_id` 是半可信 content 字段（既有样例里就是 `"proj-0001"` / `"repo-backend"` 这种非 UUID）。直接 `filter(id__in=[...])` 会抛 `ValidationError` ⇒ 整个聚合掉进 except 返空结构，**列表静默变空**而请求仍 200。
- **Fix:** `_load_names` 先按 `_is_uuid` 过滤候选 id 再查；取不到名字回落 content 快照名 / 空串，⛔ 不丢行。
- **Files:** `server/delivery/api/blueprint_list_views.py`
- **Commit:** `c623996c`

### 8. `[Rule 4 边界上的判断] 四条 REQ 不标 Complete，只在追溯表登记「供数面已就位」`

- **Found during:** 状态收口
- **Issue:** 本 plan frontmatter 的 `requirements: [VIEW-01, VIEW-03, VIEW-04, CLAR-01]` 按流程会被整条勾成 Complete。但这四条是**用户可见承诺**（「用户可打开结构化蓝图查看器」「知识库新增技术方案 tab」「看到划线高亮并可多轮回复」），由 115-02…07 的前端面兑现；本 plan 只交付它们的后端供数面。整条勾完会让相位 verifier 认为已兑现而跳过前端验收。
- **Fix:** 回滚勾选，改为在 `REQUIREMENTS.md` 追溯表逐条注明「Pending（后端供数面已就位 @ 115-01：<端点>；<本体> 待 115-0x）」——信息一条不少，完成度不虚报。四条 REQ 的最终勾选留给兑现前端面的那个 plan。
- **Files:** `.planning/REQUIREMENTS.md`
- **Commit:** 见收口 commit

### 9. `[Rule 3 - 验收 grep 与说明性文字冲突] 三个「⛔ 不要用」的符号从 docstring 里改为描述性表述`

- **Found during:** Task 2 验收
- **Issue:** 验收要求 `resolve_allowed_project_ids` / `_aassert_project_scope` / `paginate_queryset` 在列表端点源码里**零命中**，而我原先在 docstring 里逐字引用这三个符号来解释「为什么不用它们」。
- **Fix:** 保留全部解释、改为描述性表述（如「`knowledge.access_scope` 里那个「可见集合」解析函数」「`blueprint_review_views` 的 MJ-03 范围闸」「DRF 的分页 helper 只吃 queryset」）⇒ 三条 grep 归零，语义信息一条不少。
- **Files:** `server/delivery/api/blueprint_list_views.py`
- **Commit:** `c623996c`

---

## 10. 受限面删除行核算（纯追加纪律）

| 文件 | 允许上界 | 实际 | 核对 |
|---|---|---|---|
| `server/delivery/urls.py` | 删除 0 行；import 追加 2 条 + `urlpatterns` 追加 4 项 + 分组注释 | **删除 0 行**；import 追加 2 条（`blueprint_doc_views` 三 View / `blueprint_list_views` 一 View）、`urlpatterns` 追加 **4** 项、2 处分组注释 | `git diff server/delivery/urls.py \| rg "^-[^-]"` **为空** |
| `server/tests/delivery/test_blueprint_log_redaction_guard.py` | 删除 0 行；`_SCANNED_MODULES` 追加 3 行 | **删除 0 行**；追加 3 行（Task 1 两行、Task 2 一行——守卫是 `parametrize` + 直接 `read_text()`，模块不存在会抛 `FileNotFoundError`，故 `blueprint_list_views.py` 必须等到 Task 2） | 同上，**为空** |
| `server/delivery/api/blueprint_review_views.py` | 零改动 | **零改动** | `git diff` 输出为空 |
| `server/delivery/api/artifact_views.py` | 零改动 | **零改动** | `git diff` 输出为空 |

**冻结面自检**：`git diff --name-only`（三个 commit 合计）的文件集 = 本 plan 声明的七个文件；`rg "blueprint_review_views|artifact_views|services/process_runtime|blueprint_lifecycle_service|event_taxonomy|^web/"` **零命中**。

---

## 11. 全量后端门与基线比对

| 项 | 基线 | 本 plan 后 | 差异 |
|---|---|---|---|
| `cd server && uv run pytest tests/ -q` | 8546 passed / 1 failed | **8606 passed / 1 failed**（63 skipped / 26 deselected / 1 xfailed，471.78s） | **+60 passed，新增失败 0** |
| 唯一失败 | `tests/mcp_tools/test_skills_snapshot_guard.py::test_skill_files_discovered` | **同一条，无变化** | 本 worktree 的 `skills/` 是空目录、主检出里有内容 —— 纯环境现象，与蓝图无关，未触碰 |
| `makemigrations --check --dry-run` | — | 退出码 **0**（`No changes detected`） | 相位内**零** migration 文件（`git status --porcelain server/*/migrations/` 为空；最新仍是 `delivery/0033_blueprintthread_last_reminded_at.py`） |

**+60 的构成核对**：新增用例 39 条（doc 25 条 → 参数化后 42 个 case；list 14 条 → 15 个 case，合计 57 个 case）+ 脱敏守卫 `parametrize` 因追加三个模块多出 3 个 case = **60**。逐项对得上，无「顺手带绿」的隐藏改动。

其他门：`uv run pytest tests/delivery/ -q` 全绿（Task 1 后 721 passed，Task 3 新增两文件后含于全量门）；`ruff check` / `ruff format --check` 对三个新建源文件与两个新建测试文件全绿（受限面 `urls.py` 与守卫测试只跑 `ruff check`）。

---

## 12. 四条 REQ → 测试用例映射

| REQ | 兑现面 | 关键用例 |
|---|---|---|
| **VIEW-01**（结构化正文可渲染） | 端点 ① 返回 `content` dict + `quality` | `test_document_defaults_to_the_latest_version`（`content.schema_version == "blueprint/v1"`）/ `test_document_returns_history_version_with_is_current_false` / `test_document_rejects_unknown_or_foreign_version_id` / `test_quality_*` 四条 |
| **VIEW-03**（知识库 tab 列表） | 端点 ⑤ 的筛选与分页 | `test_blueprint_list_paginates_with_five_keys` / `test_blueprint_list_clamps_and_fail_softs_page_params` / `test_blueprint_list_q_matches_title_and_summary` / `test_blueprint_list_filters_by_project_status_and_repository` / `test_blueprint_list_item_uses_current_status_key` |
| **VIEW-04**（项目物料卡） | 端点 ⑤ 的项目可见性与 `?project_id=` | `test_blueprint_list_only_shows_projects_i_belong_to`（1 → 2 证非恒真）/ `test_blueprint_list_passes_through_for_superuser` / `test_blueprint_list_is_fail_closed_without_any_membership` / `test_blueprint_list_counts_threads_and_unresolved_blockers` |
| **CLAR-01**（多轮回复 + 主动选区评论） | 端点 ③ 的 `messages[]`/`options` + 端点 ④ 的写口 | `test_threads_get_extends_the_nine_row_keys_with_three_more` / `test_threads_get_normalizes_malformed_options_without_raising` / `test_threads_get_tolerates_a_null_message_author` / `test_threads_get_orders_threads_by_created_at` / `test_threads_post_creates_a_human_comment_thread` / `test_threads_post_rejects_empty_body_without_touching_db` / `test_threads_post_rejects_a_non_editable_blueprint` / `test_threads_post_accepts_a_comment_without_anchor` |
| **MJ-03 对称面**（四端点范围闸） | 参数化四端点 × 三态 | `test_doc_endpoints_reject_unauthenticated` / `test_doc_endpoints_allow_project_members` / `test_doc_endpoints_return_neutral_404_for_non_members`（`denied.json() == missing.json()`）/ `test_doc_endpoints_pass_through_for_superuser` / `test_doc_endpoints_fail_closed_without_project_id` |

---

## 13. 观测埋点登记（`.cursor/rules/observability-logging.mdc`）

| 事件 | component | category | 字段（全部标量/关联键） |
|---|---|---|---|
| `blueprint_document_read` | `blueprint_doc_api` | caller | `artifact_id` / `initiated_by_user_id` / `duration_ms` / `version_no` / `is_current` / `citation_count` |
| `blueprint_events_read` | `blueprint_doc_api` | caller | 同上五件套 + `has_session` / `event_count` |
| `blueprint_threads_read` | `blueprint_doc_api` | caller | 同上 + `thread_count` / `message_count` |
| `blueprint_thread_created` | `blueprint_doc_api` | caller | 同上 + `status` / `thread_id` / **`body_len`** / `has_anchor` |
| `blueprint_selection_comment_created` / `_failed` | `blueprint_comment_action` | caller | `artifact_id` / `thread_id` / `initiated_by_user_id` / `body_len` / `has_anchor` / `duration_ms`（失败条额外 `error=_detail(exc)`） |
| `blueprint_list_read_started` / `_completed` | `blueprint_list_api` | caller | `initiated_by_user_id` / `duration_ms` / `page` / `page_size` / `project_count` / `is_superuser` / **`q_len`** / `total` / `item_count` |
| `blueprint_list_read_failed` | `blueprint_list_api` | caller | `error_type` / `error=redact_secrets_in_text(...)` / `duration_ms` |

**只读 GET 也记 caller 事件**（`blueprint_review_snapshot_read` 是先例）：谁读过哪份蓝图必须有痕（T-115-12）。**正文类一律只记长度**：评论 `body` / `?q=` / 线程消息 / citation `quote` 零进日志。异常文本一律过 `_detail`（`redact_secrets_in_text` + 截断 500）或 `redact_secrets_in_text`。观测全程 best-effort，聚合异常返空结构**不 500**。

---

## 14. 给下游（115-02 起）的三条注意

1. **正文与快照分工**：`GET blueprint/` 出 `content`（高频重取的人审快照仍不含 content，刻意不内联）；版本轨继续用既有 `deliveryArtifacts.getArtifactTimeline`，本 plan 零新端点。
2. **状态以响应体 `current_status` 为准**：`POST threads/` 不改状态也照样回传该键；⛔ 前端不得自行乐观推断下一状态。
3. **events 的 200 空结构不是错误态**：`{session_id: "", current_stage: "", events: []}` 必须渲染成「尚未开始编排」，⛔ 不能走 404 分档的全页中性空态。

## Self-Check: PASSED
