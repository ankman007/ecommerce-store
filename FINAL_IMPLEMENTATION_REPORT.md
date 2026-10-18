# Final Implementation Report — Roadmap Phases 2, 4 and 5

Work done by parallel agents in isolated git worktrees and integrated on `main` by the coordinator. All commits are local; nothing was pushed or deployed, and no live payments or refunds were made.

## Outcome

| Phase | Status |
|---|---|
| 2 — Docker and deployment | Done, merged (`07fb74e`) |
| 3 — Nepal payment gateways | **Dropped by the owner** (US store; Stripe only). The unfinished branch was discarded. |
| 4 — Store functionality | Done, merged (`d09a524`) |
| 5 — Code health | Done, merged (`2edbb1e` CKEditor removal, `ea1dedd` settings/logging/tests) |

Final validation on `main` (`ea1dedd` + docs):

| Check | Result |
|---|---|
| Test suite | 287 tests, OK (was 130) |
| Coverage (shop, users, core; excl. migrations/tests) | 99% (was 85%) |
| Ruff lint + format | clean |
| `makemigrations --check` | no changes |
| `manage.py check` | no issues (CKEditor warning gone) |
| Dev and prod Compose configs | valid |
| Secrets / real env files tracked | none |

## What changed

### Phase 4 — store functionality
- **Shipping address and phone** collected on a new `/checkout/` step before Stripe; stored as a snapshot on the order and passed to Stripe.
- **Emails:** order confirmation (sent once, also when the webhook confirms the order), shipped (with tracking number) and refunded notifications.
- **Admin:** "Mark as shipped" action, tracking number, read-only address, totals, link to the customer.
- **Catalog:** 12 per page, sort (newest, price, name), price range and in-stock filters on home, category and search.
- **Images:** lazy loading, fixed dimensions, placeholders, real alt text.
- **SEO:** per-page titles and descriptions, canonical links, Open Graph on products, `sitemap.xml`, `robots.txt`; private pages marked noindex.
- Migration `0006` (all fields nullable or defaulted; applied locally with existing orders intact).

### Phase 2 — Docker and deployment
- Image runs as non-root user `app` (UID 1000) with a health check.
- `docker-compose.prod.yml`: separate `migrate` job (runs `check_env`, `check --deploy`, then migrations) that web/worker/beat wait for; nginx serving `/media/`; gunicorn config; Redis/MySQL volumes and health checks; Flower only on localhost behind a profile.
- `python manage.py check_env`: validates production settings without printing secret values.
- Deploy workflow: **manual trigger only**, re-runs CI checks, builds images to GHCR, deploys under a GitHub `production` environment (approval possible) using secrets instead of the old hard-coded IP and root SSH.
- `docs/DEPLOYMENT.md`: server setup, `.env.prod`, first deploy, TLS, Stripe webhook registration, rollback.

### Phase 5 — code health
- **django-ckeditor removed** (CKEditor 4 is unsupported with known vulnerabilities). Descriptions are plain text; migration `0007` converts old HTML.
- **Email via `MAILERS`** (Django 6.1 deprecation); same env vars, plus optional `EMAIL_HOST/PORT/USE_TLS/TIMEOUT`, `DEFAULT_FROM_EMAIL`, and a 30 s SMTP timeout.
- **Logging:** one config for Django, loguru and Celery, level from `LOG_LEVEL`.
- **Bug fix:** two Celery settings were silently ignored because of the settings namespace.
- django-allauth 65.19.7 → 65.20.0; settings regrouped; `SITE_URL` added for email links.
- 59 regression tests.

## Integration issues found and fixed by the coordinator
- `.gitignore` conflict (agent worktrees vs env-file rules): kept both.
- Settings/requirements conflicts: kept allauth 65.20.0, removed the CKEditor lines the code-health branch still carried, dropped a duplicate `SITE_ID`.
- Under `MAILERS`, `settings.EMAIL_HOST_USER` no longer exists: `check_env` now reads `MAILERS`, order emails send from `DEFAULT_FROM_EMAIL`, tests updated.
- A regression test written before the address step now posts an address.

## Not done / needs the owner
- **Local dev images not rebuilt:** Docker Desktop failed with an internal `lease does not exist` error. The running containers still use the previous image (root user, CKEditor package installed but unused). Restart Docker Desktop, then `docker compose up -d --build`. The Stripe CLI forwarder container is currently stopped; it returns with that command.
- **Before the first production deploy:** create the GitHub `production` environment and secrets, put `.env.prod` on the server, set up TLS, register the Stripe webhook endpoint, set `SITE_URL`. See `docs/DEPLOYMENT.md`.
- Nothing has been pushed; review `git log` and push when ready.
