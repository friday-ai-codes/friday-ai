"""抽取器基础类型 —— ExtractionBundle 与各维度 *Data dataclass。
所有抽取器函数返回 *Data dataclass 实例（非 ORM 实例），
便于单独测试和组合。最终由 graph_writer.py 转为 ORM 批量入库。
"""
from dataclasses import dataclass, field
from typing import Any
@dataclass
class FileContext:
 """解析上下文 —— 文件路径、语言、仓库 ID 等元信息。
 所有抽取器函数接收此对象作为入参之一（per RESEARCH.md §A.3）。
 """
 file_path: str
 language: str
 repository_id: str
 module_path: str = "" # 跨模块 import 解析的 hint，如 "server.services.indexer"
@dataclass
class SymbolData:
 """符号抽取结果 —— 函数/类/方法/顶层变量。
 字段与 Symbol 模型（server/codegraph/models.py）对齐，
 确保 GraphWriter 转换时字段名一一对应。
 """
 name: str
 symbol_type: str # "FUNCTION" | "CLASS" | "METHOD" | "VARIABLE"
 file_path: str
 start_line: int
 end_line: int
 signature: str = "" # 函数签名 / 类定义首行，如 "def foo(a: int, b: str) -> bool:"
 is_async: bool = False
@dataclass
class ImportData:
 """Import 导入抽取结果 —— 文件 A 从模块 B 导入了哪些符号。
 字段与 ImportEdge 模型对齐。
 """
 source_file: str
 target_module: str # 导入的模块名，如 "os.path"、"django.http"
 imported_names: list[str] = field(default_factory=list) # ["foo", "bar as baz"]
 is_relative: bool = False # 是否为相对导入（from .module import x）
 line: int = 0 # Phase: 1-indexed import 语句所在行（0 = 未知；tree-sitter / volar 填充）
 target_path: str | None = None # Phase: volar 解析后的目标文件绝对路径
@dataclass
class CallData:
 """调用边抽取结果 —— 函数 A 在文件内调用了函数/方法 B。
 字段与 CallEdge 模型对齐。Phase 仅文件内解析（per ），
 callee_name 存字符串名（非 FK）。
 caller_key 为三元组 (file_path, name, start_line)，
 与 Symbol.unique_together 对应，GraphWriter 据此查找 caller FK。
 """
 caller_key: tuple[str, str, int] # (file_path, name, start_line)
 callee_name: str
 call_type: str # "DIRECT" | "METHOD" | "ATTRIBUTE" (per )
 line_number: int
 # selector / 对象调用的限定符（Go ``pkg.Func`` 的 ``pkg``）；简单 identifier 才捕获，
 # 复杂操作数留 None。供 Go 跨包解析（Phase）。
 callee_qualifier: str | None = None
@dataclass
class EndpointData:
 """API 端点抽取结果 —— HTTP 方法 + URL 路径 + 处理函数映射。
 字段与 Endpoint 模型对齐。url_path 由 Layer 2 URL patterns 填充，
 Layer 1 装饰器扫描时为 None（由 Orchestrator 事后关联）。
 metadata 由 Go gin 抽取时填充 ogin.G* middleware 参数验证元数据。
 """
 http_method: str # "GET" | "POST" | "PUT" | "DELETE" | "PATCH" | "*"
 url_path: str | None # Layer 1 扫描时暂为 None
 handler_name: str # "views.UserViewSet.list"
 view_type: str # "FUNCTION_VIEW" | "CLASS_VIEW" | "VIEWSET"
 file_path: str
 line_number: int
 metadata: dict[str, Any] | None = field(default=None) #: ogin.G* metadata
@dataclass
class ExtractionBundle:
 """单文件四维抽取结果汇总（ 单趟遍历产出物）。
 GraphWriter.write_bundle(repo, bundle) 消费此对象。
 所有字段为 list，含零个或多个 *Data 实例。
 """
 symbols: list[SymbolData] = field(default_factory=list)
 imports: list[ImportData] = field(default_factory=list)
 calls: list[CallData] = field(default_factory=list)
 endpoints: list[EndpointData] = field(default_factory=list)
 file_path: str = ""
 language: str = ""
__all__ = [
 "ExtractionBundle",
 "FileContext",
 "SymbolData",
 "ImportData",
 "CallData",
 "EndpointData",
]
