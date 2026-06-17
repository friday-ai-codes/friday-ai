"""audit app：操作审计横切叶子包（v0.10.0 操作审计治理）。

零业务依赖的横切 bounded context——只依赖 ``django.db`` + ``accounts.User`` 标量
软引用 + ``common.logging``，可被任意 app 无环 import emit 审计事件（per RESEARCH §1）。
"""
