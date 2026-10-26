# Deploying on Dokploy

This guide deploys the full stack (Django + gunicorn, Celery worker and beat, MySQL, Redis, nginx for media) as a single Dokploy **Compose** application using `docker-compose.dokploy.yml`. It works without a domain: you can start on plain HTTP and switch to HTTPS later.

## 1. Prerequisites

- A server with Dokploy installed (`curl -sSL https://dokploy.com/install.sh | sh`), at least 2 GB RAM (MySQL + the app).
- This repository reachable by Dokploy (GitHub provider, or a Git URL with a deploy key).

## 2. Create the application

1. In Dokploy, create a **Project**, then **Create Service → Compose**.
2. **General → Provider:** choose GitHub (or Git), select this repo and the `main` branch.
3. **Compose Path:** `./docker-compose.dokploy.yml`
4. **Environment:** paste the contents of `.env.dokploy.example` and replace every value (see section 4). Dokploy writes these to `.env` next to the compose file, and every app container loads it.

Don't add anything under **Advanced → Ports**; Dokploy's Traefik already listens on 80/443 and routes to the app.

## 3. Choose how to reach the site (no domain needed)

Open **Domains → Create Domain**, service **`nginx`**, container port **`80`**, path `/`. Then pick one:

### Option A: generated traefik.me host (quickest, HTTP only)
Click the dice icon next to Host. Dokploy generates a host that resolves to your server IP. Keep **HTTPS off**.

### Option B: sslip.io host with HTTPS (recommended; still no domain to buy)
Set Host to your IP with dashes plus `.sslip.io`, e.g. `203-0-113-10.sslip.io`. It resolves to `203.0.113.10`. Turn **HTTPS on** with the **Let's Encrypt** certificate. If the certificate can't be issued, fall back to Option A.

### Option C: the bare IP
Set Host to the IP itself (`203.0.113.10`), HTTPS off. Let's Encrypt doesn't issue certificates for IPs, so this stays HTTP.

Whatever you choose, put the same host(s) in `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` (with the scheme) and `SITE_URL`.

## 4. Environment values

| Variable | Value |
|---|---|
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `ALLOWED_HOSTS` | your host(s), comma-separated, no scheme |
| `CSRF_TRUSTED_ORIGINS` | the same with `http://` (A/C) or `https://` (B) |
| `SITE_URL` | the full base URL customers will use |
| `DB_PASSWORD`, `DB_ROOT_PASSWORD`, `ADMIN_PASSWORD` | strong, unique passwords |
| `STRIPE_PUBLIC_KEY`, `STRIPE_SECRET_KEY` | test keys while testing |

**On plain HTTP (Options A and C)** these must stay as in the template, otherwise logins and forms fail because the browser won't send secure cookies over HTTP:
`SESSION_COOKIE_SECURE=False`, `CSRF_COOKIE_SECURE=False`, `SECURE_HSTS_SECONDS=0`, `ACCOUNT_DEFAULT_HTTP_PROTOCOL=http`.

**With HTTPS (Option B):** remove those four lines (secure defaults apply) and use `https://` in `CSRF_TRUSTED_ORIGINS` and `SITE_URL`.

## 5. Deploy

Click **Deploy**. Dokploy builds the images and starts the stack. Each time it starts, the `web` container:
1. runs `python manage.py check_env`: errors stop it, warnings don't;
2. applies database migrations;
3. creates the admin account from `ADMIN_*` if it doesn't exist;
4. starts the web server.

**If the deploy ends with `container ...-web-1 is unhealthy`:** open **Logs**, select the **web** container and look for lines starting with `ERROR` just after `== Checking environment ==` or `== Applying migrations ==`. Fix the value in **Environment** and deploy again.

| Error in the web logs | Fix |
|---|---|
| `DEBUG is on` | `DEBUG=False` |
| `ALLOWED_HOSTS only lists local hosts` | put your Dokploy domain host / server IP in `ALLOWED_HOSTS` |
| `... is a placeholder` | replace that `replace-with-...` value with a real one |
| `Access denied for user` (during migrations; Celery logs show it too) | MySQL created its users with the passwords from the **first** deploy and ignores later changes. **No real data yet:** add `DB_VOLUME_VERSION=3` (one higher than before; the default is 2) and redeploy, which starts a fresh database with the current passwords. **Real data:** put the original passwords back, or change the user's password inside MySQL (db container terminal: `mysql -uroot -p'<root password>' -e "ALTER USER 'ecommerce'@'%' IDENTIFIED BY '<new>';"`) |

## 6. Load the product catalog (once)

In Dokploy open the **web** container's terminal (Docker → container → Terminal) and run:

```bash
python manage.py load_catalog
```

This loads the products in `catalog/products.json` with their photos from `catalog/images/`. It's safe to run again: existing products are skipped. `--update` refreshes prices and descriptions without touching stock.

Then sign in at `/admin/` with the `ADMIN_*` credentials.

## 7. Stripe

