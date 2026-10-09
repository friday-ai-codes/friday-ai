"""Deterministic, versioned business delivery checks; no I/O or model calls.

Legacy blueprints remain readable, but never acquire a ready verdict by omission.
Fresh merges carry delivery_contract_version=1 and are gated at review/confirmation.
"""

from __future__ import annotations

import re
from typing import Any

from jsonschema import Draft202012Validator

VERSION = 1
VALIDATOR_VERSION = "delivery-readiness/1"
STATUSES = {"existing_verified", "planned_in_scope", "external_verified", "deferred"}


def _rows(value: Any) -> list[dict]:
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _ids(value: Any) -> list[str]:
    return [x for x in value if _text(x)] if isinstance(value, list) else []


def _schema(contract: dict, side: str) -> bool:
    schema = contract.get(f"{side}_schema")
    if (
        isinstance(schema, dict)
        and schema
        and any(k in schema for k in ("type", "properties", "$ref", "oneOf", "anyOf", "allOf"))
    ):
        try:
            Draft202012Validator.check_schema(schema)
            # External $ref resolution is not performed by this pure validator.
            return not any(
                isinstance(ref, str) and not ref.startswith("#") for ref in _refs(schema)
            )
        except Exception:
            return False
    ref = (
        contract.get("delivery", {}).get(f"{side}_schema_ref")
        if isinstance(contract.get("delivery"), dict)
        else None
    )
    return bool(
        isinstance(ref, dict)
        and _text(ref.get("repository_id"))
        and re.fullmatch(r"[a-f0-9]{40}", str(ref.get("commit_sha", "")))
        and _text(ref.get("path"))
        and not ref["path"].startswith("/")
        and ".." not in ref["path"].split("/")
        and re.fullmatch(r"[a-f0-9]{64}", str(ref.get("sha256", "")))
    )


