"""敏感清理：操作记录数据面的 file 级 / repo 级可控清理（Phase 23 Plan 03，EXCL-05）。

本模块是 23-02 ``run_cleanup(mode="sensitive")`` 在普通排除清理（删派生索引面）之后
**懒导入并委托**的落点（契约：``from services.sensitive_purge import purge_sensitive_planes``）。
普通排除只删「派生索引面」（Qdrant/ChunkRegistry/codegraph/...），但命中密钥/敏感信息时
还需清理「可能含正文」的操作记录面——这是 EXCL-05 补齐的泄漏面。

数据面关联方式（§9.2/§9.3 数据面矩阵）：

- ``CodeChangeArchive``（**file 级 scrub**）：``repository`` FK + ``files`` JSON（每项 ``path``）
  + ``diff_compressed``（zlib）。含被排除文件的归档 → 剔除该文件的 ``files`` 项与
  diff 段、重算计数；归档仅含被排除文件 → 整行删除；含他文件 → 保留他文件部分（不误删）。
- ``TaskResult``（**repo 级关联**）：经 ``session.repo_url`` 归一匹配本仓 ``git_url``；
  ``modified_files`` 含被排除文件 → 剔除该项 + best-effort scrub ``raw_output.modified_files``；
  关联不确定的记录**不动**（T-23-12 保守，避免误删他仓产物）。
- ``ActionLog``（**repo 级关联**）：同 session 关联；``payload`` 引用被排除 file_path 的
  条目 → 脱敏其文件正文字段（best-effort，逐条隔离）。

边界（§9.1，绝不假装清除不可达的面）：敏感清理承诺「Friday 操作记录中该文件正文不可见
（尽力而为）」，**不承诺** git object / 备份物理消失——应用层不强保证的面只文档化 caveat。

所有 ORM 访问经 ``sync_to_async``（async 约束）；逐面异常隔离（单面失败记 warning + 进
返回 dict 的 ``errors``，不中断其余面）。
"""

from __future__ import annotations

import hashlib
from typing import Any

import structlog
from asgiref.sync import sync_to_async

logger = structlog.get_logger(__name__)

__all__ = [
    "SENSITIVE_PLANES_CAVEAT",
    "purge_sensitive_planes",
]

# 敏感清理脱敏占位符（替换命中被排除文件正文的文本段）。
REDACTION_PLACEHOLDER = "[已按敏感清理脱敏 / redacted]"

# 如实声明敏感清理的范围边界（§9.1，绝不过度承诺）。落入返回 dict 经 run_cleanup /
# 状态端点透传前端：清理只保证「Friday 操作记录中该文件正文尽力而为不可见」，
# 不承诺 git object / 历史 / 备份层物理消失，且无精确 file 关联面为 best-effort 子串脱敏。
SENSITIVE_PLANES_CAVEAT = (
    "敏感清理已尽力清理 Friday 操作记录中的该文件正文（归档 diff / 知识检索面版本正文与"
    "向量 / 任务结果 / 执行轨迹 / 消息正文段）。但请注意：本地 git object 与 Git 历史不承诺物理消失（靠工具层 denylist "
    "兜底）；备份层不在应用层可控范围（基础设施层需手动处理）；prompt snapshot 等无精确文件"
    "关联的面仅做 best-effort 子串脱敏，可能存在残留。如确需彻底清除，请同步处理 Git 历史与备份。"
)

# 无精确 file 关联、应用层不强保证的面——如实上报，不假装清除（T-23-11，§9.3 矩阵）。
UNSCRUBBED_PLANES = ["prompt_snapshot", "backups", "git_objects"]


def _normalize_repo_url(url: str) -> str:
    """归一化仓库 URL，供 ``SubAgentSession.repo_url`` ↔ ``Repository.git_url`` 匹配。

    去末尾斜杠、去 ``.git`` 后缀、小写——容忍 ``https://h/o/r.git`` 与 ``https://H/o/r/``
    等价书写差异。关联是删/脱敏的前置判据，归一不当会误关联他仓（T-23-12）。
    """
    if not url:
        return ""
    s = url.strip().lower()
    s = s.rstrip("/")
    if s.endswith(".git"):
        s = s[: -len(".git")]
    return s


