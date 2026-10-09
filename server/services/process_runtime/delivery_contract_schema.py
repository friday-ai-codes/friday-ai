"""Additive delivery extension shared by blueprint and RepoPlan schemas."""

EVIDENCE_SCHEMA = {
    "type": "object",
    "required": ["repository_id", "commit_sha", "path"],
    "properties": {
        "repository_id": {"type": "string", "minLength": 1},
        "commit_sha": {"type": "string", "pattern": "^[a-f0-9]{40}$"},
        "path": {"type": "string", "minLength": 1},
        "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
    },
}
DELIVERY_SCHEMA = {
    "type": "object",
    "required": ["status"],
    "properties": {
        "status": {
            "enum": [
                "existing_verified",
                "planned_in_scope",
                "external_verified",
                "unresolved",
                "deferred",
            ]
        },
        "implementation_item_ids": {
            "type": "array",
            "items": {"type": "string"},
            "uniqueItems": True,
        },
        "provider_repository_id": {"type": "string"},
        "provider_contract_id": {"type": "string"},
        "fields_needed": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        "data_sources": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["field", "kind"],
                "properties": {
                    "field": {"type": "string"},
                    "kind": {"enum": ["planned", "existing"]},
                    "implementation_item_id": {"type": "string"},
                    "owner": {"type": "string"},
                    "acceptance": {"type": "string"},
                    "evidence": EVIDENCE_SCHEMA,
                },
            },
        },
        "evidence": EVIDENCE_SCHEMA,
        "request_schema_ref": EVIDENCE_SCHEMA,
        "response_schema_ref": EVIDENCE_SCHEMA,
        "decision_id": {"type": "string"},
        "consumer_disabled": {"type": "boolean"},
    },
}
