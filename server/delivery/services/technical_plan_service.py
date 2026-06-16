"""TechnicalPlanService —— canonical 方案的唯一写入入口（DOMAIN §5.2 / §13.2，INV-6）。

所有 canonical ``TechnicalPlan`` / ``PlanVersion`` 落库只经本 service：

- ``create_from(origin, payload, *, work_item=None)``：eager 建 canonical（plan + 首版
  v1 + 置 current_version），content 经 ``validate_technical_plan`` 校验（PF-02）。
- ``add_version(plan, content)``：content_hash 相等复用 current 不翻版本（v0.3/v0.6 铁律）；
  不等建新版本 ``supersedes=current`` 并推进 ``current_version``。
- ``resolve(ref)``：按 DOMAIN §5.4 读优先级——软链命中读 canonical（冲突以 canonical 为准）/
  无软链但旧记录完整 → lazy 建 canonical 回填链 / 找不到旧记录 → ``raise PlanNotFound``。
- ``link(old_record, canonical)``：回填软链（chat/mcp 的 ``canonical_plan_id`` 字段 /
  workflow 的 ``PlanExternalRef`` 映射表，幂等）。
- ``archive(plan)``：置 status=archived，**不级联删旧表 / 不删 PlanVersion**（DOMAIN §5.4）。

``content_hash`` 为**本地** ``sha256(canonical JSON sort_keys)``，**不 import knowledge**
（INV-3 边界）。content 校验仅 import ``workflows.schemas.technical_plan``（PF-02）。
ORM 写经 ``sync_to_async`` 桥接（沿用 delivery service async 范式），写操作用
``transaction.atomic``。chat/mcp 模型函数内 lazy import 防跨 app 循环依赖。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction

from delivery.models import (
    PlanExternalRef,
    PlanVersion,
    TechnicalPlan,
    TechnicalPlanOrigin,
    TechnicalPlanStatus,
)
from workflows.schemas.technical_plan import validate_technical_plan

logger = structlog.get_logger(__name__)

__all__ = [
    "PlanRef",
    "PlanContentInvalid",
    "PlanNotFound",
    "TechnicalPlanService",
    "chat_codingplan_to_content",
    "mcp_plan_to_content",
]

# execution_plan item.branch_strategy 合法枚举（对齐 workflows schema）
_VALID_BRANCH_STRATEGIES = {"feature", "hotfix", "release"}
# affected_files.change_type → files.action（schema action 枚举 create/modify/delete）
_CHANGE_TYPE_TO_ACTION = {
    "add": "create",
    "create": "create",
    "modify": "modify",
    "change": "modify",
    "update": "modify",
    "delete": "delete",
    "remove": "delete",
}


def _normalize_action(change_type: Any) -> str:
    return _CHANGE_TYPE_TO_ACTION.get(str(change_type or "").lower(), "modify")


def _normalize_branch_strategy(value: Any) -> str:
    candidate = str(value or "").lower()
    return candidate if candidate in _VALID_BRANCH_STRATEGIES else "feature"


class PlanContentInvalid(ValueError):
    """方案 content 未过 ``validate_technical_plan`` 校验（半可信 payload 防落坏内容）。"""


class PlanNotFound(LookupError):
    """resolve 找不到旧记录（DOMAIN §5.4 规则 3）。"""

    def __init__(self, ref: Any) -> None:
        super().__init__(f"未找到方案旧记录：{ref}")
        self.ref = ref


@dataclass(frozen=True)
class PlanRef:
    """统一来源标识（resolve 入参）。

    ``source_key`` 语义按 ``origin``：

    - chat：``chat.CodingPlan.id`` 字符串
    - mcp：``mcp_tools.McpWorkItemTechnicalPlan.id`` 字符串
    - workflow：``f"workflow:{execution_id}:{node_id}"`` 规范化 external_ref 串
    """

    origin: str
    source_key: str

    @classmethod
    def for_chat(cls, coding_plan_id: Any) -> PlanRef:
        return cls(origin=TechnicalPlanOrigin.CHAT, source_key=str(coding_plan_id))

    @classmethod
    def for_mcp(cls, plan_id: Any) -> PlanRef:
        return cls(origin=TechnicalPlanOrigin.MCP, source_key=str(plan_id))

    @classmethod
    def for_workflow(cls, execution_id: Any, node_id: Any) -> PlanRef:
        return cls(
            origin=TechnicalPlanOrigin.WORKFLOW,
            source_key=f"workflow:{execution_id}:{node_id}",
        )


def _content_hash(content: dict) -> str:
    """canonical JSON 的本地 sha256 hex（不 import knowledge，守 INV-3 边界）。"""
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class TechnicalPlanService:
    """canonical 方案唯一写入入口（INV-6）。"""

    # ---- 写入：create_from / add_version / archive ----

    async def create_from(
        self,
        origin: str,
        payload: dict,
        *,
        work_item: Any = None,
    ) -> TechnicalPlan:
        """eager 建 canonical：校验 content → 建 plan + 首版 v1 + 置 current_version。

        INV-2：``origin=chat`` 且 ``work_item=None`` 合法（不校验 work_item 必填）。
        ``payload`` 须为含 ``content`` 键的 dict；content 经 ``validate_technical_plan``，
        非法 ``raise PlanContentInvalid``（不落库）。
        """
        if origin not in TechnicalPlanOrigin.values:
            raise ValueError(f"非法 origin={origin!r}；合法值={list(TechnicalPlanOrigin.values)}")
        if not isinstance(payload, dict) or "content" not in payload:
            raise PlanContentInvalid("payload 须为含 'content' 键的 dict")
        content = payload["content"]
        valid, err = validate_technical_plan(content)
        if not valid:
            raise PlanContentInvalid(f"content 校验失败：{err}")
        return await self._create_from_sync(origin, content, work_item)

    @sync_to_async
    def _create_from_sync(self, origin: str, content: dict, work_item: Any) -> TechnicalPlan:
        with transaction.atomic():
            return self._create_canonical_sync(origin, content, work_item)

    def _create_canonical_sync(self, origin: str, content: dict, work_item: Any) -> TechnicalPlan:
        """同步建 canonical（plan + 首版 v1 + 置 current_version）；调用方负责事务边界。

        供 ``_create_from_sync`` 与 lazy 迁移加锁路径复用——后者需在同一 ``transaction.atomic``
        内「建 canonical + 回填软链」原子完成（WR-01：防并发/中断产生孤儿 canonical）。
        """
        plan = TechnicalPlan.objects.create(
            work_item=work_item,
            origin=origin,
            status=TechnicalPlanStatus.DRAFT,
        )
        v1 = PlanVersion.objects.create(
            plan=plan,
            version=1,
            content=content,
            content_hash=_content_hash(content),
        )
        plan.current_version = v1
        plan.save(update_fields=["current_version", "updated_at"])
        return plan

    async def add_version(self, plan: TechnicalPlan, content: dict) -> PlanVersion:
        """加版本：hash 相等复用 current 不翻版本；不等建 supersedes 链并推进 current。"""
        valid, err = validate_technical_plan(content)
        if not valid:
            raise PlanContentInvalid(f"content 校验失败：{err}")
        return await self._add_version_sync(plan, content, _content_hash(content))

    @sync_to_async
    def _add_version_sync(self, plan: TechnicalPlan, content: dict, new_hash: str) -> PlanVersion:
        with transaction.atomic():
            # 从 DB 取最新 current_version（避免传入实例陈旧）
            plan.refresh_from_db(fields=["current_version"])
            current = plan.current_version
            if current is not None and current.content_hash == new_hash:
                # hash 相等绝不产生新版本（v0.3/v0.6 铁律）
                return current
            next_version = (current.version + 1) if current is not None else 1
            new_version = PlanVersion.objects.create(
                plan=plan,
                version=next_version,
                supersedes=current,
                content=content,
                content_hash=new_hash,
            )
            plan.current_version = new_version
            plan.save(update_fields=["current_version", "updated_at"])
            return new_version

    async def archive(self, plan: TechnicalPlan) -> TechnicalPlan:
        """归档：置 status=archived；**不**触碰旧表 / 不删 PlanVersion（DOMAIN §5.4）。"""
        return await self._archive_sync(plan)

    @sync_to_async
    def _archive_sync(self, plan: TechnicalPlan) -> TechnicalPlan:
        plan.status = TechnicalPlanStatus.ARCHIVED
        plan.save(update_fields=["status", "updated_at"])
        return plan

    # ---- 解析 / 关联：resolve / link ----

    async def resolve(self, ref: PlanRef) -> TechnicalPlan:
        """按 DOMAIN §5.4 读优先级解析 canonical（软链命中读 / lazy 建+回填 / 找不到 raise）。"""
        if ref.origin == TechnicalPlanOrigin.CHAT:
            return await self._resolve_chat(ref)
        if ref.origin == TechnicalPlanOrigin.MCP:
            return await self._resolve_mcp(ref)
        if ref.origin == TechnicalPlanOrigin.WORKFLOW:
            return await self._resolve_workflow(ref)
        raise ValueError(f"不支持的 resolve origin={ref.origin!r}")

    @staticmethod
    def _ensure_uuid_source_key(ref: PlanRef) -> None:
        """chat/mcp 的 ``source_key`` 须为合法 UUID；非法 → ``PlanNotFound``（IN-01）。

        旧记录 pk 为 UUID，传入非 UUID 字符串时 ORM 会抛 ``ValueError``/``ValidationError``，
        绕过「找不到旧记录 → PlanNotFound」契约（DOMAIN §5.4 规则 3）。入口预校验归一化。
        """
        try:
            uuid.UUID(str(ref.source_key))
        except (ValueError, TypeError):
            raise PlanNotFound(ref) from None

    async def _resolve_chat(self, ref: PlanRef) -> TechnicalPlan:
        from chat.models import CodingPlan  # lazy import 防循环

        self._ensure_uuid_source_key(ref)
        try:
            old = await CodingPlan.objects.aget(id=ref.source_key)
        except CodingPlan.DoesNotExist:
            raise PlanNotFound(ref) from None
        if old.canonical_plan_id:
            # 已迁移：无锁快路径直接读 canonical（双检锁的乐观第一检）
            return await self._aget_plan(old.canonical_plan_id, ref)
        # 未迁移：进入加锁 lazy 迁移（锁内复检软链，原子建 canonical + 回填，WR-01）
        return await self._resolve_chat_lazy_sync(ref)

    @sync_to_async
    def _resolve_chat_lazy_sync(self, ref: PlanRef) -> TechnicalPlan:
        """chat lazy 迁移：行锁 + 锁内复检软链 + 同事务建 canonical 并回填（WR-01）。

        并发/陈旧 resolve 命中同一未迁移旧记录时，``select_for_update`` 串行化，后来者在锁内
        复检 ``canonical_plan_id`` 已被前者写入 → 直接读现有 canonical，绝不重复创建。
        """
        from chat.models import CodingPlan  # lazy import 防循环

        with transaction.atomic():
            try:
                old = CodingPlan.objects.select_for_update().get(id=ref.source_key)
            except CodingPlan.DoesNotExist:
                raise PlanNotFound(ref) from None
            if old.canonical_plan_id:
                return self._get_plan_sync(old.canonical_plan_id, ref)
            content = chat_codingplan_to_content(old)
            valid, err = validate_technical_plan(content)
            if not valid:
                raise PlanContentInvalid(f"content 校验失败：{err}")
            canonical = self._create_canonical_sync(TechnicalPlanOrigin.CHAT, content, None)
            old.canonical_plan_id = canonical.id
            old.save(update_fields=["canonical_plan_id", "updated_at"])
            return canonical

    async def _resolve_mcp(self, ref: PlanRef) -> TechnicalPlan:
        from mcp_tools.models import McpWorkItemTechnicalPlan  # lazy import 防循环

        self._ensure_uuid_source_key(ref)
        try:
            old = await McpWorkItemTechnicalPlan.objects.aget(id=ref.source_key)
        except McpWorkItemTechnicalPlan.DoesNotExist:
            raise PlanNotFound(ref) from None
        if old.canonical_plan_id:
            # 已迁移：无锁快路径直接读 canonical（双检锁的乐观第一检）
            return await self._aget_plan(old.canonical_plan_id, ref)
        # 未迁移：进入加锁 lazy 迁移（锁内复检软链，原子建 canonical + 回填，WR-01）
        return await self._resolve_mcp_lazy_sync(ref)

    @sync_to_async
    def _resolve_mcp_lazy_sync(self, ref: PlanRef) -> TechnicalPlan:
        """mcp lazy 迁移：行锁 + 锁内复检软链 + 同事务建 canonical 并回填（WR-01）。"""
        from mcp_tools.models import McpWorkItemTechnicalPlan  # lazy import 防循环

        with transaction.atomic():
            try:
                old = McpWorkItemTechnicalPlan.objects.select_for_update().get(id=ref.source_key)
            except McpWorkItemTechnicalPlan.DoesNotExist:
                raise PlanNotFound(ref) from None
            if old.canonical_plan_id:
                return self._get_plan_sync(old.canonical_plan_id, ref)
            content = mcp_plan_to_content(old)
            valid, err = validate_technical_plan(content)
            if not valid:
                raise PlanContentInvalid(f"content 校验失败：{err}")
            canonical = self._create_canonical_sync(TechnicalPlanOrigin.MCP, content, None)
            old.canonical_plan_id = canonical.id
            old.save(update_fields=["canonical_plan_id", "updated_at"])
            return canonical

    async def _resolve_workflow(self, ref: PlanRef) -> TechnicalPlan:
        # workflow 无独立旧表：仅在 PlanExternalRef 命中时读 canonical，否则 PlanNotFound
        # （eager 投影由调用方先 create_from + link，DOMAIN §5.3）。
        ext = (
            await PlanExternalRef.objects.filter(external_ref=ref.source_key)
            .select_related("canonical")
            .afirst()
        )
        if ext is None:
            raise PlanNotFound(ref)
        return ext.canonical

    async def _aget_plan(self, plan_id: Any, ref: PlanRef) -> TechnicalPlan:
        try:
            return await TechnicalPlan.objects.aget(id=plan_id)
        except TechnicalPlan.DoesNotExist:
            raise PlanNotFound(ref) from None

    def _get_plan_sync(self, plan_id: Any, ref: PlanRef) -> TechnicalPlan:
        """``_aget_plan`` 的同步版（供 lazy 加锁路径在事务内复用）。"""
        try:
            return TechnicalPlan.objects.get(id=plan_id)
        except TechnicalPlan.DoesNotExist:
            raise PlanNotFound(ref) from None

    async def link(self, old_record: Any, canonical: TechnicalPlan) -> None:
        """回填软链：chat/mcp 实例写 ``canonical_plan_id``；workflow 经 PlanExternalRef 幂等。"""
        if isinstance(old_record, str):
            await self._link_external(old_record, canonical)
            return
        if isinstance(old_record, PlanRef):
            if old_record.origin == TechnicalPlanOrigin.WORKFLOW:
                await self._link_external(old_record.source_key, canonical)
                return
            raise ValueError("PlanRef 形态的 link 仅支持 workflow origin")
        # chat/mcp 实例：写 canonical_plan_id 软链字段
        old_record.canonical_plan_id = canonical.id
        await old_record.asave(update_fields=["canonical_plan_id", "updated_at"])

    @sync_to_async
    def _link_external(self, external_ref: str, canonical: TechnicalPlan) -> None:
        PlanExternalRef.objects.update_or_create(
            external_ref=external_ref,
            defaults={"canonical": canonical},
        )


def chat_codingplan_to_content(coding_plan: Any) -> dict:
    """chat ``CodingPlan`` → 忠实映射 content（满足 validate_technical_plan）。

    ``recommended_repository_ids`` 每个 repo 派生一个 execution_plan task；
    ``affected_files``（``{file_path, change_type}``）映射成 task.files（``{path, action}``）。
    无推荐仓库时给单个占位 task（保证 execution_plan 非空过 validate）。
    """
    title = coding_plan.title or (coding_plan.tech_plan or "")[:80] or "chat 方案"
    summary = (coding_plan.tech_plan or "")[:200] or title
    repo_ids = [str(r) for r in (coding_plan.recommended_repository_ids or []) if str(r)]
    files = [
        {
            "path": str(f.get("file_path", "")),
            "action": _normalize_action(f.get("change_type")),
        }
        for f in (coding_plan.affected_files or [])
        if isinstance(f, dict) and f.get("file_path")
    ]
    instruction = coding_plan.tech_plan or ""
    if repo_ids:
        execution_plan = [
            {
                "id": f"chat-{i}",
                "name": title,
                "repository_id": repo_id,
                "repository_name": repo_id,
                "branch_strategy": "feature",
                "coding_instruction": instruction,
                "files": files,
            }
            for i, repo_id in enumerate(repo_ids)
        ]
    else:
        execution_plan = [
            {
                "id": "chat-0",
                "name": title,
                "repository_id": "",
                "repository_name": "",
                "branch_strategy": "feature",
                "coding_instruction": instruction,
                "files": files,
            }
        ]
    return {"title": title, "summary": summary, "execution_plan": execution_plan}


def mcp_plan_to_content(mcp_plan: Any) -> dict:
    """mcp ``McpWorkItemTechnicalPlan`` → 忠实映射 content（满足 validate_technical_plan）。

    优先复用 ``plan_body``（若已含 execution_plan 列表则归一化补全必填）；否则由
    ``repository_tasks`` 映射成 execution_plan。title/summary 取 ``title`` / ``markdown[:200]``。
    """
    title = mcp_plan.title or "mcp 方案"
    summary = (mcp_plan.markdown or "")[:200] or title
    plan_body = mcp_plan.plan_body if isinstance(mcp_plan.plan_body, dict) else {}

    raw_tasks: list = []
    body_tasks = plan_body.get("execution_plan")
    if isinstance(body_tasks, list) and body_tasks:
        raw_tasks = body_tasks
    elif isinstance(mcp_plan.repository_tasks, list):
        raw_tasks = mcp_plan.repository_tasks

    execution_plan = [
        _normalize_exec_task(t, i, title) for i, t in enumerate(raw_tasks) if isinstance(t, dict)
    ]
    if not execution_plan:
        execution_plan = [
            {
                "id": "mcp-0",
                "name": title,
                "repository_id": "",
                "repository_name": "",
                "branch_strategy": "feature",
            }
        ]
    return {"title": title, "summary": summary, "execution_plan": execution_plan}


def _normalize_exec_task(raw: dict, idx: int, default_name: str) -> dict:
    """把半可信 task dict 归一化为合法 execution_plan item（补全必填 + 校正枚举）。

    WR-02 / DOMAIN §5.3「忠实取材」：当 ``plan_body.execution_plan`` 已含
    ``coding_instruction`` / ``files`` / ``dependencies`` 时保真复用（与 chat 取材一致），
    仅在缺失时省略，绝不无条件丢弃。
    """
    task: dict[str, Any] = {
        "id": str(raw.get("id") or f"mcp-{idx}"),
        "name": str(raw.get("name") or raw.get("repository_name") or default_name),
        "repository_id": str(raw.get("repository_id") or ""),
        "repository_name": str(raw.get("repository_name") or ""),
        "branch_strategy": _normalize_branch_strategy(raw.get("branch_strategy")),
    }
    if raw.get("coding_instruction"):
        task["coding_instruction"] = str(raw["coding_instruction"])
    if isinstance(raw.get("files"), list):
        files = [
            {
                "path": str(f.get("path") or f.get("file_path") or ""),
                "action": _normalize_action(f.get("action") or f.get("change_type")),
            }
            for f in raw["files"]
            if isinstance(f, dict) and (f.get("path") or f.get("file_path"))
        ]
        if files:
            task["files"] = files
    if isinstance(raw.get("dependencies"), list):
        deps = [str(d) for d in raw["dependencies"] if d]
        if deps:
            task["dependencies"] = deps
    return task
