# Friday Task Container
# This container runs individual AI development tasks using claude-agent-sdk
#
# claude-agent-sdk 是 Claude Code 的 Python SDK，它底层调用 Claude Code CLI
# 因此需要安装 Node.js 和 Claude Code CLI
FROM python:3.12-slim
# Install system dependencies including Node.js (required for Claude Code CLI)
RUN apt-get update && apt-get install -y \
 git \
 openssh-client \
 curl \
 gnupg \
 ca-certificates \
 && rm -rf /var/lib/apt/lists/*
# Install Node.js 20.x (LTS) - Required for Claude Code CLI
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y nodejs \
 && rm -rf /var/lib/apt/lists/*
# Install Claude Code CLI globally
# claude-agent-sdk Python 包通过调用 @anthropic-ai/claude-code CLI 工作
RUN npm install -g @anthropic-ai/claude-code
# Set working directory
WORKDIR /app
# Copy task requirements
COPY requirements.txt .
RUN pip install -r requirements.txt
# Copy task source code
COPY src/ ./src/
# Configure Git for commits
RUN git config --global user.email "ai-agent@friday.dev" \
 && git config --global user.name "Friday AI Agent" \
 && git config --global --add safe.directory "*"
# Configure SSH
RUN mkdir -p /root/.ssh \
 && chmod 700 /root/.ssh \
 && echo "Host *\n\tStrictHostKeyChecking no\n\tUserKnownHostsFile=/dev/null" > /root/.ssh/config
# Create working directories
RUN mkdir -p /app/workspace /app/sessions
# Entry point
ENTRYPOINT ["python", "-m", "src.runner"]
