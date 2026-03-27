"""accounts App 冒烟测试。"""
import pytest
from django.contrib.auth import get_user_model
User = get_user_model
@pytest.mark.django_db
class TestUserModel:
 """User 模型创建与查询。"""
 def test_create_user(self):
 user = User.objects.create_user(
 username="smokeuser",
 email="smoke@example.com",
 password="testpass123",
 )
 assert User.objects.filter(pk=user.pk).exists
 assert user.username == "smokeuser"
