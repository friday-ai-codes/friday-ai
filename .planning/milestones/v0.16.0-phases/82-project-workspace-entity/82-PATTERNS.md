# Phase 82: 项目工作区实体 + 权限翻转 + 飞书文件夹 + 五份文件落地 - Pattern Map

**Mapped:** 2026-06-26
**Files analyzed:** 16 (新增/修改)
**Analogs found:** 16 / 16（全部命中真实同构实现，置信 HIGH；仅 `create_folder` 端点形态 MEDIUM 待 live 验证）

所有分析基于已读真实源码。新建文件逐字镜像 `server/initiatives/` 这套成熟范式：模型零业务方法 + 单一 service 写入收口（INV-6）+ grep 守护 + async ORM(`sync_to_async`) + `AuditService.aemit` 归因 + best-effort WS 推送。

## File Classification

| 新增/修改文件 | Role | Data Flow | 最近分析 Analog | Match |
|---------------|------|-----------|-----------------|-------|
| `server/initiatives/models/project.py` (MODIFY +visibility +feishu_folder_token) | model | CRUD | 同文件既有字段 + `member.py` 约束 | exact |
| `server/initiatives/models/project_doc.py` (NEW ProjectDoc/ProjectDocBlockMap) | model | CRUD | `models/memory.py` | exact |
| `server/initiatives/models/project_state_api.py` (NEW ProjectStateApi) | model | CRUD | `models/memory.py` | exact |
| `server/initiatives/models/__init__.py` (导出) | config | — | 同文件既有导出块 | exact |
| `server/initiatives/migrations/0006_*.py` | migration | batch | `migrations/0005_*.py` | exact |
| `server/initiatives/services/project_doc_service.py` (NEW INV-6) | service | CRUD + event-driven | `services/memory_service.py` + `project_service.py` | exact |
| `server/initiatives/services/project_service.py` (MODIFY update 白名单) | service | CRUD | 同文件 `update()` | exact |
| `server/initiatives/services/__init__.py` (导出) | config | — | 同文件既有导出块 | exact |
| `server/tests/initiatives/test_project_doc_inv6_guard.py` (NEW) | test | static-scan | `test_artifact_inv6_guard.py` | exact |
| `server/services/feishu_doc.py` (MODIFY +create_folder) | service | request-response | 同文件 `create_document` | role+flow |
| `server/services/project_context_packer.py` (MODIFY visibility 感知) | service | CRUD-read | 同文件 `pack_project_context` | exact |
| `server/knowledge/access_scope.py` (MODIFY public_org 并入) | service | CRUD-read | 同文件 `resolve_allowed_project_ids` | exact |
| `server/initiatives/{views,serializers,urls}.py` (MODIFY ProjectDoc/StateApi 入口) | controller/serializer/route | request-response | 同文件既有 APIView/Serializer/path | exact |
| `web/src/components/layout/AppSidebar.vue` (MODIFY 插「项目」tab) | component | event-driven | 同文件 `mainNavItems` | exact |
| `web/src/api/projects.ts` (MODIFY +visibility +ProjectDoc 端点) | api-client | request-response | 同文件 `projectsApi` | exact |
| `web/src/pages/projects/index.vue` (MODIFY 默认 space + localStorage) | component | request-response | `AppSidebar.vue` `useLocalStorage` 范式 | role-match |

---

## Pattern Assignments

### `server/initiatives/models/project.py` (MODIFY — model, CRUD)

**Analog:** 同文件既有字段块 + `models/member.py` partial constraint。

字段紧跟 `feishu_board_id` (line 66-68) 之后新增。可见性枚举镜像既有 `ProjectStatus` (line 25-30) 写法：

```python
class ProjectVisibility(models.TextChoices):
    PUBLIC_ORG = "public_org", "全员可读"
    MEMBERS_ONLY = "members_only", "仅成员"

# Project 内新增字段（紧跟 feishu_board_id）：
visibility = models.CharField(
    max_length=20, choices=ProjectVisibility.choices,
    default=ProjectVisibility.PUBLIC_ORG, verbose_name="可见性",
)
feishu_folder_token = models.CharField(
    max_length=200, blank=True, default="", verbose_name="飞书工作区文件夹 token",
)
```

