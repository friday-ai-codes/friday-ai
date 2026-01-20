"""Webhooks app configuration."""
from django.apps import AppConfig
class WebhooksConfig(AppConfig):
 """Configuration for the webhooks app."""
 default_auto_field = "django.db.models.BigAutoField"
 name = "webhooks"
 label = "webhooks"
 verbose_name = "Webhooks"
