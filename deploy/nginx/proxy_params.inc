proxy_http_version 1.1;
proxy_set_header Connection "";
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $forwarded_proto;
proxy_set_header X-Forwarded-Host $host;

proxy_connect_timeout 10s;
# Slightly above gunicorn's timeout (60s) so gunicorn, not nginx, reports slow requests.
proxy_read_timeout 75s;
proxy_send_timeout 75s;

proxy_redirect off;
proxy_buffering on;
