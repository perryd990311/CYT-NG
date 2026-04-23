# CYT-NG Web Application
# Target: Synology DS218+ (x86_64, Docker 20.10+)
#
# Requires cyt-base:latest to exist in the local Docker image store.
# Build base once:  docker build -f docker/Dockerfile.base -t cyt-base:latest .
# Rebuild base only when requirements.txt changes.

FROM cyt-base:latest

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy application code
COPY repo/cyt/ cyt/
COPY repo/web/ web/
COPY repo/sensor/kismet_sync.sh sensor/kismet_sync.sh
COPY repo/config.json .
COPY repo/ignore_lists/ ignore_lists/

# Entrypoint
COPY repo/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Data directories
RUN mkdir -p /data/cyt /data/kismet /data/logs /data/reports /data/kml && \
    chown -R cyt:cyt /app /data

USER cyt

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
