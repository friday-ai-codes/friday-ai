# Phase 83: 飞书文档双向同步引擎 - Pattern Map

**Mapped:** 2026-06-26
**Files analyzed:** 11 个新增/扩展文件组（5 NEW + 4 EXTEND + 1 migration + test 群）
**Analogs found:** 11 / 11（全部有强分析对象，已 grep/读源码确认真实签名）

> 仓库真实根为 `friday-clean`（GSD 文案可能写 `friday-ai`，以 friday-clean 为准）。
> 全部分析对象均已读源、行号真实可引用。飞书 docx API 真实形态（subscribe / update_block /
> delete_blocks 端点、`drive.file.edit_v1` 字段、revision 形态）仍 `[ASSUMED]`，plan 首个 wave
> 须 live-Feishu UAT；但**调用骨架/token/headers/retry/错误码处理**逐字镜像既有方法即可。

---

## File Classification

| 新增/扩展文件 | Role | Data Flow | 最近分析对象（Analog） | 匹配度 |
|---|---|---|---|---|
| `server/initiatives/services/doc_sync_service.py` (NEW) | service | event-driven + CRUD | `initiatives/services/project_doc_service.py` + `memory_service.py` | exact（同 app 同层 service 范式） |
| `server/initiatives/services/doc_sync_diff.py` (NEW) | utility | transform（纯函数） | `services/feishu_doc.py::blocks_to_markdown` + `tasks/index_trigger_tasks.py::parse_push_event` | role-match（同仓纯函数模块） |
| `server/services/feishu_doc.py` (EXTEND: `subscribe_file`/`update_block`/`delete_blocks`) | service/client | request-response | 同文件 `create_folder` / `_write_regular_blocks` / `get_document_content` | exact（同类方法、同文件就地扩展） |
| `server/durable/queues.py` (EXTEND: `QUEUE_DOC_SYNC`) | config | — | 同文件既有 `QUEUE_*` 常量 + `ALL_QUEUES` | exact |
| `server/durable/tasks.py` (EXTEND: `durable_doc_sync_pull/push`) | task（procrastinate 包壳） | event-driven | 同文件 `durable_index` / `durable_repo_summary` | exact |
| `server/durable/tasks_impl.py` (EXTEND: `run_doc_sync_pull/push`) | task（业务任务体） | event-driven | 同文件 `run_index` / `run_repo_summary` | exact |
| `server/feishu/views.py`（或 `websocket_client.py`，EXTEND drive 路由 + normalizer） | controller/route | event-driven | `views.py::_maybe_schedule_project_board_sync` + event_type 分支 / `websocket_client.py::register_p2_*` | exact（同入口同范式新增分支） |
| `server/agents/management/commands/runapscheduler.py` (EXTEND `poll_project_docs_revisions` job) + `server/tasks/*` 实现 | scheduler | batch/poll | `poll_repository_updates_job` + `tasks/index_trigger_tasks.py::poll_repository_updates` | exact |
| `server/initiatives/migrations/0007_*.py`（NEW，扩 `ProjectDoc` 字段 + `ProjectDocBlockRevision`） + `models/project_doc.py`（EXTEND） | migration / model | — | `migrations/0006_project_workspace_entities.py` + `models/project_doc.py` | exact |
| `server/tests/initiatives/test_doc_sync_*.py`（NEW 群） | test | — | `test_project_doc_service.py` + `test_memory_service.py` | exact |
| `server/tests/initiatives/test_doc_sync_inv6_guard.py`（NEW） | test（grep 守护） | — | `test_project_doc_inv6_guard.py`（逐字镜像） | exact |

---

## Pattern Assignments

### `server/initiatives/services/doc_sync_service.py` (service, event-driven + CRUD)

**Analog:** `server/initiatives/services/project_doc_service.py`（主）+ `server/initiatives/services/memory_service.py`（写收口 + revision + 脱敏 + 成员校验）

**模块头 + imports**（镜像 `project_doc_service.py:22-49`）——`structlog` logger、`sync_to_async`、`transaction`、`_COMPONENT="initiatives"`：

```22:49:server/initiatives/services/project_doc_service.py
from __future__ import annotations

import time
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction

from audit.services import taxonomy
from audit.services.audit_service import AuditService
from initiatives.models import (
    ApiSource,
    ApiStatus,
    DocSection,
    DocSyncStatus,
    DocType,
    ProjectDoc,
    ProjectDocBlockMap,
    ProjectStateApi,
)

logger = structlog.get_logger(__name__)

__all__ = ["ProjectDocService"]

# 审计组件常量。
_COMPONENT = "initiatives"
```

**async + `sync_to_async` + `transaction.atomic` + `select_for_update` 写收口范式**（`project_doc_service.py:113-142`）——`DocSyncService` 更新 `last_synced_revision`/`last_synced_snapshot` 须用 CAS 式条件 update（Pitfall 3：不能只靠 durable lock）：

