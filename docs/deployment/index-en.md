# Deployment Overview

Rusin-Note supports several deployment modes. Pick the guide that matches your target:

| Method | Best for | Guide |
|---|---|---|
| Vercel | Serverless, recommended (attach Neon for persistence) | [vercel-en.md](vercel-en.md) |
| AWS Lambda | Serverless, needs a credit card, not recommended | [aws-lambda-en.md](aws-lambda-en.md) |
| VPS / traditional server | Self-hosted, gunicorn + Nginx | [vps-en.md](vps-en.md) |
| Zeabur | Auto-deploy from GitHub, needs a persistent volume | [zeabur-en.md](zeabur-en.md) |

Further reading:

- Storage backends (sqlite / file / upstash / postgres / memory): [storage-backends-en.md](storage-backends-en.md)
- Real client IP and `X-Forwarded-For` forgery protection: [ip-and-proxy-en.md](ip-and-proxy-en.md)

> Note: the English README does not currently document the optional nginx + ModSecurity WAF layer; see the Chinese docs at [waf.md](waf.md) for now.

## Get a SECRET_KEY

Prepare a random key for Flask session/CSRF signing before deploying. Any one of:

- **Windows**: in PowerShell (`win+x i`) run the following and copy the result:

  ```powershell
  $bytes=New-Object byte[] 48;[System.Security.Cryptography.RNGCryptoServiceProvider]::Create().GetBytes($bytes);[Convert]::ToBase64String($bytes)
  ```

- **Linux / macOS**: `openssl rand -base64 48`
- **Cross-platform Python**: `python3 -c "import secrets; print(secrets.token_hex(32))"`

If `RUSIN_SECRET_KEY` is unset, a persistent backend (file / upstash / postgres) generates and stores one automatically; on the `memory` backend a random per-instance key is used and sessions are lost on restart. Setting it explicitly is strongly recommended on serverless platforms.

## Common environment variables

`.env.example` shows the main ones:

| Variable | Description |
|---|---|
| `RUSIN_SECRET_KEY` | Flask signing key, see above |
| `RUSIN_DATA_DIR` | Runtime data directory, default `data`; on auto-deploy platforms point it at a persistent volume (e.g. `/data`) |
| `RUSIN_STORAGE` | Force a backend: `sqlite` / `file` / `memory` / `upstash` / `postgres`; auto-detected when unset |
| `DATABASE_URL` | Neon / any PostgreSQL — selects `postgres` backend (injected automatically when Neon is attached on Vercel) |
| `KV_REST_API_URL` + `KV_REST_API_TOKEN` | Upstash Redis REST — selects the `upstash` backend |
| `REDIS_URL` | Optional. Switches page cache and rate-limit counters to a shared Redis; falls back to in-process SimpleCache when unreachable |
| `RUSIN_ADMIN` | Feature-flag admin usernames (comma-separated; merged with config.json `admin_users`) |
| `RUSIN_TRUSTED_PROXIES` / `RUSIN_IP_ALLOWLIST` / `RUSIN_IP_BLOCKLIST` | Env overrides for IP handling, see [ip-and-proxy-en.md](ip-and-proxy-en.md) |

## Proxy and cookie defaults

The repo `config.json` ships with `trust_proxy_headers` and `secure_cookies` enabled for serverless platforms:

- Behind Nginx / Cloudflare or on a serverless platform: keep both `true` and configure `trusted_proxies` (see [ip-and-proxy-en.md](ip-and-proxy-en.md)).
- Plain-HTTP local development or a VPS **without** a reverse proxy: set both back to `false` (browsers reject `Secure` cookies over HTTP, and there are no proxy headers to trust on a direct connection).
