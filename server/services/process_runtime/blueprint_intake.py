"""blueprint_intake —— 蓝图链的**生产起点**（Phase 116-02，GATE-01）。

四段契约（改动前先读）：

1. **用途**：建初始 ``Artifact`` + 落一份过得了 ``validate_blueprint`` 的
   ``blueprint/v1`` 骨架版本 + 把 ``blueprint_status`` 跳到 ``researching``。
   本模块之前**全仓没有任何代码**做这件事：``ArtifactService.create`` 的调用者只有
   ``architect_merge_adapter.py``（旧链 merge）与 ``builtin_processes.py``（echo 测试
   链），蓝图链零调用 ⇒ 蓝图至今只在测试里被预置产物驱动过。

2. **INV-6 声明**：``blueprint_status`` 的跳转一律经
   ``BlueprintLifecycleService.transition``，本模块**零裸写** ``blueprint_status``
   （既无字面赋值、无 ``setattr`` 形态、也无同名字典键形态 —— 三条正则见
   ``tests/delivery/test_blueprint_inv6_guard.py:57-62``）。
   ⛔ 本模块**不**进 ``test_blueprint_inv6_guard._ALLOWED_WRITER`` —— 唯一 writer 必须
   保持是 ``delivery/services/blueprint_lifecycle_service.py``。

3. ⭐ **三条「漏了会静默假通过」**（本模块存在的理由）：

   a. **content 缺 ``schema_version`` ⇒ 三条链同时静默降级**（P-2）。
      ``validate_blueprint`` 对缺该键的 content 返回 **``(True, None)``**（pass-through
      保 v0 零迁移），而 ``builtin_types._validate_technical_plan`` 的判别式是
      ``if content.get("schema_version")`` ⇒ 漏写会让校验器走 v0、渲染器走 v0 空壳、
      入图门控**永不触发**，三条链零异常。故 :func:`build_skeleton` 的该键取自
      **懒 import 的** ``BLUEPRINT_SCHEMA_VERSION``（MN-10：⛔ 本模块不复制那个字符串
      字面量），且用例断言的是**落库版本**的 ``content["schema_version"]``。
   b. **``StageOutcome`` 不带 ``current_artifact_version`` ⇒ 会话卡死在 spec_gate**。
      ``engine.py:108-119`` 只在非 None 时透传（无条件透传会把每次不产版本的转移都把
      指针抹成 NULL）；不传 ⇒ 会话上那个版本指针字段恒 None ⇒
      ``blueprint_spec_gate`` 取不到版本即判 ``needs_clarification`` +
      ``blueprint_spec_gate_no_artifact_version`` warning。调用方（handler）必须显式带回。
   c. **MCP 的 ``McpWorkItemContext.space`` 是 ``projects.Space`` FK 不是 Project id**
      （P-8）。``mcp_tools/technical_plan_service.py:488`` 把它当 ``"project_id"`` 键回给
      调用方；直接透传会落一份 ``meta.project_id`` 为 Space id 的蓝图 —— 它的**全部 20
      个端点恒 400、图谱恒不入、导出恒不可用**，三条都「安静地什么都没发生」且没有任何
      补救入口。故 :func:`aresolve_project_id` 是四条推导链的**唯一收口**，MCP 分支必过
      ``board_split_review._aresolve_project``，推不出即抛
      :class:`BlueprintIntakeRejected`（⛔ 不建会话、不建 artifact）。

4. **观测**：结构化五件套（事件名 snake_case + ``category`` + ``component`` +
   ``duration_ms`` + 触发用户）。⛔ **需求原文/功能点标题正文绝不进日志**，只记
   ``goal_len`` / ``point_count`` 之类的标量。本模块在
   ``tests/delivery/test_blueprint_log_redaction_guard._SCANNED_MODULES`` 之内 ⇒ 任何
   ``error=`` 实参必须经 ``redact_secrets_in_text``。
"""

from __future__ import annotations

import copy
import time
import uuid
from typing import Any

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

_COMPONENT = "blueprint_intake"

__all__ = [
    "GOAL_BLOCK_ID",
    "MINIMAL_BLUEPRINT_SKELETON",
    "FEATURE_POINT_INTENTS",
    "DEFAULT_FEATURE_POINT_INTENT",
    "BlueprintIntakeRejected",
    "build_skeleton",
    "aresolve_project_id",
    "aseed_blueprint_artifact",
    "adecompose_feature_points",
]