```113:142:server/initiatives/services/project_doc_service.py
    @sync_to_async
    def _set_doc_feishu_locked(
        self, doc_id: Any, document_id: str, doc_token: str, sync_status: str
    ) -> ProjectDoc:
        with transaction.atomic():
            doc = ProjectDoc.objects.select_for_update().get(pk=doc_id)
            doc.feishu_document_id = document_id
            doc.feishu_doc_token = doc_token
            doc.sync_status = sync_status
            doc.save(
                update_fields=[
                    "feishu_document_id",
                    "feishu_doc_token",
                    "sync_status",
                    "updated_at",
                ]
            )
        return doc

    async def set_sync_status(self, *, doc_id: Any, status: str) -> ProjectDoc:
        """持久化文件同步状态（broken 落 DB，供一键重建）。"""
        return await self._set_sync_status_locked(doc_id, status)

    @sync_to_async
    def _set_sync_status_locked(self, doc_id: Any, status: str) -> ProjectDoc:
        with transaction.atomic():
            doc = ProjectDoc.objects.select_for_update().get(pk=doc_id)
            doc.sync_status = status
            doc.save(update_fields=["sync_status", "updated_at"])
        return doc
```

**block_map upsert（SYNC-03 映射表）已就绪、直接复用**（`project_doc_service.py:146-179`）——`DocSyncService` 不旁路写表，经 `ProjectDocService.upsert_block_map`：

```146:179:server/initiatives/services/project_doc_service.py
    async def upsert_block_map(
        self,
        *,
        doc_id: Any,
        feishu_block_id: str,
        db_ref: str = "",
        section: str = DocSection.SYSTEM,
        content_hash: str = "",
    ) -> ProjectDocBlockMap:
        """按 (doc, feishu_block_id) 幂等 upsert block 映射（同步引擎 Phase 83 用，本期骨架）。"""
        block, _created = await self._upsert_block_map_locked(
            doc_id, feishu_block_id, db_ref, section, content_hash
        )
        return block

    @sync_to_async
    def _upsert_block_map_locked(
        self,
        doc_id: Any,
        feishu_block_id: str,
        db_ref: str,
        section: str,
        content_hash: str,
    ) -> tuple[ProjectDocBlockMap, bool]:
        with transaction.atomic():
            return ProjectDocBlockMap.objects.update_or_create(
                doc_id=doc_id,
                feishu_block_id=feishu_block_id,
                defaults={
                    "db_ref": db_ref,
                    "section": section,
                    "content_hash": content_hash,
                },
            )
```

**fail-soft + 脱敏 + 预取 FK 范式**（`project_doc_service.py:332-369, 464-476`）——pull/push 全程 best-effort，异常吞掉记 `*_failed` 事件；async 取 project 必须 `select_related` 预取 space（Anti-Pattern：async 裸访问 lazy FK）：

```332:369:server/initiatives/services/project_doc_service.py
    async def _provision_workspace_coro(
        self, project_id: Any, initiated_by_user_id: str | None = None
    ) -> None:
        """串行建飞书文件夹 + 5 文件 + 互链 + 看板描述追加（best-effort，绝不抛）。

        任一外呼失败 → 对应 ``ProjectDoc.sync_status=broken``（持久化 DB），继续其余，
        绝不阻断主流程。``create_folder`` 5QPS/不可并发 → 全程串行（无 ``asyncio.gather``）。
        """
        from common.logging import redact_secrets_in_text

        started = time.monotonic()
        uid_repr = initiated_by_user_id or "system"
        logger.info(
            "project_workspace_provision_started",
            project_id=str(project_id),
            initiated_by_user_id=uid_repr,
            component=_COMPONENT,
            category="caller",
        )

        ready = 0
        broken = 0
        try:
            project = await self._aget_project_with_space(project_id)
        except Exception as exc:  # noqa: BLE001 — 连项目都取不到，记 failed 后退出（不抛）
            logger.warning(
                "project_workspace_provision_failed",
                project_id=str(project_id),
                reason="project_load_failed",
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )
            return
```

```464:476:server/initiatives/services/project_doc_service.py
    @sync_to_async
    def _aget_project_with_space(self, project_id: Any) -> Any:
        """预取 space（防 async lazy FK 访问报错，Pitfall 7）。"""
        from initiatives.models import Project

        return Project.objects.select_related("space").get(pk=project_id)

    @staticmethod
    async def _build_doc_client(space: Any) -> Any:
        """构建 FeishuDocClient（入参是 Space 实例，Pitfall 5）。"""
        from agents.tools.feishu_doc_tools import create_feishu_doc_client_for_project

        return await create_feishu_doc_client_for_project(space)
```

**MEMORY 飞书编辑落 revision（SYNC-03/04 + OQ-1）**——来自 `memory_service.py`。注意 **OQ-1 冲突**：`MemoryService.edit/append` 默认 MEM-02 成员 fail-closed（`_assert_member` 抛 `MemoryPermissionError`），但非成员飞书编辑须 fail-soft。已有 `_skip_member_check` 受限入口可借鉴（`memory_service.py:89-104`），plan 须裁决用 `_skip_member_check`+来源标注路径或落草稿态：

```89:117:server/initiatives/services/memory_service.py
    async def append(
        self,
        *,
        project_id: Any,
        content: str,
        contributor: Any,
        actor: Any = None,
        initiated_by_user_id: Any = None,
        _skip_member_check: bool = False,
    ) -> ProjectMemory:
        """新增一条项目记忆（MEM-01）。成员校验 + 脱敏 + 初始 revision 快照。

        ``_skip_member_check`` 仅供 ``confirm_draft`` 内部复用（草稿确认时成员校验已在外层完成）。
        """
        if not _skip_member_check:
            await self._assert_member(project_id, contributor)
        redacted = redact_secrets_in_text(content or "")
        memory = await self._append_locked(
            project_id=project_id, content=redacted, contributor=contributor
        )
```

