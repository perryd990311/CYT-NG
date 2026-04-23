# CYT-NG Web Application
# Target: Synology DS218+ (x86_64, Docker 20.10+)
FROM python:3.12-bookworm AS base

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create non-root user (no compiler install needed — bookworm ships gcc/libssl)
# Copy application code
COPY cyt/ cyt/
COPY web/ web/
COPY sensor/kismet_sync.sh sensor/kismet_sync.sh
COPY config.json .
COPY ignore_lists/ ignore_lists/

# Copy entrypoint and set permissions
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create data directories
RUN mkdir -p /data/cyt /data/kismet /data/logs /data/reports /data/kml && \
    chown -R cyt:cyt /app /data

USER cyt

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
