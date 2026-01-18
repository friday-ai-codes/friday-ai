# Friday Task - AI-powered task executor for development automation
#
# 支持两种运行模式：
# 1. 容器模式 - 由 server scheduler 启动
# 2. 命令行模式 - 直接被 Claude Code 或用户调用
#
# 使用方式：
# python -m friday_task plan --git-url xxx --description "xxx"
# python -m friday_task exec --git-url xxx --description "xxx"
__version__ = "0.1.0"
