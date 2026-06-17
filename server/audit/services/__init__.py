"""audit service 层：审计写入入口、脱敏与 action taxonomy。

curated 不强制 re-export 全部子模块——``AuditService`` 单一写入入口为主消费面，
``taxonomy`` / ``redaction`` 按需显式 import（避免无意暴露模块私有脱敏内部）。
"""
