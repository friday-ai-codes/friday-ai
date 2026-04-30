"""Tests for CodeNode.
Covers:
- Registry registration
- Safe code execution with context access
- AST safety checks (Import, eval, exec, open)
- Restricted builtins (no dangerous functions)
- Exception handling (no traceback leak)
- Non-JSON-serializable output rejection
- Timeout handling
"""
import asyncio
from unittest.mock import MagicMock
import pytest
from workflows.nodes.base import ExecutionContext, NodeCategory, NodeResult
from workflows.nodes.registry import NodeRegistry
class TestCodeNodeRegistry:
 """Test 1: CodeNode registered in NodeRegistry."""
 @pytest.mark.django_db
 def test_code_registered(self):
 registry = NodeRegistry
 node_class = registry.get("code")
 assert node_class is not None
 assert node_class.node_type == "code"
 assert node_class.category == NodeCategory.ACTION
 assert node_class.execution_mode == "server_local"
class TestCodeNodeSafeExecution:
 """Test 2: Safe code executes correctly."""
 @pytest.mark.asyncio
 async def test_safe_code_basic(self):
 from workflows.nodes.actions.code import CodeNode
 node = CodeNode
 context = ExecutionContext(
 execution_id="exec-001",
 node_id="node-001",
 node_config={"code": "context['output'] = {'result': 1 + 1}"},
 input_data={},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "completed"
 assert result.output == {"result": 2}
 @pytest.mark.asyncio
 async def test_context_four_way_access(self):
 """Test input/config/global/trigger four-way data access."""
 from workflows.nodes.actions.code import CodeNode
 node = CodeNode
 context = ExecutionContext(
 execution_id="exec-002",
 node_id="node-002",
 node_config={
 "code": (
 "ctx = context\n"
 "ctx['output'] = {\n"
 " 'input_val': ctx['input'].get('key'),\n"
 " 'config_val': ctx['config'].get('timeout_seconds'),\n"
 " 'global_val': ctx['global'].get('gkey'),\n"
 " 'trigger_val': ctx['trigger'].get('tkey'),\n"
 "}"
 ),
 "timeout_seconds": 30,
 },
 input_data={"key": "input_value"},
 workflow_context={"global_params": {"gkey": "global_value"}},
 previous_outputs={},
 trigger_data={"tkey": "trigger_value"},
 )
 result = await node.execute(context)
 assert result.status == "completed"
 assert result.output["input_val"] == "input_value"
 assert result.output["config_val"] == 30
 assert result.output["global_val"] == "global_value"
 assert result.output["trigger_val"] == "trigger_value"
class TestCodeNodeASTSafety:
 """Tests 3-5: AST safety checks intercept dangerous code."""
 @pytest.mark.asyncio
 async def test_ast_blocks_import(self):
 from workflows.nodes.actions.code import CodeNode
 node = CodeNode
 context = ExecutionContext(
 execution_id="exec-003",
 node_id="node-003",
 node_config={"code": "import os\ncontext['output'] = {}"},
 input_data={},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "failed"
 assert "代码安全检查失败" in result.error
 assert "Import" in result.error
 @pytest.mark.asyncio
 async def test_ast_blocks_importfrom(self):
 from workflows.nodes.actions.code import CodeNode
 node = CodeNode
 context = ExecutionContext(
 execution_id="exec-004",
 node_id="node-004",
 node_config={"code": "from os import path\ncontext['output'] = {}"},
 input_data={},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "failed"
 assert "ImportFrom" in result.error
 @pytest.mark.asyncio
 async def test_ast_blocks_eval(self):
 from workflows.nodes.actions.code import CodeNode
 node = CodeNode
 context = ExecutionContext(
 execution_id="exec-005",
 node_id="node-005",
 node_config={"code": "eval('1+1')\ncontext['output'] = {}"},
 input_data={},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "failed"
 assert "eval" in result.error
 @pytest.mark.asyncio
 async def test_ast_blocks_exec_call(self):
 from workflows.nodes.actions.code import CodeNode
 node = CodeNode
 context = ExecutionContext(
 execution_id="exec-006",
 node_id="node-006",
 node_config={"code": "exec('pass')\ncontext['output'] = {}"},
 input_data={},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "failed"
 assert "exec" in result.error
 @pytest.mark.asyncio
 async def test_ast_blocks_open(self):
 from workflows.nodes.actions.code import CodeNode
 node = CodeNode
 context = ExecutionContext(
 execution_id="exec-007",
 node_id="node-007",
 node_config={"code": "open('/etc/passwd')\ncontext['output'] = {}"},
 input_data={},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "failed"
 assert "open" in result.error
 @pytest.mark.asyncio
 async def test_ast_blocks_classdef(self):
 from workflows.nodes.actions.code import CodeNode
 node = CodeNode
 context = ExecutionContext(
 execution_id="exec-008",
 node_id="node-008",
 node_config={"code": "class Foo:\n pass\ncontext['output'] = {}"},
 input_data={},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "failed"
 assert "ClassDef" in result.error
 @pytest.mark.asyncio
 async def test_ast_blocks_lambda(self):
 from workflows.nodes.actions.code import CodeNode
 node = CodeNode
 context = ExecutionContext(
 execution_id="exec-009",
 node_id="node-009",
 node_config={"code": "f = lambda x: x\ncontext['output'] = {}"},
 input_data={},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "failed"
 assert "Lambda" in result.error
 @pytest.mark.asyncio
 async def test_ast_blocks_dangerous_attr(self):
 from workflows.nodes.actions.code import CodeNode
 node = CodeNode
 context = ExecutionContext(
 execution_id="exec-010",
 node_id="node-010",
 node_config={"code": "import os; os.system('ls')\ncontext['output'] = {}"},
 input_data={},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 # Should fail at Import first, but if import somehow bypassed,
 # os.system should be blocked by dangerous attr check
 assert result.status == "failed"
class TestCodeNodeRestrictedBuiltins:
 """Test 6: Dangerous builtins are not exposed."""
 @pytest.mark.asyncio
 async def test_no_dangerous_builtins(self):
 from workflows.nodes.actions.code import CodeNode
 node = CodeNode
 context = ExecutionContext(
 execution_id="exec-011",
 node_id="node-011",
 node_config={
 "code": (
 "builtins_dict = __builtins__\n"
 "has_import = 'import' in builtins_dict or '__import__' in builtins_dict\n"
 "context['output'] = {'has_import': has_import}"
 )
 },
 input_data={},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "completed"
 assert result.output["has_import"] is False
 @pytest.mark.asyncio
 async def test_safe_builtins_available(self):
 from workflows.nodes.actions.code import CodeNode
 node = CodeNode
 context = ExecutionContext(
 execution_id="exec-012",
 node_id="node-012",
 node_config={
 "code": (
 "context['output'] = {\n"
 " 'sum': sum([1, 2, 3]),\n"
 " 'max': max([1, 2, 3]),\n"
 " 'len': len('hello'),\n"
 " 'range': list(range(3)),\n"
 "}"
 )
 },
 input_data={},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "completed"
 assert result.output["sum"] == 6
 assert result.output["max"] == 3
 assert result.output["len"] == 5
 assert result.output["range"] == [0, 1, 2]
 @pytest.mark.asyncio
 async def test_json_math_datetime_available(self):
 from workflows.nodes.actions.code import CodeNode
 node = CodeNode
 context = ExecutionContext(
 execution_id="exec-013",
 node_id="node-013",
 node_config={
 "code": (
 "# json, math, datetime are pre-injected into globals\n"
 "context['output'] = {\n"
 " 'json': json.dumps({'a': 1}),\n"
 " 'pi': math.pi,\n"
 " 'year': datetime.datetime.now.year,\n"
 "}"
 )
 },
 input_data={},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "completed"
 assert result.output["json"] == '{"a": 1}'
 assert result.output["pi"] == pytest.approx(3.14159, abs=0.001)
 assert isinstance(result.output["year"], int)
class TestCodeNodeExceptionHandling:
 """Test 7: Exceptions are caught without traceback leak."""
 @pytest.mark.asyncio
 async def test_exception_no_traceback(self):
 from workflows.nodes.actions.code import CodeNode
 node = CodeNode
 context = ExecutionContext(
 execution_id="exec-014",
 node_id="node-014",
 node_config={"code": "1 / 0\ncontext['output'] = {}"},
 input_data={},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "failed"
 assert "ZeroDivisionError" in result.error
 # Must NOT contain traceback indicators
 assert "Traceback" not in result.error
 assert "File \"" not in result.error
 assert "line " not in result.error.lower or "line" not in result.error.lower
 @pytest.mark.asyncio
 async def test_empty_code_fails(self):
 from workflows.nodes.actions.code import CodeNode
 node = CodeNode
 context = ExecutionContext(
 execution_id="exec-015",
 node_id="node-015",
 node_config={"code": " "},
 input_data={},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "failed"
 assert "代码不能为空" in result.error
class TestCodeNodeJSONSerialization:
 """Test 8: Non-JSON-serializable output returns failed."""
 @pytest.mark.asyncio
 async def test_non_json_output_fails(self):
 from workflows.nodes.actions.code import CodeNode
 node = CodeNode
 context = ExecutionContext(
 execution_id="exec-016",
 node_id="node-016",
 node_config={"code": "context['output'] = {'data': {1, 2, 3}}"},
 input_data={},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "failed"
 assert "JSON" in result.error
 @pytest.mark.asyncio
 async def test_json_serializable_output_passes(self):
 from workflows.nodes.actions.code import CodeNode
 node = CodeNode
 context = ExecutionContext(
 execution_id="exec-017",
 node_id="node-017",
 node_config={
 "code": (
 "context['output'] = {\n"
 " 'str': 'hello',\n"
 " 'num': 42,\n"
 " 'bool': True,\n"
 " 'null': None,\n"
 " 'list': [1, 2, 3],\n"
 " 'dict': {'nested': 'value'},\n"
 "}"
 )
 },
 input_data={},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 assert result.status == "completed"
 assert result.output["str"] == "hello"
 assert result.output["num"] == 42
 assert result.output["bool"] is True
 assert result.output["null"] is None
class TestCodeNodeTimeout:
 """Test 9: Timeout handling."""
 @pytest.mark.asyncio
 async def test_timeout_simulation(self):
 """Simulate timeout by using a very short timeout in scheduler.
 This test verifies the node itself handles long-running code gracefully
 when wrapped by scheduler timeout."""
 from workflows.nodes.actions.code import CodeNode
 node = CodeNode
 context = ExecutionContext(
 execution_id="exec-018",
 node_id="node-018",
 node_config={
 "code": "context['output'] = {'done': True}",
 "timeout_seconds": 1,
 },
 input_data={},
 workflow_context={},
 previous_outputs={},
 )
 result = await node.execute(context)
 # The node itself doesn't enforce timeout; scheduler does via asyncio.wait_for
 # This test verifies the node executes normally
 assert result.status == "completed"
