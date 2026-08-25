"""Phase 139：五消费面 canonical graph_query manifest 一致性。"""

from __future__ import annotations

import re
import runpy
from copy import deepcopy
from pathlib import Path

from agents.tools import graph_query as _registered_graph_query  # noqa: F401
from agents.tools.registry import ToolRegistry
from mcp_tools.serializers import GraphQueryRequestSerializer
from services.code_graph.query_manifest import (
    graph_query_manifest,
    graph_query_manifest_hash,
)
from services.code_graph.query_service import (
    GRAPH_QUERY_RANKING_VERSION,
    GRAPH_QUERY_RESPONSE_VERSION,
)

_ROOT = Path(__file__).resolve().parents[4]


def test_service_and_chat_discovery_share_canonical_manifest() -> None:
    manifest = graph_query_manifest()
    assert manifest["response_version"] == GRAPH_QUERY_RESPONSE_VERSION
    assert manifest["ranking_version"] == GRAPH_QUERY_RANKING_VERSION

    tool = ToolRegistry.get_tool("graph_query")
    assert tool is not None
    exposed = deepcopy(tool.parameters)
    exposed["properties"].pop("conversation_id")
    exposed["required"].remove("conversation_id")
    assert exposed == manifest["inputSchema"]


def test_django_serializer_matches_canonical_fields_and_defaults() -> None:
    manifest = graph_query_manifest()
    serializer = GraphQueryRequestSerializer()
    assert set(serializer.fields) == set(manifest["inputSchema"]["properties"])
    for name, schema in manifest["inputSchema"]["properties"].items():
        field = serializer.fields[name]
        if "default" in schema:
            assert field.default == schema["default"]
        if "minimum" in schema:
            assert field.min_value == schema["minimum"]
        if "maximum" in schema:
            assert field.max_value == schema["maximum"]


def test_npm_and_task_generated_artifacts_match_full_manifest_hash() -> None:
    expected_hash = graph_query_manifest_hash()
    task_generated = runpy.run_path(
        str(_ROOT / "task/core/generated_graph_query_manifest.py")
    )
    assert task_generated["GRAPH_QUERY_MANIFEST_HASH"] == expected_hash
    assert task_generated["GRAPH_QUERY_MANIFEST"] == graph_query_manifest()
    assert task_generated["GRAPH_QUERY_TOOL_SCHEMA"]["input_schema"] == (
        graph_query_manifest()["inputSchema"]
    )

    ts = (_ROOT / "mcp/src/generated/graphQueryManifest.ts").read_text(
        encoding="utf-8"
    )
    found = re.search(r"GRAPH_QUERY_MANIFEST_HASH = '([a-f0-9]{64})'", ts)
    assert found is not None
    assert found.group(1) == expected_hash


def test_contract_declares_scope_versions_capabilities_and_errors() -> None:
    manifest = graph_query_manifest()
    assert manifest["contract_version"] == "graph-query-tool/v1"
    assert set(manifest["capabilities"]) == {
        "bm25",
        "embedding",
        "process_enrichment",
        "community",
        "impact",
    }
    assert "repository_id" in manifest["inputSchema"]["required"]
    assert "scope" in manifest["outputSchema"]["required"]
    assert "repository_access_denied" in manifest["errors"]
