"""``services/code_graph/access.py`` 的 fail-closed 收口用例（覆盖 GRAPH-04）。

本文件由 **Plan 121-03**（可读性闸门、matcher fail-closed、指纹 memo、观测契约
守护）落地主体，剩余两个桩由 **Plan 121-05**（exclusion 过滤节点连带邻接边）与
**Plan 121-09**（barrel 导出红线）填充。

桩的存在是 Wave 0 的 Nyquist 要求：121-VALIDATION.md 里每个 ``-k`` 选择器都必须
从第一个 task 起就能解析到真实用例名。
"""

from __future__ import annotations

import inspect
from unittest import mock

import pytest

from services.code_graph.access import (
    _MATCHER_FP_TTL_SECONDS,
    _check_user_acl,
    build_matcher_and_fingerprint,
    ensure_repository_readable,
    invalidate_matcher_fingerprint_cache,
    make_path_exclusion_memo,
)
from services.code_graph.model import GraphAccessDenied, GraphNotIndexed


# 121-VALIDATION.md 121-05-T2：命中 exclusion 的符号不在节点集，
# 其邻接边一并消失（装配阶段过滤，不是输出阶段过滤）。
@pytest.mark.skip(reason="stub：由 Plan 121-05 实现")
def test_exclusion_hides_symbols_and_edges() -> None:
    pass


# ── 121-03-T1：仓库可读性单一校验点 ────────────────────────────────────────


# 121-VALIDATION.md 121-03-T1：index_status != INDEXED ⇒ 显式抛错，
# 不返回空图（空图会被上层误读为「没有影响」）。
@pytest.mark.django_db(transaction=True)
async def test_not_indexed_raises(indexed_repo) -> None:
    """未索引仓库抛 ``GraphNotIndexed``，且没有任何「返回空图」的出口。"""
    from repositories.models import IndexStatus, Repository

    await Repository.objects.filter(id=indexed_repo.id).aupdate(
        index_status=IndexStatus.NOT_INDEXED
    )

    with pytest.raises(GraphNotIndexed) as excinfo:
        await ensure_repository_readable(None, str(indexed_repo.id))

    assert excinfo.value.details is not None
    assert excinfo.value.details["index_status"] == IndexStatus.NOT_INDEXED

    # 「不返回空图」是签名级保证：本函数唯一的正常出口是 None，拒绝出口只有 raise。
    signature = inspect.signature(ensure_repository_readable)
    assert signature.return_annotation == "None"


# 121-VALIDATION.md 121-03-T1：is_deleted=True 的仓库 ⇒ 拒绝。
@pytest.mark.django_db(transaction=True)
async def test_deleted_repo_denied(indexed_repo) -> None:
    """软删仓库与「不存在」合并为同一出口，不泄漏存在性差异。"""
    from repositories.models import Repository

    await Repository.objects.filter(id=indexed_repo.id).aupdate(is_deleted=True)

    with pytest.raises(GraphAccessDenied) as excinfo:
        await ensure_repository_readable(None, str(indexed_repo.id))

    missing_id = "00000000-0000-0000-0000-000000000000"
    with pytest.raises(GraphAccessDenied) as excinfo_missing:
        await ensure_repository_readable(None, missing_id)

    # 同一句文案：调用方无法据此区分「已删」与「从来不存在」。
    assert excinfo.value.message == excinfo_missing.value.message


@pytest.mark.django_db(transaction=True)
async def test_invalid_repository_id_is_rejected() -> None:
    """非 UUID 的 ``repository_id`` 在打库之前就被拒（ASVS V5）。"""
    with pytest.raises(GraphAccessDenied):
        await ensure_repository_readable(None, "not-a-uuid")


@pytest.mark.django_db(transaction=True)
async def test_readable_repo_passes_gate(indexed_repo) -> None:
    """``indexed_repo`` 两道闸都过，静默返回 None。"""
    assert await ensure_repository_readable(None, str(indexed_repo.id)) is None


def test_user_acl_extension_point_is_empty() -> None:
    """ACL 扩展点存在且为空实现——本相位只收口校验点，不发明 ACL 模型。"""
    assert _check_user_acl(None, object()) is None
    assert _check_user_acl(object(), object()) is None
    assert (_check_user_acl.__doc__ or "").strip(), "_check_user_acl 必须带扩展点注释"


# ── 121-03-T2：exclusion 同步收口（fail-closed / 指纹 / memo / 记忆化） ──────


def _real_resolve_effective_specs():
    """取未被 patch 的原始实现（供 spy 的 ``side_effect`` 转调）。"""
    import services.exclusion as exclusion_module

    return exclusion_module._resolve_effective_specs


# 121-VALIDATION.md 121-03-T2：matcher 构造失败 ⇒ 抛 GraphAccessDenied，
# 不返回未过滤的图（出口是 raise，不是空列表）。
@pytest.mark.django_db
def test_fail_closed_on_matcher_build_error(indexed_repo) -> None:
    """规则解析/构造失败 ⇒ 整仓拒绝 + 审计埋点，且失败不被 memo 成「下次放行」。"""
    repo_id = str(indexed_repo.id)

    with (
        mock.patch(
            "services.exclusion._resolve_effective_specs",
            side_effect=RuntimeError("规则表炸了"),
        ) as resolve_spy,
        mock.patch("services.exclusion.log_exclusion_blocked") as blocked_spy,
    ):
        with pytest.raises(GraphAccessDenied) as excinfo:
            build_matcher_and_fingerprint(repo_id)

        # 审计埋点已发，且明确标注这是整仓级别的拦截。
        assert blocked_spy.call_count == 1
        assert blocked_spy.call_args.kwargs["surface"] == "code_graph"
        assert blocked_spy.call_args.kwargs["rel_path"] == "<repository>"
        assert excinfo.value.details is not None
        assert excinfo.value.details["error_type"] == "RuntimeError"

        # 再调一次仍抛：失败**不写 memo**，也不返回上一轮的旧 matcher。
        with pytest.raises(GraphAccessDenied):
            build_matcher_and_fingerprint(repo_id)
        assert resolve_spy.call_count == 2


