# Friday Task Container
# This container runs individual AI development tasks
FROM python:3.11-slim
# Install system dependencies
RUN apt-get update && apt-get install -y \
 git \
 openssh-client \
 curl \
 && rm -rf /var/lib/apt/lists/*
# Install Node.js for Claude Code CLI
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y nodejs \
 && npm install -g @anthropic-ai/claude-code
# Install uv for Python dependency management
RUN pip install uv
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