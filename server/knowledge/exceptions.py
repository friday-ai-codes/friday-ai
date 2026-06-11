"""knowledge 领域异常。

层级：
- KnowledgeError：knowledge app 全部领域异常的基类（message + details dict）。
- KnowledgeCollectionMismatchError：delivery_knowledge collection 配置
  （维度 / hybrid 结构）与期望不符时抛出——绝不自动删库重建（P8 防线），
  重建只能经 ``manage.py rebuild_delivery_knowledge --yes`` 显式命令。
"""

from __future__ import annotations

__all__ = ["KnowledgeError", "KnowledgeCollectionMismatchError"]


class KnowledgeError(Exception):
    """knowledge 领域异常基类。"""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message


class KnowledgeCollectionMismatchError(KnowledgeError):
    """delivery_knowledge collection 配置与期望不匹配。

    抛出即拒绝：调用方不得捕获后自动删除/重建 collection——切换 embedding
    模型不允许静默清空知识库。message 必须携带现有/期望配置与可操作指引
    （运行 ``manage.py rebuild_delivery_knowledge --yes``）。
    """