**关键约束：** 模型层零业务方法（line 120-121 仅 `__str__`）；新字段不写任何 save/create 逻辑——写入收口 `ProjectService`。

---

### `server/initiatives/models/project_doc.py` (NEW — model, CRUD)

**Analog:** `server/initiatives/models/memory.py`（多模型同文件 + 枚举 + FK + Meta）。

**模块 docstring + import 头**（镜像 `memory.py:1-19`）：

```python
"""项目工作区文档容器模型（DOC-01~06）。

模型层**不提供业务 create/save 方法**——所有写入收口于
``initiatives.services.ProjectDocService``（INV-6，由 ``test_project_doc_inv6_guard`` grep 守护）。
"""
from __future__ import annotations
import uuid
from django.db import models
```

**枚举**（镜像 `memory.py` `ProjectMemoryStatus`/`DraftStatus` 写法 line 22-27, 108-113）：

```python
class DocType(models.TextChoices):
    MEMORY = "memory", "记忆"
    STATE = "state", "状态"
    MILESTONES = "milestones", "里程碑"
    RESEARCH = "research", "调研"
    PREFLIGHT = "preflight", "前置检查"

class DocSyncStatus(models.TextChoices):
    PENDING = "pending", "待创建"
    READY = "ready", "已就绪"
    BROKEN = "broken", "失效待重建"

class DocSection(models.TextChoices):
    SYSTEM = "system", "系统区"
    HUMAN = "human", "人工区"
```

**UUID PK + FK + Meta 幂等键**（镜像 `memory.py:29-67` 字段块 + `member.py:51-66` partial/复合 UniqueConstraint）：

```python
class ProjectDoc(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "initiatives.Project", on_delete=models.CASCADE,
        related_name="docs", verbose_name="项目",
    )
    doc_type = models.CharField(max_length=20, choices=DocType.choices, verbose_name="文档类型")
    feishu_document_id = models.CharField(max_length=200, blank=True, default="")
    feishu_doc_token = models.CharField(max_length=200, blank=True, default="")
    sync_status = models.CharField(
        max_length=20, choices=DocSyncStatus.choices,
        default=DocSyncStatus.PENDING, verbose_name="同步状态",
    )
    last_synced_revision = models.CharField(max_length=200, blank=True, default="")
    last_synced_snapshot = models.TextField(blank=True, default="")  # Claude's Discretion: 内联非另起表
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "initiative_project_docs"
        verbose_name = "项目文档"; verbose_name_plural = "项目文档"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["project", "doc_type"], name="uniq_project_doc_type"),
        ]
        indexes = [models.Index(fields=["project", "doc_type"])]
```

`ProjectDocBlockMap`：FK `doc`(→ProjectDoc CASCADE related_name="block_maps") + `feishu_block_id` + `db_ref` + `section`(DocSection) + `content_hash`，`db_table="initiative_project_doc_block_maps"`，index on `[doc, feishu_block_id]`。

**注意（Pitfall 4）：** `last_synced_snapshot` 入库前必须经 `redact_secrets_in_text`（service 侧，不在模型层）。

---

### `server/initiatives/models/project_state_api.py` (NEW — model, CRUD)

**Analog:** `memory.py` 同范式。`ProjectStateApi`：`project` FK(CASCADE related_name="state_apis") + `method`(TextChoices GET/POST/PUT/DELETE/PATCH) + `path`(CharField) + `params`(JSONField default=dict) + `status`(ApiStatus 枚举 done/planned) + `source`(ApiSource 枚举 manual/cursor_hook)。`db_table="initiative_project_state_apis"`，复合 UniqueConstraint `[project, method, path]`。`params` JSONField 镜像 migration 0005 `MergeRequestEvent.raw_payload`（`models.JSONField(blank=True, default=dict)`）。

---

### `server/initiatives/models/__init__.py` (MODIFY — config)

**Analog:** 同文件 line 10-16（memory 导入块）+ line 39-43（`__all__`）。新增：

