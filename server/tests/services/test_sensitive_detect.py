"""敏感文件确定性检测器守护测试（Phase 24 Plan 01，EXCL-03）。

覆盖（DOMAIN §9 D-02/D-04）：
- 含真实密钥的文件（.env 内 AWS key、id_rsa 私钥块、settings.json 内 GitHub token）
  被识别为 severity=real_secret / detector=content。
- **脱敏断言**：reason 描述命中类型与行号，但**绝不**包含密钥本体（value not in reason）。
- 普通配置文件（无赋值密钥 / 无高熵串）不被过度标记。
- 仅文件名命中 BUILTIN_GLOBAL_DEFAULTS（如 secrets/app.pem）→ heuristic 基线建议。
- upsert 幂等 + dismissed 不复扰 + real_secret 升级重新打扰（置 pending）。
"""

from __future__ import annotations

from typing import Any

import pytest
from asgiref.sync import sync_to_async

pytestmark = pytest.mark.django_db(transaction=True)

# 测试用「密钥本体」——断言它们绝不出现在 reason 中。
AWS_SECRET_VALUE = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
GITHUB_TOKEN_VALUE = "ghp_" + "x" * 36
PRIVATE_KEY_BODY = "b3BlbnNzaC1rZXktdjEAAAFAKEPRIVATEKEYBODYDONOTLOGabcdef0123456789"


async def _make_repo() -> Any:
    from repositories.models import Repository

    return await sync_to_async(Repository.objects.create)(
        name="Sensitive Detect Repo",
        git_url="https://example.com/sec/repo.git",
        git_platform="github",
        default_branch="main",
    )


async def _suggestions(repo_id: Any) -> list[Any]:
    from repositories.models import SensitiveFileSuggestion

    return await sync_to_async(
        lambda: list(SensitiveFileSuggestion.objects.filter(repository_id=repo_id))
    )()


async def test_env_with_aws_key_is_real_secret_and_redacted(tmp_path: Any) -> None:
    from services.sensitive_detect import detect_sensitive_files

    repo = await _make_repo()
    (tmp_path / ".env").write_text(
        f"AWS_SECRET_ACCESS_KEY={AWS_SECRET_VALUE}\n", encoding="utf-8"
    )

    await detect_sensitive_files(str(repo.id), str(tmp_path))

    rows = [r for r in await _suggestions(repo.id) if r.path == ".env"]
    assert len(rows) == 1
    row = rows[0]
    assert row.severity == "real_secret"
    assert row.detector == "content"
    assert row.status == "pending"
    assert "AWS" in row.reason
    assert "行" in row.reason
    assert AWS_SECRET_VALUE not in row.reason


async def test_id_rsa_private_key_block_is_real_secret_and_redacted(tmp_path: Any) -> None:
    from services.sensitive_detect import detect_sensitive_files

    repo = await _make_repo()
    content = (
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        f"{PRIVATE_KEY_BODY}\n"
        "-----END OPENSSH PRIVATE KEY-----\n"
    )
    (tmp_path / "id_rsa").write_text(content, encoding="utf-8")

    await detect_sensitive_files(str(repo.id), str(tmp_path))

    row = next(r for r in await _suggestions(repo.id) if r.path == "id_rsa")
    assert row.severity == "real_secret"
    assert row.detector == "content"
    assert "私钥" in row.reason
    assert "行" in row.reason
    assert PRIVATE_KEY_BODY not in row.reason


async def test_settings_json_github_token_is_real_secret_and_redacted(tmp_path: Any) -> None:
    from services.sensitive_detect import detect_sensitive_files

    repo = await _make_repo()
    content = '{\n  "config": "GITHUB_TOKEN=' + GITHUB_TOKEN_VALUE + '"\n}\n'
    (tmp_path / "settings.json").write_text(content, encoding="utf-8")

    await detect_sensitive_files(str(repo.id), str(tmp_path))

    row = next(r for r in await _suggestions(repo.id) if r.path == "settings.json")
    assert row.severity == "real_secret"
    assert row.detector == "content"
    assert GITHUB_TOKEN_VALUE not in row.reason


async def test_plain_config_not_overflagged(tmp_path: Any) -> None:
    from services.sensitive_detect import detect_sensitive_files

    repo = await _make_repo()
    (tmp_path / "config.yaml").write_text(
        "name: demo\nport: 8080\nlog_level: info\n", encoding="utf-8"
    )

    await detect_sensitive_files(str(repo.id), str(tmp_path))

    rows = [r for r in await _suggestions(repo.id) if r.path == "config.yaml"]
    assert rows == []


async def test_filename_only_hit_yields_heuristic_suggestion(tmp_path: Any) -> None:
    from services.sensitive_detect import detect_sensitive_files

    repo = await _make_repo()
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "app.pem").write_text("just notes, no real material\n", encoding="utf-8")

    await detect_sensitive_files(str(repo.id), str(tmp_path))

    row = next(r for r in await _suggestions(repo.id) if r.path == "secrets/app.pem")
    assert row.detector == "heuristic"
    assert row.severity in ("config_review", "likely_sensitive")


async def test_upsert_idempotent_dismiss_respected_and_real_secret_upgrade(tmp_path: Any) -> None:
    from repositories.models import SensitiveFileSuggestion
    from services.sensitive_detect import detect_sensitive_files

    repo = await _make_repo()
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    pem = secrets_dir / "app.pem"
    pem.write_text("just notes\n", encoding="utf-8")

    await detect_sensitive_files(str(repo.id), str(tmp_path))
    first = await _suggestions(repo.id)
    first_count = len(first)
    assert first_count >= 1

    # 第二次检测同 path → upsert，不新增行
    await detect_sensitive_files(str(repo.id), str(tmp_path))
    assert len(await _suggestions(repo.id)) == first_count

    pem_row = next(r for r in await _suggestions(repo.id) if r.path == "secrets/app.pem")
    await sync_to_async(
        SensitiveFileSuggestion.objects.filter(id=pem_row.id).update
    )(status="dismissed")

    # 同级别再次命中 → 保留 dismissed，不复扰
    await detect_sensitive_files(str(repo.id), str(tmp_path))
    after = await sync_to_async(SensitiveFileSuggestion.objects.get)(id=pem_row.id)
    assert after.status == "dismissed"

    # 升级为 real_secret（内容含 AWS key）→ 重新置 pending（打扰升级）
    pem.write_text(f"AWS_SECRET_ACCESS_KEY={AWS_SECRET_VALUE}\n", encoding="utf-8")
    await detect_sensitive_files(str(repo.id), str(tmp_path))
    upgraded = await sync_to_async(SensitiveFileSuggestion.objects.get)(id=pem_row.id)
    assert upgraded.severity == "real_secret"
    assert upgraded.status == "pending"
    assert AWS_SECRET_VALUE not in upgraded.reason
