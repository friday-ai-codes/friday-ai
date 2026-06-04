"""Web Chat image upload endpoint tests for Phase."""
from __future__ import annotations
import json
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import AsyncClient
PNG_1X1 = (
 b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
 b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
 b"\x00\x00\x00\nIDATx\x9cc\xf8\x0f\x00\x01\x01\x01\x00"
 b"\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
)
@pytest.mark.asyncio
@pytest.mark.django_db
async def test_chat_image_upload_returns_storage_backed_image_part(settings, tmp_path) -> None:
 """POST /api/chat/images/ stores a valid image and returns an ImagePart."""
 settings.DATA_DIR = tmp_path
 client = AsyncClient
 upload = SimpleUploadedFile("pixel.png", PNG_1X1, content_type="image/png")
 response = await client.post("/api/chat/images/", data={"image": upload})
 assert response.status_code == 201
 payload = json.loads(response.content)
 part = payload["part"]
 assert part["type"] == "image"
 assert part["index"] == 0
 assert part["mime_type"] == "image/png"
 assert part["size_bytes"] == len(PNG_1X1)
 assert part["storage_ref"].startswith("chat_images/")
 assert (tmp_path / part["storage_ref"]).exists
@pytest.mark.asyncio
@pytest.mark.django_db
async def test_chat_image_upload_rejects_non_image(settings, tmp_path) -> None:
 """Non-image uploads fail with a structured validation code."""
 settings.DATA_DIR = tmp_path
 client = AsyncClient
 upload = SimpleUploadedFile("notes.txt", b"not an image", content_type="text/plain")
 response = await client.post("/api/chat/images/", data={"image": upload})
 assert response.status_code == 400
 payload = json.loads(response.content)
 assert payload["code"] == "unsupported_mime_type"
