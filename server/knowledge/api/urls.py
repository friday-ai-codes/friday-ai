from django.urls import path

from knowledge.api.views import KnowledgeRelatedView, KnowledgeSearchView, KnowledgeTimelineView

urlpatterns = [
    path("search/", KnowledgeSearchView.as_view(), name="knowledge-search"),
    path("timeline/<uuid:entity_id>/", KnowledgeTimelineView.as_view(), name="knowledge-timeline"),
    path("related/<uuid:entity_id>/", KnowledgeRelatedView.as_view(), name="knowledge-related"),
]
