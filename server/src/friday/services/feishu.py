"""飞书（Lark）项目集成服务。"""
import json
import time
from dataclasses import dataclass
from typing import Any, Optional
import httpx
from ..config import get_settings
settings = get_settings
@dataclass
class WorkItemInfo:
 """飞书项目工作项信息。"""
 id: int
 name: str
 description: str
 status: str
 project_key: str
 work_item_type: str
 fields: dict[str, Any]
 raw_response: Optional[str] = None # 原始 JSON 响应，用于日志记录
class FeishuClient:
 """飞书 API 客户端，用于项目管理集成。
 支持两种初始化方式：
 1. 显式传入 plugin_id 和 plugin_secret（多项目场景）
 2. 从全局配置读取（向后兼容，单项目场景）
 """
 # 飞书项目 API 基地址
 PROJECT_API_BASE = "https://project.feishu.cn"
 # PROJECT_API_BASE = "https://guanghe.feishu.cn"
 # 飞书开放平台 API 基地址
 OPEN_API_BASE = "https://project.feishu.cn"
 def __init__(
 self,
 plugin_id: Optional[str] = None,
 plugin_secret: Optional[str] = None,
 project_key: Optional[str] = None,
 user_key: Optional[str] = None,
 ):
 """初始化飞书客户端。
 Args:
 plugin_id: 飞书插件 ID（可选，默认从配置读取）
 plugin_secret: 飞书插件 Secret（可选，默认从配置读取）
 project_key: 飞书项目空间 Key（可选）
 user_key: 飞书用户 Key（使用 plugin_token 调用 API 时必填）
 """
 self.plugin_id = plugin_id
 self.plugin_secret = plugin_secret
 self.project_key = project_key
 self.user_key = user_key
 self._plugin_token: Optional[str] = None
 self._token_expires_at: float = 0
 async def get_plugin_token(self) -> str:
 """获取 plugin_access_token（带缓存）。
 Returns:
 有效的 plugin_access_token
 Raises:
 Exception: 获取 token 失败时抛出
 """
 now = time.time
 if self._plugin_token is not None and now < self._token_expires_at:
 return self._plugin_token
 # 请求新 token（获取 token 接口不需要 X-USER-KEY）
 async with httpx.AsyncClient as client:
 response = await client.post(
 f"{self.OPEN_API_BASE}/open_api/authen/plugin_token",
 headers={"Content-Type": "application/json"},
 json={
 "plugin_id": self.plugin_id,
 "plugin_secret": self.plugin_secret,
 },
 )
 data = response.json
 # 飞书 API 响应结构: {"data": {...}, "error": {"code": 0, "msg": "success"}}
 error_code = data.get("error", {}).get("code", -1)
 if error_code != 0:
 raise Exception(f"获取 plugin token 失败: {data}")
 self._plugin_token = data.get("data", {}).get("token")
 if not self._plugin_token:
 raise Exception("获取 plugin token 失败: 返回数据中缺少 token")
 # Token 有效期是相对秒数，提前 5 分钟刷新
 expire_seconds = data.get("data", {}).get("expire_time", 7200)
 self._token_expires_at = now + expire_seconds - 300
 return self._plugin_token
 async def get_work_item(
 self,
 project_key: str,
 work_item_id: int,
 work_item_type: str = "story",
 fields: Optional[list[str]] = None,
 ) -> WorkItemInfo:
 """获取工作项详情。
 使用正确的 POST query 接口：
 POST /open_api/{project_key}/work_item/{work_item_type}/query
 Args:
 project_key: 飞书项目空间 Key
 work_item_id: 工作项 ID（int64）
 work_item_type: 工作项类型（story、task、bug 等）
 fields: 需要返回的字段列表（可选，默认返回全部）
 Returns:
 WorkItemInfo 包含解析后的工作项信息
 Raises:
 Exception: API 调用失败时抛出
 """
 token = await self.get_plugin_token
 # 构建请求体
 body: dict[str, Any] = {
 "work_item_ids": [work_item_id],
 }
 if fields:
 body["fields"] = fields
 async with httpx.AsyncClient as client:
 response = await client.post(
 f"{self.PROJECT_API_BASE}/open_api/{project_key}/work_item/{work_item_type}/query",
 headers={
 "X-PLUGIN-TOKEN": token,
 "Content-Type": "application/json",
 "X-USER-KEY": self.user_key
 or "", # 使用 plugin_token 时必须指定用户身份
 },
 json=body,
 )
 data = response.json
 if data.get("err_code") != 0:
 raise Exception(f"获取工作项失败: {data}")
 items = data.get("data", )
 if not items:
 raise Exception(f"工作项不存在: {work_item_id}")
 item = items[0]
 # 解析字段
 fields_dict = {}
 for field in item.get("fields", ):
 field_key = field.get("field_key")
 field_value = field.get("field_value")
 if field_key:
 fields_dict[field_key] = field_value
 # 获取描述字段
 description = ""
 if "description" in fields_dict:
 description = self._parse_rich_text(fields_dict["description"])
 # 获取状态
 status = ""
 work_item_status = item.get("work_item_status", {})
 if work_item_status:
 status = work_item_status.get("state_key", "")
 return WorkItemInfo(
 id=item.get("id", work_item_id),
 name=item.get("name", ""),
 description=description,
 status=status,
 project_key=project_key,
 work_item_type=work_item_type,
 fields=fields_dict,
 raw_response=json.dumps(data, ensure_ascii=False),
 )
 async def add_comment(
 self,
 project_key: str,
 work_item_id: int,
 work_item_type: str,
 content: str,
 ) -> bool:
 """向工作项添加评论。
 Args:
 project_key: 项目空间 Key
 work_item_id: 工作项 ID
 work_item_type: 工作项类型
 content: 评论内容（Markdown 格式）
 Returns:
 成功返回 True
 """
 token = await self.get_plugin_token
 # 将 Markdown 转换为飞书富文本格式
 rich_content = self._markdown_to_rich_text(content)
 async with httpx.AsyncClient as client:
 response = await client.post(
 f"{self.PROJECT_API_BASE}/open_api/{project_key}/work_item/{work_item_type}/{work_item_id}/comment/create",
 headers={
 "X-PLUGIN-TOKEN": token,
 "Content-Type": "application/json",
 "X-USER-KEY": self.user_key or "",
 },
 json={
 "content": rich_content,
 },
 )
 data = response.json
 return data.get("err_code") == 0
 async def get_comments(
 self,
 project_key: str,
 work_item_id: int,
 work_item_type: str,
 limit: int = 50,
 ) -> list[dict]:
 """获取工作项评论列表。
 Args:
 project_key: 项目空间 Key
 work_item_id: 工作项 ID
 work_item_type: 工作项类型
 limit: 最大返回数量
 Returns:
 评论列表，包含内容和作者信息
 """
 token = await self.get_plugin_token
 async with httpx.AsyncClient as client:
 response = await client.get(
 f"{self.PROJECT_API_BASE}/open_api/{project_key}/work_item/{work_item_type}/{work_item_id}/comment/list",
 headers={
 "X-PLUGIN-TOKEN": token,
 "X-USER-KEY": self.user_key or "",
 },
 params={
 "page_size": limit,
 },
 )
 data = response.json
 if data.get("err_code") != 0:
 return
 comments =
 for item in data.get("data", {}).get("comments", ):
 comments.append(
 {
 "id": item.get("id"),
 "content": self._parse_rich_text(item.get("content", {})),
 "created_at": item.get("created_at"),
 "author": item.get("author", {}).get("name", "Unknown"),
 }
 )
 return comments
 async def transition_status(
 self,
 project_key: str,
 work_item_id: int,
 work_item_type: str,
 target_status_name: str,
 ) -> bool:
 """流转工作项状态。
 Args:
 project_key: 项目空间 Key
 work_item_id: 工作项 ID
 work_item_type: 工作项类型
 target_status_name: 目标状态名称（如"待Review"）
 Returns:
 成功返回 True
 Raises:
 Exception: 无法流转到目标状态时抛出
 """
 token = await self.get_plugin_token
 async with httpx.AsyncClient as client:
 # 获取可用的状态流转
 response = await client.get(
 f"{self.PROJECT_API_BASE}/open_api/{project_key}/work_item/{work_item_type}/{work_item_id}/workflow/transition",
 headers={
 "X-PLUGIN-TOKEN": token,
 "X-USER-KEY": self.user_key or "",
 },
 )
 data = response.json
 if data.get("err_code") != 0:
 raise Exception(f"获取状态流转失败: {data}")
 transitions = data.get("data", {}).get("transitions", )
 # 查找匹配的流转
 target_transition = None
 for t in transitions:
 if (
 target_status_name.lower
 in t.get("to_status", {}).get("name", "").lower
 ):
 target_transition = t
 break
 if not target_transition:
 available = [t.get("to_status", {}).get("name") for t in transitions]
 raise Exception(
 f"无法流转到 '{target_status_name}'。可用状态: {available}"
 )
 # 执行流转
 response = await client.post(
 f"{self.PROJECT_API_BASE}/open_api/{project_key}/work_item/{work_item_type}/{work_item_id}/workflow/transition",
 headers={
 "X-PLUGIN-TOKEN": token,
 "Content-Type": "application/json",
 "X-USER-KEY": self.user_key or "",
 },
 json={
 "transition_id": target_transition["id"],
 },
 )
 return response.json.get("err_code") == 0
 async def test_connection(self, project_key: Optional[str] = None) -> dict:
 """测试飞书连接和项目访问。
 Args:
 project_key: 要测试的项目空间 Key（可选）
 Returns:
 测试结果字典，包含 success、message 等字段
 """
 result = {
 "success": False,
 "message": "",
 "plugin_token_valid": False,
 "project_accessible": False,
 }
 # 测试获取 token
 try:
 await self.get_plugin_token
 result["plugin_token_valid"] = True
 except Exception as e:
 result["message"] = f"获取 plugin_access_token 失败: {e}"
 return result
 # 测试项目访问（如果提供了 project_key）
 test_key = project_key or self.project_key
 if test_key:
 try:
 token = await self.get_plugin_token
 async with httpx.AsyncClient as client:
 # 尝试获取项目下的工作项类型列表
 response = await client.get(
 f"{self.PROJECT_API_BASE}/open_api/{test_key}/work_item/all-types",
 headers={
 "X-PLUGIN-TOKEN": token,
 "X-USER-KEY": self.user_key or "",
 },
 )
 data = response.json
 if data.get("err_code") == 0:
 result["project_accessible"] = True
 result["success"] = True
 result["message"] = "连接测试成功"
 else:
 result["message"] = (
 f"项目访问失败: {data.get('err_msg', '未知错误')}"
 )
 except Exception as e:
 result["message"] = f"项目访问失败: {e}"
 else:
 result["success"] = True
 result["message"] = "Token 验证成功（未测试项目访问）"
 return result
 def _parse_rich_text(self, rich_text: Any) -> str:
 """解析飞书富文本为 Markdown。
 Args:
 rich_text: 飞书 API 返回的富文本对象
 Returns:
 Markdown 格式字符串
 """
 if isinstance(rich_text, str):
 return rich_text
 if not isinstance(rich_text, dict):
 return str(rich_text) if rich_text else ""
 # 处理文档结构
 content = rich_text.get("content", )
 if not content:
 return ""
 result =
 for block in content:
 block_type = block.get("type", "")
 if block_type == "paragraph":
 text = self._parse_paragraph(block)
 result.append(text)
 elif block_type == "heading":
 level = block.get("attrs", {}).get("level", 1)
 text = self._parse_paragraph(block)
 result.append(f"{'#' * level} {text}")
 elif block_type == "bullet_list":
 items = block.get("content", )
 for item in items:
 text = self._parse_paragraph(item)
 result.append(f"- {text}")
 elif block_type == "ordered_list":
 items = block.get("content", )
 for i, item in enumerate(items, 1):
 text = self._parse_paragraph(item)
 result.append(f"{i}. {text}")
 elif block_type == "code_block":
 code = self._parse_paragraph(block)
 lang = block.get("attrs", {}).get("language", "")
 result.append(f"```{lang}\n{code}\n```")
 elif block_type == "image":
 result.append("[Image]")
 return "\n".join(result)
 def _parse_paragraph(self, block: dict) -> str:
 """解析段落内容为文本。"""
 content = block.get("content", )
 texts =
 for node in content:
 if node.get("type") == "text":
 text = node.get("text", "")
 marks = node.get("marks", )
 for mark in marks:
 mark_type = mark.get("type")
 if mark_type == "bold":
 text = f"**{text}**"
 elif mark_type == "italic":
 text = f"*{text}*"
 elif mark_type == "code":
 text = f"`{text}`"
 elif mark_type == "link":
 href = mark.get("attrs", {}).get("href", "")
 text = f"[{text}]({href})"
 texts.append(text)
 return "".join(texts)
 def _markdown_to_rich_text(self, markdown: str) -> dict:
 """将 Markdown 转换为飞书富文本格式。
 这是简化的转换 - 复杂的 Markdown 可能无法完美转换。
 """
 return {
 "content": [
 {
 "type": "paragraph",
 "content": [
 {
 "type": "text",
 "text": markdown,
 }
 ],
 }
 ]
 }
