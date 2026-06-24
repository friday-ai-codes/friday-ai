"""LLM/AI 调用来源枚举与传播（RATE-02 / LOGGING-SPEC §4.1）。

定位
====
QPS/TPS/TTFT/上游错误统计都按 ``call_source`` 区分维度。本模块提供：

- :class:`CallSource`：LOGGING-SPEC §4.1 全部 22 个受控枚举值，作为
  ``ModelUsageRecord.call_source`` 与各 LLM chokepoint 指标标签的权威取值；任意
  非法字符串经 :meth:`CallSource.normalize` 回退安全默认，杜绝基数失控
  （T-72-02-03 Tampering mitigation）。
- ``call_source`` contextvar + :func:`get_call_source` / :func:`use_call_source`：
  调用方（compat/chat 入口、workflow 节点）声明本次调用来源，下游 chokepoint
  （``acquire_llm_slot`` / 两个 Runner）读取兜底，无需逐层透参。

与 Phase 71 ``LogSource`` 的关系：``LogSource`` 是「请求入口来源」
（rest/mcp/chat_sse...），``CallSource`` 是「LLM 调用来源」
（chat/workflow_agent_node/aux_title...），两者正交、各自独立维度。
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum

# 非法 call_source 的安全回退值（不在 22 类枚举内时使用）。
UNKNOWN_CALL_SOURCE = "unknown"


class CallSource(str, Enum):
    """LLM/AI 调用来源受控枚举（LOGGING-SPEC §4.1，22 值，权威照抄）。

    取值刻意收敛为有限集合：作为指标/筛选维度时基数可控；任意字符串经
    :meth:`normalize` 回退默认，杜绝外部输入污染 call_source 维度。
    """

    CHAT = "chat"
    CHAT_COMPAT_OPENAI = "chat_compat_openai"
    CHAT_COMPAT_ANTHROPIC = "chat_compat_anthropic"
    WORKFLOW_AGENT_NODE = "workflow_agent_node"
    WORKFLOW_PROMPT_NODE = "workflow_prompt_node"
    WORKFLOW_VARIABLE_EXTRACTOR = "workflow_variable_extractor"
    WORKFLOW_CODING_CONTAINER = "workflow_coding_container"
    PLAN_MERGE = "plan_merge"
    PLAN_SPEC_GENERATION = "plan_spec_generation"
    AUX_TITLE = "aux_title"
    AUX_SENSITIVE_LLM = "aux_sensitive_llm"
    AUX_SCREENSHOT_VISION = "aux_screenshot_vision"
    AUX_KNOWLEDGE_GRADER = "aux_knowledge_grader"
    AUX_CORPUS_TREE = "aux_corpus_tree"
    AUX_REPO_ROUTER = "aux_repo_router"
    AUX_CRAWL = "aux_crawl"
    REPO_SUMMARY_CONTAINER = "repo_summary_container"
    DEEP_ANALYSIS_CONTAINER = "deep_analysis_container"
    SDK_AGENT_TASK = "sdk_agent_task"
    PROVIDER_HEALTH_PROBE = "provider_health_probe"
    EMBEDDING = "embedding"
    RERANKER = "reranker"

    @classmethod
    def normalize(cls, value: object, default: str = UNKNOWN_CALL_SOURCE) -> str:
        """把任意输入归一化为受控枚举字符串；非法值回退 ``default``。

        接受枚举成员、其字符串值、或大小写不敏感的名字；都不命中即 ``default``。
        """
        if isinstance(value, cls):
            return value.value
        if value is None:
            return default
        raw = str(value).strip().lower()
        for member in cls:
            if raw == member.value:
                return member.value
        return default


# call_source 调用上下文：caller 标注、chokepoint 读取（默认 None 表示未声明）。
_call_source_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "friday_call_source", default=None
)


def get_call_source() -> str | None:
    """读取当前 contextvar 中声明的 call_source；未声明返回 ``None``。"""
    return _call_source_var.get()


def set_call_source(value: object) -> contextvars.Token:
    """设置 call_source contextvar（经 ``normalize`` 受控），返回 reset token。"""
    return _call_source_var.set(CallSource.normalize(value))


@contextmanager
def use_call_source(value: object) -> Iterator[None]:
    """作用域内声明 call_source，退出时恢复原值（caller 标注调用来源用）。"""
    token = _call_source_var.set(CallSource.normalize(value))
    try:
        yield
    finally:
        _call_source_var.reset(token)


__all__ = [
    "CallSource",
    "UNKNOWN_CALL_SOURCE",
    "get_call_source",
    "set_call_source",
    "use_call_source",
]
