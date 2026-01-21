FROM python:3.14.2-slim
# Install system dependencies
RUN apt-get update && apt-get install -y \
 git \
 openssh-client \
 curl \
 gnupg \
 ca-certificates \
 && rm -rf /var/lib/apt/lists/*
# Set working directory
WORKDIR /app
# Copy project files
COPY pyproject.toml ./
COPY src/ ./src/
# Install Python dependencies directly with pip (no virtual environment)
RUN pip install --no-cache-dir -e .
# Configure Git for commits
RUN git config --global user.email "ai@friday.codes" \
 && git config --global user.name "Friday Codes AI Agent" \
 && git config --global --add safe.directory "*"
# Configure SSH
RUN mkdir -p /root/.ssh \
 && chmod 700 /root/.ssh \
 && echo "Host *\n\tStrictHostKeyChecking no\n\tUserKnownHostsFile=/dev/null" > /root/.ssh/config
# Create working directories
RUN mkdir -p /app/workspace /app/sessions
# Copy and set up entrypoint script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
# Entry point - 智能入口脚本:
# - 无参数: 容器模式 (runner.py)
# - "bash" 或 "sh": 调试模式，进入交互式 shell
# - 其他参数: CLI 模式 (friday-task)
ENTRYPOINT ["/app/entrypoint.sh"]
