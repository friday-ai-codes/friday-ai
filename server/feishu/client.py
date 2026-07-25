"""飞书（Lark）项目集成服务 - API 客户端。"""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from common.encryption import decrypt_value
from services.feishu_http import feishu_client
from services.feishu_parsing import (
    build_feishu_fields,
    flatten_fields,
    parse_comments,
    rich_text_to_markdown,
    safe_response_json,
    strict_response_json,
)


class _FeishuRateLimited(Exception):
    """飞书项目 API 429 限流标记（仅用于触发退避重试）。"""


@retry(
    retry=retry_if_exception_type(_FeishuRateLimited),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(5),
    reraise=True,
)
async def _apost_feishu_project(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    json: dict[str, Any],
) -> httpx.Response:
    """POST 飞书项目 API；遇 HTTP 429 指数退避重试（限流时等待而非直接失败）。"""
    response = await client.post(url, headers=headers, json=json)
    if response.status_code == 429:
        raise _FeishuRateLimited(f"feishu project api rate limited: {url}")
    return response

# 取数 / 解析以 services/feishu.py + services/feishu_parsing.py 为 canonical。
# 本文件为近重复兼容副本（webhook / workflow 路径在用），三项修复（FIX-01/03/04）
# 经同一共享 helper 落地，保证与 canonical client 解析行为完全一致、消除漂移。


class FeishuAPIError(Exception):
    """飞书 API 调用错误"""

    pass


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
    raw_response: Optional[str] = None  # 原始 JSON 响应，用于日志记录
    # 完整字段对象数组（FIX-04，保留 field_name/type/alias 等元数据，向后兼容默认空）
    feishu_fields: list[dict] = field(default_factory=list)