```163:176:server/initiatives/services/memory_service.py
    @sync_to_async
    def _edit_locked(
        self, *, memory_id: Any, content: str, editor: Any
    ) -> tuple[ProjectMemory, str]:
        with transaction.atomic():
            memory = ProjectMemory.objects.select_for_update().get(pk=memory_id)
            before = memory.content
            memory.content = content
            memory.save(update_fields=["content", "updated_at"])
            # append-only 快照新态（编辑历史链，绝不就地丢历史）。
            ProjectMemoryRevision.objects.create(
                memory=memory, content=content, editor=editor
            )
        return memory, before
```

**read-through 缓存（SYNC-05）**——`django.core.cache`，redis 不可用 + `IGNORE_EXCEPTIONS` 返回 None 降级直读 DB；失效用 `delete` 而非 set 空（Pitfall 7）。模式见 RESEARCH `83-RESEARCH.md` Code Examples（`render_doc_cached`），无既有同款 service 内调用点，照 RESEARCH 范式实现即可。

---

### `server/initiatives/services/doc_sync_diff.py` (utility, transform — 纯函数无 IO，易测)

**Analog:** `server/services/feishu_doc.py::blocks_to_markdown`（纯转换函数，模块级 `def`）+ `server/tasks/index_trigger_tasks.py::parse_push_event` / `_branch_name_from_ref`（纯解析 + dataclass 风格返回）

**模块级纯函数 + 防御性 `.get` 取值 + 结构化 dict 返回**（`index_trigger_tasks.py:88-111`）——block diff/三方合并应是无副作用纯函数（外呼/入库在 `DocSyncService` 收口），便于 `test_doc_sync_diff.py` 无 IO 单测：

```88:111:server/tasks/index_trigger_tasks.py
def _branch_name_from_ref(ref: str) -> str:
    return ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else ""


def parse_push_event(platform: str, payload: dict) -> dict[str, Any]:
    """从不同平台的 push 事件中提取关键信息。

    返回: ref、after、branch_name、is_delete
    """
    if platform == "github":
        ref = str(payload.get("ref", ""))
        after = str(payload.get("after", ""))
    elif platform == "gitlab":
        ref = str(payload.get("ref", ""))
        after = str(payload.get("after", payload.get("checkout_sha", "")))
    elif platform == "gitea":
        ref = str(payload.get("ref", ""))
        after = str(payload.get("after", ""))
    else:
        return {"ref": "", "after": "", "branch_name": "", "is_delete": False}

    is_delete = bool(payload.get("deleted", False)) or after == _ZERO_DELETE_SHA
    branch_name = _branch_name_from_ref(ref)
    return {"ref": ref, "after": after, "branch_name": branch_name, "is_delete": is_delete}
```

**content_hash 计算**：参考 `index_trigger_tasks.py` 顶部 `import hashlib`（行 10）。block 指纹建议 `hashlib.sha256(normalized_text.encode()).hexdigest()`，落 `ProjectDocBlockMap.content_hash`（`max_length=128` 已就绪，见 `models/project_doc.py:116`）。

> 建议导出：`diff_blocks(base_snapshot, theirs_blocks, block_map) -> {added, edited, deleted}`、`three_way_merge(base, theirs, ours) -> MergeResult(merged, conflicts)`。全部 keyword-only / 普通参数 + dataclass 返回，零 ORM/httpx 依赖。

---

### `server/services/feishu_doc.py` (service/client, request-response — EXTEND `subscribe_file`/`update_block`/`delete_blocks`)

**Analog:** 同文件 `create_folder`（独立 POST + @retry + 错误码分类）、`_write_regular_blocks`（children 写）、`get_document_content`（GET + 错误码分类 + RateLimit/Permission/NotFound 分流）

**@retry 装饰 + token + headers + 错误码分类范式（必须逐字镜像）**（`feishu_doc.py:121-163`）——新方法照此对 `99991400`/"rate limit"→`RateLimitError`、`PERMISSION_CODES`→`PermissionDeniedError`、`NOT_FOUND_CODES`→`DocumentNotFoundError` 分流（SYNC-06 not-found→broken 靠 `DocumentNotFoundError`）：

```121:163:server/services/feishu_doc.py
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type(RateLimitError),
        reraise=True,
    )
    async def get_document_content(
        self,
        document_id: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Read Feishu cloud document content."""
        token = await self.get_tenant_access_token()

        async with httpx.AsyncClient() as client:
            # Get document blocks
            response = await client.get(
                f"{self.OPEN_API_BASE}/docx/v1/documents/{document_id}/blocks",
                headers={"Authorization": f"Bearer {token}"},
                params={"page_size": 500},
            )
            data = response.json()

            if data.get("code") != 0:
                error_code = data.get("code", 0)
                error_msg = data.get("msg", "Unknown error")
                if error_code == 99991400 or "rate limit" in error_msg.lower():
                    raise RateLimitError(f"Rate limit hit: {error_msg}")
                if error_code in PERMISSION_CODES:
                    raise PermissionDeniedError(f"无权限访问文档: {error_msg}")
                if error_code in NOT_FOUND_CODES:
                    raise DocumentNotFoundError(f"文档不存在: {error_msg}")
                raise FeishuDocAPIError(f"读取文档失败: {error_msg}")
```

