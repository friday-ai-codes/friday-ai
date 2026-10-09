from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("codegraph", "0015_securityfinding_unique_fingerprint")]

    operations = [
        migrations.RenameIndex(
            model_name="processtrace",
            old_name="codegraph_p_reposit_proc_br_idx",
            new_name="cg_proc_repo_branch_idx",
        ),
        migrations.RenameIndex(
            model_name="symbolcommunity",
            old_name="codegraph_s_reposit_comm_br_idx",
            new_name="cg_comm_repo_branch_idx",
        ),
        migrations.RenameIndex(
            model_name="symbolcommunity",
            old_name="codegraph_s_reposit_comm_fp_idx",
            new_name="cg_comm_repo_fingerprint_idx",
        ),
    ]