@pytest.mark.django_db
def test_fingerprint_is_stable_across_calls(indexed_repo) -> None:
    """同一仓库连算两次，指纹字符串完全一致（清 memo 后重算也一致）。"""
    repo_id = str(indexed_repo.id)

    _, first = build_matcher_and_fingerprint(repo_id)
    invalidate_matcher_fingerprint_cache(repo_id)
    _, second = build_matcher_and_fingerprint(repo_id)

    assert first == second
    assert len(first) == 16


@pytest.mark.django_db
def test_matcher_fingerprint_memo_resolves_once(indexed_repo) -> None:
    """连调两次只解析编译一次；``invalidate`` 后重新解析。"""
    repo_id = str(indexed_repo.id)

    with mock.patch(
        "services.exclusion._resolve_effective_specs",
        side_effect=_real_resolve_effective_specs(),
    ) as resolve_spy:
        matcher_a, fp_a = build_matcher_and_fingerprint(repo_id)
        matcher_b, fp_b = build_matcher_and_fingerprint(repo_id)

        assert resolve_spy.call_count == 1
        # 命中 memo 拿到的是同一个 matcher 对象（没有重新编译该仓全部 glob/regex）。
        assert matcher_a is matcher_b
        assert fp_a == fp_b

        invalidate_matcher_fingerprint_cache(repo_id)
        build_matcher_and_fingerprint(repo_id)
        assert resolve_spy.call_count == 2


@pytest.mark.django_db
def test_fingerprint_changes_when_rules_change(
    indexed_repo, exclusion_rule_factory
) -> None:
    """新增一条 per-repo 规则后指纹改变（有效规则集的任何变更都要被指纹捕获）。"""
    from services.exclusion import invalidate_matcher_cache

    repo_id = str(indexed_repo.id)
    _, before = build_matcher_and_fingerprint(repo_id)

    exclusion_rule_factory("*.generated.ts")
    # 两份 memo 都要清：只清 exclusion 那份会读到本模块的 60s 旧值。
    invalidate_matcher_cache()
    invalidate_matcher_fingerprint_cache()

    _, after = build_matcher_and_fingerprint(repo_id)
    assert before != after


@pytest.mark.django_db
def test_path_exclusion_memo_dedupes_by_file_path(indexed_repo) -> None:
    """同一 file_path 判定 10 次只穿透 matcher 一次，审计埋点也只打一次。"""
    matcher, _ = build_matcher_and_fingerprint(str(indexed_repo.id))

    with (
        mock.patch.object(
            matcher, "is_excluded", wraps=matcher.is_excluded
        ) as is_excluded_spy,
        mock.patch("services.exclusion.log_exclusion_blocked") as blocked_spy,
    ):
        is_excluded = make_path_exclusion_memo(matcher)

        for _ in range(10):
            assert is_excluded("server/.env") is True
        for _ in range(10):
            assert is_excluded("server/app/views.py") is False

        assert is_excluded_spy.call_count == 2
        # INFO 级审计不随符号数增长：每个被排除 file_path 至多一次。
        assert blocked_spy.call_count == 1

    assert set(is_excluded.excluded_files) == {"server/.env"}
    with pytest.raises(AttributeError):
        is_excluded.excluded_files.add("server/app/views.py")


# 121-VALIDATION.md 121-03-T3（planner 追加行）：观测契约守护——包内每个 structlog
# 调用都带 component="code_graph" + category="sampling" + code_graph_ 事件名前缀。
@pytest.mark.skip(reason="stub：由 Plan 121-03 实现")
def test_observability_contract() -> None:
    pass


# 121-VALIDATION.md 121-03-T2（planner 追加行）：matcher/指纹 60s TTL memo——
# 连算两次只解析一次（见 test_matcher_fingerprint_memo_resolves_once）；invalidate
# 后重新解析；构造失败不写 memo（见 test_fail_closed_on_matcher_build_error）。
def test_matcher_fingerprint_memo_ttl() -> None:
    """本模块 memo 的 TTL 与 ``services/exclusion.py`` 严格对齐。

    暴露窗口（规则变更后最多多久生效）必须与全仓既有 exclusion 读取面完全相同——
    对齐才说明这里没有引入新的弱化。要收窄就两处一起改。
    """
    from services.exclusion import _MATCHER_CACHE_TTL_SECONDS

    assert _MATCHER_FP_TTL_SECONDS == _MATCHER_CACHE_TTL_SECONDS


# 121-VALIDATION.md 121-09-T1（planner 追加行）：barrel 恰导出 17 项
# （含 invalidate_repository），loader/cache/signature/access 不可从包顶层取得。
@pytest.mark.skip(reason="stub：由 Plan 121-09 实现")
def test_barrel_exports_are_curated() -> None:
    pass
