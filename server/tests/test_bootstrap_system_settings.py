"""系统设置启动引导命令测试。"""

from io import StringIO

import pytest
from django.core.management import call_command

from common.encryption import decrypt_value
from system.models import SettingKeys, SystemSetting


@pytest.mark.django_db
def test_bootstrap_system_settings_creates_qdrant_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """首次启动时应把 compose 内部 Qdrant URL 写入数据库系统设置。"""
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    out = StringIO()

    call_command("bootstrap_system_settings", stdout=out)

    setting = SystemSetting.objects.get(key=SettingKeys.QDRANT_URL)
    assert setting.value == "http://qdrant:6333"
    assert setting.is_encrypted is False


@pytest.mark.django_db
def test_bootstrap_system_settings_preserves_existing_qdrant_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """管理后台或外部部署已配置 Qdrant 时，启动引导不得覆盖。"""
    SystemSetting.objects.create(
        key=SettingKeys.QDRANT_URL,
        value="http://external-qdrant:6333",
        is_encrypted=False,
    )
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")

    call_command("bootstrap_system_settings")

    setting = SystemSetting.objects.get(key=SettingKeys.QDRANT_URL)
    assert setting.value == "http://external-qdrant:6333"


@pytest.mark.django_db
def test_bootstrap_system_settings_encrypts_qdrant_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qdrant API key 来自环境变量时必须加密落库。"""
    monkeypatch.setenv("QDRANT_API_KEY", "secret-key")

    call_command("bootstrap_system_settings")

    setting = SystemSetting.objects.get(key=SettingKeys.QDRANT_API_KEY)
    assert setting.is_encrypted is True
    assert setting.value != "secret-key"
    assert decrypt_value(setting.value) == "secret-key"
