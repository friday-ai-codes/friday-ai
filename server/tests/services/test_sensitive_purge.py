"""敏感清理操作记录数据面守护测试（Phase 23 Plan 03，EXCL-05）。

Task 1（三面 file/repo 级清理 + 不误删）：
- ``CodeChangeArchive`` file 级 scrub：含他文件的归档仅剔除被排除文件部分（不误删他文件、
  摘要计数重算）；仅含被排除文件的归档整行删除。
- ``TaskResult``（经 ``session.repo_url`` 归一关联本仓）的 ``modified_files`` 不再含被排除
  文件；关联不确定的记录不被误删（T-23-12）。
- ``ActionLog`` payload 引用被排除文件的正文被脱敏。

Task 2（无精确 file 关联面 + caveat/unscrubbed + 端到端）：见文件后半。
"""

from __future__ import annotations

import hashlib
import zlib
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

pytestmark = pytest.mark.django_db(transaction=True)


def _file_entry(path: str, additions: int = 1, deletions: int = 1) -> dict[str, Any]:
    return {
        "path": path,
        "old_path": path,
        "change_type": "modified",
        "additions": additions,
        "deletions": deletions,
        "is_generated": False,
        "parse_failed": False,
        "hunk_ranges": [],
        "unresolved_symbols": [],
    }


def _file_segment(path: str, body_line: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1,1 +1,1 @@\n"
        "-old\n"
        f"+{body_line}"
    )


def _make_archive(repository: Any, *, files: list[str], secret_path: str) -> Any:
    """构造一条 CodeChangeArchive，diff 含每个文件一段；secret_path 段含敏感正文标记。"""
    from knowledge.models import CodeChangeArchive

    segments = []
    for p in files:
        body = "SECRET_KEY=topsecret" if p == secret_path else "harmless_change"
        segments.append(_file_segment(p, body))
    raw = "\n".join(segments)
    raw_bytes = raw.encode("utf-8")
    compressed = zlib.compress(raw_bytes, 6)
    return CodeChangeArchive.objects.create(
        source_kind="task_result",
        source_id=f"src-{secret_path}-{'-'.join(files)}",
        repository=repository,
        commit_sha=hashlib.sha1("-".join(files).encode()).hexdigest()[:40],
        diff_compressed=compressed,
        diff_size=len(raw_bytes),
        compressed_size=len(compressed),
        diff_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        files=[_file_entry(p) for p in files],
        file_count=len(files),
        total_additions=len(files),
        total_deletions=len(files),
        event_time=timezone.now(),
    )


def _make_session(repo_url: str) -> Any:
    import uuid

    from agents.models import AgentSession
    from subagent.models import SubAgentSession

    main = AgentSession.objects.create(
        session_id=f"main-{uuid.uuid4().hex}",
        status=AgentSession.Status.COMPLETED,
    )
    return SubAgentSession.objects.create(
        session_id=f"sess-{uuid.uuid4().hex}",
        main_session=main,
        repo_url=repo_url,
        task_type=SubAgentSession.TaskType.CODING,
    )


# ============================================================================
# Task 1: CodeChangeArchive / TaskResult / ActionLog 三面
# ============================================================================


async def test_sensitive_archive_scrub_keeps_other_files(repository: Any) -> None:
    """含他文件的归档：被排除文件 files 项/ diff 被剔除、计数重算；他文件保留（不误删）。"""
    from knowledge.diff_archive import decompress_diff
    from knowledge.models import CodeChangeArchive
    from services.sensitive_purge import purge_sensitive_planes

    archive = await sync_to_async(_make_archive)(
        repository, files=["src/secret.py", "src/keep.py"], secret_path="src/secret.py"
    )

    result = await purge_sensitive_planes(str(repository.id), ["src/secret.py"])

    assert result["scrubbed"]["code_change_archive"]["scrubbed"] == 1
    assert result["scrubbed"]["code_change_archive"]["deleted"] == 0

    refreshed = await CodeChangeArchive.objects.aget(id=archive.id)
    paths = [f["path"] for f in refreshed.files]
    assert paths == ["src/keep.py"]  # 他文件保留
    assert refreshed.file_count == 1
    assert refreshed.total_additions == 1
    assert refreshed.total_deletions == 1
    raw = decompress_diff(refreshed.diff_compressed)
    assert "SECRET_KEY" not in raw  # 敏感 diff 段被剔除
    assert "src/keep.py" in raw  # 他文件 diff 保留
    assert refreshed.diff_sha256 == hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def test_sensitive_archive_only_excluded_is_deleted(repository: Any) -> None:
    """仅含被排除文件的归档整行删除。"""
    from knowledge.models import CodeChangeArchive
    from services.sensitive_purge import purge_sensitive_planes

    archive = await sync_to_async(_make_archive)(
        repository, files=["src/secret.py"], secret_path="src/secret.py"
    )

    result = await purge_sensitive_planes(str(repository.id), ["src/secret.py"])

    assert result["scrubbed"]["code_change_archive"]["deleted"] == 1
    assert await CodeChangeArchive.objects.filter(id=archive.id).acount() == 0


