"""
Space and repository query tools for the Agent.

Provides tools for querying space data, repository information,
and semantic code search via Qdrant vectors.
"""

import uuid as _uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from agents.tools.base import ToolResult, tool
from projects.models import Space
from repositories.models import Repository
from services.exclusion import build_matcher_for_repo, log_exclusion_blocked

logger = structlog.get_logger(__name__)

# RAG-02 召回留痕采样上限：AI 对话链召回内容按 top-N 写 RetrievalTrace，
# 避免每 chunk 一行撑爆留痕表（§A.4 基数控制 / T-72-04-04）。
_RETRIEVAL_TRACE_SAMPLE_LIMIT = 10

# 空间级检索：超过该阈值的已索引仓数量时，先用 L1 仓库路由（repo_summaries /
# repo_index_nodes 纯向量，无 LLM）收敛到 Top-K 相关仓再深检索——避免对空间内
# 全部仓库逐个 Qdrant 查询导致 turn 过长被客户端/网关超时中断（network error）。
_SPACE_ROUTE_THRESHOLD = 8
_SPACE_ROUTE_TOPK = 6
# 路由不可用时的硬上限：兜底截断候选仓，绝不无界扇出。
_SPACE_REPO_HARD_CAP = 20


def _is_valid_uuid(value: str | None) -> bool:
    """宽松校验 UUID：LLM 偶尔把非 UUID（如 "auto"）传进 space_id/repository_id，
    直接喂给 ``aget(id=...)`` 会抛 ValidationError → 工具 500。先校验避免崩溃。"""
    if not value:
        return False
    try:
        _uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


async def _route_space_repos(query: str, repo_ids: list[str]) -> list[str]:
    """空间级检索的 L1 仓库路由：把候选仓收敛到 Top-K 最相关仓（纯向量，无 LLM）。

    复用 ``RepoRouterV2``（Stage-0，repo_index_nodes / repo_summaries 检索）。任何
    失败都 fail-soft：退回"硬上限截断"的候选子集，绝不抛、绝不无界扇出。
    """
    routed: list[str] = []
    try:
        from codegraph.services.repo_router_v2 import RepoRouterV2

        result = await RepoRouterV2.route(
            query, repository_ids=repo_ids, top_k=_SPACE_ROUTE_TOPK, use_llm=False
        )
        candidate_set = {str(c.repo_id) for c in result.candidates}
        routed = [rid for rid in repo_ids if rid in candidate_set]
        logger.info(
            "space_repo_routing",
            category="sampling",
            component="rag",
            candidate_count=len(repo_ids),
            routed_count=len(routed),
            router_version=getattr(result, "router_version", ""),
        )
    except Exception as e:  # noqa: BLE001 — 路由失败不阻塞检索
        logger.warning("space_repo_routing_failed", error=str(e))

    if routed:
        return routed[:_SPACE_ROUTE_TOPK]
    # 路由无命中/失败：硬上限截断，bound 扇出（绝不对全空间逐仓查询）。
    return repo_ids[:_SPACE_REPO_HARD_CAP]


