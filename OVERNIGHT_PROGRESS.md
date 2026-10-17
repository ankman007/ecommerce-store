# Overnight Progress

Coordinator log for the autonomous run of Phases 2–5. Local commits only; nothing is pushed or deployed.

## Baseline (main @ f046009)

- Tests: 130 run, OK (SQLite test settings, `ecommerce-dev:local` image)
- Coverage (shop, users, core; excluding migrations/tests): 85%
- Ruff lint + format: clean
- `makemigrations --check`: no changes
- Untracked user files in repo root (11 product photos): **never stage, move or delete**

## Shared tooling

- `ecommerce-dev:local` = project image + ruff 0.17.1 + coverage 7.10.7 (PyPI was unreliable earlier)
- Test command for any checkout/worktree (Git Bash):
  `MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/app" -w /app -e DJANGO_SETTINGS_MODULE=core.test_settings ecommerce-dev:local python manage.py test --parallel auto`

## Plan and ownership

Model/migration/checkout work is serialised to avoid conflicting migrations.

| Stage | Agent | Scope | Owns |
|---|---|---|---|
| 1 | A1 Docker & deploy (Phase 2) | prod compose, non-root image, healthchecks, gunicorn conf, nginx, migrate job, env validation, deploy workflow (manual trigger only), docs | Dockerfile, docker-compose.prod.yml, deploy/ (nginx, gunicorn), .github/workflows/deploy.yml, docs/DEPLOYMENT.md, new `check_env` command, .dockerignore |
| 1 | A3 Store features (Phase 4) | shipping address + phone, confirmation/status emails, admin order management, pagination, sort/filter, images, SEO | shop models + migration 0006, shop views/templates, payment.py (address + email hooks only), base.html head/SEO |
| 1 | A4a Code health (Phase 5, no models) | logging, MAILERS, settings cleanup, regression tests, safe dependency updates | core/settings.py (bulk), requirements.txt, new test files |
| 2 | A2 Nepal payments (Phase 3) | provider abstraction, Khalti, eSewa, gateway choice, NPR handling | new `payments` app + migrations, payment.py, checkout templates |
| 2 | A4b CKEditor replacement | remove django-ckeditor, plain text descriptions | shop models + migration 0007, admin, old migration references |
| 3 | A5 QA & security | review all integrated work, report findings | none (report only) |

## Status

| Item | Status |
|---|---|
| Stage A baseline | done |
| Stage 1 agents (A1 Docker, A3 Phase 4, A4a code health) | running in isolated worktrees |
| Stage 2 (A2 payments, A4b CKEditor) | waiting for A3 (models/checkout) |
| Stage 3 (A5 QA) | waiting |

## Blockers needing the owner

_None yet._

## Continuation prompt

If this run stops early, resume with:
> Continue the overnight run described in OVERNIGHT_PROGRESS.md. Read its Status and Blockers tables, check `git log` and `git worktree list`, integrate any finished agent branches into main in the documented order, run the full validation pipeline, then continue with the next unstarted stage. Local commits only; never push.
