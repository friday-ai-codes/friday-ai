"""Publish a Markdown file to Feishu as a cloud document.

Usage:
    python manage.py publish_to_feishu <file_path> [--title TITLE] [--folder FOLDER_TOKEN]
    python manage.py publish_to_feishu <file_path> --project PROJECT_ID

Examples:
    # 使用系统级飞书配置
    python manage.py publish_to_feishu docs/技术原理.md --folder fldcnXXXXXX

    # 使用项目级飞书配置
    python manage.py publish_to_feishu docs/技术原理.md --project <project_uuid>

    # 自定义标题
    python manage.py publish_to_feishu docs/技术原理.md --title "Friday AI 技术原理" --folder fldcnXXXXXX
"""

import asyncio
from pathlib import Path

import structlog
from django.core.management.base import BaseCommand, CommandError

from common.encryption import decrypt_value
from services.feishu_doc import FeishuDocClient
from system.models import SettingKeys, SystemSetting

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "将 Markdown 文件发布到飞书云文档"

    def add_arguments(self, parser):
        parser.add_argument("file_path", type=str, help="Markdown 文件路径")
        parser.add_argument("--title", type=str, help="文档标题（默认使用文件名或 Markdown 一级标题）")
        parser.add_argument("--folder", type=str, help="飞书文件夹 token")
        parser.add_argument("--project", type=str, help="使用指定项目的飞书配置")

    def handle(self, *args, **options):
        file_path = Path(options["file_path"])
        if not file_path.exists():
            raise CommandError(f"文件不存在: {file_path}")

        content = file_path.read_text(encoding="utf-8")
        if not content.strip():
            raise CommandError(f"文件为空: {file_path}")

        # 提取标题
        title = options.get("title")
        if not title:
            title = self._extract_title(content, file_path)

        asyncio.run(self._publish(content, title, options))

    async def _publish(self, content: str, title: str, options: dict):
        app_id, app_secret, folder_token = await self._resolve_config(options)

        client = FeishuDocClient(app_id=app_id, app_secret=app_secret)

        self.stdout.write(f"正在创建飞书文档: {title}")
        self.stdout.write(f"目标文件夹: {folder_token}")

        result = await client.create_document(
            title=title,
            folder_token=folder_token,
            content=content,
        )

        self.stdout.write(self.style.SUCCESS("文档创建成功!"))
        self.stdout.write(f"  文档 ID: {result['document_id']}")
        self.stdout.write(f"  链接: {result['url']}")

    async def _resolve_config(self, options: dict) -> tuple[str, str, str]:
        """解析飞书配置，优先级：命令行参数 > 项目配置 > 系统配置"""
        app_id = ""
        app_secret = ""
        folder_token = options.get("folder") or ""

        project_id = options.get("project")
        if project_id:
            from projects.models import Space

            try:
                project = await Space.objects.aget(id=project_id)
            except Space.DoesNotExist:
                raise CommandError(f"项目不存在: {project_id}")

            if not project.has_feishu_im_config():
                raise CommandError(f"项目 '{project.name}' 未配置飞书 IM 应用")

            app_id = project.feishu_app_id or ""
            app_secret = decrypt_value(project.feishu_app_secret_encrypted) if project.feishu_app_secret_encrypted else ""

            if not folder_token:
                folder_token = getattr(project, "feishu_doc_folder_token", "") or ""

        # 回退到系统配置
        if not app_id:
            try:
                setting = await SystemSetting.objects.aget(key=SettingKeys.FEISHU_APP_ID)
                app_id = setting.value or ""
            except SystemSetting.DoesNotExist:
                pass

        if not app_secret:
            try:
                setting = await SystemSetting.objects.aget(key=SettingKeys.FEISHU_APP_SECRET)
                if setting.value and setting.is_encrypted:
                    app_secret = decrypt_value(setting.value)
                else:
                    app_secret = setting.value or ""
            except SystemSetting.DoesNotExist:
                pass

        if not app_id or not app_secret:
            raise CommandError(
                "未找到飞书应用配置。请通过以下方式之一配置:\n"
                "  1. --project <project_id> 使用项目级配置\n"
                "  2. 在系统设置中配置 feishu_app_id 和 feishu_app_secret"
            )

        if not folder_token:
            raise CommandError(
                "未指定目标文件夹。请通过 --folder <folder_token> 指定飞书文件夹 token。\n"
                "文件夹 token 可从飞书文档 URL 中获取。"
            )

        return app_id, app_secret, folder_token

    @staticmethod
    def _extract_title(content: str, file_path: Path) -> str:
        """从 Markdown 内容提取标题，回退到文件名"""
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("# ") and not line.startswith("## "):
                return line[2:].strip()
        return file_path.stem
