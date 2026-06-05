"""
URL configuration for friday project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

# API routes (under /api prefix)
api_patterns = [
    # Authentication (accounts app)
    path("auth/", include("accounts.urls")),
    # Spaces
    path("spaces/", include("projects.urls")),
    # Repositories
    path("repositories/", include("repositories.urls")),
    # Feishu integration (webhook + logs)
    path("feishu/", include("feishu.urls")),
    # System settings
    path("settings/", include("system.urls")),
    # System-level health and status
    path("system/", include("system.urls_system")),
    # initial implementation contract：Provider 凭证（仅 test-connection；CRUD 归 initial implementation）
    path("providers/", include("system.urls_providers")),
    # OIDC authentication
    path("oidc/", include("identity.urls")),
    # Chat (LLM conversation)
    path("chat/", include("chat.urls")),
    # Prompts (v19.0 initial implementation 统一提示词管理)
    path("prompts/", include("prompts.urls")),
    # Workflows
    path("", include("workflows.urls")),
    # SubAgent integration
    path("subagent/", include("subagent.urls")),
    # Container callbacks (ContainerCallbackView)
    path("containers/", include("subagent.api.urls")),
    # Runners
    path("runners/", include("runners.urls")),
    # Access Tokens（initial implementation：外部 MCP/Skill 统一鉴权凭证）
    path("access-tokens/", include("access_tokens.urls")),
    # MCP read tools（initial implementation：外部仓库智能只读工具）
    path("mcp/", include("mcp_tools.urls")),
    # Agent tools API
    path("agents/", include("agents.urls")),
    # API Documentation
    path("schema", SpectacularAPIView.as_view(), name="schema"),
    path("docs", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("redoc", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

urlpatterns = [
    # All API endpoints under /api
    path("api/", include(api_patterns)),
    # Galaxy API（initial implementation/04/05）：与 playground 并列
    path("api/codegraph/galaxy/", include("codegraph.galaxy.urls")),
    # codegraph Playground（initial implementation contract）：与 /api/ 并列，裸前缀让 admin 直接访问
    path("api/codegraph/", include("codegraph.playground_urls")),
    # OpenAI 协议兼容层（contract）：与 /api/ 并列，裸前缀让 OpenAI SDK 直接接入
    path("v1/", include("compat.urls")),
    # Health check (outside /api prefix)
    path("health", include("accounts.urls_health")),
]
