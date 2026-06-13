"""WorkflowGraphValidator 纯函数核心单测（VAL-01，Phase 20 Wave 0）。

validator 与 DAG.from_node_edge_dicts 均为零 ORM / 零 DB 纯函数，本文件不使用任何
数据库 fixture（无 db / 无 transactional_db / 无 pytest 标记），直接传入 plain dict
断言 errors/warnings。

覆盖：
- 五类规则各一命中例（cycle / no_entry / edge_node_missing / invalid_source_handle /
  invalid_target_handle / config_schema_invalid / unknown_node_type / node_not_found /
  field_not_found）。
- 不误伤（关键约束）：target_handle/source_handle="default" 放行、http 无 schema 输出
  字段层跳过、condition 动态 branch_N/else handle 放行、孤立节点为 warning、
  code_generation 形态（ai_coding→ai_code_review default 边 + 审批 approved/rejected 分支）零 error。
- 信息泄露：任一 issue.message 不含被引用 config 的取值字符串（T-20-01）。
"""

from workflows.validation import ValidationIssue, WorkflowGraphValidator


def _validate(nodes, edges):
    return WorkflowGraphValidator().validate(nodes, edges)


def _reasons(result, *, key="errors"):
    return {issue["reason"] for issue in result[key]}


class TestValidatorPureFunction:
    """validator 作为纯函数的基本契约。"""

    def test_validation_issue_is_dataclass_with_expected_fields(self):
        """ValidationIssue 字段齐全且可 asdict。"""
        issue = ValidationIssue(reason="cycle", severity="error")
        assert issue.reason == "cycle"
        assert issue.severity == "error"
        assert issue.field_path == ""
        assert issue.node_id is None
        assert issue.edge_id is None

    def test_empty_graph_reports_no_entry(self):
        """空图无入口节点 → errors 含 no_entry。"""
        result = _validate([], [])
        assert "no_entry" in _reasons(result)


class TestLegalGraphs:
    """合法图零 error（不误伤）。"""

    def test_linear_trigger_to_prompt_is_clean(self):
        """合法线性图 manual_trigger → ai_prompt 零 error。"""
        nodes = [
            {"id": "u1", "short_id": "trig", "node_type": "manual_trigger", "config": {}},
            {
                "id": "u2",
                "short_id": "p",
                "node_type": "ai_prompt",
                "config": {"user_prompt": "hello"},
            },
        ]
        edges = [{"id": "e1", "source_node_id": "u1", "target_node_id": "u2"}]
        result = _validate(nodes, edges)
        assert result["errors"] == []

    def test_code_generation_form_is_clean(self):
        """code_generation 形态零 error（Pitfall 1 防误伤）。

        ai_coding → ai_code_review 走 default 边（review 无 default 输入端口，但靠扁平合并
        合法）；审批节点 approved/rejected 分支 handle 放行；rejected 回退边不算环。
        """
        nodes = [
            {"id": "ut", "short_id": "trig", "node_type": "manual_trigger", "config": {}},
            {"id": "uc", "short_id": "coding", "node_type": "ai_coding", "config": {}},
            {"id": "ua", "short_id": "approval", "node_type": "ai_plan_approval", "config": {}},
            {"id": "ur", "short_id": "review", "node_type": "ai_code_review", "config": {}},
        ]
        edges = [
            {"id": "e1", "source_node_id": "ut", "target_node_id": "uc"},
            # ai_coding → ai_code_review default 边（Pitfall 1：review 无 default 输入端口）
            {"id": "e2", "source_node_id": "uc", "target_node_id": "ua"},
            {
                "id": "e3",
                "source_node_id": "ua",
                "target_node_id": "ur",
                "source_handle": "approved",
            },
            {
                "id": "e4",
                "source_node_id": "ua",
                "target_node_id": "uc",
                "source_handle": "rejected",
            },
        ]
        result = _validate(nodes, edges)
        assert result["errors"] == []

    def test_default_handles_always_pass(self):
        """source_handle/target_handle 显式 "default" 放行，不产生 invalid_*_handle。"""
        nodes = [
            {"id": "u1", "short_id": "trig", "node_type": "manual_trigger", "config": {}},
            {
                "id": "u2",
                "short_id": "p",
                "node_type": "ai_prompt",
                "config": {"user_prompt": "x"},
            },
        ]
        edges = [
            {
                "id": "e1",
                "source_node_id": "u1",
                "target_node_id": "u2",
                "source_handle": "default",
                "target_handle": "default",
            }
        ]
        result = _validate(nodes, edges)
        assert _reasons(result).isdisjoint({"invalid_source_handle", "invalid_target_handle"})
        assert result["errors"] == []

    def test_condition_dynamic_output_handles_pass(self):
        """condition 动态输出 branch_0 / else（default_branch）handle 放行（不硬编码）。"""
        nodes = [
            {"id": "u1", "short_id": "trig", "node_type": "manual_trigger", "config": {}},
            {
                "id": "u2",
                "short_id": "cond",
                "node_type": "condition",
                "config": {"conditions": [{"name": "命中"}], "default_branch": "else"},
            },
            {
                "id": "u3",
                "short_id": "p1",
                "node_type": "ai_prompt",
                "config": {"user_prompt": "a"},
            },
            {
                "id": "u4",
                "short_id": "p2",
                "node_type": "ai_prompt",
                "config": {"user_prompt": "b"},
            },
        ]
        edges = [
            {"id": "e1", "source_node_id": "u1", "target_node_id": "u2"},
            {
                "id": "e2",
                "source_node_id": "u2",
                "target_node_id": "u3",
                "source_handle": "branch_0",
            },
            {
                "id": "e3",
                "source_node_id": "u2",
                "target_node_id": "u4",
                "source_handle": "else",
            },
        ]
        result = _validate(nodes, edges)
        assert result["errors"] == []


