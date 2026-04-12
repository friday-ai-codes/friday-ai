#!/bin/bash
# explore 模式 git 写操作拦截脚本（双层防御第二层 - Shell 层）
#
# 在 explore 模式下，wrapper 通过白名单机制放行只读 git 子命令，
# 拦截所有写操作并返回退出码 128。非 explore 模式下所有命令直接放行。
#
# 由 entrypoint.sh 在容器启动时将本脚本（以 "git" 符号链接）
# prepend 到 PATH，使所有 git 调用先经过此 wrapper。
#
#: Shell 层防御
REAL_GIT="/usr/bin/git"
# repo_summary 模式：等同 explore 模式的只读约束
if [ "$FRIDAY_TASK_MODE" = "repo_summary" ]; then
 FRIDAY_TASK_MODE="explore"
fi
# 非 explore 模式：直接放行所有命令
if [ "$FRIDAY_TASK_MODE" != "explore" ]; then
 exec "$REAL_GIT" "$@"
fi
# explore 模式：解析子命令（跳过 git 全局选项及其参数）
subcmd=""
skip_next=false
for arg in "$@"; do
 if $skip_next; then
 skip_next=false
 continue
 fi
 case "$arg" in
 -C|-c|--git-dir|--work-tree|--namespace)
 skip_next=true
 continue;;
 -*)
 continue;;
 *)
 subcmd="$arg"
 break;;
 esac
done
# 拦截函数：输出错误信息并返回退出码 128
block {
 echo "[Friday] Error: git ${subcmd} is forbidden in explore mode" >&2
 exit 128
}
# 白名单放行：已知的只读操作
case "$subcmd" in
 status|diff|log|show|remote|fetch|ls-files|rev-parse|describe|blame|shortlog|ls-remote|version|help|clone)
 exec "$REAL_GIT" "$@";;
esac
# branch 子命令特殊处理：-d/-D/--delete 拦截，其他放行（只读列出）
if [ "$subcmd" = "branch" ]; then
 for arg in "$@"; do
 case "$arg" in
 -d|-D|--delete)
 block;;
 esac
 done
 exec "$REAL_GIT" "$@"
fi
# checkout 子命令特殊处理：-b/-B 拦截（创建新分支），其他放行（切换已有分支）
if [ "$subcmd" = "checkout" ]; then
 for arg in "$@"; do
 case "$arg" in
 -b|-B)
 block;;
 esac
 done
 exec "$REAL_GIT" "$@"
fi
# config 子命令特殊处理：--get/--get-all/--get-regexp/--list/-l 放行，其他拦截
if [ "$subcmd" = "config" ]; then
 for arg in "$@"; do
 case "$arg" in
 --get|--get-all|--get-regexp|--list|-l)
 exec "$REAL_GIT" "$@";;
 esac
 done
 block
fi
# stash 子命令特殊处理：list/show 放行，drop/pop 拦截，其余拦截
if [ "$subcmd" = "stash" ]; then
 # 找到 stash 后面的子参数
 found_stash=false
 stash_action=""
 for arg in "$@"; do
 if $found_stash; then
 case "$arg" in
 -*)
 continue;;
 *)
 stash_action="$arg"
 break;;
 esac
 fi
 if [ "$arg" = "stash" ]; then
 found_stash=true
 fi
 done
 case "$stash_action" in
 list|show)
 exec "$REAL_GIT" "$@";;
 *)
 block;;
 esac
fi
# 默认拦截：未匹配任何白名单的子命令（安全优先 ）
block