**独立外呼方法（含 `[ASSUMED]` 端点标注 + 仅记业务标识不记正文/token）**（`feishu_doc.py:258-313`，`create_folder` 是新增端点的最佳模板）——`subscribe_file`/`update_block`/`delete_blocks` 照此结构，端点 live 验证后固化（A4：`update_block`=PATCH `/docx/v1/documents/{id}/blocks/{block_id}`、`delete`=batch_delete children by index）：

```258:313:server/services/feishu_doc.py
    async def create_folder(self, name: str, folder_token: str) -> str:
        """在指定父文件夹下创建子文件夹，返回新文件夹 token。

        镜像 ``create_document`` 的 token/headers/retry/错误码处理。每项目专属工作区
        文件夹经此创建（父 = Space 的 ``feishu_doc_folder_token``）。

        约束：飞书 Drive ``create_folder`` 5QPS 且**不可并发** —— 调用方须 per-task 串行
        （绝不 ``asyncio.gather``）；限流（``99991400`` / msg 含 "rate limit"）经 @retry 退避。

        # A1: 端点形态 MEDIUM，需 live 验证（POST /drive/v1/files/create_folder，
        # body {name, folder_token}，返回 data.token）。
        """
        token = await self.get_tenant_access_token()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.OPEN_API_BASE}/drive/v1/files/create_folder",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "name": name,
                    "folder_token": folder_token,
                },
            )
            data = response.json()

            if data.get("code") != 0:
                error_msg = data.get("msg", "Unknown error")
                if "rate limit" in error_msg.lower() or data.get("code") == 99991400:
                    raise RateLimitError(f"Rate limit hit: {error_msg}")
                raise FeishuDocAPIError(f"Failed to create folder: {error_msg}")

            new_token = data.get("data", {}).get("token", "")
            if not new_token:
                raise FeishuDocAPIError("No token in create_folder response")

            # 仅记父/新 token（业务标识，非凭证/正文），便于排障定位。
            logger.info(
                "feishu_folder_created",
                folder_token=folder_token,
                new_token=new_token,
            )
            return new_token
```

**block 级写（children API，SYNC-02 增量新增分支）**（`feishu_doc.py:374-398`）——`update_block`/`delete_blocks` 镜像同款 `client.post/patch/delete` + `data.get("code") != 0` 判定；**永不整篇 replace**（硬约束）：

```374:398:server/services/feishu_doc.py
    async def _write_regular_blocks(
        self,
        document_id: str,
        blocks: list[dict[str, Any]],
        headers: dict[str, str],
        client: Any,
    ) -> None:
        """Write regular (non-table) blocks via children API."""
        response = await client.post(
            f"{self.OPEN_API_BASE}/docx/v1/documents/{document_id}/blocks/{document_id}/children",
            headers=headers,
            json={"children": blocks, "index": -1},
        )
        data = response.json()
        if data.get("code") != 0:
            logger.error(
                "feishu_write_blocks_failed",
                document_id=document_id,
                error_code=data.get("code"),
                error_msg=data.get("msg"),
                error_data=data,
            )
            raise FeishuDocAPIError(
                f"文档已创建但内容写入失败: {data.get('msg', 'Unknown error')} (code={data.get('code')})"
            )
```

---

### `server/durable/queues.py` (config — EXTEND `QUEUE_DOC_SYNC`)

**Analog:** 同文件既有队列常量块 + `ALL_QUEUES` + `__all__`（`queues.py:10-42`）——加 `QUEUE_DOC_SYNC = "doc_sync"`，同步追加到 `ALL_QUEUES` 与 `__all__`：

```10:42:server/durable/queues.py
# 代码索引（仓库 reindex / 增量索引）
QUEUE_INDEX = "index"
# 代码图谱构建（codegraph / galaxy）
QUEUE_GRAPH = "graph"
...
# 维护类周期任务（stalled rescue 等运维任务）
QUEUE_MAINTENANCE = "maintenance"

# 全部已声明队列的汇总，供注册 / 校验 / worker 启动参数等场景遍历。
ALL_QUEUES: tuple[str, ...] = (
    QUEUE_INDEX,
    QUEUE_GRAPH,
    QUEUE_CRAWL_INGEST,
    QUEUE_PAGE_INDEX,
    QUEUE_REPO_SUMMARY,
    QUEUE_MAINTENANCE,
)

__all__ = [
    "QUEUE_INDEX",
    ...
    "ALL_QUEUES",
]
```

---

### `server/durable/tasks.py` (task 包壳 — EXTEND `durable_doc_sync_pull/push`)

**Analog:** 同文件 `durable_index`（`tasks.py:31-57`）与 `durable_repo_summary`（`tasks.py:89-104`）

**`@app.task(name=, queue=)` 包壳 → 函数体内局部 import → 委托 `tasks_impl.run_*`；显式 `name=` 与裸名查找同源；keyword-only 形参逐字对齐 payload + 转发 `initiated_by_user_id`（CTX-02）**：

```31:57:server/durable/tasks.py
@app.task(name="durable_index", queue=QUEUE_INDEX)
async def durable_index(
    *,
    repository_id: str,
    history_id: str | None = None,
    branch: str | None = None,
    trigger: str = "manual",
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """代码索引 durable 任务（procrastinate 包壳，委托共用任务体）。"""
    from durable.tasks_impl import run_index

    return await run_index(
        repository_id=repository_id,
        history_id=history_id,
        branch=branch,
        trigger=trigger,
        initiated_by_user_id=initiated_by_user_id,
    )
```