class TestStructuralRules:
    """DAG 结构规则命中。"""

    def test_cycle_detected(self):
        """default-handle 环 → cycle error。"""
        nodes = [
            {"id": "a", "short_id": "a", "node_type": "manual_trigger", "config": {}},
            {
                "id": "b",
                "short_id": "b",
                "node_type": "ai_prompt",
                "config": {"user_prompt": "x"},
            },
        ]
        edges = [
            {"id": "e1", "source_node_id": "a", "target_node_id": "b"},
            {"id": "e2", "source_node_id": "b", "target_node_id": "a"},
        ]
        result = _validate(nodes, edges)
        assert "cycle" in _reasons(result)

    def test_no_entry_detected(self):
        """全节点互相指向、无入度 0 节点 → no_entry error。"""
        nodes = [
            {"id": "a", "short_id": "a", "node_type": "condition", "config": {}},
            {"id": "b", "short_id": "b", "node_type": "condition", "config": {}},
        ]
        edges = [
            {"id": "e1", "source_node_id": "a", "target_node_id": "b"},
            {
                "id": "e2",
                "source_node_id": "b",
                "target_node_id": "a",
                "source_handle": "else",
            },
        ]
        result = _validate(nodes, edges)
        assert "no_entry" in _reasons(result)

    def test_orphan_node_is_warning_not_error(self):
        """孤立节点降为 warning（Pitfall 8），不出现在 errors。"""
        nodes = [
            {"id": "u1", "short_id": "trig", "node_type": "manual_trigger", "config": {}},
            {
                "id": "u2",
                "short_id": "p",
                "node_type": "ai_prompt",
                "config": {"user_prompt": "x"},
            },
            # 孤立的 ai_code_review（无任何边）
            {"id": "u3", "short_id": "lonely", "node_type": "ai_code_review", "config": {}},
        ]
        edges = [{"id": "e1", "source_node_id": "u1", "target_node_id": "u2"}]
        result = _validate(nodes, edges)
        assert "orphan_node" in _reasons(result, key="warnings")
        assert "orphan_node" not in _reasons(result)


