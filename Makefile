.PHONY: dev dev-server dev-web install install-server install-web
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
 send-keys -t $(SESSION) 'uv run uvicorn friday.asgi:application --reload --host 0.0.0.0 --port $(DEV_SERVER_PORT)' Enter \; \
 split-window -h -t $(SESSION) \; \
 pipe-pane -o -t $(SESSION):dev.0 'cat >> $(DEV_SERVER_LOG)' \; \
 pipe-pane -o -t $(SESSION):dev.1 'cat >> $(DEV_WEB_LOG)' \; \
 send-keys -t $(SESSION) 'cd web' Enter \; \
 send-keys -t $(SESSION) 'VITE_USE_POLLING=true pnpm dev --host 0.0.0.0 --port $(DEV_WEB_PORT) --strictPort' Enter \; \
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
