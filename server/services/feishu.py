"""飞书（Lark）项目集成服务。"""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
import structlog

from common.encryption import decrypt_value
from common.logging import redact_secrets_in_text
from services.feishu_parsing import (
    build_feishu_fields,
    flatten_fields,
    parse_comments,
    rich_text_to_markdown,
    safe_response_json,
    strict_response_json,
)

logger = structlog.get_logger(__name__)


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
        async with httpx.AsyncClient() as client:
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

        async with httpx.AsyncClient() as client:
            response = await client.post(
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

    async def update_work_item_fields(
        self,
        project_key: str,
        work_item_id: int,
        work_item_type: str,
        fields: dict[str, Any],
    ) -> bool:
        """更新工作项字段（飞书项目 OpenAPI，实测可用）。

        端点：
            PUT /open_api/{project_key}/work_item/{work_item_type}/{work_item_id}
            body: {"update_fields": [{"field_key": k, "field_value": v}, ...]}

        关键用途 —— 触发飞书原生「自动建群并绑定工作项」：
            飞书项目（Meegle）**没有**独立的"创建群聊 / 绑定群"OpenAPI 接口。原生建群
            是通过把工作项的 ``group_type`` 字段更新为 ``"auto"`` 来触发的：写入成功后，
            飞书后端会**异步**创建群、自动把工作项相关人（负责人/关注人等）拉入群，并把
            群 ID 原生回填到工作项的 ``chat_group`` / ``group_id`` 字段（通常数秒内生效，
            调用方需轮询 ``get_work_item`` 查询回填结果）。

            实测（study_platform 空间 story 工作项）：``group_type`` 从 ``"disabled"``
            写为 ``"auto"`` 后，约数秒 ``chat_group`` 即出现 ``oc_xxx`` 群 ID。这是目前
            唯一可编程触发"飞书原生绑定群"的方式（区别于走开放平台 IM API 自建群——后者
            不会回填到工作项字段）。

        Args:
            project_key: 飞书项目空间 Key。
            work_item_id: 工作项 ID（int64）。
            work_item_type: 工作项类型 key（story / issue / 自定义类型 key）。
            fields: ``{field_key: field_value}`` 待更新字段映射（如 ``{"group_type": "auto"}``）。

        Returns:
            True 表示更新成功（``err_code == 0``）。

        Raises:
            Exception: API 返回非 0 ``err_code`` 或非 JSON 响应时抛出。
        """
        token = await self.get_plugin_token()
        update_fields = [
            {"field_key": key, "field_value": value} for key, value in fields.items()
        ]

        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{self.PROJECT_API_BASE}/open_api/{project_key}/work_item/{work_item_type}/{work_item_id}",
                headers={
                    "X-PLUGIN-TOKEN": token,
                    "Content-Type": "application/json",
                    "X-USER-KEY": self.user_key or "",
                },
                json={"update_fields": update_fields},
            )
            data = strict_response_json(
                response,
                log_event="feishu_update_work_item_parse_failed",
                project_key=project_key,
                work_item_id=work_item_id,
            )
            if data.get("err_code") != 0:
                raise Exception(f"更新工作项失败: {data}")
            return True

    async def get_work_item_relations(
        self,
        project_key: str,
        work_item_id: int,
        work_item_type: str,
    ) -> list[dict[str, Any]]:
        """获取工作项的关联关系。

        查询所有关联类型：父子、阻塞、关联等。

        Args:
            project_key: 项目空间 Key
            work_item_id: 工作项 ID
            work_item_type: 工作项类型

        Returns:
            关联工作项列表，每项包含:
            - relation_type: 关联类型 (parent, child, blocker, blocked_by, related)
            - work_item_id: 关联工作项 ID
            - work_item_type: 关联工作项类型
            - name: 工作项名称
            - status: 工作项状态
        """
        token = await self.get_plugin_token()

        async with httpx.AsyncClient() as client:
            # Feishu API: GET /open_api/{project_key}/work_item/{type}/{id}/relation
            response = await client.get(
                f"{self.PROJECT_API_BASE}/open_api/{project_key}/work_item/{work_item_type}/{work_item_id}/relation",
                headers={
                    "X-PLUGIN-TOKEN": token,
                    "X-USER-KEY": self.user_key or "",
                },
            )
            # 可选端点（PF-10 实测返回 `Extra data` 非 JSON）：fail-soft 降级
            # expect=dict：合法 JSON 但非 dict（如 []/标量）同样软失败，避免后续
            # data.get("err_code") 抛 AttributeError（WR-01）
            data = safe_response_json(
                response,
                log_event="feishu_get_relations_parse_failed",
                expect=dict,
                project_key=project_key,
                work_item_id=work_item_id,
            )
            if data is None:
                return []  # 非 JSON / 非 dict → 已记 warning，降级返回空，绝不抛断

            if data.get("err_code") != 0:
                return []  # Graceful degradation

            relations = []
            # Parse relation types from response
            for relation in data.get("data", {}).get("relations", []):
                relations.append(
                    {
                        "relation_type": relation.get("relation_type", "related"),
                        "work_item_id": relation.get("work_item_id"),
                        "work_item_type": relation.get("work_item_type"),
                        "name": relation.get("name", ""),
                        "status": relation.get("status", ""),
                        # 标注来源端点；主路径走 derive_relations_from_fields，不依赖此端点
                        "origin": "feishu_relation_api",
                    }
                )

            return relations

    async def create_work_item(
        self,
        project_key: str,
        work_item_type: str,
        name: str,
        *,
        description: str = "",
        template_id: Optional[int] = None,
        extra_fields: Optional[list[dict[str, Any]]] = None,
    ) -> int:
        """创建工作项（飞书项目 OpenAPI 写端点，看板拆分地基 BOARD-01）。

        每个 feature 拆成一个子看板 work_item：名=feature 名、描述=feature 原文。
        鉴权复用 ``get_plugin_token()`` + ``X-PLUGIN-TOKEN`` / ``X-USER-KEY``
        骨架（与 ``update_work_item_fields`` 一致）。

        端点 / 请求体字段名标 ``[ASSUMED] A-CREATE``：Phase 78 仅验证读，写 API
        从未真机跑通，真实端点 / 请求体 / 返回 id 字段名 deferred 记 ``87-UAT.md``，
        autonomous 模式以 respx 覆盖契约、不打断。

        Args:
            project_key: 飞书项目空间 Key。
            work_item_type: 工作项类型（story / 自定义类型 key）。
            name: 工作项名（= feature 名）。
            description: 工作项描述（= feature 原文），经 ``_markdown_to_rich_text``
                落 ``description`` 字段。
            template_id: 工作项模板 id（部分空间建项必填，[ASSUMED] 可选透传）。
            extra_fields: 追加的 ``field_value_pairs`` 项（与默认字段合并）。

        Returns:
            新建工作项 id（int）。

        Raises:
            Exception: ``err_code != 0`` 或非 JSON 响应时 fail-loud 抛出（消息脱敏）。
        """
        started = time.perf_counter()
        logger.info(
            "feishu_work_item_create_started",
            category="caller",
            component="feishu",
            project_key=project_key,
            work_item_type=work_item_type,
            name_len=len(name or ""),
            description_len=len(description or ""),
        )

        token = await self.get_plugin_token()

        # [ASSUMED] A-CREATE：description 落 description 字段（富文本），其余字段透传。
        field_value_pairs: list[dict[str, Any]] = []
        if description:
            field_value_pairs.append(
                {
                    "field_key": "description",  # [ASSUMED] A-CREATE
                    "field_value": self._markdown_to_rich_text(description),
                }
            )
        if extra_fields:
            field_value_pairs.extend(extra_fields)

        # [ASSUMED] A-CREATE：请求体字段名（name / field_value_pairs / template_id）
        body: dict[str, Any] = {"name": name, "field_value_pairs": field_value_pairs}
        if template_id is not None:
            body["template_id"] = template_id

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    # [ASSUMED] A-CREATE：work_item/{type}/create 端点
                    f"{self.PROJECT_API_BASE}/open_api/{project_key}/work_item/{work_item_type}/create",
                    headers={
                        "X-PLUGIN-TOKEN": token,
                        "Content-Type": "application/json",
                        "X-USER-KEY": self.user_key or "",
                    },
                    json=body,
                )
                data = strict_response_json(
                    response,
                    log_event="feishu_work_item_create_parse_failed",
                    project_key=project_key,
                    work_item_type=work_item_type,
                )

                if data.get("err_code") != 0:
                    # 异常文本脱敏（绝不拼明文 token；err_msg 走 redact helper）
                    raise Exception(
                        redact_secrets_in_text(
                            f"创建工作项失败 err_code={data.get('err_code')}: "
                            f"{data.get('err_msg', '')}"
                        )
                    )

                # [ASSUMED] A-CREATE：返回 id 字段名（data.id 或 data.work_item_id）
                payload = data.get("data")
                new_id: Any = None
                if isinstance(payload, dict):
                    new_id = payload.get("id")
                    if new_id is None:
                        new_id = payload.get("work_item_id")
                elif isinstance(payload, int):
                    new_id = payload
                if new_id is None:
                    raise Exception("创建工作项失败: 返回数据中缺少工作项 id")

                duration_ms = (time.perf_counter() - started) * 1000
                logger.info(
                    "feishu_work_item_create_completed",
                    category="caller",
                    component="feishu",
                    project_key=project_key,
                    work_item_type=work_item_type,
                    work_item_id=int(new_id),
                    duration_ms=round(duration_ms, 2),
                )
                return int(new_id)
        except Exception as exc:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.warning(
                "feishu_work_item_create_failed",
                category="caller",
                component="feishu",
                project_key=project_key,
                work_item_type=work_item_type,
                duration_ms=round(duration_ms, 2),
                error=redact_secrets_in_text(str(exc)),
            )
            raise

    async def add_work_item_relation(
        self,
        project_key: str,
        work_item_type: str,
        work_item_id: int,
        *,
        relation_type: int,
        target_id: int,
        target_type: Optional[str] = None,
    ) -> bool:
        """为工作项写关联关系（relation_type=1 关联项目跟踪 / 父子关系）。

        端点 / 请求体标 ``[ASSUMED] A-REL``：写关系端点形态 + 是否需配置中心预配
        关系类型未真机验证，deferred 记 ``87-UAT.md``。

        Args:
            project_key: 飞书项目空间 Key。
            work_item_type: 源工作项类型。
            work_item_id: 源工作项 id。
            relation_type: 关系类型（1 = 关联项目跟踪；父子关系类型由空间配置）。
            target_id: 关联目标工作项 id。
            target_type: 关联目标工作项类型（可选）。

        Returns:
            ``err_code == 0`` 返回 True。

        Raises:
            Exception: ``err_code != 0`` 或非 JSON 响应时 fail-loud 抛出（消息脱敏）。
        """
        started = time.perf_counter()
        logger.info(
            "feishu_work_item_relation_started",
            category="caller",
            component="feishu",
            project_key=project_key,
            work_item_type=work_item_type,
            work_item_id=work_item_id,
            relation_type=relation_type,
        )

        token = await self.get_plugin_token()

        # [ASSUMED] A-REL：请求体字段名（relation_type / target_id / target_type）
        body: dict[str, Any] = {
            "relation_type": relation_type,
            "target_id": target_id,
        }
        if target_type is not None:
            body["target_type"] = target_type

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    # [ASSUMED] A-REL：work_item/{type}/{id}/relation 写端点
                    f"{self.PROJECT_API_BASE}/open_api/{project_key}/work_item/{work_item_type}/{work_item_id}/relation",
                    headers={
                        "X-PLUGIN-TOKEN": token,
                        "Content-Type": "application/json",
                        "X-USER-KEY": self.user_key or "",
                    },
                    json=body,
                )
                data = strict_response_json(
                    response,
                    log_event="feishu_work_item_relation_parse_failed",
                    project_key=project_key,
                    work_item_id=work_item_id,
                )
                if data.get("err_code") != 0:
                    raise Exception(
                        redact_secrets_in_text(
                            f"写工作项关系失败 err_code={data.get('err_code')}: "
                            f"{data.get('err_msg', '')}"
                        )
                    )

                duration_ms = (time.perf_counter() - started) * 1000
                logger.info(
                    "feishu_work_item_relation_completed",
                    category="caller",
                    component="feishu",
                    project_key=project_key,
                    work_item_type=work_item_type,
                    work_item_id=work_item_id,
                    relation_type=relation_type,
                    duration_ms=round(duration_ms, 2),
                )
                return True
        except Exception as exc:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.warning(
                "feishu_work_item_relation_failed",
                category="caller",
                component="feishu",
                project_key=project_key,
                work_item_type=work_item_type,
                work_item_id=work_item_id,
                relation_type=relation_type,
                duration_ms=round(duration_ms, 2),
                error=redact_secrets_in_text(str(exc)),
            )
            raise

    async def detect_relation_capability(
        self,
        project_key: str,
        work_item_type: str,
    ) -> dict[str, Any]:
        """探测空间是否配置父子 / 关联关系类型（fail-soft 降级位，绝不抛）。

        看板拆分需要在建看板前判断父子关系类型是否预配：缺失则降级（建看板不挂
        父子 + 提示去配置中心），绝不阻断建看板。

        端点标 ``[ASSUMED] A-DEGRADE``：空间关系类型配置端点形态未真机确认，候选
        ``work_item/{type}/meta``；无法确定的字段经 ``safe_response_json`` fail-soft。

        Returns:
            ``{"parent_child": bool, "project_track": bool, "raw": Any}``。
            保守默认：关联项目跟踪可用、父子不可用（宁可降级不可误挂）。
        """
        # 保守默认：父子默认不可用、关联项目跟踪默认可用
        capability: dict[str, Any] = {
            "parent_child": False,
            "project_track": True,
            "raw": None,
        }

        try:
            token = await self.get_plugin_token()
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    # [ASSUMED] A-DEGRADE：空间关系/字段类型配置元数据端点
                    f"{self.PROJECT_API_BASE}/open_api/{project_key}/work_item/{work_item_type}/meta",
                    headers={
                        "X-PLUGIN-TOKEN": token,
                        "X-USER-KEY": self.user_key or "",
                    },
                )
            data = safe_response_json(
                response,
                log_event="feishu_relation_capability_parse_failed",
                expect=dict,
                project_key=project_key,
                work_item_type=work_item_type,
            )
            if data is None or data.get("err_code") != 0:
                # 解析失败 / 非 dict / err_code 非 0 → 保守降级（不抛）
                logger.debug(
                    "feishu_relation_capability_probed",
                    category="sampling",
                    component="feishu",
                    project_key=project_key,
                    work_item_type=work_item_type,
                    parent_child=False,
                    project_track=True,
                    degraded=True,
                )
                return capability

            capability["raw"] = data.get("data")
            # [ASSUMED] A-DEGRADE：从 meta 中识别关系类型定义
            relation_types = _extract_relation_type_keys(data.get("data"))
            if "parent_child" in relation_types or "parent" in relation_types:
                capability["parent_child"] = True
            if relation_types:
                # 命中任意关系类型配置即认为关联项目跟踪可用
                capability["project_track"] = True

            logger.debug(
                "feishu_relation_capability_probed",
                category="sampling",
                component="feishu",
                project_key=project_key,
                work_item_type=work_item_type,
                parent_child=capability["parent_child"],
                project_track=capability["project_track"],
                degraded=False,
            )
            return capability
        except Exception as exc:  # noqa: BLE001 — 探测绝不抛、绝不阻断建看板
            logger.warning(
                "feishu_relation_capability_probe_error",
                category="sampling",
                component="feishu",
                project_key=project_key,
                work_item_type=work_item_type,
                error=redact_secrets_in_text(str(exc)),
            )
            return capability

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

        async with httpx.AsyncClient() as client:
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

        async with httpx.AsyncClient() as client:
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

        async with httpx.AsyncClient() as client:
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
                async with httpx.AsyncClient() as client:
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


