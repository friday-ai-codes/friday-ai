"""
向后兼容别名：保留 OpenAIProvider 名称和 agents.llm.openai 导入路径。
实际实现已移至 agents.llm.openai_completions 模块。
"""
from agents.llm.openai_completions import OpenAICompletionsProvider as OpenAIProvider
__all__ = ["OpenAIProvider"]
