"""内置 8 类工件类型 seed（ARTIFACT-01，builtin=True 禁删只可禁用）。

文字类（需求文档/feature list/研发 Spec/UI 评审/埋点文档/埋点评审/复盘）``ragable=True``；
UI 稿（figma/mastergo 图形外链）``ragable=False`` 仅元数据（多模态正文 RAG 留 v2 PROJX-01）。

reverse 删除内置 8 类（key 命中且 builtin=True）——自定义类型不动。
"""

from __future__ import annotations

from django.db import migrations

# (key, name, carrier, ragable)
BUILTIN_TYPES = [
    ("requirement_doc", "需求文档", "feishu_doc", True),
    ("feature_list", "feature list", "feishu_bitable", True),
    ("dev_spec", "研发 Spec", "markdown", True),
    ("ui_design", "UI 稿", "external_link", False),
    ("ui_review", "UI 评审", "feishu_doc", True),
    ("tracking_doc", "埋点文档", "feishu_doc", True),
    ("tracking_review", "埋点评审", "feishu_doc", True),
    ("retrospective", "复盘", "feishu_doc", True),
]

_BUILTIN_KEYS = [t[0] for t in BUILTIN_TYPES]


def seed_builtin_types(apps, schema_editor):
    ArtifactType = apps.get_model("initiatives", "ArtifactType")
    for key, name, carrier, ragable in BUILTIN_TYPES:
        ArtifactType.objects.update_or_create(
            key=key,
            defaults={
                "name": name,
                "carrier": carrier,
                "ragable": ragable,
                "enabled": True,
                "builtin": True,
            },
        )


def remove_builtin_types(apps, schema_editor):
    ArtifactType = apps.get_model("initiatives", "ArtifactType")
    ArtifactType.objects.filter(key__in=_BUILTIN_KEYS, builtin=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("initiatives", "0003_artifacttype_artifact"),
    ]

    operations = [
        migrations.RunPython(seed_builtin_types, remove_builtin_types),
    ]
