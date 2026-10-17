# Production deployment

The production stack runs in Docker Compose on one Linux server (`docker-compose.prod.yml`):

| Service       | What it does                                                                   |
|---------------|--------------------------------------------------------------------------------|
| `migrate`     | One-off: `check_env`, `check --deploy`, then `migrate`. Everything else waits for it. |
| `web`         | Gunicorn (`deploy/gunicorn.conf.py`), not published to the host                |
| `celery`      | Celery worker (order emails, Stripe follow-ups)                                |
| `celery-beat` | Periodic jobs (`expire_stale_checkouts` every 15 minutes). Run exactly one.     |
| `nginx`       | Reverse proxy on port 80; serves `/media/` from the shared volume              |
| `db`          | MySQL 8.4, data in the `mysql_data` volume                                     |
| `redis`       | Celery broker, append-only file in the `redis_data` volume                     |
| `flower`      | Optional (`--profile monitoring`), bound to `127.0.0.1` only                   |

Code and the nginx config are baked into images; nothing from the server's filesystem is mounted
except named volumes. The app image runs as the unprivileged `app` user (UID 1000).

Images are built by GitHub Actions and pushed to GitHub Container Registry:

- `ghcr.io/<owner>/<repo>:sha-<commit>` (app: web, celery, beat, migrate)
- `ghcr.io/<owner>/<repo>-nginx:sha-<commit>`

In this document `shop.example.com` stands for your domain.

## 1. Server prerequisites

- A Linux host with Docker Engine 24+ and the Compose plugin v2.24+ (`docker compose version`).
- DNS `A`/`AAAA` records for your domain pointing at the server.
- Firewall: allow 22 and 80/443 only. MySQL, Redis and gunicorn are never published.
- A deploy user that can run Docker (in the `docker` group) and log in with an SSH key.
- A directory for the stack, e.g. `/opt/ecommerce-store`, owned by the deploy user.

```bash
sudo mkdir -p /opt/ecommerce-store && sudo chown deploy:deploy /opt/ecommerce-store
```

## 2. `.env.prod`

Copy `.env.prod.example` to `/opt/ecommerce-store/.env.prod`, fill in every value and lock it down:

```bash
chmod 600 /opt/ecommerce-store/.env.prod
```

- `SECRET_KEY`: `python3 -c "import secrets; print(secrets.token_urlsafe(64))"`
- `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS`: your real domains (`https://` origins).
- `DB_*`: they also create the MySQL database and user on the first start. `DB_HOST=db`.
- `STRIPE_*`: live keys and the webhook signing secret from step 6.
- `EMAIL_*`, `RECIPIENT_EMAIL`: SMTP account (Gmail app password) and the shop's inbox.
- `WEB_CONCURRENCY`: gunicorn workers, roughly 2 x CPU cores + 1.

`.env.prod` is git-ignored and never baked into an image. Compose reads it twice: `--env-file`
for `${...}` interpolation in the compose file, and `env_file:` for the containers.

Every command below runs in `/opt/ecommerce-store`. To keep them short:

```bash
alias dc='docker compose --env-file .env.prod -f docker-compose.prod.yml'
```

### Validate the environment

`manage.py check_env` reports missing or unsafe settings by name, without printing secret values,
and exits non-zero on errors (`--fail-on-warning` also fails on warnings). The `migrate` service runs
it before every migration, so a broken `.env.prod` stops the deploy before anything restarts.
To run it on its own:

```bash
dc run --rm migrate python manage.py check_env
```

It checks: `SECRET_KEY` (set, not a dev or placeholder value, long enough), `DEBUG` off,
`ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` (real domains, https), database settings,
`CELERY_BROKER_URL`, Stripe keys (present, well-formed, same live/test mode; test mode is a warning),
`STRIPE_WEBHOOK_SECRET`, SMTP credentials and the secure-cookie flags.

## 3. GitHub setup (once)

In **Settings > Environments**, create `production` and add yourself as a required reviewer, so
every deploy waits for approval. Then add these to the environment (or repository):

