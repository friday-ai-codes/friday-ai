"""仓库别名解析纯函数测试。"""

from __future__ import annotations

from services.process_runtime.blueprint_repo_alias import (
    canonicalize_contract_support_repository_ids,
    canonicalize_repository_alias,
    is_resolvable_repository_alias,
    resolve_repository_alias,
    support_alias_is_ignored,
)

_UUID_ONION = "050e49b2-1111-2222-3333-444455556666"
_UUID_AUTH = "aa11bb22-3333-4444-5555-666677778888"


def _associations(*entries: tuple[str, str]) -> list[dict]:
    return [
        {"repository_id": repository_id, "repository_name": repository_name, "role": "direct"}
        for repository_id, repository_name in entries
    ]


def test_resolve_exact_uuid():
    associations = _associations((_UUID_ONION, "frontend/onion-learning"))
    assert resolve_repository_alias(associations, _UUID_ONION) == _UUID_ONION


def test_resolve_exact_full_name():
    associations = _associations((_UUID_ONION, "frontend/onion-learning"))
    assert resolve_repository_alias(associations, "frontend/onion-learning") == _UUID_ONION


def test_resolve_unique_basename():
    associations = _associations((_UUID_ONION, "frontend/onion-learning"))
    assert resolve_repository_alias(associations, "onion-learning") == _UUID_ONION


def test_ambiguous_basename_is_unresolved():
    associations = _associations(
        (_UUID_ONION, "frontend/onion-learning"),
        ("other-uuid", "backend/onion-learning"),
    )
    assert resolve_repository_alias(associations, "onion-learning") is None
    assert not is_resolvable_repository_alias(associations, "onion-learning")


def test_absent_alias_is_unresolved():
    associations = _associations((_UUID_ONION, "frontend/onion-learning"))
    assert resolve_repository_alias(associations, "onion-auth") is None
    assert resolve_repository_alias(associations, "backend/course-business") is None


def test_canonicalize_returns_uuid_or_original():
    associations = _associations((_UUID_ONION, "frontend/onion-learning"))
    assert canonicalize_repository_alias(associations, "onion-learning") == _UUID_ONION
    assert canonicalize_repository_alias(associations, "onion-auth") == "onion-auth"


def test_canonicalize_contract_support_repository_ids_in_place():
    associations = _associations((_UUID_ONION, "frontend/onion-learning"))
    contracts = [
        {
            "direction": "consumed",
            "data_source": {
                "availability": "needs_support",
                "support_repository_id": "onion-learning",
            },
        }
    ]
    changed = canonicalize_contract_support_repository_ids(contracts, associations)
    assert changed == 1
    assert contracts[0]["data_source"]["support_repository_id"] == _UUID_ONION


def test_case_sensitive_full_name():
    associations = _associations((_UUID_ONION, "frontend/onion-learning"))
    assert resolve_repository_alias(associations, "Frontend/Onion-Learning") is None


def test_whitespace_is_stripped():
    associations = _associations((_UUID_ONION, "frontend/onion-learning"))
    assert resolve_repository_alias(associations, "  onion-learning  ") == _UUID_ONION


def test_support_alias_is_ignored_matches_basename_and_exact():
    ignored = ["onion-auth", "course-business"]
    assert support_alias_is_ignored("onion-auth", ignored)
    assert support_alias_is_ignored("backend/course-business", ignored)
    assert support_alias_is_ignored("course-business", ["backend/course-business"])
    assert not support_alias_is_ignored("onion-learning", ignored)
    assert not support_alias_is_ignored("", ignored)
    assert not support_alias_is_ignored("onion-auth", None)
