"""Tasks app configuration."""
from django.apps import AppConfig
class TasksConfig(AppConfig):
 """Configuration for the tasks app."""
 default_auto_field = "django.db.models.BigAutoField"
 name = "tasks"
 verbose_name = "Tasks"