def _coding_session_repo_id(session: Any) -> str | None:
    """经 ``SubAgentSession→CodingSession``（OneToOne）取稳定 ``Repository`` FK（ME-04）。

    存在精确 FK 关联时它是权威归属判据，避免仅靠 ``repo_url`` 归一在「多仓共享同一
    remote」（同仓两条记录 / mirror）时跨仓误清。无关联（过渡期 / 非编码会话）返回 None。
    """
    from django.core.exceptions import ObjectDoesNotExist

    try:
        cs = session.coding_session
    except ObjectDoesNotExist:
        return None
    except Exception:  # noqa: BLE001 — 关联缺失/异常一律降级为"无精确 FK"
        return None
    return str(cs.repository_id) if cs is not None else None


def _repo_ids_sharing_remote(repo_key: str) -> set[str]:
    """归一化 ``git_url`` 等于 ``repo_key`` 的全部 ``Repository`` id（ME-04 共享 remote 探测）。"""
    from repositories.models import Repository

    ids: set[str] = set()
    for rid, git_url in Repository.objects.values_list("id", "git_url"):
        if _normalize_repo_url(git_url or "") == repo_key:
            ids.add(str(rid))
    return ids


def _session_repo_match(
    session: Any, repository_id: str, repo_key: str, *, shared_remote: bool
) -> tuple[bool, bool]:
    """判定 session 是否归属本仓（ME-04）。返回 (是否命中, 是否因共享 remote 歧义而保守跳过)。

    优先用 ``CodingSession.repository`` 稳定 FK 精确判定；无精确 FK 时退回 ``repo_url`` 归一
    匹配，且当多仓共享同一 remote 时保守不动（无法区分归属，避免跨仓 over-scrub）。
    """
    coding_repo_id = _coding_session_repo_id(session)
    if coding_repo_id is not None:
        return coding_repo_id == str(repository_id), False
    if _normalize_repo_url(session.repo_url) != repo_key:
        return False, False
    if shared_remote:
        return False, True  # 共享 remote 且无精确 FK → 保守跳过并如实披露
    return True, False


def _entry_path(entry: Any) -> str:
    """从 ``modified_files`` 单项取文件路径（容忍 str 或 dict 两种形态）。"""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        for key in ("path", "file", "filename", "file_path"):
            val = entry.get(key)
            if isinstance(val, str):
                return val
    return ""


def _split_diff_segments(raw: str) -> list[tuple[str, str, str]]:
    """把拼接的 unified diff 原文按 ``diff --git`` 边界切成 ``(new_path, old_path, segment)``。

    归档原文形态见 ``knowledge.diff_archive._assemble_raw_diff``：逐文件
    ``diff --git a/{old} b/{new}\\n--- ...\\n+++ ...\\n{diff}``，以 ``\\n`` 拼接。
    本函数据此还原出每个文件段及其新/旧路径，供 file 级 scrub 精确剔除目标文件段。
    """
    segments: list[tuple[str, str, str]] = []
    buf: list[str] = []
    new_path = ""
    old_path = ""

    def _parse_paths(header: str) -> tuple[str, str]:
        # header 形如 "diff --git a/<old> b/<new>"
        body = header[len("diff --git ") :]
        marker = " b/"
        idx = body.find(marker)
        if idx == -1:
            return "", ""
        a_part = body[:idx]
        new = body[idx + len(marker) :]
        old = a_part[2:] if a_part.startswith("a/") else a_part
        return new, old

    for line in raw.split("\n"):
        if line.startswith("diff --git "):
            if buf:
                segments.append((new_path, old_path, "\n".join(buf)))
            buf = [line]
            new_path, old_path = _parse_paths(line)
        else:
            buf.append(line)
    if buf:
        segments.append((new_path, old_path, "\n".join(buf)))
    return segments


