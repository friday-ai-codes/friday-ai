# Phase 114: 审查与澄清收敛 - Research

**Researched:** 2026-07-30
**Domain:** 蓝图 AI 对抗审查（六类机械规则纯函数 + 一类 goal-backward LLM）、findings→线程收敛、澄清回灌产版本、人工 block 编辑与人审操作端点
**Confidence:** HIGH（全部判据来自本仓代码实读，非训练记忆；外部依赖为零新增包）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**AI 审查代理与七类规则**
- 新建 `server/services/process_runtime/blueprint_review.py` + 追加第 10 个 stage `ai_review`（`builtin_processes.py` 只加注册与新 handler `_h_bp_ai_review`）；审查代理**独立 fresh context**，不与起草/融合共享会话（降相关性偏差）
- **六类机械规则纯函数化**（不交给 LLM，保证可复现与可证伪）：① schema 完整性（`validate_blueprint`）② 引用覆盖（`blueprint_quality`：关键结论必带 citations，无引用的事实性断言 WARNING、关键结论无引用 BLOCKER）③ 角色一致性（每个 direct 仓 ≥1 实现项；indirect 仓 `capabilities_used` 被某实现项或 API 的 data_source 引用；改动 indirect 仓即 BLOCKER）④ API 闭环（`interaction_flows.steps.api_ref` 必指向已声明契约；consumed 的 `data_source.availability=needs_support` 时 `support_repository_id` 必须出现在 repo_associations）⑤ 禁令（不得出现以周为单位排期、不得引入 out_of_scope、不得与 constraints 冲突）⑥ 章程边界（direct 仓实现项违背该仓 `RepoCharter.boundaries` 或落在 `evolution=maintenance_only` 仓，必须有对应 decision_log 支撑，否则 BLOCKER）
- **仅 goal-backward 一类走 LLM**：对每个 feature_point 逆向核对 acceptance_criteria 是否被实现项与 test_strategy 覆盖、`must_haves.truths` 是否有实现项支撑、`key_links` 两端是否都存在；`call_source` 用 111 已注册的 `blueprint_ai_review`
- findings 载体复用 `BlueprintThread(kind=ai_review_finding, severity∈{blocker,warning,info}, blocking)`，锚定到 block（section_path 走 111 `iter_blocks` 的「点分 + [标识]」约定）
- 模型档位与起草**同档**（§12 已定），不强制换模型

**有界修订与归因打回**
- 归因打回：**仓级 BLOCKER 回该仓 `repo_plan`、融合级回 `merge`**，合计 **≤2 轮**（计数存 `stage_state`，复用 113 的有界回退范式）
- **超界出口**：转 `pending_review` 并携未决 BLOCKER 清单（人审可见），**不落 FAILED**
- 仅 WARNING/INFO：直接进 `pending_review`，findings 作为人审参考（不打回）
- 确认门锁定校验：偏离 112 锁定的仓库集/职责（对照 `confirmed_at_gate`/`responsibility` 快照）即 **BLOCKER**——要变必须重开确认门
- 状态：`ai_reviewing` 期间经 `BlueprintLifecycleService` 转 `ai_reviewing`；打回转回 `drafting`；通过转 `pending_review`；`blueprint_resume` 的 stage→status 表需追加 `ai_review → ai_reviewing`（受限纯追加，同 113-06 纪律）

**澄清回灌与决策物化**
- 答案消费：由对应阶段代理消费 → 产**新 `ArtifactVersion`**（复用 113 幂等口径：同 content_hash 与 current 相同不翻版本）；线程置 `resolved` 并记 `applied_in_version`
- 决策物化：结论写进蓝图 `decision_log` 段（thread_id/question/decision/decided_by/applied_in_version）
- 重锚定接线：新版本装配后调 111 的 `blueprint_anchor` 重挂线程（block_id 精确 → quoted_text 模糊 0.85 → `orphaned`）；失锚线程**不删**且可集中查询
- pending 超时：保持 pending + 按可配周期提醒，**不自动作答、不判失败**；提醒对象为 `BlueprintReviewer` 名单 + 发起人

**人工 block 编辑**
- patch 形态：block 级 ops（`replace`/`insert`/`delete`）经 REST → service 收口（INV-6）→ 产新版本，`produced_by_ref="human_edit:{user_id}"`
- 冲突语义：**人工内容不被 AI 覆盖**——后续 AI 修订以人工版本为基线，冲突必须开线程询问
- 校验：编辑后仍须过 `validate_blueprint`，不合法直接拒绝并回显原因（不落半合法版本）
- 权限：项目成员皆可编辑；编辑者与人审操作者一并 upsert 进 `BlueprintReviewer`
- 人审操作端点属本相位，经 `BlueprintLifecycleService`：通过 → `confirmed`（守卫：无 open+blocking 线程 + 无未解决 BLOCKER）；驳回 → `drafting` 且 `revision_round + 1`

**观测**
- 审查事件 `blueprint_review_started/completed/failed` 带 `duration_ms`/`category=caller`/`component=process_runtime`；findings 计数与分级分布进 payload（**正文不进 payload**）
- 打回/超界/人审通过驳回记 `caller` 事件并绑定 `initiated_by_user_id`；机械规则逐条判定记 `sampling`
- AI 打回率与人审修改量喂给 `blueprint_quality` 的 DB 统计接口占位

### Claude's Discretion
- 六类机械规则的内部函数切分、goal-backward prompt 措辞、findings 去重与聚合策略、patch ops 的序列化细节、测试组织自行决定，遵循 111/112/113 已建立的 `blueprint_*` 模块风格。

### Deferred Ideas (OUT OF SCOPE)
- 审查与起草强制换模型的交叉验证实验（Future Requirements）
- findings 的严重度自动学习/调参 → Future
- 前端批注呈现与失锚评论列表 UI → Phase 115

</user_constraints>

## Summary

本相位无任何新外部依赖——所有判据符号都已由 111/112/113 交付并在本次调研中逐个实读定位。六类机械规则的判据来源全部落在 `blueprint_schema.py` 的 JSON Schema 字段与 `validate_blueprint` 后置检查、`blueprint_quality.citation_coverage`、`repo_associations[].role/capabilities_used/confirmed_at_gate/responsibility`、`api_contracts[].direction/data_source`、`interaction_flows[].steps[].api_ref`、`requirement_spec.boundaries/constraints`，以及 `RepoCharter.boundaries/evolution`（经 `blueprint_charter_match.aload_charters` 批量读）。

风险集中在三处**契约细节**而非技术选型：① findings 留痕**不能**走线程的「作答」通道（112 review 已记教训：作答会把线程推进 answered/门放行语义）；② `blueprint_resume` 的 stage→status 映射追加必须严格纯追加、不动前九 stage 行为；③ 打回计数写 `stage_state` 必须避开既有键（本文件列出已用键清单）。

**Primary recommendation:** 六类规则实现为 `blueprint_review.py` 的纯函数（输入 `content: dict` + 可选 `charters: dict[str, dict]`，输出统一 finding dict 列表），全部 `.get` 防御、分母为 0 走「无缺口」口径；LLM 只承担 goal-backward 一类；findings 落库与线程 resolve 走 `BlueprintLifecycleService` 而非直接写 ORM。

## 1. 六类机械规则的判据来源（逐条确切符号 + 行号）

所有符号均实读确认 `[VERIFIED: 本仓代码]`。

### 规则① schema 完整性

```
server/services/process_runtime/blueprint_schema.py:793
def validate_blueprint(content: Any) -> tuple[bool, str | None]
```

- **返回**：`(True, None)` 合法；`(False, error_message)` 非法。**绝不外抛**（:907 `except Exception` 兜底）。
- **重要陷阱**：`:809` —— `content.get("schema_version") != BLUEPRINT_SCHEMA_VERSION`（`"blueprint/v1"`）时**直接 `return True, None`**（隐式 v0 pass-through）。半成品/缺 `schema_version` 的蓝图会「假通过」规则①。审查入口必须**先自行断言** `content.get("schema_version") == "blueprint/v1"`，否则规则①形同虚设。
- 已内建的 5 项后置检查（可直接复用，不要在 `blueprint_review.py` 重写）：
  - (a) `:817-826` citations 引用完整性（块内 id 必须在顶层 `citations` 池）
  - (b) `:828-846` `implementation_overview.items[].feature_point_id` 必须解析到 `requirement_spec.feature_points[].id`
  - (c) `:848-876` `items[].repository_id` 与 `current_state_analysis[].repository_id` 必须在 `repo_associations`
  - (d) `:878-887` 引用池 key == `entry.citation_id`
  - (e) `:889-905` `feature_points` / `items` / `api_contracts` 的 `id` 唯一性
