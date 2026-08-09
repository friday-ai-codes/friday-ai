"""commit 历史摄取服务（IDX-01）。

遍历 git 历史，按 commit 产出 RAG 文档（message + author + committed_at + 变更文件路径
摘要），embedding 入 Qdrant 主 collection 并打 ``kind=commit`` payload，使 commit 历史可
被既有 ``search_rag`` chokepoint 语义检索召回，并与代码 chunk 同检索面但可区分/过滤。

关键不变量（per 25-03 PLAN + threat_model）：
- **fail-closed（T-25-08）**：变更文件路径经 Phase 22 ``build_matcher_for_repo`` /
  ``is_excluded`` 过滤；被排除文件（密钥/env）绝不进入变更摘要，且摘要只含路径不内联
  diff 正文。判定异常视为排除。
- **增量（T-25-09）**：记录 ``Repository.commit_index_boundary_sha`` 边界；只索引
  ``boundary..HEAD`` 间的新 commit；boundary 失效（force-push/rebase）回退首轮 bounded
  全量；确定性 uuid5 point id（同 sha 不重复）；**upsert 成功才推进边界**。
- **dedup 面隔离（T-25-10）**：合成 ``file_path=".friday/commits/{sha}"`` + chunk_index=0
  保证既有去重 key 唯一且不被排除规则误命中；``kind=commit`` 供检索侧区分。
- **DoS 兜底（T-25-11）**：首轮 ``--max-count=COMMIT_INDEX_FIRST_RUN_CAP`` 上限 +
  ``--no-merges`` 减量。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from services.embedding import EmbeddingService
from services.exclusion import build_matcher_for_repo, normalize_rel_path
from services.git_platform.base import truncate_diff_lines
from services.qdrant_service import QdrantService

logger = structlog.get_logger(__name__)

# 首轮（无有效边界）全量索引的 commit 数上限，避免超大仓库历史一次性灌爆（per D-01/T-25-11）。
COMMIT_INDEX_FIRST_RUN_CAP = 500
# 增量单批上限（ME-01）：boundary..HEAD 一次最多索引这么多 commit（取最旧的一批），
# 边界推进到本批最新 commit，剩余的下一轮随边界续传——保证 diff-tree 子进程数 / embedding
# 批量 / 内存解析都有界，避免长期未索引后一次性灌入造成 OOM / 超时。
COMMIT_INDEX_INCREMENTAL_CAP = 500
# 变更文件路径摘要最大行数，超出经 truncate_diff_lines 截断（避免巨型 commit 摘要膨胀）。
COMMIT_INDEX_MAX_SUMMARY_LINES = 200
# commit message 入 payload 前的最大行数截断（与摘要复用同一截断 helper）。
COMMIT_INDEX_MAX_MESSAGE_LINES = 200

# commit point id 的确定性命名空间：uuid5(namespace, f"{repo_id}:{sha}") 保证同一
# (repo, commit) 重索引命中同一 point，不产生重复（与代码 chunk 的 generate_chunk_id 同思路）。
_COMMIT_ID_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc25001")

# git log 字段分隔符（ME-02 健壮性）：commit message 正文（%B）可含任意字节，旧版用
# NUL 分字段、RS(\x1e) 分记录会被正文里的同字节碰撞，导致该 commit 被截断/丢弃。改为：
# - 记录分隔：`git log -z` 用 NUL 终止每条 commit 记录（git 标准做法）；
# - 字段分隔：US(\x1f)，且把 %B 放在**最后一个**字段，解析用 maxsplit=4 把「前 4 个分隔符」
#   之后的全部内容（含正文里的 \x1f / \x1e / 换行）原样归入 body，杜绝正文碰撞丢尾。
# 唯一无法覆盖的极端是正文内嵌 NUL（git 的 -z 机制本身亦无法区分），现实中不会由人/工具产生。
_FIELD_SEP = "\x1f"
_LOG_FORMAT = "%H%x1f%an%x1f%ae%x1f%cI%x1f%B"

_GIT_TIMEOUT = 30.0


class _Commit:
    """单个 commit 的解析结果（轻量值对象）。"""

    __slots__ = ("sha", "author_name", "author_email", "committed_at", "message")

    def __init__(
        self, sha: str, author_name: str, author_email: str, committed_at: str, message: str
    ) -> None:
        self.sha = sha
        self.author_name = author_name
        self.author_email = author_email
        self.committed_at = committed_at
        self.message = message


async def _run_git(args: list[str], cwd: str) -> tuple[int, str, str]:
    """执行 git 子进程，返回 (returncode, stdout, stderr)。沿用 indexer._get_head_sha idiom。"""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_GIT_TIMEOUT)
    return (
        proc.returncode if proc.returncode is not None else -1,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


async def _get_head_sha(repo_path: str) -> str | None:
    """获取 HEAD commit SHA；空仓库 / 失败返回 None。"""
    code, out, _ = await _run_git(["rev-parse", "HEAD"], repo_path)
    if code != 0:
        return None
    sha = out.strip()
    return sha or None


def _parse_log(raw: str) -> list[_Commit]:
    """解析 `git log -z`（_LOG_FORMAT）输出为 commit 列表。

    记录由 NUL 分隔（``-z``）；每条记录前 4 个 ``_FIELD_SEP`` 切出 sha/an/ae/cI，
    剩余全部归 body（``maxsplit=4``），使正文里的分隔字节不再截断该 commit（ME-02）。
    """
    commits: list[_Commit] = []
    for record in raw.split("\x00"):
        if not record.strip():
            continue
        # 仅切前 4 个分隔符；body（最后一段）保留正文内可能出现的 _FIELD_SEP / 旧 RS / 换行。
        fields = record.split(_FIELD_SEP, 4)
        if len(fields) < 5:
            logger.warning("commit_index_parse_skip", reason="malformed_record")
            continue
        sha, an, ae, cI, body = fields[0], fields[1], fields[2], fields[3], fields[4]
        sha = sha.strip()
        if not sha:
            continue
        commits.append(_Commit(sha, an, ae, cI.strip(), body))
    return commits


async def _rev_list(repo_path: str, boundary: str) -> list[str] | None:
    """列出 ``boundary..HEAD`` 的非 merge commit SHA（**oldest-first**）。

    用于增量分批：仅取 SHA（cheap），据此切出「最旧的一批」并定位本批应推进到的边界。
    boundary 失效（force-push/rebase 致 git 报错）返回 None（调用方回退首轮）。
    """
    code, out, err = await _run_git(
        ["rev-list", "--no-merges", "--reverse", f"{boundary}..HEAD"],
        repo_path,
    )
    if code != 0:
        # boundary 不在仓库（force-push/rebase）→ rev-list 报错 → 交由调用方回退首轮。
        logger.warning(
            "commit_index_boundary_invalid",
            boundary=boundary,
            stderr=err.strip()[:200],
        )
        return None
    return [line.strip() for line in out.splitlines() if line.strip()]


async def _read_commits(
    repo_path: str, boundary: str | None, head_sha: str
) -> tuple[list[_Commit], str | None]:
    """读取本轮待索引 commit，并给出「整批成功后应推进到的边界 SHA」。

    增量（boundary 有效）：取 ``boundary..HEAD`` 中**最旧**的 ≤ ``COMMIT_INDEX_INCREMENTAL_CAP``
    个 commit（ME-01 有界），advance_to = 本批最新 commit（整段 ≤ CAP 时即 HEAD）；剩余的
    下一轮随边界续传。
    首轮 / boundary 失效（force-push/rebase）：取**最近** ``COMMIT_INDEX_FIRST_RUN_CAP`` 个
    commit，advance_to = HEAD。

    Returns:
        (commits, advance_to)：advance_to 为本批全部成功入库后边界应推进到的 SHA；
        无 commit / 读取失败时 advance_to 不应被用于推进（调用方仅在 commits 非空时使用）。
    """
    if boundary:
        shas = await _rev_list(repo_path, boundary)
        if shas is not None:
            if not shas:
                return [], head_sha  # 增量已到 HEAD：无新 commit
            if len(shas) > COMMIT_INDEX_INCREMENTAL_CAP:
                # 仅取最旧一批；边界只推进到本批最新，剩余下轮续传（绝不跳过中间 commit）。
                advance_to = shas[COMMIT_INDEX_INCREMENTAL_CAP - 1]
                rng = f"{boundary}..{advance_to}"
            else:
                advance_to = head_sha
                rng = f"{boundary}..HEAD"
            code, out, err = await _run_git(
                ["log", "--no-merges", "-z", f"--format={_LOG_FORMAT}", rng],
                repo_path,
            )
            if code == 0:
                return _parse_log(out), advance_to
            logger.warning("commit_index_log_failed", stderr=err.strip()[:200])
            # 落到首轮回退

    code, out, err = await _run_git(
        [
            "log",
            "--no-merges",
            "-z",
            f"--max-count={COMMIT_INDEX_FIRST_RUN_CAP}",
            f"--format={_LOG_FORMAT}",
            "HEAD",
        ],
        repo_path,
    )
    if code != 0:
        logger.warning("commit_index_log_failed", stderr=err.strip()[:200])
        return [], None
    return _parse_log(out), head_sha


async def _changed_files(repo_path: str, sha: str) -> list[str]:
    """取单个 commit 的变更文件路径列表（含根 commit）。"""
    code, out, err = await _run_git(
        ["diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha],
        repo_path,
    )
    if code != 0:
        logger.warning("commit_index_difftree_failed", sha=sha, stderr=err.strip()[:200])
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def _filter_changed_files(matcher: Any, paths: list[str]) -> list[str]:
    """fail-closed 过滤被排除文件路径（T-25-08）。

    归一化经 ``normalize_rel_path``；归一失败（绝对/越界）或匹配命中 → 剔除；
    matcher 判定抛异常 → 视为排除（绝不进摘要）。
    """
    kept: list[str] = []
    for p in paths:
        rel = normalize_rel_path(p)
        if rel is None:
            continue
        try:
            excluded = matcher.is_excluded(rel)
        except Exception:  # noqa: BLE001 — 判定异常 fail-closed 视为排除（绝不泄漏）
            logger.warning("commit_index_exclusion_failclosed", path=p)
            excluded = True
        if not excluded:
            kept.append(rel)
    return kept


def _build_document(commit: _Commit, changed_files: list[str]) -> tuple[str, str]:
    """构建 commit RAG 文档文本与截断后的 message。

    Returns:
        (doc_text, message_truncated)。doc_text 仅含 message + author + date + 过滤后路径摘要，
        **不内联完整 diff 正文**（避免泄漏被排除文件内容，T-25-08）。
    """
    message_text, _ = truncate_diff_lines(commit.message.strip(), COMMIT_INDEX_MAX_MESSAGE_LINES)
    summary_raw = "\n".join(changed_files)
    summary_text, _ = truncate_diff_lines(summary_raw, COMMIT_INDEX_MAX_SUMMARY_LINES)
    doc_text = "\n".join(
        [
            message_text,
            f"Author: {commit.author_name} <{commit.author_email}>",
            f"Date: {commit.committed_at}",
            "Changed files:",
            summary_text,
        ]
    )
    return doc_text, message_text


def _commit_point_id(repository_id: str, sha: str) -> str:
    """确定性 commit point id（同 repo+sha → 同 id，重索引不重复）。"""
    return str(uuid.uuid5(_COMMIT_ID_NAMESPACE, f"{repository_id}:{sha}"))


async def _collection_is_hybrid() -> bool:
    """判断主 collection 是否 hybrid（决定 commit point 是否需 sparse 向量）。

    复用 IndexerService._is_hybrid_enabled 同一判定口径，避免双份真相。
    """
    from services.indexer import IndexerService

    return await IndexerService._is_hybrid_enabled()


async def _generate_sparse(texts: list[str]) -> list[dict]:
    """生成 BM25 稀疏向量（复用 indexer 路径，避免双份真相）。"""
    from services.indexer import IndexerService

    return await sync_to_async(IndexerService._generate_sparse_vectors)(texts)


async def index_commits(repository_id: str, repo_path: str) -> dict[str, Any]:
    """把 ``repo_path`` 的 commit 历史增量摄取为 kind=commit RAG 文档入 Qdrant。

    流程：读边界 → git log(增量/首轮) → 过滤截断构建文档 → embedding → 构建 hybrid/dense
    point（确定性 uuid5 id）→ upsert → upsert 成功推进 boundary 到 HEAD。

    Args:
        repository_id: 仓库 UUID 字符串。
        repo_path: 本地 git 仓库路径。

    Returns:
        ``{"indexed": n, "head": head_sha, "boundary_from": boundary}``。
        head 为空（空仓库 / rev-parse 失败）时 indexed=0。

    本服务对单 commit 解析失败 log warning 后继续；整体不抛致命异常由 25-04 best-effort
    包裹，但内部对边界推进严格：**仅 upsert 成功才推进 boundary，绝不丢 commit**。
    """
    from repositories.models import Repository

    boundary: str | None = (
        await Repository.objects.filter(id=repository_id)
        .values_list("commit_index_boundary_sha", flat=True)
        .afirst()
    )

    head_sha = await _get_head_sha(repo_path)
    if not head_sha:
        logger.info("commit_index_no_head", repository_id=str(repository_id))
        return {"indexed": 0, "head": None, "boundary_from": boundary}

    commits, advance_to = await _read_commits(repo_path, boundary, head_sha)
    if not commits:
        # 增量已到 HEAD（二次同 HEAD）/ 空范围：无新 commit，不 upsert、不改边界。
        logger.info(
            "commit_index_no_new_commits",
            repository_id=str(repository_id),
            head=head_sha,
            boundary_from=boundary,
        )
        return {"indexed": 0, "head": head_sha, "boundary_from": boundary}

    matcher = await build_matcher_for_repo(repository_id)

    docs: list[str] = []
    payloads: list[dict[str, Any]] = []
    for commit in commits:
        try:
            changed = await _changed_files(repo_path, commit.sha)
            filtered = _filter_changed_files(matcher, changed)
            doc_text, message_text = _build_document(commit, filtered)
        except Exception:  # noqa: BLE001 — 单 commit 解析失败不应中断整体，记 warning 跳过
            logger.warning(
                "commit_index_commit_skip", repository_id=str(repository_id), sha=commit.sha
            )
            continue
        docs.append(doc_text)
        payloads.append(
            {
                "kind": "commit",
                "commit_sha": commit.sha,
                "author_name": commit.author_name,
                "author_email": commit.author_email,
                "committed_at": commit.committed_at,
                "message": message_text,
                "changed_files": filtered,
                # 合成不可被排除路径：保证既有去重 key (repo, file_path, chunk_index) 唯一，
                # 且不被排除规则误命中（T-25-10）。
                "file_path": f".friday/commits/{commit.sha}",
                "chunk_index": 0,
                "content": doc_text,
            }
        )

    if not docs:
        return {"indexed": 0, "head": head_sha, "boundary_from": boundary}

    embeddings = await EmbeddingService.generate_embeddings_batch(docs)
    if len(embeddings) != len(docs):
        # LO-01：供应商异常导致 embedding 列表短于 docs，zip 会静默丢尾 → point 数 < 应索引数，
        # 经下方 succeeded==expected 判定自动「不推进边界」，下次整段重试（uuid5 去重）。
        logger.warning(
            "commit_index_embedding_count_mismatch",
            repository_id=str(repository_id),
            docs=len(docs),
            embeddings=len(embeddings),
        )

    hybrid = await _collection_is_hybrid()
    sparse_vectors: list[dict] | None = None
    if hybrid:
        sparse_vectors = await _generate_sparse(docs)

    points: list[dict[str, Any]] = []
    for i, (payload, embedding) in enumerate(zip(payloads, embeddings)):
        if embedding is None:
            # embedding 失败的 commit 跳过 point（不入库），下次重试（边界未到 HEAD 时）。
            logger.warning(
                "commit_index_embedding_missing",
                repository_id=str(repository_id),
                sha=payload["commit_sha"],
            )
            continue
        if hybrid and sparse_vectors and i < len(sparse_vectors):
            from qdrant_client.http.models import SparseVector

            sparse = sparse_vectors[i]
            vector: Any = {
                "dense": embedding,
                "sparse": SparseVector(indices=sparse["indices"], values=sparse["values"]),
            }
        else:
            vector = embedding
        points.append(
            {
                "id": _commit_point_id(repository_id, payload["commit_sha"]),
                "vector": vector,
                "payload": payload,
            }
        )

    # HI-01：本轮应索引（过滤 --no-merges 后解析出的）commit 数 vs 实际成功入库的 point 数。
    # 任一 commit 在「逐条构建 / embedding / zip」环节被跳过都会使 succeeded < expected。
    expected = len(commits)
    succeeded = len(points)

    if not points:
        # 全部 commit 都被跳过：不 upsert、不推进边界，下次整段重试（uuid5 去重，绝不丢 commit）。
        logger.warning(
            "commit_index_all_skipped_no_advance",
            repository_id=str(repository_id),
            expected=expected,
        )
        return {"indexed": 0, "head": head_sha, "boundary_from": boundary}

    # 写入 kind=commit 前补齐 payload 索引，否则代码检索侧 must_not(kind)
    # 在 hybrid prefetch 上会被 Qdrant 静默忽略。
    collection_name = QdrantService.get_collection_name(str(repository_id))
    await sync_to_async(QdrantService.ensure_kind_payload_index, thread_sensitive=False)(
        collection_name
    )

    ok = await sync_to_async(QdrantService.upsert_vectors)(repository_id, points)
    if not ok:
        # upsert 失败：绝不推进边界，下次重新尝试（不丢 commit，T-25-09）。
        logger.warning(
            "commit_index_upsert_failed",
            repository_id=str(repository_id),
            count=len(points),
        )
        return {"indexed": 0, "head": head_sha, "boundary_from": boundary}

    if succeeded != expected:
        # HI-01：有 commit 被跳过/失败 → 绝不把边界推到 HEAD（否则被跳过的 commit 落在
        # (boundary, HEAD] 内永不重试 → 静默丢 commit）。保持边界，下次整段 boundary..HEAD
        # 重试，确定性 uuid5 point id 保证已成功的不重复（T-25-09 advance-only-on-success）。
        logger.warning(
            "commit_index_partial_skip_no_advance",
            repository_id=str(repository_id),
            expected=expected,
            succeeded=succeeded,
            head=head_sha,
            boundary_from=boundary,
        )
        return {"indexed": succeeded, "head": head_sha, "boundary_from": boundary}

    # ME-01：边界推进到本批的 advance_to（整段 ≤ CAP 时即 HEAD；否则为本批最新，剩余下轮续传）。
    await Repository.objects.filter(id=repository_id).aupdate(commit_index_boundary_sha=advance_to)
    logger.info(
        "commit_index_done",
        repository_id=str(repository_id),
        indexed=succeeded,
        head=head_sha,
        boundary_from=boundary,
        boundary_to=advance_to,
    )
    return {"indexed": succeeded, "head": head_sha, "boundary_from": boundary}