> 新增两个包壳：`durable_doc_sync_pull(*, file_token="", event_id="", initiated_by_user_id=None)` 与 `durable_doc_sync_push(*, doc_id="", initiated_by_user_id=None)`，`queue=QUEUE_DOC_SYNC`，从 `durable.queues` import 新常量（见 `tasks.py:19-26` import 块）。RESEARCH `83-RESEARCH.md` Code Examples 已给逐字骨架。

---

### `server/durable/tasks_impl.py` (task 业务体 — EXTEND `run_doc_sync_pull/push`)

**Analog:** 同文件 `run_index`（`tasks_impl.py:27-48`）与 `run_repo_summary`（`tasks_impl.py:144-179`）

**worker 入口 `bind_task_context(user_id=..., source="durable")` 重 bind 发起用户（CTX-02）+ 函数体内局部 import service + best-effort**（注意：本期应显式带 `component="doc_sync"`，见 `83-RESEARCH.md` Code Examples）：

```27:48:server/durable/tasks_impl.py
async def run_index(
    *,
    repository_id: str,
    history_id: str | None = None,
    branch: str | None = None,
    trigger: str = "manual",
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """代码索引任务体：克隆并索引仓库。"""
    from services.indexer import clone_and_index_repository

    with bind_task_context(user_id=initiated_by_user_id, source="durable"):
        return await clone_and_index_repository(
            repository_id, history_id=history_id, branch=branch
        )
```

**幂等跳过 + 结构化 status dict 返回 + `not_found`/`skipped` 分支**（`tasks_impl.py:157-179`）——pull 内先 gate（项目归档/doc broken/not-found 跳过）：

```157:179:server/durable/tasks_impl.py
    with bind_task_context(user_id=initiated_by_user_id, source="durable"):
        repo = await Repository.objects.filter(id=repository_id, is_deleted=False).afirst()
        if repo is None:
            logger.info(
                "durable_repo_summary_skipped", repository_id=repository_id, reason="not_found"
            )
            return {"status": "skipped", "reason": "not_found", "repository_id": repository_id}

        # 已完成的不重复生成（幂等）；pending/running/failed 允许（重新触发/恢复）。
        if repo.ai_summary_status == AISummaryStatus.COMPLETED:
            return {
                "status": "skipped",
                "reason": "already_completed",
                "repository_id": repository_id,
            }
```

---

### `server/feishu/views.py`（或 `websocket_client.py`）— drive.file.edit_v1 路由 + normalizer (controller/route, event-driven)

**Analog:**
- HTTP 入口：`views.py` event_type 多路复用分支（`views.py:790-801`）+ `_maybe_schedule_project_board_sync`（`views.py:1059-1117`，normalizer→归因→后台投递的最佳模板）
- WS 入口：`websocket_client.py::_build_event_handler`（`websocket_client.py:68-76`，`register_p2_*` 注册）

**event_type 多路复用 → 新增 `drive.file.edit_v1` 分支**（`views.py:788-801`）：

```788:801:server/feishu/views.py
        if project is None:
            logger.info("webhook_event_no_project_skip_side_effects", event_type=event_type)
        elif event_type == "WorkitemCreateEvent":
            await self._handle_workitem_create(project, payload, trigger_log)
        elif event_type == "WorkitemStatusEvent":
            await self._handle_workitem_status(project, payload, trigger_log)
        elif event_type == "WorkFlowNodeStatusEvent":
            await self._handle_workflow_node_status(project, payload, trigger_log)
        elif event_type == "WorkitemCommentEvent":
            await self._handle_workitem_comment(project, payload, trigger_log)
        elif event_type == "WorkitemUpdateEvent":
            await self._handle_workitem_update(project, payload, trigger_log)
        else:
            logger.info("webhook_event_unhandled", event_type=event_type)
```

**normalizer：防御性取值 + `resolve_feishu_user` 归因（未映射 `system`）+ 只投三元组标量后台异步**（`views.py:1069-1117`，这是 drive normalizer + defer 的逐字模板，把 `run_in_background` 换成 `DurableTaskService.defer` 即可，见 RESEARCH Pattern 1）：

```1069:1117:server/feishu/views.py
        if project is None or not is_project_tracking_event(payload):
            return

        work_item_id = payload.get("id")
        work_item_type = payload.get("work_item_type_key", "")
        if not work_item_id or not work_item_type:
            logger.warning(
                "project_board_sync_skip_incomplete_identity",
                work_item_id=work_item_id,
                work_item_type=work_item_type,
            )
            return
        ...
        # 解析触发飞书人 → initiated_by_user_id（未映射 system）
        initiated_by = "system"
        operator = str(payload.get("operator_id") or payload.get("user_id") or "")
        if operator:
            from feishu.services.identity import resolve_feishu_user

            user = await resolve_feishu_user(open_id=operator) or await resolve_feishu_user(
                feishu_user_key=operator
            )
            if user is not None:
                initiated_by = str(user.id)
        ...
        run_in_background(
            lambda: ProjectBoardSyncService().sync_from_board(
                space=project,
                feishu_project_key=feishu_project_key,
                board_work_item_id=board_work_item_id,
                board_work_item_type=work_item_type,
                name=name,
                initiated_by_user_id=initiated_by,
            ),
            name=f"project-board-sync:{feishu_project_key}:{board_work_item_id}",
            initiated_by_user_id=initiated_by,  # CTX-02：worker 入口 re-bind
        )
```