async def _filter_excluded_results(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """EXCL-02 兜底过滤：剔除命中排除规则的结果项（防御未来不经 search_rag 的旁路回流）。

    search_rag 已是 RAG 单一 chokepoint 并已过滤；此处对 ``file_path`` 再做一道
    per-repo 匹配器过滤——匹配器构造 / 判定异常一律 fail-closed（丢弃该项）。
    """
    matchers: dict[str, Any] = {}
    kept: list[dict[str, Any]] = []
    for item in results:
        repo_id = str(item.get("repository_id", ""))
        if repo_id not in matchers:
            try:
                matchers[repo_id] = await build_matcher_for_repo(repo_id)
            except Exception:  # noqa: BLE001 — 构造失败一律 fail-closed
                logger.warning("exclusion.matcher_build_failed", repository_id=repo_id)
                matchers[repo_id] = None
        matcher = matchers[repo_id]
        file_path = str(item.get("file_path", ""))
        try:
            excluded = matcher is None or matcher.is_excluded(file_path)
        except Exception:  # noqa: BLE001 — 判定异常 → 丢弃该项（fail-closed）
            excluded = True
        if excluded:
            log_exclusion_blocked(
                surface="search_repository_code",
                repository_id=repo_id,
                rel_path=file_path,
            )
            continue
        kept.append(item)
    return kept


@tool(
    name="list_space_repositories",
    description=(
        "List all repositories linked to a space. "
        "Use this to discover available code repositories before searching code."
    ),
    category="PROJECT",
    parameters={
        "type": "object",
        "properties": {
            "space_id": {
                "type": "string",
                "description": "UUID of the space to query",
            },
        },
        "required": ["space_id"],
    },
)
async def list_space_repositories(space_id: str) -> ToolResult:
    """
    List all repositories associated with a space.

    Args:
        space_id: UUID of the space

    Returns:
        ToolResult with list of repositories and their metadata
    """
    logger.info("list_space_repositories", space_id=space_id)

    if not _is_valid_uuid(space_id):
        return ToolResult(
            success=True,
            output={
                "data": {"repositories": []},
                "error": f"Invalid space_id (must be a UUID): {space_id!r}",
            },
        )

    try:
        # Async query for space
        project = await Space.objects.aget(id=space_id)
    except Space.DoesNotExist:
        logger.warning("project_not_found", space_id=space_id)
        return ToolResult(
            success=True,
            output={
                "data": {"repositories": []},
                "error": f"Space not found: {space_id}",
            },
        )

    # 省 token：只暴露对「选哪个仓库」有用的字段——id（后续工具调用需要）、name、
    # index_status、以及截断后的描述。git_url / platform / default_branch 对 LLM 推理
    # 基本无用，且 overview_text（仓库摘要）可能上千字，全量塞进上下文是浪费。
    def _short_desc(text: str | None) -> str:
        t = (text or "").strip()
        return t[:240] + "…" if len(t) > 240 else t

    repositories = [
        {
            "id": str(repo.id),
            "name": repo.name,
            "index_status": repo.index_status,
            "description": _short_desc(repo.overview_text),
        }
        async for repo in Repository.objects.filter(
            spaces=project,
            is_deleted=False,
        ).select_related()
    ]

    logger.info(
        "list_space_repositories_success",
        space_id=space_id,
        count=len(repositories),
    )

    return ToolResult(
        success=True,
        output={
            "data": {
                "space_id": str(space_id),
                "space_name": project.name,
                "repositories": repositories,
            },
            "metadata": {
                "count": len(repositories),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
        },
    )


@tool(
    name="get_repository_info",
    description=(
        "Get detailed information about a specific repository. "
        "Includes index status, space associations, and metadata."
    ),
    category="PROJECT",
    parameters={
        "type": "object",
        "properties": {
            "repository_id": {
                "type": "string",
                "description": "UUID of the repository to query",
            },
        },
        "required": ["repository_id"],
    },
)
async def get_repository_info(repository_id: str) -> ToolResult:
    """
    Get detailed information about a repository.

    Args:
        repository_id: UUID of the repository

    Returns:
        ToolResult with repository details and space associations
    """
    logger.info("get_repository_info", repository_id=repository_id)

    try:
        # Async query for repository
        repo = await Repository.objects.aget(id=repository_id, is_deleted=False)
    except Repository.DoesNotExist:
        logger.warning("repository_not_found", repository_id=repository_id)
        return ToolResult(
            success=True,
            output={
                "data": None,
                "error": f"Repository not found: {repository_id}",
            },
        )

    # Use async for M2M space query
    projects = [{"id": str(p.id), "name": p.name} async for p in repo.spaces.all()]

    logger.info(
        "get_repository_info_success",
        repository_id=repository_id,
        space_count=len(projects),
    )

    return ToolResult(
        success=True,
        output={
            "data": {
                "id": str(repo.id),
                "name": repo.name,
                "git_url": repo.git_url,
                "git_platform": repo.git_platform,
                "default_branch": repo.default_branch,
                "description": repo.overview_text,
                "index_status": repo.index_status,
                "last_indexed_at": (
                    repo.last_indexed_at.isoformat() if repo.last_indexed_at else None
                ),
                "created_at": repo.created_at.isoformat(),
                "updated_at": repo.updated_at.isoformat(),
                "projects": projects,
            },
            "metadata": {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
        },
    )


@tool(
    name="search_repository_code",
    description=(
        "向已索引仓库做混合代码检索（dense embedding + BM25 sparse + 符号精确匹配 + 图谱扩展）。\n"
        "Requires at least one of repository_id or space_id.\n\n"
        "⚠️ **使用规范（这是工具效果的关键 - 错用会一直拿到 0 结果）**：\n"
        "  混合检索对**单一概念的精准 query** 效果最好，对**多关键词堆**效果灾难性差。\n\n"
        "  ✅ 正确：一次搜一个概念，多概念分多次调用\n"
        "      query='studyRoom'       # 找入口模块\n"
        "      query='UserService'     # 找类\n"
        "      query='POST /api/login' # 找接口\n"
        "      query='entrance'        # 找跳转参数\n\n"
        "  ❌ 错误：多概念混搜（系统观察到的真实失败 case）\n"
        "      query='studyRoom views classroom report friends shareRoom'  # 9 词混搜 → 0 结果\n"
        "      query='书房 入口 跳转 错题本'                                  # 多中文概念 → 0 结果\n"
        "      query='页面跳转'                                             # 太泛的描述词 → 召回差\n\n"
        "  调优：\n"
        "    - 优先用代码符号（驼峰命名、文件路径片段、API 路径、类名）做 query\n"
        "    - 中文需求先拆成 1-3 个英文 / 拼音关键词分别搜\n"
        "    - 0 结果时**不要原样重试** —— 阅读返回的 ⚠️ 诊断提示按建议调整\n"
        "    - 想要更宽召回时把 min_score 降到 0.3（默认 0.5 对低分相关结果会一刀切）\n\n"
        "Counterpart: if you have a CONCRETE starting point "
        "(file / chunk_id / symbol_name), use `find_related_code` instead — "
        "that tool walks the chunk-level graph (CALL/IMPORT/TEST_OF...) and "
        "avoids RAG fuzzy ranking entirely."
    ),
    category="PROJECT",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "**单一概念**的检索 query，建议是一个代码符号 / 短语，"
                    "如 'studyRoom'、'POST /api/login'、'UserService.login'。"
                    "禁止把多个不相关关键词拼在一起（系统会按一个完整 query 处理，导致 0 结果）。"
                ),
            },
            "repository_id": {
                "type": "string",
                "description": "目标仓库 UUID（与 space_id 二选一；指定仓库时检索更聚焦）",
            },
            "space_id": {
                "type": "string",
                "description": "项目 UUID（与 repository_id 二选一；不指定具体仓库时遍历空间下所有已索引仓库）",
            },
            "limit": {
                "type": "integer",
                "description": "最多返回多少条结果（默认 20）",
                "default": 20,
            },
            "min_score": {
                "type": "number",
                "description": (
                    "最小相似度分数阈值（默认 0.5）。"
                    "默认值对 hybrid 分数偏严 —— 拿到 0 结果可降到 0.3 重试，"
                    "但更宽松的阈值会带来更多弱相关结果，需结合 query 质量判断。"
                ),
                "default": 0.5,
            },
            "branch": {
                "type": "string",
                "description": "分支名（可选；未指定时检索默认分支）",
            },
            "conversation_id": {
                "type": "string",
                "description": "会话 UUID (auto-injected)",
            },
        },
        "required": ["query"],
    },
)
async def search_repository_code(
    query: str,
    repository_id: str | None = None,
    space_id: str | None = None,
    limit: int = 20,
    min_score: float = 0.5,
    branch: str | None = None,
    conversation_id: str = "",
) -> ToolResult:
    """
    Perform semantic code search across repositories.

    Args:
        query: Semantic search query
        repository_id: Optional specific repository to search
        space_id: Optional space to search all its repositories
        limit: Maximum results to return
        min_score: Minimum similarity score threshold

    Returns:
        ToolResult with matching code blocks and metadata
    """
    logger.info(
        "search_repository_code",
        query=query[:100],
        repository_id=repository_id,
        space_id=space_id,
        limit=limit,
        min_score=min_score,
    )

    # Validate: at least one scope must be provided
    if not repository_id and not space_id:
        return ToolResult(
            success=False,
            output={"data": {"results": []}, "error": None},
            error="At least one of repository_id or space_id is required",
        )

    # 非 UUID 的 scope（LLM 误传 "auto" 等）直接判空，避免 ORM ValidationError → 500。
    if repository_id and not _is_valid_uuid(repository_id):
        repository_id = None
    if space_id and not _is_valid_uuid(space_id):
        space_id = None
    if not repository_id and not space_id:
        return ToolResult(
            success=True,
            output={"data": {"results": []}, "error": "Invalid repository_id/space_id (must be UUID)"},
        )

    # Collect repository IDs to search.
    #
    # Contract per tool description: repository_id 与 space_id 二选一。当 LLM
    # 显式指定 repository_id 时（意图就是"锁这一个仓库"），必须忽略 chat_runner
    # 自动注入的 space_id —— 否则用户/agent 的"聚焦检索"诉求会被无声扩展成
    # "搜整个空间所有仓库"，命中噪声暴增甚至 0 结果（历史 bug）。
    repo_ids: list[str] = []

    if repository_id:
        try:
            await Repository.objects.aget(id=repository_id, is_deleted=False)
            repo_ids.append(repository_id)
        except Repository.DoesNotExist:
            return ToolResult(
                success=True,
                output={
                    "data": {"results": []},
                    "error": f"Repository not found: {repository_id}",
                },
            )
    elif space_id:
        try:
            project = await Space.objects.aget(id=space_id)
        except Space.DoesNotExist:
            return ToolResult(
                success=True,
                output={
                    "data": {"results": []},
                    "error": f"Space not found: {space_id}",
                },
            )

        project_repo_ids = [
            str(rid)
            async for rid in Repository.objects.filter(
                spaces=project,
                is_deleted=False,
                index_status="indexed",
            ).values_list("id", flat=True)
        ]
        for rid in project_repo_ids:
            rid_str = str(rid)
            if rid_str not in repo_ids:
                repo_ids.append(rid_str)

        # L1 路由收敛：仓库过多时先选 Top-K 相关仓，避免全空间扇出导致超时。
        if len(repo_ids) > _SPACE_ROUTE_THRESHOLD:
            repo_ids = await _route_space_repos(query, repo_ids)

    if not repo_ids:
        return ToolResult(
            success=True,
            output={
                "data": {"results": []},
                "metadata": {
                    "query": query,
                    "total_results": 0,
                    "searched_repositories": 0,
                },
                "error": "No indexed repositories found to search",
            },
        )

    # 统一调用 HybridSearchService (per implementation contract)
    from services.code_intel import get_provider
    from services.retrieval import HybridSearchService

    result = await HybridSearchService(get_provider()).search(
        query,
        repository_ids=repo_ids if repo_ids else None,
        branch_name=branch,
        top_k=limit,
    )

    all_results: list[dict[str, Any]] = []
    final_context = result.final_context
    # 收集 L3 原始返回的最高分（用于 0 结果时诊断 min_score 是否太高）
    l3_top_score: float | None = None
    l3_raw_count = 0
    # 精排信息（reranker / 启发式）由 search_rag 写入 L3 snapshot.extra，
    # 透传到工具结果 metadata 供对话展示「精排了哪一步」。
    rerank_info: dict[str, Any] | None = None

    # 从 L3 层结果提取向量搜索结果 (保持向后兼容的返回格式)
    for layer in result.layers:
        if layer.layer == "L3" and layer.status == "ok":
            l3_raw_count = len(layer.items)
            if isinstance(layer.extra, dict) and layer.extra.get("rerank"):
                rerank_info = layer.extra["rerank"]
            for item in layer.items:
                payload = item.get("payload", {})
                score = item.get("score", 0.0)
                if l3_top_score is None or score > l3_top_score:
                    l3_top_score = score
                if score >= min_score:
                    all_results.append(
                        {
                            "file_path": payload.get("file_path", ""),
                            "content": payload.get("content", ""),
                            "language": payload.get("language", ""),
                            "score": score,
                            "repository_id": item.get("repository_id", ""),
                        }
                    )

    # 如果 L3 为空，回退到 L2 精确匹配
    if not all_results:
        for layer in result.layers:
            if layer.layer == "L2" and layer.status == "ok":
                for item in layer.items:
                    all_results.append(
                        {
                            "file_path": item.get("file_path", ""),
                            "content": f"Symbol: {item['name']} ({item['symbol_type']}) - {item.get('signature', '')}",
                            "language": "",
                            "score": 1.0,
                            "repository_id": item.get("repository_id", ""),
                        }
                    )

    # EXCL-02 兜底过滤：剔除被排除文件（防御未来不经 search_rag 的旁路回流，T-22-10）。
    all_results = await _filter_excluded_results(all_results)

    all_results.sort(key=lambda x: x["score"], reverse=True)
    all_results = all_results[:limit]

    logger.info(
        "search_repository_code_success",
        query=query[:50],
        result_count=len(all_results),
        searched_repos=len(repo_ids),
    )

    metadata: dict[str, Any] = {
        "query": query,
        "total_results": len(all_results),
        "searched_repositories": len(repo_ids),
        "min_score": min_score,
        "context": final_context,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    if rerank_info:
        metadata["rerank"] = rerank_info

    # Phase P15：0 结果时主动返回诊断，避免 LLM 原样重试陷入循环。
    # 致敬 Claude Code issue #30150 的 progress metric / 失败诊断思路 —— 与其
    # 让模型猜「为什么没结果」，不如直接告诉它「问题在哪 + 建议怎么改」。
    # 诊断分 3 维：query 形态 / min_score 阈值 / 仓库范围。
    if len(all_results) == 0:
        diagnosis = _diagnose_empty_search(
            query=query,
            min_score=min_score,
            l3_top_score=l3_top_score,
            l3_raw_count=l3_raw_count,
            searched_repos=len(repo_ids),
        )
        metadata["diagnosis"] = diagnosis

    # RAG-02：AI 对话链召回留痕（覆盖 MCP 之外的对话链）。best-effort + top-N 采样
    # （§A.4 基数控制）：只对前 _RETRIEVAL_TRACE_SAMPLE_LIMIT 条命中写 RetrievalTrace
    # （run=None；conversation_id 经注入值透传，user_id/source 由 helper 从 Phase 71
    # contextvars 取；query 原文 + chunk 内容 + score 经 redact_for_ledger 脱敏）。
    # 整段 try/except 绝不影响工具返回（T-72-04-05）。
    try:
        from interactions.ledger import arecord_retrieval_trace
        from interactions.models import RetrievalTrace

        for hit in all_results[:_RETRIEVAL_TRACE_SAMPLE_LIMIT]:
            await arecord_retrieval_trace(
                run=None,
                kind=RetrievalTrace.Kind.CHUNK,
                conversation_id=conversation_id or "",
                payload={
                    "query": query,
                    "file_path": hit.get("file_path", ""),
                    "chunk": hit.get("content", ""),
                    "score": hit.get("score", 0.0),
                },
            )
    except Exception:  # noqa: BLE001 —— 留痕 best-effort，绝不影响工具返回
        pass

    return ToolResult(
        success=True,
        output={
            "data": {"results": all_results},
            "metadata": metadata,
        },
    )


# ============================================================================
# 0 结果诊断
# ============================================================================


_QUERY_KEYWORD_COUNT_THRESHOLD: int = 4
"""query 按空格切分超过该阈值时，触发「多概念混搜」诊断。

经验值：3 个词以内通常是"短语 / 类名 / API 路径"等单一概念；4 个词以上
基本上是 LLM 把多个独立概念拼在一起，hybrid 检索会拉胯。
"""

_QUERY_LOW_SCORE_RATIO: float = 0.7
"""``l3_top_score < min_score * 0.7`` 时认为「分数远低于阈值」—— 此时降阈值也救不回来。"""


def _diagnose_empty_search(
    *,
    query: str,
    min_score: float,
    l3_top_score: float | None,
    l3_raw_count: int,
    searched_repos: int,
) -> dict[str, Any]:
    """诊断 0 结果搜索的根因，返回结构化提示 + 建议行动。

    LLM 拿到这份诊断后应该明确知道下一步该做什么（拆 query / 降阈值 / 换工具），
    而不是简单地"再试一次"。
    """
    keyword_count = len([w for w in query.split() if w.strip()])
    has_uppercase_symbol = any(c.isupper() for c in query)
    has_dotted_id = "." in query and any(c.isalpha() for c in query)
    is_pure_lowercase_words = not has_uppercase_symbol and not has_dotted_id and keyword_count >= 2

    issues: list[str] = []
    suggestions: list[str] = []

    if keyword_count >= _QUERY_KEYWORD_COUNT_THRESHOLD:
        issues.append(
            f"query 包含 {keyword_count} 个空格分隔的词，"
            f"看起来是多个独立概念混搜 —— hybrid 检索对此效果灾难性差。"
        )
        suggestions.append(
            f"把 query 拆成 {min(keyword_count, 5)} 个独立调用，每次只搜一个概念。"
            f"例如：'{query.split()[0]}' / '{query.split()[1]}' / ..."
        )

    if is_pure_lowercase_words and keyword_count >= 2:
        issues.append(
            "query 全是小写自然语言词，没有可被 L2 精确匹配的代码符号"
            "（PascalCase 类名、camelCase 函数名、点号分隔标识符）。"
        )
        suggestions.append(
            "改用具体的代码层符号做 query，例如 'StudyRoom' 而不是 'study room'，"
            "'UserService.login' 而不是 'user login'。"
        )

    if l3_raw_count > 0 and l3_top_score is not None and l3_top_score < min_score:
        gap = min_score - l3_top_score
        if l3_top_score < min_score * _QUERY_LOW_SCORE_RATIO:
            issues.append(
                f"L3 hybrid 搜索召回了 {l3_raw_count} 条候选，但最高分仅 "
                f"{l3_top_score:.3f}，远低于 min_score={min_score:.2f} —— "
                f"说明 query 跟仓库内容相关性确实弱，降阈值救不回来。"
            )
            suggestions.append(
                "换更精准的 query（用代码符号），或确认该问题相关的仓库是否真的存在。"
            )
        else:
            issues.append(
                f"L3 hybrid 召回 {l3_raw_count} 条候选，最高分 {l3_top_score:.3f} "
                f"略低于 min_score={min_score:.2f}（差 {gap:.3f}）。"
            )
            suggestions.append("用 min_score=0.3 重试当前 query，可能能拿到弱相关但有用的结果。")

    if l3_raw_count == 0 and searched_repos > 0:
        issues.append(
            f"L3 hybrid 在 {searched_repos} 个仓库里召回 0 条候选 —— "
            f"说明 query 在向量空间里跟所有 chunk 都距离极远。"
        )
        suggestions.append(
            "先用 list_space_structure 或 list_space_repositories 看下仓库内容，"
            "确认 query 用词跟实际代码用词的一致性。"
        )

    if not issues:
        issues.append("query 形态没有明显问题，但确实没找到匹配 —— 可能该问题真的与索引内容无关。")
        suggestions.append(
            "尝试 list_space_repositories 看下当前 space 下有哪些仓库；"
            "也可能需要换用 browse_file_content 直接查看疑似相关文件。"
        )

    return {
        "summary": "⚠️ 检索返回 0 条结果，原因诊断如下：",
        "issues": issues,
        "suggestions": suggestions,
        "query_analysis": {
            "keyword_count": keyword_count,
            "has_uppercase_symbol": has_uppercase_symbol,
            "has_dotted_identifier": has_dotted_id,
            "is_pure_lowercase_words": is_pure_lowercase_words,
        },
        "score_analysis": {
            "min_score_threshold": min_score,
            "l3_raw_candidate_count": l3_raw_count,
            "l3_top_score": l3_top_score,
        },
    }