# 骨架里承载需求原文的那个 block 的 id（`iter_blocks` 走查 `requirement_spec.goal`
# 时产出 `('requirement_spec.goal', GOAL_BLOCK_ID)`，111-01 的点分 + [标识] 约定）。
GOAL_BLOCK_ID = "bp_goal_1"

# 截断上界：title 进 `Artifact.title`（max_length=500），goal 正文是半可信输入。
# 缺省标题为「{项目名} - 技术方案 - YYYY-MM-DD HH:mm」，200 足以容纳长项目名且不裁掉时间后缀。
_MAX_TITLE_CHARS = 200
_MAX_GOAL_CHARS = 4000
# 推不出 project_id 时回给四个入口的**中性** detail（⛔ 不含内部路径/异常原文）
_PROJECT_UNRESOLVED_DETAIL = "无法确定该需求所属的项目，请在项目空间内发起或补全项目信息"

# 骨架缺省文案（`meta.title` / `requirement_spec.goal[0].text` 的 minLength 兜底：
# schema 要求 title 非空；goal 为空会让规格门 `_goal_text` 拿不到输入而 fail-closed
# 到满歧义，第一轮必然开一堆无意义澄清线程）。
_DEFAULT_TITLE = "未命名技术蓝图"
_DEFAULT_GOAL_TEXT = "（需求原文缺失，待澄清）"

# `requirement_spec.feature_points[].intent` 的 schema 枚举（`blueprint_schema.py:191-194`）。
FEATURE_POINT_INTENTS: frozenset[str] = frozenset({"greenfield", "brownfield", "fix"})
# feature list 直采路径的缺省 intent：feature list 条目的产品语义就是「要做的新功能点」，
# 真实的 greenfield/brownfield 判定由后续 spec_gate 的意图分类（`BLUEPRINT_SPEC_GATE`）
# 精化。⛔ 这里不猜、不调 LLM —— 直采路径的全部价值就在于「零 LLM 且重跑不翻版本」。
DEFAULT_FEATURE_POINT_INTENT = "greenfield"

# 功能点拆分的规模上界（LLM 产出与直采同用；防一次拆出上千条把 content 撑爆）
_MAX_FEATURE_POINTS = 200
_MAX_FP_TITLE_CHARS = 200
_MAX_FP_DESC_CHARS = 1000


def _schema_version() -> str:
    """懒 import 取权威 schema 版本常量（MN-10：⛔ 本模块不复制那个字符串字面量）。

    复制字面量的代价是 P-2 的静默降级：schema 演进时本模块会继续写旧值，而
    ``validate_blueprint`` 对「不等于当前版本」的 content 走 pass-through 返
    ``(True, None)`` —— 校验、渲染、入图门控三条链同时降级且零异常。
    """
    from services.process_runtime.blueprint_schema import BLUEPRINT_SCHEMA_VERSION

    return BLUEPRINT_SCHEMA_VERSION


# ⭐ blueprint/v1 的**最小合法骨架**：`blueprint_schema.py:123-135` 的 11 个必填顶层键
# 逐字齐全。§A.2 已 `.venv` 实跑八变体：六段全部允许空数组/空对象，`meta.title` 与
# `meta.project_id` 是仅有的两个必须有真实值的字段。
#
# ⛔ **绝不直接把本常量当 content 用**（`meta` 两个必填值是空串、goal 为空）——一律经
# :func:`build_skeleton` 深拷贝后填位，否则既过不了校验、又会让调用方共享同一份可变对象。
MINIMAL_BLUEPRINT_SKELETON: dict[str, Any] = {
    "schema_version": _schema_version(),
    "meta": {
        "title": "",
        "project_id": "",
        "summary": [],
        "language": "zh-CN",
        "revision_round": 0,
    },
    "requirement_spec": {"goal": [], "feature_points": []},
    "repo_associations": [],
    "current_state_analysis": [],
    "implementation_overview": {"requirement_narrative": [], "items": []},
    "api_contracts": [],
    "impact_analysis": {"business_impact": [], "affected_features": []},
    "interaction_flows": [],
    "must_haves": {"truths": [], "artifacts": [], "key_links": []},
    "citations": {},
}


