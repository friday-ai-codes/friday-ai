"""implementation: ProviderCredential 模型测试 —— 字段、唯一约束、__str__、Manager。

覆盖 contract（系统/项目双作用域）与 contract（同 provider 多命名凭证）。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from django.db import IntegrityError


@pytest.mark.django_db
class TestProviderCredentialUniqueConstraints:
    """ProviderCredential conditional UniqueConstraint 行为验证（Pitfall C 防御）。"""

    def _make(self, **kwargs: Any) -> Any:
        """创建默认 anthropic/system/default 凭证的辅助 fixture。"""
        from common.encryption import encrypt_value
        from system.models import ProviderCredential

        defaults: dict[str, Any] = dict(
            provider_type="anthropic",
            name="default",
            scope="system",
            scope_id=None,
            encrypted_config=encrypt_value(json.dumps({"api_key": "sk-ant-test"})),
        )
        defaults.update(kwargs)
        return ProviderCredential.objects.create(**defaults)

    def test_system_scope_uniqueness(self) -> None:
        """同 (provider_type, name, scope=system) 第二条应触发 IntegrityError。"""
        self._make()
        with pytest.raises(IntegrityError):
            self._make()

    def test_project_scope_uniqueness_per_project(self) -> None:
        """不同 project_id 不冲突；同 project_id 第二条应触发 IntegrityError。"""
        proj_a = uuid.uuid4()
        proj_b = uuid.uuid4()

        self._make(scope="project", scope_id=proj_a)
        self._make(scope="project", scope_id=proj_b)  # 不同 project 不冲突

        with pytest.raises(IntegrityError):
            self._make(scope="project", scope_id=proj_a)

    def test_system_and_project_can_coexist(self) -> None:
        """系统级 default 与项目级 default 必须共存（partial unique index 生效）。

        SQLite >= 3.8 partial index 的回归保护：两条 scope 不同的 default
        不应被任一 constraint 拒绝。
        """
        self._make()  # system / default
        self._make(scope="project", scope_id=uuid.uuid4())  # project / default
        # 不抛异常即成功

    def test_str(self) -> None:
        """__str__ 应为 f'{provider_type}/{scope}/{name}' 格式。"""
        cred = self._make(name="prod")
        assert str(cred) == "anthropic/system/prod"