> ⚠️ 与上面 board_sync 用 `run_in_background` 不同，**drive 同步必须用 `DurableTaskService.defer`**（per-doc `lock` 串行 + 重启不丢，见下方 `defer` 签名）。RESEARCH Pattern 1 已给逐字 defer 调用。

**WS 路径 normalizer 注册点**（`websocket_client.py:68-76`，A2：lark-oapi 是否提供 `register_p2_drive_file_edit_v1` 需 live 验证，不可用则回退 HTTP webhook 分支）：

```68:76:server/feishu/websocket_client.py
    def _build_event_handler(self) -> lark.EventDispatcherHandler:
        ...
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._handle_message_receive)
            .register_p2_card_action_trigger(self._handle_card_action)
```

**幂等去重已就绪、直接复用**（`views.py:147-152` 的 `is_event_processed_db`/`mark_event_processed_db` + durable `idempotency_key`，Don't-Hand-Roll）。

---

### `server/durable/service.py` — `DurableTaskService.defer`（既有门面，drive 路由 + push 钩子调用契约）

**Analog:** 不新增，直接调用。`defer` 签名是 per-doc 串行（`lock`）+ debounce（`idempotency_key` + `run_at`）的真实契约（`service.py:82-130`）：

```82:107:server/durable/service.py
    @staticmethod
    async def defer(
        task: str,
        payload: dict[str, Any],
        *,
        queue: str,
        priority: int = 0,
        idempotency_key: str | None = None,
        run_at: datetime.datetime | None = None,
        lock: str | None = None,
        initiated_by_user_id: str | None = None,
    ) -> str:
        """入队一个 durable 任务，返回 job id。

        ``lock``：Procrastinate 原生 doing 并发锁（同 lock 串行执行）...
        in-process fallback 无 doing 并发概念，``lock`` 被忽略（dev/pytest 串行）。

        ``initiated_by_user_id``（CTX-02）：发起用户 id，非空时写入
        ``payload["initiated_by_user_id"]`` 随 job 跨进程/线程传播...
        """
```

> SYNC-02/04 推送侧：`lock=f"docsync-{doc_id}"`（pull/push 共用同 lock 防交叉）、`idempotency_key=f"docpush:{doc_id}"`（窗口内去重合并）、`run_at=now+DEBOUNCE`（静默窗口延迟）。⚠️ Pitfall 3：in-process（SQLite/pytest）忽略 `lock`/`run_at`，串行正确性必须靠 `DocSyncService` 内乐观并发（重拉 revision 比对 + CAS update）兜底。

---

### `server/agents/management/commands/runapscheduler.py` (scheduler — EXTEND `poll_project_docs_revisions`) + `server/tasks/*` 实现

**Analog:** `runapscheduler.py::poll_repository_updates_job`（`runapscheduler.py:146-158`）+ `add_job` 注册（`runapscheduler.py:617-629`）+ `tasks/index_trigger_tasks.py::poll_repository_updates`（`index_trigger_tasks.py:458-501`）

**job wrapper：`@_with_scheduler_log_context`（系统调度归因 `user_id="system"` + `source="scheduler"`）+ 函数体内 import + `run_async_task`**（`runapscheduler.py:146-158`）：

```146:158:server/agents/management/commands/runapscheduler.py
@_with_scheduler_log_context
def poll_repository_updates_job():
    """Job wrapper for poll_repository_updates task (implementation)."""
    from tasks.index_trigger_tasks import poll_repository_updates

    log = logger.bind(job="poll_repository_updates")
    ...
        result = run_async_task(poll_repository_updates)
```

**`add_job` 注册（`IntervalTrigger` + `max_instances=1` + `replace_existing=True`，flock 强制单实例）**（`runapscheduler.py:617-629`）：

```617:629:server/agents/management/commands/runapscheduler.py
        # Poll repository updates every N seconds (... 间隔由 settings.SYNC_INTERVAL_SECONDS 统一管理)
        scheduler.add_job(
            poll_repository_updates_job,
            trigger=IntervalTrigger(seconds=settings.SYNC_INTERVAL_SECONDS),
            id="poll_repository_updates",
            name="Poll for repository updates via git ls-remote",
            max_instances=1,
            replace_existing=True,
        )
        ...
        logger.info("job_registered", job="poll_repository_updates", schedule=f"every {settings.SYNC_INTERVAL_SECONDS}s")
```

**轮询任务体：遍历进行中目标 → 比对水位 → 变了触发（结构化 `{checked, triggered}` 返回 + 单条 try/except 隔离不阻断整批）**（`index_trigger_tasks.py:458-501`）——`poll_project_docs_revisions` 镜像：取进行中项目的 READY doc → 回拉 `revision` 比对 `ProjectDoc.last_synced_revision` → 变了 `DurableTaskService.defer("durable_doc_sync_pull", ...)`：

```458:501:server/tasks/index_trigger_tasks.py
async def poll_repository_updates() -> dict[str, int]:
    """轮询所有启用自动索引的仓库，检查远端 HEAD 是否变化。"""
    repositories = [
        repo
        async for repo in Repository.objects.filter(
            auto_index_enabled=True, is_deleted=False
        )
    ]

    checked = 0
    triggered = 0

    for repo in repositories:
        checked += 1
        ...
        try:
            remote_sha = await _get_remote_head_sha(repo.git_url)
            ...
            if remote_sha and remote_sha != repo.last_indexed_commit_sha:
                result = await trigger_auto_index(repo, "scheduled", remote_sha)
                if result["status"] == "triggered":
                    triggered += 1
        except Exception:
            logger.exception(
                "poll_check_failed",
                repository_id=str(repo.id),
                git_url=repo.git_url,
            )

    logger.info("poll_complete", checked=checked, triggered=triggered)
    return {"checked": checked, "triggered": triggered}
```

