# Phase 141: Capture 账本与仓库挂钩 - Pattern Map

**Mapped:** 2026-08-28
**Files analyzed:** 12
**Analogs found:** 12 / 12

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/initiatives/models/session_capture.py` | model | CRUD | `server/initiatives/models/merge_request.py` + `memory.py` | exact (nullable SET_NULL FKs + INV-6 TextChoices) |
| `server/initiatives/models/__init__.py` | config | — | 同文件现有 `ProjectMemory` / `RepoAssociation` 导出块 | exact |
| `server/initiatives/services/capture_service.py` | service | request-response | `server/initiatives/services/memory_service.py` | role-match（INV-6 writer；**勿复制**拒写/入图） |
| `server/initiatives/services/__init__.py` | config | — | 同文件 `MemoryService` barrel | exact |
| `server/initiatives/migrations/0015_session_capture.py` | migration | CRUD | `server/initiatives/migrations/0014_project_context_link.py` | role-match |
| `server/services/git_url.py` | utility | transform | `repositories/serializers.ssh_git_url_to_https` + `mr_service._normalize_repo_url` | role-match（抽取，非第三份 regex） |
| `server/tests/initiatives/test_capture_inv6_guard.py` | test | — | `test_repo_association_inv6_guard.py`（含 `.update`） | exact |
| `server/tests/initiatives/test_capture_service.py` | test | request-response | `test_memory_service.py` | exact |
| `server/tests/initiatives/test_capture_observability.py` | test | request-response | `server/tests/services/code_graph/test_query_observability.py` | exact |
| `server/tests/initiatives/conftest.py` | test | CRUD | 同文件 `project_memory_factory`（经 service 落库） | exact |
| `.planning/observability/LOGGING-SPEC.md` | config | — | 同文件 §5 `knowledge` component + §10 事件目录 | role-match |
| `server/initiatives/services/mr_service.py` / `server/services/sensitive_purge.py` | utility | transform | 仅在抽取 `normalize_git_url` 时改为调用共享函数 | partial |

**Out of scope（本阶段不建文件）：** MCP views/serializers、durable worker、knowledge sources、CallSource 枚举、admin（initiatives 现无 admin 注册）。

---

## Pattern Assignments

### `server/initiatives/models/session_capture.py` (model, CRUD)

**Analog A (FK 可空 + SET_NULL):** `server/initiatives/models/merge_request.py`

Capture 的 `project` / `repository` 必须复制 **MergeRequest** 的删除语义，**不要**复制 `RepoAssociation` 对 `project`/`repository` 的 `CASCADE`（删仓会物理丢掉账本，违反 STORE-02 / Pitfall 8）。

**Nullable SET_NULL FK pattern** (lines 41–56):
```python
project = models.ForeignKey(
    "initiatives.Project",
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="merge_requests",
    verbose_name="项目",
)
repository = models.ForeignKey(
    "repositories.Repository",
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="merge_requests",
    verbose_name="仓库",
)
```
Capture 改 `related_name="session_captures"`（或 `"+"` 若不需要反查）。跨 app 仓用字符串 `"repositories.Repository"`，对齐 `repo_association.py` 前向引用。

**UniqueConstraint 幂等** (lines 100–107) — 形状照抄，字段换成 CONTEXT 锁定三元组；**不要**加 `condition=~Q(session_id="")`，因缺 session 存字面 `"unspecified"` 且必须参与唯一约束：
```python
constraints = [
    models.UniqueConstraint(
        fields=["platform", "repository", "external_id"],
        condition=~models.Q(external_id=""),
        name="uniq_mr_platform_repo_external",
    ),
]
```
Capture:
```python
models.UniqueConstraint(
    fields=["initiated_by_user_id", "session_id", "question_hash"],
    name="uniq_session_capture_user_session_question",
)
```

**Analog B (INV-6 模型契约 + TextChoices):** `server/initiatives/models/memory.py`

**Docstring / 无业务写方法** (lines 10–11, 22–26):
```python
# 模型层**不提供业务 create/save 方法**——所有写入收口于 ``initiatives.services.MemoryService``
# （INV-6，由 ``test_memory_inv6_guard`` grep 守护）。

class ProjectMemoryStatus(models.TextChoices):
    ACTIVE = "active", "生效"
    SUPERSEDED = "superseded", "已废弃"
