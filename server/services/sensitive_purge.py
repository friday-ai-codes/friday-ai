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
    "purge_sensitive_planes",
]

# 敏感清理脱敏占位符（替换命中被排除文件正文的文本段）。
REDACTION_PLACEHOLDER = "[已按敏感清理脱敏 / redacted]"


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


async def _scrub_code_change_archives(repository_id: str, targets: set[str]) -> dict[str, int]:
    """CodeChangeArchive file 级 scrub：剔除被排除文件的 ``files`` 项与 diff 段、重算计数。

    仅含被排除文件的归档整行删除；含他文件的归档保留他文件部分（不误删，T-23-13）。
    """

    def _work() -> dict[str, int]:
        from knowledge.diff_archive import compress_diff, decompress_diff
        from knowledge.models import CodeChangeArchive

        scrubbed = 0
        deleted = 0
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
            kept_segments = [
                seg
                for new_p, old_p, seg in _split_diff_segments(raw)
                if new_p not in targets and old_p not in targets
            ]
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
        return {"scrubbed": scrubbed, "deleted": deleted}

    return await sync_to_async(_work)()


async def _scrub_task_results(repository_id: str, targets: set[str]) -> dict[str, int]:
    """TaskResult 可控清理：经 ``session.repo_url`` 归一匹配本仓的记录，剔除被排除文件。

    关联不确定（repo_url 归一不等于本仓 git_url）的记录**不动**（T-23-12 保守不删）。
    """

    def _work() -> dict[str, int]:
        from repositories.models import Repository
        from subagent.models import TaskResult

        repo = Repository.objects.filter(id=repository_id).first()
        if repo is None:
            return {"scrubbed": 0, "deleted": 0}
        repo_key = _normalize_repo_url(repo.git_url)
        if not repo_key:
            return {"scrubbed": 0, "deleted": 0}

        scrubbed = 0
        qs = TaskResult.objects.select_related("session").all()
        for tr in qs:
            session = tr.session
            if session is None or _normalize_repo_url(session.repo_url) != repo_key:
                continue  # 关联不确定 / 他仓：保守不动

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
        return {"scrubbed": scrubbed, "deleted": 0}

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


async def _scrub_action_logs(repository_id: str, targets: set[str]) -> dict[str, int]:
    """ActionLog payload 脱敏：经 session.repo_url 关联本仓，命中被排除路径的载荷脱敏。"""

    def _work() -> dict[str, int]:
        from repositories.models import Repository
        from subagent.models import ActionLog

        repo = Repository.objects.filter(id=repository_id).first()
        if repo is None:
            return {"scrubbed": 0, "deleted": 0}
        repo_key = _normalize_repo_url(repo.git_url)
        if not repo_key:
            return {"scrubbed": 0, "deleted": 0}

        scrubbed = 0
        for log in ActionLog.objects.select_related("session").all():
            session = log.session
            if session is None or _normalize_repo_url(session.repo_url) != repo_key:
                continue  # 关联不确定 / 他仓：保守不动
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
        return {"scrubbed": scrubbed, "deleted": 0}

    return await sync_to_async(_work)()


async def purge_sensitive_planes(repository_id: str, file_paths: list[str]) -> dict[str, Any]:
    """敏感清理入口：在普通排除清理之上，额外清理操作记录数据面（EXCL-05）。

    23-02 ``run_cleanup(mode="sensitive")`` 在普通清理之后懒导入并 ``await`` 本函数，
    其返回 dict 落入 ``CleanupReport.sensitive`` / ``CleanupRun.sensitive``，经状态端点
    如实回流前端。

    Args:
        repository_id: 仓库 UUID 字符串。
        file_paths: 本轮普通清理已处理的被排除文件路径列表（file 级关联键）。

    Returns:
        dict：``scrubbed``（各面计数）+ ``errors``（逐面隔离的失败）。
        （Task 2 追加 ``unscrubbed`` 与 ``caveat``。）
    """
    repo_id = str(repository_id)
    targets = {p for p in (file_paths or []) if p}

    scrubbed: dict[str, dict[str, int]] = {}
    errors: list[str] = []

    planes = (
        ("code_change_archive", _scrub_code_change_archives),
        ("task_result", _scrub_task_results),
        ("action_log", _scrub_action_logs),
    )
    for name, fn in planes:
        try:
            scrubbed[name] = await fn(repo_id, targets)
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

    return {"scrubbed": scrubbed, "errors": errors}