```python
from initiatives.models.project_doc import (
    DocSection, DocSyncStatus, DocType, ProjectDoc, ProjectDocBlockMap,
)
from initiatives.models.project_state_api import (
    ApiSource, ApiStatus, ProjectStateApi,
)
from initiatives.models.project import Project, ProjectStatus, ProjectVisibility  # +ProjectVisibility
# __all__ 追加上述符号
```

---

### `server/initiatives/migrations/0006_*.py` (NEW — migration, batch)

**Analog:** `migrations/0005_mergerequest_..._and_more.py`。

**dependency**（关键数字，RESEARCH 已定）：

```python
dependencies = [
    ('initiatives', '0005_mergerequest_mergerequestevent_projectmemory_and_more'),
    migrations.swappable_dependency(settings.AUTH_USER_MODEL),
]
```

**operations:** `migrations.AddField`(Project.visibility, Project.feishu_folder_token，**纯 AddField + default，无回填** — 无历史项目) + `migrations.CreateModel`(ProjectDoc/ProjectDocBlockMap/ProjectStateApi，镜像 0005 `CreateModel` 块 line 19-115 的 `id`/FK `django.db.models.deletion.CASCADE`/`options.db_table`) + `migrations.AddIndex` + `migrations.AddConstraint`（镜像 0005 line 116-143 + line 124-127 partial constraint `condition=models.Q(...)`）。

**Gate:** `cd server && uv run python manage.py makemigrations --check --dry-run` 干净。

---

### `server/initiatives/services/project_doc_service.py` (NEW — service, CRUD + event-driven) ★INV-6 chokepoint

**Analog:** `services/memory_service.py`（成员闸 + 脱敏 + 审计）+ `project_service.py`（`async def` + `@sync_to_async _xxx_locked` + `transaction.atomic` + `get_or_create`）。

**import 头 + 常量**（镜像 `memory_service.py:19-48`）：

```python
from __future__ import annotations
import structlog
from asgiref.sync import sync_to_async
from django.db import transaction
from audit.services import taxonomy
from audit.services.audit_service import AuditService
from common.logging import redact_secrets_in_text
from initiatives.models import DocSyncStatus, DocType, ProjectDoc, ProjectStateApi

logger = structlog.get_logger(__name__)
_COMPONENT = "initiatives"
```

**upsert 写入收口**（镜像 `project_service.py:128-168` `_create_locked` 的 `get_or_create` + `transaction.atomic`）：

```python
@sync_to_async
def _upsert_doc_locked(self, *, project_id, doc_type, **fields):
    with transaction.atomic():
        return ProjectDoc.objects.get_or_create(
            project_id=project_id, doc_type=doc_type, defaults=fields,
        )
```

**审计 + 推送**（每个写方法收尾，逐字镜像 `project_service.py:103-124` / `memory_service.py:343-369`）：

```python
await AuditService.aemit(
    action=taxonomy.ACTION_PROJECT_DOC_PROVISIONED,  # 需在 taxonomy 登记新常量
    actor=actor, target_type="project_doc", target_id=doc.id, target_repr=str(doc.id),
    after={"project_id": str(project_id), "doc_type": doc_type, "sync_status": doc.sync_status},
    metadata={"component": _COMPONENT, "category": "caller",
              "initiated_by_user_id": str(actor_id) if actor_id else "system"},
    source="api",
)
```

**provision 后台外呼**（镜像 `background_runner.py:111-153` 调用契约 — **传 factory 不传 coroutine** + `initiated_by_user_id`）：

```python
from services.background_runner import run_in_background

def provision_workspace(self, project_id, *, initiated_by_user_id=None):
    run_in_background(
        lambda: self._provision_workspace_coro(project_id),   # factory！
        name=f"project-workspace:{project_id}",
        initiated_by_user_id=str(initiated_by_user_id) if initiated_by_user_id else None,
    )
```

**provision coroutine（串行外呼 + fail-soft 置 broken + 生命周期日志，本期观测强制项）：**