```
Capture 枚举预留后续相位（141 **只写入** `pending_eval`）：
`pending_eval` / `eval_failed` / `ingest_pending` / `evaluated`。

**UUID PK + `db_table` + `initiated_by_user_id` CharField:** 抄 `repo_association.py` 76–79 / `merge_request.py` 134–136：
```python
id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
initiated_by_user_id = models.CharField(max_length=64, blank=True, default="system")
```
`db_table = "initiative_session_captures"`（CONTEXT 锁定）。

**标量 `unknown`：** 勿用 IntegerField 存 token。`response_model` / `provider` / `input_tokens` / `output_tokens` 均为 `CharField(max_length=64, default="unknown")`。`session_id` 用非空 CharField，缺省字面 `"unspecified"`（不要用 `unknown`）。`question_hash` `CharField(max_length=64)`。`link_reason` `CharField`。`question`/`answer` `TextField`。`branch_name` 只存元数据。

**索引建议：** `(initiated_by_user_id, session_id)`、`(repository, status)`、`(status, created_at)` — 形状照 `RepoAssociation.Meta.indexes`。

---

### `server/initiatives/models/__init__.py` (config)

**Analog:** 同文件 `ProjectMemory` 导出块 (lines 22–28, 91–95)

```python
from initiatives.models.memory import (
    DraftStatus,
    ProjectMemory,
    ...
)
# __all__ 同步追加符号
```
新增 `from initiatives.models.session_capture import SessionCapture, SessionCaptureStatus` 并列入 `__all__`。

---

### `server/initiatives/services/capture_service.py` (service, request-response)

**Analog:** `server/initiatives/services/memory_service.py`（唯一 writer 骨架）+ `server/services/code_graph/query_service.py`（caller 日志）+ `server/initiatives/services/mr_service.py`（IntegrityError 幂等）+ `server/knowledge/access_scope.py`（挂钩授权）

**Imports / logger / INV-6 模块 docstring** (`memory_service.py` 1–41):
```python
from asgiref.sync import sync_to_async
from django.db import transaction
from common.logging import redact_secrets_in_text
from initiatives.models import ProjectMember, ...

logger = structlog.get_logger(__name__)
```
Capture **额外**需要：
- `from django.db import IntegrityError, transaction`
- `from knowledge.access_scope import resolve_allowed_project_ids, resolve_allowed_repository_ids`
- `from repositories.serializers import ssh_git_url_to_https` 或共享 `normalize_git_url`
- `from repositories.models import Repository`
- `import hashlib, unicodedata, time, uuid`
- `_COMPONENT = "knowledge"`（CONTEXT 锁定；**不要**抄 Memory 的 `_COMPONENT = "initiatives"`）

**禁止从 MemoryService 复制：**
- `_assert_member` 导致整次 `append` 抛 `MemoryPermissionError`（Capture 未授权只空 FK，仍落行）
- `_skip_member_check` 后门
- `_schedule_materialization` / `_schedule_doc_push` / `aschedule_ingestion` / `MemoryService.append` / `record_hook_writeback`
- `AuditService.aemit` 把问答放进 `before`/`after`（OBS-02；141 不写 Ledger）
- `arecord_tool_call` / `arecord_retrieval_trace`

**脱敏后 create** (`memory_service.py` 108–137) — 复制顺序「先 redact 再 objects.create」，不要复制成员拒绝：
```python
redacted = redact_secrets_in_text(content or "")
memory = await self._append_locked(...)
# _append_locked:
with transaction.atomic():
    memory = ProjectMemory.objects.create(...)
```
Capture：对 `question` 与 `answer` **分别** `redact_secrets_in_text`；哈希用脱敏后正文（或约定 NFKC(strip(redacted_question))，测试钉死一种）。

**sync_to_async + transaction.atomic** 同 `_append_locked`。`persist` 对外 `async`。

**幂等 IntegrityError** — 抄 `mr_service.py` 387–389（撞唯一键视为已存在），然后 **get 原行原样返回，不 update answer**：
```python
except IntegrityError:
    return {"deduped": True, "created": False, "mr_id": str(mr.id)}
