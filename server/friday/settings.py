"""
Django settings for Friday project.
AI-powered Development Automation System
"""
import os
from datetime import timedelta
from pathlib import Path
# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve.parent.parent
DATA_DIR = BASE_DIR / "data"
# Ensure data directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "repos").mkdir(exist_ok=True)
(DATA_DIR / "sessions").mkdir(exist_ok=True)
(DATA_DIR / "credentials").mkdir(exist_ok=True)
# =============================================================================
# Core Settings
# =============================================================================
# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-change-me-in-production")
# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("FRIDAY_DEBUG", "True").lower in ("true", "1", "yes")
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")
# =============================================================================
# Application definition
# =============================================================================
INSTALLED_APPS = [
 "django.contrib.auth",
 "django.contrib.contenttypes",
 "django.contrib.sessions",
 "django.contrib.messages",
 "django.contrib.staticfiles",
 # Third-party apps
 "rest_framework",
 "rest_framework_simplejwt",
 "drf_spectacular",
 "corsheaders",
 # Local apps (refactored by domain)
 "accounts",
 "system",
 "repositories",
 "projects",
 "feishu",
 "tasks",
]
MIDDLEWARE = [
 "django.middleware.security.SecurityMiddleware",
 "corsheaders.middleware.CorsMiddleware",
 "django.contrib.sessions.middleware.SessionMiddleware",
 "django.middleware.common.CommonMiddleware",
 "django.middleware.csrf.CsrfViewMiddleware",
 "django.contrib.auth.middleware.AuthenticationMiddleware",
 "django.contrib.messages.middleware.MessageMiddleware",
 "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "friday.urls"
# URL Configuration - Allow both with and without trailing slash
APPEND_SLASH = False
TEMPLATES = [
 {
 "BACKEND": "django.template.backends.django.DjangoTemplates",
 "DIRS":,
 "APP_DIRS": True,
 "OPTIONS": {
 "context_processors": [
 "django.template.context_processors.request",
 "django.contrib.auth.context_processors.auth",
 "django.contrib.messages.context_processors.messages",
 ],
 },
 },
]
WSGI_APPLICATION = "friday.wsgi.application"
ASGI_APPLICATION = "friday.asgi.application"
# =============================================================================
# Database
# =============================================================================
DATABASES = {
 "default": {
 "ENGINE": "django.db.backends.sqlite3",
 "NAME": DATA_DIR / "friday.db",
 }
}
# =============================================================================
# Custom User Model
# =============================================================================
AUTH_USER_MODEL = "accounts.User"
# =============================================================================
# Password validation
# =============================================================================
AUTH_PASSWORD_VALIDATORS = [
 {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
 {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
 {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
 {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
# =============================================================================
# Internationalization
# =============================================================================
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True
# =============================================================================
# Static files
# =============================================================================
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
# =============================================================================
# CORS Settings
# =============================================================================
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = [
 origin.strip
 for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
 if origin.strip
]
# =============================================================================
# REST Framework Settings
# =============================================================================
REST_FRAMEWORK = {
 "DEFAULT_AUTHENTICATION_CLASSES": [
 "rest_framework_simplejwt.authentication.JWTAuthentication",
 ],
 "DEFAULT_PERMISSION_CLASSES": [
 "rest_framework.permissions.IsAuthenticated",
 ],
 "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
 "EXCEPTION_HANDLER": "common.exceptions.custom_exception_handler",
}
# =============================================================================
# JWT Settings
# =============================================================================
SIMPLE_JWT = {
 "ACCESS_TOKEN_LIFETIME": timedelta(
 minutes=int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
 ),
 "REFRESH_TOKEN_LIFETIME": timedelta(
 days=int(os.environ.get("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))
 ),
 "SIGNING_KEY": os.environ.get("JWT_SECRET_KEY", "") or SECRET_KEY,
 "AUTH_HEADER_TYPES": ("Bearer",),
 "USER_ID_FIELD": "id",
 "USER_ID_CLAIM": "sub",
}
# Cookie settings for refresh token
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "False").lower in ("true", "1", "yes")
COOKIE_SAMESITE = os.environ.get("COOKIE_SAMESITE", "Lax")
COOKIE_HTTPONLY = os.environ.get("COOKIE_HTTPONLY", "True").lower in ("true", "1", "yes")
# =============================================================================
# drf-spectacular (Swagger/OpenAPI) Settings
# =============================================================================
SPECTACULAR_SETTINGS = {
 "TITLE": "Friday API",
 "DESCRIPTION": "AI-powered Development Automation System",
 "VERSION": "1.0.0",
 "SERVE_INCLUDE_SCHEMA": False,
 "COMPONENT_SPLIT_REQUEST": True,
}
# =============================================================================
# External Integrations
# =============================================================================
# Anthropic/Claude API
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
# Encryption key for sensitive data (base64 encoded 32-byte key)
FRIDAY_ENCRYPTION_KEY = os.environ.get("FRIDAY_ENCRYPTION_KEY", "")
# GitHub webhook secret
GITHUB_WEBHOOK_SECRET = os.environ.get("FRIDAY_GITHUB_WEBHOOK_SECRET", "")
# =============================================================================
# Logging
# =============================================================================
LOGGING = {
 "version": 1,
 "disable_existing_loggers": False,
 "formatters": {
 "verbose": {
 "format": "{levelname} {asctime} {module} {message}",
 "style": "{",
 },
 },
 "handlers": {
 "console": {
 "class": "logging.StreamHandler",
 "formatter": "verbose",
 },
 },
 "root": {
 "handlers": ["console"],
 "level": "INFO",
 },
 "loggers": {
 "django": {
 "handlers": ["console"],
 "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
 "propagate": False,
 },
 "friday": {
 "handlers": ["console"],
 "level": "DEBUG" if DEBUG else "INFO",
 "propagate": False,
 },
 },
}