```python
async def _provision_workspace_coro(self, project_id):
    start = perf_counter()
    logger.info("project_workspace_provision_started", project_id=str(project_id),
                component=_COMPONENT, category="caller")
    try:
        project = await Project.objects.select_related("space").aget(pk=project_id)  # Pitfall 7: select_related
        client = create_feishu_doc_client_for_project(project.space)  # Pitfall 5: 入参是 Space
        # 1) create_folder（父 = project.space.feishu_doc_folder_token）→ ProjectService.set_folder_token()
        # 2) for doc_type in DocType: await client.create_document(...)（绝不 gather 并发，5QPS 串行）
        #    → self._upsert_doc_locked(project_id, doc_type, feishu_document_id=..., sync_status=READY)
        # 3) 互链回写 + update_work_item_fields 追加看板段（先 get_work_item 读后写，勿覆盖）
        logger.info("project_workspace_provision_completed", project_id=str(project_id),
                    duration_ms=int((perf_counter()-start)*1000), component=_COMPONENT, category="caller")
    except Exception:  # best-effort 绝不反噬：置 broken，留一键重建
        logger.warning("project_workspace_provision_failed", project_id=str(project_id), exc_info=True,
                       component=_COMPONENT, category="caller")
        await self._mark_broken(project_id)
```

**写路径成员闸（StateApi/Doc 写）：** 复用 `memory_service.py:72-85` `_is_member_sync`/`_assert_member` fail-closed —— **写一律成员闸，不放宽**。

---

### `server/initiatives/services/project_service.py` (MODIFY — service, CRUD)

**Analog:** 同文件 `update()` line 170-216。

**Pitfall 3 修复点 line 182**：白名单加 `visibility`（`feishu_folder_token` 不进 update，走专用 `set_folder_token` 后台写）：

```python
allowed = {"name", "description", "feishu_board_url", "feishu_board_id", "visibility"}
```

新增 `set_folder_token`（专用方法，镜像 `_update_locked` line 205-216 的 `select_for_update` + `save(update_fields=...)`，供后台 provision 写 `Project.feishu_folder_token`，不暴露给用户 PATCH）。`space` 改归（WS-03）另起专用方法，不塞 update 白名单。

---

### `server/tests/initiatives/test_project_doc_inv6_guard.py` (NEW — test, static-scan)

**Analog:** `tests/initiatives/test_artifact_inv6_guard.py`（多模型版，已处理前缀误伤）。

逐字镜像 `_PRUNE_DIRS`(line 16-26)、`_iter_py_files`(line 41-47)、`_is_scanned`(line 50-59) 与两个断言（`test_inv6_no_bypass_*` + `test_inv6_writer_module_actually_writes`）。改三处：

```python
_ALLOWED_WRITER = "initiatives/services/project_doc_service.py"
_MODELS = ("ProjectDoc", "ProjectDocBlockMap", "ProjectStateApi")
```

**Pitfall 4 前缀重叠（关键）：** 镜像 line 74-76 的跳过逻辑 —— `ProjectDoc(` 会误伤 `ProjectDocBlockMap(`，须加：

```python
if m == "ProjectDoc" and _RE_INSTANTIATE["ProjectDocBlockMap"].search(line):
    continue
```

`writer_actually_writes` 断言改检 `ProjectDoc.objects.get_or_create` 在 writer 内存在。

---

### `server/services/feishu_doc.py` (MODIFY — service, request-response) ★MEDIUM 待 live 验证

**Analog:** 同文件 `create_document` line 183-250（token/headers/retry/错误码 99991400 处理）。新增 `create_folder` 镜像其结构：

```python
# 镜像 create_document line 203-224 的 token 获取 + httpx.AsyncClient + code!=0 判错
async def create_folder(self, name: str, folder_token: str) -> str:
    token = await self.get_tenant_access_token()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{self.OPEN_API_BASE}/drive/v1/files/create_folder",  # A1: 待 live 验证
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"name": name, "folder_token": folder_token},
        )
        data = resp.json()
        if data.get("code") != 0:
            msg = data.get("msg", "Unknown error")
            if "rate limit" in msg.lower() or data.get("code") == 99991400:
                raise RateLimitError(f"Rate limit hit: {msg}")
            raise FeishuDocAPIError(f"Failed to create folder: {msg}")
        return data["data"]["token"]   # 返回结构待 live 验证
```

