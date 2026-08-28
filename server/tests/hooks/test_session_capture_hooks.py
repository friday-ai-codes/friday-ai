"""Phase 145 Wave 0：Claude Code / Cursor 可见问答采集 RED 合同。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

ALLOWED_PAYLOAD_KEYS = {
    "question",
    "answer",
    "git_url",
    "branch_name",
    "session_id",
    "response_model",
    "provider",
    "input_tokens",
    "output_tokens",
    "client",
}
FAKE_TOKEN = "friday-test-pat-never-print"


def _capture_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if "report_session_knowledge" in record.get("url", "")]


def _body(record: dict[str, Any]) -> dict[str, Any]:
    body = record["body"]
    assert isinstance(body, dict)
    return body


def _claude_prompt(session: str, generation: str, cwd: Path, prompt: str = "用户问题") -> dict:
    return {
        "session_id": session,
        "generation_id": generation,
        "cwd": str(cwd),
        "prompt": prompt,
    }


def _claude_stop(session: str, generation: str, cwd: Path, answer: str = "可见答案") -> dict:
    return {
        "session_id": session,
        "generation_id": generation,
        "cwd": str(cwd),
        "last_assistant_message": answer,
    }


def test_helper_builds_shared_payload(
    hook_paths, git_workspaces, run_hook, read_http_records
) -> None:
    """145-01-01 / D-06：两宿主共用白名单 POST 体。"""
    cwd = git_workspaces["clean"]
    run_hook(hook_paths["claude_prompt"], _claude_prompt("s1", "g1", cwd), cwd=cwd)
    result = run_hook(hook_paths["claude_stop"], _claude_stop("s1", "g1", cwd), cwd=cwd)
    assert result.returncode == 0
    records = _capture_records(read_http_records())
    assert records
    body = _body(records[-1])
    assert set(body) <= ALLOWED_PAYLOAD_KEYS
    assert body["question"].strip() and body["answer"].strip()
    assert body["client"] == "claude_code"
    assert {"project_id", "repository_id", "user_email"}.isdisjoint(body)


def test_claude_user_prompt_submit_caches_prompt(
    hook_paths, git_workspaces, run_hook, pending_files
) -> None:
    """145-01-02 / D-01：UPS 缓存 prompt，状态权限收紧且不泄漏。"""
    cwd = git_workspaces["clean"]
    prompt = "不得出现在 stdout 的问题"
    result = run_hook(
        hook_paths["claude_prompt"],
        _claude_prompt("session-a", "generation-a", cwd, prompt),
        cwd=cwd,
    )
    assert result.returncode == 0
    pending = pending_files()
    assert len(pending) == 1
    assert pending[0].stat().st_mode & 0o777 == 0o600
    assert pending[0].parent.stat().st_mode & 0o777 == 0o700
    assert prompt not in result.stdout
    assert str(pending[0]) not in result.stdout
    assert "Bearer" not in result.stdout


def test_claude_stop_posts_visible_answer_on_clean_tree(
    hook_paths, git_workspaces, run_hook, read_http_records, pending_files
) -> None:
    """145-02-01 / D-02：clean tree 仍 Capture，成功后消费 pending。"""
    cwd = git_workspaces["clean"]
    run_hook(hook_paths["claude_prompt"], _claude_prompt("s2", "g2", cwd), cwd=cwd)
    assert pending_files()
    result = run_hook(hook_paths["claude_stop"], _claude_stop("s2", "g2", cwd), cwd=cwd)
    assert result.returncode == 0
    body = _body(_capture_records(read_http_records())[-1])
    assert body["answer"] == "可见答案"
    assert not pending_files()


def test_claude_stop_preserves_project_memory_gate_on_dirty_tree(
    hook_paths, git_workspaces, run_hook, read_http_records
) -> None:
    """145-02-02：Capture 不受 diff 门闩影响，项目记忆仍仅 dirty 上报。"""
    for label in ("clean", "dirty", "no_git"):
        cwd = git_workspaces[label]
        session = f"session-{label}"
        run_hook(hook_paths["claude_prompt"], _claude_prompt(session, "g", cwd), cwd=cwd)
        run_hook(hook_paths["claude_stop"], _claude_stop(session, "g", cwd), cwd=cwd)
    records = read_http_records()
    captures = _capture_records(records)
    project_reports = [
        record for record in records if "report_project_knowledge" in record.get("url", "")
    ]
    assert len(captures) == 3
    assert len(project_reports) == 1
    no_git_body = next(
        _body(record) for record in captures if _body(record)["session_id"] == "session-no_git"
    )
    assert not no_git_body.get("git_url")
    assert not no_git_body.get("branch_name")


def test_claude_stop_fail_soft_modes_keep_pending(
    hook_paths, git_workspaces, run_hook, pending_files, http_record
) -> None:
    """145-02-03 / SKILL-05：缺凭证或强制网络故障均 fail-soft 并保留状态。"""
    cwd = git_workspaces["clean"]
    for index, failure in enumerate(("timeout", "http_error"), start=1):
        session = f"failure-{index}"
        run_hook(hook_paths["claude_prompt"], _claude_prompt(session, "g", cwd), cwd=cwd)
        result = run_hook(
            hook_paths["claude_stop"],
            _claude_stop(session, "g", cwd),
            cwd=cwd,
            extra_env={"FRIDAY_CAPTURE_HTTP_FORCE": failure},
            record_http=False,
        )
        assert result.returncode == 0
    missing = run_hook(
        hook_paths["claude_prompt"],
        _claude_prompt("missing-creds", "g", cwd),
        cwd=cwd,
        extra_env={"FRIDAY_BASE_URL": None, "FRIDAY_ACCESS_TOKEN": None},
        record_http=False,
    )
    assert missing.returncode == 0
    assert len(pending_files()) == 2
    assert not http_record.exists()


def test_claude_stop_strips_thinking_and_ignores_transcript(
    tmp_path, hook_paths, git_workspaces, run_hook, read_http_records
) -> None:
    """145-03-01 / D-07：只取可见答案，不读 transcript 或 thinking。"""
    cwd = git_workspaces["clean"]
    transcript = tmp_path / "transcript.jsonl"
    transcript_secret = "TRANSCRIPT-MUST-NOT-UPLOAD"
    transcript.write_text(transcript_secret, encoding="utf-8")
    run_hook(hook_paths["claude_prompt"], _claude_prompt("s3", "g3", cwd), cwd=cwd)
    event = _claude_stop(
        "s3",
        "g3",
        cwd,
        "<thinking>隐藏推理</thinking>\n公开结论\n<thought>也要删除</thought>",
    )
    event["transcript_path"] = str(transcript)
    run_hook(hook_paths["claude_stop"], event, cwd=cwd)
    body = _body(_capture_records(read_http_records())[-1])
    assert body["answer"] == "公开结论"
    assert "隐藏推理" not in body["answer"]
    assert transcript_secret not in str(body)


def test_claude_stop_handles_background_tasks(
    hook_paths, git_workspaces, run_hook, read_http_records
) -> None:
    """145-03-02 / OQ-02：background_tasks 非空仍上报本轮可见答案。"""
    cwd = git_workspaces["clean"]
    run_hook(hook_paths["claude_prompt"], _claude_prompt("s4", "g4", cwd), cwd=cwd)
    event = _claude_stop("s4", "g4", cwd)
    event["background_tasks"] = [{"id": "background-1"}]
    run_hook(hook_paths["claude_stop"], event, cwd=cwd)
    assert _capture_records(read_http_records())


def test_cursor_hooks_pair_visible_answer(
    hook_paths, git_workspaces, run_hook, read_http_records, pending_files
) -> None:
    """145-04-01 / D-03：Cursor before/after 配对，conversation_id 优先。"""
    cwd = git_workspaces["clean"]
    before = {
        "conversation_id": "conversation-primary",
        "session_id": "session-secondary",
        "generation_id": "generation-1",
        "workspace": str(cwd),
        "prompt": "Cursor 问题",
    }
    after = {
        **before,
        "text": "Cursor 可见答案",
        "afterAgentThought": "隐藏 thought",
        "transcript_path": str(cwd / "must-not-read"),
    }
    before_result = run_hook(hook_paths["cursor_before"], before, cwd=cwd)
    assert "additionalContext" not in before_result.stdout
    run_hook(hook_paths["cursor_after"], after, cwd=cwd)
    body = _body(_capture_records(read_http_records())[-1])
    assert body["session_id"] == "conversation-primary"
    assert body["client"] == "cursor"
    assert body["question"] == "Cursor 问题"
    assert body["answer"] == "Cursor 可见答案"
    assert not pending_files()


def test_cursor_pairing_rejects_ambiguous_generation(
    hook_paths, git_workspaces, run_hook, read_http_records
) -> None:
    """145-04-02 / D-05：错代、重复及多 pending 无 generation 均不得误配。"""
    cwd = git_workspaces["clean"]
    base = {"conversation_id": "cursor-ambiguous", "workspace": str(cwd)}
    for generation in ("one", "two"):
        run_hook(
            hook_paths["cursor_before"],
            {**base, "generation_id": generation, "prompt": f"问题-{generation}"},
            cwd=cwd,
        )
    for event in (
        {**base, "generation_id": "wrong", "text": "错代答案"},
        {**base, "text": "无 generation 答案"},
        {**base, "generation_id": "one", "text": ""},
    ):
        assert run_hook(hook_paths["cursor_after"], event, cwd=cwd).returncode == 0
    assert not _capture_records(read_http_records())


def test_hook_outputs_do_not_leak_sensitive_values(
    hook_paths, git_workspaces, run_hook, pending_files
) -> None:
    """145-05-03 / T-145-01..03：输出和缓存文件名不含凭证、问答或上游 body。"""
    cwd = git_workspaces["clean"]
    prompt = "SENSITIVE-PROMPT"
    answer = "SENSITIVE-ANSWER"
    run_hook(
        hook_paths["claude_prompt"],
        _claude_prompt("sensitive-session", "g", cwd, prompt),
        cwd=cwd,
    )
    result = run_hook(
        hook_paths["claude_stop"],
        _claude_stop("sensitive-session", "g", cwd, answer),
        cwd=cwd,
        extra_env={"FRIDAY_CAPTURE_HTTP_FORCE": "http_error"},
        record_http=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0
    assert all(value not in output for value in (FAKE_TOKEN, prompt, answer, "Bearer"))
    assert all(FAKE_TOKEN not in path.name for path in pending_files())