def _extract_relation_type_keys(meta: Any) -> set[str]:
    """从空间 meta 中尽力提取关系类型 key/name 集合（[ASSUMED] A-DEGRADE，fail-soft）。

    meta 真实形状未真机确认，兼容多种候选：``relation_types`` / ``relations`` /
    嵌套 ``fields`` 中带 ``relation`` 标记的项；逐项取 ``type_key`` / ``key`` /
    ``name`` / ``relation_type``。任何形状不符均跳过，绝不抛。
    """
    keys: set[str] = set()
    if not isinstance(meta, dict):
        return keys

    candidates: list[Any] = []
    for container_key in ("relation_types", "relations", "relation_type_list"):
        value = meta.get(container_key)
        if isinstance(value, list):
            candidates.extend(value)

    # 部分空间把关系类型藏在 fields 元数据里
    fields = meta.get("fields")
    if isinstance(fields, list):
        for fld in fields:
            if isinstance(fld, dict) and "relation" in str(fld.get("field_type_key", "")):
                candidates.append(fld)

    for item in candidates:
        if isinstance(item, str):
            keys.add(item)
        elif isinstance(item, dict):
            for k in ("type_key", "key", "relation_type", "name", "field_key"):
                v = item.get(k)
                if isinstance(v, str) and v:
                    keys.add(v)
    return keys


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
    plugin_secret = decrypt_value(project.feishu_plugin_secret_encrypted)

    return FeishuClient(
        plugin_id=project.feishu_plugin_id,
        plugin_secret=plugin_secret,
        project_key=project.feishu_project_key,
        user_key=project.feishu_user_key,
    )
