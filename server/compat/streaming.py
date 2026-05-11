"""OpenAI SSE chunk JSON 序列化工具。"""
from __future__ import annotations
import json
from typing import Any
# 占位常量：值为此对象的 key 在序列化时被剔除
_omit = object
def sse_encode(payload: dict[str, Any]) -> bytes:
 """序列化为 OpenAI SSE chunk 帧，剔除值为 _omit 的 key。
 格式：b"data: {...}\n\n"
 """
 clean = {k: v for k, v in payload.items if v is not _omit}
 return b"data: " + json.dumps(clean, ensure_ascii=False).encode + b"\n\n"