class BlueprintIntakeRejected(Exception):
    """蓝图发起被拒（**会话与 artifact 都尚未建立**时抛，零副作用）。

    ``reason`` 是给日志/聚合用的稳定枚举串（当前唯一取值 ``project_unresolved``），
    ``detail`` 是可直接回显给用户的中性文案（⛔ 不含内部路径、异常原文、id 之外的内部
    状态）。四个入口各自的错误出口由 116-03 映射：工作流
    ``NodeResult(status="failed", next_handle="error")`` / chat
    ``ToolResult(success=False, error=detail)`` / MCP ``error_response(code, detail)``。
    """

    def __init__(self, *, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail or _PROJECT_UNRESOLVED_DETAIL
        super().__init__(self.detail)


def build_skeleton(*, title: str, project_id: str, goal_text: str) -> dict:
    """产出一份**独立的**最小 blueprint/v1 content（深拷贝常量后填三个位）。

    三个位：``meta.title`` / ``meta.project_id`` / ``requirement_spec.goal`` 的
    paragraph block（承载需求原文）。返回值与 :data:`MINIMAL_BLUEPRINT_SKELETON`
    及彼此之间**无共享可变对象**（连调两次互不影响，有单测背书）。
    """
    content = copy.deepcopy(MINIMAL_BLUEPRINT_SKELETON)
    content["schema_version"] = _schema_version()
    content["meta"]["title"] = str(title or "").strip()[:_MAX_TITLE_CHARS] or _DEFAULT_TITLE
    content["meta"]["project_id"] = str(project_id or "")
    content["requirement_spec"]["goal"] = [
        {
            "block_id": GOAL_BLOCK_ID,
            "type": "paragraph",
            "text": str(goal_text or "").strip()[:_MAX_GOAL_CHARS] or _DEFAULT_GOAL_TEXT,
        }
    ]
    return content


def _first_line(text: str) -> str:
    """取首个非空行（``Artifact.title`` 的缺省取值口径）。"""
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _is_uuid(value: Any) -> bool:
    """字符串是否是合法 UUID（``meta.project_id`` 落 Space id 之外的第二道形状闸）。"""
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


async def _aproject_exists(project_id: str) -> bool:
    """该 id 是否真的是一条 ``initiatives.Project``（⛔ 不接受「非空即可」）。"""
    from initiatives.models import Project

    return await Project.objects.filter(id=project_id).aexists()


async def _aproject_id_from_space(space: Any) -> str:
    """Space → Project.id 的**唯一换算**（复用 ``board_split_review._aresolve_project``）。

    ⛔ 绝不在本仓写第二份 Space→Project 换算：``_aresolve_project`` 的语义是「优先
    ``feishu_project_key`` 命中、否则该 space 下首个 Project」，``plan_research
    ._send_clarify_card:470`` 已是这个用法，两份实现漂移会让同一 space 在不同入口解析
    到不同项目。
    """
    if space is None:
        return ""
    from workflows.nodes.integrations.board_split_review import _aresolve_project

    project = await _aresolve_project(space)
    return str(getattr(project, "id", "") or "")


async def _aload_space(space_id: Any) -> Any:
    """``space_id`` → ``projects.Space`` 行（取不到返 None）。"""
    if not space_id:
        return None
    from projects.models import Space

    return await Space.objects.filter(id=space_id).afirst()


async def aresolve_project_id(
    *,
    entry: str,
    space: Any = None,
    feature_meta: dict | None = None,
    conversation: Any = None,
    work_item_context: Any = None,
) -> str:
    """⭐ 四条入口链推导 ``meta.project_id`` 的**唯一收口**（116-03 直接 import 复用）。

    ``meta.project_id`` 是全链范围闸、SC-4 图谱边与 space 归属、导出可用性的**唯一来源**；
    写错即三条防线同时失效且**不报错**。故四个入口**绝不各写一份推导**。

    ============  =====================================  ==============================
    入口           权威上下文                              换算
    ============  =====================================  ==============================
    feature_list  ``feature_meta["project_id"]``          已是 Project id，仍校验 UUID +
                                                          ``Project`` 存在
    workflow      ``space``（工作流关联空间）              ``_aresolve_project(space)``
    chat          ``conversation.bound_project_id``        已是 Project id；否则
                  / ``conversation.space``                 ``_aresolve_project(space)``
    mcp           ``work_item_context.space``              ⭐ 先取 ``Space`` 再过
                  （``projects.Space`` **FK**）             ``_aresolve_project``
    ============  =====================================  ==============================

    ⭐ **MCP 那条是本函数存在的首要理由**（P-8）：``mcp_tools/technical_plan_service.py:488``
    把 ``McpWorkItemContext.space_id`` 当 ``"project_id"`` 键回给调用方 —— 那是 **Space id
    不是 Project id**。透传即落一份「20 个端点恒 400、图谱恒不入、导出恒不可用」且无补救
    入口的蓝图。本函数对该分支**只**返回 ``_aresolve_project`` 换算出来的 Project id。

    Returns:
        非空 Project id 字符串。

    Raises:
        BlueprintIntakeRejected: 四条链都推不出 ⇒ ``reason="project_unresolved"``。
            调用方（``start_blueprint_orchestration``）在**建会话之前**调用本函数，
            故抛出时**零副作用**：⛔ 不建 session、⛔ 不建 artifact。
    """
    started = time.monotonic()
    entry_key = str(entry or "unknown")
    source = ""
    project_id = ""

    # ① feature list：feature_meta.project_id 已是 Project id，但仍要校验形状与存在性
    #    （坏 id 落进 content 与推不出一样致命，且没有补救入口）。
    meta_pid = str((feature_meta or {}).get("project_id") or "").strip()
    if meta_pid and _is_uuid(meta_pid) and await _aproject_exists(meta_pid):
        project_id, source = meta_pid, "feature_meta"

    # ② workflow / 显式 space：Space → Project 唯一换算。
    if not project_id and space is not None:
        project_id, source = await _aproject_id_from_space(space), "space"

    # ③ MCP：context.space 是 projects.Space FK（`mcp_tools/models.py:276-282`），而
    #    `mcp_tools/technical_plan_service.py:488` 把 space_id 当 "project_id" 键回传 ——
    #    ⛔ 绝不把 space_id 当 project id 返回，必须先取 Space 再过 _aresolve_project。
    if not project_id and work_item_context is not None:
        ctx_space = getattr(work_item_context, "space", None)
        if ctx_space is None:
            ctx_space = await _aload_space(getattr(work_item_context, "space_id", None))
        project_id, source = await _aproject_id_from_space(ctx_space), "mcp_context_space"

    # ④ chat：优先会话显式绑定的项目，否则回落会话所属空间。
    if not project_id and conversation is not None:
        bound = str(getattr(conversation, "bound_project_id", "") or "")
        if bound and await _aproject_exists(bound):
            project_id, source = bound, "conversation_bound_project"
        else:
            conv_space = await _aload_space(getattr(conversation, "space_id", None))
            project_id, source = await _aproject_id_from_space(conv_space), "conversation_space"

    duration_ms = round((time.monotonic() - started) * 1000, 2)
    if not project_id:
        logger.warning(
            "blueprint_intake_project_unresolved",
            category="caller",
            component=_COMPONENT,
            entry=entry_key,
            reason="project_unresolved",
            duration_ms=duration_ms,
        )
        raise BlueprintIntakeRejected(
            reason="project_unresolved", detail=_PROJECT_UNRESOLVED_DETAIL
        )

    logger.info(
        "blueprint_intake_project_resolved",
        category="caller",
        component=_COMPONENT,
        entry=entry_key,
        project_id=project_id,
        source=source,
        duration_ms=duration_ms,
    )
    return project_id


async def aseed_blueprint_artifact(
    *,
    session: Any,
    requirement_text: str,
    project_id: str,
    title: str = "",
    created_by_user_id: str = "",
) -> Any:
    """建蓝图初始 ``Artifact`` + ``blueprint/v1`` v1 骨架版本 + 跳 ``researching``。

    三件产出缺一不可：

    1. 一条 ``artifact_type = "technical_plan"`` 的交付物经 ``ArtifactService.create``
       建成 —— ⛔ **不是那条「加版本」方法**：此刻 artifact 还不存在，``create`` 自己建
       交付物行 + v1 并置 ``current_version``（``artifact_service.py:53-84`` /
       ``:105-115``）。
    2. ``blueprint_status`` 经 ``BlueprintLifecycleService.transition`` 跳到
       ``researching``（状态机入口边只有 ``"" → researching``；形状逐字照
       ``builtin_processes._abp_mark_drafting``，best-effort 包裹 —— 状态映射是展示面，
       映射失败绝不阻断编排）。
    3. 返回 ``artifact``，供 handler 把 ``artifact.current_version_id`` 放进
       ``StageOutcome.current_artifact_version``（不放则会话卡死在 spec_gate）。

    ⚠️ ``ArtifactService.create`` 内部**先跑 ``validate_content``，不过就抛
    ``ArtifactContentInvalid``** ⇒ 骨架形状错会**响亮失败**而不是静默落一份坏 content。
    ⛔ **不要在外面包 try 吞掉它**（那正是 P-2 那类静默降级的温床）。
    """
    from delivery.artifacts.builtin_types import ARTIFACT_TYPE_TECHNICAL_PLAN
    from delivery.services.artifact_service import ArtifactService
    from django.utils import timezone

    from services.process_runtime.blueprint_title import format_blueprint_title

    started = time.monotonic()
    goal_text = str(requirement_text or "")
    # 显式非空 title 仍尊重调用方；缺省改为「{项目名} - 技术方案 - YYYY-MM-DD HH:mm」。
    explicit = str(title or "").strip()
    if explicit:
        resolved_title = explicit
    else:
        project_name = ""
        try:
            from initiatives.models import Project

            project_name = str(
                await Project.objects.filter(id=project_id).values_list("name", flat=True).afirst()
                or ""
            )
        except Exception:  # noqa: BLE001 — 查名失败不阻断 seeding，前缀回落「未关联项目」
            project_name = ""
        resolved_title = format_blueprint_title(project_name, timezone.now())
    content = build_skeleton(title=resolved_title, project_id=project_id, goal_text=goal_text)

    artifact = await ArtifactService().create(
        ARTIFACT_TYPE_TECHNICAL_PLAN,
        content,
        title=content["meta"]["title"],
        produced_by_session_id=str(getattr(session, "id", "") or ""),
        produced_by_ref="blueprint_intake",
        created_by_user_id=created_by_user_id or "",
    )
    await _amark_researching(artifact, session)

    logger.info(
        "blueprint_intake_seeded",
        category="caller",
        component=_COMPONENT,
        session_id=str(getattr(session, "id", "") or ""),
        artifact_id=str(artifact.id),
        project_id=str(project_id or ""),
        version_no=1,
        goal_len=len(goal_text),
        initiated_by_user_id=str(getattr(session, "initiated_by_user_id", "") or "") or "system",
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )
    return artifact


async def _amark_researching(artifact: Any, session: Any) -> None:
    """把蓝图状态跳到 ``researching``（INV-6 唯一写口，形状照 ``_abp_mark_drafting``）。

    best-effort：状态映射是展示面，跳转失败绝不阻断编排（artifact 与 v1 骨架已落库，
    后续 ``_abp_mark_drafting`` 会在阶段 2/3 补跳 ``"" → researching → drafting``）。
    """
    from delivery.models import BlueprintStatus
    from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

    try:
        if str(getattr(artifact, "blueprint_status", "") or ""):
            return
        initiated_by = str(getattr(session, "initiated_by_user_id", "") or "") or "system"
        await BlueprintLifecycleService().transition(
            artifact,
            BlueprintStatus.RESEARCHING,
            initiated_by_user_id=initiated_by,
            session=session,
        )
    except Exception as exc:  # noqa: BLE001 — 状态映射是展示面，绝不阻断编排
        logger.warning(
            "blueprint_intake_status_map_skipped",
            category="sampling",
            component=_COMPONENT,
            artifact_id=str(getattr(artifact, "id", "")),
            error=redact_secrets_in_text(str(exc)),
        )


# ══════════════════════════════════════════════════════════════════════════
# 功能点拆分（decompose stage 的落地实现）
# ══════════════════════════════════════════════════════════════════════════


def _feature_point_id(index: int) -> str:
    """⭐ **确定性** feature_point id（``fp_1`` / ``fp_2`` …，按输入顺序）。

    ⛔ **绝不用随机 uuid**：``feature_points`` 有重复 id 校验（``validate_blueprint`` 后置
    检查 e），而随机 id 会让**每次重跑都翻一个新版本**，把版本历史刷成噪声、diff 视图
    不可用（T-116-14；114-04 已为时间戳立过同款纪律）。确定性 id ⇒ 同一 segments 重跑得
    同一份 content ⇒ ``content_hash`` 相等 ⇒ ``add_version`` 复用 current 不翻版本。
    """
    return f"fp_{index + 1}"


def _normalize_intent(value: Any) -> str:
    """把任意输入收敛到 schema 枚举内（不在枚举内一律落缺省值，⛔ 不外抛）。"""
    text = str(value or "").strip().lower()
    return text if text in FEATURE_POINT_INTENTS else DEFAULT_FEATURE_POINT_INTENT


def _points_from_segments(segments: list[dict]) -> list[dict]:
    """``feature_segments`` → ``requirement_spec.feature_points``（**零 LLM** 直采）。

    映射表（116-03 的 feature list 入口据它传参）：

    ==================  =========================================================
    segment 字段         feature_point 字段
    ==================  =========================================================
    （位序 index）       ``id`` = :func:`_feature_point_id`（``fp_{index+1}``）
    ``title``            ``title``（截断；空条目整条丢弃 —— schema 要求非空）
    ``intent`` （可选）  ``intent``（不在枚举内落 :data:`DEFAULT_FEATURE_POINT_INTENT`）
    ``module``/``layer`` ``description``：一个 paragraph block，``block_id``
                         = ``fp_{n}_desc_1``（确定性，重跑同值）
    ==================  =========================================================
    """
    points: list[dict] = []
    for index, segment in enumerate(segments[:_MAX_FEATURE_POINTS]):
        if not isinstance(segment, dict):
            continue
        title = str(segment.get("title") or "").strip()[:_MAX_FP_TITLE_CHARS]
        if not title:
            continue
        point_id = _feature_point_id(len(points))
        point: dict[str, Any] = {
            "id": point_id,
            "title": title,
            "intent": _normalize_intent(segment.get("intent")),
        }
        parts = [
            str(segment.get(key) or "").strip() for key in ("module", "layer") if segment.get(key)
        ]
        if parts:
            point["description"] = [
                {
                    "block_id": f"{point_id}_desc_1",
                    "type": "paragraph",
                    "text": " / ".join(parts)[:_MAX_FP_DESC_CHARS],
                }
            ]
        points.append(point)
    return points


def _decompose_system_prompt() -> str:
    return (
        "你是技术蓝图的需求拆分助手。用户会给你一段需求原文，请把它拆成互不重叠的功能点。\n"
        "要求：① 每个功能点是一句可独立验收的能力描述；② 不要发明需求里没有的功能；"
        "③ intent 三选一：greenfield（净新增）/ brownfield（存量改造）/ fix（缺陷修复），"
        "判不出就填 greenfield；④ 严格输出 JSON："
        '{"items": [{"title": "功能点标题", "intent": "greenfield"}]}'
    )


async def _allm_feature_points(session: Any, requirement_text: str) -> list[dict] | None:
    """LLM 拆分功能点；**任何不可得情形返回 ``None``**（⛔ 不抛、⛔ 不落 FAILED）。

    复用**已注册**的 ``CallSource.BLUEPRINT_DECOMPOSE``（``agents/call_source.py:112``）——
    ⛔ 零新增枚举（清单锁 ``tests/test_model_usage_call_source.py:77``）。
    """
    session_id = str(getattr(session, "id", "") or "")
    try:
        import json
        import re

        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.call_source import CallSource, use_call_source
        from agents.llm_factory import build_chat_model
        from services.provider_config import ProviderConfigService

        resolved = await ProviderConfigService.aresolve()
        model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
        if not model_name:
            return None

        model = build_chat_model(resolved, model_name, streaming=False)
        messages = [
            SystemMessage(content=_decompose_system_prompt()),
            HumanMessage(content=f"## 需求原文\n{requirement_text[:_MAX_GOAL_CHARS]}"),
        ]
        with use_call_source(CallSource.BLUEPRINT_DECOMPOSE):
            response = await model.ainvoke(messages)

        raw = getattr(response, "content", "")
        text = raw if isinstance(raw, str) else str(raw or "")
        candidates = re.findall(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL) + [text]
        for block in candidates:
            try:
                data = json.loads(block.strip())
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                return [item for item in data["items"] if isinstance(item, dict)]
        return None
    except Exception as exc:  # noqa: BLE001 — fail-soft：上游抖动绝不废掉整条蓝图
        logger.warning(
            "blueprint_decompose_llm_failed",
            category="sampling",
            component=_COMPONENT,
            session_id=session_id,
            error=redact_secrets_in_text(str(exc)),
        )
        return None


async def _aload_latest_content(artifact: Any) -> tuple[dict, Any]:
    """取**最新** ``version_no`` 的 content 与该版本（⛔ 绝不读 ``session`` 钉住的那一版）。

    STATE 114-04 纪律：上游 ``add_version`` 已推进 ``current_version``，而 session 钉住的
    那一版只在显式 ``StageOutcome`` 里才更新 —— 读 session 那一版会把上游成果覆盖回旧内容。
    """
    from delivery.models import ArtifactVersion

    version = await (
        ArtifactVersion.objects.filter(artifact=artifact).order_by("-version_no").afirst()
    )
    content = getattr(version, "content", None)
    return (copy.deepcopy(content) if isinstance(content, dict) else {}), version


async def adecompose_feature_points(
    *,
    session: Any,
    artifact: Any,
    requirement_text: str,
    feature_segments: list[dict] | None = None,
) -> Any:
    """把需求拆成 ``requirement_spec.feature_points`` 并落新版本；**无变化返 ``None``**。

    两条路径：

    - **(a) ``feature_segments`` 非空 ⇒ 直接映射，⛔ 零 LLM**（feature list 入口）。
      映射表与确定性 id 规则见 :func:`_points_from_segments` / :func:`_feature_point_id`。
      重跑得同一份 content ⇒ ``content_hash`` 相等 ⇒ ``add_version`` 复用 current ⇒
      本函数返 ``None``（无版本噪声）。
    - **(b) 否则走 LLM**（复用 ``CallSource.BLUEPRINT_DECOMPOSE``，⛔ 零新增枚举）。
      ⭐ **LLM 不可得 / 解析失败 ⇒ fail-soft**：保留空 ``feature_points``、记一条
      ``blueprint_decompose_unavailable`` warning，**⛔ 不抛、⛔ 不落 FAILED** —— 规格门
      本就会因信息不足而开澄清，那才是正确的下一步；一次上游抖动不该废掉整条蓝图。

    Returns:
        新 ``ArtifactVersion``（本次真的翻了版本）；``None`` = 未产版本（无 artifact /
        无基线版本 / 内容无实质变化 / 拆不出任何功能点）。
    """
    from delivery.services.artifact_service import ArtifactContentInvalid, ArtifactService

    started = time.monotonic()
    session_id = str(getattr(session, "id", "") or "")
    if artifact is None:
        return None

    segments = [s for s in (feature_segments or []) if isinstance(s, dict)]
    dropped = 0
    if segments:
        source = "feature_segments"
        points = _points_from_segments(segments)
        dropped = len(segments) - len(points)
    else:
        source = "llm"
        items = await _allm_feature_points(session, str(requirement_text or ""))
        if items is None:
            logger.warning(
                "blueprint_decompose_unavailable",
                category="caller",
                component=_COMPONENT,
                session_id=session_id,
                artifact_id=str(getattr(artifact, "id", "")),
                reason="llm_unavailable",
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            return None
        points = _points_from_segments(items)
        dropped = len(items) - len(points)

    if not points:
        return None

    content, base = await _aload_latest_content(artifact)
    if base is None or not content:
        return None
    spec = content.get("requirement_spec")
    if not isinstance(spec, dict):
        spec = {}
        content["requirement_spec"] = spec
    spec["feature_points"] = points

    try:
        version = await ArtifactService().add_version(
            artifact,
            content,
            produced_by_session_id=session_id,
            produced_by_ref="blueprint_decompose",
        )
    except ArtifactContentInvalid as exc:
        # 拆分产出不过 schema ⇒ **不落半合法版本**，保留基线并记 warning（规格门会开澄清）。
        logger.warning(
            "blueprint_decompose_invalid_content",
            category="caller",
            component=_COMPONENT,
            session_id=session_id,
            artifact_id=str(getattr(artifact, "id", "")),
            error=redact_secrets_in_text(str(exc)),
        )
        return None

    if str(version.id) == str(base.id):
        # `content_hash` 相等 ⇒ `add_version` 返回 current 不翻版本（重跑零版本噪声）。
        return None

    logger.info(
        "blueprint_decompose_completed",
        category="caller",
        component=_COMPONENT,
        session_id=session_id,
        artifact_id=str(getattr(artifact, "id", "")),
        source=source,
        point_count=len(points),
        dropped_count=max(dropped, 0),
        version_no=int(version.version_no),
        initiated_by_user_id=str(getattr(session, "initiated_by_user_id", "") or "") or "system",
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )
    return version
