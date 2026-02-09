# Friday AI Dev Agent - Django API Service
# Stage 1: Build dependencies
FROM python:3.14-slim AS builder
# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
 gcc \
 libc-dev \
 libffi-dev \
 libpq-dev \
 default-libmysqlclient-dev \
 pkg-config \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# Copy project files
COPY . .
# Install dependencies directly to system Python (no venv)
RUN pip install uv && uv pip install --system -e .
# Stage 2: Runtime image
FROM python:3.14-slim
# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
 curl \
 libpq5 \
 default-mysql-client \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# Copy app from builder
COPY --from=builder /app /app
# Copy installed packages from builder's system Python
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
# Create data directory
RUN mkdir -p /app/data
# Expose port
EXPOSE 8000
# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
 CMD curl -f http://localhost:8000/health || exit 1
# Run the application
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py init_superuser && gunicorn friday.asgi:application --workers 2 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --access-logfile - --error-logfile - --capture-output --timeout 120"]
