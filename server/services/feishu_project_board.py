"""飞书"项目跟踪"看板枚举（FSPROJ-01）。

把"项目跟踪"看板工作项转成结构化枚举结果：**子关联项（story/缺陷）** + **人员（带角色）**。

设计立场（与 `.planning/project-aggregate/MILESTONE-PROPOSAL.md` §3/§4 一致）：

- **飞书无整板 listing API**：无法一次列出看板下所有子项/成员。枚举只能经"项目跟踪"工作项
  本身的 fields 派生——子项经**关联多选字段**（`work_item_related_multi_select`，复用 Phase 27
  `derive_relations_from_fields` / `extract_related_ids` 范式）、人员经**用户类字段**
  （`field_type_key in {user, multi_user, role}`）。
- **硬/软路径分治**：硬路径 = 读"项目跟踪"工作项本身（`FeishuClient.get_work_item` 内部
  `strict_response_json` fail-loud，非 JSON 抛 `FeishuResponseError`）；软路径 = 从 fields 派生
  子项/人员（缺料 → 部分结果 + warning + `degraded=True`，绝不抛）。调用方据硬路径异常**降级半自动**
  （仍幂等建项目，子项/成员留待后续 webhook 逐个并入）。
- **字段 key 不确定性（needs live-Feishu）**：真实看板的子项关联字段 key、人员字段 key、角色标签
  尚未经真实飞书 payload 校验，故采用**集中映射表 + 关键字推断 + 保守默认**（角色默认 `backend`、
  子项类型默认 `story`），真实 key 经 live UAT 后补登记即可，逻辑不变。

本模块**不依赖 Django**（纯 service 层 + dataclass），ORM/落库归 `initiatives` service。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from services.feishu_parsing import RELATION_FIELD_TYPE_KEY, extract_related_ids

logger = structlog.get_logger(__name__)

__all__ = [
    "BoardWorkItemRef",
    "BoardPerson",
    "BoardEnumeration",
    "enumerate_board",
    "map_role",
    "STORY_WORK_ITEM_TYPE",
    "DEFECT_WORK_ITEM_TYPE",
    "DEFAULT_PROJECT_ROLE",
]


# === 类型推断 / 角色映射常量（集中定义，唯一事实源）===

STORY_WORK_ITEM_TYPE = "story"
DEFECT_WORK_ITEM_TYPE = "issue"  # 飞书"缺陷"工作项类型 key（live UAT 可校正）

# 用户类字段（人员派生来源）的 field_type_key 集合（保守覆盖常见命名）
_USER_FIELD_TYPE_KEYS: frozenset[str] = frozenset(
    {"user", "multi_user", "user_property", "role", "role_owner"}
)

# 子项类型推断：字段名/别名含以下关键字 → 缺陷；否则 story（保守默认）
_DEFECT_KEYWORDS: tuple[str, ...] = ("缺陷", "bug", "issue", "defect")

# ``ProjectRole`` 取值（避免本 service 反向依赖 initiatives.models，硬编码与枚举同值）。
# 与 initiatives.models.member.ProjectRole 一一对应（owner/pm/frontend/backend/qa）。
_ROLE_OWNER = "owner"
_ROLE_PM = "pm"
_ROLE_FRONTEND = "frontend"
_ROLE_BACKEND = "backend"
_ROLE_QA = "qa"

DEFAULT_PROJECT_ROLE = _ROLE_BACKEND  # 无法判定时的保守默认

# 飞书看板"人员角色"字段标签（小写归一）→ ProjectRole（集中映射表，FSPROJ-01）。
# 经 field_alias / field_name 子串匹配；未命中给保守默认 DEFAULT_PROJECT_ROLE。
ROLE_LABEL_TO_PROJECT_ROLE: dict[str, str] = {
    # 主R / owner
    "主r": _ROLE_OWNER,
    "负责人": _ROLE_OWNER,
    "项目负责人": _ROLE_OWNER,
    "owner": _ROLE_OWNER,
    # 产品经理
    "产品经理": _ROLE_PM,
    "产品": _ROLE_PM,
    "pm": _ROLE_PM,
    # 前端
    "前端": _ROLE_FRONTEND,
    "frontend": _ROLE_FRONTEND,
    "fe": _ROLE_FRONTEND,
    # 后端
    "后端": _ROLE_BACKEND,
    "服务端": _ROLE_BACKEND,
    "backend": _ROLE_BACKEND,
    "be": _ROLE_BACKEND,
    # 测试
    "测试": _ROLE_QA,
    "测试工程师": _ROLE_QA,
    "qa": _ROLE_QA,
    "test": _ROLE_QA,
}


@dataclass
class BoardWorkItemRef:
    """看板下的子关联工作项引用（story/缺陷，统一复用 delivery.WorkItem）。"""

    work_item_id: int
    work_item_type: str


@dataclass
class BoardPerson:
    """看板人员（带映射后的项目角色）。"""

    user_key: str
    role: str  # ProjectRole 取值


@dataclass
class BoardEnumeration:
    """看板枚举结果（部分可降级）。"""

    work_items: list[BoardWorkItemRef] = field(default_factory=list)
    people: list[BoardPerson] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    degraded: bool = False


# === 纯函数派生 helper ===


def map_role(fld: dict[str, Any]) -> str:
    """飞书人员字段 → ProjectRole（经 field_alias/field_name 子串匹配，保守默认 backend）。

    Args:
        fld: `build_feishu_fields` 产出的字段对象（含 field_name/field_alias）。

    Returns:
        映射后的 ProjectRole 取值；未命中返回 ``DEFAULT_PROJECT_ROLE``。
    """
    for source in (fld.get("field_alias"), fld.get("field_name")):
        if not isinstance(source, str) or not source:
            continue
        needle = source.strip().lower()
        # 先整体精确命中，再子串命中（标签可能是"前端负责人"含"前端"）
        if needle in ROLE_LABEL_TO_PROJECT_ROLE:
            return ROLE_LABEL_TO_PROJECT_ROLE[needle]
        for label, role in ROLE_LABEL_TO_PROJECT_ROLE.items():
            if label in needle:
                return role
    return DEFAULT_PROJECT_ROLE


def _infer_child_type(fld: dict[str, Any]) -> str:
    """子项关联字段 → 工作项类型（含缺陷关键字 → 缺陷，否则 story）。"""
    for source in (fld.get("field_alias"), fld.get("field_name")):
        if not isinstance(source, str) or not source:
            continue
        needle = source.strip().lower()
        if any(kw in needle for kw in _DEFECT_KEYWORDS):
            return DEFECT_WORK_ITEM_TYPE
    return STORY_WORK_ITEM_TYPE


def _extract_user_keys(field_value: Any) -> list[str]:
    """从用户类字段值派生 user_key 列表（兼容 str / list[str] / list[{...}]）。

    用户字段值常见三形态：单个 user_key 字符串、user_key 字符串列表、
    ``[{value|id|user_key|user_id}, ...]`` 字典列表。非法/空项跳过（fail-soft）。
    """
    keys: list[str] = []

    def _push(raw: Any) -> None:
        if isinstance(raw, str):
            s = raw.strip()
            if s:
                keys.append(s)
        elif isinstance(raw, dict):
            for k in ("user_key", "value", "id", "user_id", "open_id"):
                cand = raw.get(k)
                if isinstance(cand, str) and cand.strip():
                    keys.append(cand.strip())
                    return

    if isinstance(field_value, list):
        for item in field_value:
            _push(item)
    else:
        _push(field_value)
    return keys


def _derive_board_work_items(feishu_fields: list[dict]) -> list[BoardWorkItemRef]:
    """从关联多选字段派生子项引用（复用 Phase 27 关系字段范式，按字段推断类型）。"""
    refs: list[BoardWorkItemRef] = []
    seen: set[tuple[int, str]] = set()
    for fld in feishu_fields or []:
        if not isinstance(fld, dict):
            continue
        if fld.get("field_type_key") != RELATION_FIELD_TYPE_KEY:
            continue
        child_type = _infer_child_type(fld)
        for wid in extract_related_ids(fld.get("field_value")):
            key = (wid, child_type)
            if key in seen:
                continue
            seen.add(key)
            refs.append(BoardWorkItemRef(work_item_id=wid, work_item_type=child_type))
    return refs


def _derive_board_people(feishu_fields: list[dict]) -> list[BoardPerson]:
    """从用户类字段派生人员（带角色），按 user_key 去重保留首个角色。"""
    people: list[BoardPerson] = []
    seen: set[str] = set()
    for fld in feishu_fields or []:
        if not isinstance(fld, dict):
            continue
        if fld.get("field_type_key") not in _USER_FIELD_TYPE_KEYS:
            continue
        role = map_role(fld)
        for uk in _extract_user_keys(fld.get("field_value")):
            if uk in seen:
                continue
            seen.add(uk)
            people.append(BoardPerson(user_key=uk, role=role))
    return people


# === 枚举入口 ===


async def enumerate_board(
    client: Any,
    *,
    feishu_project_key: str,
    board_work_item_id: int,
    board_work_item_type: str = STORY_WORK_ITEM_TYPE,
) -> BoardEnumeration:
    """枚举"项目跟踪"看板工作项的子项 + 人员（带角色）。

    硬路径（读看板工作项本身）fail-loud：``client.get_work_item`` 内部 ``strict_response_json``
    对非 JSON 响应抛 ``FeishuResponseError``，本函数**不**吞此异常——由调用方（事件 handler /
    `create_project` 节点）捕获后降级半自动。软路径（从 fields 派生子项/人员）fail-soft：缺料
    返回部分结果 + warning + ``degraded=True``。

    Args:
        client: `FeishuClient` 实例（或鸭子类型兼容 `get_work_item`）。
        feishu_project_key: 飞书项目空间 Key。
        board_work_item_id: "项目跟踪"看板工作项 ID。
        board_work_item_type: 看板工作项类型（默认 story）。

    Returns:
        ``BoardEnumeration``（含 work_items / people / warnings / degraded）。

    Raises:
        FeishuResponseError: 硬路径读取看板工作项响应非 JSON（fail-loud，调用方降级）。
    """
    started = time.monotonic()
    logger.info(
        "board_enumeration_started",
        feishu_project_key=feishu_project_key,
        board_work_item_id=board_work_item_id,
        component="feishu",
        category="sampling",
    )

    # 硬路径：读看板工作项本身（非 JSON → strict 抛 FeishuResponseError，不吞）
    info = await client.get_work_item(
        feishu_project_key, board_work_item_id, board_work_item_type
    )

    # 软路径：从 fields 派生子项 + 人员（缺料 → 部分 + warning + degraded）
    feishu_fields = getattr(info, "feishu_fields", None) or []
    work_items = _derive_board_work_items(feishu_fields)
    people = _derive_board_people(feishu_fields)

    warnings: list[str] = []
    degraded = False
    if not work_items:
        warnings.append("no_child_work_items")
        degraded = True
    if not people:
        warnings.append("no_people")
        degraded = True

    logger.info(
        "board_enumeration_completed",
        feishu_project_key=feishu_project_key,
        board_work_item_id=board_work_item_id,
        work_item_count=len(work_items),
        people_count=len(people),
        degraded=degraded,
        duration_ms=round((time.monotonic() - started) * 1000, 2),
        component="feishu",
        category="sampling",
    )
    return BoardEnumeration(
        work_items=work_items, people=people, warnings=warnings, degraded=degraded
    )
