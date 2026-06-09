"""MCPB-01/03 锁名测试桩：工具令牌绑定 CRUD + owner 隔离 + 不泄漏明文（Nyquist Wave 0）。

在实现绑定模型 / 序列化器 / 端点（10-02/10-03）落地前，先用锁名测试把绑定的
可验证安全契约钉死：

- MCPB-01：用户可把自己的 PAT 绑给 mcp/skill 工具（upsert 入库，重复绑定换令牌）；
  绑 builtin 工具被拒；引用他人令牌 id 被拒（access_token.created_by==request.user）。
- MCPB-03：list/unbind 仅作用于自己的绑定（owner 隔离，越权 delete → 404 不泄漏存在性）。
- MCPB-01/03：序列化器永不吐明文与 ``token_hash``（仅 name/token_prefix/token_suffix/is_valid）。
- MCPB-01：可绑定列表只含 ``source ∈ {mcp, skill}`` 且 ``is_active`` 的工具。

约定（per 10-01 plan）：URL 全部硬编码字符串（``/api/tools/bindings/`` /
``/api/tools/bindable/``，末尾带 ``/``），**不 import 未落地的 views/serializers**，
从而「端点 404 → RED」而非 collection error。绑定 CRUD 经 CookieJWT，用
``APIClient.force_authenticate(user=...)`` 注入身份。

预期 RED：绑定/可绑定端点未实现（404）；依赖 ``make_tool_binding`` 播种的隔离用例
在 ``ToolTokenBinding`` 落地前优雅 skip。实现（10-02/10-03）落地后转 GREEN。
任何状态下都不应出现 collection / import error。
"""

from __future__ import annotations

from typing import Any, Callable

import pytest

# access_tokens 已实现（Phase 7）；用 importorskip 守卫保住「模块缺失则整文件 skip
# 而非 collection error」的不变量（与 test_pat_identity.py 同范式）。
pytest.importorskip("access_tokens.models")

from access_tokens.models import AccessToken, generate_pat  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from runners.models import hash_token  # noqa: E402

pytestmark = pytest.mark.django_db

BINDINGS_URL = "/api/tools/bindings/"
BINDABLE_URL = "/api/tools/bindable/"


def _mint_token(owner: Any, name: str = "iso") -> tuple[Any, str]:
    """直接经 ORM 给任意 owner 铸一把有效 PAT，返回 (token, 明文)。

    供「为二号用户播种令牌」场景使用——``make_access_token`` 仅为主用户铸令牌。
    明文仅作返回值供断言比对，绝不入除指纹外的任何字段。
    """
    plaintext = generate_pat()
    token = AccessToken.objects.create(
        name=name,
        token_hash=hash_token(plaintext),
        token_prefix=plaintext[:12],
        token_suffix=plaintext[-4:],
        created_by=owner,
    )
    return token, plaintext


def _binding_model() -> Any:
    """返回 ``ToolTokenBinding`` 类或 None（10-02 未落地时为 None）。"""
    from tools import models as tools_models

    return getattr(tools_models, "ToolTokenBinding", None)


def test_upsert_rebind_updates_token(
    make_remote_tool: Callable[..., Any],
    make_access_token: Callable[..., tuple[Any, str]],
    user: Any,
) -> None:
    """MCPB-01：同一工具重复绑定即更新所绑令牌（update_or_create，per Pitfall 3）。"""
    tool = make_remote_tool(source="mcp")
    token_a, _ = make_access_token(name="token-a")
    token_b, _ = make_access_token(name="token-b")

    client = APIClient()
    client.force_authenticate(user=user)

    # 首次绑定 token A。
    resp_a = client.post(
        BINDINGS_URL, {"remote_tool": tool.id, "access_token": str(token_a.id)}, format="json"
    )
    assert resp_a.status_code == 201

    # 再次绑定同一工具到 token B：upsert 不应撞 unique_together 抛 500。
    resp_b = client.post(
        BINDINGS_URL, {"remote_tool": tool.id, "access_token": str(token_b.id)}, format="json"
    )
    assert resp_b.status_code in (200, 201)

    # 列表只 1 条，且其令牌指向 B（换令牌生效）。
    listing = client.get(BINDINGS_URL)
    assert listing.status_code == 200
    rows = listing.data
    assert len(rows) == 1
    assert rows[0]["access_token"]["id"] == str(token_b.id)


def test_bind_builtin_rejected(
    make_remote_tool: Callable[..., Any],
    make_access_token: Callable[..., tuple[Any, str]],
    user: Any,
) -> None:
    """MCPB-01：绑定 source=builtin 工具被拒（source 白名单仅 mcp/skill，per Pitfall 1）。"""
    builtin_tool = make_remote_tool(source="builtin")
    token, _ = make_access_token(name="bt")

    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post(
        BINDINGS_URL,
        {"remote_tool": builtin_tool.id, "access_token": str(token.id)},
        format="json",
    )
    assert resp.status_code == 400


