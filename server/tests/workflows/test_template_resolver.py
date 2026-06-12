"""模板变量解析核心专项单测（Phase 17 / VAR-02 + VAR-04）。

纯函数零 DB：所有用例用 plain dict 构造 ResolutionSources，
jsonpath_resolver 用简单 lambda stub，不依赖 Django ORM 与 fixture。

覆盖场景（与 17-01-PLAN.md Task 1 behavior 一一对应）：
- 节点 ID 不存在（含大小写近似提示、available 过滤 UUID 键）
- 字段不存在（节点存在）
- 嵌套 dict / list 数字索引路径
- 未知前缀
- 段数不足（missing_field_path，不得误报为未知前缀）
- UUID 与 short_id 双键兼容
- get_template_value 单变量保类型 + [n]/[-n] 索引后缀
- render 多变量字符串渲染
- 非 nodes 前缀字段缺失现状锁定（空串，不报错）
"""

import pytest

from workflows.engine.template_resolver import (
    ResolutionSources,
    TemplateResolutionError,
    get_template_value,
    render_template,
    resolve_path,
)

UUID_KEY = "550e8400-e29b-41d4-a716-446655440000"

NODE_OUTPUT = {
    "x": "vx",
    "count": 42,
    "data": {"name": "alice", "secret-value": "should-not-leak"},
    "items": [{"name": "first"}, {"name": "second"}],
    "tags": ["t0", "t1", "t2"],
}


def _jp_stub(expr):
    """单测中不应触达 JSONPath 分支的 stub。"""
    raise AssertionError(f"不应调用 jsonpath_resolver: {expr}")


def make_sources(**overrides) -> ResolutionSources:
    defaults = dict(
        previous_outputs={"aB1": NODE_OUTPUT, UUID_KEY: NODE_OUTPUT},
        input_data={"k": "iv", "project": {"id": "p1"}},
        workflow_context={"ctx_key": "cv"},
        node_config={"cfg_key": "cfgv"},
        trigger_data={"payload": {"id": "t1"}},
        global_values={"g": "gv"},
    )
    defaults.update(overrides)
    return ResolutionSources(**defaults)


# ---------------------------------------------------------------------------
# 节点 ID 不存在（node_not_found）
# ---------------------------------------------------------------------------


class TestNodeNotFound:
    def test_unknown_node_raises(self):
        sources = make_sources()
        with pytest.raises(TemplateResolutionError) as exc_info:
            render_template("{{nodes.zzz.field}}", sources, _jp_stub)
        err = exc_info.value
        assert err.reason == "node_not_found"
        assert err.reference == "nodes.zzz.field"
        assert err.template == "{{nodes.zzz.field}}"
        assert "zzz" in str(err)
        assert "不存在" in str(err)

    def test_error_is_value_error_with_attrs(self):
        sources = make_sources()
        with pytest.raises(ValueError) as exc_info:
            render_template("{{nodes.zzz.field}}", sources, _jp_stub)
        err = exc_info.value
        assert isinstance(err, TemplateResolutionError)
        assert hasattr(err, "template")
        assert hasattr(err, "reference")
        assert hasattr(err, "reason")
        assert hasattr(err, "available")

    def test_case_insensitive_hint(self):
        sources = make_sources(previous_outputs={"aB1": NODE_OUTPUT})
        with pytest.raises(TemplateResolutionError) as exc_info:
            render_template("{{nodes.ab1.x}}", sources, _jp_stub)
        msg = str(exc_info.value)
        assert "你是否想使用 'aB1'" in msg

    def test_available_filters_uuid_keys(self):
        sources = make_sources(previous_outputs={"aB1": NODE_OUTPUT, UUID_KEY: NODE_OUTPUT})
        with pytest.raises(TemplateResolutionError) as exc_info:
            render_template("{{nodes.zzz.x}}", sources, _jp_stub)
        err = exc_info.value
        assert err.available == ["aB1"]
        assert UUID_KEY not in err.available

    def test_available_falls_back_to_all_keys_when_only_uuid(self):
        sources = make_sources(previous_outputs={UUID_KEY: NODE_OUTPUT})
        with pytest.raises(TemplateResolutionError) as exc_info:
            render_template("{{nodes.zzz.x}}", sources, _jp_stub)
        assert exc_info.value.available == [UUID_KEY]

    def test_available_contains_only_keys_never_values(self):
        sources = make_sources(previous_outputs={"aB1": {"x": "secret-output-value"}})
        with pytest.raises(TemplateResolutionError) as exc_info:
            render_template("{{nodes.zzz.x}}", sources, _jp_stub)
        err = exc_info.value
        assert err.available == ["aB1"]
        assert all("secret-output-value" not in item for item in err.available)
        assert "secret-output-value" not in str(err)


