"""多模态消息 helper。

本模块只负责内部图片 part 的安全存储、读取与 provider content-block 转换；
入口层（Web / 飞书 / OpenAI-compatible）统一产出这里定义的 ImagePart 形态。
"""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NoReturn

from django.conf import settings

from chat.parts import ImagePart, part_to_dict
from services.model_modalities import (
    InputModality,
    infer_model_modalities,
    normalize_input_modalities,
)
from services.provider_config import PROVIDER_REGISTRY, ProviderType

ALLOWED_IMAGE_MIME_TYPES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
# 截图识别（Phase 35 VIS-01）后端权威允许集：与前端 / 35-UI-SPEC 一致，仅 png/jpeg/webp
# （刻意排除 GIF —— 截图场景无动图诉求，且与上传 UI 的 accept 列表对齐）。
SCREENSHOT_RECALL_MIME_TYPES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGES_PER_MESSAGE = 4

DetailLevel = Literal["auto", "low", "high"]


@dataclass(frozen=True)
class StoredImage:
    """受控图片存储引用。"""

    storage_ref: str
    mime_type: str
    size_bytes: int
    source: str


class ImageValidationError(ValueError):
    """图片校验或 provider vision 能力错误。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _chat_images_root() -> Path:
    return (Path(settings.DATA_DIR) / "chat_images").resolve()


def _normalize_mime_type(mime_type: str | None) -> str:
    if not mime_type:
        return ""
    return mime_type.split(";", 1)[0].strip().lower()


def _sniff_image_mime(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _raise(code: str, message: str) -> NoReturn:
    raise ImageValidationError(code, message)


def validate_image_bytes(
    data: bytes,
    *,
    declared_mime_type: str | None,
    allowed_mime_types: dict[str, str] | None = None,
) -> tuple[str, int]:
    """非持久化双校验：仅校验图片 bytes（空 / 超限 / MIME / sniff / 声明不一致），不写盘。

    承载 ``store_image_bytes`` 原有的全部校验逻辑，返回 ``(mime_type, size_bytes)``；
    非法时抛既有 ``ImageValidationError(code, message)``（code 不变，零行为回归）。

    ``allowed_mime_types`` 为允许集（默认 ``ALLOWED_IMAGE_MIME_TYPES``，含 GIF）；调用方
    可传入更窄的集合（如截图识别的 ``SCREENSHOT_RECALL_MIME_TYPES``，仅 png/jpeg/webp）以
    收紧后端权威校验，与对应入口前端 accept 列表对齐（Phase 35 VIS-01）。
    """
    allowed = allowed_mime_types if allowed_mime_types is not None else ALLOWED_IMAGE_MIME_TYPES
    if not data:
        _raise("empty_image", "图片为空，请重新选择一张有效图片。")
    if len(data) > MAX_IMAGE_BYTES:
        _raise("image_too_large", "图片过大，请上传 10MB 以内的图片。")

    declared = _normalize_mime_type(declared_mime_type)
    sniffed = _sniff_image_mime(data)
    generic_declared = declared in {"", "application/octet-stream", "binary/octet-stream"}

    if declared and declared not in allowed and not generic_declared:
        _raise("unsupported_mime_type", "不支持的图片格式，请使用 PNG、JPEG、GIF 或 WebP。")
    if sniffed is None or sniffed not in allowed:
        _raise("unsupported_mime_type", "图片格式不支持，或文件内容不是有效图片。")
    if declared in allowed and declared != sniffed:
        _raise("mime_mismatch", "图片声明格式与文件内容不一致，请重新上传。")

    return sniffed, len(data)


def store_image_bytes(
    data: bytes,
    *,
    declared_mime_type: str | None,
    source: str,
    filename: str = "",
) -> StoredImage:
    """校验并写入图片 bytes，返回可落库的相对 storage_ref。"""
    mime_type, _size = validate_image_bytes(data, declared_mime_type=declared_mime_type)
    ext = ALLOWED_IMAGE_MIME_TYPES[mime_type]
    root = _chat_images_root()
    root.mkdir(parents=True, exist_ok=True)
    storage_ref = f"chat_images/{uuid.uuid4().hex}{ext}"
    target = (Path(settings.DATA_DIR) / storage_ref).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        _raise("invalid_storage_ref", "图片存储路径无效。")

    target.write_bytes(data)
    return StoredImage(
        storage_ref=storage_ref,
        mime_type=mime_type,
        size_bytes=len(data),
        source=source or filename,
    )


def read_image_bytes(storage_ref: str) -> bytes:
    """读取受控 storage_ref 指向的图片 bytes，防止 path traversal。"""
    if not storage_ref:
        _raise("missing_storage_ref", "图片存储引用为空。")
    root = _chat_images_root()
    target = (Path(settings.DATA_DIR) / storage_ref).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        _raise("invalid_storage_ref", "图片存储路径无效。")
    try:
        return target.read_bytes()
    except FileNotFoundError:
        _raise("image_not_found", "图片文件不存在，请重新上传。")


def build_image_part(
    *,
    index: int,
    mime_type: str,
    size_bytes: int,
    storage_ref: str = "",
    source_url: str = "",
    width: int | None = None,
    height: int | None = None,
    detail: DetailLevel = "auto",
    alt_text: str = "",
) -> dict[str, Any]:
    """构造可直接写入 Message.parts 的 ImagePart dict。"""
    return part_to_dict(
        ImagePart(
            id=f"p_{uuid.uuid4().hex[:12]}",
            index=index,
            mime_type=mime_type,
            size_bytes=size_bytes,
            width=width,
            height=height,
            detail=detail,
            storage_ref=storage_ref,
            source_url=source_url,
            alt_text=alt_text,
        )
    )


def _part_index(part: dict[str, Any]) -> int:
    value = part.get("index", 0)
    return value if isinstance(value, int) else 0


def extract_text_from_parts(parts: list[dict[str, Any]]) -> str:
    """只抽取 text part，供 prompt/search/query 等文本路径复用。"""
    ordered = sorted(parts, key=_part_index)
    return "".join(str(part.get("text", "")) for part in ordered if part.get("type") == "text")


def ensure_vision_supported(provider_type: ProviderType, model: str) -> None:
    """确认 provider + model 均支持 vision；否则给入口层可直接展示的错误。"""
    provider_meta = PROVIDER_REGISTRY[provider_type]
    if not provider_meta.supports_vision:
        _raise("vision_not_supported", "当前 Provider 不支持图片，请切换支持视觉能力的模型。")

    modalities, _ = infer_model_modalities(
        provider_type=provider_type,
        model_id=model,
    )
    if "image" not in modalities:
        _raise("vision_not_supported", "当前模型不支持图片，请切换支持视觉能力的模型。")


def _bound_model_modalities(
    available_models: Any,
    *,
    provider_type: ProviderType,
    model: str,
) -> list[InputModality] | None:
    if not isinstance(available_models, list):
        return None

    for item in available_models:
        if isinstance(item, str):
            model_id = item.strip()
            raw_model: dict[str, Any] = {"id": model_id, "display_name": model_id}
        elif isinstance(item, dict):
            model_id = str(item.get("id") or item.get("name") or "").strip()
            raw_model = item
        else:
            continue
        if model_id != model:
            continue
        if "input_modalities" in raw_model:
            return normalize_input_modalities(raw_model.get("input_modalities"))
        modalities, _ = infer_model_modalities(
            provider_type=provider_type,
            model_id=model_id,
            raw_model=raw_model,
        )
        return modalities
    return None


def ensure_image_input_supported(
    *,
    provider_type: ProviderType,
    model: str,
    available_models: Any = None,
) -> None:
    """确认当前绑定模型支持 image 输入，绑定模型能力优先于全局推断。"""
    modalities = _bound_model_modalities(
        available_models,
        provider_type=provider_type,
        model=model,
    )
    if modalities is not None:
        if "image" not in modalities:
            _raise("vision_not_supported", "当前模型不支持图片，请切换支持图片的模型。")
        return

    ensure_vision_supported(provider_type, model)


def _image_data_url(part: dict[str, Any]) -> tuple[str, str]:
    mime_type = str(part.get("mime_type") or "")
    source_url = str(part.get("source_url") or "")
    if source_url.startswith("data:"):
        return source_url, mime_type

    storage_ref = str(part.get("storage_ref") or "")
    raw = read_image_bytes(storage_ref)
    data = base64.b64encode(raw).decode("ascii")
    return f"data:{mime_type};base64,{data}", mime_type


def to_provider_content_blocks(
    parts: list[dict[str, Any]],
    *,
    provider_type: ProviderType,
    model: str,
    available_models: Any = None,
) -> list[dict[str, Any]]:
    """把内部 parts 转成 provider 可接受的 content blocks。

    只有 text/image 会进入 prompt；tool_use/thinking 是 assistant 输出结构，不作为
    用户多模态请求块发送。

    含图片时的能力门控必须与发送入口（``conversation_service.send_message_stream``）
    一致：优先用凭证绑定模型的模态配置判定，避免全局推断把已配置 vision 的自定义
    模型误判为 text-only（典型：anthropic 兼容代理下 ``mimo-v2.5-pro`` 等非
    ``claude-`` 前缀模型）。``available_models`` 缺省时回退到全局推断（向后兼容）。
    """
    ordered = sorted(parts, key=_part_index)
    has_images = any(part.get("type") == "image" for part in ordered)
    if has_images:
        ensure_image_input_supported(
            provider_type=provider_type,
            model=model,
            available_models=available_models,
        )

    blocks: list[dict[str, Any]] = []
    for part in ordered:
        ptype = part.get("type")
        if ptype == "text":
            text = str(part.get("text", ""))
            if text:
                blocks.append({"type": "text", "text": text})
            continue
        if ptype != "image":
            continue

        data_url, mime_type = _image_data_url(part)
        detail = str(part.get("detail") or "auto")
        if provider_type == ProviderType.ANTHROPIC:
            blocks.append(
                {
                    "type": "image",
                    "source_type": "base64",
                    "mime_type": mime_type,
                    "data": data_url.split(",", 1)[1],
                }
            )
        else:
            blocks.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": data_url,
                        "detail": detail,
                    },
                }
            )

    return blocks