async def _scrub_code_change_archives(repository_id: str, targets: set[str]) -> dict[str, Any]:
    """CodeChangeArchive file 级 scrub：剔除被排除文件的 ``files`` 项与 diff 段、重算计数。

    仅含被排除文件的归档整行删除；含他文件的归档保留他文件部分（不误删，T-23-13）。
    HI-03：含他文件归档剔除 diff 段后做后置不变量校验（被剔除段数 == 命中 files 项数），
    不一致则保守保留原归档并记 ``errors``，绝不在未确认正文剔除时回写"已 scrub"的 metadata。
    """

    def _work() -> dict[str, Any]:
        from knowledge.diff_archive import compress_diff, decompress_diff
        from knowledge.models import CodeChangeArchive

        scrubbed = 0
        deleted = 0
        errors: list[str] = []
        for archive in CodeChangeArchive.objects.filter(repository_id=repository_id):
            files = archive.files or []
            hit = [
                f
                for f in files
                if isinstance(f, dict)
                and (f.get("path") in targets or f.get("old_path") in targets)
            ]
            if not hit:
                continue

            remaining = [f for f in files if f not in hit]
            if not remaining:
                # 归档仅含被排除文件 → 整行删除
                archive.delete()
                deleted += 1
                logger.info(
                    "purge.sensitive_plane",
                    plane="code_change_archive",
                    repository_id=repository_id,
                    scrubbed=0,
                    deleted=1,
                )
                continue

            # 含他文件：剔除被排除文件的 diff 段 + 重算计数
            try:
                raw = decompress_diff(archive.diff_compressed)
            except Exception:  # noqa: BLE001 — 解压失败：不冒险写坏归档，保守跳过该行
                logger.warning(
                    "purge.sensitive_decompress_failed",
                    repository_id=repository_id,
                    archive_id=str(archive.id),
                    exc_info=True,
                )
                continue
            segments = _split_diff_segments(raw)
            kept_segments = [
                seg
                for new_p, old_p, seg in segments
                if new_p not in targets and old_p not in targets
            ]
            removed_count = sum(
                1 for new_p, old_p, _seg in segments if new_p in targets or old_p in targets
            )
            # HI-03 后置不变量：被剔除的 diff 段数必须与命中的 files 项数一致。不一致
            # 意味着路径解析偏差（含空格/git 引号转义）、格式漂移或归档截断——此刻无法
            # 确认被排除文件正文已从 diff_compressed 剔除。绝不回写"已 scrub"的 metadata
            # （否则元数据声称剔除而正文残留 = 静默 under-scrub）；保守保留原归档行不动，
            # 记 errors 让上层如实披露。
            if removed_count != len(hit):
                logger.warning(
                    "purge.sensitive_archive_scrub_mismatch",
                    repository_id=repository_id,
                    archive_id=str(archive.id),
                    hit_count=len(hit),
                    removed_segments=removed_count,
                )
                errors.append(
                    f"{archive.id}:segment_mismatch(hit={len(hit)},removed={removed_count})"
                )
                continue
            new_raw = "\n".join(kept_segments)
            raw_bytes = new_raw.encode("utf-8")
            compressed = compress_diff(new_raw)

            archive.files = remaining
            archive.file_count = len(remaining)
            archive.total_additions = sum(int(f.get("additions", 0) or 0) for f in remaining)
            archive.total_deletions = sum(int(f.get("deletions", 0) or 0) for f in remaining)
            archive.diff_compressed = compressed
            archive.diff_size = len(raw_bytes)
            archive.compressed_size = len(compressed)
            archive.diff_sha256 = hashlib.sha256(raw_bytes).hexdigest()
            archive.save(
                update_fields=[
                    "files",
                    "file_count",
                    "total_additions",
                    "total_deletions",
                    "diff_compressed",
                    "diff_size",
                    "compressed_size",
                    "diff_sha256",
                ]
            )
            scrubbed += 1
            logger.info(
                "purge.sensitive_plane",
                plane="code_change_archive",
                repository_id=repository_id,
                scrubbed=1,
                deleted=0,
            )
        result: dict[str, Any] = {"scrubbed": scrubbed, "deleted": deleted}
        if errors:
            result["errors"] = errors
        return result

    return await sync_to_async(_work)()


