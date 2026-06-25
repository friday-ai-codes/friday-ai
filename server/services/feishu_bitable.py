"""飞书 Bitable（多维表格）开放平台 client 骨架（REL-02）。

``BitableClient`` **复用既有 ``FeishuDocClient`` 的开放平台 ``tenant_access_token``
模式**（``open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal``，
app_id/app_secret，2h 缓存自动刷新）——为真正 DRY，内部组合一个 ``FeishuDocClient``
实例并委托其 ``get_tenant_access_token``，token 端点保证是**开放平台 internal 端点**
（开放平台域，**非**项目 plugin token ``project.feishu.cn``）。

凭证来源（``create_bitable_client_for_project``）镜像
``create_feishu_doc_client_for_project``——项目级 ``feishu_app_id`` /
``feishu_app_secret_encrypted`` 优先、回退系统级 SystemSetting 加密凭证；**绝不**取
``services/feishu.py`` 的项目 plugin token（``project.feishu.cn``）。这是 REL-02 的
解耦核心：Bitable 走开放平台 token 体系，与项目 plugin token 来源完全独立。

本 plan 是**骨架**：``list_records`` 等方法可调通 token 获取与开放平台 bitable 端点
形状，返回原始 ``data``（含 ``items``/``has_more``/``page_token``），**不解析列结构**
——真实多维表格列结构解析归 v2 REL-03（待开放平台凭证 + 列样例）。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from services.feishu_doc import FeishuDocClient

if TYPE_CHECKING:
    from projects.models import Space

logger = structlog.get_logger(__name__)

__all__ = [
    "BitableClient",
    "BitableAPIError",
    "RateLimitError",
    "create_bitable_client_for_project",
]


class BitableAPIError(Exception):
    """飞书 Bitable 开放平台 API 错误。"""

    pass


class RateLimitError(BitableAPIError):
    """触发频控，应退避重试（沿用 feishu_doc.py 错误码分类风格）。"""

    pass


# 飞书开放平台频控错误码（沿用 feishu_doc.py 风格）
_RATE_LIMIT_CODES: frozenset[int] = frozenset({99991400})


class BitableClient:
    """飞书 Bitable 开放平台 client（骨架，REL-02）。

    复用 ``FeishuDocClient`` 的开放平台 ``tenant_access_token`` 取 token（开放平台域，
    **非** ``project.feishu.cn`` plugin token）。骨架方法 ``list_records`` 打通 token +
    开放平台 bitable 端点形状，返回原始 ``data`` 不解析列（真实列解析留 adapter / REL-03）。
    """

    OPEN_API_BASE = FeishuDocClient.OPEN_API_BASE

    def __init__(self, app_id: str, app_secret: str):
        """初始化 Bitable client。

        Args:
            app_id: 飞书自建应用 App ID（开放平台凭证，独立于项目 plugin token）。
            app_secret: 飞书自建应用 App Secret。
        """
        self.app_id = app_id
        self.app_secret = app_secret
        # 复用 FeishuDocClient 的开放平台 token 实现（2h 缓存 + internal 端点），DRY。
        self._doc_client = FeishuDocClient(app_id=app_id, app_secret=app_secret)

    async def get_tenant_access_token(self) -> str:
        """取开放平台 ``tenant_access_token``（委托 FeishuDocClient，2h 缓存）。

        token 端点为 ``{OPEN_API_BASE}/auth/v3/tenant_access_token/internal``
        （开放平台 internal 端点，**非**项目 plugin token）。
        """
        return await self._doc_client.get_tenant_access_token()

    async def list_records(
        self,
        app_token: str,
        table_id: str,
        *,
        page_token: str | None = None,
        page_size: int = 100,
        sort: list[str] | None = None,
    ) -> dict[str, Any]:
        """列出 Bitable 表记录（骨架：打通 token + 开放平台端点形状）。

        GET ``{OPEN_API_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records``
        （DOMAIN §4），Bearer 鉴权 + 分页 params；成功返回原始 ``data``（含
        ``items``/``has_more``/``page_token`` 原始形状，**不解析列结构**）。

        Args:
            app_token: Bitable app token。
            table_id: 数据表 id。
            page_token: 分页游标（可选）。
            page_size: 单页大小（默认 100）。
            sort: 排序参数（开放平台格式 ``["字段名 DESC", ...]``）。非空时开放平台
                视为对全表过滤、忽略 view_id（本 client 不传 view_id，无影响）。

        Returns:
            开放平台返回的原始 ``data`` 字典。

        Raises:
            BitableAPIError: API 调用失败。
            RateLimitError: 触发频控（可退避重试）。
        """
        token = await self.get_tenant_access_token()

        params: dict[str, Any] = {"page_size": page_size}
        if page_token:
            params["page_token"] = page_token
        if sort:
            # 开放平台 sort 为 JSON 字符串数组（httpx 自动 URL 编码）。
            params["sort"] = json.dumps(sort, ensure_ascii=False)

        # 大表首页/复杂字段可能 >5s，显式给 30s（对齐 FeishuDocClient.get_document_content），
        # 否则 httpx 默认 5s ReadTimeout 会被上层吞成「抓取信息源时出错」泛化提示。
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.OPEN_API_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
            data = response.json()

        if data.get("code") != 0:
            error_code = data.get("code", 0)
            error_msg = data.get("msg", "Unknown error")
            if error_code in _RATE_LIMIT_CODES or "rate limit" in error_msg.lower():
                raise RateLimitError(f"Bitable 频控: {error_msg}")
            raise BitableAPIError(f"读取 Bitable 记录失败: {error_msg}")

        # TODO(REL-03): 真实多维表格列结构解析待开放平台凭证 + 列样例（当前只返回原始 data，不解析列）。
        return data.get("data", {})

    async def list_tables(
        self, app_token: str, *, page_size: int = 100
    ) -> dict[str, Any]:
        """列出 Bitable 数据表（骨架，端点形状同 list_records，留 REL-03 演进）。"""
        token = await self.get_tenant_access_token()

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.OPEN_API_BASE}/bitable/v1/apps/{app_token}/tables",
                headers={"Authorization": f"Bearer {token}"},
                params={"page_size": page_size},
            )
            data = response.json()

        if data.get("code") != 0:
            raise BitableAPIError(
                f"读取 Bitable 数据表失败: {data.get('msg', 'Unknown error')}"
            )
        return data.get("data", {})


async def _aget_system_open_platform_credentials() -> tuple[str, str] | None:
    """从 SystemSetting 读开放平台凭证（app_id/app_secret），加密则解密（async）。"""
    from common.encryption import decrypt_value
    from system.models import SettingKeys, SystemSetting

    app_id_setting = await SystemSetting.objects.filter(
        key=SettingKeys.FEISHU_APP_ID
    ).afirst()
    app_secret_setting = await SystemSetting.objects.filter(
        key=SettingKeys.FEISHU_APP_SECRET
    ).afirst()
    if (
        app_id_setting
        and app_secret_setting
        and app_id_setting.value
        and app_secret_setting.value
    ):
        app_secret = (
            decrypt_value(app_secret_setting.value)
            if app_secret_setting.is_encrypted
            else app_secret_setting.value
        )
        return app_id_setting.value, app_secret
    return None


async def create_bitable_client_for_project(project: Space) -> BitableClient:
    """为项目构造 BitableClient（**开放平台 token 来源，独立于项目 plugin token**，REL-02）。

    凭证来源镜像 ``create_feishu_doc_client_for_project``：优先项目级开放平台凭证
    （``project.feishu_app_id`` + ``decrypt_value(project.feishu_app_secret_encrypted)``），
    回退系统级 SystemSetting（``FEISHU_APP_ID`` / ``FEISHU_APP_SECRET``，加密则解密）。

    **绝不**取 ``services/feishu.py`` 的项目 plugin token（``project.feishu.cn``）——
    Bitable 走开放平台 ``tenant_access_token`` 体系，与项目 plugin token 来源完全解耦
    （REL-02 核心）。

    Args:
        project: Space 模型实例。

    Returns:
        配置好的 BitableClient 实例。

    Raises:
        ValueError: 项目与系统均未配置开放平台凭证（由 adapter 捕获降级，不崩）。
    """
    from common.encryption import decrypt_value

    # 优先项目级开放平台凭证（feishu_app_id / feishu_app_secret_encrypted）。
    if project.feishu_app_id and project.feishu_app_secret_encrypted:
        app_secret = decrypt_value(project.feishu_app_secret_encrypted)
        return BitableClient(app_id=project.feishu_app_id, app_secret=app_secret)

    # 回退系统级 SystemSetting 开放平台凭证。
    credentials = await _aget_system_open_platform_credentials()
    if credentials:
        return BitableClient(app_id=credentials[0], app_secret=credentials[1])

    raise ValueError(
        f"项目 {project.id} 未配置飞书开放平台应用凭证（app_id/app_secret）。"
        "Bitable 走开放平台 tenant_access_token，独立于项目 plugin token；"
        "请在系统设置或项目设置中配置飞书自建应用 App ID 和 App Secret。"
    )
