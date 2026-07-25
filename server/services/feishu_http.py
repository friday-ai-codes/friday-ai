"""飞书开放平台 HTTP 客户端工厂 —— 统一超时口径。

httpx 的 `AsyncClient()` 默认 `timeout=None`，即**永不超时**。飞书侧一旦出现半开
连接、DNS 卡死或对端不回，协程就会一直挂着占住 async worker；worker 被占满后
工作流触发、webhook 处理、IM 发卡会一起被拖垮，且没有任何超时日志可循。

本模块把超时收敛到 `settings.FEISHU_HTTP_TIMEOUT_SECONDS` 一处（可经同名 env 覆盖），
调用点一律用 `feishu_client()` 取客户端，不各写各的魔数。

用法与原来一致：

    async with feishu_client() as client:
        response = await client.post(url, json=payload)

个别接口确实需要更长时间（如大文档导出）时，显式传参覆盖：

    async with feishu_client(timeout=60.0) as client:
        ...
"""

from __future__ import annotations

import httpx
from django.conf import settings


def feishu_timeout() -> float:
    """当前生效的飞书 HTTP 超时秒数。

    运行时读 settings 而非模块导入期取值，便于测试用 override_settings 调整。
    """
    return float(getattr(settings, "FEISHU_HTTP_TIMEOUT_SECONDS", 30.0))


def feishu_client(timeout: float | None = None, **kwargs) -> httpx.AsyncClient:
    """返回带超时的 `httpx.AsyncClient`。

    Args:
        timeout: 覆盖默认超时（秒）。None 表示用 `FEISHU_HTTP_TIMEOUT_SECONDS`。
        **kwargs: 透传给 `httpx.AsyncClient`（headers、base_url 等）。
    """
    return httpx.AsyncClient(timeout=timeout if timeout is not None else feishu_timeout(), **kwargs)