async def test_sensitive_archive_unrelated_untouched(repository: Any) -> None:
    """归档不含被排除文件 → 完全不动（不误删）。"""
    from knowledge.models import CodeChangeArchive
    from services.sensitive_purge import purge_sensitive_planes

    archive = await sync_to_async(_make_archive)(
        repository, files=["src/other.py"], secret_path="src/secret.py"
    )

    await purge_sensitive_planes(str(repository.id), ["src/secret.py"])

    refreshed = await CodeChangeArchive.objects.aget(id=archive.id)
    assert refreshed.file_count == 1
    assert [f["path"] for f in refreshed.files] == ["src/other.py"]


async def test_sensitive_task_result_scrubbed_and_unrelated_preserved(repository: Any) -> None:
    """本仓 TaskResult.modified_files 剔除被排除文件；关联不确定记录不动（T-23-12）。"""
    from services.sensitive_purge import purge_sensitive_planes
    from subagent.models import TaskResult

    def _seed() -> tuple[Any, Any]:
        own_session = _make_session(repository.git_url)
        own = TaskResult.objects.create(
            session=own_session,
            result_type=TaskResult.ResultType.GIT,
            modified_files=["src/secret.py", "src/keep.py"],
            raw_output={"modified_files": ["src/secret.py", "src/keep.py"], "note": "ok"},
        )
        other_session = _make_session("https://github.com/other/elsewhere.git")
        other = TaskResult.objects.create(
            session=other_session,
            result_type=TaskResult.ResultType.GIT,
            modified_files=["src/secret.py"],
            raw_output={},
        )
        return own, other

    own, other = await sync_to_async(_seed)()

    result = await purge_sensitive_planes(str(repository.id), ["src/secret.py"])
    assert result["scrubbed"]["task_result"]["scrubbed"] == 1

    own_refreshed = await TaskResult.objects.aget(id=own.id)
    assert own_refreshed.modified_files == ["src/keep.py"]
    assert own_refreshed.raw_output["modified_files"] == ["src/keep.py"]

    # 他仓记录原样保留（保守不删）
    other_refreshed = await TaskResult.objects.aget(id=other.id)
    assert other_refreshed.modified_files == ["src/secret.py"]


async def test_sensitive_action_log_payload_redacted(repository: Any) -> None:
    """本仓 ActionLog payload 引用被排除文件的正文段被脱敏。"""
    from services.sensitive_purge import purge_sensitive_planes
    from subagent.models import ActionLog

    def _seed() -> Any:
        session = _make_session(repository.git_url)
        return ActionLog.objects.create(
            session=session,
            action_type=ActionLog.ActionType.TOOL_CALL,
            timestamp=timezone.now(),
            sequence=0,
            payload={
                "tool": "read_file",
                "input": {"file_path": "src/secret.py"},
                "output": "SECRET_KEY in src/secret.py exposed",
                "keep": "unrelated",
            },
        )

    log = await sync_to_async(_seed)()

    result = await purge_sensitive_planes(str(repository.id), ["src/secret.py"])
    assert result["scrubbed"]["action_log"]["scrubbed"] == 1

    refreshed = await ActionLog.objects.aget(id=log.id)
    assert refreshed.payload["input"]["file_path"] != "src/secret.py"
    assert "src/secret.py" not in refreshed.payload["output"]
    assert refreshed.payload["keep"] == "unrelated"  # 无关字段保留


async def test_sensitive_plane_isolation_on_failure(repository: Any, monkeypatch: Any) -> None:
    """单面失败不中断其余面：errors 记录该面，其余面正常返回。"""
    from services import sensitive_purge
    from services.sensitive_purge import purge_sensitive_planes

    async def _boom(_repo: str, _targets: set[str]) -> dict[str, int]:
        raise RuntimeError("archive boom")

    monkeypatch.setattr(sensitive_purge, "_scrub_code_change_archives", _boom)

    result = await purge_sensitive_planes(str(repository.id), ["src/secret.py"])
    assert any("code_change_archive" in e for e in result["errors"])
    # 其余面仍产出计数
    assert "task_result" in result["scrubbed"]
    assert "action_log" in result["scrubbed"]
