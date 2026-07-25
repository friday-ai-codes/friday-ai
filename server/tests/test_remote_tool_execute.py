"""RTOOL-01/MCPB-02 锁名测试桩：PAT 认证的 RemoteTool 执行端点 fail-closed + 审计（Wave 0）。

在执行端点（10-02）落地前，先用锁名测试把执行端点的可验证安全契约钉死：

- RTOOL-01：有效 PAT 经完整 DRF 链路按 name 执行 → 200 + executor ``{ok: True, ...}``。
- RTOOL-01：匿名请求 → 401（fail-closed，per Pitfall 2，断言精确 401 而非 403 降级）。
- RTOOL-01/IDENT-05：吊销 PAT → 401。
- RTOOL-01：未知工具 → 200 + ``{ok: False, error.code == "not_found"}``（透传 executor 契约）。
- MCPB-02/IDENT-04：执行建审计 ``InteractionRun``，``token_fingerprint == token_hash``（绝不明文）。

约定（per 10-01 plan）：执行端点 URL 硬编码 ``/api/tools/execute/``（末尾带 ``/``），
真实 PAT 经 ``client.credentials(HTTP_AUTHORIZATION="Bearer <plaintext>")`` 注入。
execute_tool 桩以 ``monkeypatch.setattr("tools.views.execute_tool", _stub, raising=False)``
注入（10-02 之前 tools.views 无该符号 → raising=False 不报错）。

预期 RED：端点未实现（404）。实现（10-02）落地后转 GREEN。
任何状态下都不应出现 collection / import error。
"""

from __future__ import annotations

from typing import Any, Callable

import pytest

# access_tokens 已实现（Phase 7）；importorskip 守卫保住「模块缺失则整文件 skip」。
pytest.importorskip("access_tokens.models")

from rest_framework.test import APIClient  # noqa: E402

from interactions.models import InteractionRun, ToolCallRecord  # noqa: E402

pytestmark = pytest.mark.django_db

EXECUTE_URL = "/api/tools/execute/"


def _make_stub_ok() -> tuple[Callable[..., Any], dict[str, Any]]:
    """构造 execute_tool 成功桩 + 捕获字典。

    桩签名必须与生产 ``tools.executor.execute_tool`` 对齐：视图按 101-04 步级 trace
    契约透传 ``run``（本次审计建的 ``InteractionRun``），供 skill 分支写步级
    ToolCallRecord。捕获下来供用例断言，避免透传被静默丢失。
    """
    captured: dict[str, Any] = {}

    async def _stub_ok(
        name: str, arguments: dict[str, Any], run: InteractionRun | None = None
    ) -> dict[str, Any]:
        captured["name"] = name
        captured["arguments"] = arguments
        captured["run"] = run
        return {"ok": True, "result": {"echo": name, "args": arguments}}

    return _stub_ok, captured


def test_pat_execute_ok(
    monkeypatch: pytest.MonkeyPatch,
    make_access_token: Callable[..., tuple[Any, str]],
) -> None:
    """RTOOL-01：有效 PAT → 200 + resp.data["ok"] is True（executor 透传）。"""
    stub, captured = _make_stub_ok()
    monkeypatch.setattr("tools.views.execute_tool", stub, raising=False)
    _token, plaintext = make_access_token(name="exec-ok")

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {plaintext}")
    resp = client.post(
        EXECUTE_URL, {"name": "x", "arguments": {}}, format="json"
    )

    assert resp.status_code == 200
    assert resp.data["ok"] is True
    assert captured["name"] == "x"
    # 101-04：执行端点必须把本次审计 run 透传给 executor（步级 trace 的挂载点）。
    assert isinstance(captured["run"], InteractionRun)


def test_anonymous_401() -> None:
    """RTOOL-01：匿名请求 → 401（fail-closed，per Pitfall 2，绝不降级 403）。"""
    client = APIClient()
    resp = client.post(EXECUTE_URL, {"name": "x", "arguments": {}}, format="json")
    assert resp.status_code == 401


