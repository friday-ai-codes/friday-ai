"""implementation: LSP 协议层 helper（lsprotocol 类型重导出 + URI 双向转换）。

设计目标（per work item / work item / Pitfall P15）：
- 把 ``lsprotocol.types`` 集中通过一个 namespace（``lsp``）暴露，避免 LSP 类型
  散落在多个模块的 ``from lsprotocol.types import ...`` 中。
- 提供 ``Path → file:// URI`` 与 ``file:// URI → Path`` 的对称转换 helper，
  作为 LSP supervisor / backend 与 indexer 文件路径之间的桥梁。

本模块不依赖 supervisor / backend / client，可独立被任意层 import。
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from lsprotocol import types as lsp  # noqa: F401  re-export 入口（其他模块从这里取类型）


def path_to_uri(path: Path) -> str:
    """把绝对路径转为 ``file://`` URI。

    严格要求绝对路径：相对路径在 LSP 协议下无明确语义，且不同 LSP server 的
    workspace 解析不一致，统一在转换处守门。
    """
    if not path.is_absolute():
        raise ValueError(
            f"path_to_uri 需要绝对路径，收到 {path!r}（建议先 Path.resolve()）"
        )
    return path.as_uri()


def uri_to_path(uri: str) -> Path:
    """把 ``file://`` URI 解码为 :class:`pathlib.Path`。

    仅支持 ``file`` scheme；其他 scheme（``http`` / ``git`` 等）一律拒绝，
    避免静默把 HTTP URL 当本地路径处理。
    """
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError(
            f"uri_to_path 仅支持 file scheme，收到 {parsed.scheme!r}（uri={uri!r}）"
        )
    return Path(unquote(parsed.path))


__all__ = ["lsp", "path_to_uri", "uri_to_path"]
