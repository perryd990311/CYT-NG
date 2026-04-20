# CYT-NG Web Application
# Target: Synology DS218+ (x86_64, Docker 20.10+)
FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps for cryptography + bcrypt (compiled wheels)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
        libssl-dev && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r cyt && useradd -r -g cyt -d /app -s /sbin/nologin cyt

WORKDIR /app

# Install Python deps first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY cyt/ cyt/
COPY web/ web/
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
