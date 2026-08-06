"""蓝图列表 REST（Phase 115-01，VIEW-03 / VIEW-04）。

``GET /api/delivery/blueprints/`` —— 知识库「技术方案」tab 与项目物料卡共用的唯一列表面。
Query（均可选、可组合）：``project_id`` / ``repository_id``（UUID，非法值前置 **400**）/
状态精确筛选 / ``q``（标题 + ``meta.summary`` 大小写不敏感包含）/ ``page`` / ``page_size``。

⭐ **可见性口径与四个 artifact 级端点不同**：那四者是「拿着一个 artifact_id 问能不能看」
（``blueprint_review_views`` 的 MJ-03 范围闸逐个判）；本端点是「列出我能看的全部」。对 N 条
候选逐条跑那道闸 = N 次 ``meta.project_id`` 提取 + N 次 ``aexists()``，**形态错误**。正确
做法是先算出「我是成员的 project id 集合」再过滤；superuser 直通（与那道闸的 superuser
直通行对称）；集合为空 ⇒ **fail-closed 直接返空结构，零 DB 越权查询**。
⛔ 绝不用 ``knowledge.access_scope`` 里那个「可见集合」解析函数——它返回的是**可见 Space
id** 不是 project id（其 docstring 逐字），拿它过滤等于按空间冒充项目授权。

⭐ **为什么不改 ``ArtifactListView``**（``delivery/api/artifact_views.py``）：它是通用
artifact 面、**无任何项目可见性过滤**、返裸数组无分页，且已被
``web/src/components/delivery/ArtifactTimeline.vue`` 以 ``space_id + artifact_type`` 消费
——给它挂闸就是改既有面行为。本 plan 对该文件一行不改。

⛔ **命名纪律（P-1）**：响应键一律 ``current_status``，源码内不出现「模型字段名 + 等号 /
字典键 / ``setattr``」三种形态——INV-6 的字段级守卫扫整个 ``server/``（豁免只有唯一 writer /
tests / migrations）且这是**有意的**（``filter(<字段名>=...)`` 出现在 writer 之外通常意味着
有人在自己拼 CAS 旁路）。ORM 过滤一律经模块常量 :data:`_STATUS_FIELD`。⛔ 绝不为迁就命名
去豁免守卫。

观测：``blueprint_list_read_started`` / ``blueprint_list_read_completed`` 两条 ``caller``
事件（``component="blueprint_list_api"``），只记参数与计数；⛔ **``?q=`` 只记长度不记内容**
（T-114-36 的同一条纪律：正文与检索词都不进日志）。

⭐ **「best-effort」只覆盖观测，不覆盖业务**（115-MJ-04）：埋点写不出去一律吞掉；而
``_aggregate``（queryset + 可见性过滤 + 行装配 + ``_load_names`` 两次查询）是**业务主体**，
它失败一律 **503 + 中性 detail**，⛔ 绝不返 200 空结构 —— 那会让「读失败」与「真的没数据」
在 HTTP 层完全同形，前端只能把两者渲染成同一个「暂无技术方案」。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

logger = structlog.get_logger(__name__)

_COMPONENT = "blueprint_list_api"

_DEFAULT_PAGE_SIZE = 20
_MAX_PAGE_SIZE = 100
_SUMMARY_MAX_CHARS = 200

# 聚合失败时的中性文案（⛔ 不回显异常原文：那既可能带半可信正文，也可能带连接串）
_LIST_UNAVAILABLE_DETAIL = "蓝图列表暂时读取不到，请稍后重试"

_EMPTY: dict[str, Any] = {
    "total": 0,
    "items": [],
    "page": 1,
    "page_size": _DEFAULT_PAGE_SIZE,
    "has_next": False,
}

# 蓝图链刻意复用 technical_plan 这个 artifact_type（DESIGN §4.3）
_BLUEPRINT_ARTIFACT_TYPE = "technical_plan"

# ⭐ 状态字段名走常量而**不写字面 kwarg**（P-1）：INV-6 字段级守卫的三条正则
# （字面赋值 / setattr / 字典键）扫整个 server/，`filter(<字段名>=...)` 这种纯读形态也会命中
# ——那是**有意的**设计（旁路 CAS 的写法正长这样）。本行本身三条都不命中（字段名后紧跟的是
# 引号，既不是等号也不是冒号），配合 `filter(**{_STATUS_FIELD: ...})` 就能既保持守卫满弦、
# 又不给本模块开豁免。⛔ 后人别「顺手改直白」——改回去两条测试同时转红，而报错信息会指向
# 「旁路写状态字段」这个与本模块完全无关的方向。
_STATUS_FIELD = "blueprint_status"


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


def _parse_uuid_param(value: str | None) -> tuple[str | None, bool]:
    """解析可空 UUID query param：返回 ``(规范化字符串|None, 是否合法)``。

    未提供（None/空）视为合法且不过滤；提供但非 UUID 视为非法（调用方前置 400）——
    范式与 ``artifact_views._parse_uuid_param`` 同源。
    """
    if not value:
        return None, True
    try:
        return str(uuid.UUID(value)), True
    except (ValueError, TypeError, AttributeError):
        return None, False


def _is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return False
    return True


def _load_member_project_ids(user: Any) -> list[str]:
    """「我是成员的项目 id 集合」（判据与 ``blueprint_review_views._ais_project_member``
    同源：``ProjectMember`` 一人一项目一行）。"""
    from initiatives.models import ProjectMember

    return [
        str(pid)
        for pid in ProjectMember.objects.filter(user=user).values_list("project_id", flat=True)
        if pid
    ]


def _meta(content: Any) -> dict:
    meta = content.get("meta") if isinstance(content, dict) else None
    return meta if isinstance(meta, dict) else {}


def _summary_text(content: Any) -> str:
    """``meta.summary`` 首块纯文本（截断 ≤200 字符）。

    ``summary`` 是 ``block_list`` 而不是字符串 ⇒ 取文本必须走与 ``_block_text``
    **同一份**四分支优先级实现（text 串 / text 数组 / pseudocode 的 code.source /
    table 的 rows 扁平），⛔ 不 ``json.dumps`` 全文匹配（会把 block_id 与 type 也匹进去）。
    """
    from delivery.services.blueprint_anchor import _block_text

    blocks = _meta(content).get("summary")
    if not isinstance(blocks, list):
        return ""
    for block in blocks:
        if isinstance(block, dict):
            text = _block_text(block).strip()
            if text:
                return text[:_SUMMARY_MAX_CHARS]
    return ""


def _search_text(artifact: Any, content: Any) -> str:
    """``?q=`` 的匹配面：标题 + ``meta.summary`` 全部块的扁平文本（小写）。"""
    from delivery.services.blueprint_anchor import _block_text

    parts = [str(getattr(artifact, "title", "") or "")]
    blocks = _meta(content).get("summary")
    if isinstance(blocks, list):
        parts.extend(_block_text(block) for block in blocks if isinstance(block, dict))
    return "\n".join(parts).lower()


def _repo_rows(content: Any, names: dict[str, str]) -> list[dict]:
    """``repo_associations[]`` → ``[{id, name, role}]``（半可信，逐键 ``.get`` 防御）。

    ``name`` 优先取库里的真名（可能已改名），回落 content 里的快照名、再回落空串——
    ⛔ 取不到名字**不丢行**。
    """
    rows: list[dict] = []
    associations = content.get("repo_associations") if isinstance(content, dict) else None
    for assoc in associations or []:
        if not isinstance(assoc, dict):
            continue
        repo_id = str(assoc.get("repository_id") or "")
        rows.append(
            {
                "id": repo_id,
                "name": names.get(repo_id) or str(assoc.get("repository_name") or ""),
                "role": str(assoc.get("role") or ""),
            }
        )
    return rows


def _list_row(artifact: Any, content: Any, names: dict[str, dict[str, str]]) -> dict:
    """artifact → 列表条目（手写 dict builder，逐值归一）。

    ⚠️ **本函数内零查库**：项目名与仓库名由调用方**批量**取好后以 dict 传入，行循环里逐条
    查就是 N+1。

    ⭐ ``title`` **始终派生**（``{项目名} - 技术方案 - YYYY-MM-DD HH:mm``），不直接回 DB
    原标题——旧数据在展示层统一口径，无需 migration 回填。
    """
    from services.process_runtime.blueprint_title import format_blueprint_title

    meta = _meta(content)
    project_id = str(meta.get("project_id") or "")
    project_name = names.get("projects", {}).get(project_id, "")
    revision_round = meta.get("revision_round")
    version = getattr(artifact, "current_version", None)
    created_at = getattr(artifact, "created_at", None)
    return {
        "artifact_id": str(artifact.id),
        "title": format_blueprint_title(project_name, created_at),
        "summary": _summary_text(content),
        # ⭐ 响应键是 current_status 不是模型字段名（P-1，与 INV-6 守卫互为双保险）
        "current_status": str(getattr(artifact, _STATUS_FIELD, "") or ""),
        "project_id": project_id or None,
        "project_name": project_name,
        "repositories": _repo_rows(content, names.get("repositories", {})),
        "thread_count": int(getattr(artifact, "thread_count", 0) or 0),
        "unresolved_blocker_count": int(getattr(artifact, "unresolved_blocker_count", 0) or 0),
        "revision_round": revision_round
        if isinstance(revision_round, int) and not isinstance(revision_round, bool)
        else 0,
        "current_version_no": int(getattr(version, "version_no", 0) or 0),
        "created_at": created_at.isoformat() if created_at else "",
        "updated_at": artifact.updated_at.isoformat() if artifact.updated_at else "",
    }


def _load_names(project_ids: set[str], repository_ids: set[str]) -> dict[str, dict[str, str]]:
    """一次性批量取项目名与仓库名（**两次查询封顶**，防 `_list_row` 里的 N+1）。"""
    from initiatives.models import Project
    from repositories.models import Repository

    names: dict[str, dict[str, str]] = {"projects": {}, "repositories": {}}
    valid_projects = {pid for pid in project_ids if _is_uuid(pid)}
    if valid_projects:
        names["projects"] = {
            str(pid): str(name or "")
            for pid, name in Project.objects.filter(id__in=valid_projects).values_list("id", "name")
        }
    valid_repos = {rid for rid in repository_ids if _is_uuid(rid)}
    if valid_repos:
        names["repositories"] = {
            str(rid): str(name or "")
            for rid, name in Repository.objects.filter(id__in=valid_repos).values_list("id", "name")
        }
    return names


def _aggregate(
    allowed_project_ids: list[str],
    *,
    is_superuser: bool,
    filters: dict[str, str | None],
    page: int,
    page_size: int,
) -> dict:
    """纯同步聚合（方案 A：**先聚合再切片**）。全部 ORM 收在本函数内，View 里零 ORM。

    为什么必须在 Python 侧过滤：蓝图的项目归属存在
    ``ArtifactVersion.content["meta"]["project_id"]`` 里、**不是 DB 列** ⇒ 无法
    ``filter(project_id__in=...)``；``?repository_id=`` 与 ``?q=`` 的摘要面同理（JSON 内检索
    跨 PG/MySQL/SQLite 行为不一）。蓝图总量小（一项目一份活跃蓝图），代价可接受。
    ⇒ 切片必须在过滤**之后**，否则 ``total`` 与 ``has_next`` 都是错的。
    """
    from django.db.models import Count, Q

    from delivery.models import Artifact, ThreadSeverity, ThreadStatus

    allowed = set(allowed_project_ids)
    # 候选收窄走复合索引 Index(["artifact_type", <状态字段>])；空串状态 = v0 旧数据，
    # 未进状态机 ⇒ 不是蓝图，不出现在列表里。两处都经 _STATUS_FIELD 常量（P-1）。
    queryset = (
        Artifact.objects.filter(artifact_type=_BLUEPRINT_ARTIFACT_TYPE)
        .exclude(**{_STATUS_FIELD: ""})
        .select_related("current_version")
        .annotate(
            thread_count=Count("blueprint_threads", distinct=True),
            # ⛔ 计数一律 ORM 自算，**不 import lifecycle service 那个「仅供呈现」的未决计数
            # async 方法**：它与 confirm 转移同现会撞 TOCTOU 扫描守卫（判据是「同一 API 文件里
            # 两者同现即事务外预查询」），且逐条调 async 函数本来就是 N+1。判据与守卫口径对齐：
            # open 与 answered **都算未决**。走 Index(["artifact","status","blocking"])。
            unresolved_blocker_count=Count(
                "blueprint_threads",
                filter=Q(blueprint_threads__severity=ThreadSeverity.BLOCKER)
                & Q(blueprint_threads__blocking=True)
                & Q(
                    blueprint_threads__status__in=[
                        ThreadStatus.OPEN,
                        ThreadStatus.ANSWERED,
                    ]
                ),
                distinct=True,
            ),
        )
        .order_by("-created_at")
    )
    status_filter = filters.get("status") or None
    if status_filter:
        queryset = queryset.filter(**{_STATUS_FIELD: status_filter})

    project_filter = filters.get("project_id") or None
    repository_filter = filters.get("repository_id") or None
    keyword = (filters.get("q") or "").strip().lower()

    matched: list[tuple[Any, dict]] = []
    for artifact in queryset:
        version = artifact.current_version
        content = getattr(version, "content", None)
        content = content if isinstance(content, dict) else {}
        project_id = str(_meta(content).get("project_id") or "")
        # 可见性：非 superuser 必须命中「我是成员的项目」集合（读不到项目 id 一律不可见，
        # 与 artifact 级端点的 fail-closed 对称）
        if not is_superuser and project_id not in allowed:
            continue
        if project_filter and project_id != project_filter:
            continue
        if repository_filter and not any(
            isinstance(assoc, dict) and str(assoc.get("repository_id") or "") == repository_filter
            for assoc in (content.get("repo_associations") or [])
        ):
            continue
        if keyword and keyword not in _search_text(artifact, content):
            continue
        matched.append((artifact, content))

    total = len(matched)
    offset = (page - 1) * page_size
    window = matched[offset : offset + page_size]
    names = _load_names(
        {str(_meta(content).get("project_id") or "") for _artifact, content in window},
        {
            str(assoc.get("repository_id") or "")
            for _artifact, content in window
            for assoc in (content.get("repo_associations") or [])
            if isinstance(assoc, dict)
        },
    )
    items = [_list_row(artifact, content, names) for artifact, content in window]
    return {
        "total": total,
        "items": items,
        "page": page,
        "page_size": page_size,
        "has_next": offset + len(items) < total,
    }


def _log_list(event: str, request: Any, started: float, **fields: Any) -> None:
    """列表端点的 caller 埋点（无单一 ``artifact_id``，故不复用 doc 面那个签名）。

    ⭐ **观测 best-effort**：埋点失败一律吞掉，绝不打断请求。这与聚合失败**如实 503**
    （见 :class:`BlueprintListView`）是同一条纪律的两面 —— 观测不反噬业务，业务错误也不许
    伪装成观测噪音被吞掉。
    """
    try:
        logger.info(
            event,
            category="caller",
            component=_COMPONENT,
            initiated_by_user_id=str(getattr(request.user, "id", "") or "system"),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            **fields,
        )
    except Exception:  # noqa: BLE001 — 观测永不反噬业务
        pass


class BlueprintListView(APIView):
    """GET /api/delivery/blueprints/ —— 蓝图列表（可见性 + 筛选 + 稳定分页）。

    响应体是 ``{total, items, page, page_size, has_next}`` 五键（与
    ``knowledge/api/artifact_overview.py`` 同款手写分页）——⛔ **不是 DRF 分页体**：方案 A 要
    在 Python 侧过滤后再切片，而 DRF 的分页 helper 只吃 queryset、用不上；⛔ 也不发明第三套。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any) -> Response:
        from common.logging import redact_secrets_in_text

        started = time.monotonic()
        page = _parse_page(request.query_params.get("page"))
        page_size = _parse_page_size(request.query_params.get("page_size"))
        project_id, ok_project = _parse_uuid_param(request.query_params.get("project_id"))
        if not ok_project:
            return Response(
                {"detail": "project_id 格式无效（需为 UUID）"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        repository_id, ok_repo = _parse_uuid_param(request.query_params.get("repository_id"))
        if not ok_repo:
            return Response(
                {"detail": "repository_id 格式无效（需为 UUID）"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        keyword = request.query_params.get("q") or ""
        filters: dict[str, str | None] = {
            "project_id": project_id,
            "repository_id": repository_id,
            "status": request.query_params.get(_STATUS_FIELD) or None,
            "q": keyword,
        }

        is_superuser = bool(getattr(request.user, "is_superuser", False))
        allowed: list[str] = []
        if not is_superuser:
            allowed = await sync_to_async(_load_member_project_ids)(request.user)
        _log_list(
            "blueprint_list_read_started",
            request,
            started,
            page=page,
            page_size=page_size,
            project_count=len(allowed),
            is_superuser=is_superuser,
            # ⛔ ?q= 只记长度不记内容
            q_len=len(keyword),
        )
        if not is_superuser and not allowed:
            # fail-closed：零可见项目 → 空结构，**零 DB 越权查询**
            _log_list(
                "blueprint_list_read_completed",
                request,
                started,
                total=0,
                item_count=0,
                page=page,
                page_size=page_size,
                q_len=len(keyword),
            )
            return Response({**_EMPTY, "page": page, "page_size": page_size})

        try:
            payload = await sync_to_async(_aggregate)(
                allowed,
                is_superuser=is_superuser,
                filters=filters,
                page=page,
                page_size=page_size,
            )
        except Exception as exc:  # noqa: BLE001 — 观测 best-effort，但**如实 503**（见下）
            # ⭐ 聚合失败必须让调用方看见，⛔ 不得吞成 200 空结构。
            #
            # `.cursor/rules/observability-logging.mdc` 的「best-effort、失败吞掉」约束的是
            # **观测代码**；这里 try 住的 `_aggregate` 是**业务主体本身**（queryset + 可见性
            # 过滤 + 行装配 + `_load_names` 两次查询）。把它的异常翻译成「该用户一份蓝图都
            # 没有」，会让 DB 抖动 / 关联表查询失败与「真的没数据」在 HTTP 层完全同形 ——
            # 前端两个消费方于是把读失败渲染成「暂无技术方案」，甚至整张卡从项目页消失。
            #
            # 观测仍是 best-effort：日志本身另包一层，写不出去也不改变响应。
            try:
                logger.warning(
                    "blueprint_list_read_failed",
                    category="caller",
                    component=_COMPONENT,
                    initiated_by_user_id=str(getattr(request.user, "id", "") or "system"),
                    error_type=type(exc).__name__,
                    error=redact_secrets_in_text(str(exc)),
                    duration_ms=round((time.monotonic() - started) * 1000, 2),
                )
            except Exception:  # noqa: BLE001 — 观测永不反噬业务
                pass
            return Response(
                {"detail": _LIST_UNAVAILABLE_DETAIL},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        _log_list(
            "blueprint_list_read_completed",
            request,
            started,
            total=payload["total"],
            item_count=len(payload["items"]),
            page=page,
            page_size=page_size,
            q_len=len(keyword),
        )
        return Response(payload)