def test_revoked_pat_401(
    make_access_token: Callable[..., tuple[Any, str]],
) -> None:
    """RTOOL-01/IDENT-05：吊销 PAT → 401。"""
    _token, plaintext = make_access_token(name="exec-revoked", revoked=True)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {plaintext}")
    resp = client.post(
        EXECUTE_URL, {"name": "x", "arguments": {}}, format="json"
    )
    assert resp.status_code == 401


def test_unknown_tool_ok_false(
    make_access_token: Callable[..., tuple[Any, str]],
) -> None:
    """RTOOL-01：未知工具 → 200 + {ok: False, error.code == "not_found"}（不 mock executor）。"""
    _token, plaintext = make_access_token(name="exec-unknown")

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {plaintext}")
    resp = client.post(
        EXECUTE_URL, {"name": "does_not_exist", "arguments": {}}, format="json"
    )

    assert resp.status_code == 200
    assert resp.data["ok"] is False
    assert resp.data["error"]["code"] == "not_found"


def test_execute_records_run(
    monkeypatch: pytest.MonkeyPatch,
    make_access_token: Callable[..., tuple[Any, str]],
) -> None:
    """MCPB-02/IDENT-04：执行建审计 InteractionRun，fingerprint=token_hash（无明文）。"""
    stub, captured = _make_stub_ok()
    monkeypatch.setattr("tools.views.execute_tool", stub, raising=False)
    token, plaintext = make_access_token(name="exec-audit")

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {plaintext}")
    resp = client.post(
        EXECUTE_URL, {"name": "x", "arguments": {}}, format="json"
    )
    assert resp.status_code == 200

    # 审计：以令牌 hash 作指纹建 run（绝不存明文）。
    assert InteractionRun.objects.filter(
        token_fingerprint=token.token_hash
    ).exists()
    # 透传给 executor 的 run 与审计落库的是同一条，步级 trace 才挂得到正确的顶层 run。
    assert captured["run"].token_fingerprint == token.token_hash


def test_execute_finalizes_run(
    monkeypatch: pytest.MonkeyPatch,
    make_access_token: Callable[..., tuple[Any, str]],
) -> None:
    """MCPB-02/WR-02：execute 后 run 推进到终态并记录 tool-call，不留悬挂 RUNNING。"""
    stub, _captured = _make_stub_ok()
    monkeypatch.setattr("tools.views.execute_tool", stub, raising=False)
    token, plaintext = make_access_token(name="exec-finalize")

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {plaintext}")
    resp = client.post(EXECUTE_URL, {"name": "x", "arguments": {}}, format="json")
    assert resp.status_code == 200

    run = InteractionRun.objects.filter(token_fingerprint=token.token_hash).latest(
        "created_at"
    )
    # 终态：不再是 RUNNING（成功 → COMPLETED）。
    assert run.status == InteractionRun.Status.COMPLETED
    assert run.completed_at is not None
    # 记录了 tool-call 明细（result 留痕）。
    assert ToolCallRecord.objects.filter(run=run, status="ok").exists()


def test_execute_error_finalizes_run_error(
    make_access_token: Callable[..., tuple[Any, str]],
) -> None:
    """WR-02：执行失败（未知工具 ok=False）后 run 推进到 ERROR 终态并记录 error tool-call。"""
    token, plaintext = make_access_token(name="exec-finalize-err")

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {plaintext}")
    resp = client.post(
        EXECUTE_URL, {"name": "does_not_exist", "arguments": {}}, format="json"
    )
    assert resp.status_code == 200
    assert resp.data["ok"] is False

    run = InteractionRun.objects.filter(token_fingerprint=token.token_hash).latest(
        "created_at"
    )
    assert run.status == InteractionRun.Status.ERROR
    assert run.completed_at is not None
    assert ToolCallRecord.objects.filter(run=run, status="error").exists()
