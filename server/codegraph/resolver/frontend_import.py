"""work item —— FrontendImportResolver：TS/TSX/JS/JSX/Vue import → 仓内文件路径。

实现 288 ``base.ImportResolver`` Protocol（结构化子类型，无需显式继承）。覆盖：

- **相对路径**：``./Foo`` / ``../utils/bar`` 按 ``source_file`` 目录回溯（segment 级
  ``.`` 跳过、``..`` 上弹），与 Python 的点分模块不同——前端相对导入是路径式。
- **tsconfig alias**：``~/components/Foo`` 按注入的 ``alias_map``（``{"~/":"src/"}``，
  来自 ``tsconfig.compilerOptions.paths``）改写为 ``src/components/Foo``。
- **扩展名补全 + index 解析**：候选顺序 ``.ts → .tsx → .js → .jsx → .vue``，文件优先
  于 ``dir/index.{ext}``；显式扩展（``./Foo.vue``）只按该扩展精确匹。
- **命中口径**：``has_file`` 精确优先 + ``f"/{candidate}"`` endswith 锚定兜底（复用
  ``python_import._lookup`` 同款双保险，避免 ``auth.ts`` 误匹 ``oauth.ts``）。

非相对、非 alias 命中的裸模块（``vue`` / ``@vueuse/core`` 等）视为第三方，返回
``None`` 不误连。纯同步内存（查 ``SymbolIndex``，不碰 ORM / 文件系统）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from codegraph.resolver.symbol_index import SymbolIndex

__all__ = ["FrontendImportResolver", "load_alias_map", "parse_tsconfig_aliases"]

# 前端候选扩展名，固定优先级顺序（.ts 优先于 .vue）。
_FRONTEND_EXTENSIONS: tuple[str, ...] = (".ts", ".tsx", ".js", ".jsx", ".vue")


def parse_tsconfig_aliases(
    tsconfig_data: dict | str, *, base_dir: str = ""
) -> dict[str, str]:
    """把 ``tsconfig.compilerOptions.paths`` 解析为前缀 alias_map。

    ``{"~/*": ["src/*"]}`` → ``{"~/": "src/"}``（去尾 ``*``，多 target 取首项）。
    ``baseUrl`` 非 ``.``/空时，value 前缀拼 ``baseUrl``（相对 baseUrl 归一到仓相对）。
    缺 ``paths`` / 非法 JSON 返回 ``{}``（不抛）。

    Args:
        tsconfig_data: 已解析的 dict，或待解析的 JSON 文本（不支持含注释的 JSONC）。
        base_dir: 仓内 tsconfig 所在目录前缀（291 整库接入时传，单测可省）。
    """
    if isinstance(tsconfig_data, str):
        try:
            data = json.loads(tsconfig_data)
        except (ValueError, TypeError):
            return {}
    else:
        data = tsconfig_data

    if not isinstance(data, dict):
        return {}

    compiler_options = data.get("compilerOptions") or {}
    paths = compiler_options.get("paths") or {}
    if not isinstance(paths, dict):
        return {}

    base_url = compiler_options.get("baseUrl") or "."
    prefix_parts = [p for p in (base_dir, base_url) if p and p != "."]
    prefix = "/".join(part.strip("/") for part in prefix_parts)
    prefix = f"{prefix}/" if prefix else ""

    alias_map: dict[str, str] = {}
    for alias_pattern, targets in paths.items():
        if not isinstance(targets, list) or not targets:
            continue
        key = alias_pattern.rstrip("*")
        value = str(targets[0]).rstrip("*")
        alias_map[key] = f"{prefix}{value}"
    return alias_map


def load_alias_map(tsconfig_path: str) -> dict[str, str]:
    """从磁盘读取 tsconfig 并解析 alias_map；文件不存在/读失败返回 ``{}``。

    仅 291 整库接入索引/重建流程时使用（IO 隔离）；单测直接用 ``parse_tsconfig_aliases``。
    """
    try:
        with open(tsconfig_path, encoding="utf-8") as fh:
            return parse_tsconfig_aliases(fh.read())
    except OSError:
        return {}


class FrontendImportResolver:
    """前端 import 模块名 → 仓内 ``file_path`` 的语言专属解析器（work item）。"""

    def __init__(self, symbol_index: SymbolIndex, alias_map: Mapping[str, str]) -> None:
        self._idx = symbol_index
        self._aliases = dict(alias_map)

    def resolve_module(
        self, target_module: str, is_relative: bool, source_file: str
    ) -> str | None:
        """把前端 import 模块名解析为仓内 ``file_path``，第三方/解析不到返回 ``None``。"""
        located = self._locate(target_module, is_relative, source_file)
        if located is None:
            # 非相对、非 alias 命中 → 第三方裸模块，不试候选、不误连。
            return None

        # 剥离显式扩展名（``./Foo.vue`` → base=``.../Foo`` + ext=``.vue``）。
        explicit_ext = ""
        base = located
        for ext in _FRONTEND_EXTENSIONS:
            if base.endswith(ext):
                explicit_ext = ext
                base = base[: -len(ext)]
                break

        # 归一化：折叠重复 ``/`` 与前导 ``/``，保证 has_file 精确命中。
        base = "/".join(seg for seg in base.split("/") if seg)

        if explicit_ext:
            candidates: tuple[str, ...] = (f"{base}{explicit_ext}",)
        else:
            file_candidates = tuple(f"{base}{ext}" for ext in _FRONTEND_EXTENSIONS)
            index_candidates = tuple(
                f"{base}/index{ext}" for ext in _FRONTEND_EXTENSIONS
            )
            candidates = file_candidates + index_candidates

        for candidate in candidates:
            hit = self._lookup(candidate)
            if hit is not None:
                return hit
        return None

    def _locate(
        self, target_module: str, is_relative: bool, source_file: str
    ) -> str | None:
        """定位仓内 base 路径（未含扩展名补全）；第三方返回 ``None``。

        优先 alias 改写，其次相对路径回溯；两者皆不命中视为第三方裸模块。
        """
        for prefix, replacement in self._aliases.items():
            if prefix and target_module.startswith(prefix):
                return f"{replacement}{target_module[len(prefix):]}"

        if (
            is_relative
            or target_module.startswith("./")
            or target_module.startswith("../")
        ):
            src_dir = source_file.rsplit("/", 1)[0] if "/" in source_file else ""
            parts = [p for p in src_dir.split("/") if p] if src_dir else []
            for segment in target_module.split("/"):
                if segment in ("", "."):
                    continue
                if segment == "..":
                    if parts:
                        parts.pop()
                    continue
                parts.append(segment)
            return "/".join(parts)

        return None

    def _lookup(self, candidate: str) -> str | None:
        """单候选命中判定：精确 ``has_file`` 优先，miss 后 ``/`` + endswith 锚定兜底。

        锚定用 ``f"/{candidate}"`` 而非裸 ``candidate`` endswith，防 ``auth.ts`` 误匹配
        ``oauth.ts``（口径同 ``python_import._lookup``）。
        """
        if self._idx.has_file(candidate):
            return candidate
        anchored = f"/{candidate}"
        for file_path in self._idx._files:
            if file_path.endswith(anchored):
                return file_path
        return None
