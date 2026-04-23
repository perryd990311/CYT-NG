# CYT-NG Web Application
# Target: Synology DS218+ (x86_64, Docker 20.10+)
FROM python:3.12-bookworm AS base

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create non-root user (no compiler install needed — bookworm ships gcc/libssl)
RUN groupadd -r cyt && useradd -r -g cyt -d /app -s /sbin/nologin cyt

WORKDIR /app

# Install Python dependencies
COPY repo/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY repo/cyt/ cyt/
COPY repo/web/ web/
COPY repo/sensor/kismet_sync.sh sensor/kismet_sync.sh
COPY repo/config.json .
COPY repo/ignore_lists/ ignore_lists/

# Copy entrypoint and set permissions
COPY repo/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create data directories
RUN mkdir -p /data/cyt /data/kismet /data/logs /data/reports /data/kml && \
    chown -R cyt:cyt /app /data

USER cyt

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