须加 `@retry(...RateLimitError...)` 装饰（既有 client 范式）；**5QPS 不可并发 → per-task 串行 await，绝不 `asyncio.gather`**。上游响应体/异常文本入库/日志前过 `redact_secrets_in_text`。

---

### `server/services/project_context_packer.py` (MODIFY — service, CRUD-read) ★泄漏风险

**Analog + 改造点:** 同文件 `_is_member` line 72-78 + `pack_project_context` fail-closed line 100-110。

**Pitfall 2 改造**（line 100-110，visibility 感知，不一刀切删 fail-closed）：

```python
from initiatives.models import ProjectVisibility
allowed = await _is_member(project_id, user)
if not allowed and getattr(project, "visibility", "") == ProjectVisibility.PUBLIC_ORG:
    allowed = True          # public_org 非成员可读召回
if not allowed:
    logger.info("project_context_pack_denied", project_id=str(project_id),
                reason="members_only_non_member", component=_COMPONENT, category="caller")
    return PackedContext()  # members_only 维持 fail-closed
```

`_write_trace`(line 288-320) 保留 —— 放宽后非成员命中仍写 `RetrievalTrace`（标 visibility）。

**对称守护测试（扩充 `tests/services/test_project_context_packer.py`）：** public_org 非成员可召回 / members_only 非成员零召回。

---

### `server/knowledge/access_scope.py` (MODIFY — service, CRUD-read)

**Analog:** 同文件 `resolve_allowed_project_ids` line 20-45。

把 `PermissionService.get_user_projects(user)` membership 集合（line 34-37）**并入** public_org 项目 id（visibility==public_org），再与 caller `project_ids` intersect。**注意（Pitfall 2）：** caller intersect 收窄语义（line 42-45）不能被放宽破坏 —— 只扩大 `allowed_set` 基集，交集逻辑不动。

---

### `server/initiatives/{views,serializers,urls}.py` (MODIFY — controller/serializer/route, request-response)

**views.py Analog:** `ArtifactListCreateView` line 431-471 + `_aget_project_for_read/write` line 403-428。新增 `ProjectDocListView`(GET 列表，读权限) / `ProjectDocRebuildView`(POST 重建，写权限→`ProjectDocService.provision_workspace`) / `ProjectStateApiListCreateView`(GET/POST)，逐字复用 `_aget_project_for_read`/`_aget_project_for_write` 闸 + `try/except ...Error → 400/403` + `await sync_to_async(serializer.is_valid)(raise_exception=True)`。**读放宽：** ProjectDoc 列表读权限须接 visibility（public_org 非成员可读，对齐 packer）。

**serializers.py Analog:** `ProjectSerializer` line 40-62（`fields` 列表加 `"visibility"`、`"feishu_folder_token"`）+ `ProjectUpdateSerializer` line 89-99（加 `visibility = serializers.ChoiceField(choices=ProjectVisibility.choices, required=False)`，V5 闭集校验）。新增 `ProjectDocSerializer` / `ProjectStateApiCreateSerializer`（method/path/status 走 `ChoiceField`）镜像既有 ModelSerializer/Serializer 写法。

**urls.py Analog:** 同文件 `path("<uuid:project_id>/memories/", ...)` line 79-83。新增 `<uuid:project_id>/docs/`、`<uuid:project_id>/docs/rebuild/`、`<uuid:project_id>/state-apis/`。

新增 REST 入口自动纳入 RequestMetric（统一中间件，无需手写）。

---

### `web/src/components/layout/AppSidebar.vue` (MODIFY — component, event-driven)

**Analog:** 同文件 `mainNavItems` line 89-100。WS-01 在 index 0(首页) 与 1(空间) 之间插入：

```typescript
const mainNavItems: NavItem[] = [
  { to: '/', label: '首页', icon: 'lucide--home', exact: true },
  { to: '/projects', label: '项目', icon: 'lucide--folder-kanban' },  // 新增（首页↓ 空间↑）
  { to: '/spaces', label: '空间', icon: 'lucide--folder-git-2' },
  // ... 其余不变
]
```

