"""charter_service 单测（CHARTER-01，111-03 Task 2）。

覆盖：三源蒸馏起草（happy / provider 缺失 / 非法 JSON 零副作用）、confirm 收口
（署名/version/edits/draft 提升）、**P11 不覆盖不变量**（human_confirmed 后 AI 只写
draft_content，正式字段逐字节不变）、normalize 纯函数边界、INV-6 源码扫描守护。

LLM mock 手法参照 ``test_decompose_segments.py``：charter_service 函数内懒 import，
patch 点在源模块 ``agents.llm_factory.build_chat_model`` /
``services.provider_config.ProviderConfigService.aresolve``。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.call_source import get_call_source
from repositories.models import RepoCharter, Repository
from repositories.services.charter_service import (
    aconfirm_charter,
    adraft_charter,
    normalize_charter_draft,
)
from tests.helpers.fake_chat_model import FakeChatModel

pytestmark = pytest.mark.django_db(transaction=True)

_ARESOLVE = "services.provider_config.ProviderConfigService.aresolve"
_BUILD = "agents.llm_factory.build_chat_model"


def _resolved(default_model: str = "test-model") -> SimpleNamespace:
    return SimpleNamespace(extra={"default_model": default_model})


def _charter_json(positioning: str = "C 端学生移动 H5 学习应用集") -> str:
    return json.dumps(
        {
            "positioning": positioning,
            "owned_domains": [
                {
                    "domain": "学习功能页 / 培优课",
                    "status": "planned",
                    "note": "净新增落点",
                    "citations": ["cit_1"],
                }
            ],
            "boundaries": [
                {"rule": "不承接课程权益鉴权", "decided_by": "human:zane", "citations": []}
            ],
            "placement_preferences": [{"kind": "学生端练习页", "target": "apps/*", "note": ""}],
            "audience": "C端学生",
            "form": "移动端H5",
            "evolution": "active",
        },
        ensure_ascii=False,
    )


def _fake_model(content: str) -> FakeChatModel:
    return FakeChatModel(responses=[content])


# ── 起草：happy path ──────────────────────────────────────────────────────


async def test_adraft_creates_ai_draft_row(repository: Repository) -> None:
    """无 charter 时起草 → 建行 source=ai_draft、version=1，字段来自 mock JSON 且过 normalize。"""
    with (
        patch(_ARESOLVE, new=AsyncMock(return_value=_resolved())),
        patch(_BUILD, return_value=_fake_model(_charter_json())),
    ):
        charter = await adraft_charter(str(repository.id))

    assert charter is not None
    assert charter.source == RepoCharter.Source.AI_DRAFT
    assert charter.version == 1
    assert charter.positioning == "C 端学生移动 H5 学习应用集"
    assert charter.owned_domains == [
        {
            "domain": "学习功能页 / 培优课",
            "status": "planned",
            "note": "净新增落点",
            "citations": ["cit_1"],
        }
    ]
    assert charter.boundaries[0]["rule"] == "不承接课程权益鉴权"
    assert charter.evolution == "active"
    assert charter.draft_content == {}
    assert await RepoCharter.objects.acount() == 1


async def test_adraft_redrafts_in_place_while_still_ai_draft(repository: Repository) -> None:
    """已有 ai_draft 再起草 → 正式字段就地更新，version 不变，不产新行。"""
    with (
        patch(_ARESOLVE, new=AsyncMock(return_value=_resolved())),
        patch(_BUILD, return_value=_fake_model(_charter_json("初版定位"))),
    ):
        first = await adraft_charter(str(repository.id))
    assert first is not None

    with (
        patch(_ARESOLVE, new=AsyncMock(return_value=_resolved())),
        patch(_BUILD, return_value=_fake_model(_charter_json("二版定位"))),
    ):
        second = await adraft_charter(str(repository.id))

    assert second is not None
    assert second.id == first.id
    assert second.version == 1
    assert second.source == RepoCharter.Source.AI_DRAFT
    assert second.positioning == "二版定位"
    assert await RepoCharter.objects.acount() == 1


async def test_adraft_sets_call_source_during_invoke(repository: Repository) -> None:
    """LLM 调用期 contextvar call_source == 'blueprint_charter_draft'。"""
    captured: dict[str, object] = {}

    async def _capture_ainvoke(_messages: object) -> SimpleNamespace:
        captured["call_source"] = get_call_source()
        return SimpleNamespace(content=_charter_json())

    model = MagicMock()
    model.ainvoke = AsyncMock(side_effect=_capture_ainvoke)
    with (
        patch(_ARESOLVE, new=AsyncMock(return_value=_resolved())),
        patch(_BUILD, return_value=model),
    ):
        charter = await adraft_charter(str(repository.id))
    assert charter is not None
    assert captured["call_source"] == "blueprint_charter_draft"


# ── 起草：失败零副作用 ────────────────────────────────────────────────────


async def test_adraft_no_default_model_returns_none(repository: Repository) -> None:
    """provider 缺 default_model → None 且不落任何行。"""
    with (
        patch(_ARESOLVE, new=AsyncMock(return_value=_resolved(default_model=""))),
        patch(_BUILD) as build_spy,
    ):
        result = await adraft_charter(str(repository.id))
    assert result is None
    build_spy.assert_not_called()
    assert await RepoCharter.objects.acount() == 0


async def test_adraft_aresolve_none_returns_none(repository: Repository) -> None:
    """aresolve 返回 None → None 且不落行（getattr 兜底不抛）。"""
    with patch(_ARESOLVE, new=AsyncMock(return_value=None)):
        result = await adraft_charter(str(repository.id))
    assert result is None
    assert await RepoCharter.objects.acount() == 0


async def test_adraft_malformed_json_returns_none(repository: Repository) -> None:
    """LLM 返回非法 JSON → None、不落行。"""
    with (
        patch(_ARESOLVE, new=AsyncMock(return_value=_resolved())),
        patch(_BUILD, return_value=_fake_model("这只是一段没有 JSON 的解释。")),
    ):
        result = await adraft_charter(str(repository.id))
    assert result is None
    assert await RepoCharter.objects.acount() == 0


async def test_adraft_missing_repository_raises(db: object) -> None:
    """仓库不存在 → DoesNotExist 上抛（视图层转 404）。"""
    with pytest.raises(Repository.DoesNotExist):
        await adraft_charter("00000000-0000-0000-0000-000000000000")


# ── confirm 收口 ──────────────────────────────────────────────────────────


async def test_aconfirm_promotes_to_human_confirmed(repository: Repository, user) -> None:
    """confirm → source=human_confirmed、version=2、confirmed_by=user、draft_content=={}。"""
    with (
        patch(_ARESOLVE, new=AsyncMock(return_value=_resolved())),
        patch(_BUILD, return_value=_fake_model(_charter_json())),
    ):
        await adraft_charter(str(repository.id))

    charter = await aconfirm_charter(str(repository.id), user)
    assert charter.source == RepoCharter.Source.HUMAN_CONFIRMED
    assert charter.version == 2
    assert charter.confirmed_by_id == user.id
    assert charter.draft_content == {}


async def test_aconfirm_missing_charter_raises_value_error(repository: Repository, user) -> None:
    """charter 不存在 → ValueError（视图层转 404）。"""
    with pytest.raises(ValueError):
        await aconfirm_charter(str(repository.id), user)


async def test_aconfirm_applies_edits_with_normalize(repository: Repository, user) -> None:
    """confirm 带 edits → 白名单字段生效，且 evolution 非法值被 normalize 回退。"""
    with (
        patch(_ARESOLVE, new=AsyncMock(return_value=_resolved())),
        patch(_BUILD, return_value=_fake_model(_charter_json())),
    ):
        await adraft_charter(str(repository.id))

    charter = await aconfirm_charter(
        str(repository.id),
        user,
        edits={"positioning": "人工改写", "evolution": "bogus-value"},
    )
    assert charter.positioning == "人工改写"
    assert charter.evolution == "active"  # 非法值回退
    # 未在 edits 中的字段不被清空
    assert charter.audience == "C端学生"
    assert charter.source == RepoCharter.Source.HUMAN_CONFIRMED


# ── P11 不覆盖不变量（CHARTER-01 核心）────────────────────────────────────


async def test_ai_never_overwrites_human_confirmed(repository: Repository, user) -> None:
    """human_confirmed 后再起草：正式字段逐字节不变，仅 draft_content 变为新草案。"""
    with (
        patch(_ARESOLVE, new=AsyncMock(return_value=_resolved())),
        patch(_BUILD, return_value=_fake_model(_charter_json("人工确认前定位"))),
    ):
        await adraft_charter(str(repository.id))
    confirmed = await aconfirm_charter(str(repository.id), user)

    snapshot = {
        "positioning": confirmed.positioning,
        "owned_domains": confirmed.owned_domains,
        "boundaries": confirmed.boundaries,
        "placement_preferences": confirmed.placement_preferences,
        "audience": confirmed.audience,
        "form": confirmed.form,
        "evolution": confirmed.evolution,
        "source": confirmed.source,
        "version": confirmed.version,
        "confirmed_by_id": confirmed.confirmed_by_id,
    }

    with (
        patch(_ARESOLVE, new=AsyncMock(return_value=_resolved())),
        patch(_BUILD, return_value=_fake_model(_charter_json("AI 想覆盖的新定位"))),
    ):
        redraft = await adraft_charter(str(repository.id))
    assert redraft is not None

    reloaded = await RepoCharter.objects.aget(repository_id=repository.id)
    assert reloaded.positioning == snapshot["positioning"]
    assert reloaded.owned_domains == snapshot["owned_domains"]
    assert reloaded.boundaries == snapshot["boundaries"]
    assert reloaded.placement_preferences == snapshot["placement_preferences"]
    assert reloaded.audience == snapshot["audience"]
    assert reloaded.form == snapshot["form"]
    assert reloaded.evolution == snapshot["evolution"]
    assert reloaded.source == snapshot["source"]
    assert reloaded.version == snapshot["version"]
    assert reloaded.confirmed_by_id == snapshot["confirmed_by_id"]
    # 新草案只进 draft_content
    assert reloaded.draft_content["positioning"] == "AI 想覆盖的新定位"


async def test_aconfirm_promotes_pending_draft_content(repository: Repository, user) -> None:
    """human_confirmed + 非空 draft_content 再 confirm → 草案提升为正式、version+1、draft 清空。"""
    with (
        patch(_ARESOLVE, new=AsyncMock(return_value=_resolved())),
        patch(_BUILD, return_value=_fake_model(_charter_json("初版定位"))),
    ):
        await adraft_charter(str(repository.id))
    await aconfirm_charter(str(repository.id), user)  # v2 human_confirmed

    with (
        patch(_ARESOLVE, new=AsyncMock(return_value=_resolved())),
        patch(_BUILD, return_value=_fake_model(_charter_json("修订草案定位"))),
    ):
        await adraft_charter(str(repository.id))  # 只写 draft_content

    charter = await aconfirm_charter(str(repository.id), user)
    assert charter.positioning == "修订草案定位"  # 草案提升为正式
    assert charter.version == 3
    assert charter.source == RepoCharter.Source.HUMAN_CONFIRMED
    assert charter.draft_content == {}


# ── normalize_charter_draft 纯函数边界（无 DB）────────────────────────────


@pytest.mark.django_db(transaction=False)
class TestNormalizeCharterDraft:
    """白名单归一：非法类型逐字段回退空值，绝不抛。"""

    def test_non_dict_input_returns_empty_shape(self) -> None:
        for bad in (None, "文本", 123, ["list"]):
            result = normalize_charter_draft(bad)
            assert result == {
                "positioning": "",
                "owned_domains": [],
                "boundaries": [],
                "placement_preferences": [],
                "audience": "",
                "form": "",
                "evolution": "active",
            }

    def test_owned_domains_non_list_falls_back_empty(self) -> None:
        result = normalize_charter_draft({"owned_domains": {"domain": "非 list"}})
        assert result["owned_domains"] == []

    def test_owned_domain_status_invalid_falls_back_implemented(self) -> None:
        result = normalize_charter_draft({"owned_domains": [{"domain": "d", "status": "shipped"}]})
        assert result["owned_domains"][0]["status"] == "implemented"

    def test_owned_domain_missing_domain_skipped(self) -> None:
        result = normalize_charter_draft({"owned_domains": [{"status": "planned"}]})
        assert result["owned_domains"] == []

    def test_evolution_invalid_falls_back_active(self) -> None:
        assert normalize_charter_draft({"evolution": "weird"})["evolution"] == "active"
        assert (
            normalize_charter_draft({"evolution": "MAINTENANCE_ONLY"})["evolution"]
            == "maintenance_only"
        )

    def test_positioning_truncated_to_500(self) -> None:
        result = normalize_charter_draft({"positioning": "长" * 600})
        assert len(result["positioning"]) == 500

    def test_boundaries_missing_rule_skipped(self) -> None:
        result = normalize_charter_draft(
            {"boundaries": [{"decided_by": "human"}, {"rule": "有效规则"}]}
        )
        assert len(result["boundaries"]) == 1
        assert result["boundaries"][0]["rule"] == "有效规则"

    def test_audience_form_truncated_to_64(self) -> None:
        result = normalize_charter_draft({"audience": "a" * 100, "form": "f" * 100})
        assert len(result["audience"]) == 64
        assert len(result["form"]) == 64


# ── INV-6 守护（源码扫描，无 DB）──────────────────────────────────────────

SERVER_DIR = Path(__file__).resolve().parents[2]

_PRUNE_DIRS = {
    ".venv",
    "node_modules",
    "staticfiles",
    "__pycache__",
    ".git",
    "htmlcov",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
}

# 唯一允许写 RepoCharter 的模块（相对 server/）
_ALLOWED_WRITER = "repositories/services/charter_service.py"

_RE_ORM_WRITE = re.compile(
    r"\bRepoCharter\.objects\."
    r"(?:a?create|bulk_create|a?get_or_create|a?update_or_create|a?update)\b"
)
_RE_INSTANTIATE = re.compile(r"\bRepoCharter\s*\(")
_RE_INSTANCE_SAVE = re.compile(r"\bRepoCharter\([^)]*\)\.save\(")


def _iter_py_files() -> list[Path]:
    files: list[Path] = []
    for path in SERVER_DIR.rglob("*.py"):
        if any(part in _PRUNE_DIRS for part in path.relative_to(SERVER_DIR).parts):
            continue
        files.append(path)
    return files


def _is_scanned(rel: str) -> bool:
    if rel == _ALLOWED_WRITER:
        return False
    if rel.startswith("tests/") or "/tests/" in rel:
        return False
    if "/migrations/" in rel:
        return False
    if rel == "repositories/models.py":  # 模型定义处
        return False
    return True


@pytest.mark.django_db(transaction=False)
def test_inv6_no_bypass_writes() -> None:
    """INV-6：除 charter_service 外，server 源码无旁路 RepoCharter 写表入口。"""
    violations: list[str] = []

    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        if not _is_scanned(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("class RepoCharter"):
                continue
            if (
                _RE_ORM_WRITE.search(line)
                or _RE_INSTANCE_SAVE.search(line)
                or _RE_INSTANTIATE.search(line)
            ):
                violations.append(f"{rel}:{lineno}: {line.strip()}")

    assert not violations, (
        "INV-6 违反：发现旁路 RepoCharter 写表（唯一 writer = "
        f"{_ALLOWED_WRITER}）：\n" + "\n".join(violations)
    )


@pytest.mark.django_db(transaction=False)
def test_inv6_writer_actually_writes() -> None:
    """守护有效性：唯一 writer 确实建行 + save，否则守护形同虚设。"""
    writer = SERVER_DIR / _ALLOWED_WRITER
    assert writer.exists(), f"{_ALLOWED_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    assert _RE_ORM_WRITE.search(text), "charter_service 应包含 RepoCharter.objects.create"
    assert ".save(" in text, "charter_service 应包含实例 .save( 写入"
