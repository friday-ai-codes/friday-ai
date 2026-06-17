"""RepositorySerializer.methodology 只读派生字段守护（Phase 48 Plan 02，SDD-02）。

为满足「仓库列表与详情页可见 SDD 方法论标签」，标准 RepositorySerializer 从
``facets["methodology"]`` 派生只读 ``methodology`` 字段（无 facets / 未打标时为 None）。

覆盖：
- facets 含 methodology="SDD" → 序列化输出 "SDD"。
- 无 facets / methodology 缺省 → 输出 None。
- 字段为只读：写入被忽略（不进 validated_data）。
"""

from __future__ import annotations

import pytest

from repositories.models import Repository
from repositories.serializers import RepositorySerializer


@pytest.fixture
def repo(db) -> Repository:
    return Repository.objects.create(
        name="methodology-repo",
        git_url="https://github.com/test/methodology-repo.git",
        git_platform="github",
        default_branch="main",
    )


@pytest.mark.django_db
def test_methodology_derived_from_facets_sdd(repo: Repository) -> None:
    repo.facets = {"methodology": "SDD"}
    repo.save(update_fields=["facets"])

    data = RepositorySerializer(repo).data
    assert data["methodology"] == "SDD"


@pytest.mark.django_db
def test_methodology_null_when_absent(repo: Repository) -> None:
    data = RepositorySerializer(repo).data
    assert "methodology" in data
    assert data["methodology"] is None


@pytest.mark.django_db
def test_methodology_is_read_only(repo: Repository) -> None:
    """SerializerMethodField 始终只读——写入不进 validated_data。"""
    serializer = RepositorySerializer(repo, data={"methodology": "forged"}, partial=True)
    assert serializer.is_valid(), serializer.errors
    assert "methodology" not in serializer.validated_data
