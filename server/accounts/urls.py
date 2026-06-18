"""Accounts URL configuration."""

from django.urls import path

from .views import (
    AdminChangePasswordView,
    AdminProfileView,
    ChangePasswordView,
    ForceChangePasswordView,
    InvitationAcceptView,
    InvitationView,
    LoginView,
    LogoutView,
    MeView,
    ProfileUpdateView,
    RefreshTokenView,
    SetupInitView,
    SetupStatusView,
    UserDetailView,
    UserListView,
    UserMembershipsView,
)

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("refresh/", RefreshTokenView.as_view(), name="refresh"),
    path("me/", MeView.as_view(), name="me"),
    path("me/profile/", ProfileUpdateView.as_view(), name="me-profile"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),
    path("force-change-password/", ForceChangePasswordView.as_view(), name="force-change-password"),
    # Admin management endpoints
    path("admin/profile/", AdminProfileView.as_view(), name="admin-profile"),
    path("admin/password/", AdminChangePasswordView.as_view(), name="admin-password"),
    # Invitation endpoints
    path("invite/", InvitationView.as_view(), name="invite"),
    path("invite/accept/", InvitationAcceptView.as_view(), name="invite-accept"),
    # System user management
    path("users/", UserListView.as_view(), name="user-list"),
    path("users/<str:user_id>/", UserDetailView.as_view(), name="user-detail"),
    path(
        "users/<str:user_id>/memberships/",
        UserMembershipsView.as_view(),
        name="user-memberships",
    ),
    # 首启向导：初始化状态（AllowAny 只读）
    path("setup/status/", SetupStatusView.as_view(), name="setup-status"),
    # 首启向导：初始化写入（fail-closed + 防重入）
    path("setup/", SetupInitView.as_view(), name="setup-init"),
]
