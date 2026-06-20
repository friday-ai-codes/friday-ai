"""知识树浏览 API（PageIndex 化前端金字塔）。

- GET  /api/repositories/knowledge-tree/            全局树（业务域视角）+ 仓库卡片注册表
- GET  /api/repositories/knowledge-tree/facet/      分面透视视角（?dimension=技术形态）
- GET  /api/repositories/knowledge-tree/search/     树内搜索（命中节点 + 完整祖先路径）
- POST /api/repositories/knowledge-tree/rebuild/    全量重建域树（admin，后台执行）
- POST /api/repositories/knowledge-tree/pin/        人工修正仓库归属并 pin
- GET  /api/repositories/<id>/index-tree/           单仓完整能力树
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from adrf.views import APIView
from rest_framework import serializers, status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response

logger = structlog.get_logger(__name__)


def _repo_card(repo: Any) -> dict[str, Any]:
    """浏览树用的仓库卡片（轻量字段）。"""
    overview = ""
    if repo.ai_summary:
        try:
            overview = str(json.loads(repo.ai_summary).get("overview", ""))[:200]
        except (json.JSONDecodeError, TypeError):
            overview = str(repo.ai_summary)[:200]
    facets = {
        k: v for k, v in (repo.facets or {}).items() if not str(k).startswith("_")
    }
    return {
        "repo_id": str(repo.id),
        "name": repo.name,
        "overview": overview,
        "is_monorepo": repo.is_monorepo,
        "has_tree": bool(repo.ai_summary_tree),
        "index_status": repo.index_status,
        "facets": facets,
    }


async def _load_repo_cards() -> dict[str, dict[str, Any]]:
    from repositories.models import Repository

    cards: dict[str, dict[str, Any]] = {}
    async for repo in Repository.objects.filter(is_deleted=False).only(
        "id", "name", "ai_summary", "ai_summary_tree",
        "is_monorepo", "index_status", "facets",
    ):
        cards[str(repo.id)] = _repo_card(repo)
    return cards


class KnowledgeTreeView(APIView):
    """全局知识树（业务域视角）。无 LLM 快照时按团队归属分面兜底分组。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any) -> Response:
        from codegraph.services.corpus_tree import CorpusTreeService

        cards = await _load_repo_cards()
        active = await CorpusTreeService.get_active_tree()

        if active is not None:
            return Response({
                "view": "domain",
                "has_tree": True,
                "tree": active["tree"],
                "repos": cards,
                "total_repos": len(cards),
                "snapshot": {
                    "version": active["version"],
                    "built_by": active["built_by"],
                    "created_at": active["created_at"],
                },
            })

        # fallback：按团队归属分面分组（确定性，无 LLM）
        groups: dict[str, list[str]] = {}
        for rid, card in cards.items():
            team = card["facets"].get("团队归属") or "未分组"
            groups.setdefault(team, []).append(rid)
        tree = [
            {
                "id": f"team-{idx}",
                "title": team,
                "summary": "",
                "children": [],
                "repo_ids": sorted(rids, key=lambda r: cards[r]["name"]),
            }
            for idx, (team, rids) in enumerate(sorted(groups.items()))
        ]
        return Response({
            "view": "team_fallback",
            "has_tree": False,
            "tree": tree,
            "repos": cards,
            "total_repos": len(cards),
            "snapshot": None,
        })


