# CYT-NG Web Application
# Target: Synology DS218+ (x86_64, Docker 20.10+)
#
# Requires cyt-base:latest to exist in the local Docker image store.
# Build base once:  docker build -f docker/Dockerfile.base -t cyt-base:latest .
# Rebuild base only when requirements.txt changes.

FROM cyt-base:latest

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Path prefix: "repo/" on NAS (context is parent dir), empty in CI (context is repo root)
ARG REPO_PREFIX=repo/

# Copy application code
COPY ${REPO_PREFIX}cyt/ cyt/
COPY ${REPO_PREFIX}web/ web/
COPY ${REPO_PREFIX}sensor/kismet_sync.sh sensor/kismet_sync.sh
COPY ${REPO_PREFIX}config.json .
COPY ${REPO_PREFIX}ignore_lists/ ignore_lists/

# Entrypoint
COPY ${REPO_PREFIX}docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Data directories
RUN mkdir -p /data/cyt /data/kismet /data/logs /data/reports /data/kml && \
    chown -R cyt:cyt /app /data

USER cyt

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