```
Capture 在 `atomic` 内 `create`，`IntegrityError` 后 `get(initiated_by_user_id=..., session_id=..., question_hash=...)`。禁止 `update_or_create`。

**Caller 生命周期日志** — 抄 `query_service.py` 145–157 / 512–542，事件名换成 `session_capture_persist_*`，`component="knowledge"`：
```python
started = time.monotonic()
try:
    logger.info(
        "code_graph_query_started",
        initiated_by_user_id=initiated_by_user_id,
        category="caller",
        component="code_graph",
    )
except Exception:  # noqa: BLE001
    pass
try:
    ...
    try:
        logger.info("code_graph_query_completed", duration_ms=..., category="caller", ...)
    except Exception:
        pass
    return response
except Exception as exc:
    try:
        logger.warning(
            "code_graph_query_failed",
            error=redact_secrets_in_text(str(exc)),
            duration_ms=int((time.monotonic() - started) * 1000),
            category="caller",
            ...
        )
    except Exception:
        pass
    raise
```
completed kv 白名单（RESEARCH）：`capture_id`、`link_reason`、`repository_bound`、`project_bound`、`session_present`（bool）、`idempotent_hit`、`initiated_by_user_id`、`duration_ms`。禁止 `question`/`answer`/`git_url`/`token`/`question[:n]`。

**挂钩授权** — 用 `knowledge/access_scope.py` 97–139，**不用** `RepositoryPermission`（任意登录可读仓，lines 12–16 of `permissions.py`）。

`resolve_allowed_repository_ids(user, repository_ids=[str(id)])`：caller 含不可见 id 时返回 `[]`（intersect fail-closed，lines 136–138）。挂钩：仓不在 allowed → FK null + `repo_unauthorized`（对外可折叠为 `repo_unresolved` 防枚举，RESEARCH 推荐）。

项目：`resolve_allowed_project_ids` 和/或 `ProjectMember.objects.filter`（`memory_service.py` 76–80），未授权 → 不绑 project FK。

软删仓：`Repository.objects.filter(id=..., is_deleted=False)`（全仓 REST 先例）。非法 UUID：`uuid.UUID(str)` 失败 → `repo_unresolved`。

**git 匹配：** 先 `ssh_git_url_to_https` 再 strip/lower/去 `/`/去 `.git`。**不要**复制 `mr_service._match_repository` 全表扫描（lines 312–315）；先对候选变体 `filter(git_url__in=variants, is_deleted=False)`，多命中 → `repo_ambiguous` 不绑 FK。

**成员校验语义翻转：** Memory 非成员 = 拒绝写入。Capture 非成员/无权仓 = 仍 `objects.create`，`initiated_by_user_id` 归提交者。

**unknown 归一：** 空 / None / 空白 → 字面 `"unknown"`；禁止按问答推断模型名。

**返回类型：** dataclass `CapturePersistResult(capture, link_reason, idempotent_hit, created)` — 形状可对照 `BoardSyncResult` barrel，不必新建异常类型（挂钩失败不是异常）。

---

### `server/initiatives/services/__init__.py` (config)

**Analog:** 同文件 `MemoryService` 块 (lines 29–34, 83–86)

```python
from initiatives.services.memory_service import (
    MemoryError,
    MemoryPermissionError,
    MemoryService,
    MemoryStateError,
)
```
导出 `CaptureService`、`CapturePersistResult`（及若有的错误类）。注意：`RepoAssociationService` **尚未**进 barrel；Capture **应**导出，因 142 MCP 会 `from initiatives.services import CaptureService`。

---

### `server/initiatives/migrations/0015_session_capture.py` (migration, CRUD)

**Analog:** `server/initiatives/migrations/0014_project_context_link.py`

**Dependencies** (lines 12–15)：`('initiatives', '0014_project_context_link')` + `repositories` + swappable `AUTH_USER_MODEL`（若有 User FK；本阶段推荐无 User FK，仅 `initiated_by_user_id` 字符串，则可不依赖 AUTH）。

**CreateModel 形状** (lines 18–43)：UUID PK、`initiated_by_user_id`、`db_table`、`indexes`、`UniqueConstraint`。

**FK on_delete：** 用 `django.db.models.deletion.SET_NULL` 指向 `initiatives.project` 与 `repositories.repository`。评审 migration 文本时 grep `CASCADE` 到这两张表必须为 0。

---

### `server/services/git_url.py` (utility, transform) — 推荐抽取

**Analog 1:** `server/repositories/serializers.py` 21–38（SSH→HTTPS，**唯一**保留 regex 处）

```python
def ssh_git_url_to_https(git_url: str) -> str:
    url = git_url.strip()
    match = _SSH_SCP_RE.match(url) or _SSH_URL_RE.match(url)
    if match:
        return f"https://{match.group(1)}/{match.group(2)}"
    return url
