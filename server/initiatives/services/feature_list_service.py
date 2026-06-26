"""FeatureListService —— feature list 工件 → 模块/功能点/验收项 树 + 进度灯（WB-02，84-01）。

从项目 ``feature_list`` 工件（飞书 bitable 载体）解析「模块 → 功能点 → 验收项」三层树，对每个
功能点按其名称匹配到的 ``delivery.WorkItem`` 状态映射四态进度灯（待开发/进行中/测试中/已完成）。

四态灯映射表在本 service 内集中维护（``progress_light`` + ``_KEY_*`` 常量），注释每档来源；
依据 ``WorkItem`` 的 ``status_state_key`` / ``status_sub_stage`` / ``is_archived_state`` /
``is_init_state``。无匹配 WorkItem 时回退记录自身状态文本，再回退「待开发」。

只读：不写库（无 INV-6 约束）。飞书 bitable 拉取经既有 ``aget_artifact_view`` fail-soft；空
feature_list / 拉取失败 → 返回空树不报错。深度项目域 RAG 标注留 Phase 85。
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from initiatives.models import Artifact, ProjectWorkItemLink

logger = structlog.get_logger(__name__)

__all__ = ["FeatureListService", "progress_light", "FEATURE_LIST_TYPE_KEY"]

_COMPONENT = "initiatives.workspace"

# feature list 工件类型 key（见 initiatives/migrations/0004_seed_artifact_types.py）。
FEATURE_LIST_TYPE_KEY = "feature_list"

# 四态进度灯（zh-CN，与 UI-SPEC §Color 进度灯语义一致）。
LIGHT_PENDING = "待开发"
LIGHT_IN_PROGRESS = "进行中"
LIGHT_TESTING = "测试中"
LIGHT_DONE = "已完成"

# bitable 字段名兜底候选（飞书表列名不固定，按候选集模糊取首个非空）。
_MODULE_KEYS = ("模块", "module", "Module", "所属模块", "分组")
_FEATURE_KEYS = ("功能点", "功能", "feature", "Feature", "需求点")
_ACCEPTANCE_KEYS = ("验收项", "验收", "验收标准", "acceptance", "Acceptance")
_STATUS_KEYS = ("状态", "status", "Status", "进度")

# WorkItem 状态 → 四态灯关键词集（飞书 state_key/sub_stage 取值不固定，用关键词匹配兜底）：
# - 已完成：归档完成态 is_archived_state，或 state_key 命中完成关键词。
# - 测试中：sub_stage / state_key 命中测试关键词。
# - 待开发：is_init_state 初始态 / 无状态。
# - 进行中：其余非完成非初始进行态。
_DONE_KEYWORDS = ("done", "finish", "closed", "complete", "完成", "已上线", "结束")
_TESTING_KEYWORDS = ("test", "qa", "verify", "测试", "验收", "联调")


def progress_light(
    *,
    status_state_key: str = "",
    status_sub_stage: str = "",
    is_archived_state: bool = False,
    is_init_state: bool = False,
    status_text: str = "",
) -> str:
    """映射 WorkItem / 记录状态到四态进度灯（集中维护，每档来源见上方常量注释）。"""
    haystack = " ".join(
        s.lower()
        for s in (status_state_key, status_sub_stage, status_text)
        if s
    )
    # 已完成：归档完成态优先（飞书归档即终态完成）。
    if is_archived_state or any(k in haystack for k in _DONE_KEYWORDS):
        return LIGHT_DONE
    # 测试中：测试子阶段 / 状态命中测试关键词。
    if any(k in haystack for k in _TESTING_KEYWORDS):
        return LIGHT_TESTING
    # 待开发：初始态 / 无任何状态信息。
    if is_init_state or not haystack:
        return LIGHT_PENDING
    # 其余进行态。
    return LIGHT_IN_PROGRESS


class FeatureListService:
    """feature_list 工件 → 三层树 + 四态灯（只读编排）。"""

    async def build_tree(self, project_id: Any) -> dict[str, Any]:
        """构建项目 feature 树；无 feature_list 工件 / 拉取失败 → 返回空树（不报错）。"""
        started = time.monotonic()
        artifact = await self._aget_feature_list_artifact(project_id)
        if artifact is None:
            logger.info(
                "project_feature_list_built",
                project_id=str(project_id),
                modules=0,
                features=0,
                reason="no_artifact",
                duration_ms=round((time.monotonic() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
            return {"modules": []}

        records = await self._fetch_records(artifact)
        work_item_index = await self._aload_work_item_index(project_id)
        tree = self._parse_records(records, work_item_index)

        feature_count = sum(len(m["features"]) for m in tree["modules"])
        logger.info(
            "project_feature_list_built",
            project_id=str(project_id),
            modules=len(tree["modules"]),
            features=feature_count,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            component=_COMPONENT,
            category="caller",
        )
        return tree

    @sync_to_async
    def _aget_feature_list_artifact(self, project_id: Any) -> Artifact | None:
        return (
            Artifact.objects.select_related("type", "project", "project__space")
            .filter(project_id=project_id, type__key=FEATURE_LIST_TYPE_KEY)
            .order_by("-created_at")
            .first()
        )

    async def _fetch_records(self, artifact: Artifact) -> list[dict[str, Any]]:
        """拉取 feature_list 工件记录（复用 ``aget_artifact_view`` bitable 路径，fail-soft）。

        返回 bitable 记录列表（每项形如 ``{"fields": {...}}``）；非 records 视图 / 拉取失败 → []。
        测试可 patch 本方法注入合成记录。
        """
        from initiatives.services.artifact_view import aget_artifact_view

        try:
            view = await aget_artifact_view(artifact)
        except Exception as exc:  # noqa: BLE001 — 拉取失败 fail-soft 返回空（不反噬树构建）
            logger.warning(
                "project_feature_list_fetch_failed",
                artifact_id=str(artifact.id),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )
            return []
        if view.get("render_type") != "records":
            return []
        return view.get("records") or []

    @sync_to_async
    def _aload_work_item_index(self, project_id: Any) -> dict[str, dict[str, Any]]:
        """项目关联 WorkItem 的状态索引（按 title 归一键），供功能点匹配进度灯。"""
        rows = (
            ProjectWorkItemLink.objects.filter(project_id=project_id)
            .select_related("work_item")
            .values(
                "work_item__title",
                "work_item__status_state_key",
                "work_item__status_sub_stage",
                "work_item__status_display_name",
                "work_item__is_archived_state",
                "work_item__is_init_state",
            )
        )
        index: dict[str, dict[str, Any]] = {}
        for r in rows:
            title = (r["work_item__title"] or "").strip()
            if not title:
                continue
            index[title] = {
                "status_state_key": r["work_item__status_state_key"] or "",
                "status_sub_stage": r["work_item__status_sub_stage"] or "",
                "status_display_name": r["work_item__status_display_name"] or "",
                "is_archived_state": r["work_item__is_archived_state"],
                "is_init_state": r["work_item__is_init_state"],
            }
        return index

    def _parse_records(
        self,
        records: list[dict[str, Any]],
        work_item_index: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """解析 bitable 记录为模块→功能点→验收项 树（保序，defensive）。"""
        modules: dict[str, dict[str, Any]] = {}
        for rec in records:
            fields = rec.get("fields", rec) if isinstance(rec, dict) else {}
            module_name = self._first(fields, _MODULE_KEYS) or "未分组"
            feature_name = self._first(fields, _FEATURE_KEYS)
            if not feature_name:
                continue
            acceptance = self._first(fields, _ACCEPTANCE_KEYS)
            status_text = self._first(fields, _STATUS_KEYS)

            module = modules.setdefault(
                module_name, {"module": module_name, "features": {}}
            )
            feature = module["features"].setdefault(
                feature_name,
                {
                    "name": feature_name,
                    "acceptance": [],
                    "progress": LIGHT_PENDING,
                    "status_display_name": "",
                },
            )
            if acceptance and acceptance not in feature["acceptance"]:
                feature["acceptance"].append(acceptance)

            wi = work_item_index.get(feature_name)
            if wi is not None:
                feature["progress"] = progress_light(
                    status_state_key=wi["status_state_key"],
                    status_sub_stage=wi["status_sub_stage"],
                    is_archived_state=wi["is_archived_state"],
                    is_init_state=wi["is_init_state"],
                )
                feature["status_display_name"] = wi["status_display_name"]
            else:
                feature["progress"] = progress_light(status_text=status_text)

        return {
            "modules": [
                {
                    "module": m["module"],
                    "features": list(m["features"].values()),
                }
                for m in modules.values()
            ]
        }

    @staticmethod
    def _first(fields: dict[str, Any], keys: tuple[str, ...]) -> str:
        """从记录字段按候选 key 取首个非空文本值（兼容飞书 bitable 多形态值）。"""
        for key in keys:
            if key in fields:
                text = FeatureListService._text_of(fields[key])
                if text:
                    return text
        return ""

    @staticmethod
    def _text_of(value: Any) -> str:
        """归一飞书 bitable 字段值为纯文本（str / [{text}] / {text} / 其它 → str）。"""
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            return str(value.get("text", value.get("name", ""))).strip()
        if isinstance(value, list):
            parts = [FeatureListService._text_of(v) for v in value]
            return " ".join(p for p in parts if p).strip()
        return str(value).strip()
