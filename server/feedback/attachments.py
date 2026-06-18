"""反馈附件存储 helper：图片 + 视频，落 ``DATA_DIR/feedback_attachments``。

复用 chat 多模态的安全存储思路（magic-bytes sniff + path-traversal 防护 + storage_ref
相对路径落库），并扩展视频支持。校验失败抛 ``AttachmentValidationError(code, message)``，
入口层可直接展示。限制：图片 ≤10MB（png/jpeg/gif/webp），视频 ≤50MB（mp4/webm）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NoReturn

from django.conf import settings

AttachmentKind = Literal["image", "video"]

ALLOWED_IMAGE_MIME_TYPES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
ALLOWED_VIDEO_MIME_TYPES: dict[str, str] = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024
MAX_ATTACHMENTS = 9


@dataclass(frozen=True)
class StoredAttachment:
    """受控附件存储引用。"""

    storage_ref: str
    kind: AttachmentKind
    mime_type: str
    size_bytes: int


class AttachmentValidationError(ValueError):
    """附件校验错误（携带可直接展示的 code + message）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _raise(code: str, message: str) -> NoReturn:
    raise AttachmentValidationError(code, message)


def _attachments_root() -> Path:
    return (Path(settings.DATA_DIR) / "feedback_attachments").resolve()


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


def _sniff_video_mime(data: bytes) -> str | None:
    # WebM / Matroska EBML 头
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    # MP4 / ISO BMFF：偏移 4 处为 "ftyp" box
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "video/mp4"
    return None


def validate_attachment_bytes(
    data: bytes,
    *,
    declared_mime_type: str | None,
) -> tuple[AttachmentKind, str, int]:
    """校验附件 bytes（空 / 超限 / MIME / magic-bytes sniff），返回 (kind, mime, size)。"""
    if not data:
        _raise("empty_attachment", "附件为空，请重新选择。")

    declared = _normalize_mime_type(declared_mime_type)
    generic_declared = declared in {"", "application/octet-stream", "binary/octet-stream"}

    sniffed_image = _sniff_image_mime(data)
    sniffed_video = _sniff_video_mime(data)

    if sniffed_image is not None:
        if len(data) > MAX_IMAGE_BYTES:
            _raise("image_too_large", "图片过大，请上传 10MB 以内的图片。")
        if declared and declared in ALLOWED_IMAGE_MIME_TYPES and declared != sniffed_image:
            _raise("mime_mismatch", "图片声明格式与内容不一致，请重新上传。")
        return "image", sniffed_image, len(data)

    if sniffed_video is not None:
        if len(data) > MAX_VIDEO_BYTES:
            _raise("video_too_large", "视频过大，请上传 50MB 以内的视频。")
        if (
            declared
            and declared in ALLOWED_VIDEO_MIME_TYPES
            and declared != sniffed_video
            and not generic_declared
        ):
            _raise("mime_mismatch", "视频声明格式与内容不一致，请重新上传。")
        return "video", sniffed_video, len(data)

    _raise(
        "unsupported_type",
        "不支持的附件类型，请上传图片（PNG/JPEG/GIF/WebP）或视频（MP4/WebM）。",
    )


def store_attachment_bytes(
    data: bytes,
    *,
    declared_mime_type: str | None,
) -> StoredAttachment:
    """校验并写入附件 bytes，返回可落库的相对 storage_ref。"""
    kind, mime_type, size = validate_attachment_bytes(data, declared_mime_type=declared_mime_type)
    ext = (ALLOWED_IMAGE_MIME_TYPES | ALLOWED_VIDEO_MIME_TYPES)[mime_type]
    root = _attachments_root()
    root.mkdir(parents=True, exist_ok=True)
    storage_ref = f"feedback_attachments/{uuid.uuid4().hex}{ext}"
    target = (Path(settings.DATA_DIR) / storage_ref).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        _raise("invalid_storage_ref", "附件存储路径无效。")

    target.write_bytes(data)
    return StoredAttachment(
        storage_ref=storage_ref,
        kind=kind,
        mime_type=mime_type,
        size_bytes=size,
    )


def read_attachment_bytes(storage_ref: str) -> bytes:
    """读取受控 storage_ref 指向的附件 bytes，防止 path traversal。"""
    if not storage_ref:
        _raise("missing_storage_ref", "附件存储引用为空。")
    root = _attachments_root()
    target = (Path(settings.DATA_DIR) / storage_ref).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        _raise("invalid_storage_ref", "附件存储路径无效。")
    try:
        return target.read_bytes()
    except FileNotFoundError:
        _raise("attachment_not_found", "附件文件不存在。")


def content_type_for(file_name: str) -> str:
    """按扩展名推断 content-type（读取端用）。"""
    suffix = Path(file_name).suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
    }.get(suffix, "application/octet-stream")
