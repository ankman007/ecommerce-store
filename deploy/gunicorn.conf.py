"""Gunicorn settings for production (``gunicorn --config deploy/gunicorn.conf.py core.wsgi:application``).

Every value can be tuned with an environment variable (Dokploy Environment tab) without rebuilding the image.
"""

import multiprocessing
import os


def _int(name, default):
    value = os.getenv(name, "").strip()
    return int(value) if value else default


bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")

# gunicorn 26 creates a control socket in the working directory by default; /app is
# read-only for the non-root user, so keep it in /tmp.
control_socket = os.getenv("GUNICORN_CONTROL_SOCKET", "/tmp/gunicorn.ctl")

# WEB_CONCURRENCY is the conventional knob; default to 2 x CPUs + 1, capped so a big host
# doesn't spawn dozens of workers that each hold a DB connection.
workers = _int("WEB_CONCURRENCY", min(multiprocessing.cpu_count() * 2 + 1, 8))
threads = _int("GUNICORN_THREADS", 1)
worker_class = "gthread" if threads > 1 else "sync"

# Stripe and SMTP calls happen in-request on some views, so allow a generous timeout.
timeout = _int("GUNICORN_TIMEOUT", 60)
graceful_timeout = _int("GUNICORN_GRACEFUL_TIMEOUT", 30)
keepalive = _int("GUNICORN_KEEPALIVE", 5)

# Recycle workers periodically to contain slow memory leaks; jitter avoids all restarting at once.
max_requests = _int("GUNICORN_MAX_REQUESTS", 1000)
max_requests_jitter = _int("GUNICORN_MAX_REQUESTS_JITTER", 100)

# Logs go to stdout/stderr so `docker compose logs` collects them.
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%({x-forwarded-for}i)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)sus'

# Gunicorn is only reachable through nginx on the private compose network (its port is not
# published), so trust X-Forwarded-* from any peer there. Narrow this if the port is ever exposed.
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "*")
proxy_allow_ips = forwarded_allow_ips

# /tmp in the slim image is disk-backed; /dev/shm keeps the worker heartbeat off the disk.
worker_tmp_dir = "/dev/shm"
