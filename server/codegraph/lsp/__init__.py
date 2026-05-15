"""Phase: LSP 客户端 + Supervisor 子包。
本子包封装通用 LSP 客户端框架：
- ``exceptions``：5 类业务异常（LspError 基类 + 4 子类）
- ``protocol``：lsprotocol 类型重导出 + URI 双向转换 helper
- ``client``：FridayLanguageClient（pygls BaseLanguageClient 子类，封装超时与异常归一）
- ``supervisor``：LspSupervisor 状态机 + 健康检查 + crash-loop 防护
- ``backend``：LspBackend 抽象基类 + 模板方法 + tree-sitter fallback
本 phase 仅落地通用框架，**不**实装任何具体 LSP server（volar / gopls）；
工厂函数 ``get_or_create_supervisor`` / ``shutdown_all_supervisors`` 在 Plan 落地。
"""
from __future__ import annotations
__all__: list[str] =
