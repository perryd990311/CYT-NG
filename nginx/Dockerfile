FROM nginx:stable-alpine

# Upgrade all Alpine packages to pick up patched libxml2 (CVE-2025-49794, CVE-2025-49796)
RUN apk upgrade --no-cache && apk add --no-cache openssl

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 80 443

ENTRYPOINT ["/entrypoint.sh"]
