"""容器失败归因 —— 「这次失败该不该烧掉重试预算」。

判据的价值全在**两个方向都收得住**：漏判只是照旧烧一格预算（现状），错判会让一个永远
跑不出合格产物的仓无限重派容器、把重试上界变成摆设。所以正反两组都要锁。
"""

from __future__ import annotations

import pytest

from services.process_runtime.failure_classification import (
    INFRASTRUCTURE_FAILURE_REASON,
    is_infrastructure_failure,
)


@pytest.mark.parametrize(
    "text",
    [
        # 事故原文形状（2026-09-04：编码 Agent 额度不足打爆三个会话）
        "API error 403: 用户额度不足，请充值后重试",
        "openai.RateLimitError: insufficient_quota",
        "Error code: 429 - Too Many Requests",
        "anthropic.AuthenticationError: invalid_api_key",
        "provider returned 401 Unauthorized",
        "模型供应商凭证失效，请重新配置",
        "dispatch failed: no online runner",
        "runner offline, container was never started",
        "ImagePullBackOff: failed to pull image",
        "connection refused while calling upstream",
    ],
)
def test_infrastructure_failures_are_recognized(text: str) -> None:
    assert is_infrastructure_failure(text) is True


@pytest.mark.parametrize(
    "text",
    [
        # 产物侧失败：重跑大概率还是这个结果，必须照旧计数
        "agent exited with unusable output",
        "repo_plan schema validation failed: impl_items 为空",
        "缺 fitness.verdict，无法解析容器产物",
        "容器超时",
        "unhandled exception in agent loop",
        "",
        None,
        {"reason": "container_failed"},
    ],
)
def test_product_failures_and_junk_are_not_infrastructure(text: object) -> None:
    assert is_infrastructure_failure(text) is False


def test_reason_constant_is_distinguishable_from_container_failed() -> None:
    """归因值必须与既有 ``container_failed`` 不同——运维靠它一眼分清两类失败。"""
    assert INFRASTRUCTURE_FAILURE_REASON == "infrastructure_failed"
    assert INFRASTRUCTURE_FAILURE_REASON != "container_failed"