- 报错已脱敏截断（`_format_error`，`server/services/process_runtime/blueprint_schema.py:764`，上限 `_MAX_ERROR_CHARS = 500`，:760）——finding 正文可直接引用该字符串。

### 规则② 引用覆盖

```
server/services/process_runtime/blueprint_quality.py:68
def citation_coverage(blueprint: dict) -> float
server/services/process_runtime/blueprint_quality.py:39
def _iter_key_conclusion_citations(blueprint: Any) -> Iterator[Any]   # 私有
```

- **三类关键结论口径**（`:42-47`）：`current_state_analysis[].findings[].citations`、`repo_associations[].rationale.citations`、`impact_analysis.affected_features[].citations`。
- **分母为 0 返回 1.0**（`:76`）——空文档不被惩罚。半成品蓝图跑规则②会得满分，**不能只看覆盖率**：BLOCKER 判定应逐条走「关键结论条目存在但 citations 空」，需要**条目级**而非比率级信息。
- `citation_coverage` 只回 float，拿不到「哪一条缺引用」。**建议**：在 `blueprint_review.py` 内新写条目级走查（复刻 `_iter_key_conclusion_citations` 的三类口径，但同时 yield section_path），不要改 `blueprint_quality`（111 已交付、有单测锁口径）。
- `_cited`（`:34`）判定 = `isinstance(value, list) and len(value) > 0`。

### 规则③ 角色一致性

判据字段（schema 定义）：

| 字段 | 位置 | 形状 |
|------|------|------|
| `repo_associations[].role` | `blueprint_schema.py:247-251` | `enum: ["direct", "indirect"]`，**required**（:235 与 `repository_id`/`repository_name` 同为必填） |
| `repo_associations[].capabilities_used` | `blueprint_schema.py:300-303` | `array`，**indirect 专属**：会被用到的能力清单（无 items 约束——半可信，逐项 `.get` 防御） |
| `repo_associations[].planned_change_summary` | `blueprint_schema.py:296-299` | `block_list`，**direct 专属** |
| `implementation_overview.items[].repository_id` | 后置检查 (c) `blueprint_schema.py:856-866` 已保证在 `repo_associations` 内 | — |
| `api_contracts[].data_source` | `blueprint_schema.py:544-569` | consumed 专属，见规则④ |

- 「每个 direct 仓 ≥1 实现项」：按 `items[].repository_id` 分组计数，与 `role=="direct"` 的 `repository_id` 集合求差 → BLOCKER。
- 「indirect 仓 `capabilities_used` 被引用」：`capabilities_used` 是自由 array（无 schema），元素可能是 str 也可能是 dict → 用**归一化取文本**再在 items 的 how/text 与 `api_contracts[].data_source.from_api/from_service` 里做包含匹配。这是六条里唯一带模糊匹配的一条，**判 WARNING 更稳**，只有「改动 indirect 仓」（即某 item 的 `repository_id` 指向 `role=="indirect"` 的仓）才判 BLOCKER——后者是纯集合运算，可确定性证伪。

### 规则④ API 闭环

```
interaction_flows[].steps[].api_ref     server/services/process_runtime/blueprint_schema.py:684-687   # "引用 api_contracts 的契约 id"
api_contracts[].id                      server/services/process_runtime/blueprint_schema.py:509        # required: ["id","name","kind","direction"]
api_contracts[].direction               server/services/process_runtime/blueprint_schema.py:522-524    # enum: ["provided", "consumed"]  ← 注意是 provided 不是 produced
api_contracts[].data_source.availability          blueprint_schema.py:555-559  # enum: ["existing", "needs_support"]
api_contracts[].data_source.support_repository_id blueprint_schema.py:560-563
```

- 两条判定都是纯集合运算 → 全部 BLOCKER 可证伪：
  1. `{step.api_ref} - {contract.id} != ∅` → 断链 BLOCKER。
  2. `direction=="consumed" and data_source.availability=="needs_support"` 时，`data_source.support_repository_id` 必须 ∈ `{assoc.repository_id}`（缺失或不在集合内 → BLOCKER）。
- **枚举值纠偏**：CONTEXT 写「consumed」正确；但若代码里写 `"produced"` 会永远匹配不到——schema 实际枚举是 `provided` / `consumed`。

### 规则⑤ 禁令

```
requirement_spec.boundaries    server/services/process_runtime/blueprint_schema.py:216-219  # object，"范围边界（in_scope / out_of_scope）"
requirement_spec.constraints   server/services/process_runtime/blueprint_schema.py:220-223  # array，"约束清单（id/text/kind/citations）"
```

- 两者都是**弱 schema**（object / array，无 properties / items 约束）→ 运行期形状不保证。必须逐字段 `.get` 且对 `boundaries.out_of_scope` 既容忍 `list[str]` 也容忍 `list[dict]`。
- `rationale.constraint_refs`（`blueprint_schema.py:260-264`，"关联 requirement_spec.constraints 的约束 id"）是**唯一已存在的 constraint 引用通道**——「与 constraints 冲突」若要可证伪，只能做到「引用了不存在的 constraint id」这一层（集合运算，BLOCKER）；语义冲突留给 goal-backward LLM 一类，机械规则不碰。
- 「以周为单位排期」：正则扫全文本块（`\d+\s*周` / `week`），命中即 WARNING/BLOCKER（CONTEXT 定为禁令 → BLOCKER）。文本抽取复用 `iter_blocks` + `blueprint_anchor._block_text` 的取文本口径（见主题 4）。
- `deferred_ideas`（`blueprint_schema.py:737-740`）是「scope 外想法」段——扫 out_of_scope 引入时应排除该段，否则误报。

### 规则⑥ 章程边界

```
server/repositories/models.py:1091   class RepoCharter
  :1144  boundaries = models.JSONField(default=list)   # 负向边界禁区：[{rule, decided_by, citations}]
  :1150  evolution  = models.CharField(choices=Evolution.choices, default=ACTIVE)
  :1113  class Evolution: ACTIVE="active" / MAINTENANCE_ONLY="maintenance_only" / DEPRECATED="deprecated"
  :1107  class Source:    AI_DRAFT="ai_draft" / HUMAN_CONFIRMED="human_confirmed"
  :1142  owned_domains, :1146 placement_preferences, :1156 draft_content（pending 草案，不生效）
  db_table = "repo_charters"（:1162），与 Repository 是 OneToOne（:1121，related_name="charter"）
```

批量读章程**不要自己写 ORM**，复用：

```
server/services/process_runtime/blueprint_charter_match.py:288
async def aload_charters(repository_ids: list[str]) -> dict[str, dict]
# 返回 {repository_id: 正式字段 dict}；缺章程的仓不出现在结果里；
# best-effort：任何异常 → warning + 返回 {}（:296-308）
```

- **注意 `draft_content`（:1156）不生效**——`aload_charters` 走 `_CHARTER_VALUE_FIELDS`（`:267` 起含 `"evolution"`）取正式字段，不含草案。规则⑥只对正式字段判定，符合「AI 草案不约束」的语义。
- 章程缺失 → 该仓不在返回 dict 中 → **规则⑥对该仓跳过**（不判 BLOCKER）。这是必须显式写进测试的边界。
- `boundaries` 元素形状 `{rule, decided_by, citations}`（`:1143` 注释）——`rule` 是自由文本，机械匹配只能做「direct 仓 + 该仓 evolution == maintenance_only/deprecated + 无 decision_log 支撑 → BLOCKER」这条**可证伪**判定；「违背 boundaries.rule」是文本语义，建议降为 WARNING 或交由 LLM 一类，否则会产生不可复现的 BLOCKER。
- `decision_log` 支撑判定见主题 4（`blueprint_schema.py:733-736`，弱 schema array）。

### 确认门锁定校验（CONTEXT 归入有界修订，判据同属机械规则）

```
repo_associations[].confirmed_at_gate   blueprint_schema.py:313-316  # boolean，"是否经阶段 1 用户确认门锁定"
repo_associations[].responsibility      blueprint_schema.py:272-275  # block_list，"本仓在方案中的职责（阶段 1 确认门锁定）"
repo_associations[].decided_by          blueprint_schema.py:308-312  # enum ["ai","human"]
```

112 的写入侧（口径出处，读时对齐）：

```
server/services/process_runtime/blueprint_confirm_gate.py:264   # 一律写 decided_by="human" / confirmed_at_gate=True
server/services/process_runtime/blueprint_confirm_gate.py:291-303  # responsibility 经 _as_block_list(block_id=f"blk_gate_resp_{repository_id}")
server/services/process_runtime/blueprint_confirm_gate.py:270    # decisions 覆盖层形状 {rid: {role, responsibility, removed}}
```

