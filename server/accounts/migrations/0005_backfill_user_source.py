"""回填存量 User 的 source 字段。
推断规则（按优先级）：
1. 有 OIDCIdentity → 取关联 OIDCProvider.kind 映射到对应 source
2. 有已接受的 Invitation → invitation
3. 最早创建的 superuser（系统初始化超管）→ system
4. 其余 → admin
"""
from django.db import migrations
KIND_TO_SOURCE = {
 "feishu": "feishu",
 "google": "google",
 "github": "github",
 "other": "oidc_other",
}
def forwards(apps, schema_editor):
 User = apps.get_model("accounts", "User")
 Invitation = apps.get_model("accounts", "Invitation")
 OIDCIdentity = apps.get_model("identity", "OIDCIdentity")
 oidc_user_kinds: dict[str, str] = {}
 for identity in OIDCIdentity.objects.select_related("provider").all:
 if str(identity.user_id) in oidc_user_kinds:
 continue
 oidc_user_kinds[str(identity.user_id)] = identity.provider.kind
 invited_user_emails: set[str] = set(
 Invitation.objects.exclude(accepted_at__isnull=True)
 .exclude(email="")
 .values_list("email", flat=True)
 )
 earliest_superuser = (
 User.objects.filter(is_superuser=True).order_by("created_at").first
 )
 earliest_superuser_id = (
 str(earliest_superuser.id) if earliest_superuser else None
 )
 for user in User.objects.all:
 kind = oidc_user_kinds.get(str(user.id))
 if kind is not None:
 user.source = KIND_TO_SOURCE.get(kind, "oidc_other")
 elif user.email and user.email in invited_user_emails:
 user.source = "invitation"
 elif str(user.id) == earliest_superuser_id:
 user.source = "system"
 else:
 user.source = "admin"
 user.save(update_fields=["source"])
def backwards(apps, schema_editor):
 """回滚时不重置 source（无需精确还原，字段会随表回退一并删除）。"""
 return None
class Migration(migrations.Migration):
 dependencies = [
 ("accounts", "0004_add_user_source"),
 ("identity", "0002_add_provider_kind"),
 ]
 operations = [
 migrations.RunPython(forwards, backwards),
 ]
