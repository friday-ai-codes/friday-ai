"""Django app configuration for SubAgent integration."""

from django.apps import AppConfig


class SubagentConfig(AppConfig):
    """SubAgent app configuration."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "subagent"
    verbose_name = "SubAgent Integration"