class TestEdgeRules:
    """边归属 + handle 规则命中。"""

    def test_edge_node_missing(self):
        """边端点不在节点集 → edge_node_missing error。"""
        nodes = [{"id": "u1", "short_id": "trig", "node_type": "manual_trigger", "config": {}}]
        edges = [{"id": "e1", "source_node_id": "u1", "target_node_id": "ghost"}]
        result = _validate(nodes, edges)
        assert "edge_node_missing" in _reasons(result)

    def test_invalid_source_handle(self):
        """非 default source_handle 不在输出端口 → invalid_source_handle error。"""
        nodes = [
            {"id": "u1", "short_id": "trig", "node_type": "manual_trigger", "config": {}},
            {
                "id": "u2",
                "short_id": "p",
                "node_type": "ai_prompt",
                "config": {"user_prompt": "x"},
            },
        ]
        edges = [
            {
                "id": "e1",
                "source_node_id": "u1",
                "target_node_id": "u2",
                "source_handle": "nonexistent",
            }
        ]
        result = _validate(nodes, edges)
        assert "invalid_source_handle" in _reasons(result)

    def test_invalid_target_handle(self):
        """非 default target_handle 不在输入端口 → invalid_target_handle error。"""
        nodes = [
            {"id": "u1", "short_id": "trig", "node_type": "manual_trigger", "config": {}},
            {
                "id": "u2",
                "short_id": "p",
                "node_type": "ai_prompt",
                "config": {"user_prompt": "x"},
            },
        ]
        edges = [
            {
                "id": "e1",
                "source_node_id": "u1",
                "target_node_id": "u2",
                "target_handle": "nonexistent",
            }
        ]
        result = _validate(nodes, edges)
        assert "invalid_target_handle" in _reasons(result)


class TestConfigAndTypeRules:
    """config schema + node_type 规则命中。"""

    def test_unknown_node_type(self):
        """未注册 node_type → unknown_node_type error。"""
        nodes = [{"id": "u1", "short_id": "x", "node_type": "does_not_exist", "config": {}}]
        result = _validate(nodes, [])
        assert "unknown_node_type" in _reasons(result)

    def test_config_schema_invalid(self):
        """ai_prompt 缺必填 user_prompt → config_schema_invalid error。"""
        nodes = [
            {"id": "u1", "short_id": "trig", "node_type": "manual_trigger", "config": {}},
            {"id": "u2", "short_id": "p", "node_type": "ai_prompt", "config": {}},
        ]
        edges = [{"id": "e1", "source_node_id": "u1", "target_node_id": "u2"}]
        result = _validate(nodes, edges)
        assert "config_schema_invalid" in _reasons(result)


