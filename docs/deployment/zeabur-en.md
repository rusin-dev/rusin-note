# Zeabur

> Prerequisites (SECRET_KEY, env vars) live in the [Deployment Overview](index-en.md).

## Persistent volume (avoid data wiped on redeploy)

When deploying from GitHub on Zeabur, the application directory is rebuilt on each deployment. To prevent clipboards, users, share links, and benben posts from being cleared, store runtime data in a persistent volume:

1. Open the current service in your Zeabur project.
2. Go to `Storage` / `Volumes` and create a new Volume.
3. Set the Volume mount path to `/data`.
4. Go to `Environment Variables` and add `RUSIN_DATA_DIR=/data`.
5. Redeploy the service.

Do not mount the Volume to the project root, or it may hide the deployed application code. After setup, runtime data is stored under `/data`:

```plaintext
/data/index.db          # SQLite index: note / KV / image / attachment metadata (fast lookup)
/data/notes/<user>/<ID>.json   # note content (JSON)
/data/images/
/data/attachments/
/data/users.json
/data/sessions.json
/data/shares.json
/data/benben.json
/data/comments.json
/data/note_tags.json
/data/note_folders.json
/data/note_pins.json
/data/todos.json
/data/feature_flags.json
/data/orgs.json
/data/org_members.json
/data/org_invites.json
/data/org_join_requests.json
/data/.secret_key      # auto-generated SECRET_KEY (when RUSIN_SECRET_KEY is unset)
/data/plugins/         # installed plugins
/data/log/
```

> Local/VPS defaults to the `sqlite` backend: SQLite (`index.db`) stores only
> index metadata for fast listing / sorting / searching / stats, while the actual
> content of notes and collections is still persisted as JSON files. Two migrations
> run automatically on first startup: legacy plain-text notes
> (`notes/<user>/<ID>.txt` → `.json`) and old runtime data that used to sit in the
> repository root (→ `data/`). Note: the `note_titles.json` key is still registered
> in the storage layer but is no longer read or written, so it is never created on
> a fresh deployment.

## Enable Redis (page cache + shared rate limiting)

Zeabur is a PaaS platform, so installing Redis inside the container (`apt install redis`) is neither required nor recommended — build output is rebuilt on every redeploy, so the package would not survive. The standard approach is to add a managed Redis service; Zeabur then injects its connection details into the other services:

1. Open **Market** / **Marketplace** in your Zeabur project, search for and add a **Redis** service (ships with the `redis/redis-stack-server` image; Zeabur generates a random password for it).
2. Once added, Zeabur automatically injects `REDIS_CONNECTION_STRING`, `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, etc. into the other services of the project (you can also find them under the Redis service's **Instructions**).
3. Back in this service, open **Variables** and add one cross-service reference (Zeabur expands it into the password-bearing connection string):

   ```plaintext
   REDIS_URL = ${REDIS_CONNECTION_STRING}
   ```

   equivalent to `redis://:password@service-name:6379`.
4. Redeploy. On startup the app actively `PING`s Redis: when reachable, the page cache (homepage / notes / benben, ...) switches to the shared Redis backend and rate-limit counters are stored there too (shared across instances); when unreachable, the log prints `Redis 缓存不可达（…），已降级到 SimpleCache` (`Redis cache unreachable (…), falling back to SimpleCache`) and the app keeps using the in-process cache with no loss of functionality.

> Note: Redis only handles caching and rate limiting. Clipboard, user, share, benben, and other business data still live on the `/data` volume mounted above (the `file` backend); the two do not affect each other. If you want business data shared across instances and safe from restarts, switch to the `postgres` or `upstash` backend (see [Storage Backends](storage-backends-en.md)).

Benben posts are now persisted to the storage backend (up to `benben.max_posts`, default 200) instead of pure memory.
