"""Variable Extractor Node - Extract variables from JSON data using JSONPath."""
import structlog
from asgiref.sync import sync_to_async
from jsonpath_ng.exceptions import JsonPathParserError
from jsonpath_ng.ext import parse
from workflows.nodes.base import (
 BaseNode,
 ExecutionContext,
 NodeCategory,
 NodePort,
 NodeResult,
 PortType,
)
logger = structlog.get_logger(__name__)
class VariableExtractorNode(BaseNode):
 """变量提取节点
 从上游节点的 JSON 输出中提取指定字段，注册为全局变量。
 支持 JSONPath 语法进行复杂数据提取。
 """
 node_type = "variable_extractor"
 display_name = "变量提取"
 description = "从 JSON 数据中提取字段并注册为全局变量"
 icon = "variable"
 category = NodeCategory.ACTION
 execution_mode = "server_local"
 config_schema = {
 "type": "object",
 "properties": {
 "extractions": {
 "type": "array",
 "title": "提取规则",
 "description": "定义要提取的变量列表",
 "items": {
 "type": "object",
 "properties": {
 "source_path": {
 "type": "string",
 "title": "JSONPath 路径",
 "description": "JSONPath 表达式，如 $.data.title 或 $.fields[?(@.key=='desc')].value",
 },
 "key": {
 "type": "string",
 "title": "变量标识符",
 "description": "在模板中引用时使用的 key，如 {{ global.key }}",
 "pattern": "^[a-zA-Z_][a-zA-Z0-9_]*$",
 },
 "name": {
 "type": "string",
 "title": "显示名称",
 "description": "变量的中文名称，用于界面展示",
 },
 "desc": {
 "type": "string",
 "title": "描述",
 "description": "变量的详细描述（选填）",
 },
 "required": {
 "type": "boolean",
 "title": "是否必填",
 "description": "如果为 true，提取失败时节点将报错",
 "default": False,
 },
 },
 "required": ["source_path", "key", "name"],
 },
 },
 },
 "required": ["extractions"],
 }
 inputs = [
 NodePort(
 name="data",
 label="数据输入",
 port_type=PortType.OBJECT,
 required=True,
 description="要提取变量的 JSON 数据",
 )
 ]
 outputs = [
 NodePort(
 name="variables",
 label="提取结果",
 port_type=PortType.OBJECT,
 description="提取的变量摘要",
 )
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 """执行变量提取"""
 extractions = context.get_config("extractions", )
 if not extractions:
 return NodeResult(
 status="completed",
 output={"variables": {}, "message": "无提取规则"},
 )
 # 获取输入数据
 input_data = context.input_data
 if not input_data:
 # 尝试从上游节点获取
 for node_id, output in context.previous_outputs.items:
 if output:
 input_data = output
 break
 if not input_data:
 return NodeResult(
 status="failed",
 error="无输入数据",
 )
 extracted_variables: dict[str, dict] = {}
 errors: list[str] =
 for extraction in extractions:
 source_path = extraction.get("source_path", "")
 key = extraction.get("key", "")
 name = extraction.get("name", "")
 desc = extraction.get("desc", "")
 required = extraction.get("required", False)
 if not source_path or not key or not name:
 errors.append(f"提取规则配置不完整: {extraction}")
 continue
 try:
 # 解析 JSONPath
 jsonpath_expr = parse(source_path)
 matches = jsonpath_expr.find(input_data)
 if matches:
 # 取第一个匹配结果
 value = matches[0].value
 # 注册全局变量（使用 sync_to_async 因为底层会调用 save）
 await sync_to_async(context.set_global_variable)(
 key=key,
 name=name,
 value=value,
 desc=desc,
 required=required,
 )
 extracted_variables[key] = value
 logger.info(
 "variable_extracted",
 key=key,
 name=name,
 path=source_path,
 value_type=type(value).__name__,
 )
 else:
 # 未匹配到数据
 if required:
 errors.append(
 f"必填变量 '{name}' ({key}) 未找到匹配数据，路径: {source_path}"
 )
 else:
 logger.warning(
 "variable_not_found",
 key=key,
 name=name,
 path=source_path,
 )
 except JsonPathParserError as e:
 errors.append(f"JSONPath 语法错误 ({source_path}): {e}")
 except Exception as e:
 errors.append(f"提取变量 '{name}' 时出错: {e}")
 if errors:
 error_message = "; ".join(errors)
 logger.error("variable_extraction_failed", errors=errors)
 return NodeResult(
 status="failed",
 error=error_message,
 output=extracted_variables,
 )
 return NodeResult(
 status="completed",
 output=extracted_variables,
 )
