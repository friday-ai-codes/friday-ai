"""Chat runner 多模态 prompt 构造测试。"""
from __future__ import annotations
import base64
from agents.chat_runner import ChatRunnerConfig, _build_human_message_content
from chat.multimodal import build_image_part, store_image_bytes
from services.provider_config import ProviderType
PNG_1X1 = base64.b64decode(
 "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)
def test_build_human_message_content_uses_provider_blocks_for_image_parts(settings) -> None:
 settings.DATA_DIR = settings.BASE_DIR / "data-test"
 stored = store_image_bytes(PNG_1X1, declared_mime_type="image/png", source="test")
 parts = [
 {"type": "text", "id": "p_text", "index": 0, "text": "看图", "state": "done"},
 build_image_part(
 index=1,
 mime_type=stored.mime_type,
 size_bytes=stored.size_bytes,
 storage_ref=stored.storage_ref,
 ),
 ]
 config = ChatRunnerConfig(
 system_prompt="sys",
 model="claude-sonnet-4-5-20250929",
 space_id="space",
 session_id="session",
 provider_type=ProviderType.ANTHROPIC,
 )
 content = _build_human_message_content("看图", parts, config)
 assert isinstance(content, list)
 assert content[0] == {"type": "text", "text": "看图"}
 assert content[1]["type"] == "image"
 assert content[1]["source_type"] == "base64"