# ---------------------------------------------------------------------------
# 字段不存在（field_not_found）
# ---------------------------------------------------------------------------


class TestFieldNotFound:
    def test_missing_top_level_field(self):
        sources = make_sources()
        with pytest.raises(TemplateResolutionError) as exc_info:
            render_template("{{nodes.aB1.nope}}", sources, _jp_stub)
        err = exc_info.value
        assert err.reason == "field_not_found"
        msg = str(err)
        assert "aB1" in msg
        assert "nope" in msg
        assert "不存在字段" in msg

    def test_available_is_top_level_output_keys(self):
        sources = make_sources()
        with pytest.raises(TemplateResolutionError) as exc_info:
            render_template("{{nodes.aB1.nope}}", sources, _jp_stub)
        assert sorted(exc_info.value.available) == sorted(NODE_OUTPUT.keys())


# ---------------------------------------------------------------------------
# 嵌套路径（VAR-04）
# ---------------------------------------------------------------------------


class TestNestedPath:
    def test_nested_dict_path(self):
        sources = make_sources()
        assert render_template("{{nodes.aB1.data.name}}", sources, _jp_stub) == "alice"

    def test_list_numeric_index_path(self):
        sources = make_sources()
        assert render_template("{{nodes.aB1.items.0.name}}", sources, _jp_stub) == "first"
        assert render_template("{{nodes.aB1.items.1.name}}", sources, _jp_stub) == "second"

    def test_nested_missing_key_reports_full_path(self):
        sources = make_sources()
        with pytest.raises(TemplateResolutionError) as exc_info:
            render_template("{{nodes.aB1.data.bad}}", sources, _jp_stub)
        err = exc_info.value
        assert err.reason == "field_not_found"
        assert err.reference == "nodes.aB1.data.bad"
        assert "data.bad" in str(err)

    def test_mid_path_non_container_breaks(self):
        # x 是字符串，继续下钻应报 field_not_found
        sources = make_sources()
        with pytest.raises(TemplateResolutionError) as exc_info:
            render_template("{{nodes.aB1.x.deeper}}", sources, _jp_stub)
        assert exc_info.value.reason == "field_not_found"

    def test_list_index_out_of_range(self):
        sources = make_sources()
        with pytest.raises(TemplateResolutionError) as exc_info:
            render_template("{{nodes.aB1.items.9.name}}", sources, _jp_stub)
        assert exc_info.value.reason == "field_not_found"

    def test_list_non_numeric_segment(self):
        sources = make_sources()
        with pytest.raises(TemplateResolutionError) as exc_info:
            render_template("{{nodes.aB1.items.name}}", sources, _jp_stub)
        assert exc_info.value.reason == "field_not_found"


# ---------------------------------------------------------------------------
# 未知前缀（unknown_prefix）
# ---------------------------------------------------------------------------


class TestUnknownPrefix:
    def test_unknown_prefix_raises(self):
        sources = make_sources()
        with pytest.raises(TemplateResolutionError) as exc_info:
            render_template("{{foo.bar}}", sources, _jp_stub)
        err = exc_info.value
        assert err.reason == "unknown_prefix"
        assert err.available == [
            "input",
            "context",
            "config",
            "nodes",
            "global",
            "trigger",
            "$",
        ]

    def test_unknown_prefix_not_kept_as_literal(self):
        sources = make_sources()
        with pytest.raises(TemplateResolutionError):
            render_template("prefix {{foo.bar}} suffix", sources, _jp_stub)

    def test_unknown_prefix_in_value_mode(self):
        sources = make_sources()
        with pytest.raises(TemplateResolutionError) as exc_info:
            get_template_value("{{foo.bar}}", sources, _jp_stub)
        assert exc_info.value.reason == "unknown_prefix"


# ---------------------------------------------------------------------------
# 段数不足（missing_field_path，Pitfall 3）
# ---------------------------------------------------------------------------


