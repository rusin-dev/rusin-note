# Storage Backends (Key for Serverless)

> Platform-specific guides live in the [Deployment Overview](index-en.md).

The storage layer (`app/core/storage.py`) is the unified data interface and provides five backends, selected explicitly via the `RUSIN_STORAGE` env var or auto-detected:

| Backend | How to enable | Notes |
|---|---|---|
| `sqlite` | default (local/VPS) | SQLite (`<DATA_DIR>/index.db`) stores an index for fast lookup; note and collection content is persisted as JSON under `<DATA_DIR>/`; legacy `file` layouts are migrated automatically |
| `file` | `RUSIN_STORAGE=file` | Plain-file layout kept for backward compatibility: notes are plain text at `notes/<user>/<ID>.txt` (not JSON), while collections, images and attachments follow the same layout as the `sqlite` row but without `index.db`; data goes under `RUSIN_DATA_DIR` |
| `upstash` | set `KV_REST_API_URL` + `KV_REST_API_TOKEN` (Upstash Redis REST API) | Data in external KV — shared across instances, survives cold starts; plain HTTPS requests, works on any Python serverless platform |
| `postgres` | set `DATABASE_URL` (Neon or any PostgreSQL; injected automatically when Neon is attached on Vercel) | Data in `storage_kv`, `storage_notes`, `storage_images`, and `storage_attachments`; cross-instance mutual exclusion via PG advisory locks |
| `memory` | `RUSIN_STORAGE=memory` (auto-enabled on serverless platforms without the above) | In-memory only, cleared on restart |

Auto-detect priority: explicit `RUSIN_STORAGE` > `KV_REST_API_URL`+`KV_REST_API_TOKEN` (upstash) > `DATABASE_URL` (postgres) > serverless platform (memory) > local (sqlite).

- Benben posts are persisted (up to `benben.max_posts`, default 200) instead of pure memory — they survive restarts when an external backend is available.
- Serverless environments (detected via `VERCEL` / `NETLIFY` / `AWS_LAMBDA_FUNCTION_NAME`) do not start background threads — cleanup runs opportunistically inside requests; logs fall back to stderr (platform log streams).
- `RUSIN_SECRET_KEY` is strongly recommended on serverless platforms. If it is unset and the backend is persistent (file/upstash/postgres), a key is generated and stored automatically; otherwise a random per-instance key is used.
- `.env.example` shows four variables: `RUSIN_STORAGE`, `RUSIN_DATA_DIR`, `RUSIN_SECRET_KEY` and `RUSIN_ADMIN`; cache-related environment variables are documented above and in the deployment guides.
- The full data-directory layout and collection keys are covered in [Configuration Options](../configuration-en.md).