> 实现落点：建议放 `server/initiatives/services/doc_sync_service.py`（`DocSyncService.poll_revisions`）或 `server/tasks/`，job wrapper 在 `runapscheduler.py` 调用。

---

### migration + `models/project_doc.py` (migration/model — 扩 `ProjectDoc` 字段 + 新增 `ProjectDocBlockRevision`)

**Analog:** `migrations/0006_project_workspace_entities.py`（`AddField` + `CreateModel` + `AddIndex` + `AddConstraint` 完整范式）+ `models/project_doc.py`（`ProjectDocBlockMap` 是新 revision 模型的形态模板）

**OQ-4：`ProjectDoc` 加 `subscribed`(bool) + `last_feishu_edit_at`(datetime)**（承载飞书订阅态 + 编辑感知活跃探测），`AddField` 镜像 `0006:15-19`：

```15:19:server/initiatives/migrations/0006_project_workspace_entities.py
        migrations.AddField(
            model_name='project',
            name='feishu_folder_token',
            field=models.CharField(blank=True, default='', max_length=200, verbose_name='飞书工作区文件夹 token'),
        ),
```

**OQ-2：新增 `ProjectDocBlockRevision`（doc + block_id + content + source + captured_at）**作 STATE/MILESTONES/RESEARCH/PREFLIGHT capture-never-clobber 落败方落点；`CreateModel` + `AddConstraint`/`AddIndex` 镜像 `0006:46-99`，模型定义镜像 `ProjectDocBlockMap`（`models/project_doc.py:98-133`）：

```98:133:server/initiatives/models/project_doc.py
class ProjectDocBlockMap(models.Model):
    """飞书 block ↔ 库内引用的同步映射（每文档每 block_id 至多一行）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    doc = models.ForeignKey(
        "initiatives.ProjectDoc",
        on_delete=models.CASCADE,
        related_name="block_maps",
        verbose_name="所属文件",
    )
    feishu_block_id = models.CharField(max_length=200, verbose_name="飞书 block id")
    db_ref = models.CharField(max_length=200, blank=True, default="", verbose_name="库内引用")
    section = models.CharField(
        max_length=20,
        choices=DocSection.choices,
        default=DocSection.SYSTEM,
        verbose_name="区段",
    )
    content_hash = models.CharField(max_length=128, blank=True, default="", verbose_name="内容指纹")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "initiative_project_doc_block_maps"
        ...
        constraints = [
            models.UniqueConstraint(fields=["doc", "feishu_block_id"], name="uniq_doc_block"),
        ]
        indexes = [
            models.Index(fields=["doc", "section"]),
        ]
```

> 关键约束：`last_synced_revision` 已是 `BigIntegerField`（`models/project_doc.py:69`）——A5 须确认飞书 revision 为整型。新 revision 写入仍经 `ProjectDocService`（INV-6），并把新模型加入 `test_doc_sync_inv6_guard` 的 `_MODELS`。migration 文件名顺延 `0007_*`，`dependencies` 指向 `0006`。Phase gate 需 `makemigrations --check`。

---

### tests（`tests/initiatives/test_doc_sync_*.py` + `test_doc_sync_inv6_guard.py`）

**Analog（业务测试）:** `test_project_doc_service.py:14-56`（`pytestmark = pytest.mark.django_db(transaction=True)`、`unittest.mock` mock FeishuDocClient、`sync_to_async` fixture 工厂）。飞书外呼用 `respx`（httpx mock，见 `83-RESEARCH.md` Validation）：

```14:40:server/tests/initiatives/test_project_doc_service.py
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from audit.models import AuditEvent
from audit.services import taxonomy
from initiatives.models import (
    ApiStatus,
    DocSyncStatus,
    DocType,
    Project,
    ProjectDoc,
    ProjectDocBlockMap,
    ProjectStateApi,
)
from initiatives.services import ProjectDocService, ProjectService
from projects.models import Space
from services.feishu_doc import FeishuDocAPIError

pytestmark = pytest.mark.django_db(transaction=True)
```

**Analog（INV-6 grep 守护）:** `test_project_doc_inv6_guard.py`（**逐字镜像**给 `test_doc_sync_inv6_guard.py`）——纯源码扫描、无 DB/网络、`_MODELS` + `_RE_ORM_WRITE` + `_RE_INSTANTIATE` + 唯一 writer 白名单。本期新 `ProjectDocBlockRevision` 落库须只经 `ProjectDocService`，故应**扩展现有 guard 的 `_MODELS`**（而非另写）：

```32:42:server/tests/initiatives/test_project_doc_inv6_guard.py
_ALLOWED_WRITER = "initiatives/services/project_doc_service.py"

_MODELS = ("ProjectDoc", "ProjectDocBlockMap", "ProjectStateApi")
_RE_ORM_WRITE = {
    m: re.compile(
        rf"\b{m}\.objects\.(?:create|bulk_create|get_or_create|update_or_create)\b"
    )
    for m in _MODELS
}
# 直接实例化 Model(...)（紧跟 "(" 排除 ProjectDocBlockMap( 误伤 ProjectDoc 等更长符号）
_RE_INSTANTIATE = {m: re.compile(rf"\b{m}\s*\(") for m in _MODELS}
```

