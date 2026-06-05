"""initial implementation plan（work item 加列部分）：code_relations 2 模型 branch_name 字段自省。

纯 ``_meta`` 自省断言，不依赖数据库、不需 apply 迁移。
"""

from __future__ import annotations

import pytest
from django.db.models import CharField, Model

from code_relations.models import ChunkEdge, ChunkRegistry

_BRANCH_MODELS: list[type[Model]] = [ChunkRegistry, ChunkEdge]


@pytest.mark.parametrize("model", _BRANCH_MODELS)
def test_code_relations_model_has_branch_name(model: type[Model]) -> None:
    """work item：ChunkRegistry / ChunkEdge 均有 branch_name，max_length=200、default=""。"""
    field = model._meta.get_field("branch_name")
    assert isinstance(field, CharField)
    assert field.max_length == 200
    assert field.default == ""
