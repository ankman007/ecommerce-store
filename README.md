# Project Description

[![CI](https://github.com/ankman007/ecommerce-store/actions/workflows/ci.yml/badge.svg)](https://github.com/ankman007/ecommerce-store/actions/workflows/ci.yml)

This Django-based eCommerce platform delivers a dynamic, responsive shopping experience with in-page content updates powered by HTMX. It integrates Stripe for secure payment processing, and uses Celery with Redis to manage asynchronous tasks like order confirmation emails. The entire application is containerized with Docker and deployed behind Nginx for scalable and reliable hosting.

## Technology used

- Django
- HTMX
- Bootstrap
- MySQL
- Celery
- Stripe API

## To set up this project

1. cd into project directory
2. Create a new .env file by copying the env.example file
3. Open the .env file and update it with your credentials as needed
4. Build docker image with `docker-compose build`
5. Start container with `docker-compose up`
6. Project should be live at http://localhost:8085 (Flower at http://localhost:5560). Change `WEB_PORT` / `FLOWER_PORT` in .env if those ports are taken.
7. Optional demo data: `docker compose exec web python manage.py seed_demo_data` (19 products and a test customer `customer@example.com` / `Customer@12345`)

## Development

### Tests

The suite uses SQLite in memory, eager Celery, in-memory email and mocked Stripe, so it needs no database, network or payment keys:

```bash
docker compose exec web python manage.py test --settings=core.test_settings
```

### Lint and format

[Ruff](https://docs.astral.sh/ruff/) handles both; settings are in `ruff.toml`.

```bash
pip install -r requirements-dev.txt
ruff check .          # lint (add --fix to auto-fix)
ruff format .         # format
```

### Pre-commit hooks

Run ruff and a few safety checks (merge markers, private keys, large files, line endings) on every commit:

```bash
pip install -r requirements-dev.txt
pre-commit install
pre-commit run --all-files   # optional: check everything once
```

To make `git blame` skip the bulk formatting commit: `git config blame.ignoreRevsFile .git-blame-ignore-revs`

### Stripe webhooks and background jobs

Orders are confirmed by Stripe webhooks, so they complete even if the customer closes the tab after paying.

1. Put your **test** keys in `.env` (`STRIPE_SECRET_KEY`, `STRIPE_PUBLIC_KEY`) and add `COMPOSE_PROFILES=stripe`.
2. Get the local signing secret and put it in `.env` as `STRIPE_WEBHOOK_SECRET`:
   ```bash
   docker compose run --rm stripe listen --print-secret
   ```
3. `docker compose up -d` now also runs the Stripe CLI, which forwards events to `/stripe/webhook/`.

`celery-beat` runs `expire_stale_checkouts` every 15 minutes: it cancels abandoned checkouts (sessions expire after 60 minutes) and completes any paid order whose webhook was missed.

Paid orders that need attention (stock ran out after payment, amount mismatch) get the status **Paid - needs review** and the shop is emailed. Resolve them in the admin with **Refund via Stripe** or **Mark reviewed**.

In production, add the endpoint `https://<your-domain>/stripe/webhook/` in the Stripe dashboard for `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed` and `checkout.session.expired`, and use its signing secret.

### Email and logging

Email uses Django's `MAILERS` setting, built from the same `.env` variables as before (`EMAIL_BACKEND`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `RECIPIENT_EMAIL`; optional `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_TIMEOUT`, `DEFAULT_FROM_EMAIL`). Mail is sent from `DEFAULT_FROM_EMAIL`, which defaults to `EMAIL_HOST_USER`.

All logs go to the console (`docker compose logs`). Set `LOG_LEVEL` (default `INFO`) to change the level. Messages logged with loguru are passed to Python's standard `logging`, so they use the same format and level. Celery workers and beat use this config too, so `LOG_LEVEL` replaces their `--loglevel` flag. Tests run with `LOG_LEVEL=CRITICAL` unless you set it yourself.

### Continuous integration

`.github/workflows/ci.yml` runs on every push to `main` and every pull request:

- **Lint:** `ruff check` and `ruff format --check`
- **Tests:** Django system checks, a missing-migrations check, then the full test suite

## Production deployment

Production runs on [Dokploy](https://dokploy.com) from `docker-compose.dokploy.yml`: gunicorn behind nginx (which also serves uploaded media), a Celery worker and beat, MySQL and Redis. Configuration comes from Dokploy's Environment tab (template: `.env.dokploy.example`) and is validated by `python manage.py check_env` every time the web container starts.

Step-by-step guide (domains, HTTPS with Cloudflare, Stripe webhook, troubleshooting): [docs/DOKPLOY.md](docs/DOKPLOY.md).

### Product catalog

`catalog/products.json` and `catalog/images/` hold the store's products. Load them with `python manage.py load_catalog` (safe to re-run; `--update` refreshes prices and descriptions without touching stock).
