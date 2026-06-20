"""全局知识树聚合服务（业务域 → 子域 → 仓库，PageIndex 化）。

浏览树顶层的业务域/子域分组由 LLM 聚类生成并缓存到 CorpusTreeSnapshot：

- **全量聚类**（build_full）：仅首次构建或人工触发；输入全部仓库的根摘要 +
  分面，输出域/子域树。
- **增量归类**（assign_repository）：新仓库接入 / 根摘要实质变化时执行，
  LLM 在现有域结构内为仓库找位置（封闭动作空间：assign 或
  propose_new_subdomain），不允许自由改树——防漂移。
- **人工 pin**（manual_overrides {repo_id: node_id}）：重建/归类时不可改动。

树 JSON 结构（域节点递归）：
    {"id": "d-xxxx", "title": "用户", "summary": "...",
     "children": [...], "repo_ids": ["uuid", ...]}
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid as uuid_mod
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

MAX_DOMAINS = 20
MAX_REPOS_PER_LLM_BATCH = 500
_SUMMARY_SNIPPET = 160


def _new_node_id() -> str:
    return f"d-{uuid_mod.uuid4().hex[:8]}"


def _iter_nodes(tree: list[dict[str, Any]]):
    stack = list(tree)
    while stack:
        node = stack.pop()
        yield node
        stack.extend(node.get("children", []))


def _repo_one_liner(repo: Any) -> str:
    """仓库一句话摘要：优先树 overview，退 ai_summary 文本。"""
    text = ""
    if repo.ai_summary:
        try:
            obj = json.loads(repo.ai_summary)
            text = str(obj.get("overview", ""))
        except (json.JSONDecodeError, TypeError):
            text = str(repo.ai_summary)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_SUMMARY_SNIPPET]


class CorpusTreeService:
    """全局知识树构建/查询——纯 @classmethod async 服务类。"""

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    @classmethod
    async def get_active_tree(cls) -> dict[str, Any] | None:
        """读取当前生效快照；无快照返回 None（调用方走 fallback 分组）。"""
        from repositories.models import CorpusTreeSnapshot

        snapshot = await CorpusTreeSnapshot.objects.filter(is_active=True).afirst()
        if snapshot is None:
            return None
        return {
            "snapshot_id": str(snapshot.id),
            "version": snapshot.version,
            "tree": snapshot.tree,
            "built_by": snapshot.built_by,
            "created_at": snapshot.created_at.isoformat(),
        }

    @classmethod
    async def compute_source_hash(cls) -> str:
        """全仓输入（id/ai_summary/facets）确定性指纹，供 run_page_index 按 hash 跳过重建。

        取材沿用 ``build_full`` 的 ``.only("id","name","ai_summary","facets")``（剔除
        ``_`` 前缀私有 facet 键），按 repo_id 排序后 ``json.dumps(..., sort_keys=True)``
        → ``sha256``。相同仓库集合恒等同值；任一仓 ai_summary / facets 变化 → hash 变化。
        """
        from repositories.models import Repository

        items: list[dict[str, Any]] = []
        async for r in Repository.objects.filter(is_deleted=False).only(
            "id", "name", "ai_summary", "facets"
        ):
            facets = {
                k: v for k, v in (r.facets or {}).items() if not str(k).startswith("_")
            }
            items.append(
                {
                    "id": str(r.id),
                    "ai_summary": r.ai_summary or "",
                    "facets": facets,
                }
            )
        items.sort(key=lambda x: x["id"])
        payload = json.dumps(items, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # 全量聚类
    # ------------------------------------------------------------------

    @classmethod
    async def build_full(cls) -> dict[str, Any]:
        """全量 LLM 聚类构建业务域树（仅首次/人工触发）。

        Returns:
            {"status": "ok", "snapshot_id": ..., "domain_count": ...} 或
            {"status": "failed", "reason": ...}
        """
        from repositories.models import CorpusTreeSnapshot, Repository

        repos = [
            r
            async for r in Repository.objects.filter(is_deleted=False).only(
                "id", "name", "ai_summary", "facets"
            )[:MAX_REPOS_PER_LLM_BATCH]
        ]
        if not repos:
            return {"status": "failed", "reason": "no_repositories"}

        repo_lines = []
        for r in repos:
            facets = {
                k: v for k, v in (r.facets or {}).items() if not k.startswith("_")
            }
            facet_part = f" | {json.dumps(facets, ensure_ascii=False)}" if facets else ""
            repo_lines.append(f"- {r.id} | {r.name} | {_repo_one_liner(r)}{facet_part}")

        tree = await cls._llm_cluster(repo_lines)
        if tree is None:
            return {"status": "failed", "reason": "llm_failed"}

        # 校验 repo_ids 合法性 + 兜底未归类仓库
        valid_ids = {str(r.id) for r in repos}
        assigned: set[str] = set()
        for node in _iter_nodes(tree):
            node.setdefault("id", _new_node_id())
            node.setdefault("children", [])
            node.setdefault("repo_ids", [])
            node["repo_ids"] = [rid for rid in node["repo_ids"] if rid in valid_ids]
            assigned.update(node["repo_ids"])

        unassigned = sorted(valid_ids - assigned)
        if unassigned:
            tree.append(
                {
                    "id": _new_node_id(),
                    "title": "未分类",
                    "summary": "尚未归入任何业务域的仓库",
                    "children": [],
                    "repo_ids": unassigned,
                }
            )

        # 沿用旧快照的人工 pin
        prev = await CorpusTreeSnapshot.objects.filter(is_active=True).afirst()
        overrides = dict(prev.manual_overrides) if prev else {}
        if overrides:
            cls._apply_overrides(tree, overrides)

        # 构建时算得输入指纹，落 snapshot 供下次比对（run_page_index hash 跳过依据）。
        source_hash = await cls.compute_source_hash()
        snapshot = await cls._activate_new_snapshot(
            tree, overrides, built_by="llm_full", source_hash=source_hash
        )
        return {
            "status": "ok",
            "snapshot_id": str(snapshot.id),
            "domain_count": len(tree),
            "unassigned_count": len(unassigned),
            "source_hash": source_hash,
        }

    # ------------------------------------------------------------------
    # 增量归类
    # ------------------------------------------------------------------

    @classmethod
    async def assign_repository(cls, repository_id: str) -> dict[str, Any]:
        """增量归类：在现有域结构内为仓库找位置（封闭动作空间，防漂移）。"""
        from repositories.models import CorpusTreeSnapshot, Repository

        repo = await Repository.objects.filter(id=repository_id).afirst()
        if repo is None:
            return {"status": "failed", "reason": "repo_not_found"}

        snapshot = await CorpusTreeSnapshot.objects.filter(is_active=True).afirst()
        if snapshot is None:
            return {"status": "skipped", "reason": "no_active_snapshot"}

        overrides = dict(snapshot.manual_overrides or {})
        if str(repository_id) in overrides:
            return {"status": "skipped", "reason": "manually_pinned"}

        tree = json.loads(json.dumps(snapshot.tree))  # deep copy

        skeleton_lines: list[str] = []

        def _walk(nodes: list[dict[str, Any]], depth: int) -> None:
            for n in nodes:
                example_count = len(n.get("repo_ids", []))
                skeleton_lines.append(
                    f"{'  ' * depth}- [{n['id']}] {n.get('title', '')}: "
                    f"{n.get('summary', '')}（{example_count} 仓库）"
                )
                _walk(n.get("children", []), depth + 1)

        _walk(tree, 0)

        decision = await cls._llm_assign(
            skeleton_lines, repo.name, _repo_one_liner(repo), repo.facets or {}
        )
        if decision is None:
            return {"status": "failed", "reason": "llm_failed"}

        node_by_id = {n["id"]: n for n in _iter_nodes(tree)}
        action = decision.get("action")
        rid = str(repository_id)

        # 先从旧位置移除
        for node in _iter_nodes(tree):
            if rid in node.get("repo_ids", []):
                node["repo_ids"].remove(rid)

        if action == "assign" and decision.get("node_id") in node_by_id:
            node_by_id[decision["node_id"]].setdefault("repo_ids", []).append(rid)
        elif action == "propose_new_subdomain" and decision.get("parent_id") in node_by_id:
            parent = node_by_id[decision["parent_id"]]
            parent.setdefault("children", []).append(
                {
                    "id": _new_node_id(),
                    "title": str(decision.get("title", "新子域"))[:50],
                    "summary": str(decision.get("summary", ""))[:200],
                    "children": [],
                    "repo_ids": [rid],
                }
            )
        else:
            return {"status": "failed", "reason": f"invalid_decision: {decision}"}

        await cls._activate_new_snapshot(tree, overrides, built_by="incremental")
        logger.info(
            "corpus_tree_repo_assigned",
            repository_id=rid,
            action=action,
        )
        return {"status": "ok", "action": action}

    # ------------------------------------------------------------------
    # 人工修正
    # ------------------------------------------------------------------

    @classmethod
    async def pin_repository(
        cls, repository_id: str, node_id: str
    ) -> dict[str, Any]:
        """人工修正仓库归属并 pin（重建时不可改动）。"""
        from repositories.models import CorpusTreeSnapshot

        snapshot = await CorpusTreeSnapshot.objects.filter(is_active=True).afirst()
        if snapshot is None:
            return {"status": "failed", "reason": "no_active_snapshot"}

        tree = json.loads(json.dumps(snapshot.tree))
        node_by_id = {n["id"]: n for n in _iter_nodes(tree)}
        if node_id not in node_by_id:
            return {"status": "failed", "reason": "node_not_found"}

        rid = str(repository_id)
        for node in _iter_nodes(tree):
            if rid in node.get("repo_ids", []):
                node["repo_ids"].remove(rid)
        node_by_id[node_id].setdefault("repo_ids", []).append(rid)

        overrides = dict(snapshot.manual_overrides or {})
        overrides[rid] = node_id
        await cls._activate_new_snapshot(tree, overrides, built_by="manual")
        return {"status": "ok"}

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    @classmethod
    def _apply_overrides(
        cls, tree: list[dict[str, Any]], overrides: dict[str, str]
    ) -> None:
        node_by_id = {n["id"]: n for n in _iter_nodes(tree)}
        for rid, node_id in overrides.items():
            target = node_by_id.get(node_id)
            if target is None:
                continue
            for node in _iter_nodes(tree):
                if rid in node.get("repo_ids", []):
                    node["repo_ids"].remove(rid)
            target.setdefault("repo_ids", []).append(rid)

    @classmethod
    async def _activate_new_snapshot(
        cls,
        tree: list[dict[str, Any]],
        overrides: dict[str, str],
        *,
        built_by: str,
        source_hash: str = "",
    ):
        from repositories.models import CorpusTreeSnapshot

        prev = await CorpusTreeSnapshot.objects.filter(is_active=True).afirst()
        version = (prev.version + 1) if prev else 1
        snapshot = await CorpusTreeSnapshot.objects.acreate(
            version=version,
            tree=tree,
            manual_overrides=overrides,
            is_active=True,
            built_by=built_by,
            source_hash=source_hash,
        )
        await CorpusTreeSnapshot.objects.filter(is_active=True).exclude(
            id=snapshot.id
        ).aupdate(is_active=False)
        return snapshot

    @classmethod
    async def _llm_cluster(cls, repo_lines: list[str]) -> list[dict[str, Any]] | None:
        """全量聚类 LLM 调用。"""
        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.llm_factory import build_chat_model
        from services.provider_config import ProviderConfigService, ProviderMissingError

        # 无参调用走四层兜底的最后一层：系统 default ProviderCredential
        resolved = await ProviderConfigService.aresolve_or_error()
        if isinstance(resolved, ProviderMissingError):
            return None
        model_name = (resolved.extra or {}).get("default_model", "")
        if not model_name:
            logger.warning("corpus_tree_default_model_missing")
            return None
        model = build_chat_model(resolved, model_name, streaming=False)

        system = SystemMessage(
            content=(
                "你是研发知识架构师。把仓库清单聚类为「业务域 → 子域」树。\n"
                "切分原则：\n"
                "- 按业务边界（DDD 限界上下文）切分，禁止按技术分层（前端域/后端域不合法）\n"
                "- 子域名称应能出现在 PRD 里（如「用户付费」合法，「用户服务 API 层」不合法）\n"
                f"- 顶层域 5~{MAX_DOMAINS} 个；子域扇出超过 15 时递归再切一层\n"
                "- 每个仓库必须且只归入一个叶子域节点\n"
                "严格输出 JSON 数组（不要 markdown 包裹），递归结构：\n"
                '[{"title": str, "summary": "一句中文域职责", '
                '"children": [...], "repo_ids": [str]}]\n'
                "非叶子节点 repo_ids 留空数组；repo_id 必须从清单中选取。"
            )
        )
        human = HumanMessage(
            content="仓库清单（id | 名称 | 摘要 | 分面）：\n" + "\n".join(repo_lines)
        )
        response = await model.ainvoke([system, human])
        from agents.llm_factory import content_to_text

        return cls._parse_json_array(content_to_text(response.content))

    @classmethod
    async def _llm_assign(
        cls,
        skeleton_lines: list[str],
        repo_name: str,
        repo_summary: str,
        facets: dict[str, Any],
    ) -> dict[str, Any] | None:
        """增量归类 LLM 调用（封闭动作空间）。"""
        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.llm_factory import build_chat_model
        from services.provider_config import ProviderConfigService, ProviderMissingError

        resolved = await ProviderConfigService.aresolve_or_error()
        if isinstance(resolved, ProviderMissingError):
            return None
        model_name = (resolved.extra or {}).get("haiku_model") or (
            resolved.extra or {}
        ).get("default_model", "")
        if not model_name:
            logger.warning("corpus_tree_default_model_missing")
            return None
        model = build_chat_model(resolved, model_name, streaming=False)

        facets_clean = {k: v for k, v in facets.items() if not str(k).startswith("_")}
        system = SystemMessage(
            content=(
                "你是研发知识架构师。在现有业务域树中为新仓库找归属位置。\n"
                "只允许两种动作（严格输出单个 JSON 对象，不要 markdown 包裹）：\n"
                '1. {"action": "assign", "node_id": "现有叶子域节点 id"}\n'
                '2. {"action": "propose_new_subdomain", "parent_id": "现有节点 id", '
                '"title": "新子域名", "summary": "一句职责"}\n'
                "优先 assign；仅当确实归不进任何现有域时才提议新子域。"
                "禁止其它任何形式的树结构修改。"
            )
        )
        human = HumanMessage(
            content=(
                "现有域树：\n" + "\n".join(skeleton_lines) + "\n\n"
                f"新仓库：{repo_name}\n摘要：{repo_summary}\n"
                f"分面：{json.dumps(facets_clean, ensure_ascii=False)}"
            )
        )
        response = await model.ainvoke([system, human])
        from agents.llm_factory import content_to_text

        return cls._parse_json_object(content_to_text(response.content))

    @staticmethod
    def _parse_json_array(raw: str) -> list[Any] | None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\[[\s\S]*\]", raw)
            if not match:
                return None
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
        return data if isinstance(data, list) else None

    @staticmethod
    def _parse_json_object(raw: str) -> dict[str, Any] | None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", raw)
            if not match:
                return None
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
        return data if isinstance(data, dict) else None


__all__ = ["CorpusTreeService"]
