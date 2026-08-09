"""``SymbolCommunity`` 模型契约（MOD-01 / D-01 / D-02）。"""

from __future__ import annotations

from django.db import models

from codegraph.models import Symbol, SymbolCommunity


def test_symbol_community_fields_and_unique_together() -> None:
    """``SymbolCommunity`` 字段齐全；``unique_together`` 覆盖仓库/分支/社区键。

    （Req: MOD-01, 决策: D-01）
    """
    field_names = {f.name for f in SymbolCommunity._meta.get_fields()}
    required = {
        "id",
        "repository",
        "branch_name",
        "community_key",
        "algorithm",
        "member_count",
        "members",
        "member_keys",
        "top_files",
        "member_fingerprint",
        "summary",
        "summary_model",
        "summary_generated_at",
        "built_at_sha",
        "created_at",
        "updated_at",
    }
    assert required.issubset(field_names)

    branch = SymbolCommunity._meta.get_field("branch_name")
    assert isinstance(branch, models.CharField)
    assert branch.default == ""

    algorithm = SymbolCommunity._meta.get_field("algorithm")
    assert isinstance(algorithm, models.CharField)
    assert algorithm.default == "louvain"

    members = SymbolCommunity._meta.get_field("members")
    assert isinstance(members, models.JSONField)
    assert members.default is list or members.default() == []

    top_files = SymbolCommunity._meta.get_field("top_files")
    assert isinstance(top_files, models.JSONField)

    summary = SymbolCommunity._meta.get_field("summary")
    assert summary.null is True or summary.blank is True

    ut = list(SymbolCommunity._meta.unique_together)
    assert ("repository", "branch_name", "community_key") in ut or any(
        set(group) == {"repository", "branch_name", "community_key"} for group in ut
    )


def test_symbol_has_no_community_fk_or_m2m() -> None:
    """``Symbol`` 模型无 community FK/M2M（社区侧软引用，不污染符号表）。

    （Req: MOD-01, 决策: D-02）
    """
    names = {f.name for f in Symbol._meta.get_fields()}
    assert "community_id" not in names
    assert "community" not in names
    assert "communities" not in names
    for field in Symbol._meta.get_fields():
        related = getattr(field, "related_model", None)
        if related is SymbolCommunity:
            raise AssertionError(f"Symbol must not relate to SymbolCommunity via {field.name}")


def test_members_symbol_id_is_soft_string_not_fk() -> None:
    """``members`` JSON 内 ``symbol_id`` 为软字符串，非 ORM FK。

    （Req: MOD-01, 决策: D-02）
    """
    members = SymbolCommunity._meta.get_field("members")
    assert isinstance(members, models.JSONField)
    # 模型层不得存在指向 Symbol 的 members FK / M2M。
    for field in SymbolCommunity._meta.get_fields():
        if field.name in {"members", "member", "symbols", "symbol"}:
            assert not isinstance(field, (models.ForeignKey, models.ManyToManyField))
        related = getattr(field, "related_model", None)
        if related is Symbol and field.name != "repository":
            # repository 是仓 FK，允许；members 不得是 Symbol FK。
            assert field.name != "members"
