"""运行时兼容性补丁。

adrf 0.1.12 在 15 处使用 asyncio.iscoroutinefunction()，
Python 3.14 弃用该函数（3.16 移除），替换为 inspect.iscoroutinefunction()。
adrf 无新版本修复此问题，需要运行时 monkey-patch。
"""

import asyncio
import inspect

import structlog

logger = structlog.get_logger(__name__)


def patch_asyncio_iscoroutinefunction() -> None:
    """将 asyncio.iscoroutinefunction 替换为 inspect.iscoroutinefunction。

    两者功能完全等价，inspect 版本是 Python 官方推荐用法。
    """
    asyncio.iscoroutinefunction = inspect.iscoroutinefunction  # type: ignore[assignment] # Necessary monkey patch


def patch_langchain_anthropic_usage_metadata() -> None:
    """兼容非官方 Anthropic 网关的 usage 解析（幂等，可重复调用）。

    Anthropic 兼容网关（如公司 ops-ai-gateway）返回的 ``usage.cache_creation``
    里键存在但值为 ``null``，langchain-anthropic 的 ``_create_usage_metadata``
    对其 ``+= cache_creation.get(k, 0)`` 时取到 ``None`` 直接 TypeError ——
    模型响应内容本身是成功的，却因计费元数据解析失败整个调用被判失败
    （线上症状：项目描述生成 422「未配置 AI Provider」误导提示）。

    这里包一层：原函数解析失败时回退到只含 input/output tokens 的最小
    ``UsageMetadata``，绝不让 usage 解析毁掉调用。官方 API 路径行为不变
    （原函数成功即原样返回）。上游修复后（langchain-anthropic 处理 null
    token 字段）本补丁自然变成 no-op，可移除。
    """
    try:
        from langchain_anthropic import chat_models as _chat_models
    except ImportError:  # 未安装 langchain-anthropic 时无需补丁
        return

    original = _chat_models._create_usage_metadata
    if getattr(original, "_friday_usage_patch", False):
        return

    from langchain_core.messages.ai import UsageMetadata

    def _safe_create_usage_metadata(anthropic_usage):  # type: ignore[no-untyped-def]
        try:
            return original(anthropic_usage)
        except (TypeError, ValueError):
            input_tokens = getattr(anthropic_usage, "input_tokens", 0) or 0
            output_tokens = getattr(anthropic_usage, "output_tokens", 0) or 0
            # best-effort 观测：走到回退分支说明网关 usage 形状异常（采样级，不刷屏）
            try:
                logger.debug(
                    "anthropic_usage_metadata_fallback",
                    category="sampling",
                    component="llm_factory",
                )
            except Exception:  # noqa: BLE001 — 观测绝不反噬调用
                pass
            return UsageMetadata(
                input_tokens=int(input_tokens),
                output_tokens=int(output_tokens),
                total_tokens=int(input_tokens) + int(output_tokens),
            )

    _safe_create_usage_metadata._friday_usage_patch = True  # type: ignore[attr-defined]
    _chat_models._create_usage_metadata = _safe_create_usage_metadata  # type: ignore[assignment]
