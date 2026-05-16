"""API Resolver 数据结构 —— ApiWrapperData / ApiCallSiteData dataclass。
per: ApiWrapperData 对应 codegraph_api_wrapper 表
per: ApiCallSiteData 对应 codegraph_api_call_site 表
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
@dataclass
class ApiWrapperData:
 """ApiWrapper 抽取结果 —— 调用 LowLevelHelper 的 export function。
 字段与 ApiWrapper 模型对齐，GraphWriter 据此批量写入 DB。
 _jsdoc_text 为内部临时字段，Plan JSDoc 富集后清除（不写 DB）。
 """
 file_path: str
 function_symbol: str
 http_method: str
 url_path_raw: str
 url_path_pattern: str
 detected_via: str = "axios_anchor"
 line_number: int = 0
 metadata: dict[str, Any] | None = field(default=None)
 _jsdoc_text: str | None = field(default=None, repr=False)
@dataclass
class ApiCallSiteData:
 """ApiCallSite 抽取结果 —— ApiWrapper 的调用点（通过 volar references 发现）。
 api_wrapper_file + api_wrapper_symbol 用于在 DB 中定位对应 ApiWrapper FK。
 字段与 ApiCallSite 模型对齐。
 """
 api_wrapper_file: str
 api_wrapper_symbol: str
 caller_file: str
 caller_function: str
 line_number: int
__all__ = ["ApiWrapperData", "ApiCallSiteData"]
