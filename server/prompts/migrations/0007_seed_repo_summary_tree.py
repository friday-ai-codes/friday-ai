"""repo.summary_generator prompt 升级为层级能力树版本（PageIndex 化）。

沿用 0003_seed_repo_summary.py 的幂等 upsert 模式：
- active_version.body 与新 body 字节级相等 → skip
- 不同 → append_version 并切换 active_version
"""
from __future__ import annotations

from typing import Any

from django.db import migrations
from django.db.models import Max

SEED_SLUG = "repo.summary_generator"

REPO_SUMMARY_TREE_PROMPT_BODY = """\
你是一个仓库分析助手。你的任务是阅读仓库源码并生成「层级能力树」结构的仓库描述，\
让检索系统能按「子应用 → 模块 → 能力」逐层定位职责。

## 约束

- **只读操作**：你只能读取文件，不能写入、删除或修改任何文件
- **禁止 Git 写操作**：不能执行 git commit、git push 等写操作
- **禁止网络请求**：不能发起 HTTP 请求或访问外部服务

## 分析步骤

1. 阅读 README.md（如果存在）
2. 阅读包管理器文件：package.json / pyproject.toml / go.mod / Cargo.toml / pom.xml 等
3. 查看前 2-3 层目录结构，识别模块边界
4. 逐个主要模块采样阅读核心源文件（入口、路由、模型），归纳其承担的业务能力

## 能力树构建规则（核心要求）

输出的 tree 是扁平节点列表，每个节点通过 parent_id 指向父节点（顶层节点 parent_id=null）。

各层切分原则：

- **sub_app（仅 monorepo）**：若上文提供了「Monorepo 子项目清单」，第一层必须严格以\
该清单为骨架，一个子项目一个 sub_app 节点，禁止合并/遗漏/发明；若无清单但你从目录结构\
（如 apps/*、packages/*、go.work、多服务目录）判断出仓库是 monorepo，也按子应用建第一层。
- **module**：代码中真实存在的组织边界（Django app / Go package / 前端 feature 目录），\
每个节点的 paths 必须指向真实存在的目录，禁止发明代码中不存在的"逻辑模块"。
- **capability**：叶子层，粒度 =「一条需求能描述清楚的功能点」（如"消息撤回"、\
"角色批量授权"）。节点名用业务语言，要能出现在一份 PRD 里；这一层是检索命中的主力，\
keywords 写用户/产品会用的业务词。

硬性约束：

- 树深不超过 4 层；总节点数不超过 80
- 每层子节点数控制在 3~15 个，过多则合并归纳
- 每个节点的 summary 用一句中文说清"这块支撑什么业务动作"
- paths 用仓库根目录的相对路径，必须真实存在

## 语义分面（如 prompt 提供了受控词表）

若上文提供了「分面词表」，为仓库整体打 facets 标签：只能从词表中选值，\
选不出的维度填 "未分类"，禁止自由发挥。

## 其他字段

- overview：一段简洁的项目总体描述（中文）
- tech_stack：主要技术栈列表（保留英文技术名称）
- entry_points / build_commands / testing_commands / conventions：按实际情况填写
- 信息不足的字段返回空数组 [] 或空字符串 ""
"""


def forwards(apps: Any, schema_editor: Any) -> None:
    """升级 repo.summary_generator 为能力树版本（幂等 upsert）。"""
    Prompt = apps.get_model("prompts", "Prompt")
    PromptVersion = apps.get_model("prompts", "PromptVersion")

    prompt, created = Prompt.objects.get_or_create(
        slug=SEED_SLUG,
        scope="system",
        project=None,
        defaults={
            "category": "repo_analysis",
            "title": "仓库智能描述生成",
            "description": "分析仓库源码并生成层级能力树描述（PageIndex 化）",
            "is_builtin": True,
        },
    )

    if created:
        version = PromptVersion.objects.create(
            prompt=prompt,
            version=1,
            body=REPO_SUMMARY_TREE_PROMPT_BODY,
            variables_schema={},
            change_note="repo index tree initial seed",
        )
        prompt.active_version = version
        prompt.save(update_fields=["active_version", "updated_at"])
        return

    active = prompt.active_version
    if active is not None and active.body == REPO_SUMMARY_TREE_PROMPT_BODY:
        return  # 幂等 skip
    max_v = prompt.versions.aggregate(Max("version"))["version__max"] or 0
    new_version = PromptVersion.objects.create(
        prompt=prompt,
        version=max_v + 1,
        body=REPO_SUMMARY_TREE_PROMPT_BODY,
        variables_schema={},
        change_note="upgrade to hierarchical capability tree (PageIndex)",
    )
    prompt.active_version = new_version
    prompt.save(update_fields=["active_version", "updated_at"])


def reverse(apps: Any, schema_editor: Any) -> None:
    """回滚：不删 Prompt（0003 仍依赖），仅为 noop。

    版本化 prompt 的回滚语义是切回旧 active_version，由运维手工处理；
    自动回滚删除会连带删掉 0003 的种子数据。
    """


class Migration(migrations.Migration):
    dependencies = [
        ("prompts", "0006_intent_priority_resync"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse),
    ]
