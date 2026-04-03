#!/bin/sh
set -e
# 配置 XDG 目录（nobody 用户无默认 home）
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-/data/.config}"
export XDG_DATA_HOME="${XDG_DATA_HOME:-/data/.local/share}"
# 等待 server 就绪
echo "等待 server 就绪..."
retries=0
max_retries=60
until wget -q --spider "${FRIDAY_RUNNER_URL}/health" 2>/dev/null; do
 retries=$((retries + 1))
 if [ "$retries" -ge "$max_retries" ]; then
 echo "错误: server 连接超时（${max_retries} 次重试）"
 exit 1
 fi
 echo "等待 server 就绪... (${retries}/${max_retries})"
 sleep 2
done
echo "server 已就绪"
# 检查是否已注册（容器重启时跳过注册）
if [ ! -f "${XDG_CONFIG_HOME}/friday-runner/config.toml" ]; then
 echo "开始注册 Runner..."
 /friday-runner register \
 --url "${FRIDAY_RUNNER_URL}" \
 --token "${FRIDAY_RUNNER_TOKEN}" \
 --name "${FRIDAY_RUNNER_NAME:-compose-runner}"
 echo "注册完成"
else
 echo "Runner 已注册，跳过注册步骤"
fi
echo "启动 Runner..."
exec /friday-runner run
