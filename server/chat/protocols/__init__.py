"""Chat protocol base class and registry."""
from chat.protocols.base import ProviderProtocol
from chat.protocols.openai_chat import OpenAIChatProtocol
__all__ = ["OpenAIChatProtocol", "ProviderProtocol"]
