#!/bin/sh
set -e

echo "CYT-NG starting..."

# Run Gunicorn with eventlet worker for WebSocket support
exec gunicorn \
    --worker-class eventlet \
    --workers 1 \
    --bind 0.0.0.0:8000 \
    --timeout 120 \
    --graceful-timeout 30 \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    "web.app:create_app()"
