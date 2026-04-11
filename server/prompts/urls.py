"""Prompt URL 配置。挂载在 /api/prompts/ 下（见 server/friday/urls.py）。
所有路径以 `/` 结尾（developer-notes.md 硬性要求）。
"""
from __future__ import annotations
from django.urls import path
from prompts.views import (
 PromptActivateVersionView,
 PromptDetailView,
 PromptListView,
 PromptRenderPreviewView,
 PromptVersionDiffView,
 PromptVersionListView,
)
urlpatterns = [
 path("", PromptListView.as_view, name="prompt-list"),
 path(
 "<uuid:prompt_id>/",
 PromptDetailView.as_view,
 name="prompt-detail",
 ),
 path(
 "<uuid:prompt_id>/preview/",
 PromptRenderPreviewView.as_view,
 name="prompt-preview",
 ),
 path(
 "<uuid:prompt_id>/versions/",
 PromptVersionListView.as_view,
 name="prompt-versions",
 ),
 path(
 "<uuid:prompt_id>/versions/<int:v1_num>/diff/<int:v2_num>/",
 PromptVersionDiffView.as_view,
 name="prompt-version-diff",
 ),
 path(
 "<uuid:prompt_id>/activate/<uuid:version_id>/",
 PromptActivateVersionView.as_view,
 name="prompt-activate",
 ),
]