def _refs(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref":
                yield item
            yield from _refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _refs(item)


def _evaluate_delivery_readiness(
    content: Any, *, content_hash: str = "", tasks: list[dict] | None = None
) -> dict:
    data = content if isinstance(content, dict) else {}
    blockers: list[dict] = []
    matrix: list[dict] = []

    def block(code: str, location: str):
        blockers.append({"code": code, "location": location})

    version = data.get("delivery_contract_version")
    if version != VERSION or isinstance(version, bool):
        block(
            "legacy_contract_unverified" if version is None else "unsupported_delivery_contract",
            "delivery_contract_version",
        )
    items = (
        _rows((data.get("implementation_overview") or {}).get("items"))
        if isinstance(data.get("implementation_overview"), dict)
        else []
    )
    contracts = _rows(data.get("api_contracts"))
    repos = {
        x.get("repository_id")
        for x in _rows(data.get("repo_associations"))
        if _text(x.get("repository_id"))
    }
    item_map = {x.get("id"): x for x in items if _text(x.get("id"))}
    contract_map = {x.get("id"): x for x in contracts if _text(x.get("id"))}
    if not items:
        block("implementation_missing", "implementation_overview.items")
    if len(item_map) != len(items):
        block("item_identity_invalid", "implementation_overview.items")
    if len(contract_map) != len(contracts):
        block("contract_identity_invalid", "api_contracts")
    for item in items:
        if item.get("repository_id") not in repos:
            block("item_repository_unknown", str(item.get("id")))
        for dep in _ids(item.get("depends_on")):
            if dep not in item_map:
                block("dependency_unknown", str(item.get("id")))
    spec = data.get("requirement_spec") if isinstance(data.get("requirement_spec"), dict) else {}
    features = _rows(spec.get("feature_points"))
    if not features:
        block("features_missing", "requirement_spec.feature_points")
    for feature in features:
        matching = [x for x in items if x.get("feature_point_id") == feature.get("id")]
        if not matching:
            block("feature_task_missing", str(feature.get("id")))
        elif not all(x.get("test_strategy") for x in matching):
            block("feature_acceptance_missing", str(feature.get("id")))
    for c in contracts:
        cid = str(c.get("id", "?"))
        d = c.get("delivery") if isinstance(c.get("delivery"), dict) else {}
        status = d.get("status")
        if status not in STATUSES:
            block("contract_unresolved", cid)
        if status == "deferred":
            decisions = _rows(data.get("decision_log"))
            if d.get("consumer_disabled") is not True or not any(
                x.get("id") == d.get("decision_id") and x.get("decided_by") == "human"
                for x in decisions
            ):
                block("deferred_without_decision", cid)
            continue
        if c.get("kind") not in ["http", "rpc", "event", "mq"]:
            block("contract_kind_invalid", cid)
        if not _text(c.get("path")):
            block("contract_address_missing", cid)
        if c.get("kind") == "http" and c.get("method", "").upper() not in [
            "GET",
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
            "HEAD",
            "OPTIONS",
        ]:
            block("http_method_invalid", cid)
        for side in ["request", "response"]:
            if not _schema(c, side):
                block(f"{side}_schema_missing", cid)
        if c.get("direction") not in ("provided", "consumed"):
            block("contract_direction_invalid", cid)
        rid = c.get("repository_id")
        if rid not in repos:
            block("contract_repository_unknown", cid)
        own = _ids(d.get("implementation_item_ids"))
        if c.get("direction") == "consumed" or status == "planned_in_scope":
            if not own or any(
                i not in item_map or item_map[i].get("repository_id") != rid for i in own
            ):
                block("contract_task_missing", cid)
        provider = None
        if c.get("direction") == "consumed":
            provider = contract_map.get(d.get("provider_contract_id"))
            if status != "external_verified":
                if (
                    not provider
                    or provider.get("direction") != "provided"
                    or provider.get("repository_id") != d.get("provider_repository_id")
                ):
                    block("provider_binding_missing", cid)
                elif any(
                    c.get(k) != provider.get(k)
                    for k in ["kind", "method", "path", "request_schema", "response_schema"]
                ):
                    block("provider_consumer_schema_mismatch", cid)
        if provider:
            for side in ("request", "response"):
                consumer_ref = d.get(f"{side}_schema_ref")
                provider_ref = (provider.get("delivery") or {}).get(f"{side}_schema_ref")
                if consumer_ref != provider_ref:
                    block("provider_consumer_schema_ref_mismatch", cid)
        if status in ["existing_verified", "external_verified"] and not _evidence(
            d.get("evidence")
        ):
            block("existing_evidence_missing", cid)
        if c.get("direction") == "provided" or status == "external_verified":
            sources = _rows(d.get("data_sources"))
            needed = _ids(d.get("fields_needed"))
            response = c.get("response_schema")
            fields = (
                set(response.get("properties", {}))
                if isinstance(response, dict) and isinstance(response.get("properties"), dict)
                else set()
            )
            if fields and not fields.issubset(set(needed)):
                block("response_field_source_uncovered", cid)
            if not sources or not needed:
                block("data_sources_missing", cid)
            for field in needed:
                candidates = [x for x in sources if x.get("field") == field]
                if len(candidates) != 1:
                    block("field_source_missing", cid)
                    continue
                src = candidates[0]
                if src.get("kind") == "planned":
                    item_id = src.get("implementation_item_id")
                    if (
                        item_id not in item_map
                        or item_map[item_id].get("repository_id") != rid
                        or not _text(src.get("owner"))
                        or not _text(src.get("acceptance"))
                    ):
                        block("data_build_task_missing", cid)
                elif not _evidence(src.get("evidence")):
                    block("data_source_evidence_missing", cid)
        matrix.append(
            {
                "contract_id": cid,
                "repository_id": rid,
                "direction": c.get("direction"),
                "status": status,
                "implementation_item_ids": own,
                "provider_contract_id": d.get("provider_contract_id"),
                "provider_task_id": f"task_{provider['repository_id']}" if provider else None,
            }
        )
    if tasks is not None:
        expected = {x.get("id") for x in items}
        actual = [i for t in tasks for i in _ids(t.get("implementation_item_ids"))]
        if set(actual) != expected or len(actual) != len(set(actual)):
            block("task_projection_loss", "repository_tasks")
    return {
        "schemaVersion": VERSION,
        "validatorVersion": VALIDATOR_VERSION,
        "contentHash": content_hash,
        "ready": not blockers,
        "status": "ready" if not blockers else "blocked",
        "blockers": blockers,
        "contractTaskMatrix": matrix,
    }


def _evidence(value: Any) -> bool:
    return bool(
        isinstance(value, dict)
        and _text(value.get("repository_id"))
        and re.fullmatch(r"[a-f0-9]{40}", str(value.get("commit_sha", "")))
        and _text(value.get("path"))
        and not value["path"].startswith("/")
        and ".." not in value["path"].split("/")
    )


def project_delivery_refs(content: dict, repository_id: str) -> dict:
    """Lossless stable IDs; no route-name matching or semantic guessing."""
    items = _rows((content.get("implementation_overview") or {}).get("items"))
    local = [x for x in items if x.get("repository_id") == repository_id]
    contracts = _rows(content.get("api_contracts"))
    return {
        "implementation_item_ids": sorted(x["id"] for x in local),
        "feature_point_ids": sorted(
            {x["feature_point_id"] for x in local if _text(x.get("feature_point_id"))}
        ),
        "provides": sorted(
            c["id"]
            for c in contracts
            if c.get("repository_id") == repository_id and c.get("direction") == "provided"
        ),
        "contract_dependencies": sorted(
            {
                "task_" + c["delivery"]["provider_repository_id"]
                for c in contracts
                if c.get("repository_id") == repository_id
                and c.get("direction") == "consumed"
                and isinstance(c.get("delivery"), dict)
                and c["delivery"].get("status") == "planned_in_scope"
                and _text(c["delivery"].get("provider_repository_id"))
                and c["delivery"]["provider_repository_id"] != repository_id
            }
        ),
        "consumes": sorted(
            c["id"]
            for c in contracts
            if c.get("repository_id") == repository_id and c.get("direction") == "consumed"
        ),
    }


def evaluate_delivery_readiness(
    content: Any, *, content_hash: str = "", tasks: list[dict] | None = None
) -> dict:
    try:
        return _evaluate_delivery_readiness(content, content_hash=content_hash, tasks=tasks)
    except (TypeError, ValueError, AttributeError, KeyError):
        return {
            "schemaVersion": VERSION,
            "validatorVersion": VALIDATOR_VERSION,
            "contentHash": content_hash,
            "ready": False,
            "status": "blocked",
            "blockers": [{"code": "malformed_delivery_contract", "location": "blueprint"}],
            "contractTaskMatrix": [],
        }