> 测试文件群（来自 `83-RESEARCH.md` Wave 0 Gaps）：`test_doc_sync_diff.py`（纯函数核心，无 IO）、`test_doc_sync_conflict.py`、`test_doc_sync_rebase.py`、`test_doc_sync_push.py`（respx 断言无全量 PUT）、`test_doc_sync_poll.py`、`test_doc_sync_cache.py`、`test_doc_sync_boundaries.py`、`tests/feishu/test_drive_event_route.py`、`tests/initiatives/conftest.py`（ProjectDoc/BlockMap/Memory + respx fixtures）。

---

## Shared Patterns

### 写入收口（INV-6）
**Source:** `initiatives/services/project_doc_service.py`、`memory_service.py`
**Apply to:** `doc_sync_service.py` 所有 DB 写、新 `ProjectDocBlockRevision`、`ProjectDoc` 新字段
所有 `ProjectDoc`/`ProjectDocBlockMap`/新 revision 写入只经 `ProjectDocService`；MEMORY 条目/revision 只经 `MemoryService`。`doc_sync_service.py` 内**绝不** `Model.objects.create/update_or_create`，否则 `test_doc_sync_inv6_guard` 直接 fail。

### 触发用户归因（CTX-02）
**Source:** `feishu/views.py:1088-1098`（`resolve_feishu_user`）+ `durable/tasks_impl.py:45`（worker 入口 `bind_task_context`）
**Apply to:** drive 事件 normalizer、所有 durable 任务体、scheduler job
入口解析 operator→`initiated_by_user_id`（未映射 `system`）；`defer(..., initiated_by_user_id=...)` 透传；worker 入口 `with bind_task_context(user_id=..., source="durable", component="doc_sync")` 重 bind。

### 脱敏（强制）
**Source:** `common/logging.py::redact_secrets_in_text`（`project_doc_service.py:340/361` 用法）
**Apply to:** 所有飞书正文/上游响应体/异常文本入日志前
日志只记 `doc_id`/`doc_type`/计数/`event` 名/`revision`；**绝不**记正文/token 明文。webhook 原始 payload 经 `record_inbound_webhook`（`views.py:27`）脱敏落库。

### 结构化 structlog 事件（started/completed/failed + duration_ms + category/component）
**Source:** `project_doc_service.py:344-350, 625-635`
**Apply to:** pull/push 生命周期、poll job
事件名 snake_case（`doc_sync_pull_started`/`_completed`/`_failed`），kv 字段；关键生命周期带 `duration_ms`；设 `category`（caller=drive 事件触发 / sampling=高频内部步骤）+ `component="doc_sync"`。高频编辑用 `sampling`+debug 防 INFO 刷屏（Pitfall 7）。

### best-effort 不反噬（fail-soft）
**Source:** `project_doc_service.py:354-366`（`except Exception: noqa BLE001` 记 warning 不抛）
**Apply to:** pull/push 全程、缓存失效、subscribe 注册/退订
同步失败 → 置 `sync_status=broken`（持久化）+ 通知，**绝不**抛回 webhook/编辑主流程。

### async ORM 桥接 + 预取 FK
**Source:** `project_doc_service.py:464-469`（`select_related` 预取）
**Apply to:** pull/push 内所有 ORM 访问
async 上下文 ORM 走 `sync_to_async` + `transaction.atomic` + `select_for_update`；取 project/doc 必须 `select_related` 预取关联（Anti-Pattern：async 裸访问 lazy FK）。

---

## No Analog Found

无完全无分析对象的文件。以下点**无现成同款调用点**，照 RESEARCH 范式实现（非凭空）：

| 点 | Role | 说明 |
|---|---|---|
| read-through 缓存调用点 | service 内 | `django.core.cache` 框架已配（redis/LocMem 自动回退 + `IGNORE_EXCEPTIONS`），但 service 内 `cache.get/set/delete` 调用为净新；照 `83-RESEARCH.md` Code Examples `render_doc_cached` 实现 |
| 三方合并 + capture-never-clobber 算法 | utility | 纯算法净新，无既有同款；落 `doc_sync_diff.py`，结构借 `parse_push_event` 纯函数范式 |
| 飞书 `subscribe_file`/`update_block`/`delete_blocks` 外呼 | service/client | 端点 `[ASSUMED]`（A3/A4），调用骨架镜像 `create_folder`/`_write_regular_blocks`，端点 live-Feishu UAT 后固化 |

---

## Metadata

**Analog search scope:** `server/initiatives/services/`、`server/initiatives/models/` + `migrations/`、`server/services/feishu_doc.py`、`server/durable/`、`server/feishu/`、`server/agents/management/commands/`、`server/tasks/`、`server/tests/{initiatives,feishu,durable}/`
**Files scanned（读源确认签名）:** project_doc_service.py、memory_service.py、project_doc.py、0006 migration、queues.py、tasks.py、tasks_impl.py、service.py（defer）、feishu_doc.py（1-475）、views.py（路由/normalizer 段）、websocket_client.py（grep）、runapscheduler.py（grep + 关键段）、index_trigger_tasks.py、test_project_doc_inv6_guard.py、test_project_doc_service.py
**Pattern extraction date:** 2026-06-26
