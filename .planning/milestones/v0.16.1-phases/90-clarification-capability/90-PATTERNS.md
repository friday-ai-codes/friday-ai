# Phase 90: 澄清能力层 (clarification-capability) - Pattern Map

**Mapped:** 2026-06-27
**Files analyzed:** 9 (3 model/migration · 1 service · 3 plan_orchestration · 测试集)
**Analogs found:** 9 / 9（全部在仓内有强匹配，无新栈）

> 本 phase 90% 是「模型扩展 + 接线」。几乎每个新文件都能从**自身既有版本**或**同 app 邻近模型/迁移**直接拷范式。下表给每个落点的最近 analog + 可拷贝的具体片段（文件:行号）。

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/delivery/models/clarification.py`（扩展容器 + 新增 `ClarificationQuestion` 子表） | model | CRUD / storage | `server/delivery/models/technical_plan.py`（父子 FK 子表范式）+ 自身 | exact（父子模型）|
| `server/delivery/models/__init__.py`（re-export 子模型） | config / barrel | — | 自身（既有 re-export 块） | exact |
| `server/delivery/migrations/0026_*.py`（容器 AddField + 子表 CreateModel） | migration | schema | `0016_clarification.py`（CreateModel）+ `0024_ingestrun_durable_queue.py`（AddField/AlterField） | exact |
| `server/delivery/services/clarification_service.py`（`create_round`/`answer_round`/`ahas_pending`） | service | CRUD（INV-6 单一写入） | 自身（`create_clarification`/`answer_clarification`） | exact |
| `server/services/plan_orchestration/clarify_adapter.py`（接 LLM 多题 + pending 升级 + fail-soft） | adapter / orchestration | request-response + LLM | 自身（`clarify` 三段判定）+ `clarification_questions.py` | exact |
| `server/services/plan_orchestration/ask_clarification.py`（统一 helper，CLARIFY-03） | helper / orchestration | transform → write | `clarify_adapter.py`（薄封装 service）+ `resume.py`（入口无关 docstring 范式） | role-match |
| `server/services/plan_orchestration/resume.py`（CLARIFYING pending 短路升级） | helper / orchestration | event-driven 续驱 | 自身（`adrive_...` clarifying 短路 63-68） | exact |
| `server/tests/delivery/test_clarification_service.py`（采纳率/兼容/INV-6 守护扩展） | test | unit | 自身（`test_inv6_...` 146-163） | exact |
| `server/tests/services/test_ask_clarification_helper.py`（新建，CLARIFY-03） | test | unit | `test_engine_clarify.py` / `test_clarification_service.py` | role-match |

## Pattern Assignments

### `server/delivery/models/clarification.py` (model, CRUD/storage)

**Analog A（自身——容器扩展）:** `server/delivery/models/clarification.py:20-49`
**Analog B（父子子表 FK 范式）:** `server/delivery/models/technical_plan.py:96-128`（`PlanVersion` 子表）

**容器现状（保留不删，新增字段一律 nullable）** — `clarification.py:20-49`:

```20:49:server/delivery/models/clarification.py
class Clarification(models.Model):
    """HITL 澄清问答（§6 字段 + affected_partials 重跑面）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 归属一次 PlanSession 编排；删 session 级联删其澄清
    session = models.ForeignKey(
        "delivery.PlanSession",
        on_delete=models.CASCADE,
        related_name="clarifications",
    )
    question = models.TextField()
    answer = models.TextField(blank=True, default="")
    answered_at = models.DateTimeField(null=True, blank=True)
    # 回答后哪些 task 须重跑；related_name="+" 不污染 RepoResearchTask 反查
    affected_partials = models.ManyToManyField(
        "delivery.RepoResearchTask",
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
```

**子表 FK 范式拷自** `technical_plan.py:96-128`（CASCADE + `related_name` + `JSONField(default=...)` + `Meta.db_table`/`indexes`）:

```96:128:server/delivery/models/technical_plan.py
class PlanVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(
        TechnicalPlan,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version = models.PositiveIntegerField()
    ...
    content = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "delivery_plan_version"
        unique_together = (("plan", "version"),)
        indexes = [
            models.Index(fields=["plan", "-version"]),
        ]
```

**拷贝指引（RESEARCH §Pattern 1，行 188-213）:**
- 容器新增 `round_no` / `container_status`（**不要叫 `status`**，避免与 `PlanSession.status` 混淆）/ `origin_repo` / `plan_version_id`，全部 `null=True, blank=True`。
- 子表 `ClarificationQuestion`：FK 容器 `on_delete=CASCADE, related_name="questions"`；`order`/`question`(TextField)/`qtype`(**避开内建 `type`**)/`options`(JSONField default=list)/`recommended`(JSONField)/`origin_repo`/`selected`(JSONField null)/`freeform_text`/`answered_at`/`recommendation_adopted`(BooleanField null)。
- `Meta.db_table="delivery_clarification_question"` + `indexes=[Index(fields=["clarification","order"])]`，对齐 `PlanVersion` 复合索引范式。

---

### `server/delivery/models/__init__.py` (barrel re-export)

**Analog:** 自身 `__init__.py:7`（`from delivery.models.clarification import Clarification`）+ `:64-70`（多符号 re-export）+ `:109`（`__all__` 条目）。

**Imports pattern** — `__init__.py:64-70`:

```64:70:server/delivery/models/__init__.py
from delivery.models.technical_plan import (
    PlanExternalRef,
    PlanVersion,
    TechnicalPlan,
    TechnicalPlanOrigin,
    TechnicalPlanStatus,
)
```

**拷贝指引:** 把 `:7` 单行扩展为 `from delivery.models.clarification import (Clarification, ClarificationQuestion)`，并在 `__all__`（`:109` 旁）加 `"ClarificationQuestion"`。

---

### `server/delivery/migrations/0026_*.py` (migration, schema)

**Analog A（CreateModel 子表）:** `0016_clarification.py:9-35`
**Analog B（AddField/AlterField 容器）:** `0024_ingestrun_durable_queue.py:6-28`

**CreateModel + Meta options 范式** — `0016_clarification.py:15-34`:

```15:34:server/delivery/migrations/0016_clarification.py
    operations = [
        migrations.CreateModel(
            name='Clarification',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('question', models.TextField()),
                ('answer', models.TextField(blank=True, default='')),
                ('answered_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('affected_partials', models.ManyToManyField(blank=True, related_name='+', to='delivery.reporesearchtask')),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='clarifications', to='delivery.plansession')),
            ],
            options={
                'db_table': 'delivery_clarification',
                'ordering': ['created_at'],
                'indexes': [models.Index(fields=['session'], name='delivery_cl_session_29b666_idx')],
            },
        ),
    ]
```

**AddField nullable 范式** — `0024_ingestrun_durable_queue.py:13-22`:

```13:22:server/delivery/migrations/0024_ingestrun_durable_queue.py
        migrations.AddField(
            model_name='ingestrun',
            name='durable_job_id',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='ingestrun',
            name='idempotency_key',
            field=models.CharField(blank=True, db_index=True, default='', max_length=128),
        ),
```

**拷贝指引（RESEARCH §Pattern 1，行 184-187）:**
- `dependencies = [('delivery', '0025_rename_project_to_space')]`（**执行前 `ls server/delivery/migrations/` 复核 head 仍为 0025**）。
- 一个迁移内：对 `clarification` 做 4 个 `AddField`（容器新字段，全 nullable）+ 1 个 `CreateModel`（`ClarificationQuestion` 子表，FK CASCADE）。
- 优先 `cd server && uv run python manage.py makemigrations delivery` 自动生成，再人工核对编号/字段约束与上方范式一致。

---

### `server/delivery/services/clarification_service.py` (service, CRUD / INV-6)

**Analog:** 自身 `clarification_service.py`（`create_clarification` 53-70 / `answer_clarification` 72-105 / async 桥接范式）。

**INV-6 同步写入块范式** — `clarification_service.py:63-70`:

```63:70:server/delivery/services/clarification_service.py
    @sync_to_async
    def _create_sync(
        self, session: Any, question: str, affected_task_ids: list
    ) -> Clarification:
        clar = Clarification.objects.create(session=session, question=question)
        if affected_task_ids:
            clar.affected_partials.set(affected_task_ids)
        return clar
```

**幂等条件更新（`answered_at IS NULL` 前置）范式 + 按题计算落点** — `clarification_service.py:89-105`:

```89:105:server/delivery/services/clarification_service.py
    @sync_to_async
    def _answer_sync(self, clarification: Clarification, answer: str) -> tuple[bool, list]:
        now = timezone.now()
        updated = Clarification.objects.filter(
            id=clarification.id, answered_at__isnull=True
        ).update(answer=answer, answered_at=now)
        if updated != 1:
            # 幂等 no-op：已答，不二次覆盖首答、不重复 stale/emit
            logger.info(...)
            return False, []
        clarification.answer = answer
        clarification.answered_at = now
        return True, list(clarification.affected_partials.values_list("id", flat=True))
```

**best-effort emit（经 session_id 取 PlanSession，不裸 lazy-FK）** — `clarification_service.py:107-133`（拷给 `clarification.asked`/`answered` 多题摘要 payload）。

**拷贝指引（RESEARCH §Code Examples，行 341-387）:**
- 新增 `create_round(session, questions, *, origin_repo=None, round_no=None, plan_version_id=None)` → 内部 `@sync_to_async _create_round_sync`：`Clarification.objects.create(...)`（`question=""` 占位保旧 NOT NULL 列）+ `ClarificationQuestion.objects.bulk_create([...])`。
- 新增 `answer_round` / `_answer_question_sync`：按题 `filter(id=..., answered_at__isnull=True).update(...)` 幂等，**作答时一次性算 `recommendation_adopted`**（single: `selected==rec[0]`；multi: `set(selected)==set(rec)`；无 rec/纯 freeform→`None`，RESEARCH 行 369-386）。
- 新增统一 pending 谓词 `ahas_pending(session_id)`（收口三处判定，兼容旧单题行：`无子题 且 容器 answered_at IS NULL` 也算 pending，见 Pitfall 2 / RESEARCH 行 272、320）。
- 所有写入须经本 service（INV-6）；async 禁裸 lazy-FK，用 `*_id` 标量 + `sync_to_async`。

---

### `server/services/plan_orchestration/clarify_adapter.py` (adapter, request-response + LLM)

**Analog:** 自身 `clarify_adapter.py`（三段判定 86-118）+ `clarification_questions.py:132-138`（待接线签名）。

**三段判定现状（pending → already-answered 短路 → 首轮 policy）** — `clarify_adapter.py:86-118`:

```86:118:server/services/plan_orchestration/clarify_adapter.py
    async def clarify(self, session: PlanSession) -> dict:
        from delivery.models import Clarification

        # 1. 已有 pending（未答）→ 保持挂起，不重复建（resume 幂等）
        has_pending = await Clarification.objects.filter(
            session_id=session.id, answered_at__isnull=True
        ).aexists()
        if has_pending:
            return {"needs_clarification": True, "pending": True}

        # 2. CR-01 单轮短路：已存在「已答」且无 pending → 放行 researching
        has_answered = await Clarification.objects.filter(
            session_id=session.id, answered_at__isnull=False
        ).aexists()
        if has_answered:
            return {"needs_clarification": False}

        # 3. 首轮 → policy 判定
        needs, question, affected_task_ids = self.policy(session)
        if not needs:
            return {"needs_clarification": False}

        clar = await self.clarification_service.create_clarification(
            session, question, affected_task_ids
        )
        await self._emit_asked(session, clar, question)
        return {"needs_clarification": True, "clarification_id": str(clar.id)}
```

**LLM 生成器签名（待接线，绝不抛）** — `clarification_questions.py:132-138`:

```132:138:server/services/plan_orchestration/clarification_questions.py
async def agenerate_clarification_questions(
    *,
    requirement: str,
    routing: dict[str, Any] | None = None,
    recall_hits: list | None = None,
    max_questions: int = _MAX_QUESTIONS,
) -> list[dict[str, Any]]:
```

**拷贝指引（RESEARCH §Pattern 2 行 215-231 / §Code Examples 行 389-405）:**
- 第 1/2 步 pending/answered 判定改调 service 统一谓词 `ahas_pending`（兼容旧行）；第 3 步 `needs==True` 后接 `agenerate_clarification_questions(requirement=session.decomposition.get("requirement_text"), routing=session.routing, recall_hits=session.recall_context)`。
- `questions` 非空 → `create_round(...)`；空 → **fail-soft** 回退建单题轮（policy 的 `question` 文本，type=single），并记 `clarification_fallback_coarse_question`(category=sampling, component=plan_orchestration)。
- **绝不**在 adapter 让 LLM 异常上抛（`agenerate_...` 已 best-effort 返回 `[]`，只需 `[] → 回退` 一处分支；否则 engine.advance 通用 except 会落 `failed`，见 `engine.py:181-183`）。

---

### `server/services/plan_orchestration/ask_clarification.py` (helper, transform → write) — 新建 CLARIFY-03

**Analog A（薄封装 service 写入）:** `clarify_adapter.py:114-118`（`create_clarification` 调用范式）
**Analog B（入口无关 docstring 精神 + lazy import 规避环）:** `resume.py:1-17` / `resume.py:42-44`

**入口无关 lazy import 范式** — `resume.py:42-44`:

```42:44:server/services/plan_orchestration/resume.py
    # 函数内 lazy import 规避 import 环（resume → models / barrel）
    from delivery.models import Clarification, PlanSession, PlanSessionStatus
    from services.plan_orchestration import aall_research_tasks_terminal
```

**拷贝指引（RESEARCH §Pattern 3 行 233-248 / Pitfall 1 行 311-315）:**
- 签名 `async def ask_clarification(session, questions, *, origin_repo=None, clarification_service=None) -> Clarification`，内部仅 `clarification_service.create_round(session, questions, origin_repo=origin_repo)`（薄封装，**不**驱动 `engine.advance`、**不**挂起 marker —— 驱动是入口私有）。
- **命名撞车守护（Pitfall 1）**：仓内已有 `server/agents/tools/clarification.py` 的 `ask_clarification`（`@tool`，`CLARIFICATION_PENDING_MARKER="ask_clarification"`，写 `chat.ConversationIntentTrace` 不写 delivery，见 `clarification.py:1-36`）。新 helper 放 `services/plan_orchestration/`，靠模块路径区分（`from services.plan_orchestration import ask_clarification`）或显式改名 `ask_plan_clarification`。**绝不**改/复用 chat tool。

---

### `server/services/plan_orchestration/resume.py` (helper, event-driven 续驱)

**Analog:** 自身 `resume.py:63-68`（CLARIFYING pending 短路）。

**现状短路查询（待升级）** — `resume.py:63-68`:

```63:68:server/services/plan_orchestration/resume.py
        if session.status == PlanSessionStatus.CLARIFYING:
            has_pending = await Clarification.objects.filter(
                session_id=session.id, answered_at__isnull=True
            ).aexists()
            if has_pending:
                return session
```

**拷贝指引（RESEARCH §Pattern 5 行 266-272）:** 把 `Clarification.objects.filter(answered_at__isnull=True).aexists()` 替换为调 service 统一谓词 `await clarification_service.ahas_pending(session.id)`（兼容旧单题行 + 新子题）。三处升级点（`clarify_adapter.py:91-94/103-105`、`resume.py:63-68`、e2e `test_plan_research_e2e.py` 驱动 helper）都改调同一谓词，避免判定逻辑漂移。

---

### `server/tests/delivery/test_clarification_service.py` (test, unit)

**Analog:** 自身 `test_inv6_clarification_single_write_entry:146-163`（grep 守护）。

**INV-6 grep 守护现状（须扩展覆盖子模型）** — `test_clarification_service.py:146-163`:

```146:163:server/tests/delivery/test_clarification_service.py
def test_inv6_clarification_single_write_entry() -> None:
    """INV-6 grep 守护：Clarification.objects.create 仅出现在 clarification_service.py。"""
    _SKIP_DIRS = (".venv", "node_modules", ".git", "__pycache__", "site-packages")
    offenders: list[str] = []
    for path in _SERVER_ROOT.rglob("*.py"):
        rel = path.relative_to(_SERVER_ROOT).as_posix()
        ...
        if "Clarification.objects.create" in line:
            offenders.append(f"{rel}: {line.strip()}")
    assert not offenders, f"Clarification 旁路写入（应只经 ClarificationService）：{offenders}"
```

**拷贝指引（RESEARCH Pitfall 3 行 323-327 / §Validation 行 461-465）:** 扩展守护断言覆盖 `ClarificationQuestion.objects.create`/`.save`（正则覆盖两模型）；docstring 内若出现字面 `ClarificationQuestion(...)` 用全角括号避 grep 误判（STATE.md:275 先例）。新增用例：`recommendation_adopted`（single/multi/无推荐→None）、采纳率聚合（adopted/total）、向后兼容旧行读映射 + 仍判 pending、按题幂等作答。

---

### `server/tests/services/test_ask_clarification_helper.py` (test, unit) — 新建

**Analog:** `test_engine_clarify.py`（adapter 行为 mock）/ `test_clarification_service.py`（INV-6 + 落库断言）。

**拷贝指引（RESEARCH §Validation 行 469、480）:** 新文件名/导入须与既有 `tests/test_ask_clarification_tool.py`（chat tool）**显式区分**，避免拿错 `ask_clarification`。断言：helper 写 `delivery.Clarification` 轮 + 多问题、携带 `origin_repo`、守 INV-6（只经 service）、不驱动 advance / 不挂起。

## Shared Patterns

### INV-6 单一写入收口
**Source:** `server/delivery/services/clarification_service.py:63-70`（`@sync_to_async` + `Clarification.objects.create`）
**Apply to:** 所有澄清/问题/答案写入（`create_round`/`answer_round`/`ask_clarification` helper）。`ClarificationQuestion` 子表写入同样只经 service；grep 守护测试扩展覆盖子模型。

### async ORM 防裸 lazy-FK（Phase 38 CR-01 类）
**Source:** `clarification_service.py:104-117`（`.values_list(..., flat=True)` + `PlanSession.objects.filter(id=clarification.session_id).afirst()`）、`resume.py:42-44`（函数内 lazy import）
**Apply to:** 所有新增 service 方法与 plan_orchestration helper。用 `*_id` 标量 / `.values_list` / `.aexists` / `.afirst`，写入包 `sync_to_async` 同步块；绝不裸访问 `clarification.session` / `question.clarification`。

### best-effort 观测埋点（绝不反噬业务）
**Source:** `clarification_service.py:125-133`（emit `try/except` + `logger.warning`）、`clarification_questions.py:163-177`（`clarification_questions_generated` category=sampling/component=plan_orchestration + 失败只记 `str(exc)`）
**Apply to:** 澄清生成/作答生命周期事件（started/completed/failed + `duration_ms`）、`clarification_fallback_coarse_question`、`clarification.asked`/`.answered`。事件 emit 失败只 warning，绝不阻断主流程。LLM 调用赋 `call_source=plan_clarification`（已在生成器内）。

### status 只经 transition（engine 纯度）
**Source:** `engine.py:185-195`（`_clarify` 经 `session_service.transition` + `ConcurrentTransitionError` 良性 no-op）
**Apply to:** adapter/helper 绝不直接写 `session.status`；状态流转只经 `PlanSessionService.transition`（白名单 + 并发守卫）。

### 父子模型 + 最小迁移
**Source:** `technical_plan.py:96-128`（子表 FK CASCADE + JSONField + Meta indexes）、`0016_clarification.py:15-34`（CreateModel + options）、`0024_*.py:13-22`（nullable AddField）
**Apply to:** `ClarificationQuestion` 子表建模 + `0026_*` 迁移。新增容器字段全 nullable（旧行不破坏），子表用 `makemigrations` 自动生成后人工核对。

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| —（无） | — | — | 本 phase 全部落点都有仓内强 analog（自身既有版本 / 同 app 邻近模型 / 既有迁移）。`agenerate_clarification_questions` 已就绪，无需新建 LLM 解析逻辑。 |

## Metadata

**Analog search scope:** `server/delivery/models/`、`server/delivery/migrations/`、`server/delivery/services/`、`server/services/plan_orchestration/`、`server/agents/tools/`、`server/tests/delivery/`
**Files scanned:** clarification.py（model + service）、technical_plan.py、models/__init__.py、0016/0024 migrations、clarify_adapter.py、clarification_questions.py、resume.py、engine.py、agents/tools/clarification.py、test_clarification_service.py
**Pattern extraction date:** 2026-06-27
**关键执行前复核:** delivery migration head 仍须确认为 `0025_rename_project_to_space`（RESEARCH 行 555）。
