"""Context retrieval node for RAG-based code search."""
import structlog
from asgiref.sync import sync_to_async
from services.embedding import EmbeddingService
from services.qdrant_service import QdrantService
from workflows.nodes.base import (
 BaseNode,
 ExecutionContext,
 NodeCategory,
 NodePort,
 NodeResult,
 PortType,
)
from workflows.nodes.registry import register_node
logger = structlog.get_logger(__name__)
@register_node
class ContextRetrievalNode(BaseNode):
 """召回上下文节点
 根据查询文本从代码库向量索引中检索相关代码片段，
 用于为后续 AI 编码节点提供上下文。
 """
 node_type = "context_retrieval"
 display_name = "召回上下文"
 description = "从代码库中检索与需求相关的代码片段，为 AI 编码提供上下文"
 icon = "search-code"
 category = NodeCategory.AI
 config_schema = {
 "type": "object",
 "properties": {
 "query": {
 "type": "string",
 "title": "检索查询",
 "description": "用于检索的文本，支持模板变量如 {{global.requirement_text}}",
 },
 "repository_id": {
 "type": "string",
 "title": "仓库 ID",
 "description": "代码仓库 ID，支持模板变量",
 },
 "top_k": {
 "type": "integer",
 "title": "返回数量",
 "description": "返回的代码片段数量",
 "default": 10,
 "minimum": 1,
 "maximum": 50,
 },
 "score_threshold": {
 "type": "number",
 "title": "相似度阈值",
 "description": "最低相似度分数，低于此分数的结果将被过滤",
 "default": 0.5,
 "minimum": 0,
 "maximum": 1,
 },
 "language_filter": {
 "type": "string",
 "title": "语言过滤",
 "description": "可选，按编程语言过滤（如 python, typescript）",
 "default": "",
 },
 "include_content": {
 "type": "boolean",
 "title": "包含代码内容",
 "description": "是否在输出中包含完整代码内容",
 "default": True,
 },
 "format_as_markdown": {
 "type": "boolean",
 "title": "格式化为 Markdown",
 "description": "是否将结果格式化为 Markdown 代码块",
 "default": True,
 },
 },
 "required": ["query", "repository_id"],
 }
 inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT, required=False)]
 outputs = [
 NodePort(name="default", label="检索结果", port_type=PortType.OBJECT),
 NodePort(name="error", label="失败", port_type=PortType.OBJECT),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 config = context.node_config
 # 渲染模板变量
 query = context.render_template(config.get("query", ""))
 repository_id = context.render_template(config.get("repository_id", ""))
 top_k = config.get("top_k", 10)
 score_threshold = config.get("score_threshold", 0.5)
 language_filter = context.render_template(config.get("language_filter", ""))
 include_content = config.get("include_content", True)
 format_as_markdown = config.get("format_as_markdown", True)
 # 验证必填参数
 if not query:
 return NodeResult(
 status="failed",
 error="检索查询不能为空",
 next_handle="error",
 )
 if not repository_id:
 return NodeResult(
 status="failed",
 error="仓库 ID 不能为空",
 next_handle="error",
 )
 logger.info(
 "context_retrieval_start",
 query=query[:100],
 repository_id=repository_id,
 top_k=top_k,
 )
 try:
 # 生成查询向量
 query_embedding = await EmbeddingService.generate_embedding(query)
 if not query_embedding:
 return NodeResult(
 status="failed",
 error="生成查询向量失败，请检查 Embedding 服务配置",
 next_handle="error",
 )
 # 构建过滤条件
 filters = {}
 if language_filter:
 filters["language"] = language_filter
 # 执行向量检索（同步方法需要包装）
 search_results = await sync_to_async(QdrantService.search, thread_sensitive=True)(
 repository_id,
 query_embedding,
 top_k=top_k,
 filters=filters if filters else None,
 )
 if not search_results:
 logger.info("context_retrieval_no_results", repository_id=repository_id)
 return NodeResult(
 status="completed",
 output={
 "contexts":,
 "formatted_context": "",
 "total": 0,
 "query": query,
 },
 next_handle="default",
 )
 # 过滤低分结果
 filtered_results = [r for r in search_results if r["score"] >= score_threshold]
 # 构建输出
 contexts =
 for r in filtered_results:
 payload = r["payload"]
 ctx = {
 "file_path": payload.get("file_path"),
 "score": r["score"],
 "language": payload.get("language"),
 "start_line": payload.get("start_line"),
 "end_line": payload.get("end_line"),
 "context_header": payload.get("context_header", ""),
 }
 if include_content:
 ctx["content"] = payload.get("content", "")
 contexts.append(ctx)
 # 格式化为 Markdown
 formatted_context = ""
 if format_as_markdown and contexts:
 formatted_context = self._format_as_markdown(contexts)
 logger.info(
 "context_retrieval_completed",
 total=len(contexts),
 repository_id=repository_id,
 )
 return NodeResult(
 status="completed",
 output={
 "contexts": contexts,
 "formatted_context": formatted_context,
 "total": len(contexts),
 "query": query,
 },
 next_handle="default",
 )
 except Exception as e:
 logger.error("context_retrieval_failed", error=str(e))
 return NodeResult(
 status="failed",
 error=f"上下文召回失败: {e!s}",
 next_handle="error",
 )
 def _format_as_markdown(self, contexts: list[dict]) -> str:
 """将检索结果格式化为 Markdown 代码块"""
 parts = ["## 相关代码上下文\n"]
 for i, ctx in enumerate(contexts, 1):
 file_path = ctx.get("file_path", "unknown")
 start_line = ctx.get("start_line", 0)
 end_line = ctx.get("end_line", 0)
 language = ctx.get("language", "")
 content = ctx.get("content", "")
 score = ctx.get("score", 0)
 context_header = ctx.get("context_header", "")
 # 标题行
 line_info = f"L{start_line}-{end_line}" if start_line and end_line else ""
 header = f"### {i}. {file_path}"
 if line_info:
 header += f" ({line_info})"
 header += f" [相似度: {score:.2f}]"
 parts.append(header)
 # 上下文头（如函数/类名）
 if context_header:
 parts.append(f"> {context_header}")
 # 代码块
 if content:
 parts.append(f"```{language}")
 parts.append(content.strip)
 parts.append("```")
 parts.append("") # 空行分隔
 return "\n".join(parts)