def test_bind_others_token_rejected(
    make_remote_tool: Callable[..., Any],
    make_access_token: Callable[..., tuple[Any, str]],
    second_user: Any,
) -> None:
    """MCPB-01：引用他人令牌 id 绑定被拒（access_token.created_by==request.user，per Pitfall 1）。

    ``make_access_token`` 给主用户（access_user）铸令牌，再以二号用户身份用该令牌 id
    去绑自己可见的工具 → 越权引用应 4xx，且绝不创建绑定。
    """
    others_token, _ = make_access_token(name="owner-token")  # 属主用户
    tool = make_remote_tool(source="mcp")

    client = APIClient()
    client.force_authenticate(user=second_user)
    resp = client.post(
        BINDINGS_URL,
        {"remote_tool": tool.id, "access_token": str(others_token.id)},
        format="json",
    )
    # 不泄漏存在性：400/403/404 均可接受，统一断言 >= 400。
    assert resp.status_code >= 400

    binding_cls = _binding_model()
    if binding_cls is not None:
        # 模型已落地（10-02 之后）：确认越权引用未落库。
        assert not binding_cls.objects.filter(access_token=others_token).exists()


def test_bind_revoked_token_rejected(
    make_remote_tool: Callable[..., Any],
    make_access_token: Callable[..., tuple[Any, str]],
    user: Any,
) -> None:
    """MCPB-01/WR-04：绑定已吊销/过期令牌被拒（服务端强校验，per Pitfall 5）。

    直接 API 调用（绕过前端 is_valid 过滤）引用一把已吊销令牌去绑 mcp 工具，
    序列化器须在 ``validate_access_token`` 收成 400，且绝不落库。
    """
    tool = make_remote_tool(source="mcp")
    revoked_token, _ = make_access_token(name="revoked-bind", revoked=True)

    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post(
        BINDINGS_URL,
        {"remote_tool": tool.id, "access_token": str(revoked_token.id)},
        format="json",
    )
    assert resp.status_code == 400

    binding_cls = _binding_model()
    if binding_cls is not None:
        assert not binding_cls.objects.filter(access_token=revoked_token).exists()


def test_list_owner_isolation(
    make_remote_tool: Callable[..., Any],
    make_tool_binding: Callable[..., Any],
    second_user: Any,
    user: Any,
) -> None:
    """MCPB-03：list 仅返回自己的绑定，不含他人绑定（owner 隔离）。

    二号用户的绑定经 ORM 工厂 ``make_tool_binding`` 直接播种（API 无法跨用户绑定）；
    主用户 GET 列表不应出现二号用户的绑定 id。
    """
    tool = make_remote_tool(source="mcp")
    second_token, _ = _mint_token(second_user, name="second-iso")
    # ToolTokenBinding 未落地时此处优雅 skip（10-02 之前）。
    others_binding = make_tool_binding(second_user, second_token, tool)

    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.get(BINDINGS_URL)
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.data]
    assert others_binding.id not in ids


def test_unbind_and_cross_user_404(
    make_remote_tool: Callable[..., Any],
    make_tool_binding: Callable[..., Any],
    make_access_token: Callable[..., tuple[Any, str]],
    second_user: Any,
    user: Any,
) -> None:
    """MCPB-03：解绑自己的绑定 → 204；删他人绑定 → 404（不泄漏存在性）。"""
    tool_self = make_remote_tool(source="mcp")
    own_token, _ = make_access_token(name="own-token")
    # 自己的绑定经 ORM 播种（10-02 之前 skip）。
    own_binding = make_tool_binding(user, own_token, tool_self)

    tool_other = make_remote_tool(source="skill")
    second_token, _ = _mint_token(second_user, name="second-unbind")
    others_binding = make_tool_binding(second_user, second_token, tool_other)

    client = APIClient()
    client.force_authenticate(user=user)

    # 解绑自己的绑定 → 204。
    own_resp = client.delete(f"{BINDINGS_URL}{own_binding.id}/")
    assert own_resp.status_code == 204

    # 删他人绑定 → 404（owner 隔离 get_queryset 天然为空集）。
    cross_resp = client.delete(f"{BINDINGS_URL}{others_binding.id}/")
    assert cross_resp.status_code == 404


def test_serializer_no_plaintext_no_hash(
    make_remote_tool: Callable[..., Any],
    make_access_token: Callable[..., tuple[Any, str]],
    user: Any,
) -> None:
    """MCPB-01/03：绑定列表响应永不含令牌明文与 token_hash（白名单 only）。"""
    tool = make_remote_tool(source="mcp")
    token, plaintext = make_access_token(name="leak-check")

    client = APIClient()
    client.force_authenticate(user=user)
    client.post(
        BINDINGS_URL, {"remote_tool": tool.id, "access_token": str(token.id)}, format="json"
    )

    resp = client.get(BINDINGS_URL)
    # 端点落地后 200；Wave 0 因端点缺失而 RED。
    assert resp.status_code == 200
    content = resp.content.decode()
    # 真实明文子串绝不出现在任何响应里（T-10-01）。
    assert plaintext not in content
    # token_hash 键绝不进序列化白名单。
    assert "token_hash" not in content
    assert token.token_hash not in content


def test_bindable_filters_mcp_skill_active(
    make_remote_tool: Callable[..., Any],
    user: Any,
) -> None:
    """MCPB-01：可绑定列表只含 source ∈ {mcp, skill} 且 is_active 的工具。"""
    mcp_active = make_remote_tool(source="mcp", is_active=True)
    skill_active = make_remote_tool(source="skill", is_active=True)
    make_remote_tool(source="builtin", is_active=True)  # 排除：builtin
    make_remote_tool(source="mcp", is_active=False)  # 排除：inactive

    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.get(BINDABLE_URL)
    assert resp.status_code == 200

    names = {row["name"] for row in resp.data}
    assert mcp_active.name in names
    assert skill_active.name in names
    # 仅前两者：builtin / inactive 均不出现。
    assert len(names) == 2
