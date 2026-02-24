.PHONY: dev dev-server dev-web install install-server install-web
SESSION:= friday-ai
# 一键启动前后端（tmux 分屏，支持鼠标滚动查看历史日志）
dev:
	@if tmux has-session -t $(SESSION) 2>/dev/null; then \
 echo "会话 $(SESSION) 已存在，正在连接..."; \
 tmux attach -t $(SESSION); \
	else \
 tmux new-session -d -s $(SESSION) -n dev \; \
 set-option -t $(SESSION) mouse on \; \
 send-keys -t $(SESSION) 'cd server' Enter \; \
 send-keys -t $(SESSION) 'uv run uvicorn friday.asgi:application --reload --host 0.0.0.0 --port 8080' Enter \; \
 split-window -h -t $(SESSION) \; \
 send-keys -t $(SESSION) 'cd web' Enter \; \
 send-keys -t $(SESSION) 'pnpm dev' Enter \; \
 attach -t $(SESSION); \
	fi
dev-server:
	cd server && uv run uvicorn friday.asgi:application --reload --host 0.0.0.0 --port 8080
dev-web:
	cd web && pnpm dev
# 安装依赖
install: install-server install-web
install-server:
	cd server && uv sync
install-web:
	cd web && pnpm install
