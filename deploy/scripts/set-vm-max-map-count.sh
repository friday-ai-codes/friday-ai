#!/usr/bin/env bash
# 设置并持久化 vm.max_map_count，供 Qdrant 使用。
#
# 为什么需要：Qdrant 用 mmap 存储向量/索引，一仓一 collection 时 mmap 数量会撞
# 内核 vm.max_map_count 默认上限(65530)，导致 Qdrant 创建线程栈失败而 abort、
# 进入崩溃重启循环。该参数是非命名空间内核参数，docker compose 的 sysctls 无法
# 设置，必须在宿主机执行一次。
#
# 用法：
#   sudo bash deploy/scripts/set-vm-max-map-count.sh           # 默认 1048576
#   sudo bash deploy/scripts/set-vm-max-map-count.sh 262144    # 自定义值
set -euo pipefail

VALUE="${1:-1048576}"

if [[ "$EUID" -ne 0 ]]; then
  echo "请用 root / sudo 运行" >&2
  exit 1
fi

current="$(cat /proc/sys/vm/max_map_count 2>/dev/null || echo 0)"
echo "当前 vm.max_map_count=${current}，目标=${VALUE}"

sysctl -w "vm.max_map_count=${VALUE}"
echo "vm.max_map_count=${VALUE}" > /etc/sysctl.d/99-qdrant.conf

echo "已设置并持久化到 /etc/sysctl.d/99-qdrant.conf"
echo "重启 Qdrant 容器使其在新上限下重新加载：docker compose restart qdrant"
