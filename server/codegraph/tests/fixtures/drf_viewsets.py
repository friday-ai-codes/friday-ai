"""DRF ViewSet fixture.
Covers: ModelViewSet with default actions + @action decorated custom actions.
"""
from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from django.contrib.auth.models import User
from .serializers import UserSerializer
class UserViewSet(ModelViewSet):
 """CRUD operations for User model."""
 queryset = User.objects.all
 serializer_class = UserSerializer
 @action(detail=True, methods=["post"])
 def activate(self, request, pk=None):
 """Custom action: activate a user."""
 user = self.get_object
 user.is_active = True
 user.save
 return Response({"status": "activated"})
 @action(detail=False, methods=["get"])
 def recent(self, request):
 """Custom action: list recent users."""
 recent_users = self.get_queryset.order_by("-date_joined")[:10]
 serializer = self.get_serializer(recent_users, many=True)
 return Response(serializer.data)