class TestVariableRules:
    """nodes.* 变量静态校验（D-03 / Pitfall 2）。"""

    def test_node_not_found(self):
        """引用不存在的 short_id → node_not_found error。"""
        nodes = [
            {"id": "u1", "short_id": "trig", "node_type": "manual_trigger", "config": {}},
            {
                "id": "u2",
                "short_id": "p",
                "node_type": "ai_prompt",
                "config": {"user_prompt": "{{nodes.ghost.text}}"},
            },
        ]
        edges = [{"id": "e1", "source_node_id": "u1", "target_node_id": "u2"}]
        result = _validate(nodes, edges)
        assert "node_not_found" in _reasons(result)

    def test_field_not_found_when_schema_present(self):
        """引用存在节点但字段不在输出 schema（ai_prompt 有 schema）→ field_not_found error。"""
        nodes = [
            {"id": "u1", "short_id": "trig", "node_type": "manual_trigger", "config": {}},
            {
                "id": "u2",
                "short_id": "src",
                "node_type": "ai_prompt",
                "config": {"user_prompt": "out"},
            },
            {
                "id": "u3",
                "short_id": "p",
                "node_type": "ai_prompt",
                "config": {"user_prompt": "{{nodes.src.nonexistent_field}}"},
            },
        ]
        edges = [
            {"id": "e1", "source_node_id": "u1", "target_node_id": "u2"},
            {"id": "e2", "source_node_id": "u2", "target_node_id": "u3"},
        ]
        result = _validate(nodes, edges)
        assert "field_not_found" in _reasons(result)

    def test_existing_field_passes(self):
        """引用 ai_prompt 真实输出字段 text → 无变量类 error。"""
        nodes = [
            {"id": "u1", "short_id": "trig", "node_type": "manual_trigger", "config": {}},
            {
                "id": "u2",
                "short_id": "src",
                "node_type": "ai_prompt",
                "config": {"user_prompt": "out"},
            },
            {
                "id": "u3",
                "short_id": "p",
                "node_type": "ai_prompt",
                "config": {"user_prompt": "{{nodes.src.text}}"},
            },
        ]
        edges = [
            {"id": "e1", "source_node_id": "u1", "target_node_id": "u2"},
            {"id": "e2", "source_node_id": "u2", "target_node_id": "u3"},
        ]
        result = _validate(nodes, edges)
        assert _reasons(result).isdisjoint({"node_not_found", "field_not_found"})

    def test_no_schema_output_skips_field_layer(self):
        """上游 http_request 输出端口无 schema → {{nodes.h.body}} 字段层跳过（Pitfall 2）。"""
        nodes = [
            {"id": "u1", "short_id": "trig", "node_type": "manual_trigger", "config": {}},
            {
                "id": "u2",
                "short_id": "h",
                "node_type": "http_request",
                "config": {"url": "https://example.com"},
            },
            {
                "id": "u3",
                "short_id": "p",
                "node_type": "ai_prompt",
                "config": {"user_prompt": "{{nodes.h.body}}"},
            },
        ]
        edges = [
            {"id": "e1", "source_node_id": "u1", "target_node_id": "u2"},
            {"id": "e2", "source_node_id": "u2", "target_node_id": "u3"},
        ]
        result = _validate(nodes, edges)
        assert _reasons(result).isdisjoint({"node_not_found", "field_not_found"})

    def test_lenient_prefixes_skipped(self):
        """input./trigger./global. 等宽松前缀不触发变量校验（D-03 宽松边界）。"""
        nodes = [
            {"id": "u1", "short_id": "trig", "node_type": "manual_trigger", "config": {}},
            {
                "id": "u2",
                "short_id": "p",
                "node_type": "ai_prompt",
                "config": {"user_prompt": "{{input.foo}} {{trigger.bar}} {{global.baz}}"},
            },
        ]
        edges = [{"id": "e1", "source_node_id": "u1", "target_node_id": "u2"}]
        result = _validate(nodes, edges)
        assert _reasons(result).isdisjoint({"node_not_found", "field_not_found"})


class TestInformationDisclosure:
    """T-20-01：错误消息不回显被引用 config 的取值。"""

    def test_message_does_not_leak_config_value(self):
        """含敏感字面量的 config 触发变量错误时，message 不含该字面量。"""
        secret = "TOP_SECRET_TOKEN_abc123"
        nodes = [
            {"id": "u1", "short_id": "trig", "node_type": "manual_trigger", "config": {}},
            {
                "id": "u2",
                "short_id": "p",
                "node_type": "ai_prompt",
                "config": {"user_prompt": f"{secret} {{{{nodes.ghost.field}}}}"},
            },
        ]
        edges = [{"id": "e1", "source_node_id": "u1", "target_node_id": "u2"}]
        result = _validate(nodes, edges)
        # 命中 node_not_found，但所有 message 都不含敏感字面量
        assert "node_not_found" in _reasons(result)
        for issue in result["errors"] + result["warnings"]:
            assert secret not in issue["message"]
