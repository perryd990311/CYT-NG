#!/bin/sh
set -e

CERT_DIR="/etc/nginx/certs"
CERT_FILE="$CERT_DIR/server.crt"
KEY_FILE="$CERT_DIR/server.key"

# Generate self-signed certificate if none provided
if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
    echo "No TLS certificate found — generating self-signed certificate..."
    mkdir -p "$CERT_DIR"
    openssl req -x509 -nodes -days 365 \
        -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
        -keyout "$KEY_FILE" \
        -out "$CERT_FILE" \
        -subj "/C=US/ST=Local/L=Local/O=CYT-NG/CN=cyt-ng.local"
    echo "Self-signed certificate generated."
fi

# Start Nginx
exec nginx -g "daemon off;"
