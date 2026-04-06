from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid
class Migration(migrations.Migration):
 dependencies = [
 ("chat", "0003_conversation_provider_type"),
 migrations.swappable_dependency(settings.AUTH_USER_MODEL),
 ]
 operations = [
 migrations.CreateModel(
 name="ChatPushSubscription",
 fields=[
 ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
 ("endpoint", models.TextField(unique=True)),
 ("p256dh", models.CharField(max_length=255)),
 ("auth", models.CharField(max_length=255)),
 ("user_agent", models.TextField(blank=True, default="")),
 ("is_active", models.BooleanField(db_index=True, default=True)),
 ("last_used_at", models.DateTimeField(auto_now=True)),
 ("created_at", models.DateTimeField(auto_now_add=True)),
 ("updated_at", models.DateTimeField(auto_now=True)),
 (
 "user",
 models.ForeignKey(
 on_delete=django.db.models.deletion.CASCADE,
 related_name="chat_push_subscriptions",
 to=settings.AUTH_USER_MODEL,
 ),
 ),
 ],
 options={
 "db_table": "chat_push_subscriptions",
 "verbose_name": "聊天 Push 订阅",
 "verbose_name_plural": "聊天 Push 订阅",
 "indexes": [models.Index(fields=["user", "is_active"], name="chat_push_s_user_id_cd665d_idx")],
 },
 ),
 ]
