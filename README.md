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

### Continuous integration

`.github/workflows/ci.yml` runs on every push to `main` and every pull request:

- **Lint:** `ruff check` and `ruff format --check`
- **Tests:** Django system checks, a missing-migrations check, then the full test suite
