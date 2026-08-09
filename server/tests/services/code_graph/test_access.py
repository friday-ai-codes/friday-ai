"""``services/code_graph/access.py`` 的 fail-closed 收口用例（覆盖 GRAPH-04）。

本文件由 **Plan 121-03**（可读性闸门、matcher fail-closed、指纹 memo、观测契约
守护）落地主体，剩余两个桩由 **Plan 121-05**（exclusion 过滤节点连带邻接边）与
**Plan 121-09**（barrel 导出红线）填充。

桩的存在是 Wave 0 的 Nyquist 要求：121-VALIDATION.md 里每个 ``-k`` 选择器都必须
从第一个 task 起就能解析到真实用例名。
"""

from __future__ import annotations

import inspect

import pytest

from services.code_graph.access import (
    _check_user_acl,
    ensure_repository_readable,
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


# 121-VALIDATION.md 121-03-T3（planner 追加行）：观测契约守护——包内每个 structlog
# 调用都带 component="code_graph" + category="sampling" + code_graph_ 事件名前缀。
@pytest.mark.skip(reason="stub：由 Plan 121-03 实现")
def test_observability_contract() -> None:
    pass


# 121-VALIDATION.md 121-03-T2（planner 追加行）：matcher/指纹 60s TTL memo——
# 连算两次只解析一次；invalidate 后重新解析；构造失败不写 memo。
@pytest.mark.skip(reason="stub：由 Plan 121-03 实现")
def test_matcher_fingerprint_memo_ttl() -> None:
    pass


# 121-VALIDATION.md 121-09-T1（planner 追加行）：barrel 恰导出 17 项
# （含 invalidate_repository），loader/cache/signature/access 不可从包顶层取得。
@pytest.mark.skip(reason="stub：由 Plan 121-09 实现")
def test_barrel_exports_are_curated() -> None:
    pass
