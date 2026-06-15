"""Plan 26-04：实例级 Git 凭证 REST CRUD 安全守护测试（REPO-01，D-04）。

覆盖威胁 T-26-13/14/15/16/17：
- Test 1（T-26-13/14）：POST 明文 token → DB 存 Fernet 密文（≠明文、decrypt 还原一致），
  且 GET list/detail 响应 JSON **不含**明文 token 子串。
- Test 2：has_token 反映是否配置；空 access_token 的 PATCH **不清空**既有 token。
- Test 3（T-26-16）：非管理员（普通认证用户 / 未认证）访问 → 拒绝（403/401）。
- Test 4（T-26-17）：捕获结构化日志，断言 CRUD 路径日志不含 token 明文。
"""

from __future__ import annotations

import pytest
import structlog

from common.encryption import decrypt_value
from repositories.models import GitInstanceCredential

pytestmark = pytest.mark.django_db(transaction=True)

LIST_URL = "/api/repositories/git-instance-credentials/"
DETAIL_URL = "/api/repositories/git-instance-credentials/{cred_id}/"

PLAINTEXT_TOKEN = "glpat-SECRET-PLAINTEXT-abc123XYZ"


class TestNoPlaintextToken:
    def test_create_encrypts_and_response_has_no_plaintext(
        self, authenticated_admin_client
    ) -> None:
        resp = authenticated_admin_client.post(
            LIST_URL,
            {
                "host": "gitlab.example.com",
                "access_token": PLAINTEXT_TOKEN,
                "label": "公司 GitLab",
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        body = resp.json()
        # 响应只含安全字段，绝不回显明文 token（威胁 T-26-13）
        assert body["host"] == "gitlab.example.com"
        assert body["has_token"] is True
        assert "access_token" not in body
        assert "encrypted_token" not in body
        assert PLAINTEXT_TOKEN not in resp.content.decode()

        # DB 存 Fernet 密文：≠ 明文，且 decrypt 还原一致（威胁 T-26-14）
        cred = GitInstanceCredential.objects.get(host="gitlab.example.com")
        assert cred.encrypted_token != PLAINTEXT_TOKEN
        assert PLAINTEXT_TOKEN not in cred.encrypted_token
        assert decrypt_value(cred.encrypted_token) == PLAINTEXT_TOKEN

    def test_list_and_detail_responses_have_no_plaintext_token(
        self, authenticated_admin_client
    ) -> None:
        from common.encryption import encrypt_value

        cred = GitInstanceCredential.objects.create(
            host="gitlab.internal",
            provider="gitlab",
            encrypted_token=encrypt_value(PLAINTEXT_TOKEN),
        )
        list_resp = authenticated_admin_client.get(LIST_URL)
        assert list_resp.status_code == 200
        assert PLAINTEXT_TOKEN not in list_resp.content.decode()

        detail_resp = authenticated_admin_client.get(DETAIL_URL.format(cred_id=cred.id))
        assert detail_resp.status_code == 200
        assert PLAINTEXT_TOKEN not in detail_resp.content.decode()
        assert detail_resp.json()["has_token"] is True

    def test_host_uniqueness_chinese_error(self, authenticated_admin_client) -> None:
        from common.encryption import encrypt_value

        GitInstanceCredential.objects.create(
            host="dup.example.com", encrypted_token=encrypt_value("x")
        )
        resp = authenticated_admin_client.post(
            LIST_URL,
            {"host": "dup.example.com", "access_token": PLAINTEXT_TOKEN},
            format="json",
        )
        assert resp.status_code == 400
        assert "已存在" in resp.content.decode()


class TestHasTokenAndUpdate:
    def test_has_token_and_empty_token_patch_keeps_existing(
        self, authenticated_admin_client
    ) -> None:
        from common.encryption import encrypt_value

        cred = GitInstanceCredential.objects.create(
            host="gitlab.keep.com",
            encrypted_token=encrypt_value(PLAINTEXT_TOKEN),
            label="old",
        )
        original_encrypted = cred.encrypted_token

        # 空 access_token 的 PATCH（仅改 label）不应清空既有 token
        resp = authenticated_admin_client.patch(
            DETAIL_URL.format(cred_id=cred.id),
            {"label": "new label"},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["label"] == "new label"
        assert resp.json()["has_token"] is True

        cred.refresh_from_db()
        assert cred.encrypted_token == original_encrypted
        assert decrypt_value(cred.encrypted_token) == PLAINTEXT_TOKEN

    def test_patch_with_new_token_overwrites(self, authenticated_admin_client) -> None:
        from common.encryption import encrypt_value

        cred = GitInstanceCredential.objects.create(
            host="gitlab.rotate.com",
            encrypted_token=encrypt_value("old-token"),
        )
        new_token = "glpat-NEW-ROTATED-token-999"
        resp = authenticated_admin_client.patch(
            DETAIL_URL.format(cred_id=cred.id),
            {"access_token": new_token},
            format="json",
        )
        assert resp.status_code == 200
        assert new_token not in resp.content.decode()
        cred.refresh_from_db()
        assert decrypt_value(cred.encrypted_token) == new_token

    def test_delete_removes_credential(self, authenticated_admin_client) -> None:
        from common.encryption import encrypt_value

        cred = GitInstanceCredential.objects.create(
            host="gitlab.del.com", encrypted_token=encrypt_value("x")
        )
        resp = authenticated_admin_client.delete(DETAIL_URL.format(cred_id=cred.id))
        assert resp.status_code == 204
        assert not GitInstanceCredential.objects.filter(id=cred.id).exists()


class TestPermissions:
    def test_non_admin_authenticated_denied(
        self, authenticated_client, api_client
    ) -> None:
        # 普通认证用户（非 superuser）→ 403
        assert authenticated_client.get(LIST_URL).status_code == 403
        assert (
            authenticated_client.post(
                LIST_URL,
                {"host": "x.example.com", "access_token": PLAINTEXT_TOKEN},
                format="json",
            ).status_code
            == 403
        )
        # 未认证 → 401/403
        assert api_client.get(LIST_URL).status_code in (401, 403)
        # 普通用户的 POST 不得写库
        assert not GitInstanceCredential.objects.filter(host="x.example.com").exists()


class TestNoTokenInLogs:
    def test_crud_logs_have_no_plaintext_token(self, authenticated_admin_client) -> None:
        # 捕获结构化日志，断言 CRUD 路径日志事件不含 token 明文（威胁 T-26-17）
        with structlog.testing.capture_logs() as logs:
            create_resp = authenticated_admin_client.post(
                LIST_URL,
                {"host": "gitlab.logsafe.com", "access_token": PLAINTEXT_TOKEN},
                format="json",
            )
            assert create_resp.status_code == 201
            cred_id = create_resp.json()["id"]
            authenticated_admin_client.patch(
                DETAIL_URL.format(cred_id=cred_id),
                {"access_token": "another-secret-token"},
                format="json",
            )
            authenticated_admin_client.delete(DETAIL_URL.format(cred_id=cred_id))

        blob = str(logs)
        assert PLAINTEXT_TOKEN not in blob
        assert "another-secret-token" not in blob