- **Checkout** works on HTTP in test mode (card `4242 4242 4242 4242`).
- **Webhooks need HTTPS.** Without one, orders are still confirmed when the customer returns to the success page, and the reconciliation job confirms any paid order within 15 minutes.
- Once on HTTPS: Stripe Dashboard → Developers → Webhooks → add `https://<host>/stripe/webhook/` with the events `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`, `checkout.session.expired`. Put its signing secret in `STRIPE_WEBHOOK_SECRET` and redeploy.

## 8. Data and backups

MySQL data, uploaded media and Redis live in named volumes (`mysql_data`, `media`, `redis_data`). Redeploys keep them. Set up **Volume Backups** in Dokploy for `mysql_data` and `media`.

## 9. Moving to a real domain (Cloudflare)

Example: `ecommerce-store.ankit-poudel.com.np`, managed in Cloudflare.

1. **Cloudflare → DNS:** an `A` record `ecommerce-store` → server IP, **Proxied** (orange cloud).
2. **Cloudflare → SSL/TLS → Overview:** **Full (strict)**.
3. **Dokploy → Domains:** add Host `ecommerce-store.ankit-poudel.com.np`, service **`nginx`**, container port **`80`** (not 8000: nginx also serves product images), HTTPS **on**, certificate **Let's Encrypt**. Delete the old traefik.me/sslip.io domain.
4. **Environment:**
   ```env
   ALLOWED_HOSTS=ecommerce-store.ankit-poudel.com.np
   CSRF_TRUSTED_ORIGINS=https://ecommerce-store.ankit-poudel.com.np
   SITE_URL=https://ecommerce-store.ankit-poudel.com.np
   ```
   and **delete** these four lines so the secure defaults apply: `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_HSTS_SECONDS`, `ACCOUNT_DEFAULT_HTTP_PROTOCOL`.
5. **Deploy.**
6. **Stripe webhook** (now possible, because the site has HTTPS): Stripe Dashboard → Developers → Webhooks → add `https://ecommerce-store.ankit-poudel.com.np/stripe/webhook/` with the four events in section 7. Copy its signing secret into `STRIPE_WEBHOOK_SECRET` and deploy again.

If the browser shows **Cloudflare error 526** right after adding the domain, Let's Encrypt hasn't issued the certificate yet: set the DNS record to **DNS only** (grey cloud), wait a couple of minutes, then switch it back to **Proxied**.

HTTPS flows Cloudflare → Traefik → nginx → Django; nginx forwards Traefik's `X-Forwarded-Proto: https`, which Django trusts (`SECURE_PROXY_SSL_HEADER`), so secure cookies and CSRF checks work.

## 10. Cloudflare error 522: the server can't be reached from the internet

**522** means Cloudflare could not even open a connection to the server. The app's nginx logs show no incoming requests at all. Confirm from any computer outside the server's network:

```bash
curl -v --max-time 10 http://<server-ip>
```

If it times out, ports 80/443 are blocked by a firewall, or the server sits behind a router (NAT) that doesn't forward them. No app setting can fix that. There are two options, and both need the server/network owner's agreement:

### Option A: open the ports
Ask the network owner to allow (or port-forward) **TCP 80 and 443** from the public IP to the Dokploy server. Everything in section 9 then works unchanged.

### Option B: Cloudflare Tunnel (no open ports needed)
`cloudflared` runs as a container, makes an outbound connection to Cloudflare, and Cloudflare sends visitors through it. One tunnel serves every app on the server.

1. **Cloudflare → Zero Trust → Networks → Tunnels → Create a tunnel** → *Cloudflared* → name it. On the install screen, copy the **token** (the long string after `--token`).
2. **Dokploy:** create a new **Compose** service from this repository with Compose Path `./deploy/cloudflared/docker-compose.yml`. In its Environment tab add `TUNNEL_TOKEN=<token>`, then deploy. The tunnel should turn **Healthy** in Cloudflare.
3. **Cloudflare DNS:** delete the existing `A` records for the subdomains you'll route through the tunnel (e.g. `ecommerce-store`). The tunnel creates its own records, and they conflict with existing ones of the same name.
4. **Tunnel → Public Hostname → Add**, for each app:
   - Subdomain `ecommerce-store`, domain `ankit-poudel.com.np`
   - Service type **HTTP**, URL **`dokploy-traefik:80`**
5. **Dokploy → each app's Domains:** keep the same host, but set **HTTPS off** and **Certificate None**. Cloudflare handles HTTPS at its edge and the tunnel delivers plain HTTP to Traefik; with HTTPS on, Traefik would redirect in a loop.
6. Keep the app's environment set for HTTPS (`https://` in `CSRF_TRUSTED_ORIGINS` and `SITE_URL`, no "no TLS" overrides). Visitors still use `https://`.

If the tunnel is Healthy but the site gives **502**, Traefik isn't reachable under that name: check the Traefik container's name and network in Dokploy and use those in step 4.
