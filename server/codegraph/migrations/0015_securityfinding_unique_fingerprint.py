# Phase 127 review MJ-01 — 给 update_or_create 的查找键补唯一约束。
#
# 落库走 update_or_create(repository, fingerprint, mr_key)，但 0014 只建了非唯一
# 索引：并发扫描 / 任务重试会插出重复行，之后 update_or_create 抛
# MultipleObjectsReturned 被逐条吞掉，表现为静默丢 finding + 台账重复。
#
# AddConstraint 前先按 (repository, fingerprint, mr_key) 去重（保留最新一条），
# 否则历史库里已有重复时迁移会直接失败。

from django.db import migrations, models


def _dedupe_security_findings(apps, schema_editor):
    """按 (repository, fingerprint, mr_key) 去重，保留 updated_at 最新的一条。"""
    SecurityFinding = apps.get_model("codegraph", "SecurityFinding")
    seen: set[tuple[str, str, str]] = set()
    stale_ids: list[str] = []
    rows = SecurityFinding.objects.order_by("-updated_at", "-created_at").values_list(
        "id", "repository_id", "fingerprint", "mr_key"
    )
    for row_id, repository_id, fingerprint, mr_key in rows.iterator(chunk_size=2000):
        key = (str(repository_id), fingerprint or "", mr_key or "")
        if key in seen:
            stale_ids.append(row_id)
        else:
            seen.add(key)
    for start in range(0, len(stale_ids), 500):
        SecurityFinding.objects.filter(id__in=stale_ids[start : start + 500]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("codegraph", "0014_securityfinding"),
    ]

    operations = [
        migrations.RunPython(
            _dedupe_security_findings,
            migrations.RunPython.noop,
            elidable=True,
        ),
        migrations.AddConstraint(
            model_name="securityfinding",
            constraint=models.UniqueConstraint(
                fields=("repository", "fingerprint", "mr_key"),
                name="uniq_security_finding_repo_fp_mr",
            ),
        ),
    ]
