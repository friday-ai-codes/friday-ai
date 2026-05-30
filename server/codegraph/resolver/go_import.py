""" —— GoImportResolver：Go import path → 仓内包目录 / 代表 .go 文件。
Go 的「包」是**目录**而非单文件：import path ``github.com/org/repo/internal/svc``
对应仓内目录 ``internal/svc/``（剥去 go.mod 的 module 前缀），该目录下任意 ``.go``
文件都属于同一个包。因此：
- ``resolve_package_dir`` 给出包目录前缀，供 ``SymbolResolver`` 的 Go selector 分支
 在该目录范围内按符号名定位 ``pkg.Func`` 的目标 ``Symbol``。
- ``resolve_module``（实现 288 ``ImportResolver`` Protocol）返回包目录下字典序最小的
 ``.go`` 文件作代表（确定性），满足「本仓 package import 解析到目录 .go 文件」。
``module_path`` 来自仓内 ``go.mod`` 的 ``module`` 行，依赖注入（沿用 288 风格）。
标准库（``fmt``）/ 第三方（``github.com/gin-gonic/gin``，非本 module 前缀）→ ``None``，
绝不误连。纯同步内存（查 ``SymbolIndex``）。
"""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
 from codegraph.resolver.symbol_index import SymbolIndex
__all__ = ["GoImportResolver", "parse_go_module"]
def parse_go_module(go_mod_text: str) -> str | None:
 """从 go.mod 文本读取 ``module`` 路径；无 module 行返回 ``None``。"""
 for line in go_mod_text.splitlines:
 stripped = line.strip
 if stripped.startswith("module "):
 module_path = stripped[len("module "):].strip
 return module_path or None
 return None
def _dir_of(file_path: str) -> str:
 """取文件所在目录（仓根文件返回空串）。"""
 return file_path.rsplit("/", 1)[0] if "/" in file_path else ""
class GoImportResolver:
 """Go import path → 仓内包目录 / 代表文件的语言专属解析器。"""
 def __init__(self, symbol_index: SymbolIndex, module_path: str) -> None:
 self._idx = symbol_index
 self._module_path = module_path.strip("/")
 def resolve_package_dir(self, import_path: str) -> str | None:
 """本仓 import path → 仓内相对目录前缀；标准库/第三方返回 ``None``。
 ``import_path == module_path`` → ``""``（仓根包）；以 ``module_path + "/"``
 开头 → 剥前缀得相对目录；否则非本仓，返回 ``None``。
 """
 if not self._module_path:
 return None
 if import_path == self._module_path:
 return ""
 prefix = f"{self._module_path}/"
 if import_path.startswith(prefix):
 return import_path[len(prefix):].strip("/")
 return None
 def resolve_module(
 self, target_module: str, is_relative: bool, source_file: str
 ) -> str | None:
 """把 Go import path 解析为包目录下代表 ``.go`` 文件（确定性取字典序最小）。
 实现 ``ImportResolver`` Protocol；标准库/第三方/无 .go 文件 → ``None``。
 """
 package_dir = self.resolve_package_dir(target_module)
 if package_dir is None:
 return None
 go_files = [
 file_path
 for file_path in self._idx._files
 if file_path.endswith(".go") and _dir_of(file_path) == package_dir
 ]
 if not go_files:
 return None
 return sorted(go_files)[0]
