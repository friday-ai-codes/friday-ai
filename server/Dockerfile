# Friday AI Dev Agent - Main API Service
FROM python:3.14-slim
# Install system dependencies
RUN apt-get update && apt-get install -y \
 curl \
 && rm -rf /var/lib/apt/lists/*
# Install uv
RUN pip install uv
# Set working directory
WORKDIR /app
# Copy project files
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
# Install dependencies
RUN uv sync --frozen --no-dev
# Create data directory
RUN mkdir -p /app/data
# Expose port
EXPOSE 8000
# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
 CMD curl -f http://localhost:8000/health || exit 1
# Run the application
CMD ["uv", "run", "uvicorn", "friday.main:app", "--host", "0.0.0.0", "--port", "8000"]