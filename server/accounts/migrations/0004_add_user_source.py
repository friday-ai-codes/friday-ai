"""为 User 增加 source 字段，标记账号来源渠道。"""
from django.db import migrations, models
class Migration(migrations.Migration):
 dependencies = [
 ("accounts", "0003_add_invitation"),
 ]
 operations = [
 migrations.AddField(
 model_name="user",
 name="source",
 field=models.CharField(
 choices=[
 ("feishu", "飞书"),
 ("google", "Google"),
 ("github", "GitHub"),
 ("oidc_other", "SSO"),
 ("invitation", "邀请"),
 ("admin", "管理员"),
 ("system", "系统"),
 ],
 default="admin",
 help_text="标记账号从哪个渠道进入系统（飞书/Google/GitHub/SSO/邀请/管理员/系统）",
 max_length=20,
 verbose_name="用户来源",
 ),
 ),
 ]