class TestMissingFieldPath:
    def test_two_segments_only(self):
        sources = make_sources()
        with pytest.raises(TemplateResolutionError) as exc_info:
            render_template("{{nodes.aB1}}", sources, _jp_stub)
        err = exc_info.value
        assert err.reason == "missing_field_path"
        assert "缺少字段路径" in str(err)
        assert "未知" not in str(err)

    def test_bare_nodes_prefix(self):
        sources = make_sources()
        with pytest.raises(TemplateResolutionError) as exc_info:
            render_template("{{nodes}}", sources, _jp_stub)
        assert exc_info.value.reason == "missing_field_path"

    def test_value_mode_same_semantics(self):
        sources = make_sources()
        with pytest.raises(TemplateResolutionError) as exc_info:
            get_template_value("{{nodes.aB1}}", sources, _jp_stub)
        assert exc_info.value.reason == "missing_field_path"


# ---------------------------------------------------------------------------
# UUID 与 short_id 双键兼容
# ---------------------------------------------------------------------------


class TestDualKeyCompat:
    def test_short_id_reference_resolves(self):
        sources = make_sources()
        assert render_template("{{nodes.aB1.x}}", sources, _jp_stub) == "vx"

    def test_uuid_reference_resolves(self):
        sources = make_sources()
        assert render_template(f"{{{{nodes.{UUID_KEY}.x}}}}", sources, _jp_stub) == "vx"


# ---------------------------------------------------------------------------
# get_template_value 保类型 + 索引后缀
# ---------------------------------------------------------------------------


class TestTypePreservation:
    def test_single_variable_preserves_int(self):
        sources = make_sources()
        value = get_template_value("{{nodes.aB1.count}}", sources, _jp_stub)
        assert value == 42
        assert isinstance(value, int)

    def test_single_variable_preserves_dict(self):
        sources = make_sources()
        value = get_template_value("{{nodes.aB1.data}}", sources, _jp_stub)
        assert value == NODE_OUTPUT["data"]

    def test_array_index_suffix(self):
        sources = make_sources()
        assert get_template_value("{{nodes.aB1.tags[0]}}", sources, _jp_stub) == "t0"
        assert get_template_value("{{nodes.aB1.tags[-1]}}", sources, _jp_stub) == "t2"

    def test_array_index_out_of_range_returns_empty(self):
        # 索引后缀越界维持现状：返回空串而非报错
        sources = make_sources()
        assert get_template_value("{{nodes.aB1.tags[9]}}", sources, _jp_stub) == ""


# ---------------------------------------------------------------------------
# render 多变量渲染
# ---------------------------------------------------------------------------


class TestMultiVariableRender:
    def test_multi_variable_string(self):
        sources = make_sources()
        result = render_template("a={{nodes.aB1.x}}, b={{input.k}}", sources, _jp_stub)
        assert result == "a=vx, b=iv"

    def test_value_mode_falls_back_to_render_for_mixed_content(self):
        sources = make_sources()
        result = get_template_value("prefix_{{nodes.aB1.x}}_suffix", sources, _jp_stub)
        assert result == "prefix_vx_suffix"


# ---------------------------------------------------------------------------
# 非 nodes 前缀现状锁定（OQ#1 定界）
# ---------------------------------------------------------------------------


class TestNonNodesPrefixStatusQuo:
    @pytest.mark.parametrize(
        "template",
        [
            "{{input.missing}}",
            "{{trigger.payload.missing}}",
            "{{global.missing}}",
            "{{context.missing}}",
            "{{config.missing}}",
        ],
    )
    def test_render_returns_empty_string(self, template):
        sources = make_sources()
        assert render_template(template, sources, _jp_stub) == ""

    @pytest.mark.parametrize(
        "template",
        [
            "{{input.missing}}",
            "{{trigger.payload.missing}}",
            "{{global.missing}}",
            "{{context.missing}}",
            "{{config.missing}}",
        ],
    )
    def test_value_mode_returns_empty_string(self, template):
        sources = make_sources()
        assert get_template_value(template, sources, _jp_stub) == ""

    def test_existing_non_nodes_prefixes_still_resolve(self):
        sources = make_sources()
        assert render_template("{{input.project.id}}", sources, _jp_stub) == "p1"
        assert render_template("{{trigger.payload.id}}", sources, _jp_stub) == "t1"
        assert render_template("{{global.g}}", sources, _jp_stub) == "gv"
        assert render_template("{{context.ctx_key}}", sources, _jp_stub) == "cv"
        assert render_template("{{config.cfg_key}}", sources, _jp_stub) == "cfgv"


# ---------------------------------------------------------------------------
# resolve_path 直接调用（核心函数级）
# ---------------------------------------------------------------------------


