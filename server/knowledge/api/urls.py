from django.urls import path

from knowledge.api.views import (
    KnowledgeEntityDetailView,
    KnowledgeRelatedView,
    KnowledgeSearchView,
    KnowledgeTimelineView,
)

urlpatterns = [
    path("search/", KnowledgeSearchView.as_view(), name="knowledge-search"),
    path("entities/<uuid:entity_id>/", KnowledgeEntityDetailView.as_view(), name="knowledge-entity-detail"),
    path("timeline/<uuid:entity_id>/", KnowledgeTimelineView.as_view(), name="knowledge-timeline"),
    path("related/<uuid:entity_id>/", KnowledgeRelatedView.as_view(), name="knowledge-related"),
]
