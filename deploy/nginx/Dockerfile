# nginx with the site config baked in, so the production server needs no bind mounts.
FROM nginx:1.30-alpine

RUN rm /etc/nginx/conf.d/default.conf
COPY default.conf /etc/nginx/conf.d/default.conf
# .inc (not .conf) so nginx's `include conf.d/*.conf` doesn't load it at the http level.
COPY proxy_params.inc /etc/nginx/conf.d/proxy_params.inc

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/nginx-health || exit 1