- 判据：取当前蓝图中 `confirmed_at_gate is True` 的条目集合与其 `responsibility` 文本，与 merge 后蓝图对比。**block_id 命名 `blk_gate_resp_{repository_id}` 是稳定锚**——职责被改写时该 block 的文本变化即可确定性检出。
- 113 侧已有等价投影可参考：`blueprint_repo_plan.py:165` 与 `:973`——「`repo_associations` / 确认门快照 → `[{repository_id, role, responsibility, fitness}]`」。**建议直接复用该投影函数做对比基线**，避免两处口径漂移。

## 2. findings → 线程 API（含 112 review 教训）

### 模型字段（全部实读）

`server/delivery/models/blueprint_thread.py`

| 字段 | 行 | 形状 |
|------|----|------|
| `artifact` | :69 | FK → `delivery.Artifact`，`related_name="blueprint_threads"` |
| `created_on_version` | :75 | FK → `delivery.ArtifactVersion`，`null=True`，`SET_NULL`（删版本不删线程） |
| `anchor` | :84 | JSON，可 null；形状 `{section_path, block_id, start_offset, end_offset, quoted_text}`（:82-83） |
| `anchor_status` | :85 | `ThreadAnchorStatus`：`anchored` / `orphaned`（:22-26），默认 `anchored` |
| `kind` | :91 | `ThreadKind`：`ai_clarification` / **`ai_review_finding`** / `human_comment` / `repo_confirmation`（:29-35），`max_length=24` |
| `severity` | :92 | `ThreadSeverity`：`blocker` / `warning` / `info`（:38-43），**blank 默认 `""`** |
| `blocking` | :99 | bool，默认 False |
| `options` | :101 | JSON list，默认 `[]`，形状 `[{label, value, note}]` |
| `status` | :102 | `ThreadStatus`：`open` → `answered` → `resolved` \| `dismissed`（:46-52） |
| `return_stage` | :108 | `max_length=16`，取值 `researching`/`drafting`/**`ai_reviewing`**（:107） |
| `initiated_by_user_id` | :110 | `max_length=64`，默认 `"system"` |
| 索引 | :119-122 | `Index(fields=["artifact","status","blocking"])` —— 守卫查询驱动 |

`BlueprintThreadMessage`（:128-159）：`thread` FK（`related_name="messages"`）、`author_type`（`ai`/`human`）、`author` FK 可空、`body` TextField、`ordering = ["created_at"]`。**无「结论」字段**——结构化留痕必须写蓝图 `decision_log`。

**模型层零业务方法**（:11-13 docstring）：旁路写表由 `server/tests/delivery/test_blueprint_inv6_guard.py` 源码扫描锁死。`blueprint_review.py` **绝不可**直接 `BlueprintThread.objects.create(...)`，必须走 service。

### Service API（`server/delivery/services/blueprint_lifecycle_service.py`）

```python
# :365  开线程（线程行 + 首条 AI 消息同事务，杜绝半截线程 :378-385）
async def open_thread(
    self,
    artifact: Artifact,
    *,
    kind: str,                       # 必须 ∈ ThreadKind.values，否则 raise ValueError（:386-387）
    blocking: bool,
    question: str,                   # → 首条 AI 消息 body（:512-516）
    options: list | None = None,
    initiated_by_user_id: str = "system",
    created_on_version: Any = None,
    anchor: dict | None = None,
    return_stage: str = "",          # 超 16 字符截断 + warning，不抛（:390-399）
) -> BlueprintThread
```

⚠️ **`open_thread` 没有 `severity` 参数**。CONTEXT 要求 findings 带 `severity∈{blocker,warning,info}`——本相位必须**给 `open_thread` 追加 `severity: str = ""` 形参**（默认空 = 与现有 112/113 调用逐字等价，属安全追加），并在 `_open_thread_sync`（:486-517）的 `objects.create` 里带上。这是本相位唯一需要改 111 已交付 service 签名的地方，必须在计划里显式登记。

```python
# :456  收尾线程（幂等，只 open/answered 可推进 :547-565）
async def resolve_thread(
    self, thread, *, resolution: str = "", initiated_by_user_id: str = "system",
    dismissed: bool = False,
) -> BlueprintThread
# resolution 非空 → 同事务追加一条 AI 结论消息；已终态 → no-op 且不覆盖首次结论（:552-557）

# :347  守卫查询
async def ahas_open_blocking_threads(self, artifact, *, kind: str | None = None) -> bool
# 只认 status=open AND blocking=True；kind 过滤让规格门/确认门互不误挡（:352-354）

# :215  评审人 upsert
async def add_reviewer(self, artifact, user, first_action: str) -> BlueprintReviewer
# aget_or_create；已在名单原样返回，first_action 不覆盖（:220）

# :143  状态转移（⚠️ 方法名是 transition，不是 atransition）
async def transition(
    self, artifact, to_status: str, *,
    initiated_by_user_id: str, acting_user=None, session=None, return_status: str | None = None,
) -> Artifact
```

### ⚠️ 112 review 教训：留痕**不可**用 `record_answer`

```python
# :425  record_answer —— 追加消息 **并把 open 推到 answered**（:434, :536-540）
async def record_answer(self, thread, *, body, author=None,
                        author_type=ThreadAuthorType.HUMAN, initiated_by_user_id="system")
```

`_record_answer_sync`（:520-541）在同事务里执行 `filter(id=..., status=OPEN).update(status=ANSWERED)`。后果由 `_arecord_gate_note` 的 docstring 逐字写明（:1046-1051）：

> 确认门线程必须保持 `open` 直到 `confirm` 收尾——一旦被推到 `answered`，`ahas_open_blocking_threads`（只认 `open`）会判为无门，`open_gate` 就会再开第二条确认门线程，续驱的 pause 判据也会失守。

**对 114 的直接推论**：`ai_review_finding` 线程的 blocking 语义靠 `status==open` 支撑（LIFE-02 守卫 `_apply_transition_sync:252-259` 与 `ahas_open_blocking_threads:356-360` 都只认 `open`）。审查过程中的任何**中间留痕**（如「第 2 轮复检仍未修复」）若用 `record_answer` 写入，会把 BLOCKER finding 推到 `answered`，于是：
- `pending_review → confirmed` 的守卫放行（人审能通过带未决 BLOCKER 的蓝图）；
- `blueprint_resume` 的 pause 判据（`:100-101` 只认 open+blocking）失守，续驱把会话一路 advance。

**正确用法**：
1. **创建 finding** → `open_thread(kind="ai_review_finding", severity=..., blocking=(severity=="blocker"), question=<finding 正文>, anchor=<section_path/block_id/quoted_text>, created_on_version=<当前版本>, initiated_by_user_id="system", return_stage="ai_reviewing")`。
2. **中间留痕**（不改状态）→ 现有唯一通道是私有的 `_append_thread_message_sync`（:1055-1064，`author_type` 硬编码 `HUMAN`）。本相位应**提炼一个公开方法**（如 `append_note(thread, *, body, author=None, author_type=ThreadAuthorType.AI)`），把 `_arecord_gate_note`（:1043-1053）改为调用它——纯增能力、不改既有语义。**绝不新增第二条旁路写表路径**（INV-6 扫描会挂）。
3. **finding 已修复/不成立** → `resolve_thread(thread, resolution=<结论>, dismissed=False|True)`。`dismissed=True` 用于「审查误报，人审驳回该 finding」。
4. **人类回答澄清线程**（`ai_clarification`）→ 这才是 `record_answer` 的正当用法（open→answered 正是澄清流转所需）。

### findings 去重（Discretion 项，给出建议）

同一 block 上重复开线程会让人审侧噪声爆炸。建议以 `(rule_id, anchor.block_id or section_path)` 为幂等键：开线程前查该 artifact 上 `kind="ai_review_finding"` 且 `status__in=[open, answered]` 的既有线程，命中则 `append_note` 追加「第 N 轮仍存在」而非新开。第 2 轮复检时已修复的 finding 走 `resolve_thread`。

## 3. stage 追加与状态映射

### 3.1 注册字典与接续点（`server/services/process_runtime/builtin_processes.py`）

- 注册入口：`:822-849`，三次 `register_process_type`。蓝图链为第三次（`:843-849`）：`process_type="technical_blueprint"`、`artifact_type="technical_plan"`（**不新增 artifact_type**，`:840-842`）、`initial_stage="intake"`、`stages=_TECHNICAL_BLUEPRINT_STAGES`。
- stage 字典：`_TECHNICAL_BLUEPRINT_STAGES`（`:723-817`），九个 stage：`intake`(:724) / `decompose`(:729) / `spec_gate`(:734) / `route`(:741) / `repo_research`(:746) / `reroute`(:756) / `repo_confirmation`(:767) / `repo_plan`(:787) / `merge`(:801)。
- **114 接续点已被 113 显式留好**（`:805-809` 注释原文）：

```
"merge": StageDef(
    ...
    transitions={
        # 114 接续点：追加 ai_review stage 时把该值改为 "ai_review" 即可
        # （transitions 是数据，无需改 engine）。
        "merged": STAGE_DONE,     # ← 本相位改为 "ai_review"
        "repo_rework": "repo_plan",
        "remerge": "merge",
        "needs_clarification": "merge",
    },
    pausable=True,
    wait_status="waiting_clarification",
),
```

**改动上界：`merge.transitions["merged"]` 一行 + 新增 `"ai_review": StageDef(...)` 一项。前九个 stage 的 handler 与 transitions 一字不动**（对齐 `:786` 注释「上面七个 stage 一字未动」的 113 先例）。

### 3.2 handler 签名与 StageOutcome

```python
# 统一形状（九个 handler 全同）：
async def _h_bp_ai_review(session: Any, engine: Any) -> StageOutcome

# server/services/process_runtime/engine.py:34-46
@dataclass
class StageOutcome:
    event: str                              # 查 StageDef.transitions；未登记 event → engine ValueError
    stage_state_update: dict | None = None  # 合并进 session.stage_state 的增量（None 不改）
    current_artifact_version: Any = None    # 本步产出的 ArtifactVersion id
    error: dict | None = None               # 仅 fail/exhausted 路径
```

- 依赖注入范式：`adapter = getattr(getattr(engine, "deps", None), "review", None)`；**缺失时返回 `StageOutcome(event="needs_clarification")`**——`_h_bp_merge:682-695` 已把三条备选的取舍逐条论证（返自身 event 会引擎自旋、返终态 event 是「假装成功」）。114 照抄该纪律。
- 建议的 `ai_review` StageDef 形状（与 CONTEXT 的出口语义一一对应）：

```python
"ai_review": StageDef(
    key="ai_review",
    handler=_h_bp_ai_review,
    transitions={
        "review_passed": STAGE_DONE,          # 仅 WARNING/INFO 或全清 → pending_review
        "review_exhausted": STAGE_DONE,       # 超 2 轮 → pending_review 携未决 BLOCKER（不落 failed）
        "repo_rework": "repo_plan",           # 仓级 BLOCKER 归因打回
        "remerge": "merge",                   # 融合级 BLOCKER 打回
        "needs_clarification": "ai_review",   # 停在本 stage 等澄清
    },
    pausable=True,
    wait_status="waiting_clarification",
),
```

⚠️ `transitions` **不含 `failed` 出边**——与 `merge`（`:807-808`）同纪律：超界是「待人审」不是「流程失败」。

⚠️ `needs_clarification` self-loop 前必须先确保有 open+blocking 线程，否则续驱会 advance 到 `max_steps=20` 上限后落 FAILED。复用 `_abp_ensure_blocking_clarification(session, stage=..., reason=...)`（`_h_bp_merge:713-719` 的用法）。

### 3.3 `blueprint_resume` 的映射表追加

```python
# server/services/process_runtime/blueprint_resume.py:65-68
_STAGE_BLUEPRINT_STATUS: dict[str, str] = {
    "repo_plan": "drafting",   # == BlueprintStatus.DRAFTING
    "merge": "drafting",       # == BlueprintStatus.DRAFTING
}
```

**本相位的唯一改动是加一行**：

```python
    "ai_review": "ai_reviewing",  # == BlueprintStatus.AI_REVIEWING
```

纪律（`:58-64` 注释已立）：
- 值用**字面量**而非 `BlueprintStatus.AI_REVIEWING`——本模块所有 Django import 都在函数内（lazy），模块级表拿不到枚举。
- 已有测试 `test_stage_status_table_matches_enum` 锁死字面量与枚举相等，**新行会被该测试自动覆盖**；`test_blueprint_status_stage_map` 有七条参数化等价性断言背书前七个 stage 回落 `researching`——本次追加不得触碰这七条。
- 消费方 `_resolve_stage_status`（:71-82）与 `_amap_blueprint_status`（:273）无需改动。
- **删除行上界 = 0**。本文件唯一允许的改动是上述一行新增。

`transition` 的合法边已支持全部所需路径（`blueprint_lifecycle_service.py:89-121`）：

```
DRAFTING            → {NEEDS_CLARIFICATION, AI_REVIEWING, FAILED, SUPERSEDED}
AI_REVIEWING        → {NEEDS_CLARIFICATION, DRAFTING, PENDING_REVIEW}
NEEDS_CLARIFICATION → {RESEARCHING, DRAFTING, AI_REVIEWING}
PENDING_REVIEW      → {DRAFTING, CONFIRMED, SUPERSEDED}
```

`_CLARIFICATION_RETURN_TARGETS = {researching, drafting, ai_reviewing}`（:80-86）——`return_status="ai_reviewing"` 已合法，**状态机无需任何改动**。

## 4. 版本与回灌

### 4.1 `add_version` 签名与「同 hash 不翻版本」的确切判定

```python
# server/delivery/services/artifact_service.py:117
async def add_version(
    self,
    artifact: Artifact,
    content: dict,
    *,
    produced_by_session_id: str = "",
    produced_by_ref: str = "",
) -> ArtifactVersion
```

- **先校验后落库**（:126-130）：`validate_content(artifact.artifact_type, content)` 失败 → `raise ArtifactContentInvalid`。蓝图走 `artifact_type="technical_plan"` + `content.schema_version=="blueprint/v1"` 的判别分支（`delivery/artifacts/builtin_types.py`），即 `validate_blueprint`。**人工编辑「不合法直接拒绝、不落半合法版本」这条已由该行天然保证**——但视图层仍应先显式调 `validate_blueprint` 拿到可回显的中文错因（`ArtifactContentInvalid` 的 message 已含 `_format_error` 输出）。
- **幂等判定**（`_add_version_sync:145-162`，全程 `transaction.atomic`）：

```python
artifact.refresh_from_db(fields=["current_version"])
current = artifact.current_version
if current is not None and current.content_hash == new_hash:
    return current            # ← 同 hash 直接复用 current，不建行、不推进 version_no
next_version = (current.version_no + 1) if current is not None else 1
ArtifactVersion.objects.create(..., supersedes=current, content_hash=new_hash, ...)
artifact.current_version = new_version
artifact.save(update_fields=["current_version", "updated_at"])
```

- hash 口径（`artifact_service.py:43-47`）：

```python
canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
sha256(canonical.encode("utf-8")).hexdigest()
```

**推论**：`sort_keys=True` 意味着 key 顺序不影响 hash；但**任何时间戳字段（如 decision_log 的 `decided_at`）都会改变 hash**。澄清回灌若在无实质变更时也写入 `decided_at=now()`，会每次翻新版本，破坏「同 hash 不翻版本」的幂等意图。**建议**：回灌路径的 `decided_at` 取「线程作答消息的 `created_at`」而非 `timezone.now()`（spec_gate 目前用 `timezone.now().isoformat()`，:561——那里每次锁定只跑一次故无碍，114 的回灌是可重放路径，必须换成稳定时间源）。
- `produced_by_ref` 约定：CONTEXT 定人工编辑用 `"human_edit:{user_id}"`；AI 回灌建议 `"ai_review_reflow:{thread_id}"`，与 113 的 merge 版本可在 diff 视图区分。

### 4.2 `blueprint_anchor` 调用契约

```python
# server/delivery/services/blueprint_anchor.py:66
def reanchor(anchor: dict, new_blocks: list[dict]) -> tuple[dict, str]
# 返回 (new_anchor, anchor_status)；anchor_status ∈ {"anchored", "orphaned"}
# 常量：SIMILARITY_THRESHOLD = 0.85 (:28)，ANCHOR_STATUS_ANCHORED/_ORPHANED (:30-31)
```

三分支（:66-106）：① `anchor.block_id` 仍在 `new_blocks` → 原样返回 `anchored`；② `quoted_text` 与各块文本 `difflib.SequenceMatcher.ratio()` 最佳 ≥ 0.85 → `dict(anchor, block_id=best)` + `anchored`（`quoted_text` 保留原文）；③ 否则 `(anchor, orphaned)`。同分取 `block_id` 字典序小者（:97-98，确定性）。空/非 dict anchor → 直接 `orphaned`（:75-76）。

**输入 `new_blocks` 从哪来**：`iter_blocks(content)` 返回 `list[tuple[section_path, block]]`（`blueprint_schema.py:919`），需取第二元素：`new_blocks = [b for _path, b in iter_blocks(new_content)]`。**注意 `reanchor` 不更新 `anchor.section_path`**——只改 `block_id`。若块换了落位，`section_path` 会陈旧。本相位应在批量重锚定时用 `iter_blocks` 的 path 一并刷新 `anchor["section_path"]`（115 渲染依赖它定位）。

**批量应用是本相位的活**（`blueprint_anchor.py:9-10` docstring 原文：「批量应用到线程行的调用方在 Phase 114，111 只交付算法与单测」）。写线程行仍须经 service（INV-6）——`resolve_thread` / `open_thread` 都不改 `anchor`，本相位需**新增**一个 lifecycle service 方法（如 `areanchor_threads(artifact, new_content, *, initiated_by_user_id)`），批量更新 `anchor` / `anchor_status`。

### 4.3 `decision_log` 段的字段形状

Schema 侧是**弱定义**（`blueprint_schema.py:733-736`）：

```python
"decision_log": {"type": "array", "description": "已解决澄清线程的决策快照（可选；DESIGN §3.13）"}
```

实际形状由两个既有写入方确立（必须对齐，否则 §3.13 的自包含语义在导出时分裂）：

| 写入方 | 位置 | 条目形状 | 去重键 |
|--------|------|----------|--------|
| 规格门 | `blueprint_spec_gate.py:569-577` | `{thread_id, question, answer, decided_at, decided_by}` | `thread_id`（`_merge_decision_log:497-510`） |
| 确认门 | `blueprint_confirm_gate.py:906` / `:935-953` | `{thread_id, action, repository_id, before, after, ...}` | `(thread_id, action, repository_id)` |

CONTEXT 要求 114 写 `{thread_id, question, decision, decided_by, applied_in_version}`。**建议采用规格门形状的超集**（保 `question`/`decided_at`/`decided_by`，把 `answer` 与 `decision` 二选一统一为 `answer`，另加 `applied_in_version`），并按 `thread_id` 去重——理由：`blueprint_spec_gate._collect_prior_answers:583-593` 已在**读** `decision_log[].question` / `[].answer` 做「同一问题不再重复问」的指纹去重；若 114 写 `decision` 而不写 `answer`（:587 `item.get("answer")`），那条已建立的纪律在审查阶段就断了。这直接对应 CONTEXT specifics 第 3 条「断言同一问题不再重复问」。

`decided_by` 口径（`blueprint_spec_gate.py:548, 558-559`）：默认 `"human"`，有 `author_id` 时取 `str(author_id)`。AI 侧决策应写 `"ai"`。

## 5. DB 统计接口

三项占位在 `server/services/process_runtime/blueprint_quality.py:105-141`，**顶层零 ORM import**（`:11` 明确要求实装走函数内懒 import）：

```python
def ai_rejection_rate(artifact_id: str) -> float | None      # :111，当前 return None
def human_edit_volume(artifact_id: str) -> int | None        # :122，当前 return None
def clarification_rounds(artifact_id: str) -> int | None     # :132，当前 return None
```

docstring 已锁死口径（不可自行改口径）：

| 函数 | 口径原文 | 本相位要统计的表 |
|------|----------|------------------|
| `ai_rejection_rate` (:112-117) | 「按 `ConvergenceSessionEvent` 的 `blueprint.stage.*` 事件统计（打回轮次 / ai_reviewing 总轮次）」 | `ConvergenceSessionEvent`——需按 `stage=ai_review` 的 event 名区分打回（`repo_rework`/`remerge`）与总轮次 |
| `human_edit_volume` (:123-126) | 「按 `created_by_user_id` 非系统的版本行计数」 | `ArtifactVersion`。⚠️ **该模型无 `created_by_user_id` 字段**（`add_version` 只写 `produced_by_session_id` / `produced_by_ref`，`artifact_service.py:151-159`）。实装必须改用 `produced_by_ref__startswith="human_edit:"`——这是 111 docstring 与实际模型的**已知偏差**，计划里要显式登记为「口径 docstring 同步修正」 |
| `clarification_rounds` (:133-137) | 「按 `BlueprintThread` / `BlueprintThreadMessage` 统计（每线程一问一答记一轮）」 | `BlueprintThread`（filter `artifact_id`）+ `BlueprintThreadMessage`（按 `thread__artifact_id` 计 `author_type=human` 的消息数） |

三个函数都是**同步**签名。若实装需 ORM 查询，从 async 上下文调用必须 `sync_to_async` 包裹（或新增 `a*` 变体）。**建议保持同步签名不变**（111 已交付、被 `evaluate_blueprint_golden` 离线评估调用），内部懒 import ORM，由调用方决定是否包裹。

三项都返回 `| None` 表示「指标不可用」——无数据时**必须继续返回 None 而不是 0**，否则 golden 评估会把「没数据」当成「零打回」。

## 6. 人审与编辑端点落位

### 6.1 112 确认门端点的既有惯例

文件：`server/delivery/api/blueprint_gate_views.py`（八个端点，`:1-30` docstring 立了全部纪律）；路由：`server/delivery/urls.py:136-177`。

| 惯例 | 出处 | 内容 |
|------|------|------|
| URL 形状 | `urls.py:139-176` | `artifacts/<uuid:artifact_id>/blueprint-gate/<动作段>/`，动作段为**字面 kebab-case**，name 为 `blueprint-gate-<动作>` |
| 一动作一 View | `blueprint_gate_views.py:4` | 「一动作一 View、**不发明 action 分派**」 |
| 基类 | `:35` | `from adrf.views import APIView`（异步） |
| 权限 | `:38, :206, :230, :277…` | `permission_classes = [IsAuthenticated]`——「与 delivery/repositories 既有 view 同级，§6.4『项目成员皆可确认』的低门槛决策」（`:3-4`） |
| 写入纪律 | `:16-20` | **视图零 ORM 写**，全部委托 service；读路径允许视图直查；serializer `.data` 一律 `sync_to_async` 包裹 |
| 错误码分层 | `:153-179` | 不存在类 → 404（中性消息常量 `_ARTIFACT_MISSING_DETAIL` / `_GATE_NOT_OPEN_DETAIL` / `_SESSION_MISSING_DETAIL`），入参类 → 400 |
| 续驱接线 | `:22-30` | 改状态的动作端点在**持久化成功之后**调 `blueprint_resume.aresume_after_gate_action`；失败隔离在 helper 内自带 try/except，视图**不重复包 try**、**不因续驱失败改响应码**；只读端点不接续驱 |

### 6.2 本相位端点应放哪里

**建议新建 `server/delivery/api/blueprint_review_views.py`**，路由前缀 `artifacts/<uuid:artifact_id>/blueprint-review/`，理由：

1. `blueprint_gate_views.py` 已有八个 View + 一批门专属 helper（`_ARTIFACT_MISSING_DETAIL` / `_GATE_NOT_OPEN_DETAIL` / `_lookup_gate_repository` 等），本相位再塞 4–6 个语义不同的 View（人审通过/驳回、block patch、findings 列表、失锚线程列表）会让「确认门」文件承担两个门的语义，违背 112 自己立的「一动作一 View、不发明分派」的清晰边界。
2. URL 前缀区分让 115 的前端数据面一目了然（`blueprint-gate/` = 阶段 1 门，`blueprint-review/` = 阶段 4 人审）。
3. 新文件**逐条照抄** 6.1 的七条惯例（adrf `APIView` + `IsAuthenticated` + 视图零 ORM 写 + 404/400 分层 + 续驱失败隔离）。

建议端点集：

| 方法 | URL | 动作 | service 收口 |
|------|-----|------|--------------|
| GET | `artifacts/<uuid>/blueprint-review/` | findings + 线程 + 失锚列表快照（只读，不接续驱） | 视图直查允许 |
| POST | `artifacts/<uuid>/blueprint-review/approve/` | 人审通过 → `confirmed` | `transition(..., to_status="confirmed", acting_user=request.user)`（守卫 + reviewer upsert 同事务） |
| POST | `artifacts/<uuid>/blueprint-review/reject/` | 驳回 → `drafting` + `revision_round + 1` | `transition(..., "drafting")` + 划线评论经 `open_thread(kind="human_comment")` |
| POST | `artifacts/<uuid>/blueprint-review/edit-blocks/` | block 级 patch ops | 新建 service 方法收口 → `validate_blueprint` → `add_version(produced_by_ref=f"human_edit:{user_id}")` → 批量重锚定 |
| POST | `artifacts/<uuid>/blueprint-review/threads/<uuid>/answer/` | 澄清作答 | `record_answer`（此处才是它的正当用法） |

⚠️ **`revision_round` 是蓝图 content 字段，不是模型字段**——`blueprint_schema.py:160-164`，位于 `meta` 段（`:142-165`）：

```python
"revision_round": {"type": "integer", "minimum": 0,
                   "description": "修订轮次（AI 审查打回 / 人审驳回 +1）"}
```

全仓 `rg revision_round` 只命中 schema 定义、`blueprint_merge` 的两处注释（`:1576`, `:2218`，标注为「非 required 键」）、golden fixture 与测试 helper——**没有任何写入方**。`Artifact` 模型上不存在该字段。

因此「驳回 → `revision_round + 1`」的正确实现是：读 current content → `content["meta"]["revision_round"] = 旧值 + 1` → `add_version(...)` 产新版本 → 再 `transition(..., "drafting")`。**不要**去扩 `_apply_transition_sync`。⚠️ 顺序很重要：先落版本再转状态，否则状态已 `drafting` 而轮次未加的窗口里，AI 会拿旧轮次重跑。两步之间的失败需幂等——`add_version` 的同 hash 复用（`:148-149`）保证重试不会连加两次**只有在轮次值相同时成立**，故重试前必须重读 current content 而非用内存副本。

⚠️ **approve 端点必须先查未决 BLOCKER**：`transition(to_status=confirmed)` 的内建守卫只查 `open + blocking` 线程（:252-259）。CONTEXT 要求的守卫是「无 open+blocking 线程 **+ 无未解决 BLOCKER**」。若 BLOCKER finding 都以 `blocking=True` 开线程，两者等价；但 `severity=blocker` 而 `blocking=False` 的条目会漏挡。**建议**：`ai_review_finding` 的 `blocking` 严格等于 `severity == "blocker"`，把两个条件收敛成一个，并在测试里断言这条不变式。

## Don't Hand-Roll

| 问题 | 别自己写 | 用这个 | 为什么 |
|------|----------|--------|--------|
| 蓝图结构校验 | 自己遍历字段 | `validate_blueprint`（`blueprint_schema.py:793`） | 已含 5 项后置检查 + 报错脱敏截断 |
| block 走查取 section_path | 自己递归 | `iter_blocks`（`blueprint_schema.py:919`） | 115 渲染消费同一路径约定，两份实现必漂移 |
| 版本 hash / 幂等 | 自己算 hash 比对 | `add_version`（`artifact_service.py:117`） | canonical json + 事务内 CAS + supersedes 链 |
| 线程重锚定相似度 | 自己写模糊匹配 | `reanchor`（`blueprint_anchor.py:66`） | 0.85 阈值 + 同分字典序确定性已单测锁死 |
| 章程批量读 | 自己写 ORM | `aload_charters`（`blueprint_charter_match.py:288`） | 避免 N+1 与 async 裸 lazy-FK；best-effort 不阻断 |
| 线程状态流转 | 直接写 ORM | `BlueprintLifecycleService` | `test_blueprint_inv6_guard` 源码扫描会挂 |
| block diff | 自己比对 | `diff_blueprint_blocks`（`blueprint_schema.py:1044`） | 人工编辑与 AI 版本共用同一 diff 视图 |

## Common Pitfalls

### P1：机械规则跑半成品蓝图的空值 / 缺段防护

**会出什么错**：`ai_review` 的输入来自 `merge`，而 `merge` 的 `exhausted` 出口**也走 `merged` 边**（`builtin_processes.py:704-709`，注释 `:807-808` 明确「覆盖率未达标也进」）。因此 114 拿到的蓝图**可能是「已成形但未达标」的半成品**：某些段可能整段缺失、`repo_associations` 可能为空、`citations` 池可能不存在。

**具体防护清单**：
- `validate_blueprint` 对缺 `schema_version` 的 content **直接返回 `(True, None)`**（`:809-810`）——规则①必须先自行断言 `schema_version == "blueprint/v1"`，否则半成品「假通过」。
- `citation_coverage` 分母为 0 返回 **1.0**（`blueprint_quality.py:76`）——空文档拿满分。规则②必须走条目级判定而非比率阈值。
- `target_repo_hit_rate` expected 为空返回 **1.0**（`:92-93`）——同理。
- 规则③④⑤⑥的所有集合运算，被减集合为空时应判 **skip 而非 pass**：`repo_associations` 为空时「每个 direct 仓 ≥1 实现项」恒真，这是假阳性通过。**建议**：单开一条「前置完整性」判定——六段中任一为空即 BLOCKER（`repo_associations` / `implementation_overview.items` / `requirement_spec.feature_points` 三者必非空），命中则短路，不再跑后五条规则（避免一片假通过噪声）。
- 所有 `.get` 链路要容忍 `None` / 非 dict / 非 list（111 全模块已立此纪律，逐字沿用）。
- **测试要求**：六条规则各构造一条「空蓝图」样例，断言输出是 skip 或 BLOCKER，**绝不是 pass**。

### P2：打回计数与既有 `stage_state` 键冲突

`stage_state` 是**扁平顶层 dict**（`StageOutcome.stage_state_update` 合并进 `session.stage_state`，`engine.py:38`）。**已被占用的顶层键清单**（实读）：

| 键 | 写入方 | 出处 |
|----|--------|------|
| `decomposition` | `_h_bp_decompose` | `builtin_processes.py:73, :104` |
| `routing` | `_h_bp_route`（唯一写入方） | `builtin_processes.py:117, :364`；`blueprint_route.py:14` |
| `spec_gate` | `BlueprintSpecGateAdapter` | `blueprint_spec_gate.py:69` (`STAGE_STATE_KEY`), `:703` |
| `repo_research_fitness` | 调研 adapter | `blueprint_research_adapter.py:93` (`_FITNESS_STATE_KEY`), `:774` |
| `reroute` | 调研 adapter | `blueprint_research_adapter.py:1086, :1126` |
| `confirmation` | `blueprint_confirm_gate` | `blueprint_confirm_gate.py:67` (`STAGE_STATE_KEY`), `:428, :438, :486` |
| `repo_plan` | `blueprint_repo_plan` | `blueprint_repo_plan.py:56` (`STAGE_STATE_KEY`), `:679` |
| `merge` | `blueprint_merge` | `blueprint_merge.py:88` (`STAGE_STATE_KEY`), `:2290, :2330` |
| `include_repos` | 入口 | `builtin_processes.py:97`；`entrypoint.py:66` |
| `blueprint` | 入口嵌套持有者 | `blueprint_route.py:445, :849` |

`ai_review` / `review` **均未被占用**。**建议**：新建 `blueprint_review.py` 内定义 `STAGE_STATE_KEY = "ai_review"`（与三个既有模块同名常量的命名范式一致），打回计数存 `stage_state["ai_review"]["round"]`。

⚠️ **绝不要复用 `merge` 桶存审查轮次**：`blueprint_merge` 的 `_merge_state`（`:2290`）会**整桶读改写**（`:2330` `{**state, STAGE_STATE_KEY: bucket}`），114 塞进去的键会在下一次 merge 打回时被覆盖，打回计数归零 → **无限循环**（这正是 CONTEXT specifics 第 2 条要求证伪的场景）。

⚠️ **上下文纪律（DESIGN §5.2 强制，`DESIGN.md:472`）**：「`stage_state` 只允许存 id、计数、小摘要（单字段 < 2KB）」。findings 正文**绝不进 `stage_state`**，只存 `{round, thread_ids: [...], blocker_count, warning_count, info_count, back_target}`。

### P3：重锚定在大量 block 变动时的性能

`reanchor`（`blueprint_anchor.py:92-100`）对**每条线程**遍历**全部新 block** 做 `difflib.SequenceMatcher(...).ratio()`。复杂度 O(线程数 × 块数 × 文本长度²)——`SequenceMatcher.ratio()` 本身是准平方级。一份大蓝图数百个 block、数十条线程时，单次重锚定可能进入秒级甚至更差，而它挂在**同步请求路径上**（人工编辑端点 → 产新版本 → 重锚定）。

**防护**：
1. **先做精确命中短路**：`reanchor` 已内建（`:81-83`，block_id 命中直接返回，不进模糊分支）。批量调用方应**先用 `diff_blueprint_blocks`（`blueprint_schema.py:1044`）算出变动块集合**，只对 anchor 落在变动块上的线程走 `reanchor`，未变动块的线程直接跳过。这把常见场景（改一两个块）从 O(N×M) 降到 O(1)。
2. 用 `quick_ratio()` 预筛：`SequenceMatcher.quick_ratio()` 是 O(N) 上界估计，低于 0.85 的候选可直接淘汰再算精确 `ratio()`。**但这需要改 `blueprint_anchor.py`（111 交付、有单测）**——若要做，必须保证输出逐字等价（`quick_ratio() >= ratio()` 恒成立，故淘汰安全），并在计划里登记为「111 模块的性能优化改动」。**默认建议先不改**，靠第 1 条即可。
3. 批量重锚定应在 service 层用 `bulk_update` 一次写回 `anchor` / `anchor_status`，不要逐行 save。

### P4：`transition` 的并发 CAS 语义

- **方法名是 `transition` 不是 `atransition`**（`blueprint_lifecycle_service.py:143`）。
- CAS 实现（`_apply_transition_sync:261-269`）：`Artifact.objects.filter(id=..., blueprint_status=from_status).update(blueprint_status=to_status, updated_at=timezone.now())`；`updated != 1` → `raise ConcurrentBlueprintTransitionError`（`:70`）。
- `from_status` 取自**内存对象**（`transition:167` `artifact.blueprint_status`）。若调用方持有的 `artifact` 实例是陈旧的，CAS 会拒（这是设计意图），但**调用方必须处理该异常**：审查 handler 里应 `refresh_from_db` 后重试一次，或把它映射成 `needs_clarification` event 而不是让 engine 落 FAILED。
- `updated_at` 是 `auto_now` 字段，`.update()` **绕过 auto_now**——必须显式带上（`:243-244` 已注释）。本相位若扩 `_apply_transition_sync` 加 `revision_round` bump，同样必须显式带字段。
- **守卫与 CAS 同事务**（`:251` `transaction.atomic`）：confirm 的 open+blocking 检查与状态更新在同一事务内，check-then-act 窗口已收敛（MN-01）。114 若在**视图层**先查 BLOCKER 再调 `transition`，那次查询在事务外——存在窗口。**建议**把「无未解决 BLOCKER」收敛为「无 open+blocking 线程」（见 §6.2 的不变式建议），直接复用事务内守卫。
- 非法转移 `raise ValueError`（`:169-173`），状态不变、DB 不写。两类异常语义不同，端点错误码应分开：`ValueError` → 400/409，`ConcurrentBlueprintTransitionError` → 409。

### P5：§13.2 冻结清单 + `blueprint_resume` 追加纪律

**§13.2 第 2 条（`DESIGN.md:772`）——对 v0.20 只读冻结的文件**：

```
server/services/process_runtime/decompose_segments.py
server/services/process_runtime/research_adapter.py
server/services/process_runtime/architect_merge_adapter.py
delivery 侧 merged_plan.py
server/services/process_runtime/clarify_adapter.py
render.py
```

「三大阶段流水线全部走**新文件**（`blueprint_*` adapters + schema 模块），`builtin_processes.py` **仅新增**一个 process 注册项」。114 的等价推论：新逻辑一律进 `blueprint_review.py`；`builtin_processes.py` 只加 `_h_bp_ai_review` + `_TECHNICAL_BLUEPRINT_STAGES["ai_review"]` + 改 `merge.transitions["merged"]` 一行。

**§13.2 第 3 条（`:773`）**：`ConvergenceSessionEvent` 既有事件类型与 payload 由 v0.19 定义，**0.20 只新增 `blueprint_*` 事件类型，不改既有类型与字段**。`blueprint_review_started/completed/failed` 是新增，合规。

**§13.2 第 4 条（`:774`）**：前端只新建不改旧——本相位无前端，但 115 消费面的数据形状要一次定好。

**§13.2 第 5 条（`:775`）**：新增 migration 在每次同步点 rebase 时重新生成序号。本相位若给 `BlueprintThread` 加字段（不建议）会引入 migration；`severity` 字段**已存在**（`blueprint_thread.py:92`），只需改 service 签名，**零 migration**——这是应当保持的状态。

**`blueprint_resume` 追加纪律**（113-06 已立，逐字沿用）：
- 本文件**唯一允许的改动**是 `_STAGE_BLUEPRINT_STATUS` 加一行 `"ai_review": "ai_reviewing"`。
- **删除行上界 = 0**。任何删除都要逐行登记并说明。
- 不改 `_resolve_stage_status` / `_amap_blueprint_status` / 三个 `a*` 入口的任何行为。
- 前七个 stage 回落 `researching` 的七条参数化等价性断言（`test_blueprint_status_stage_map`）必须继续绿。

### P6：`_h_bp_merge` 的「三条备选」教训必须照抄

`_h_bp_merge` 的 docstring（`builtin_processes.py:682-691`）逐条论证了 handler 在依赖缺失时的三种错误出口：返自身 event → **引擎自旋**；返终态 event → **假装成功**（下游拿到空输入，最坏的静默失败）；返 `needs_clarification` → 正确。`_h_bp_ai_review` 必须照抄第三条，且 self-loop 前先 `_abp_ensure_blocking_clarification`（`:713-719`），否则续驱会 advance 到 `max_steps=20`（`blueprint_resume.py:94, :130-135`）后落 FAILED。

## Runtime State Inventory

本相位为新增功能，非 rename/refactor。仍逐项确认运行期状态：

| 类别 | 发现 | 需要的动作 |
|------|------|------------|
| 存储数据 | `delivery_blueprint_thread` / `delivery_blueprint_thread_message` 表已存在（111 建），本相位只新增行 | 无迁移；`severity` 字段已存在 |
| 会话运行态 | `ConvergenceSession.stage_state` 是活跃 JSON，新增顶层键 `ai_review`；`current_stage` 会出现新值 `"ai_review"` | 已在途会话（`current_stage="merge"`）在本相位上线后，`merged` 会转到新 stage 而非 DONE——**这是行为变更**，需确认无生产在途蓝图会话，或接受其多走一个 stage |
| OS 注册态 | 无（无 cron / task scheduler 变更）；pending 超时提醒若用 apscheduler 需登记 | 提醒周期走 `SystemSetting`（§12 已定），不新增 OS 级注册 |
| 密钥 / 环境变量 | 无新增；LLM 调用走 111 已注册的 `call_source="blueprint_ai_review"` | 无 |
| 构建产物 | 无 | 无 |

## Environment Availability

无新增外部依赖。本相位全部使用仓内既有能力：`jsonschema`（已在 `blueprint_schema.py` 使用）、`difflib`（stdlib）、`hashlib`/`json`（stdlib）、Django ORM、既有 LLM 调用通道。**无需 Package Legitimacy Audit**（零外部包安装）。

## Validation Architecture

### Test Framework

| 属性 | 值 |
|------|-----|
| 框架 | `pytest>=9.0.2` + `pytest-django>=4.8` + `pytest-asyncio`（`server/pyproject.toml`） |
| 配置 | `server/pyproject.toml` `[tool.pytest.ini_options]`；`server/tests/conftest.py`（含 adrf monkeypatch） |
| 既有蓝图测试落位 | `server/tests/delivery/`（如 `test_blueprint_anchor.py`、`test_blueprint_inv6_guard.py`）与 `server/tests/services/process_runtime/` |
| 快速跑 | `uv run pytest server/tests/delivery/test_blueprint_review*.py -x` |
| 全量 | `uv run pytest server/tests/ -q` |

### 关键断言（CONTEXT specifics 直接映射）

| 断言 | 类型 | 说明 |
|------|------|------|
| 六类规则各一条证伪样例（缺引用 / 角色不一致 / API 断链 / 超期排期 / 越确认门 / 违章程） | unit（纯函数，无 DB） | CONTEXT specifics 第 1 条 |
| 空蓝图 → 六条规则全部 skip 或 BLOCKER，绝不 pass | unit | P1 |
| 持续 BLOCKER → 2 轮后转 `pending_review` 且携未决清单，不落 FAILED | integration（engine 驱动） | CONTEXT specifics 第 2 条 |
| `stage_state["ai_review"]` 与 `merge` 桶互不覆盖 | integration | P2 |
| 同一问题不再重复问（查 `decision_log` + resolved 线程指纹） | integration | CONTEXT specifics 第 3 条 |
| `record_answer` **不**被用于 finding 留痕（源码扫描或行为断言：留痕后线程仍 `open`） | unit | 112 教训 |
| `_STAGE_BLUEPRINT_STATUS` 新行与枚举相等 | unit | 已有 `test_stage_status_table_matches_enum` 自动覆盖 |
| 前七 stage 回落 `researching` 七条断言仍绿 | 回归 | P5 |
| 人工编辑不合法 content → 拒绝且**不落版本** | integration | INV-6 + `add_version:126-130` |
| 同 content_hash 重复回灌 → 不翻版本 | integration | `_add_version_sync:148-149` |

### Wave 0 Gaps

- `server/tests/services/process_runtime/test_blueprint_review.py` —— 六类规则纯函数单测（新建）
- `server/tests/delivery/test_blueprint_review_views.py` —— 人审 / 编辑端点（新建）
- `server/tests/services/process_runtime/test_blueprint_review_loop.py` —— 有界回退 + 超界出口（新建）
- 蓝图构造 fixture：建议复用 111 golden set 的样例蓝图作基线，逐条注入缺陷生成六个证伪样例

## Security Domain

| ASVS 类别 | 适用 | 标准控制 |
|-----------|------|----------|
| V2 Authentication | 是 | `IsAuthenticated`（沿用 `blueprint_gate_views.py:38` 惯例） |
| V3 Session Management | 否（复用既有 JWT） | — |
| V4 Access Control | 是 | §6.4「项目成员皆可编辑」——与 112 同级低门槛；但 404 中性消息避免枚举（`blueprint_gate_views.py:153-179`） |
| V5 Input Validation | 是 | patch ops 与 content 一律过 `validate_blueprint`；`add_version` 内建校验 |
| V6 Cryptography | 否 | 不涉及 |

| 威胁 | STRIDE | 缓解 |
|------|--------|------|
| 半合法 content 落版本 | Tampering | `add_version:126-130` 校验前置 + 视图层显式 `validate_blueprint` 回显 |
| BLOCKER 被 `record_answer` 意外推到 answered 后绕过确认守卫 | Elevation of Privilege | 留痕走 `append_note`；`blocking == (severity=="blocker")` 不变式 + 测试 |
| 蓝图正文 / 凭证样本经报错回显 | Information Disclosure | `_format_error`（`blueprint_schema.py:764`，500 字符截断）+ `redact_secrets_in_text` |
| findings 正文进事件 payload | Information Disclosure | CONTEXT 已锁「正文不进 payload」，只进计数与分级分布 |
| 并发人审导致状态错乱 | Tampering | `transition` 的事务内 CAS（`:251-269`） |

## Assumptions Log

| # | 断言 | 章节 | 猜错的后果 |
|---|------|------|------------|
| A1 | `open_thread` 需要追加 `severity` 形参才能落 findings 分级 | §2 | 若计划漏了这步，findings 的 severity 全为 `""`，人审无法分级、`blocking` 与 severity 的不变式无从建立 |
| A2 | `human_edit_volume` 的 docstring 口径（`created_by_user_id`）与 `ArtifactVersion` 实际字段不符，须改用 `produced_by_ref__startswith="human_edit:"` | §5 | 实装时按 docstring 写会直接 `FieldError` |
| A3 | 建议新建 `blueprint_review_views.py` 而非塞进 `blueprint_gate_views.py` | §6.2 | 属 Discretion 范围，塞在一起也能跑，只是文件语义混杂 |
| A4 | 「违背 `RepoCharter.boundaries.rule`」是文本语义，机械规则只能做到 `evolution` 那一层 | §1 规则⑥ | 若强判 BLOCKER 会产生不可复现的假阳性，违背「可复现可证伪」的立项前提 |
| A5 | `decision_log` 采用规格门形状超集（保 `answer` 键） | §4.3 | 若只写 `decision`，`blueprint_spec_gate._collect_prior_answers:587` 读不到，「同一问题不再重复问」在审查阶段断链 |
| A6 | `meta.revision_round` 由本相位首次写入（此前无写入方，默认缺省） | §6.2 | 若某处已在写而本次调研漏了，会出现双写竞争；已用 `rg revision_round` 全仓确认只有 schema 定义 + 注释 + fixture |

## Open Questions

1. **`ai_review` stage 的 `severity` 落库需要改 `open_thread` 签名——是否接受？**
   - 已知：`BlueprintThread.severity` 字段已存在（`blueprint_thread.py:92`），零 migration；`open_thread`（`:365-377`）无该形参。
   - 不清楚：是否有「111 service 签名冻结」的隐含纪律。§13.2 只冻结旧 `technical_plan` 文件，`blueprint_lifecycle_service.py` 是 0.20 自己的新文件，不在冻结清单内。
   - **推荐**：接受，追加 `severity: str = ""`（默认空 = 既有 112/113 调用逐字等价），同时补一条 `severity ∈ ThreadSeverity.values or ""` 的入参校验。

2. **`revision_round + 1` 放哪？**
   - 已知：`revision_round` 是 content 的 `meta` 段字段（`blueprint_schema.py:160-164`），**不是模型字段**，全仓无写入方；`transition` 只更新 `blueprint_status` + `updated_at`（`:261-263`）。
   - **推荐**：驳回端点按「读 current content → `meta.revision_round += 1` → `add_version` → `transition("drafting")`」的顺序做，本相位成为该字段的首个写入方。AI 审查打回同理（同一 helper）。不扩 `_apply_transition_sync`。

3. **「无未解决 BLOCKER」守卫与「无 open+blocking 线程」是否收敛为一条？**
   - 已知：`transition(confirmed)` 的事务内守卫只查 `open+blocking`（`:252-259`）；视图层额外查 BLOCKER 会落在事务外，有 TOCTOU 窗口。
   - **推荐**：收敛为一条——强制 `ai_review_finding` 的 `blocking == (severity == "blocker")`，用单测锁死该不变式，人审端点直接依赖内建守卫，不加事务外二次查询。

4. **在途会话的行为变更**（`merge.merged` 从 `STAGE_DONE` 改指 `ai_review`）
   - 已知：改动即生效，已 `current_stage="merge"` 的会话下次 advance 会进新 stage。
   - **推荐**：接受（v0.20 尚未上线，无生产在途会话），但在计划里显式登记为已知行为变更，并在 execute 前确认开发环境无残留会话。

## Sources

### Primary（HIGH confidence，全部为本仓代码实读）
- `server/services/process_runtime/blueprint_schema.py`（:205-323, :509-574, :670-751, :764-935, :1044）
- `server/services/process_runtime/blueprint_quality.py`（全文 141 行）
- `server/delivery/services/blueprint_anchor.py`（全文 107 行）
- `server/delivery/services/blueprint_lifecycle_service.py`（:70-137, :140-283, :347-576, :1043-1064）
- `server/delivery/models/blueprint_thread.py`（全文 160 行）
- `server/services/process_runtime/builtin_processes.py`（:304-849）
- `server/services/process_runtime/blueprint_resume.py`（:40-139）
- `server/delivery/services/artifact_service.py`（:43-162）
- `server/repositories/models.py`（:1091-1167 RepoCharter）
- `server/services/process_runtime/blueprint_charter_match.py`（:29-35, :175-330）
- `server/services/process_runtime/blueprint_confirm_gate.py`（:58-67, :263-303, :906-953）
- `server/services/process_runtime/blueprint_spec_gate.py`（:66-69, :497-596）
- `server/services/process_runtime/blueprint_merge.py`（:60-88, :2290-2330）
- `server/services/process_runtime/blueprint_repo_plan.py`（:47-56, :165-190, :679）
- `server/services/process_runtime/blueprint_research_adapter.py`（:93, :774, :1086-1126）
- `server/services/process_runtime/engine.py`（:34-64）
- `server/delivery/api/blueprint_gate_views.py`（:1-40, :153-460）
- `server/delivery/urls.py`（:136-177）
- `.planning/technical-blueprint/DESIGN.md`（§5.2 表 :460-472、§5.5、§13.2 :769-777）
- `.planning/phases/114-ai/114-CONTEXT.md`（全文）

### Secondary / Tertiary
- 无。本相位零外部依赖，未使用 WebSearch / Context7。

## Metadata

**Confidence breakdown:**
- Standard stack：HIGH —— 零新增依赖，全部符号实读定位到行号
- Architecture：HIGH —— 113 在 `builtin_processes.py:805-809` 与 `blueprint_resume.py:58-68` 显式留好了 114 接续点与追加纪律
- Pitfalls：HIGH —— P2 的 `stage_state` 键清单、P4 的 CAS 语义、P5 的冻结清单均逐条实读；P3 的性能判断基于 `difflib` 算法特性（stdlib 常识）+ 代码实读，属 MEDIUM-HIGH

**Research date:** 2026-07-30
**Valid until:** 本仓代码变更即失效——111/112/113 的模块若在 rebase 中改动，须重核 §1–§6 的行号