def _scrub_diff_section(content: str, targets: set[str]) -> tuple[str, bool]:
    """剔除知识实体版本 content 内 ``## diff`` 段中被排除文件的 diff 段（HI-01）。

    content 结构见 ``knowledge.diff_archive.build_code_change_content``：
    ``{title}\\n\\n## 变更摘要\\n{...}\\n\\n## diff\\n{逐文件段}``。仅当能可靠按
    ``diff --git`` 边界切段且确有命中段被剔除时做精确剔除；否则（无 diff 段结构 /
    diff 段被预算截断 / 切段未命中任何目标但子串确实出现）保守把整个 ``## diff`` 段
    替换为占位符——绝不在无法确认正文剔除时保留残留正文。返回 (新 content, 是否改动)。
    """
    marker = "\n\n## diff\n"
    idx = content.find(marker)
    if idx == -1:
        # 无标准 diff 段结构（格式漂移）：保守对命中叶子整体占位
        return _redact_value(content, targets)
    head = content[: idx + len(marker)]
    diff_body = content[idx + len(marker) :]
    # diff 段被 build_code_change_content 预算截断时无法可靠切段 → 整段占位
    if "[diff truncated" in diff_body:
        return head + REDACTION_PLACEHOLDER, True
    segments = _split_diff_segments(diff_body)
    kept = [seg for new_p, old_p, seg in segments if new_p not in targets and old_p not in targets]
    removed = [seg for new_p, old_p, seg in segments if new_p in targets or old_p in targets]
    if not removed:
        # 子串命中但段切割未匹配（路径含空格/格式漂移）→ 保守整段占位，绝不留残留
        return head + REDACTION_PLACEHOLDER, True
    return head + "\n".join(kept), True


