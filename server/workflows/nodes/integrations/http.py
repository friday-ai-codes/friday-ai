"""HTTP request node."""
import httpx
from workflows.nodes.base import (
 BaseNode,
 ExecutionContext,
 NodeCategory,
 NodePort,
 NodeResult,
 PortType,
)
from workflows.nodes.registry import register_node
@register_node
class HTTPRequestNode(BaseNode):
 """HTTP 请求节点
 发送 HTTP 请求到外部 API，可用于调用 n8n webhook 等。
 """
 node_type = "http_request"
 display_name = "HTTP 请求"
 description = "发送 HTTP 请求到外部 API"
 icon = "globe"
 category = NodeCategory.INTEGRATION
 config_schema = {
 "type": "object",
 "properties": {
 "url": {
 "type": "string",
 "title": "URL",
 "description": "请求地址，支持模板变量 {{input.xxx}}",
 },
 "method": {
 "type": "string",
 "title": "方法",
 "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
 "default": "POST",
 },
 "headers": {
 "type": "object",
 "title": "请求头",
 "additionalProperties": {"type": "string"},
 "default": {},
 },
 "body_type": {
 "type": "string",
 "title": "Body 类型",
 "enum": ["none", "json", "form", "raw"],
 "default": "json",
 },
 "body": {
 "type": ["object", "string"],
 "title": "请求体",
 "default": {},
 },
 "timeout": {
 "type": "integer",
 "title": "超时(秒)",
 "default": 30,
 "minimum": 1,
 "maximum": 300,
 },
 "ignore_ssl": {
 "type": "boolean",
 "title": "忽略 SSL 验证",
 "default": False,
 },
 "retry_on_error": {
 "type": "boolean",
 "title": "错误时重试",
 "default": True,
 },
 },
 "required": ["url"],
 }
 inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
 outputs = [
 NodePort(name="default", label="响应", port_type=PortType.OBJECT),
 NodePort(name="error", label="错误", port_type=PortType.OBJECT),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 config = context.node_config
 # 渲染模板变量
 url = context.render_template(config.get("url", ""))
 method = config.get("method", "POST")
 headers = {k: context.render_template(v) for k, v in config.get("headers", {}).items}
 timeout = config.get("timeout", 30)
 # 构建请求体
 body_type = config.get("body_type", "json")
 body = config.get("body", {})
 if isinstance(body, str):
 body = context.render_template(body)
 elif isinstance(body, dict):
 # 对 dict 中的字符串值进行模板渲染
 body = self._render_dict(body, context)
 try:
 async with httpx.AsyncClient(verify=not config.get("ignore_ssl", False)) as client:
 request_kwargs: dict = {
 "method": method,
 "url": url,
 "headers": headers,
 "timeout": timeout,
 }
 if body_type == "json" and body:
 request_kwargs["json"] = body
 elif body_type == "form" and body:
 request_kwargs["data"] = body
 elif body_type == "raw" and body:
 request_kwargs["content"] = body
 response = await client.request(**request_kwargs)
 # 尝试解析 JSON 响应
 try:
 response_data = response.json
 except Exception:
 response_data = response.text
 return NodeResult(
 status="completed",
 output={
 "status_code": response.status_code,
 "headers": dict(response.headers),
 "body": response_data,
 "ok": response.is_success,
 },
 next_handle="default" if response.is_success else "error",
 )
 except httpx.TimeoutException:
 return NodeResult(
 status="failed",
 error=f"请求超时 ({timeout}s)",
 next_handle="error",
 )
 except Exception as e:
 return NodeResult(
 status="failed",
 error=str(e),
 next_handle="error",
 )
 def _render_dict(self, d: dict, context: ExecutionContext) -> dict:
 """递归渲染字典中的模板字符串"""
 result = {}
 for k, v in d.items:
 if isinstance(v, str):
 result[k] = context.render_template(v)
 elif isinstance(v, dict):
 result[k] = self._render_dict(v, context)
 elif isinstance(v, list):
 result[k] = [context.render_template(i) if isinstance(i, str) else i for i in v]
 else:
 result[k] = v
 return result
