"""API Resolver 配置层 —— settings.API_DETECTOR_CONFIG + .friday/config.yaml 覆盖。
per: 支持仓库级 .friday/config.yaml 覆盖 force_helpers/exclude_helpers/
base_url_patterns 三个维度。如文件不存在则全使用 settings 默认值。
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any
import structlog
logger = structlog.get_logger(__name__)
def get_api_detector_config(repo_root: str | None = None) -> dict[str, Any]:
 """获取合并后的 API 检测配置（settings + .friday/config.yaml）。
 优先级：.friday/config.yaml（追加）> settings.API_DETECTOR_CONFIG（基础默认）
 Args:
 repo_root: 仓库根路径（用于读取 .friday/config.yaml）
 Returns:
 dict，含 _compiled_base_patterns（预编译 Pattern 列表）
 """
 from django.conf import settings
 base: dict[str, Any] = dict(getattr(settings, "API_DETECTOR_CONFIG", {}))
 if repo_root:
 friday_cfg = _load_friday_config(repo_root)
 resolver_cfg = friday_cfg.get("api_resolver", {})
 if resolver_cfg.get("force_helpers"):
 base.setdefault("force_helpers", )
 base["force_helpers"] = list(base["force_helpers"]) + list(
 resolver_cfg["force_helpers"]
 )
 if resolver_cfg.get("exclude_helpers"):
 base.setdefault("exclude_helpers", )
 base["exclude_helpers"] = list(base["exclude_helpers"]) + list(
 resolver_cfg["exclude_helpers"]
 )
 if resolver_cfg.get("base_url_patterns"):
 base.setdefault("base_url_patterns", )
 base["base_url_patterns"] = list(base["base_url_patterns"]) + list(
 resolver_cfg["base_url_patterns"]
 )
 # 预编译 base URL patterns（避免重复编译）
 base["_compiled_base_patterns"] = [
 re.compile(p) for p in base.get("base_url_patterns", )
 ]
 return base
def _load_friday_config(repo_root: str) -> dict[str, Any]:
 """读取 .friday/config.yaml，不存在或解析失败时返回 {}。
 Args:
 repo_root: 仓库根路径
 Returns:
 解析后的 yaml dict，失败时为 {}
 """
 config_path = Path(repo_root) / ".friday" / "config.yaml"
 if not config_path.exists:
 return {}
 try:
 import yaml # type: ignore[import-untyped]
 with open(config_path, encoding="utf-8") as f:
 result: dict[str, Any] = yaml.safe_load(f) or {}
 logger.info(
 "api_resolver_config_loaded",
 path=str(config_path),
 keys=list(result.keys),
 )
 return result
 except Exception as e:
 logger.warning(
 "api_resolver_config_load_failed",
 path=str(config_path),
 error=str(e),
 )
 return {}
def strip_base_url(url: str, config: dict[str, Any]) -> str:
 """从 URL 模板字符串中剥除 base URL 模板变量，返回路径 pattern。
 例：
 "${configGlobal.api}/api/user/info" → "/api/user/info"
 "${import.meta.env.VITE_API_URL}/health" → "/health"
 Args:
 url: 原始 URL 字符串（可能含 ${...} 模板表达式）
 config: 已合并的 config dict（含 _compiled_base_patterns）
 Returns:
 剥除后的 URL 路径（str）
 """
 result = url
 for pattern in config.get("_compiled_base_patterns", ):
 result = pattern.sub("", result)
 return result.strip
__all__ = ["get_api_detector_config", "strip_base_url"]