class TestResolvePath:
    def test_nodes_nested_value(self):
        sources = make_sources()
        assert resolve_path("nodes.aB1.data.name", sources) == "alice"

    def test_non_nodes_missing_returns_none(self):
        sources = make_sources()
        assert resolve_path("input.missing", sources) is None

    def test_unknown_prefix_raises(self):
        sources = make_sources()
        with pytest.raises(TemplateResolutionError) as exc_info:
            resolve_path("foo.bar", sources)
        assert exc_info.value.reason == "unknown_prefix"


# ---------------------------------------------------------------------------
# ExecutionContext 集成层（薄委托后行为 + JSONPath 现状锁定，零 DB）
# ---------------------------------------------------------------------------


class TestExecutionContextIntegration:
    """两 API 经 ExecutionContext 委托后语义一致；JSONPath 现状锁定（Pitfall 6）。"""

    def _make_context(self):
        from workflows.nodes.base import ExecutionContext

        return ExecutionContext(
            execution_id="exec-1",
            node_id="node-1",
            node_config={"cfg_key": "cfgv"},
            input_data={"k": "iv"},
            workflow_context={},
            previous_outputs={"aB1": dict(NODE_OUTPUT)},
        )

    def test_render_template_bad_reference_raises(self):
        ctx = self._make_context()
        with pytest.raises(TemplateResolutionError) as exc_info:
            ctx.render_template("{{nodes.zzz.output}}")
        assert exc_info.value.reason == "node_not_found"

    def test_render_template_unknown_prefix_raises(self):
        ctx = self._make_context()
        with pytest.raises(TemplateResolutionError) as exc_info:
            ctx.render_template("{{foo.bar}}")
        assert exc_info.value.reason == "unknown_prefix"

    def test_get_template_value_preserves_type(self):
        ctx = self._make_context()
        value = ctx.get_template_value("{{nodes.aB1.count}}")
        assert value == 42
        assert isinstance(value, int)

    def test_jsonpath_still_resolves(self):
        # JSONPath 现状锁定：{{$nodes.x.items[*].name}} 正常解析
        ctx = self._make_context()
        result = ctx.render_template("{{$nodes.aB1.items[*].name}}")
        assert result == "first\nsecond"

    def test_jsonpath_zero_match_keeps_literal(self):
        # Pitfall 6 characterization：JSONPath 零匹配时 render 保留 {{...}} 字面量
        ctx = self._make_context()
        template = "{{$nodes.aB1.missing[*].name}}"
        assert ctx.render_template(template) == template

    def test_get_previous_output_nested(self):
        ctx = self._make_context()
        assert ctx.get_previous_output("aB1", "data.name") == "alice"
        assert ctx.get_previous_output("aB1", "items.0.name") == "first"

    def test_get_previous_output_missing_returns_default(self):
        # 与模板解析路径不同：直接调用方保留 default 语义，不抛异常
        ctx = self._make_context()
        assert ctx.get_previous_output("aB1", "data.bad", "DF") == "DF"
        assert ctx.get_previous_output("zzz", "x", "DF") == "DF"
        assert ctx.get_previous_output("aB1", "x.deeper", "DF") == "DF"

    def test_global_params_resolve_from_model_field_after_db_reload(self):
        """WR-01 回归：set_global_param 只持久化 WorkflowExecution.global_params
        模型字段，不写 context 镜像；execution 从 DB 重载（resume/approve 等路径）
        后镜像为空，{{global.x}} 仍必须能从模型字段解析（legacy 语义）。"""
        from workflows.models import WorkflowExecution
        from workflows.nodes.base import ExecutionContext

        we = WorkflowExecution(global_params={"x": "persisted-value"}, context={})
        ctx = ExecutionContext(
            execution_id="exec-1",
            node_id="node-1",
            node_config={},
            input_data={},
            workflow_context=we.context,
            previous_outputs={},
            workflow_execution=we,
        )
        assert ctx.render_template("val={{global.x}}") == "val=persisted-value"

    def test_global_params_context_mirror_overrides_model_field(self):
        """同进程内 context 镜像有最新值时优先于模型字段（覆盖语义不回退）。"""
        from workflows.models import WorkflowExecution
        from workflows.nodes.base import ExecutionContext

        we = WorkflowExecution(global_params={"x": "stale"}, context={})
        ctx = ExecutionContext(
            execution_id="exec-1",
            node_id="node-1",
            node_config={},
            input_data={},
            workflow_context={"global_params": {"x": "fresh"}},
            previous_outputs={},
            workflow_execution=we,
        )
        assert ctx.render_template("val={{global.x}}") == "val=fresh"
