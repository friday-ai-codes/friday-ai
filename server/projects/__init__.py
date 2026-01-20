"""Projects app configuration."""
from django.apps import AppConfig
class ProjectsConfig(AppConfig):
 """Configuration for the projects app."""
 default_auto_field = "django.db.models.BigAutoField"
 name = "projects"
 label = "projects"
 verbose_name = "项目管理"
