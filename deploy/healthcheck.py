"""Container healthcheck: is gunicorn answering HTTP on this container?

Sends ``GET /`` to 127.0.0.1 with a Host header Django accepts (the first entry of
ALLOWED_HOSTS), so the request runs through the whole stack including the database.
Exit 0 for any status below 500 (a redirect or 404 still means the app is up), 1 otherwise.
Standard library only, so it adds nothing to the image.
"""

import http.client
import os
import sys

PORT = int(os.getenv("HEALTHCHECK_PORT", "8000"))
PATH = os.getenv("HEALTHCHECK_PATH", "/")


def host_header():
    hosts = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]
    host = hosts[0] if hosts else "localhost"
    if host == "*":
        return "localhost"
    # ".example.com" allows example.com and its subdomains
    return host.lstrip(".")


def main():
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=8)
    try:
        # X-Forwarded-Proto mirrors what nginx sends, so SECURE_SSL_REDIRECT doesn't redirect-loop us.
        conn.request("GET", PATH, headers={"Host": host_header(), "X-Forwarded-Proto": "https"})
        status = conn.getresponse().status
    except OSError as exc:
        print(f"unhealthy: {exc}")
        return 1
    finally:
        conn.close()
    if status >= 500:
        print(f"unhealthy: HTTP {status}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
