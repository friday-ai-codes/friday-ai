"""Accounts app configuration."""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Accounts app configuration."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "用户认证"
