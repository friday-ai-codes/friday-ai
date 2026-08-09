"""ProcessTrace 模型契约验收（EXEC-01 / D-01 / D-04）。"""

from __future__ import annotations

import codegraph.models as cg_models
from codegraph.models import Endpoint, ProcessTrace
from django.db import models


def test_process_trace_fields_and_unique_together() -> None:
    """ProcessTrace 字段最小集 + unique_together=(repository, branch_name, process_key)。

    （Req: EXEC-01, 决策: D-01）
    """
    field_names = {f.name for f in ProcessTrace._meta.get_fields()}
    required = {
        "id",
        "repository",
        "branch_name",
        "process_key",
        "name",
        "entry_endpoint",
        "steps",
        "community_class",
        "step_count",
        "built_at_sha",
        "created_at",
        "updated_at",
    }
    assert required.issubset(field_names), f"missing fields: {required - field_names}"

    branch = ProcessTrace._meta.get_field("branch_name")
    assert isinstance(branch, models.CharField)
    assert branch.default == ""

    entry = ProcessTrace._meta.get_field("entry_endpoint")
    assert isinstance(entry, models.JSONField)

    steps = ProcessTrace._meta.get_field("steps")
    assert isinstance(steps, models.JSONField)

    community_class = ProcessTrace._meta.get_field("community_class")
    assert isinstance(community_class, models.CharField)
    choice_values = {c[0] for c in ProcessTrace.CommunityClass.choices}
    assert choice_values == {"intra_community", "cross_community"}

    ut = list(ProcessTrace._meta.unique_together)
    assert ("repository", "branch_name", "process_key") in ut

    index_fields = {tuple(idx.fields) for idx in ProcessTrace._meta.indexes}
    assert ("repository", "branch_name") in index_fields


def test_process_trace_has_no_endpoint_fk() -> None:
    """entry_endpoint 为 JSONField；无指向 Endpoint 的 ForeignKey。

    （Req: EXEC-01, 决策: D-01）
    """
    for field in ProcessTrace._meta.get_fields():
        if isinstance(field, models.ForeignKey) and field.related_model is Endpoint:
            raise AssertionError(f"ProcessTrace must not FK Endpoint via {field.name}")
        if getattr(field, "related_model", None) is Endpoint:
            raise AssertionError(f"ProcessTrace must not relate to Endpoint via {field.name}")


def test_process_trace_not_named_process() -> None:
    """codegraph.models 无名为 Process 的 ORM 类（避免与 process_runtime 撞名）。

    （Req: EXEC-01, 决策: D-01）
    """
    assert hasattr(cg_models, "ProcessTrace")
    assert not hasattr(cg_models, "Process") or not isinstance(
        getattr(cg_models, "Process", None), type
    )
    assert not any(
        isinstance(obj, type)
        and issubclass(obj, models.Model)
        and obj.__name__ == "Process"
        and obj.__module__ == "codegraph.models"
        for obj in vars(cg_models).values()
    )
