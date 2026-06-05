"""明文 token 防回归锁名契约（implementation / contract / contract / contract）。

锁名契约（仿 server/tests/test_credential_leak_protection.py:28 范式）：
- 本文件必含**顶层函数** `def test_no_plaintext_token_in_db()` —— 命名锁死、不可改名，
  作为 CI 永久守护，扫描所有账本表断言明文 token 绝不入库。

Wave：顶部 importorskip 让 interactions.ledger / access_tokens.models 未实现时
整文件优雅 skip；checkpoint/03 落地后转为真实断言（RED→GREEN）。
"""

from __future__ import annotations

import pytest

pytest.importorskip("interactions.ledger")
pytest.importorskip("access_tokens.models")

from access_tokens.models import generate_pat  # noqa: E402
from interactions import ledger  # noqa: E402
from interactions.models import InteractionEvent, InteractionRun  # noqa: E402
from runners.models import hash_token  # noqa: E402


@pytest.mark.django_db
def test_no_plaintext_token_in_db() -> None:
    """contract 锁死命名契约：明文 token 绝不出现在任何账本表。

    故意把明文塞进 raw_request / payload → 经写入 helper 脱敏后入库 →
    扫描全部 InteractionRun.raw_request 与 InteractionEvent.payload 断言无明文；
    同时断言 fingerprint(token_hash) 允许存在（只存 hash，不存明文）。
    """
    plaintext = generate_pat()
    fingerprint = hash_token(plaintext)

    run = ledger.create_interaction_run(
        token_fingerprint=fingerprint,
        source="mcp",
        raw_request={"authorization": f"Bearer {plaintext}"},
    )
    ledger.record_event(run, "user_input", {"text": f"my token is {plaintext}"})

    # 扫描所有账本表，断言明文绝不出现
    for r in InteractionRun.objects.all():
        assert plaintext not in str(r.raw_request)
    for event in InteractionEvent.objects.all():
        assert plaintext not in str(event.payload)

    # fingerprint 允许存在：只存 hash，明文绝不入库
    assert InteractionRun.objects.filter(token_fingerprint=fingerprint).exists()
    assert plaintext not in fingerprint
