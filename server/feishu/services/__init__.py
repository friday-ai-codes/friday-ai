"""feishu services 包 —— 飞书域服务（身份映射等）。

re-export ``resolve_feishu_user`` / ``bind_feishu_user``（飞书人员↔Friday 用户单一解析/写入
入口，IDENT-01）。
"""

from feishu.services.identity import bind_feishu_user, resolve_feishu_user

__all__ = ["resolve_feishu_user", "bind_feishu_user"]
