"""initiatives app —— 项目聚合根 bounded context（v0.15.0 Phase 77）。

承载新聚合根 ``Project``（隶属 ``projects.Space``、关联飞书"项目跟踪"看板、含状态机）、
项目成员 ``ProjectMember``（多对多 + 身份角色）、项目↔项目轻量关联 ``ProjectRelation``，
以及唯一写入入口 ``ProjectService``（INV-6）。与组织单元 ``Space``（在 ``projects`` app）
清晰分离，避免与 ``SpaceMembership`` 混淆。
"""