async def _scrub_code_change_knowledge(repository_id: str, targets: set[str]) -> dict[str, Any]:
    """KnowledgeEntityVersion（code_change 实体）残留清理（HI-01）。

    归档 diff 在 Phase 13 被复制进 ``KnowledgeEntityVersion.content``（embedding 输入）
    并向量化进知识检索面；仅 scrub ``CodeChangeArchive.diff_compressed`` 会漏掉这份
    DB 明文 + 向量残留（普通 ``purge_file`` 按 file_path payload 删，亦兜不住以 archive
    维度为键的 code_change 知识向量）。本面定位本仓 code_change 实体版本，剔除被排除
    文件的 ``## diff`` 段（无法精确切割时整段保守占位），并删除其向量（避免残留正文
    经知识检索召回），置 ``vector_synced=False``。
    """

    def _work() -> tuple[int, list[str], list[str]]:
        from knowledge.models import KnowledgeEntityVersion

        scrubbed = 0
        point_ids_to_delete: list[str] = []
        errors: list[str] = []
        qs = KnowledgeEntityVersion.objects.filter(
            entity__repository_id=repository_id,
            entity__kind="code_change",
        ).select_related("entity")
        for ver in qs:
            content = ver.content or ""
            if not any(t and t in content for t in targets):
                continue
            new_content, changed = _scrub_diff_section(content, targets)
            point_ids = [str(pid) for pid in (ver.qdrant_point_ids or []) if pid]
            if not changed and not point_ids:
                continue
            ver.content = new_content
            ver.content_hash = hashlib.sha256(new_content.encode("utf-8")).hexdigest()
            ver.qdrant_point_ids = []
            ver.vector_synced = False
            ver.save(update_fields=["content", "content_hash", "qdrant_point_ids", "vector_synced"])
            point_ids_to_delete.extend(point_ids)
            scrubbed += 1
            logger.info(
                "purge.sensitive_plane",
                plane="code_change_knowledge",
                repository_id=repository_id,
                scrubbed=1,
                deleted=0,
            )
        return scrubbed, point_ids_to_delete, errors

    scrubbed, point_ids, errors = await sync_to_async(_work)()

    # 删向量（DB 明文已 scrub；向量删除失败如实记 error，避免静默残留于检索面）
    if point_ids:
        try:
            from knowledge.vector_ops import delete_points

            await delete_points(point_ids)
        except Exception as exc:  # noqa: BLE001 — 向量删除失败不回滚 DB scrub，但如实上报
            logger.warning(
                "purge.sensitive_knowledge_vector_delete_failed",
                repository_id=repository_id,
                point_count=len(point_ids),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            errors.append(f"vector_delete:{type(exc).__name__}")

    result: dict[str, Any] = {"scrubbed": scrubbed, "deleted": 0}
    if errors:
        result["errors"] = errors
    return result


async def _scrub_task_results(repository_id: str, targets: set[str]) -> dict[str, Any]:
    """TaskResult 可控清理：关联本仓的记录剔除被排除文件（ME-04 收敛到 Repository 维度）。

    优先经 ``CodingSession.repository`` 稳定 FK 精确归属；无精确 FK 时退回 ``repo_url`` 归一
    匹配，多仓共享同一 remote 时保守不动并如实计入 ``unscrubbed``（避免跨仓 over-scrub）。
    关联不确定的记录一律**不动**（T-23-12 保守不删）。
    """

    def _work() -> dict[str, Any]:
        from repositories.models import Repository
        from subagent.models import TaskResult

        repo = Repository.objects.filter(id=repository_id).first()
        if repo is None:
            return {"scrubbed": 0, "deleted": 0}
        repo_key = _normalize_repo_url(repo.git_url)
        if not repo_key:
            return {"scrubbed": 0, "deleted": 0}

        shared_remote = len(_repo_ids_sharing_remote(repo_key)) > 1
        scrubbed = 0
        skipped_ambiguous = 0
        qs = TaskResult.objects.select_related("session", "session__coding_session").all()
        for tr in qs:
            session = tr.session
            if session is None:
                continue
            matched, ambiguous = _session_repo_match(
                session, repository_id, repo_key, shared_remote=shared_remote
            )
            if not matched:
                if ambiguous:
                    skipped_ambiguous += 1
                continue  # 关联不确定 / 他仓 / 共享 remote 歧义：保守不动

            changed = False
            modified = tr.modified_files or []
            kept = [e for e in modified if _entry_path(e) not in targets]
            if len(kept) != len(modified):
                tr.modified_files = kept
                changed = True

            # raw_output 内若另存 modified_files 镜像，同步剔除（best-effort）
            raw = tr.raw_output
            if isinstance(raw, dict) and isinstance(raw.get("modified_files"), list):
                raw_kept = [e for e in raw["modified_files"] if _entry_path(e) not in targets]
                if len(raw_kept) != len(raw["modified_files"]):
                    raw["modified_files"] = raw_kept
                    tr.raw_output = raw
                    changed = True

            if changed:
                tr.save(update_fields=["modified_files", "raw_output"])
                scrubbed += 1
                logger.info(
                    "purge.sensitive_plane",
                    plane="task_result",
                    repository_id=repository_id,
                    scrubbed=1,
                    deleted=0,
                )
        result: dict[str, Any] = {"scrubbed": scrubbed, "deleted": 0}
        if skipped_ambiguous:
            result["unscrubbed"] = ["task_result_shared_remote"]
        return result

    return await sync_to_async(_work)()


def _redact_value(value: Any, targets: set[str]) -> tuple[Any, bool]:
    """递归脱敏：任一 str 叶子若含被排除 file_path 子串 → 替换为占位符。

    只动「命中的叶子」，不整体清空载荷（避免过度清理，T-23-13）。返回 (新值, 是否改动)。
    """
    if isinstance(value, str):
        if any(t and t in value for t in targets):
            return REDACTION_PLACEHOLDER, True
        return value, False
    if isinstance(value, dict):
        changed = False
        out: dict[str, Any] = {}
        for k, v in value.items():
            nv, c = _redact_value(v, targets)
            out[k] = nv
            changed = changed or c
        return out, changed
    if isinstance(value, list):
        changed = False
        out_list: list[Any] = []
        for item in value:
            nv, c = _redact_value(item, targets)
            out_list.append(nv)
            changed = changed or c
        return out_list, changed
    return value, False


async def _scrub_action_logs(repository_id: str, targets: set[str]) -> dict[str, Any]:
    """ActionLog payload 脱敏：关联本仓的载荷脱敏（ME-04 收敛到 Repository 维度）。

    优先经 ``CodingSession.repository`` 稳定 FK 精确归属；无精确 FK 时退回 ``repo_url`` 归一
    匹配，多仓共享同一 remote 时保守不动并如实计入 ``unscrubbed``（避免跨仓 over-scrub）。
    """

    def _work() -> dict[str, Any]:
        from repositories.models import Repository
        from subagent.models import ActionLog

        repo = Repository.objects.filter(id=repository_id).first()
        if repo is None:
            return {"scrubbed": 0, "deleted": 0}
        repo_key = _normalize_repo_url(repo.git_url)
        if not repo_key:
            return {"scrubbed": 0, "deleted": 0}

        shared_remote = len(_repo_ids_sharing_remote(repo_key)) > 1
        scrubbed = 0
        skipped_ambiguous = 0
        for log in ActionLog.objects.select_related("session", "session__coding_session").all():
            session = log.session
            if session is None:
                continue
            matched, ambiguous = _session_repo_match(
                session, repository_id, repo_key, shared_remote=shared_remote
            )
            if not matched:
                if ambiguous:
                    skipped_ambiguous += 1
                continue  # 关联不确定 / 他仓 / 共享 remote 歧义：保守不动
            new_payload, changed = _redact_value(log.payload, targets)
            if changed:
                log.payload = new_payload
                log.save(update_fields=["payload"])
                scrubbed += 1
                logger.info(
                    "purge.sensitive_plane",
                    plane="action_log",
                    repository_id=repository_id,
                    scrubbed=1,
                    deleted=0,
                )
        result: dict[str, Any] = {"scrubbed": scrubbed, "deleted": 0}
        if skipped_ambiguous:
            result["unscrubbed"] = ["action_log_shared_remote"]
        return result

    return await sync_to_async(_work)()


async def _scrub_loose_text_planes(repository_id: str, targets: set[str]) -> dict[str, Any]:
    """chat ``Message`` 子串脱敏（HI-02：严格限定本仓作用域，绝不跨仓销毁）。

    历史实现对 ``Message`` 全表无作用域扫描 + 命中即整段叶子替换，会不可逆地销毁其他
    仓库/空间里任何顺带提到被排除路径子串的对话（过度清理 T-23-13 的反向破坏）。本实现
    将作用域收敛到「经 ``CodingSession.repository`` 关联到本仓」的会话消息（与
    ``TaskResult``/``ActionLog`` 的 repo 级作用域一致），无稳定 repo 关联的消息**一律不动**
    （保守不删），并把「无关联消息面」如实计入 ``unscrubbed``（§9.1 诚实披露，绝不假装
    已清不可达面）。命中的会话内仅脱敏命中的文本叶子，不动其余正文。
    """

    def _work() -> int:
        from functools import reduce
        from operator import or_

        from django.db.models import Q

        from chat.models import Conversation, Message

        if not targets:
            return 0

        # 仅本仓关联会话（经 CodingSession.repository 稳定 FK）；无关联会话不纳入作用域。
        conv_ids = list(
            Conversation.objects.filter(coding_sessions__repository_id=repository_id)
            .values_list("id", flat=True)
            .distinct()
        )
        if not conv_ids:
            return 0

        scrubbed_ids: set[Any] = set()

        # content 面：限定本仓会话后 DB 子串过滤逐条脱敏（命中叶子替换为占位符）
        content_q = reduce(or_, (Q(content__contains=t) for t in targets))
        for msg in Message.objects.filter(conversation_id__in=conv_ids).filter(content_q):
            new_content, changed = _redact_value(msg.content, targets)
            if changed:
                msg.content = new_content
                msg.save(update_fields=["content"])
                scrubbed_ids.add(msg.id)

        # parts 面：JSONField 子串无法跨库 portable 过滤 → 在本仓会话内扫非空 parts 逐条
        # Python 判定，只脱敏命中的文本叶子（part 级正文段），不动其余 part（可控）。
        for msg in Message.objects.filter(conversation_id__in=conv_ids).exclude(parts=[]):
            new_parts, changed = _redact_value(msg.parts, targets)
            if changed:
                msg.parts = new_parts
                msg.save(update_fields=["parts"])
                scrubbed_ids.add(msg.id)

        if scrubbed_ids:
            logger.info(
                "purge.sensitive_plane",
                plane="message_text",
                repository_id=repository_id,
                scrubbed=len(scrubbed_ids),
                deleted=0,
            )
        return len(scrubbed_ids)

    count = await sync_to_async(_work)()
    # 无 repo 关联的会话消息无法精确归属本仓 → 一律不动并如实披露（HI-02）。
    return {"scrubbed": count, "deleted": 0, "unscrubbed": ["chat_messages_unscoped"]}


async def purge_sensitive_planes(repository_id: str, file_paths: list[str]) -> dict[str, Any]:
    """敏感清理入口：在普通排除清理之上，额外清理操作记录数据面（EXCL-05）。

    23-02 ``run_cleanup(mode="sensitive")`` 在普通清理之后懒导入并 ``await`` 本函数，
    其返回 dict 落入 ``CleanupReport.sensitive`` / ``CleanupRun.sensitive``，经状态端点
    如实回流前端。

    Args:
        repository_id: 仓库 UUID 字符串。
        file_paths: 本轮普通清理已处理的被排除文件路径列表（file 级关联键）。

    Returns:
        dict：``scrubbed``（各面计数）+ ``unscrubbed``（应用层不强保证/无精确关联的面）
        + ``caveat``（如实声明 git/备份不承诺物理消失）+ ``errors``（逐面隔离的失败）。
    """
    repo_id = str(repository_id)
    targets = {p for p in (file_paths or []) if p}

    scrubbed: dict[str, dict[str, int]] = {}
    errors: list[str] = []
    extra_unscrubbed: list[str] = []

    planes = (
        ("code_change_archive", _scrub_code_change_archives),
        ("code_change_knowledge", _scrub_code_change_knowledge),
        ("task_result", _scrub_task_results),
        ("action_log", _scrub_action_logs),
        ("message_text", _scrub_loose_text_planes),
    )
    for name, fn in planes:
        try:
            res = await fn(repo_id, targets)
        except Exception as exc:  # noqa: BLE001 — 单面失败不中断其余（逐面隔离）
            logger.warning(
                "purge.sensitive_plane_failed",
                plane=name,
                repository_id=repo_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            errors.append(f"{name}:{type(exc).__name__}:{exc}")
            scrubbed[name] = {"scrubbed": 0, "deleted": 0}
            continue
        # 逐面级 errors / unscrubbed 上浮到顶层（诚实披露：HI-01/HI-02/HI-03）
        plane_errors = res.pop("errors", None)
        if plane_errors:
            errors.extend(f"{name}:{e}" for e in plane_errors)
        plane_unscrubbed = res.pop("unscrubbed", None)
        if plane_unscrubbed:
            extra_unscrubbed.extend(plane_unscrubbed)
        scrubbed[name] = res

    # 去重保序合并应用层不强保证的面（静态面 + 逐面如实上报的面）
    merged_unscrubbed = list(UNSCRUBBED_PLANES)
    for plane in extra_unscrubbed:
        if plane not in merged_unscrubbed:
            merged_unscrubbed.append(plane)

    return {
        "scrubbed": scrubbed,
        "unscrubbed": merged_unscrubbed,
        "caveat": SENSITIVE_PLANES_CAVEAT,
        "errors": errors,
    }
