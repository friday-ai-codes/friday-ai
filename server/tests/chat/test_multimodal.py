"""implementation 多模态消息基础设施测试。"""

from __future__ import annotations

import base64

import pytest

from chat.multimodal import (
    ImageValidationError,
    build_image_part,
    extract_text_from_parts,
    read_image_bytes,
    store_image_bytes,
    to_provider_content_blocks,
)
from services.provider_config import ProviderType

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


@pytest.mark.django_db
def test_store_image_bytes_validates_and_reads_back(settings) -> None:
    settings.DATA_DIR = settings.BASE_DIR / "data-test"

    stored = store_image_bytes(
        PNG_1X1,
        declared_mime_type="image/png",
        source="web",
        filename="screenshot.png",
    )

    assert stored.mime_type == "image/png"
    assert stored.size_bytes == len(PNG_1X1)
    assert stored.storage_ref.startswith("chat_images/")
    assert read_image_bytes(stored.storage_ref) == PNG_1X1


def test_store_image_bytes_rejects_non_image(settings) -> None:
    settings.DATA_DIR = settings.BASE_DIR / "data-test"

    with pytest.raises(ImageValidationError) as exc:
        store_image_bytes(b"not an image", declared_mime_type="text/plain", source="web")

    assert exc.value.code == "unsupported_mime_type"
    assert "图片" in exc.value.message


def test_build_image_part_and_extract_text() -> None:
    part = build_image_part(
        index=1,
        mime_type="image/png",
        size_bytes=10,
        storage_ref="chat_images/x.png",
        alt_text="截图",
    )
    parts = [
        {"type": "text", "id": "p1", "index": 0, "text": "分析一下", "state": "done"},
        part,
    ]

    assert part["type"] == "image"
    assert part["detail"] == "auto"
    assert extract_text_from_parts(parts) == "分析一下"


def test_provider_conversion_anthropic_reads_storage(settings) -> None:
    settings.DATA_DIR = settings.BASE_DIR / "data-test"
    stored = store_image_bytes(PNG_1X1, declared_mime_type="image/png", source="web")
    parts = [
        {"type": "text", "id": "p1", "index": 0, "text": "看图", "state": "done"},
        build_image_part(
            index=1,
            mime_type=stored.mime_type,
            size_bytes=stored.size_bytes,
            storage_ref=stored.storage_ref,
        ),
    ]

    blocks = to_provider_content_blocks(
        parts,
        provider_type=ProviderType.ANTHROPIC,
        model="claude-sonnet-4-5-20250929",
    )

    assert blocks[0] == {"type": "text", "text": "看图"}
    assert blocks[1]["type"] == "image"
    assert blocks[1]["source_type"] == "base64"
    assert blocks[1]["mime_type"] == "image/png"
    assert isinstance(blocks[1]["data"], str)


def test_provider_conversion_openai_uses_data_url(settings) -> None:
    settings.DATA_DIR = settings.BASE_DIR / "data-test"
    stored = store_image_bytes(PNG_1X1, declared_mime_type="image/png", source="web")
    parts = [
        build_image_part(
            index=0,
            mime_type=stored.mime_type,
            size_bytes=stored.size_bytes,
            storage_ref=stored.storage_ref,
            detail="low",
        ),
    ]

    blocks = to_provider_content_blocks(
        parts,
        provider_type=ProviderType.OPENAI_CHAT,
        model="gpt-4o-mini",
    )

    assert blocks[0]["type"] == "image_url"
    assert blocks[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert blocks[0]["image_url"]["detail"] == "low"


def test_provider_conversion_respects_bound_model_modalities(settings) -> None:
    """绑定模型声明了 image 模态时放行——即使模型名不被全局推断识别为 vision。

    回归：anthropic 兼容代理下 ``mimo-v2.5-pro`` 这类非 ``claude-`` 前缀模型，
    全局推断会误判为 text-only；发送入口已用 available_models 放行，runner 侧
    必须同样以绑定模型模态为准，否则发图片消息会静默无响应。
    """
    settings.DATA_DIR = settings.BASE_DIR / "data-test"
    stored = store_image_bytes(PNG_1X1, declared_mime_type="image/png", source="web")
    parts = [
        build_image_part(
            index=0,
            mime_type=stored.mime_type,
            size_bytes=stored.size_bytes,
            storage_ref=stored.storage_ref,
        ),
    ]

    blocks = to_provider_content_blocks(
        parts,
        provider_type=ProviderType.ANTHROPIC,
        model="mimo-v2.5-pro",
        available_models=[
            {"id": "mimo-v2.5-pro", "input_modalities": ["text", "image"]},
        ],
    )

    assert blocks[0]["type"] == "image"
    assert blocks[0]["source_type"] == "base64"


def test_provider_conversion_unknown_model_without_binding_rejects(settings) -> None:
    """缺省 available_models 时回退全局推断：非 claude- 前缀的 anthropic 模型按
    text-only 处理，含图片应拒绝（保持向后兼容的保守判定）。"""
    settings.DATA_DIR = settings.BASE_DIR / "data-test"
    stored = store_image_bytes(PNG_1X1, declared_mime_type="image/png", source="web")

    with pytest.raises(ImageValidationError) as exc:
        to_provider_content_blocks(
            [
                build_image_part(
                    index=0,
                    mime_type=stored.mime_type,
                    size_bytes=stored.size_bytes,
                    storage_ref=stored.storage_ref,
                ),
            ],
            provider_type=ProviderType.ANTHROPIC,
            model="mimo-v2.5-pro",
        )

    assert exc.value.code == "vision_not_supported"


def test_provider_conversion_rejects_non_vision_provider(settings) -> None:
    settings.DATA_DIR = settings.BASE_DIR / "data-test"
    stored = store_image_bytes(PNG_1X1, declared_mime_type="image/png", source="web")

    with pytest.raises(ImageValidationError) as exc:
        to_provider_content_blocks(
            [
                build_image_part(
                    index=0,
                    mime_type=stored.mime_type,
                    size_bytes=stored.size_bytes,
                    storage_ref=stored.storage_ref,
                ),
            ],
            provider_type=ProviderType.OLLAMA,
            model="llama3.1",
        )

    assert exc.value.code == "vision_not_supported"
    assert "不支持图片" in exc.value.message
