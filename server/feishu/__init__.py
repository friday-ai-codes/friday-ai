"""Feishu app - Feishu (Lark) project integration."""
def __getattr__(name: str):
 """Lazy import to avoid circular imports during Django setup."""
 if name == "FeishuApprovalHandler":
 from feishu.approval import FeishuApprovalHandler
 return FeishuApprovalHandler
 raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
__all__ = ["FeishuApprovalHandler"]