class KnowledgeTreeFacetView(APIView):
    """分面透视视角：按指定维度分组仓库（树就地重组）。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any) -> Response:
        dimension = str(request.query_params.get("dimension", "")).strip()
        if not dimension:
            return Response(
                {"detail": "dimension 参数必填"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cards = await _load_repo_cards()
        groups: dict[str, list[str]] = {}
        for rid, card in cards.items():
            value = card["facets"].get(dimension) or "未分类"
            groups.setdefault(value, []).append(rid)
        return Response({
            "view": "facet",
            "dimension": dimension,
            "groups": [
                {
                    "value": value,
                    "repo_ids": sorted(rids, key=lambda r: cards[r]["name"]),
                }
                for value, rids in sorted(
                    groups.items(), key=lambda kv: -len(kv[1])
                )
            ],
            "repos": cards,
        })


class KnowledgeTreeSearchView(APIView):
    """树内搜索：repo_index_nodes 节点检索，返回命中节点 + 祖先路径。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any) -> Response:
        query = str(request.query_params.get("q", "")).strip()
        if not query:
            return Response(
                {"detail": "q 参数必填"}, status=status.HTTP_400_BAD_REQUEST
            )
        top_k = min(int(request.query_params.get("top_k", 20)), 50)

        from codegraph.services.repo_router_v2 import RepoRouterV2

        node_hits = await RepoRouterV2._stage0_node_search(query, None)
        results = []
        for hit in node_hits[:top_k]:
            payload = hit.get("payload", {})
            results.append({
                "repository_id": str(payload.get("repository_id", "")),
                "repo_name": str(payload.get("repo_name", "")),
                "node_id": str(payload.get("node_id", "")),
                "node_type": str(payload.get("node_type", "")),
                "title": str(payload.get("title", "")),
                "summary": str(payload.get("summary", "")),
                "node_path": str(payload.get("node_path", "")),
                "sub_project": str(payload.get("sub_project", "")),
                "score": float(hit.get("score", 0.0)),
            })
        return Response({"query": query, "results": results, "total": len(results)})


class KnowledgeTreeRebuildView(APIView):
    """全量重建域树（admin）：经 durable QUEUE_PAGE_INDEX 持久化执行。"""

    permission_classes = [IsAdminUser]

    async def post(self, request: Any) -> Response:
        from codegraph.services.corpus_tree import CorpusTreeService
        from durable import QUEUE_PAGE_INDEX, DurableTaskService

        # 入队点算 target hash：run_page_index 据此 hash 跳过（未变不重建重 LLM 聚类，T-62-05 DoS）。
        target_hash = await CorpusTreeService.compute_source_hash()
        key = "page_index:corpus_tree"
        job_id = await DurableTaskService.defer(
            "durable_page_index",
            {"target_id": "corpus_tree", "target_hash": target_hash},
            queue=QUEUE_PAGE_INDEX,
            idempotency_key=key,
        )
        return Response(
            {"status": "rebuild_started", "job_id": job_id},
            status=status.HTTP_202_ACCEPTED,
        )


class PinRepositorySerializer(serializers.Serializer):
    repository_id = serializers.UUIDField(required=True)
    node_id = serializers.CharField(max_length=64, required=True)


class KnowledgeTreePinView(APIView):
    """人工修正仓库归属并 pin（重建时不可改动）。"""

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any) -> Response:
        serializer = PinRepositorySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from codegraph.services.corpus_tree import CorpusTreeService

        result = await CorpusTreeService.pin_repository(
            str(serializer.validated_data["repository_id"]),
            serializer.validated_data["node_id"],
        )
        if result.get("status") != "ok":
            return Response(result, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)


class RepositoryIndexTreeView(APIView):
    """单仓完整能力树（直接读 ai_summary_tree）。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any, repository_id: str) -> Response:
        from repositories.models import Repository

        repo = await Repository.objects.filter(
            id=repository_id, is_deleted=False
        ).afirst()
        if repo is None:
            return Response(
                {"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND
            )
        return Response({
            "repository_id": str(repo.id),
            "name": repo.name,
            "is_monorepo": repo.is_monorepo,
            "tree": repo.ai_summary_tree or [],
            "facets": {
                k: v
                for k, v in (repo.facets or {}).items()
                if not str(k).startswith("_")
            },
            "stale_state": repo.tree_stale_state or {},
            "ai_summary_status": repo.ai_summary_status,
            "generated_at": (
                repo.ai_summary_generated_at.isoformat()
                if repo.ai_summary_generated_at
                else None
            ),
        })