```

**Analog 2:** `server/initiatives/services/mr_service.py` 54–59（HTTPS 等价归一）

```python
def _normalize_repo_url(url: str) -> str:
    u = (url or "").strip().lower().rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    return u
```
`sensitive_purge.py` 58–70 几乎同文。共享入口应为：
`normalize_git_url(url) -> str` = `ssh_git_url_to_https` 后再做 strip/lower/rstrip `/` / 去 `.git`。Capture 与（可选）MR/purge 调用它。**禁止**在 `capture_service.py` 再写一份 `_SSH_SCP_RE`。

`validate_https_git_url` 会 `ValidationError` 拒绝非 http(s) — Capture **不要**调用它（挂钩失败仍落库）。

---

### `server/tests/initiatives/test_capture_inv6_guard.py` (test)

**Primary analog:** `server/tests/initiatives/test_repo_association_inv6_guard.py`（比 memory 守卫多扫 `.update`）

复制：`SERVER_DIR`、`_PRUNE_DIRS`、`_iter_py_files`、`_is_scanned`（排除 writer / `tests/` / `migrations/` / `initiatives/models/`）。

`_ALLOWED_WRITER = "initiatives/services/capture_service.py"`
`_MODELS = ("SessionCapture",)`

**ORM write regex** 必须含 `update`（CONTEXT 禁止旁路改状态），抄 association 守卫 34–37：
```python
_RE_ORM_WRITE = re.compile(
    r"\b(?:RepoAssociation|RepoVerifyTask)\.objects\."
    r"(?:create|bulk_create|get_or_create|update_or_create|update)\b"
)
```
另加 RESEARCH 建议：`SessionCapture.objects.filter(...).update`、实例化 `SessionCapture(`、`.save(`。跳过 `class SessionCapture` / `SessionCaptureStatus(`。

**Writer 自检** 抄 `test_memory_inv6_guard.py` 80–87：`assert "SessionCapture.objects.create" in text`。再断言 writer **不含** `aschedule_ingestion`、`MemoryService`、`record_hook_writeback`、`background_runner`、`_resolve_report_project_id`、`lookup_project_by_branch`。

---

### `server/tests/initiatives/test_capture_service.py` (test)

**Analog:** `server/tests/initiatives/test_memory_service.py`

**模块级 DB 标记** (lines 28–45):
```python
pytestmark = pytest.mark.django_db(transaction=True)
User = get_user_model()

@sync_to_async
def _make_user(username):
    return User.objects.create_user(username=username, password="x")

async def _make_project_with_member():
    space = await sync_to_async(Space.objects.create)(name="S")
    owner = await _make_user("owner")
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key="mem-k", created_by=owner
    )
    return project, owner
```
仓工厂：`Repository.objects.create(..., git_url=..., is_deleted=False)` + `space.repositories.add(repo)`（挂钩授权依赖 Space M2M，见 `access_scope._repos_for_projects`）。

**脱敏断言** (lines 108–117) 复制到 question **和** answer：
```python
assert "sk-ant-abc123secretvalue1234567890" not in refreshed.content
assert "REDACTED" in refreshed.content
```

**语义对照（必须反转的测试）：**
| Memory 测试 | Capture 测试 |
|-------------|--------------|
| 非成员 `raises MemoryPermissionError` | 非成员仍 `acount()==1`，`project_id is None`，`link_reason` 含 unauthorized |
| 必须有 `project_id` | 无 project、无 repo 仍 `status=pending_eval` |
| 写 `ProjectMemory` | `ProjectMemory.objects.acount()` 不变；未 mock 到 `arecord_tool_call` |

幂等：同 user+session+question 两次，同 `id`，answer 仍为第一次。`unknown` 标量。SSH `git@host:group/repo.git` 挂钩到已存 HTTPS 仓。未知 URL → 有行 + `repo_unresolved`。显式 `repository_id` 优先于 `git_url`。

工厂经 `CaptureService.persist`，不要在生产路径测试里直接 `SessionCapture.objects.create`（守卫虽排除 tests/）。

---

### `server/tests/initiatives/test_capture_observability.py` (test)

**Analog:** `server/tests/services/code_graph/test_query_observability.py`

**capture_logs + 事件过滤** (lines 66–68, 71+):
```python
def _events(captured: list[dict], *names: str) -> list[dict]:
    allowed = set(names)
    return [event for event in captured if event.get("event") in allowed]
```
`structlog.testing.capture_logs()`；成功路径 `started` 然后 `completed`；`completed` 有 `duration_ms`、`category=="caller"`、`component=="knowledge"`；无 `failed`。

**正文/密钥不进 JSON** (lines 178–181):
```python
serialized = json.dumps(captured, ensure_ascii=False)
assert "failure-query-sentinel" not in serialized
assert token not in serialized
```
Capture 用独特 sentinel 问答 + `sk-ant-...`。

**logger 失败不丢业务** (lines 199–229)：`monkeypatch.setattr` writer 模块的 `logger.info`/`warning` 抛错；persist 仍返回 Capture；业务异常 `is` 原异常。

本阶段断言 **没有** `session_capture_eval_*` / ingest sampling 事件名。

---

### `server/tests/initiatives/conftest.py` (test, optional factory)

**Analog:** 同文件 docstring 5–6 行：`project_memory_factory` 经 `MemoryService.append` 落库。Capture fixture 必须走 `CaptureService.persist`，参数含 actor user。

---

### `.planning/observability/LOGGING-SPEC.md` (config)

**Analog:** §5 component 清单已含 `knowledge`（约 line 150）。§10 事件目录追加三事件，形状对齐 `code_graph_query_started/completed/failed`（query_service 即运行时实现）。

**不要**在 §4.1 `CallSource` 增加 `session_capture_eval`（Phase 143）。

---

## Shared Patterns

### INV-6 唯一 writer
**Source:** `memory.py` docstring + `memory_service.py` + `test_memory_inv6_guard.py` / `test_repo_association_inv6_guard.py`  
**Apply to:** `SessionCapture` 模型、`CaptureService`、INV-6 测试  
业务代码禁止 `SessionCapture.objects.create|bulk_create|get_or_create|update_or_create|update` 与 `SessionCapture(...).save()`。

### 脱敏
**Source:** `common.logging.redact_secrets_in_text` (lines 391–399)；Memory 入库前调用 (memory_service 110)  
**Apply to:** persist 的 question/answer；failed 日志的 `error=`  
141 不写 Ledger，不必 `redact_for_ledger`。勿手写新正则。

### 触发用户
**Source:** `RepoAssociation.initiated_by_user_id` default `"system"`；query_service kv `initiated_by_user_id`  
**Apply to:** 模型字段 + 三条 persist 日志。缺 actor → `"system"`。

### Caller 观测 best-effort
**Source:** `query_service.py` 每处 `logger.*` 包 `except Exception: pass`（`# noqa: BLE001`）  
**Apply to:** persist 三事件。顺序：started（吞）→ create（不吞）→ completed（吞）；create 失败 → failed（吞）→ re-raise。

### 挂钩授权 = 知识召回 scope
**Source:** `knowledge.access_scope.resolve_allowed_*`  
**Apply to:** 是否赋值 FK。不决定是否插入行。

### 项目成员存在性
**Source:** `MemoryService._is_member_sync` (`ProjectMember.objects.filter(project_id=, user_id=).exists()`)  
**Apply to:** 可选项目 FK。False → 不绑项目，仍 persist。

### 幂等
**Source:** `MergeRequest` UniqueConstraint + `mr_service` IntegrityError  
**Apply to:** user + session_id + question_hash。First write wins。

### 软删仓
**Source:** 全仓 `is_deleted=False` 过滤  
**Apply to:** id/url 解析。软删 = 不存在 → `repo_unresolved`。

### async ORM
**Source:** MemoryService `@sync_to_async` + `pytest.mark.django_db(transaction=True)`  
**Apply to:** persist 写路径与行为测试。

---

## Anti-Patterns to Copy Never

| Anti-pattern | Source | Why |
|--------------|--------|-----|
| `_resolve_report_project_id` 返回 `branch_unresolved` 且调用方不写库 | `mcp_tools/views.py` 3719–3738, 4045 | Capture 无项目也必须有行 |
| `lookup_project_by_branch` / 默认分支第三源 | MCP lookup | Phase 144；141 `branch_name` 只存字段 |
| `RepositoryPermission`（任意登录可读未删仓） | `repositories/permissions.py` 12–16 | 会绑上 144 召回不到的仓 |
| `RepoAssociation` `on_delete=CASCADE` 到 Project/Repository | `repo_association.py` 46–64 | 删仓丢账本 |
| Memory `_assert_member` 整笔拒绝 | `memory_service.py` 82–88 | 未授权仍要落 Capture |
| Memory `_skip_member_check` | `append(..., _skip_member_check=)` | 禁止未授权 FK 后门 |
| `component="initiatives"` | Memory `_COMPONENT` | CONTEXT 锁定 `knowledge` |
| `mr_service._match_repository` 全表 `for repo in Repository.objects.filter` | lines 312–315 | 用 URL 变体 filter；多命中 `repo_ambiguous` |
| `validate_https_git_url` 抛 ValidationError | `serializers.py` 41–47 | 非法 URL 仍落库 |
| `update_or_create` | — | 会覆盖 answer |
| token `IntegerField` | — | 无法存 `"unknown"` |
| 日志 `question[:80]` | Phase 140 已判泄漏 | 只记 bound flags |
| persist 内 durable/eval/ingest | Memory `_schedule_materialization` | Phase 143 |
| 测试正向断言 `report_project_knowledge` skip | `test_report_project_knowledge.py` | 141 回归保持旧工具不变，新路径相反 |

---

## Reusable Symbols (copy these names)

| Symbol | Module | Use |
|--------|--------|-----|
| `redact_secrets_in_text` | `common.logging` | 问答入库 + error 日志 |
| `resolve_allowed_repository_ids` | `knowledge.access_scope` | 仓 FK |
| `resolve_allowed_project_ids` | `knowledge.access_scope` | 项目 FK |
| `ProjectMember` | `initiatives.models` | 成员存在性 |
| `RepoAssociation` | `initiatives.models` | 仓↔项目关系校验（mismatch） |
| `ssh_git_url_to_https` | `repositories.serializers` | SSH 第一步 |
| `Repository` + `is_deleted` | `repositories.models` | 解析 |
| `ProjectService().create` | `initiatives.services` | 测试夹具 |
| `structlog.get_logger(__name__)` | structlog | persist 日志 |
| `structlog.testing.capture_logs` | 观测测试 | |
| `hashlib.sha256` | stdlib | `question_hash` |
| `unicodedata.normalize("NFKC", ...)` | stdlib | RESEARCH A4，测试钉死 |

**Do not import:** `_resolve_report_project_id`, `MemoryService`, `aschedule_ingestion`, `background_runner`, `record_hook_writeback`, `CallSource`（无 LLM）, `arecord_tool_call`.

---

## No Analog Found

无完全空白项。以下为「有近邻但语义必须改写」：

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `capture_service.py` persist 挂钩 | service | request-response | 无「失败仍 insert」的现成 writer；最近是 Memory（失败则拒绝）与 report_*（失败则跳过）。必须新写挂钩状态机，只复用授权/脱敏/日志骨架。 |
| `server/services/git_url.py` | utility | transform | 无共享模块，只有两份私有 `_normalize_repo_url` + serializers SSH。 |

---

## Metadata

**Analog search scope:** `server/initiatives/models/`, `server/initiatives/services/`, `server/initiatives/migrations/`, `server/tests/initiatives/`, `server/knowledge/access_scope.py`, `server/repositories/{serializers,permissions}.py`, `server/services/code_graph/query_service.py`, `server/common/logging.py`, `server/mcp_tools/views.py`（反模式）, `.planning/observability/LOGGING-SPEC.md`, `.planning/REQUIREMENTS.md` STORE/OBS, `.planning/ROADMAP.md` Phase 141  
**Files scanned:** ~25 primary analogs  
**Pattern extraction date:** 2026-08-28
