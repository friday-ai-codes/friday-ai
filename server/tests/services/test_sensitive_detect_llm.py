"""Phase 24 Plan 02 Task 2 — 可选 LLM 二分类段 guard 测试（EXCL-03，TDD）。

锁定可选 LLM 增强段 ``classify_ambiguous_files`` 的四条不变量：

1. **graceful 退化**：provider 缺失（``ProviderMissingError``）或调用抛异常 → 返回空增量
   （0），不冒泡；确定性段结果不受影响（T-24-07）。
2. **强密钥不外送**：``real_secret`` 强命中候选绝不进入 LLM 输入（T-24-06）。
3. **最小化特征**：传给 model 的 human 内容只含文件名 + 最小化布尔特征，**不含**任何
   命中的密钥值（T-24-06）。
4. **命中入库**：LLM 判 ``sensitive=true`` → severity=likely_sensitive、detector=llm，
   经统一 ``_upsert_suggestion`` 落库。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from services import sensitive_detect
from services.provider_config import ProviderMissingError
from services.sensitive_detect import (
    AmbiguousCandidate,
    classify_ambiguous_files,
)

# 一个看起来像密钥的值——用于断言它**绝不**出现在送 LLM 的入参里。
_FAKE_SECRET_VALUE = "AKIAIOSFODNN7EXAMPLE_SECRET_BODY"


class _FakeModel:
    """记录 ainvoke 入参的假 model，返回预置 JSON 文本。"""

    def __init__(self, payload: str, recorder: dict) -> None:
        self._payload = payload
        self._recorder = recorder

    async def ainvoke(self, messages):
        self._recorder["messages"] = messages
        return SimpleNamespace(content=self._payload)


def _patch_provider_ok(monkeypatch, payload: str, recorder: dict) -> None:
    """monkeypatch provider 可用 + 假 model 返回 payload。"""

    async def _resolve(*_a, **_k):
        return SimpleNamespace(extra={"default_model": "fake-model"})

    monkeypatch.setattr(
        sensitive_detect.ProviderConfigService,
        "aresolve_or_error",
        staticmethod(_resolve),
        raising=True,
    )
    monkeypatch.setattr(
        "agents.llm_factory.build_chat_model",
        lambda *_a, **_k: _FakeModel(payload, recorder),
        raising=True,
    )


# ---------------------------------------------------------------------------
# 1. graceful 退化
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_provider_missing_returns_empty(monkeypatch) -> None:
    """provider 未配置 → 返回 0，不抛（确定性结果不受影响）。"""

    async def _missing(*_a, **_k):
        return ProviderMissingError(
            missing_provider="anthropic",
            recommended_action="配置凭证",
            source_attempted="system",
        )

    monkeypatch.setattr(
        sensitive_detect.ProviderConfigService,
        "aresolve_or_error",
        staticmethod(_missing),
        raising=True,
    )

    candidates = [AmbiguousCandidate(path="config/app.yaml", severity="config_review")]
    applied = await classify_ambiguous_files("repo-1", candidates)
    assert applied == 0


@pytest.mark.django_db(transaction=True)
async def test_provider_invoke_raises_degrades_to_empty(monkeypatch) -> None:
    """provider 可用但 build_chat_model/ainvoke 抛异常 → 退化为 0，不冒泡。"""

    async def _resolve(*_a, **_k):
        return SimpleNamespace(extra={"default_model": "fake-model"})

    def _boom(*_a, **_k):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(
        sensitive_detect.ProviderConfigService,
        "aresolve_or_error",
        staticmethod(_resolve),
        raising=True,
    )
    monkeypatch.setattr("agents.llm_factory.build_chat_model", _boom, raising=True)

    candidates = [AmbiguousCandidate(path="config/app.yaml", severity="config_review")]
    applied = await classify_ambiguous_files("repo-1", candidates)
    assert applied == 0


@pytest.mark.django_db(transaction=True)
async def test_no_default_model_returns_empty(monkeypatch) -> None:
    """resolved.extra 无 default_model → 退化为 0。"""

    async def _resolve(*_a, **_k):
        return SimpleNamespace(extra={})

    monkeypatch.setattr(
        sensitive_detect.ProviderConfigService,
        "aresolve_or_error",
        staticmethod(_resolve),
        raising=True,
    )

    candidates = [AmbiguousCandidate(path="config/app.yaml", severity="config_review")]
    applied = await classify_ambiguous_files("repo-1", candidates)
    assert applied == 0


# ---------------------------------------------------------------------------
# 2 + 3. 强密钥不外送 + 最小化特征（不含密钥值）
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_real_secret_excluded_and_secret_value_not_sent(monkeypatch) -> None:
    """real_secret 文件不入 LLM 候选；密钥值不出现在送 model 的入参。"""
    recorder: dict = {}
    # model 对所有 ambiguous 文件都判 sensitive=false（本例只关心入参）。
    _patch_provider_ok(monkeypatch, json.dumps([]), recorder)

    candidates = [
        # 强命中：绝不进候选，绝不外送。
        AmbiguousCandidate(
            path="secrets/leaked.env",
            severity=sensitive_detect._REAL_SECRET,
            sample_text=f"AWS_SECRET_ACCESS_KEY={_FAKE_SECRET_VALUE}",
        ),
        # 模糊 config：可进候选，但 sample_text 含密钥值——不得外送。
        AmbiguousCandidate(
            path="config/settings.toml",
            severity="config_review",
            sample_text=f"token = {_FAKE_SECRET_VALUE}",
        ),
    ]

    await classify_ambiguous_files("repo-2", candidates)

    # model 收到过入参（ambiguous 子集非空）。
    assert "messages" in recorder
    serialized = json.dumps(
        [getattr(m, "content", str(m)) for m in recorder["messages"]],
        ensure_ascii=False,
    )

    # real_secret 文件名不得外送。
    assert "secrets/leaked.env" not in serialized
    # 任何密钥值不得外送（哪怕来自被接纳的 ambiguous 文件）。
    assert _FAKE_SECRET_VALUE not in serialized
    # 被接纳的 ambiguous 文件名应在入参中（确认它确实进了候选）。
    assert "config/settings.toml" in serialized


# ---------------------------------------------------------------------------
# 4. 命中入库
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_sensitive_true_upserts_likely_sensitive_llm(monkeypatch) -> None:
    """LLM 判 sensitive=true → likely_sensitive / detector=llm 落库。"""
    from repositories.models import Repository, SensitiveFileSuggestion

    repo = await Repository.objects.acreate(
        name="llm-detect-repo",
        git_url="https://github.com/test/llm-detect.git",
        git_platform="github",
        default_branch="main",
    )

    recorder: dict = {}
    payload = json.dumps(
        [
            {"path": "config/db.yaml", "sensitive": True, "reason": "疑似数据库口令"},
            {"path": "docs/readme.md", "sensitive": False, "reason": "纯文档"},
        ]
    )
    _patch_provider_ok(monkeypatch, payload, recorder)

    candidates = [
        AmbiguousCandidate(path="config/db.yaml", severity="config_review"),
        AmbiguousCandidate(path="docs/readme.md", severity="config_review"),
    ]
    applied = await classify_ambiguous_files(str(repo.id), candidates)
    assert applied == 1

    row = await SensitiveFileSuggestion.objects.filter(
        repository_id=str(repo.id), path="config/db.yaml"
    ).afirst()
    assert row is not None
    assert row.severity == SensitiveFileSuggestion.Severity.LIKELY_SENSITIVE
    assert row.detector == SensitiveFileSuggestion.Detector.LLM
    assert row.status == SensitiveFileSuggestion.Status.PENDING
    # reason 不得回显密钥值（脱敏兜底）。
    assert _FAKE_SECRET_VALUE not in row.reason

    # sensitive=false 文件不入库。
    none_row = await SensitiveFileSuggestion.objects.filter(
        repository_id=str(repo.id), path="docs/readme.md"
    ).afirst()
    assert none_row is None


@pytest.mark.django_db(transaction=True)
async def test_empty_candidates_short_circuits(monkeypatch) -> None:
    """无 ambiguous 候选（全 real_secret 或空）→ 不调 provider，直接返回 0。"""

    async def _should_not_call(*_a, **_k):
        raise AssertionError("provider 不应被调用")

    monkeypatch.setattr(
        sensitive_detect.ProviderConfigService,
        "aresolve_or_error",
        staticmethod(_should_not_call),
        raising=True,
    )

    candidates = [
        AmbiguousCandidate(path="x.pem", severity=sensitive_detect._REAL_SECRET),
    ]
    applied = await classify_ambiguous_files("repo-3", candidates)
    assert applied == 0
