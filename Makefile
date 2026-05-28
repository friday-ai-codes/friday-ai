.PHONY: dev dev-server dev-web install install-server install-web build-runner build-task
TASK_IMAGE ?= friday-task:latest
SESSION:= friday-ai
DEV_WEB_PORT ?= 10240
DEV_SERVER_PORT ?= 10241
DEV_LOG_DIR ?= $(CURDIR)/.logs
DEV_SERVER_LOG ?= $(DEV_LOG_DIR)/server.log
DEV_WEB_LOG ?= $(DEV_LOG_DIR)/web.log
# 一键启动前后端（tmux 分屏，支持鼠标滚动查看历史日志）
dev:
	@if tmux has-session -t $(SESSION) 2>/dev/null; then \
 echo "会话 $(SESSION) 已存在，正在连接..."; \
 tmux attach -t $(SESSION); \
	else \
 mkdir -p $(DEV_LOG_DIR); \
 tmux new-session -d -s $(SESSION) -n dev \; \
 set-option -t $(SESSION) mouse on \; \
 send-keys -t $(SESSION) 'cd server' Enter \; \
 send-keys -t $(SESSION) 'uv run uvicorn friday.asgi:application --reload --host 0.0.0.0 --port $(DEV_SERVER_PORT) 2>&1 | tee -a $(DEV_SERVER_LOG)' Enter \; \
 split-window -h -t $(SESSION) \; \
 send-keys -t $(SESSION) 'cd web' Enter \; \
 send-keys -t $(SESSION) 'VITE_USE_POLLING=true pnpm dev --host 0.0.0.0 --port $(DEV_WEB_PORT) --strictPort 2>&1 | tee -a $(DEV_WEB_LOG)' Enter \; \
 attach -t $(SESSION); \
	fi
dev-server:
	cd server && uv run uvicorn friday.asgi:application --reload --host 0.0.0.0 --port $(DEV_SERVER_PORT)
dev-web:
	cd web && VITE_USE_POLLING=true pnpm dev --host 0.0.0.0 --port $(DEV_WEB_PORT) --strictPort
# 安装依赖
install: install-server install-web
install-server:
	cd server && uv sync
install-web:
	cd web && pnpm install
# 构建 Go Runner（二进制输出到 runner/friday-runner）
build-runner:
	$(MAKE) -C runner build
# 重新构建 Task 容器镜像（Runner 启动新 task 容器时自动用最新 latest，无需重启 runner）
# 用法：
# make build-task # 构建 friday-task:latest
# TASK_IMAGE=friday-task:v26.1 make build-task # 自定义 tag
build-task:
	@echo "构建 Task 容器镜像: $(TASK_IMAGE)"
	docker build -t $(TASK_IMAGE) ./task/
	@echo "完成。Runner 下次启动新容器时会用到最新镜像。"
