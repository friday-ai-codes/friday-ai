"""Phase Plan（ 加列部分）：codegraph 5 模型 branch_name 字段自省。
纯 ``_meta`` 自省断言，不依赖数据库、不需 apply 迁移。同时断言越界防御：
ApiCallSite / CrossRepoApiCall **不应**有 branch_name 字段（不在 v26.2 范围）。
"""
from __future__ import annotations
import pytest
from django.core.exceptions import FieldDoesNotExist
from django.db.models import CharField, Model
from codegraph.models import (
 ApiCallSite,
 ApiWrapper,
 CallEdge,
 CrossRepoApiCall,
 Endpoint,
 ImportEdge,
 Symbol,
)
_BRANCH_MODELS: list[type[Model]] = [Symbol, ImportEdge, CallEdge, Endpoint, ApiWrapper]
_OUT_OF_SCOPE_MODELS: list[type[Model]] = [ApiCallSite, CrossRepoApiCall]
@pytest.mark.parametrize("model", _BRANCH_MODELS)
def test_codegraph_model_has_branch_name(model: type[Model]) -> None:
 """：codegraph 5 模型均有 branch_name，max_length=200、default=""。"""
 field = model._meta.get_field("branch_name")
 assert isinstance(field, CharField)
 assert field.max_length == 200
 assert field.default == ""
@pytest.mark.parametrize("model", _OUT_OF_SCOPE_MODELS)
def test_out_of_scope_models_have_no_branch_name(model: type[Model]) -> None:
 """越界防御：ApiCallSite / CrossRepoApiCall 不在 v26.2 范围，不得新增 branch_name。"""
 with pytest.raises(FieldDoesNotExist):
 model._meta.get_field("branch_name")