| Kind     | Name                 | Value                                                          |
|----------|----------------------|----------------------------------------------------------------|
| Secret   | `DEPLOY_HOST`        | Server hostname or IP                                          |
| Secret   | `DEPLOY_USER`        | Deploy user, e.g. `deploy`                                     |
| Secret   | `DEPLOY_SSH_KEY`     | Private key (ed25519) whose public key is in the user's `authorized_keys` |
| Secret   | `DEPLOY_KNOWN_HOSTS` | Output of `ssh-keyscan -t ed25519 <host>`, verified against the server's fingerprint |
| Variable | `DEPLOY_PATH`        | Optional, defaults to `/opt/ecommerce-store`                   |
| Variable | `DEPLOY_PORT`        | Optional SSH port, defaults to `22`                            |

The images are pushed with the workflow's own `GITHUB_TOKEN`; the deploy job logs the server in to
GHCR with that short-lived token, pulls, and logs out again. No long-lived registry token is stored.
(Alternatively make the packages public, or `docker login ghcr.io` on the server with a PAT that
only has `read:packages`.)

## 4. Deploying

**Actions > Deploy > Run workflow** (manual only, never on push). The workflow:

1. Runs lint, system checks, the missing-migrations check and the test suite on the selected ref.
2. Builds both images and pushes them as `sha-<commit>` (and `latest`).
3. Waits for approval on the `production` environment, then over SSH:
   copies `docker-compose.prod.yml`, and runs

   ```bash
   dc pull
   dc run --rm migrate      # check_env, check --deploy, migrate
   dc up -d --remove-orphans --wait
   ```

   with `APP_IMAGE`/`NGINX_IMAGE` set to the new tag, and records them in `.deployed-images`.

If `check_env` or a migration fails, the old containers keep running and the job fails.
Recreating `web` causes a few seconds of 502s while the new container starts.

### First deploy

The first deploy is the same workflow. Afterwards create an admin account:

```bash
set -a; . ./.deployed-images; set +a      # use the deployed image tags
dc exec web python manage.py createsuperuser
```

In the admin, set **Sites** > `example.com` to your domain (allauth uses it in emails).

### Manual deploy (without Actions)

```bash
export APP_IMAGE=ghcr.io/<owner>/<repo>:sha-<commit> NGINX_IMAGE=ghcr.io/<owner>/<repo>-nginx:sha-<commit>
dc pull && dc run --rm migrate && dc up -d --wait
```

Or build on the server from a checkout: `dc build && dc run --rm migrate && dc up -d`.

## 5. TLS

The `nginx` container speaks plain HTTP. Terminate TLS in front of it and forward
`X-Forwarded-Proto: https`; nginx passes that on and Django trusts it (`SECURE_PROXY_SSL_HEADER`).
Once https works, keep `SECURE_SSL_REDIRECT=True` and raise `SECURE_HSTS_SECONDS`.

**Option A: host nginx + certbot** (simple single server)

1. In `.env.prod`: `NGINX_HTTP_BIND=127.0.0.1` and `NGINX_HTTP_PORT=8080`, then `dc up -d nginx`.
2. Install nginx and certbot on the host and add a site:

   ```nginx
   server {
       listen 80;
       server_name shop.example.com www.shop.example.com;
       location / {
           proxy_pass http://127.0.0.1:8080;
           proxy_set_header Host $host;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
           client_max_body_size 10m;
       }
   }
   ```

3. `sudo certbot --nginx -d shop.example.com -d www.shop.example.com` adds the 443 server and the
   HTTP-to-HTTPS redirect, and installs a renewal timer (`sudo certbot renew --dry-run` to test).

**Option B: managed proxy** (cloud load balancer, Cloudflare, Caddy): point it at port 80 of the
server and make sure it sets `X-Forwarded-Proto`. Restrict port 80 to the proxy's addresses.

