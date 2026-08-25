"""共享 Agent→Friday MCP 结构化提交工厂测试（260818-pt8 Task 1/Task 2）。

覆盖：场景注册与隔离、tool 全名、prompt 契约、`apply_capture_to_result` 收口
（空捕获失败 / 有捕获覆盖 empty error），以及 fitness / repo_plan schema 与服务端
契约常量的**对照防漂移**（task 侧不得运行时 import Django）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.agent_submit_mcp import (
    MAX_SUBMIT_PAYLOAD_BYTES,
    MCP_TOOL_NOT_CALLED,
    REPO_PLAN_CHANGE_TYPES,
    SCENARIO_BLUEPRINT_FITNESS,
    SCENARIO_BLUEPRINT_REPO_PLAN,
    SCENARIO_REPO_SUMMARY,
    SUBMIT_MCP_SERVER_NAME,
    CaptureStore,
    apply_capture_to_result,
    build_submit_mcp,
    full_tool_name,
    get_scenario,
    known_scenarios,
    validate_submit_payload,
)

_SERVER_ROOT = Path(__file__).resolve().parents[2] / "server"


class TestScenarioRegistry:
    def test_three_builtin_scenarios_registered(self):
        scenarios = set(known_scenarios())
        assert {
            SCENARIO_REPO_SUMMARY,
            SCENARIO_BLUEPRINT_FITNESS,
            SCENARIO_BLUEPRINT_REPO_PLAN,
        } <= scenarios

    def test_unknown_scenario_raises(self):
        with pytest.raises(ValueError):
            get_scenario("does_not_exist")

    def test_tool_full_name_prefixed(self):
        assert full_tool_name("submit_repo_summary") == (
            f"mcp__{SUBMIT_MCP_SERVER_NAME}__submit_repo_summary"
        )

    def test_build_returns_isolated_capture_and_mount(self):
        a = build_submit_mcp(SCENARIO_REPO_SUMMARY)
        b = build_submit_mcp(SCENARIO_BLUEPRINT_FITNESS)
        # 场景隔离：两次构建的 capture 相互独立
        assert a.capture is not b.capture
        a.capture.value = {"x": 1}
        assert b.capture.value is None
        # 挂载信息齐备
        assert a.full_tool_name in a.allowed_tools
        assert SUBMIT_MCP_SERVER_NAME in a.mcp_servers
        assert a.prompt_contract  # 非空契约段


class TestApplyCaptureToResult:
    def test_no_capture_marks_failure_with_stable_reason(self):
        capture = CaptureStore()
        result = apply_capture_to_result(
            {"success": True, "output": "some free text"},
            capture,
            scenario=SCENARIO_REPO_SUMMARY,
        )
        assert result["success"] is False
        assert result["error_reason"] == MCP_TOOL_NOT_CALLED
        assert result["submit_scenario"] == SCENARIO_REPO_SUMMARY
        assert "mcp_result" not in result

    def test_capture_overrides_empty_error(self):
        capture = CaptureStore(value={"overview": "ok"})
        result = apply_capture_to_result(
            {"success": False, "error": "Claude SDK returned empty response"},
            capture,
            scenario=SCENARIO_REPO_SUMMARY,
        )
        assert result["success"] is True
        assert "error" not in result
        assert result["mcp_result"] == {"overview": "ok"}
        assert result["submit_scenario"] == SCENARIO_REPO_SUMMARY


class TestPromptContract:
    def test_each_scenario_contract_names_its_tool(self):
        for scenario in (
            SCENARIO_REPO_SUMMARY,
            SCENARIO_BLUEPRINT_FITNESS,
            SCENARIO_BLUEPRINT_REPO_PLAN,
        ):
            built = build_submit_mcp(scenario)
            assert built.full_tool_name in built.prompt_contract
            # 契约明确禁止把 JSON 写进普通文本回复
            assert "不要把 JSON 写在普通文本" in built.prompt_contract


class TestSchemaDriftGuards:
    """task 侧 fitness / repo_plan schema 关键 required/enum 必须与服务端常量一致。"""

    def test_fitness_required_and_verdict_enum_match_server(self):
        spec = get_scenario(SCENARIO_BLUEPRINT_FITNESS)
        props = spec.input_schema["properties"]
        assert set(spec.input_schema["required"]) == {
            "fitness",
            "role_suggestion",
            "responsibility",
            "findings",
        }
        verdict_enum = set(props["fitness"]["properties"]["verdict"]["enum"])
        assert verdict_enum == {"suitable", "partial", "unsuitable"}

        # 对照服务端 callbacks.py：fitness verdict 必含同一组枚举字面量。
        cb = (_SERVER_ROOT / "subagent" / "api" / "callbacks.py").read_text()
        for verdict in ("suitable", "partial", "unsuitable"):
            assert verdict in cb

    def test_repo_plan_change_types_match_server_schema(self):
        spec = get_scenario(SCENARIO_BLUEPRINT_REPO_PLAN)
        section = spec.input_schema["properties"]["repo_plan"]
        assert set(section["required"]) >= {"role", "impl_items"}

        server_schema = (
            _SERVER_ROOT / "services" / "process_runtime" / "blueprint_repo_plan_schema.py"
        ).read_text()
        # 服务端 change_type 枚举字面量必须逐个出现在服务端 schema 源码里（防漂移）。
        m = re.search(r"REPO_PLAN_CHANGE_TYPES\s*=\s*\(([^)]*)\)", server_schema, re.S)
        assert m, "server REPO_PLAN_CHANGE_TYPES not found"
        server_change_types = set(re.findall(r'"([^"]+)"', m.group(1)))
        assert set(REPO_PLAN_CHANGE_TYPES) == server_change_types

    def test_repo_plan_schema_is_bounded_and_closed(self):
        spec = get_scenario(SCENARIO_BLUEPRINT_REPO_PLAN)
        root = spec.input_schema
        section = root["properties"]["repo_plan"]
        assert root["additionalProperties"] is False
        assert section["additionalProperties"] is False
        assert section["properties"]["impl_items"]["maxItems"] > 0
        assert section["properties"]["impl_items"]["items"]["additionalProperties"] is False
        assert section["properties"]["impl_items"]["items"]["properties"]["how"]["maxLength"] > 0


class TestSubmitPayloadLimits:
    def test_payload_at_limit_is_accepted(self):
        payload = {"repo_plan": {"role": "direct", "impl_items": []}}
        assert validate_submit_payload(payload) > 0

    def test_oversized_payload_is_rejected_before_capture(self):
        payload = {
            "repo_plan": {
                "role": "direct",
                "impl_items": [],
                "padding": "x" * MAX_SUBMIT_PAYLOAD_BYTES,
            }
        }
        with pytest.raises(ValueError, match="payload_too_large"):
            validate_submit_payload(payload)
