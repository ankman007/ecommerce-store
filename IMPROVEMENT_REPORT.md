# Improvement Report

Audit and hardening pass over the Django eCommerce store, done by five parallel agents (backend, performance, testing, security, business logic) followed by an integration review. Nothing has been committed yet.

## Summary

| Area | Result |
|---|---|
| Checkout & payments | All 8 confirmed money/stock bugs fixed; verified against Stripe test mode |
| Performance | Home page 44 → 3 queries, search 41 → 3, category/product 12 → 4 |
| Security | Production hardening in settings, fail-fast secret key, form validation, Flower bound to localhost |
| Storefront UX | Reworked catalog, product, cart, order pages; footer categories fixed site-wide |
| Tests | 0 → **112 tests, all passing** |
| Lint | `ruff` (pyflakes + syntax) clean apart from one pre-existing star import |

## Changes by area

### Checkout, cart and orders (critical)
- **Checkout is built from server data only.** Line items come from the user's cart in the database with database prices; prices and names posted by the browser are ignored. Previously a user could set their own price.
- **Orders are only marked paid after Stripe confirms it.** A pending `Order` (with price snapshots) is created before redirecting to Stripe. `/success/?session_id=…` retrieves the session from Stripe server-side and requires `payment_status == 'paid'`, a matching amount and an order owned by the current user. Previously visiting `/success/` created a paid order with no payment.
- **Fulfilment is idempotent and stock-safe.** `fulfill_checkout_session()` locks the order row, so refreshes or a webhook retry cannot double-process. Stock is decremented with a conditional update that can never go negative. Out-of-stock and empty carts are refused before payment.
- **Stripe webhook** at `/stripe/webhook/` with signature verification (`STRIPE_WEBHOOK_SECRET`). Unsigned or unverifiable events are rejected.
- **Order lifecycle:** new `status` (pending / paid / shipped / cancelled), `total`, `shipping_cost`, `paid_at` fields (migration `0004_order_status_totals`). The existing `paid` flag is kept and backfilled.
- **Cart fixes:**
  - The guest cart is merged into the account cart on login.
  - Quantities are validated and capped by stock.
  - Shipping is one value ($5) on the cart page and in Stripe; previously the page showed $10, the server used $5 and Stripe charged nothing.
  - The misleading client-only checkboxes and price fields were removed, and quantity changes now save through HTMX.
  - "Login to Checkout" no longer ends in a 400.
- Order creation no longer depends on the Celery worker being up.
- The orders page lists only paid orders and shows each order's status.
- **Found during integration:** Stripe's current API rejects `payment_method_types`, so every real checkout failed. The parameter was removed; payment methods are now managed in the Stripe dashboard.

### Performance
- Product grids use `select_related('category')` plus a prefetch of images (`shop/utils.py: product_grid_queryset`). Templates use the prefetched images instead of `.first()`.
- The cart count in the header is one `SUM` query, cached per request and shared with the views. It no longer writes to the session on every request.
- Similar products are limited to 8; the orders page prefetches items, products and images.
- One cart helper (`shop/utils.py: get_user_cart`) replaces `Cart.objects.get(user=…)`, which could crash with `MultipleObjectsReturned`.

| Page | Before | After |
|---|---|---|
| Home | 44 | 3 |
| Search | 41 | 3 |
| Category | 12 | 4 |
| Product detail | 12 | 4 |

### Security
- `SECRET_KEY` is required when `DEBUG` is off; there is a dev-only fallback when it's on.
- **Production settings, active only when `DEBUG` is off:**
  - secure, HttpOnly, SameSite cookies
  - HSTS, nosniff, a referrer policy, COOP and `X_FRAME_OPTIONS=DENY`
  - all of these can be tuned through env vars
- `CSRF_TRUSTED_ORIGINS` is configurable through env and defaults to the current production domains. Request and upload size limits are set.
- **allauth:** unique emails and enumeration prevention are on; the email verification mode is configurable.
- **Form validation:**
  - Contact form: rejects newlines in the name and subject, which blocks email header injection.
  - Username: case-insensitive uniqueness, 3–30 characters.
  - Email: case-insensitive uniqueness.
  - Avatar: maximum size and allowed image types.
- **XSS:** every caller of the toast partial, which uses `|safe`, was audited. None passes user input today, and a warning comment was added to the template.
- Flower (no auth, shows task arguments) is bound to `127.0.0.1` only.
- A superuser can't delete their own account from the profile page.

### Backend robustness
- **Profiles:** a user without a profile no longer gets a 500 on `/profile/` or `/@username/`, and username lookups are case-insensitive.
- **Email and username change views:** the GET, HTMX and POST handling was fixed, bare `except:` blocks were removed, and the email-sync signal was fixed (no empty addresses, never two primary addresses).
- **Admin:**
  - `Order` is registered, with read-only order items, status and date filters.
  - Products show their images inline.
  - `list_select_related` is set everywhere.
- `create_admin.py` does nothing if the `ADMIN_*` env vars are missing, doesn't print the password, and always creates a profile for the admin.
- The contact email now includes the subject the user typed; it was being dropped.

### Testing
- `core/test_settings.py`: in-memory SQLite, Celery runs tasks inline, emails captured in memory, dummy Stripe keys. Tests need neither MySQL nor network access.
- **Test files:**

