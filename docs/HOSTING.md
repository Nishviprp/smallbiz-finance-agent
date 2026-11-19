# Hosting it online

Run SmallBiz Finance Agent as **one website for many businesses**: each owner signs up, gets
their own private books, and stays logged in. Their data is stored on your server, so they never
upload the same files twice.

> Running it just for yourself? You don't need any of this — use the one-click launcher
> (`start.bat` / `start.command`) on your own computer.

## Which option should I pick?

| | **A. Your own small server (recommended)** | **B. Render (no server to manage)** |
|---|---|---|
| Rough cost | ~$5–10 / month (a VPS) | ~$20–30 / month (2 web services + Postgres) |
| Setup | ~30 min, copy-paste commands | ~30 min, clicks in a web dashboard |
| HTTPS | Automatic (Caddy) | Automatic |
| Backups | `deploy/backup.sh` (cron) | Render's Postgres backups + a disk |
| Good for | Most people; cheapest, everything in one place | You never want to log into a server |

VPS providers that work well: **Hetzner**, **DigitalOcean**, **Vultr**, **Linode** — choose a US
location if your users are in the US. Pick **2 vCPU / 4 GB RAM** (or at least 2 GB). Prices change
often; check the provider's page before you buy.

Also budget for:
- **A domain name**, ~$10–15 / year (Namecheap, Cloudflare, Porkbun…).
- **AI** (optional): on a small server use `LLM_PROVIDER=openai` (`gpt-4o-mini`) or
  `anthropic` — usually cents per month for a small business — or `none` (built-in keywords
  still categorize most lines). Running Ollama needs a much bigger server.
- **Plaid bank feeds** (optional): sandbox is free. Real banks need Plaid's production approval;
  Transactions is billed per connected bank login per month. See Plaid's pricing page.

---

## Option A — Your own server (Docker + Caddy + Postgres)

What you get: Caddy in front (free HTTPS, auto-renewing), the dashboard, the API and Postgres —
only ports 80/443 are open to the internet. The API and database stay private.

### 1. Create the server and point your domain at it

1. Create an **Ubuntu 24.04** server at your VPS provider. Add your SSH key.
2. Copy its **IPv4 address**.
3. At your domain registrar, add a DNS **A record**: `books` → that IP
   (so the site will be `books.yourdomain.com`). Wait a few minutes.

### 2. Install Docker (on the server)

```bash
ssh root@YOUR_SERVER_IP
curl -fsSL https://get.docker.com | sh
```

### 3. Get the code and fill in the settings

```bash
git clone https://github.com/Nishviprp/smallbiz-finance-agent.git /opt/smallbiz-finance-agent
cd /opt/smallbiz-finance-agent/deploy
cp prod.env.example prod.env
nano prod.env
```

Set at least:
- `DOMAIN=books.yourdomain.com`
- `POSTGRES_PASSWORD=` — make one with `openssl rand -hex 24`
- `ENCRYPTION_KEY=` — the command to make one is in the file. **Save a copy somewhere safe.**
- `ALLOW_SIGNUP=true` while you onboard clients; `false` later if you want to stop new sign-ups.

### 4. Start it

```bash
docker compose -f docker-compose.prod.yml --env-file prod.env up -d --build
```

Open `https://books.yourdomain.com` → **Create account**. Done.

### 5. Turn on the firewall

```bash
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
```

### 6. Nightly backups

```bash
chmod +x backup.sh && ./backup.sh          # test once
crontab -e                                  # add the line below
0 3 * * * cd /opt/smallbiz-finance-agent/deploy && ./backup.sh
```

Backups land in `~/backups` (database dump, uploaded files, settings). Copy them off the server
now and then — or turn on your provider's snapshot backups (usually +20% of the server price).

**Restore** the database from a dump:

```bash
docker compose -f docker-compose.prod.yml --env-file prod.env exec -T db \
  pg_restore -U finagent -d finagent --clean < ~/backups/db-2026-11-18.dump
```

### Everyday commands (run in `deploy/`)

| Task | Command |
|---|---|
| Update to the latest version | `git pull && docker compose -f docker-compose.prod.yml --env-file prod.env up -d --build` |
| See logs | `docker compose -f docker-compose.prod.yml logs -f api` |
| List users | `docker compose -f docker-compose.prod.yml --env-file prod.env exec api python -m finagent.cli list-users` |
| Reset someone's password | `docker compose -f docker-compose.prod.yml --env-file prod.env exec api python -m finagent.cli reset-password owner@example.com` |

---

## Option B — Render

Render runs each part as a separate service (it can't run `docker-compose.yml` directly).

1. **New → Postgres** (Basic plan). Copy its *Internal Database URL* and change the start from
   `postgresql://` to `postgresql+psycopg://`.
2. **New → Web Service** from your GitHub fork → *Docker* → Dockerfile path
   `docker/api.Dockerfile`. Name it `finagent-api`. Environment variables:
   `DATABASE_URL` (from step 1), `AUTH_MODE=accounts`, `ENCRYPTION_KEY`, `UPLOAD_DIR=/app/data/uploads`,
   plus any AI / Plaid keys. Add a **Disk** mounted at `/app/data` (1 GB) so uploaded files survive
   deploys.
3. **New → Web Service** again → Dockerfile path `docker/dashboard.Dockerfile`. Environment:
   `API_URL` = the API service's **Internal Address** shown on its Render page
   (looks like `http://finagent-api:8000`).
4. Add your domain to the **dashboard** service under *Settings → Custom Domains*.

Use paid (Starter or higher) instances — free ones go to sleep and are slow to wake.

---

## Bank feeds (Plaid)

1. Sign up at [dashboard.plaid.com](https://dashboard.plaid.com) → *Developers → Keys*.
2. Put `PLAID_CLIENT_ID`, `PLAID_SECRET` (sandbox secret) and `PLAID_ENV=sandbox` in your env
   file, then restart.
3. In the app: **Bank accounts → Connect a bank** → pick any bank → user `user_good`,
   password `pass_good`. Or click **Connect Plaid's test bank**.
4. For real banks, request **Production** access in the Plaid dashboard (they review your app
   and company), then switch to the production secret and `PLAID_ENV=production`.

Bank login tokens are encrypted with `ENCRYPTION_KEY`. Lose the key → each business has to
reconnect its banks (their books are not affected).

## Security checklist

- [ ] `AUTH_MODE=accounts` (the production compose file sets it for you)
- [ ] Only ports 22, 80 and 443 open; API (8000) and Postgres never published
- [ ] Strong `POSTGRES_PASSWORD`, `ENCRYPTION_KEY` saved off the server
- [ ] Backups running and tested with a restore at least once
- [ ] `ALLOW_SIGNUP=false` once everyone you expect has signed up (optional)
- [ ] Update regularly (`git pull` + rebuild)

Passwords are stored as scrypt hashes, login sessions as SHA-256 hashes, repeated wrong
passwords are rate-limited, and every database query is scoped to the logged-in business.

> This software helps organise records; you are responsible for how and where you host other
> people's financial data (privacy laws, terms of service, backups).
