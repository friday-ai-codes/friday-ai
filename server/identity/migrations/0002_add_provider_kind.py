"""为 OIDCProvider 增加 kind 字段，用于区分 feishu/google/github/other。"""
from django.db import migrations, models
class Migration(migrations.Migration):
 dependencies = [
 ("identity", "0001_initial"),
 ]
 operations = [
 migrations.AddField(
 model_name="oidcprovider",
 name="kind",
 field=models.CharField(
 choices=[
 ("feishu", "飞书"),
 ("google", "Google"),
 ("github", "GitHub"),
 ("other", "其他 OIDC"),
 ],
 default="other",
 help_text="用于标记用户来源，便于在用户管理页面区分飞书/Google/GitHub 等",
 max_length=20,
 verbose_name="Provider 类型",
 ),
 ),
 ]