| File | Tests |
|---|---|
| `shop/tests/test_checkout.py` | 23 |
| `shop/tests/test_cart.py` | 18 |
| `shop/tests/test_catalog.py` | 11 |
| `shop/tests/test_models.py` | 11 |
| `shop/tests/test_performance.py` | 8 |
| `shop/tests/test_contact.py` | 4 |
| `shop/tests/test_storefront.py` | 11 |
| `users/tests.py` | 26 |

- All Stripe calls in tests are mocked.

### Storefront and checkout experience
- **Footer:** categories and the copyright year now appear on every page through a context processor. Before, About, Contact and Privacy showed "No categories found" and no page showed the year.
- **Product cards:** each card has an add-to-cart button and a stock badge (In stock / Only N left / Out of stock), and shows clean category names.
- **Product page:**
  - breadcrumb and quantity picker
  - shipping and security notes
  - after adding, a green "Added · View cart" button instead of a disabled dead end
  - the toast names the product, with the name escaped
- **Cart page:**
  - −/+ quantity steppers that save immediately, and per-line stock warnings
  - an item count in the summary
  - a "Continue shopping" link and guest sign-in prompts
  - a checkout button that can't be double-clicked
  - a stacked layout on mobile
- **After payment:** a dedicated order confirmation page (`/orders/<id>/?placed=1`). Before, the customer landed on the home page with only a toast. A cancelled payment returns to the cart and explains that the cart was saved.
- **Orders:** the list shows order cards with status badge, total and thumbnails, linking to a detail page. Customers can only see their own paid orders. The empty states are friendly and point to the catalog.
- **Header:** the desktop and mobile cart badges both update, since they previously shared one HTML id. The badge is hidden when the cart is empty, and the mobile menu has an Orders link.

### Developer tooling
- `python manage.py seed_demo_data [--reset]` seeds 19 demo products in 5 categories with generated images, plus a test customer.

## Verification

```bash
docker compose exec web python manage.py test --settings=core.test_settings   # 112 tests, OK
docker compose exec web python manage.py check                                # no errors
docker compose exec web python manage.py makemigrations --check --dry-run     # no changes
```

Live test-mode check with Stripe test keys (no real money):
- Checkout redirected to `checkout.stripe.com`.
- The Stripe session total matched the database total ($55.97), while the forged price was ignored.
- `/success/` with an unpaid session left the order pending.
- A forged `/success/` created nothing.

## New environment variables
All are optional and have safe defaults; see `.env.example`.
- **Stripe:** `STRIPE_WEBHOOK_SECRET`
- **Hosts and cookies:** `CSRF_TRUSTED_ORIGINS`, `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SESSION_COOKIE_AGE`
- **HSTS:** `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_HSTS_PRELOAD`
- **Request limits:** `DATA_UPLOAD_MAX_MEMORY_SIZE`, `FILE_UPLOAD_MAX_MEMORY_SIZE`
- **allauth:** `ACCOUNT_EMAIL_VERIFICATION`
- **Docker:** `WEB_PORT`, `FLOWER_PORT`

## Remaining issues

| Priority | Issue | Suggested fix |
|---|---|---|
| High | The webhook isn't configured locally, so a payment completed on Stripe is only fulfilled when the customer returns to `/success/` | Run `stripe listen --forward-to localhost:8085/stripe/webhook/` and put the `whsec_…` value in `.env`; register the endpoint in the Stripe dashboard for production |
| High | CKEditor 4 is unsupported and has known security issues (admin-only) | Move to `django-ckeditor-5` or a plain text field with sanitising |
| Medium | Abandoned checkouts stay `pending` forever | A periodic Celery task that cancels pending orders older than about 24h (Stripe sessions expire after 24h) |
| Medium | If an item sells out after the customer has paid, the order is still marked paid and only a warning is logged | Add a "needs review" status and refund or notify |
| Medium | Recommended database constraints and indexes not yet applied | One active cart per user; unique `(cart, product)`; `unique=True` on `stripe_session_id`; indexes on `Order(user, created_at)` and `Product(category)` |
| Medium | Concurrent add-to-cart requests may lose updates (not verified) | Use `F('quantity') + n` inside `transaction.atomic` |
| Low | No coupon or discount system (none existed) | Build only if needed |
| Low | `Payment` model is unused | Remove it, or record Stripe payment intents in it |
| Low | The verification-email link sends on GET; profile settings read `emailaddress_set.first` instead of the primary address | Switch to POST; use the primary address |
| Low | Star import in `users/urls.py` | Use explicit imports |
| Low | Django 6.1 deprecates the `EMAIL_*` settings | Migrate to `MAILERS` before Django 7 |
| Info | Stripe isn't available to merchants in Nepal | Add Khalti/eSewa behind the same "verify on the server, then fulfil" flow |

## Recommendations
1. ~~Commit this work and add a GitHub Actions job that runs the test suite on every push.~~ Done: `.github/workflows/ci.yml` (lint + tests), pre-commit hooks and `.gitattributes`.
2. Configure the Stripe webhook before going live; it makes order creation independent of the customer's browser.
3. Apply the recommended constraints in a dedicated migration, after checking existing production data for duplicate carts.
4. Before deploying, the production server needs Python 3.12+, `pip install -r requirements.txt` and `python manage.py migrate` (migrations `0003`, `0004`).