class FeishuClient:
    """飞书 API 客户端，用于项目管理集成。

    支持两种初始化方式：
    1. 显式传入 plugin_id 和 plugin_secret（多项目场景）
    2. 从全局配置读取（向后兼容，单项目场景）
    """

    # 飞书项目 API 基地址
    PROJECT_API_BASE = "https://project.feishu.cn"

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
        now = time.time()
        if self._plugin_token is not None and now < self._token_expires_at:
            return self._plugin_token

        # 请求新 token（获取 token 接口不需要 X-USER-KEY）
        async with feishu_client() as client:
            response = await client.post(
                f"{self.OPEN_API_BASE}/open_api/authen/plugin_token",
                headers={"Content-Type": "application/json"},
                json={
                    "plugin_id": self.plugin_id,
                    "plugin_secret": self.plugin_secret,
                },
            )
            data = strict_response_json(
                response,
                log_event="feishu_get_plugin_token_parse_failed",
                plugin_id=self.plugin_id,
            )

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
        work_item_type: str,
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
        token = await self.get_plugin_token()

        # 构建请求体
        body: dict[str, Any] = {
            "work_item_ids": [work_item_id],
        }
        if fields:
            body["fields"] = fields

        async with feishu_client() as client:
            response = await _apost_feishu_project(
                client,
                f"{self.PROJECT_API_BASE}/open_api/{project_key}/work_item/{work_item_type}/query",
                headers={
                    "X-PLUGIN-TOKEN": token,
                    "Content-Type": "application/json",
                    "X-USER-KEY": self.user_key or "",  # 使用 plugin_token 时必须指定用户身份
                },
                json=body,
            )
            # 硬取数路径：非 JSON 响应 fail-loud（抛 FeishuResponseError，带脱敏 body 片段）
            data = strict_response_json(
                response,
                log_event="feishu_get_work_item_parse_failed",
                project_key=project_key,
                work_item_id=work_item_id,
            )

            if data.get("err_code") != 0:
                raise Exception(f"获取工作项失败: {data}")

            items = data.get("data", [])
            if not items:
                raise Exception(f"工作项不存在: {work_item_id}")

            item = items[0]

            # 解析字段：完整对象数组（FIX-04）+ 向后兼容拍平 dict 双写
            raw_fields = item.get("fields", [])
            feishu_fields = build_feishu_fields(raw_fields)
            fields_dict = flatten_fields(raw_fields)

            # 获取描述字段
            description = ""
            if "description" in fields_dict:
                description = rich_text_to_markdown(fields_dict["description"])

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
                feishu_fields=feishu_fields,
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
        token = await self.get_plugin_token()

        # 将 Markdown 转换为飞书富文本格式
        rich_content = self._markdown_to_rich_text(content)

        async with feishu_client() as client:
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
            # 防御式解析（CONTEXT：所有 .json() 加防御）：非 JSON/非 dict → 视为失败
            data = safe_response_json(
                response,
                log_event="feishu_add_comment_parse_failed",
                expect=dict,
                project_key=project_key,
                work_item_id=work_item_id,
            )
            return data is not None and data.get("err_code") == 0

    async def get_comments(
        self,
        project_key: str,
        work_item_id: int,
        work_item_type: str,
        limit: int = 50,
    ) -> list[dict]:  # work_item_type 必填（FIX-01，无默认）
        """获取工作项评论列表。

        Args:
            project_key: 项目空间 Key
            work_item_id: 工作项 ID
            work_item_type: 工作项类型
            limit: 最大返回数量

        Returns:
            评论列表，包含内容和作者信息
        """
        token = await self.get_plugin_token()

        async with feishu_client() as client:
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
            # 可选列表端点（PF-11 实测响应形状漂移）：fail-soft 防御解析
            # expect=dict：合法 JSON 但非 dict（如 []/标量）同样软失败，避免后续
            # data.get("err_code") 抛 AttributeError（WR-01）
            data = safe_response_json(
                response,
                log_event="feishu_get_comments_parse_failed",
                expect=dict,
                project_key=project_key,
                work_item_id=work_item_id,
            )
            if data is None:
                return []  # 非 JSON / 非 dict → 已记 warning，降级返回空

            if data.get("err_code") != 0:
                return []

            return parse_comments(data)

    async def update_field(
        self,
        project_key: str,
        work_item_id: int,
        work_item_type: str,
        field_key: str,
        field_value: Any,
    ) -> bool:
        """更新工作项字段

        Args:
            project_key: 项目空间 Key
            work_item_id: 工作项 ID
            work_item_type: 工作项类型 (story/task/bug)
            field_key: 字段 Key (e.g., 'field_000001')
            field_value: 字段值

        Returns:
            成功返回 True，失败抛出异常

        Raises:
            FeishuAPIError: 更新字段失败时抛出
        """
        token = await self.get_plugin_token()

        async with feishu_client() as client:
            response = await client.patch(
                f"{self.PROJECT_API_BASE}/open_api/{project_key}/work_item/{work_item_type}/{work_item_id}",
                headers={
                    "X-PLUGIN-TOKEN": token,
                    "Content-Type": "application/json",
                    "X-USER-KEY": self.user_key or "",
                },
                json={
                    "update_fields": [
                        {
                            "field_key": field_key,
                            "field_value": field_value,
                        }
                    ]
                },
                timeout=30,
            )

            # 写操作硬路径：非 JSON fail-loud（抛 FeishuResponseError，带脱敏 body 片段）
            data = strict_response_json(
                response,
                log_event="feishu_update_field_parse_failed",
                project_key=project_key,
                work_item_id=work_item_id,
            )
            if data.get("err_code") != 0:
                raise FeishuAPIError(f"更新字段失败: {data.get('err_msg', 'Unknown error')}")

            return True

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
        token = await self.get_plugin_token()

        async with feishu_client() as client:
            # 获取可用的状态流转
            response = await client.get(
                f"{self.PROJECT_API_BASE}/open_api/{project_key}/work_item/{work_item_type}/{work_item_id}/workflow/transition",
                headers={
                    "X-PLUGIN-TOKEN": token,
                    "X-USER-KEY": self.user_key or "",
                },
            )
            # 决策硬路径（需读取可用流转）：非 JSON fail-loud（与 get_work_item 一致）
            data = strict_response_json(
                response,
                log_event="feishu_transition_status_parse_failed",
                project_key=project_key,
                work_item_id=work_item_id,
            )

            if data.get("err_code") != 0:
                raise Exception(f"获取状态流转失败: {data}")

            transitions = data.get("data", {}).get("transitions", [])

            # 查找匹配的流转
            target_transition = None
            for t in transitions:
                if target_status_name.lower() in t.get("to_status", {}).get("name", "").lower():
                    target_transition = t
                    break

            if not target_transition:
                available = [t.get("to_status", {}).get("name") for t in transitions]
                raise Exception(f"无法流转到 '{target_status_name}'。可用状态: {available}")

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
            # 执行流转结果：防御式解析，非 JSON/非 dict → 视为失败
            result_data = safe_response_json(
                response,
                log_event="feishu_transition_status_parse_failed",
                expect=dict,
                project_key=project_key,
                work_item_id=work_item_id,
            )
            return result_data is not None and result_data.get("err_code") == 0

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
            await self.get_plugin_token()
            result["plugin_token_valid"] = True
        except Exception as e:
            result["message"] = f"获取 plugin_access_token 失败: {e}"
            return result

        # 测试项目访问（如果提供了 project_key）
        test_key = project_key or self.project_key
        if test_key:
            try:
                token = await self.get_plugin_token()
                async with feishu_client() as client:
                    # 尝试获取项目下的工作项类型列表
                    response = await client.get(
                        f"{self.PROJECT_API_BASE}/open_api/{test_key}/work_item/all-types",
                        headers={
                            "X-PLUGIN-TOKEN": token,
                            "X-USER-KEY": self.user_key or "",
                        },
                    )
                    # 防御式解析（CONTEXT：所有 .json() 加防御）
                    data = safe_response_json(
                        response,
                        log_event="feishu_test_connection_parse_failed",
                        expect=dict,
                        project_key=test_key,
                    )
                    if data is None:
                        result["message"] = "项目访问失败: 响应非预期 JSON"
                    elif data.get("err_code") == 0:
                        result["project_accessible"] = True
                        result["success"] = True
                        result["message"] = "连接测试成功"
                    else:
                        result["message"] = f"项目访问失败: {data.get('err_msg', '未知错误')}"
            except Exception as e:
                result["message"] = f"项目访问失败: {e}"
        else:
            result["success"] = True
            result["message"] = "Token 验证成功（未测试项目访问）"

        return result

    def _parse_rich_text(self, rich_text: Any) -> str:
        """解析飞书富文本为 Markdown（薄封装，委托共享 helper 消除解析漂移）。

        Args:
            rich_text: 飞书 API 返回的富文本对象

        Returns:
            Markdown 格式字符串
        """
        return rich_text_to_markdown(rich_text)

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


def create_feishu_client_for_project(project) -> FeishuClient:
    """为指定项目创建飞书客户端。

    从 Space 模型中读取加密的凭证并创建客户端实例。

    Args:
        project: Space 模型实例

    Returns:
        配置好的 FeishuClient 实例

    Raises:
        ValueError: 项目未配置飞书集成时抛出
    """
    if not project.feishu_plugin_id or not project.feishu_plugin_secret_encrypted:
        raise ValueError(f"项目 {project.id} 未配置飞书集成")

    # 解密 plugin_secret
    try:
        plugin_secret = decrypt_value(project.feishu_plugin_secret_encrypted)
    except Exception as e:
        raise ValueError(f"项目 {project.id} 飞书凭证解密失败，请重新配置 plugin_secret") from e

    return FeishuClient(
        plugin_id=project.feishu_plugin_id,
        plugin_secret=plugin_secret,
        project_key=project.feishu_project_key,
        user_key=project.feishu_user_key,
    )
