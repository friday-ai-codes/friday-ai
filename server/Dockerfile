# Friday AI Dev Agent - Django API Service
# Stage 1: Build dependencies
FROM python:3.14-alpine AS builder
# Install build dependencies
RUN apk add --no-cache \
 gcc \
 musl-dev \
 libffi-dev \
 postgresql-dev \
 mariadb-dev \
 tree-sitter-dev
WORKDIR /app
# Copy project files
COPY . .
# Install dependencies directly to system Python (no venv)
RUN pip install uv && uv pip install --system -e .
# Stage 2: Runtime image
FROM python:3.14-alpine
# Install runtime dependencies only
RUN apk add --no-cache \
 curl \
 libpq \
 mariadb-connector-c
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