If you instead expose the container's port 80 directly to the internet without a TLS proxy (not
recommended), replace the `map` in `deploy/nginx/default.conf` with `$scheme` so clients cannot
spoof `X-Forwarded-Proto`.

## 6. Stripe webhook

Orders are confirmed by Stripe webhooks, so this endpoint must exist before taking payments.

1. Stripe Dashboard (live mode) > **Developers > Webhooks > Add endpoint**:
   `https://shop.example.com/stripe/webhook/`
2. Events: `checkout.session.completed`, `checkout.session.async_payment_succeeded`,
   `checkout.session.async_payment_failed`, `checkout.session.expired`.
3. Copy the endpoint's signing secret into `STRIPE_WEBHOOK_SECRET` in `.env.prod`, then
   `dc up -d` to restart with it.
4. Use **Send test event** in the dashboard and check `dc logs web` for a 200.

`celery-beat` also reconciles paid orders whose webhook was missed, every 15 minutes.

## 7. Operations

```bash
dc ps                          # status and health
dc logs -f web celery          # logs (rotated: 5 x 10 MB per container)
dc exec web python manage.py shell
dc --profile monitoring up -d flower   # then: ssh -L 5555:127.0.0.1:5555 deploy@<host>
```

Set `FLOWER_BASIC_AUTH=user:password` in `.env.prod` before starting Flower.

## 8. Backups

The state lives in two volumes: `mysql_data` (database) and `media` (uploaded images).
Redis only holds queued tasks. Back up at least daily and copy the files off the server:

```bash
# Database (consistent dump without locking InnoDB tables)
dc exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -u root --single-transaction --routines "$MYSQL_DATABASE"' \
  | gzip > backup-$(date +%F).sql.gz

# Media
docker run --rm -v "$(basename "$PWD")_media:/media:ro" -v "$PWD:/backup" alpine \
  tar czf /backup/media-$(date +%F).tar.gz -C /media .
```

(The volume name is `<compose project>_media`; the project defaults to the directory name. Check with
`docker volume ls`.) Restore a dump with `gunzip -c dump.sql.gz | dc exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -u root "$MYSQL_DATABASE"'`.
Test restores now and then. Never run `dc down -v`: it deletes the volumes.

## 9. Rollback

Every deploy is an immutable `sha-<commit>` image. To roll back, run **Actions > Deploy** with
`image_tag` set to the previous tag (see the earlier run's log, or `.deploy-history` on the server). That
skips the build and redeploys that tag with its own commit's compose file.

Migrations are not reversed automatically. A rollback across a migration that removed or renamed
columns needs a manual `dc run --rm migrate python manage.py migrate <app> <previous_migration>`
(with the newer image) first, or a restore from backup. Prefer backward-compatible migrations
(add columns first, remove them a release later) so the previous image keeps working.

On the server without Actions:

```bash
export APP_IMAGE=ghcr.io/<owner>/<repo>:sha-<previous> NGINX_IMAGE=ghcr.io/<owner>/<repo>-nginx:sha-<previous>
dc pull && dc up -d --wait
```

## Local development and the non-root image

`docker-compose.yml` (development) uses the same image with the source bind-mounted at `/app`. The
container runs as UID 1000, so it needs write access to `./media` on the host:

- Docker Desktop (Windows/macOS): works as is.
- Linux: works if your user is UID 1000 (`id -u`). Otherwise run `mkdir -p media && chmod 777 media`,
  or rebuild with your UID: `docker compose build --build-arg APP_UID=$(id -u) --build-arg APP_GID=$(id -g)`.

To try the production stack locally without touching the dev stack, use another project name and
port, e.g. `NGINX_HTTP_BIND=127.0.0.1 NGINX_HTTP_PORT=8095` in a throwaway env file:

```bash
docker compose -p ecommerce-prodtest --env-file .env.prodtest -f docker-compose.prod.yml up -d --build --wait
# (set ENV_FILE=.env.prodtest too, so the containers read the same file)
docker compose -p ecommerce-prodtest --env-file .env.prodtest -f docker-compose.prod.yml down -v
```
