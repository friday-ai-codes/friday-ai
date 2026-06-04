"""interactions app 配置 —— 全量交互账本（Interaction Ledger）。"""
from django.apps import AppConfig
class InteractionsConfig(AppConfig):
 default_auto_field = "django.db.models.BigAutoField"
 name = "interactions"
 verbose_name = "Interaction Ledger"
