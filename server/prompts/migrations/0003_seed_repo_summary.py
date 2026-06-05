"""implementation seed: repo.summary_generator prompt 入库。

决策依据（work-item.md）：
- 仿照 0002_seed_system_defaults.py 的 data migration 模式
- slug 已在 keys.py 预声明（implementation）: PromptSlugs.REPO_SUMMARY_GENERATOR
- 幂等 upsert: 已存在且 body 相等 → skip；不同 → append_version
"""
from __future__ import annotations

from typing import Any

from django.db import migrations
from django.db.models import Max

SEED_SLUG = "repo.summary_generator"

REPO_SUMMARY_PROMPT_BODY = """\
你是一个仓库分析助手。你的任务是阅读仓库源码并生成结构化的仓库描述。

## 约束

- **只读操作**：你只能读取文件，不能写入、删除或修改任何文件
- **禁止 Git 写操作**：不能执行 git commit、git push 等写操作
- **禁止网络请求**：不能发起 HTTP 请求或访问外部服务
- **输出限制**：最终 JSON 输出不超过 2000 字符

## 分析步骤

1. 阅读 README.md（如果存在）
2. 阅读包管理器文件：package.json / pyproject.toml / go.mod / Cargo.toml / pom.xml 等
3. 执行 `ls` 查看前 2 层目录结构
4. 随机采样 5-10 个核心源文件，了解代码风格和架构

## 输出格式

输出严格的 JSON（不要 markdown 代码块包裹），schema 如下：

{
  "overview": "一段简洁的项目总体描述（work-item字）",
  "tech_stack": ["主要技术栈列表，如 Python, Django, Vue.js, TypeScript"],
  "modules": [
    {"name": "模块名", "description": "模块职责描述"}
  ],
  "entry_points": ["主要入口文件路径"],
  "build_commands": ["构建命令，如 npm run build"],
  "testing_commands": ["测试命令，如 pytest"],
  "conventions": ["代码规范和约定，如 使用 TypeScript strict mode"]
}

注意：
- overview 用中文撰写
- tech_stack 保留英文技术名称
- modules 只列出主要模块（不超过 10 个）
- 如果某个字段信息不足，返回空数组 [] 或空字符串 ""
"""


def forwards(apps: Any, schema_editor: Any) -> None:
    """Seed repo.summary_generator prompt（幂等 upsert）。"""
    Prompt = apps.get_model("prompts", "Prompt")
    PromptVersion = apps.get_model("prompts", "PromptVersion")

    prompt, created = Prompt.objects.get_or_create(
        slug=SEED_SLUG,
        scope="system",
        project=None,
        defaults={
            "category": "repo_analysis",
            "title": "仓库智能描述生成",
            "description": "分析仓库源码并生成结构化 JSON 描述（implementation seed）",
            "is_builtin": True,
        },
    )

    if created:
        version = PromptVersion.objects.create(
            prompt=prompt,
            version=1,
            body=REPO_SUMMARY_PROMPT_BODY,
            variables_schema={},
            change_note="implementation initial seed",
        )
        prompt.active_version = version
        prompt.save(update_fields=["active_version", "updated_at"])
    else:
        active = prompt.active_version
        if active is not None and active.body == REPO_SUMMARY_PROMPT_BODY:
            return  # 幂等 skip（字节级相等）
        max_v = prompt.versions.aggregate(Max("version"))["version__max"] or 0
        new_version = PromptVersion.objects.create(
            prompt=prompt,
            version=max_v + 1,
            body=REPO_SUMMARY_PROMPT_BODY,
            variables_schema={},
            change_note=f"implementation seed sync (body drift from v{max_v})",
        )
        prompt.active_version = new_version
        prompt.save(update_fields=["active_version", "updated_at"])


def reverse(apps: Any, schema_editor: Any) -> None:
    """回滚：限定 is_builtin=True 的系统级条目。"""
    Prompt = apps.get_model("prompts", "Prompt")
    Prompt.objects.filter(
        slug=SEED_SLUG,
        scope="system",
        is_builtin=True,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("prompts", "0002_seed_system_defaults"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse),
    ]
