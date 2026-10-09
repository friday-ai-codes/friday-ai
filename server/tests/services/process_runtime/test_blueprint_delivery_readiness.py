from copy import deepcopy

import pytest

from services.process_runtime.blueprint_delivery_readiness import evaluate_delivery_readiness
from services.process_runtime.blueprint_execution import derive_execution_plan
from services.process_runtime.blueprint_merge import (
    _bind_delivery_providers,
    _demote_ignored_support_contracts,
)


def fixture():
    schema = {
        "type": "object",
        "properties": {"topics": {"type": "array", "items": {"type": "object"}}},
        "required": ["topics"],
    }
    provider = {
        "id": "p",
        "kind": "http",
        "method": "GET",
        "path": "/topics",
        "direction": "provided",
        "repository_id": "backend",
        "request_schema": {"type": "object"},
        "response_schema": schema,
        "delivery": {
            "status": "planned_in_scope",
            "implementation_item_ids": ["build"],
            "fields_needed": ["topics"],
            "data_sources": [
                {
                    "field": "topics",
                    "kind": "planned",
                    "implementation_item_id": "build",
                    "owner": "backend-team",
                    "acceptance": "seed and read back",
                }
            ],
        },
    }
    consumer = {
        **deepcopy(provider),
        "id": "c",
        "direction": "consumed",
        "repository_id": "web",
        "delivery": {
            "status": "planned_in_scope",
            "implementation_item_ids": ["ui"],
            "provider_repository_id": "backend",
            "provider_contract_id": "p",
        },
    }
    return {
        "delivery_contract_version": 1,
        "repo_associations": [
            {"repository_id": "backend", "repository_name": "backend"},
            {"repository_id": "web", "repository_name": "web"},
        ],
        "requirement_spec": {"feature_points": [{"id": "f"}]},
        "implementation_overview": {
            "items": [
                {
                    "id": "build",
                    "feature_point_id": "f",
                    "repository_id": "backend",
                    "title": "API",
                    "test_strategy": [{"text": "write and read"}],
                },
                {
                    "id": "ui",
                    "feature_point_id": "f",
                    "repository_id": "web",
                    "title": "UI",
                    "test_strategy": [{"text": "consume provider fixture"}],
                },
            ]
        },
        "api_contracts": [provider, consumer],
    }


def codes(b):
    return {x["code"] for x in evaluate_delivery_readiness(b)["blockers"]}


def test_planned_api_can_be_ready_without_existing_implementation():
    b = fixture()
    assert evaluate_delivery_readiness(b)["ready"]
    tasks = derive_execution_plan(b)
    assert evaluate_delivery_readiness(b, tasks=tasks)["ready"]
    assert tasks[0]["provides"] == ["p"]
    assert tasks[1]["consumes"] == ["c"]


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda b: b["implementation_overview"]["items"].pop(0), "contract_task_missing"),
        (lambda b: b["api_contracts"][0].pop("response_schema"), "response_schema_missing"),
        (
            lambda b: b["api_contracts"][1].update(response_schema={"type": "array"}),
            "provider_consumer_schema_mismatch",
        ),
        (
            lambda b: b["api_contracts"][0]["delivery"]["data_sources"][0].update(
                implementation_item_id="missing"
            ),
            "data_build_task_missing",
        ),
        (
            lambda b: b["api_contracts"][1]["delivery"].update(provider_contract_id="missing"),
            "provider_binding_missing",
        ),
        (
            lambda b: b["requirement_spec"]["feature_points"].append({"id": "unimplemented"}),
            "feature_task_missing",
        ),
        (
            lambda b: b["api_contracts"][0]["delivery"]["data_sources"].clear(),
            "data_sources_missing",
        ),
        (
            lambda b: b["api_contracts"][0]["delivery"].update(status="existing_verified"),
            "existing_evidence_missing",
        ),
    ],
)
def test_delivery_holes_fail_closed(mutate, code):
    b = fixture()
    mutate(b)
    assert code in codes(b)


def test_legacy_handoff_is_readable_but_not_ready():
    b = fixture()
    b.pop("delivery_contract_version")
    assert "legacy_contract_unverified" in codes(b)
    assert not evaluate_delivery_readiness(b)["ready"]


def test_dropped_task_detected_even_when_other_tasks_exist():
    b = fixture()
    tasks = derive_execution_plan(b)
    assert "task_projection_loss" in {
        x["code"] for x in evaluate_delivery_readiness(b, tasks=tasks[:1])["blockers"]
    }


def test_external_refs_require_immutable_hash_and_path():
    b = fixture()
    c = b["api_contracts"][0]
    c.pop("request_schema")
    c["delivery"]["request_schema_ref"] = {
        "repository_id": "backend",
        "commit_sha": "a" * 40,
        "path": "api/schema.json",
        "sha256": "b" * 64,
    }
    assert "request_schema_missing" not in codes(b)
    c["delivery"]["request_schema_ref"]["path"] = "../secrets"
    assert "request_schema_missing" in codes(b)


def test_deferral_requires_human_decision_and_disables_consumer():
    b = fixture()
    c = b["api_contracts"][1]
    c["delivery"] = {"status": "deferred", "decision_id": "d", "consumer_disabled": True}
    assert "deferred_without_decision" in codes(b)
    b["decision_log"] = [{"id": "d", "decided_by": "human"}]
    assert "deferred_without_decision" not in codes(b)


def test_ignored_repository_never_becomes_existing_by_exclusion():
    c = fixture()["api_contracts"][1]
    c["data_source"] = {"availability": "needs_support", "support_repository_id": "backend"}
    _demote_ignored_support_contracts([c], ["backend"])
    assert c["data_source"]["availability"] == "needs_support"
    assert c["delivery"]["status"] == "unresolved"


def test_provider_binding_never_uses_display_name():
    b = fixture()
    c = b["api_contracts"][1]
    c["delivery"].pop("provider_contract_id")
    c["path"] = "/wrong"
    _bind_delivery_providers(b["api_contracts"])
    assert "provider_contract_id" not in c["delivery"]
    c["path"] = "/topics"
    _bind_delivery_providers(b["api_contracts"])
    assert c["delivery"]["provider_contract_id"] == "p"


def test_invalid_schema_never_treated_as_ready():
    b = fixture()
    b["api_contracts"][0]["response_schema"] = {"type": "nonsense"}
    assert "response_schema_missing" in codes(b)


def test_declared_schema_fields_cannot_disappear_from_source_matrix():
    b = fixture()
    b["api_contracts"][0]["response_schema"]["properties"]["knowledgeCard"] = {"type": "object"}
    assert "response_field_source_uncovered" in codes(b)


def test_malformed_identity_cannot_crash_or_return_ready():
    b = fixture()
    b["api_contracts"][0]["id"] = ["not-an-id"]
    assert not evaluate_delivery_readiness(b)["ready"]


def test_mapping_preserves_contract_references_and_implementation_ids():
    from mcp_tools.technical_plan_service import _map_execution_plan_to_repository_tasks

    b = fixture()
    mapped = _map_execution_plan_to_repository_tasks({"execution_plan": derive_execution_plan(b)})
    assert evaluate_delivery_readiness(b, tasks=mapped)["ready"]
    assert mapped[0]["implementation_item_ids"] == ["build"]
    assert mapped[1]["consumes"] == ["c"]