localStorage 范式同文件 line 78：`const isCollapsed = useLocalStorage('sidebar-collapsed', false)`（`@vueuse/core`，auto-import）。

---

### `web/src/pages/projects/index.vue` (MODIFY — component, request-response)

**Analog:** `AppSidebar.vue:78` `useLocalStorage` 范式。所选空间记忆：

```typescript
const spaceFilter = useLocalStorage('projects-selected-space', '__all__')
// 列表查询透传 space_id（projectsApi.list({ space_id })）
```

扩充 `web/src/pages/projects/__tests__/projects-list.spec.ts`：所选空间 localStorage 默认 + 侧边栏 tab。

---

### `web/src/api/projects.ts` (MODIFY — api-client, request-response)

**Analog:** 同文件 `Project` interface line 18-32 + `projectsApi` line 87-166。

`interface Project` 加 `visibility: 'public_org' | 'members_only'` 与 `feishu_folder_token: string`；新增 `ProjectDoc` interface + 端点（镜像既有 `get`/`post` 写法）：

```typescript
listDocs: (id: string): Promise<ProjectDoc[]> => get<ProjectDoc[]>(`/projects/${id}/docs/`),
rebuildDocs: (id: string): Promise<void> => post(`/projects/${id}/docs/rebuild/`, {}),
```

---

## Shared Patterns

### 写入收口 + 审计归因（INV-6）
**Source:** `initiatives/services/project_service.py:103-124`、`memory_service.py:343-369`
**Apply to:** `project_doc_service.py` 所有写方法、`project_service.py` set_folder_token。
每个写方法：`@sync_to_async _xxx_locked`(transaction.atomic + select_for_update/get_or_create) → `AuditService.aemit`(component=initiatives, category=caller, `initiated_by_user_id=str(actor_id) if actor_id else "system"`, source="api") → best-effort `apush_project_event`。

### 成员闸 fail-closed（写路径不动）
**Source:** `memory_service.py:72-85`（`_is_member_sync` + `_assert_member`）
**Apply to:** 所有写（ProjectDoc/StateApi/记忆/成员/文件）。**WS-02 翻转只放宽读/召回，写一律成员闸。**

### 后台任务归因 re-bind
**Source:** `services/background_runner.py:111-153`
**Apply to:** provision_workspace。传 factory（lambda）不传 coroutine；`initiated_by_user_id` → worker 干净 context 内 `bind_task_context(source="background")` 重绑。

### 脱敏不可绕过
**Source:** `common.logging.redact_secrets_in_text`（`memory_service.py:105,148,231` 用法）
**Apply to:** ProjectDoc.last_synced_snapshot 入库、飞书上游响应体/异常文本入库或日志前。

### adrf APIView 读写权限闸
**Source:** `initiatives/views.py:403-428`（`_aget_project_for_read/write`）
**Apply to:** ProjectDoc/StateApi 所有 view；读闸须接 visibility 放宽（public_org）。

### 前端 localStorage 偏好
**Source:** `AppSidebar.vue:78` `useLocalStorage('sidebar-collapsed', false)`
**Apply to:** projects/index.vue 所选空间记忆。

---

## No Analog Found

无。全部 16 文件均命中真实同构 analog。唯一非源码不确定项：飞书 `create_folder` 端点字段/返回结构（A1，库内无实现，镜像 `create_document` 形态后须 live 验证；标 MEDIUM）；看板 description 的 field_key（A2，`update_work_item_fields`/`get_work_item` 签名已确认 `server/services/feishu.py:118,206`，但具体 field_key 待 live 验证）。

## Metadata

**Analog search scope:** `server/initiatives/{models,services,migrations}`、`server/services/{feishu_doc,feishu,background_runner,project_context_packer}.py`、`server/knowledge/access_scope.py`、`server/tests/initiatives/`、`web/src/{components/layout,api,pages/projects}`
**Files scanned (read):** 18
**Pattern extraction date:** 2026-06-26

## PATTERN MAPPING COMPLETE
