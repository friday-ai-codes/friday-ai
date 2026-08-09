"""``services/code_graph/signature.py`` 的复合签名用例（覆盖 GRAPH-02、GRAPH-04）。

签名 = 水位 ‖ 轨 A（IndexHistory / ChunkEdge）‖ 轨 B（GraphBuildHistory /
Symbol·CallEdge）‖ 计数 ‖ exclusion 规则指纹。

四个用例分别锁死四类敏感性中的一类，外加「无变化时稳定」这条前提——没有稳定性，
敏感性断言全都是假阳性（任意两次计算都不等，当然"敏感"）。
"""

from __future__ import annotations

import pytest

from services.code_graph.signature import compute_signature

pytestmark = pytest.mark.django_db

_FP = "0123456789abcdef"


# 121-VALIDATION.md 121-04-T1：无变更时签名稳定（连算两次相等）。
def test_signature_stable_without_changes(indexed_repo, branch_index) -> None:
    """同参数、无任何写入 ⇒ 两次签名逐字符相等。

    这条是其余全部敏感性断言的前提：若签名自身不稳定（例如把 ``timezone.now()``
    或某个 ``auto_now`` 字段拼了进去），「改了 X 之后签名变了」就不能证明任何事。
    """
    first = compute_signature(
        str(indexed_repo.id), "", exclusion_fingerprint=_FP
    )
    second = compute_signature(
        str(indexed_repo.id), "", exclusion_fingerprint=_FP
    )

    assert first == second
    assert len(first) == 64  # sha256 十六进制串


# 121-VALIDATION.md 121-04-T1：签名对 last_indexed_commit_sha 变化敏感。
def test_signature_watermark_sensitive(db, indexed_repo, branch_index) -> None:
    """水位分量对两条路径都敏感：分支索引行优先，无行时回落 ``Repository``。

    第一段同时是**分支键翻译的回归**（RESEARCH Pitfall 6）：只改
    ``RepositoryBranchIndex.last_indexed_commit_sha``、**不动** ``Repository`` 的，
    签名若不变就说明查询压根没命中 ``is_base_branch=True`` 的行、静默退化成了
    「永远走 Repository 回落」。
    """
    from repositories.models import IndexStatus, Repository

    before = compute_signature(str(indexed_repo.id), "", exclusion_fingerprint=_FP)

    branch_index.last_indexed_commit_sha = "b" * 40
    branch_index.save(update_fields=["last_indexed_commit_sha"])

    after = compute_signature(str(indexed_repo.id), "", exclusion_fingerprint=_FP)
    assert after != before, "分支索引行的水位推进未反映到签名（键翻译很可能落空）"

    # 回落路径：没有任何 RepositoryBranchIndex 行的老仓。
    bare_repo = Repository.objects.create(
        name="code-graph-bare-repo",
        git_url="https://example.com/code-graph-bare-repo.git",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
        last_indexed_commit_sha="c" * 40,
    )
    bare_before = compute_signature(str(bare_repo.id), "", exclusion_fingerprint=_FP)

    bare_repo.last_indexed_commit_sha = "d" * 40
    bare_repo.save(update_fields=["last_indexed_commit_sha"])

    bare_after = compute_signature(str(bare_repo.id), "", exclusion_fingerprint=_FP)
    assert bare_after != bare_before, "无分支索引行时未回落到 Repository 水位"


# 121-VALIDATION.md 121-04-T1：exclusion 规则变更 ⇒ 指纹变 ⇒ 签名变 ⇒ 旧图失效
# （不依赖 matcher 的 60s TTL，TTL 不是版本号）。
def test_signature_exclusion_fingerprint_changes(indexed_repo, branch_index) -> None:
    """同一仓库、同一分支，仅 exclusion 指纹入参不同 ⇒ 签名不同（GRAPH-04）。

    指纹由 ``access.build_matcher_and_fingerprint`` 对**有效规则集**哈希得出，
    覆盖 per-repo 规则 / ``SystemSetting`` 全局 JSON / ``BUILTIN_GLOBAL_DEFAULTS``
    三个来源；本用例只验证「指纹变化会穿透到签名」这一段接线。
    """
    repo_id = str(indexed_repo.id)

    with_a = compute_signature(repo_id, "", exclusion_fingerprint=_FP)
    with_b = compute_signature(repo_id, "", exclusion_fingerprint="fedcba9876543210")

    assert with_a != with_b


# 121-VALIDATION.md 121-04-T2：签名对**两条**边构建轨各自的变化都敏感（D-02）——
# 只看 IndexHistory 一条轨会漏失效，CallEdge 抽取走的是另一条轨。
@pytest.mark.skip(reason="stub：由 Plan 121-04 Task 2 实现")
def test_signature_generation_two_tracks() -> None:
    pass