def verify_webhook_token(received_token: str, expected_token: str) -> bool:
 """验证飞书项目 Webhook Token。
 飞书项目 Webhook 使用简单的 Token 比对验证，
 Token 在 header.token 字段中传递。
 Args:
 received_token: 从 Webhook 请求中收到的 token
 expected_token: 预期的 token（配置的值）
 Returns:
 Token 匹配返回 True
 """
 if not expected_token:
 # 未配置 token，跳过验证
 return True
 return received_token == expected_token
# 工厂函数
def create_feishu_client_for_project(project: Any) -> FeishuClient:
 """为指定项目创建飞书客户端。
 从 Project 模型中读取加密的凭证并创建客户端实例。
 Args:
 project: Project 模型实例
 Returns:
 配置好的 FeishuClient 实例
 Raises:
 ValueError: 项目未配置飞书集成时抛出
 """
 from ..services.crypto import decrypt_value
 if not project.feishu_plugin_id or not project.feishu_plugin_secret_encrypted:
 raise ValueError(f"项目 {project.id} 未配置飞书集成")
 # 解密 plugin_secret
 plugin_secret = decrypt_value(project.feishu_plugin_secret_encrypted)
 return FeishuClient(
 plugin_id=project.feishu_plugin_id,
 plugin_secret=plugin_secret,
 project_key=project.feishu_project_key,
 user_key=project.feishu_user_key,
 )
# 向后兼容的全局客户端（deprecated）
_feishu_client: Optional[FeishuClient] = None
def get_feishu_client -> FeishuClient:
 """获取飞书客户端单例。
 注意：此函数已弃用，建议使用 create_feishu_client_for_project 替代。
 保留此函数仅为向后兼容。
 """
 global _feishu_client
 if _feishu_client is None:
 _feishu_client = FeishuClient
 return _feishu_client
