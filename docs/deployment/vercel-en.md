# Vercel (Serverless, Recommended)

> Prerequisites (SECRET_KEY, env vars, proxy/cookie defaults) live in the [Deployment Overview](index-en.md).

The repository ships with Vercel configuration (`vercel.json` + `api/index.py`):

[Vercel Demo](https://rusin-note.vercel.app)

[![Deploy to Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2Frusin-dev%2Frusin-note&&env=RUSIN_SECRET_KEY)

1. Import this repository on [Vercel](https://vercel.com) (the Python runtime is auto-detected).
2. Pick a storage backend:
   - **Neon (PostgreSQL)**: install [Neon](https://vercel.com/marketplace/neon) from the Vercel Storage / Marketplace — Vercel injects `DATABASE_URL` automatically (Vercel KV has been sunset; Neon is the recommended persistent option).
   - **Upstash Redis**: install Upstash Redis from the Vercel Marketplace and set `KV_REST_API_URL` / `KV_REST_API_TOKEN` manually. Upstash wins if both are set.
3. Add `RUSIN_SECRET_KEY` (a long random string used for session/CSRF signing). This is strongly recommended; a persistent backend can generate and retain one automatically, while the `memory` backend cannot preserve it across cold starts.
4. Deploy. Notes, media, users, sessions, shares, feeds, comments, and organization data use Neon/Upstash, are shared across instances, and survive cold starts.

> Attaching Neon injects `DATABASE_URL`, and the app switches to the `postgres` backend automatically (shared across instances, survives cold starts). See [Storage Backends](storage-backends-en.md).

Optional: set `REDIS_URL` (a Redis connection string, e.g. Upstash or self-hosted Redis) so page caching switches to shared Redis and rate-limit counters are shared across instances. Without it, the cache first tries `cache.redis_url` (the repository default is `redis://localhost:6379/0`, usually unreachable on serverless platforms), falls back to the in-process SimpleCache when unreachable, and rate limiting counts per instance.

> Note: `config.json` defaults to `trust_proxy_headers: true` and `secure_cookies: true` for serverless platforms. Change them back for local/VPS use if needed. Real client IP and `trusted_proxies` are covered in [IP Rate Limiting and XFF Forgery Protection](ip-and-proxy-en.md).
