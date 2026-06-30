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

import json
import time
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from initiatives.models import Artifact, ProjectWorkItemLink
from initiatives.models.artifact import ArtifactCarrier

logger = structlog.get_logger(__name__)

__all__ = [
    "FeatureListService",
    "progress_light",
    "FEATURE_LIST_TYPE_KEY",
    "to_feature_node_tree",
]

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


# 进度灯（中文）→ 前端 FeatureState 枚举（前端 STATE_CLASS 着色键）。
_PROGRESS_TO_STATE = {
    LIGHT_PENDING: "todo",
    LIGHT_IN_PROGRESS: "in_progress",
    LIGHT_TESTING: "testing",
    LIGHT_DONE: "done",
}


def to_feature_node_tree(tree: dict[str, Any]) -> dict[str, Any]:
    """把内部树 ``{modules:[{module, features:[{name,acceptance,progress,...}]}]}`` 转为
    前端 ``FeatureNode`` 树：``{modules:[{kind:'module',name,children:[{kind:'feature',name,
    state,status_display_name,module_normalized,children:[{kind:'acceptance',name}]}]}]}``。

    前端 FeatureBoard / 健康总览 / 上手引导 / 星图均按此 kind/children/state 契约消费；
    本转换是接口出参的唯一表示层，内部 ``build_tree`` 输出保持不变（galaxy 等内部消费照旧）。
    """
    modules_out: list[dict[str, Any]] = []
    for mod in tree.get("modules", []):
        module_name = str(mod.get("module") or "未分组")
        feats_out: list[dict[str, Any]] = []
        for feat in mod.get("features", []):
            progress = feat.get("progress") or LIGHT_PENDING
            state = _PROGRESS_TO_STATE.get(progress, "todo")
            acceptance_children = [
                {"kind": "acceptance", "name": str(a)}
                for a in (feat.get("acceptance") or [])
                if str(a).strip()
            ]
            feat_node: dict[str, Any] = {
                "kind": "feature",
                "name": str(feat.get("name") or ""),
                "state": state,
                "status_display_name": str(feat.get("status_display_name") or ""),
                "module_normalized": module_name,
                "children": acceptance_children,
            }
            # 整段原文（供前端点开后按需结构化为 sections 详情；可缺省）。
            source = str(feat.get("source") or "").strip()
            if source:
                feat_node["source"] = source
            feats_out.append(feat_node)
        mod_node: dict[str, Any] = {
            "kind": "module",
            "name": module_name,
            "children": feats_out,
        }
        summary = str(mod.get("summary") or "").strip()
        if summary:
            mod_node["source"] = summary
        modules_out.append(mod_node)
    return {"modules": modules_out}


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

        work_item_index = await self._aload_work_item_index(project_id)
        # 手动录入（#5）：markdown 载体的 feature_list 直接解析 content_ref JSON，
        # 不走飞书 bitable 拉取；飞书链接（feishu_bitable 等）仍走 records 路径。
        if artifact.carrier == ArtifactCarrier.MARKDOWN:
            tree = self._parse_manual(artifact.content_ref, work_item_index)
        else:
            records = await self._fetch_records(artifact)
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

    async def aset_feature_list(
        self,
        project_id: Any,
        *,
        mode: str,
        modules: list[dict[str, Any]] | None = None,
        url: str = "",
        paste_text: str = "",
        title: str = "",
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> Artifact:
        """设置/更新项目 feature_list 工件（#4/#5，唯一写入入口走 ArtifactService）。

        - ``mode="manual"``：手动录入 → markdown 载体，``content_ref`` 存归一 JSON。
        - ``mode="feishu"``：飞书多维表格链接 → feishu_bitable 载体，``url`` 存链接。
        - ``mode="gitlab"``：GitLab 文件链接 → 全局凭证取文 + LLM 逐字解析 → markdown 载体。
        - ``mode="paste"``：粘贴整篇文档 → LLM 逐字解析结构 → markdown 载体。

        每项目复用同一条 feature_list 工件（存在则更新、否则新建），避免堆积多条。
        """
        from initiatives.services.artifact_service import ArtifactService

        if mode == "manual":
            carrier = ArtifactCarrier.MARKDOWN
            content_ref = json.dumps(
                {"modules": self._normalize_manual_modules(modules or [])},
                ensure_ascii=False,
            )
            url = ""
            default_title = "Feature List（手动录入）"
        elif mode == "feishu":
            carrier = ArtifactCarrier.FEISHU_BITABLE
            content_ref = ""
            default_title = "Feature List（飞书）"
        elif mode in ("paste", "gitlab"):
            # 文档导入：先取正文（gitlab 取文 / paste 直接用），再 LLM 逐字解析为结构化模块。
            from initiatives.services.feature_list_import import (
                afetch_gitlab_file_text,
                agenerate_feature_modules_from_text,
            )

            if mode == "gitlab":
                if not url:
                    raise ValueError("gitlab 模式需提供文件链接")
                text = await afetch_gitlab_file_text(url)
                default_title = "Feature List（GitLab 文档）"
            else:
                text = paste_text or ""
                if not text.strip():
                    raise ValueError("paste 模式需提供文档内容")
                default_title = "Feature List（文档解析）"
            parsed = await agenerate_feature_modules_from_text(project_id, text)
            if not parsed:
                raise ValueError("AI 解析未产出有效 feature list（请检查文档内容或 AI Provider 配置）")
            carrier = ArtifactCarrier.MARKDOWN
            content_ref = json.dumps(
                {"modules": self._normalize_manual_modules(parsed)},
                ensure_ascii=False,
            )
            url = ""
        else:
            raise ValueError(f"未知 feature list 录入模式：{mode}")

        type_id = await self._aget_feature_list_type_id()
        existing_id = await self._aget_feature_list_artifact_id(project_id)
        service = ArtifactService()
        if existing_id is not None:
            return await service.update_artifact(
                artifact_id=existing_id,
                title=title or default_title,
                carrier=carrier,
                url=url,
                content_ref=content_ref,
                actor=actor,
                initiated_by_user_id=initiated_by_user_id,
            )
        return await service.create_artifact(
            project_id=project_id,
            type_id=type_id,
            title=title or default_title,
            carrier=carrier,
            url=url,
            content_ref=content_ref,
            contributor=actor,
            actor=actor,
            initiated_by_user_id=initiated_by_user_id,
        )

    @staticmethod
    def _normalize_manual_modules(modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """归一手动录入模块（防御脏数据：丢空名功能点、去空验收项、裁剪类型）。"""
        out: list[dict[str, Any]] = []
        for raw_mod in modules:
            if not isinstance(raw_mod, dict):
                continue
            module_name = str(raw_mod.get("module") or "未分组").strip() or "未分组"
            features: list[dict[str, Any]] = []
            for raw_feat in raw_mod.get("features") or []:
                if not isinstance(raw_feat, dict):
                    continue
                name = str(raw_feat.get("name") or "").strip()
                if not name:
                    continue
                acceptance = [
                    str(a).strip()
                    for a in (raw_feat.get("acceptance") or [])
                    if str(a).strip()
                ]
                feat: dict[str, Any] = {"name": name, "acceptance": acceptance}
                status = str(raw_feat.get("status") or "").strip()
                if status:
                    feat["status"] = status
                # 功能点整段原文（供详情按需结构化为 sections；解析得来，可缺省）。
                source = str(raw_feat.get("source") or "").strip()
                if source:
                    feat["source"] = source
                features.append(feat)
            mod_out: dict[str, Any] = {"module": module_name, "features": features}
            summary = str(raw_mod.get("summary") or "").strip()
            if summary:
                mod_out["summary"] = summary
            out.append(mod_out)
        return out

    @sync_to_async
    def _aget_feature_list_type_id(self) -> Any:
        from initiatives.models import ArtifactType

        artifact_type = ArtifactType.objects.filter(key=FEATURE_LIST_TYPE_KEY).first()
        if artifact_type is None:
            raise ValueError(
                f"工件类型 {FEATURE_LIST_TYPE_KEY} 未注册（应由 data migration seed）"
            )
        return artifact_type.id

    @sync_to_async
    def _aget_feature_list_artifact_id(self, project_id: Any) -> Any:
        artifact = (
            Artifact.objects.filter(
                project_id=project_id, type__key=FEATURE_LIST_TYPE_KEY
            )
            .order_by("-created_at")
            .first()
        )
        return artifact.id if artifact is not None else None

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

    def _parse_manual(
        self,
        content_ref: str,
        work_item_index: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """解析手动录入的 feature_list（markdown 载体，content_ref 存 JSON）。

        约定结构：``{"modules": [{"module": str, "features": [{"name": str,
        "acceptance": [str], "status": str}]}]}``。任何解析异常 → 返回空树（fail-soft）。
        """
        try:
            data = json.loads(content_ref or "{}")
        except (ValueError, TypeError):
            return {"modules": []}
        raw_modules = data.get("modules") if isinstance(data, dict) else None
        if not isinstance(raw_modules, list):
            return {"modules": []}

        modules_out: list[dict[str, Any]] = []
        for raw_mod in raw_modules:
            if not isinstance(raw_mod, dict):
                continue
            module_name = str(raw_mod.get("module") or "未分组").strip() or "未分组"
            features_out: list[dict[str, Any]] = []
            for raw_feat in raw_mod.get("features") or []:
                if not isinstance(raw_feat, dict):
                    continue
                name = str(raw_feat.get("name") or "").strip()
                if not name:
                    continue
                acceptance = [
                    str(a).strip()
                    for a in (raw_feat.get("acceptance") or [])
                    if str(a).strip()
                ]
                status_text = str(raw_feat.get("status") or "").strip()
                wi = work_item_index.get(name)
                if wi is not None:
                    progress = progress_light(
                        status_state_key=wi["status_state_key"],
                        status_sub_stage=wi["status_sub_stage"],
                        is_archived_state=wi["is_archived_state"],
                        is_init_state=wi["is_init_state"],
                    )
                    status_display = wi["status_display_name"]
                else:
                    progress = progress_light(status_text=status_text)
                    status_display = ""
                feat_out: dict[str, Any] = {
                    "name": name,
                    "acceptance": acceptance,
                    "progress": progress,
                    "status_display_name": status_display,
                }
                source = str(raw_feat.get("source") or "").strip()
                if source:
                    feat_out["source"] = source
                features_out.append(feat_out)
            mod_out: dict[str, Any] = {"module": module_name, "features": features_out}
            summary = str(raw_mod.get("summary") or "").strip()
            if summary:
                mod_out["summary"] = summary
            modules_out.append(mod_out)
        return {"modules": modules_out}

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
