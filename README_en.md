> [!IMPORTANT]
>
> Note: If you are a member of rusin-dev (this organization) and want to contribute, please see the [Collaboration Guide](https://github.com/rusin-dev/rusin-note?tab=contributing-ov-file). If you are not a member of this organization, you can join or open an Issue.

<div align="center">
    <a href="https://github.com/rusin-dev/rusin-note"><img width="15%" alt="logo" src="./image/logo.png" /></a>
    <h1><b>Rusin-Note</b></h1>
    <p><em>🖊︎ A lightweight cloud clipboard project inspired by note.ms, deployable on VPS and serverless platforms (Vercel / AWS Lambda), ready to use out of the box.</em></p>
    <p>
        <a href="https://github.com/rusin-dev/rusin-note/blob/main/README.md">简体中文</a> | English | <a href="https://note.rusin7.com">Demo</a>
    </p>
        <p align="center">
        <a href="https://github.com/rusin-dev/rusin-note/blob/main/LICENSE"><img src="https://img.shields.io/github/license/rusin-dev/rusin-note" alt="License" /></a>
        <a href="https://github.com/rusin-dev/rusin-note/releases"><img src="https://img.shields.io/github/release/rusin-dev/rusin-note" alt="latest version" /></a>
        <a href="https://github.com/rusin-dev/rusin-note/releases"><img src="https://img.shields.io/github/downloads/rusin-dev/rusin-note/total?color=%239F7AEA&logo=github" alt="Downloads" /></a>
        <a href="https://github.com/rusin-dev/rusin-note/stargazers"><img src="https://img.shields.io/github/stars/rusin-dev/rusin-note" alt="Stars" /></a>
        <a href="https://github.com/rusin-dev/rusin-note/network/members"><img src="https://img.shields.io/github/forks/rusin-dev/rusin-note" alt="Forks" /></a>
        <a href="https://github.com/rusin-dev/rusin-note/actions/workflows/check.yml">
        <img src="https://github.com/rusin-dev/rusin-note/actions/workflows/check.yml/badge.svg" alt="CI Build"></a>
        <a href="https://github.com/rusin-dev/rusin-note/actions/workflows/auto-merge.yml">
        <img src="https://github.com/rusin-dev/rusin-note/actions/workflows/auto-merge.yml/badge.svg?branch=main" alt="Auto merge"></a>
        <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white" alt="Python version"></a>
        <a href="https://www.repostatus.org/#active"><img src="https://img.shields.io/badge/repo%20status-Active-Green" alt="Project Status: Active – The project has reached a stable, usable state and is being actively developed."></a>
    </p>
</div>

![Screenshot](https://github.com/rusin-dev/rusin-note/blob/main/image/screenshots1.png)

## Features

- **Cloud clipboard that works out of the box**: A lightweight Flask implementation for VPS or serverless (Vercel / AWS Lambda) deployment, letting you save and access text quickly from any browser.
- **Public and private notes**: Random short paths for public notes, plus a private note list for every signed-in user, covering both temporary sharing and personal storage.
- **Secure share links**: Generate random-token share links for user notes, with optional write-back support for simple cross-device collaboration.
- **Markdown and LaTeX rendering**: Read-only pages, comments, and the benben feed support Bleach-sanitized Markdown, KaTeX math, and syntax highlighting (server-side Pygments tokenization, with client-side highlight.js covering unrecognized languages and generating line numbers, following the light/dark theme). Editor live rendering can be toggled manually.
- **Document outline**: Read-only pages build an `h1`-`h6` outline with active-section tracking. Wide screens use a sidebar, narrow screens use a floating button and drawer, and the editor preview provides a live outline menu.
- **Markdown heading anchors**: Headings receive stable slug IDs for in-page links and deep links; the anchor control copies the section URL.
- **Markdown alert cards (GitHub Alerts)**: Start a blockquote with `[!NOTE]`, `[!TIP]`, `[!IMPORTANT]`, `[!WARNING]`, or `[!CAUTION]` (`[!INFO]` aliases `[!NOTE]`) to render a GitHub-style colored card. Cards are `<details>` elements: click the title to expand/collapse. They are expanded by default; add `-` after the marker (`> [!WARNING]-`) to collapse by default, or `+` to force open. Markdown, code blocks, and nested cards all render inside.
- **Quick note references (`#`)**: Typing `#` in a private-note editor opens GitHub-Issues-style autocomplete by note ID and first-line title. Rendered references link to the referenced note without affecting code blocks.
- **Note tags**: Add tags with autocomplete in the editor and filter the user note list by tag.
- **Note folders**: Assign each note to one folder and filter the user note list by folder.
- **Pinned notes**: Pin important notes from the note list so they remain at the top.
- **Note image hosting**: Paste or drag PNG, JPEG, GIF, or WebP images into the editor. Formats are validated by file signature, images are referenced through Markdown, and defaults are 2MB per image and 50MB per user.
- **Note attachments**: Upload arbitrary file types (executables and archives are blacklisted by default), with a default 50KB per-file limit, 500KB per-note quota, and 10MB per-user quota (all configurable in `config.json`), drag-drop upload on the management page, referenced as links in notes. Downloads require a logged-in account by default (`/attachment/<u>/<id>` returns 401 for anonymous visitors), and per-user in-flight queues are capped ([#191](https://github.com/rusin-dev/rusin-note/issues/191): 1 concurrent download, 1 concurrent upload) so a thousand trickling (1KB/s) connections or 100 parallel download threads cannot occupy the workers or saturate egress bandwidth.
- **Comment system**: Comment functionality for notes and share pages, supports anonymous comments, configurable max comments (default 200), cooldown time, paginated loading, similar posting wait mechanism to benben feed.
- **Benben feed**: A persistent lightweight feed where logged-in users can post and anonymous users can read, with live preview, pagination, post cooldowns, and a Reply action that fills `|| @username: original content`.
- **Feature flags**: Admins can toggle public notes, benben, share links, registration, references, tags, folders, pins, heading anchors, alert cards, images, attachments, comments, LaTeX, highlighting, avatars, and organizations at `/admin/features`. Changes are persisted and take effect without restarting; disabled routes return 404 and their entry points are hidden.
- **Organizations and collaboration**: Create organizations and invite members, with Owner / Admin / Member roles. Organization notes live in the isolated `_orgs/<org_name>/` storage namespace, completely separate from personal notes. Three join modes: invitation codes, public joining, and approval requests (Admin/Owner decides). Owners manage organization settings, add/remove admins, and delete the organization; admins manage members and invitations; members create and edit organization notes.
- **Homepage notice banner**: The top of the homepage shows the first non-empty line of `NOTICE.txt` in the repository root (leading blank lines are skipped) as a site notice. It hides automatically when the file is missing or empty, the text is HTML-escaped, and no extra configuration is required.
- **Homepage workbench**: When signed in, the homepage becomes a VSCode-welcome-style workbench — recently edited notes (count controlled by `home_page.recent_notes_limit`) and a **to-do list** (add / toggle / delete / clear completed, bounded by the `todos` config). With simple mode enabled, the homepage jumps straight to a new note.
- **Multi-language UI**: Simplified Chinese and English are built in, with manual switching and browser-language fallback.
- **User settings**: Every signed-in user manages their account at `/user/<username>/settings` — toggle **simple mode** (hides tags, pins, benben, the org menu, the share entry and other advanced features; the editor also hides the preview pane, attachments and the comment entry, keeping only note editing; the preference is tied to the account and applies on all devices, and the old navbar toggle has moved here), change the password (verifies the current password and complexity, and signs out other devices), and change the login username (notes, images, attachments, tags/folders/pins/todos/shares/benben/comments/org data are automatically migrated to the new username, and the current session is renamed so you stay signed in).
- **Deployment-friendly configuration**: Common options live in `config.json`, including note expiration, session timeout, password policy, trusted proxy IP handling, and HTTPS cookies. Business data can live in local SQLite (index) + JSON files, Upstash Redis, Neon/PostgreSQL, or in-memory storage — external backends survive cold starts on serverless platforms.
- **Practical baseline protection**: Includes CSRF protection, request rate limits, save limits, registration limits, a global per-IP fallback limit, IP allow/block lists, content sanitization, and X-Forwarded-For forgery protection for safer public deployments.

## Quick Start

### Requirements

Python version $\geq$ 3.10.

### Local Development

1. Clone the repository

    ```bash
    git clone https://github.com/rusin-dev/rusin-note.git
    cd rusin-note
    ```

2. Dependency installation

   ```bash
   pip install -r requirements.txt
   ```

3. Start the server

    ```bash
    python3 -m app      # on Windows: python -m app
    ```

    Then open <http://localhost:8080> (the port is controlled by the `PORT` env var, default `8080`).

4. Run the tests (optional)

    ```bash
    pip install -r requirements-dev.txt
    pytest tests/                     # end-to-end tests (isolated temp data dir, never touches local data)
    python tests/frontend_check.py    # front-end syntax check (Jinja2 + inline CSS/JSON; inline JS only when Node is installed)
    ```

### Production Deployment

#### Get a SECRET_KEY

Windows: in PowerShell (`win+x i`) run `$bytes=New-Object byte[] 48;[System.Security.Cryptography.RNGCryptoServiceProvider]::Create().GetBytes($bytes);[Convert]::ToBase64String($bytes)` to generate a key.

Linux / macOS: in a terminal run `openssl rand -base64 48` to generate a key.

Cross-platform Python: `python -c "import secrets; print(secrets.token_hex(32))"` or `python3 -c "import secrets; print(secrets.token_hex(32))"`.

#### Option 1: Vercel (Serverless, Recommended)

The repository ships with Vercel configuration (`vercel.json` + `api/index.py`):

[Vercel Demo](https://rusin-note.vercel.app)

[![Deploy to Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2Frusin-dev%2Frusin-note&&env=RUSIN_SECRET_KEY)

1. Import this repository on [Vercel](https://vercel.com) (the Python runtime is auto-detected).
2. Pick a storage backend:
   - **Neon (PostgreSQL)**: install [Neon](https://vercel.com/marketplace/neon) from the Vercel Storage / Marketplace — Vercel injects `DATABASE_URL` automatically (Vercel KV has been sunset; Neon is the recommended persistent option).
   - **Upstash Redis**: install Upstash Redis from the Vercel Marketplace and set `KV_REST_API_URL` / `KV_REST_API_TOKEN` manually. Upstash wins if both are set.
3. Add `RUSIN_SECRET_KEY` (a long random string used for session/CSRF signing). This is strongly recommended; a persistent backend can generate and retain one automatically, while the `memory` backend cannot preserve it across cold starts.
4. Deploy. Notes, media, users, sessions, shares, feeds, comments, and organization data use Neon/Upstash, are shared across instances, and survive cold starts.

Optional: set `REDIS_URL` (a Redis connection string, e.g. Upstash or self-hosted Redis) so page caching switches to shared Redis and rate-limit counters are shared across instances. Without it, the cache first tries `cache.redis_url` (the repository default is `redis://localhost:6379/0`, usually unreachable on serverless platforms), falls back to the in-process SimpleCache when unreachable, and rate limiting counts per instance.

> Note: `config.json` defaults to `trust_proxy_headers: true` and `secure_cookies: true` for serverless platforms. Change them back for local/VPS use if needed.

#### Option 2: AWS Lambda (Serverless)

A credit card is required, so this option is not recommended.

`lambda_handler.py` (Mangum WSGI adapter) is included:

1. Package the repository (including `templates/`, `config.json`, etc.);
2. Handler: `lambda_handler.handler`, with API Gateway proxy integration;
3. Env vars as on Vercel (`RUSIN_SECRET_KEY` plus storage: `DATABASE_URL` or `KV_REST_API_URL` / `KV_REST_API_TOKEN`);
4. Memory ≥ 512MB recommended (Markdown rendering).

#### Option 3: VPS / Traditional Server

Connect to your server, then:

1. Clone the repository

    ```bash
    git clone https://github.com/rusin-dev/rusin-note.git
    cd rusin-note
    ```

2. Dependency installation

   ```bash
   pip install -r requirements.txt
   ```
3. Start the server

    ```bash
    python3 -m app

    # Run in the background
    nohup python3 -m app > app.log 2>&1 &

    # Recommended in production (Linux, gunicorn — install it separately: pip install gunicorn)
    # The listen port comes from PORT; replace 8080 yourself if PORT is unset (must match the reverse-proxy target below)
    gunicorn 'app.wsgi:app' -b 0.0.0.0:${PORT:-8080} --workers 2 --threads 4
    ```

4. Configure Nginx (optional)

    Create a site configuration:

    ```bash
    sudo nano /etc/nginx/sites-available/rusin-note
    ```

    Copy the following content:

    ```nginx
    server {
        listen 80;
        server_name _ your_domain.com;

        location / {
            proxy_pass http://127.0.0.1:8080;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            # Let Nginx (re)write XFF by appending the peer it saw, so a client-supplied XFF is not passed through
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }
    }
    ```

    > After setting up the Nginx/Cloudflare reverse proxy, set `trust_proxy_headers` to `true` in
    > `config.json` and make sure `trusted_proxies` covers the proxy address (the default
    > `["loopback", "private"]` handles a same-host Nginx; add the `"cloudflare"` preset when
    > Cloudflare is in front). The server first validates the direct TCP peer against
    > `trusted_proxies`, then resolves the real client IP by walking `X-Forwarded-For` from right
    > to left while skipping trusted proxies — forged left-hand entries are never used. If the peer
    > is not trusted, all proxy headers are ignored and the direct IP is used.

    > Note: `config.json` ships with `trust_proxy_headers: true` and `secure_cookies: true`
    > for serverless platforms. Keep both when you are behind Nginx/Cloudflare (plus a
    > matching `trusted_proxies`); set them back to `false` only for plain-HTTP local/VPS
    > use **without** a reverse proxy — browsers reject `Secure` cookies over HTTP, and
    > there are no proxy headers to trust when clients connect directly.

    ```bash
    # Enable and reload
    sudo ln -s /etc/nginx/sites-available/rusin-note /etc/nginx/sites-enabled
    sudo nginx -t && sudo systemctl reload nginx
    sudo ufw allow 'Nginx Full'
    ```

#### Zeabur Auto Deployment

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

#### Zeabur: enable Redis (page cache + shared rate limiting)

Zeabur is a PaaS platform, so installing Redis inside the container (`apt install redis`) is neither required nor recommended — build output is rebuilt on every redeploy, so the package would not survive. The standard approach is to add a managed Redis service; Zeabur then injects its connection details into the other services:

1. Open **Market** / **Marketplace** in your Zeabur project, search for and add a **Redis** service (ships with the `redis/redis-stack-server` image; Zeabur generates a random password for it).
2. Once added, Zeabur automatically injects `REDIS_CONNECTION_STRING`, `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, etc. into the other services of the project (you can also find them under the Redis service's **Instructions**).
3. Back in this service, open **Variables** and add one cross-service reference (Zeabur expands it into the password-bearing connection string):

   ```plaintext
   REDIS_URL = ${REDIS_CONNECTION_STRING}
   ```

   equivalent to `redis://:password@service-name:6379`.
4. Redeploy. On startup the app actively `PING`s Redis: when reachable, the page cache (homepage / notes / benben, ...) switches to the shared Redis backend and rate-limit counters are stored there too (shared across instances); when unreachable, the log prints `Redis 缓存不可达（…），已降级到 SimpleCache` (`Redis cache unreachable (…), falling back to SimpleCache`) and the app keeps using the in-process cache with no loss of functionality.

> Note: Redis only handles caching and rate limiting. Clipboard, user, share, benben, and other business data still live on the `/data` volume mounted above (the `file` backend); the two do not affect each other. If you want business data shared across instances and safe from restarts, switch to the `postgres` or `upstash` backend (next section).

Benben posts are now persisted to the storage backend (up to `benben.max_posts`, default 200) instead of pure memory.

### Storage Backends (Key for Serverless)

The storage layer (`app/storage.py`) is the unified data interface and provides five backends, selected explicitly via the `RUSIN_STORAGE` env var or auto-detected:

| Backend | How to enable | Notes |
|---|---|---|
| `sqlite` | default (local/VPS) | SQLite (`<DATA_DIR>/index.db`) stores an index for fast lookup; note and collection content is persisted as JSON under `<DATA_DIR>/`; legacy `file` layouts are migrated automatically |
| `file` | `RUSIN_STORAGE=file` | Plain-file layout kept for backward compatibility: notes are plain text at `notes/<user>/<ID>.txt` (not JSON), while collections, images and attachments follow the same layout as the `sqlite` row but without `index.db`; data goes under `RUSIN_DATA_DIR` |
| `upstash` | set `KV_REST_API_URL` + `KV_REST_API_TOKEN` (Upstash Redis REST API) | Data in external KV — shared across instances, survives cold starts; plain HTTPS requests, works on any Python serverless platform |
| `postgres` | set `DATABASE_URL` (Neon or any PostgreSQL; injected automatically when Neon is attached on Vercel) | Data in `storage_kv`, `storage_notes`, `storage_images`, and `storage_attachments`; cross-instance mutual exclusion via PG advisory locks |
| `memory` | `RUSIN_STORAGE=memory` (auto-enabled on serverless platforms without the above) | In-memory only, cleared on restart |

Auto-detect priority: explicit `RUSIN_STORAGE` > `KV_REST_API_URL`+`KV_REST_API_TOKEN` (upstash) > `DATABASE_URL` (postgres) > serverless platform (memory) > local (sqlite).

- Serverless environments (detected via `VERCEL` / `NETLIFY` / `AWS_LAMBDA_FUNCTION_NAME`) do not start background threads — cleanup runs opportunistically inside requests; logs fall back to stderr (platform log streams).
- `RUSIN_SECRET_KEY` is strongly recommended on serverless platforms. If it is unset and the backend is persistent (file/upstash/postgres), a key is generated and stored automatically; otherwise a random per-instance key is used.
- `.env.example` shows four variables: `RUSIN_STORAGE`, `RUSIN_DATA_DIR`, `RUSIN_SECRET_KEY` and `RUSIN_ADMIN`; cache-related environment variables are documented above.

## Plugin System

Plugins are distributed as zip archives. Place a `*.plugin.zip` package in `RUSIN_DATA_DIR`; at startup the application validates and extracts it into `plugins/<namespace>/`, registers its Flask blueprint, and removes the package. **Serverless deployments (read-only filesystem) do not support plugins.**

### Plugin package structure

```plaintext
+ desc.json          metadata
+ icon.ico           optional icon named by desc.icon
+ src/
  + __init__.py      APP_ROUTER / OVERRIDE / ENV_VARIBLES declarations
  + app.py           contains a Flask Blueprint
  + templates/       namespaced Jinja2 templates
  + static/          blueprint static files
```

Example `desc.json`:

```json
{
  "name": "example",
  "version": "v0.1",
  "upstream_repo": "https://github.com/rusin-dev/template-plug",
  "icon": "icon.ico",
  "namespace": "template_plug",
  "auth_token": "sk-ccccddddddd"
}
```

- `namespace`: the namespace (`^[a-zA-Z0-9_\-]+$`), matching the install directory `plugins/<namespace>`; it must not collide with an existing one;
- `upstream_repo`: upstream repository used for automatic updates — either a direct zip URL or a GitHub repository URL (the latest `main` / `master` archive is downloaded);
- `auth_token`: installation credential. **Packages missing it are rejected** unless startup runs with `--skip-auth` or the environment variable `RUSIN_PLUGIN_SKIP_AUTH=1` (not recommended in production).

`src/__init__.py` template:

```python
APP_ROUTER = "app.py"    # module that defines the Blueprint (defaults to app.py)
OVERRIDE = False         # whether to override site static files
# OVERRIDE = {"source": {"static/dst.css": "static/src.css"}}
ENV_VARIBLES = []        # required environment variables (a log warning is raised when missing)
```

### Installation, update and security

- **Phase 1 (install)**: at startup the app scans the runtime directory for `*.plugin.zip`, validates and extracts them into `plugins/<namespace>/`, writes `auth_token` and `last_update` back into `desc.json`, then deletes the package. Checks include: zip path traversal, oversized extraction, package root must contain only `desc.json` / icon / `src/`, `auth_token` verification, and namespace conflicts (a different source may not reuse an existing namespace unless it declares `OVERRIDE`; the same source may). The plugin must contain a Blueprint in `src/app.py`; a missing one logs an error and is skipped without breaking the site.
- **Phase 2 (update)**: a background thread (every `plugins.update_interval_hours`, default 6 hours) scans `plugins/*/desc.json`; when `last_update` is older than `update_stale_days` (default 3 days) it fetches `upstream_repo` (3 second timeout), saves the result as `<namespace>.plugin.zip` and reruns Phase 1. Already-loaded plugins only pick up the new files after a restart.
- `plugins` config in `config.json`: `enabled` (default `true`), `update_interval_hours` (default `6`), `update_stale_days` (default `3`).
- Plugin blueprints are registered before the root short-link catch-all, so plugin routes are not swallowed by `/<id>`; a plugin that fails to import only disables itself and is logged, the site keeps running.
- Plugin POST forms must include `{{ csrf_token() }}` because CSRF protection is global.
- Plugins execute Python inside the application process. Install only trusted packages; `auth_token` is recommended so unofficial packages are rejected (the check is skipped only with the explicit bypass above).

## Project Structure

```plaintext
rusin-note:.
│  config.json (configuration)
│  contributing.md (collaboration guide)
│  Disclaimer-en.md (English disclaimer)
│  Disclaimer.md (disclaimer)
│  favicon.ico
│  LICENSE
│  .gitignore
│  NOTICE.txt (homepage notice banner content, first non-empty line)
│  README.md
│  README_en.md
│  requirements.txt (Python dependencies)
│  requirements-dev.txt (dev dependencies: pytest)
│  pytest.ini (pytest configuration)
│  todo.md (roadmap / to-dos)
│  AGENTS.md / CLAUDE.md (AI collaboration guide)
│  zbpack.json (packaging configuration)
│  vercel.json (Vercel serverless configuration)
│  lambda_handler.py (AWS Lambda entry)
│  .env.example (environment variable example)
│  feature_flags.json (legacy flag-state file; runtime writes data/feature_flags.json)
│
├─api (serverless entry)
│      index.py (Vercel Python entry)
│
├─app (core code)
│  │  __init__.py
│  │  __main__.py (entry: python3 -m app)
│  │  attachments.py (attachment validation, quotas, and storage API)
│  │  auth.py (password hashing & session auth)
│  │  background.py (background cleanup tasks)
│  │  comments.py (comment validation and business API)
│  │  concurrency.py (in-process concurrency gate: per-user in-flight request cap)
│  │  config.py (configuration loading & global constants)
│  │  extensions.py (Flask extension instances)
│  │  feature_flags.py (feature registry and persisted runtime state)
│  │  folders.py (note folders)
│  │  i18n.py (multi-language support)
│  │  images.py (image validation, quotas, and storage API)
│  │  ip_utils.py (safe client-IP parsing: trusted-proxy check / right-to-left XFF / IP lists)
│  │  logger.py (logging)
│  │  middleware.py (request hooks and rate-limit helpers)
│  │  notes.py (note file operations & stats)
│  │  pins.py (pinned notes)
│  │  plugins.py (plugin installation, loading, and updates)
│  │  storage.py (sqlite / file / memory / upstash / postgres backends)
│  │  storage_sqlite.py (SQLite index backend implementation)
│  │  store.py (users/sessions/shares/benben/comments/org data)
│  │  tags.py (note tags)
│  │  theme.py (theme and static resource helpers)
│  │  todos.py (homepage workbench to-do list)
│  │  user_settings.py (simple mode / password / username change & data migration)
│  │  utils.py (shared utilities)
│  │  wsgi.py (WSGI entry)
│  │
│  └─views (blueprints and routes)
│          __init__.py (blueprint registration)
│          _helpers.py (view helpers)
│          admin.py (feature flag administration)
│          auth.py (login and registration)
│          benben.py (benben feed)
│          comments.py (comment pages)
│          home.py (home / stats / disclaimer)
│          org.py (organizations and collaboration)
│          share.py (share pages)
│          static_routes.py (favicon / image / attachment serving)
│          todos.py (workbench to-do actions)
│          user.py (user and user notes)
│          world.py (public notes)
│          world_short.py (short-link public notes)
│
├─templates (Jinja2 templates)
│  │  base.html (base layout)
│  │  count.html (statistics page)
│  │  disclaimer.html (disclaimer page)
│  │  home.html (homepage / workbench)
│  │
│  ├─admin (administration pages)
│  ├─attachments (attachment management pages)
│  ├─auth (auth pages)
│  ├─benben (benben pages)
│  ├─comments (comment pages)
│  ├─errors (error pages)
│  ├─images (image management pages)
│  ├─notes (note pages)
│  ├─org (organization pages)
│  ├─partials (shared partials)
│  └─share (share pages)
│
├─tests (pytest end-to-end tests & front-end syntax check)
│       README.md (test conventions and file notes)
│       conftest.py (environment isolation and shared fixtures)
│       support.py (shared HTTP helpers and assertions)
│       frontend_check.py (front-end syntax check CLI)
│       test_*.py (per-feature end-to-end tests)
│
├─image (image assets)
│      logo.png
│      screenshots1.png
│
├─.github
│  │  issue-labeler.yml (Issue label configuration)
│  │
│  ├─ISSUE_TEMPLATE (Issue templates)
│  └─workflows (GitHub Actions)
│          auto-merge.yml (auto-merge)
│          check.yml (checks)
│          codeql.yml (CodeQL analysis)
│          labeler.yml (auto-labeling)
│          release.yml (release)
│          trigger-fork-sync.yml (trigger fork sync)
│          upstream-sync.yml (upstream sync)
```

### IP Rate Limiting and XFF Forgery Protection

Rate limiting keys on the *real client IP*, while `X-Forwarded-For` (XFF), `X-Real-IP` and `CF-Connecting-IP` are request headers any client can forge — trusting them blindly lets an attacker rotate fake IPs and bypass every limit. The rules implemented in `app/ip_utils.py` are:

1. **Peer validation**: proxy headers are honoured only when the direct TCP peer (`remote_addr`) matches `trusted_proxies`; for direct public traffic all proxy headers are ignored.
2. **Strict parsing**: a header value must be a valid IP (`1.2.3.4:80`, `[2001:db8::1]:443`, `::ffff:1.2.3.4` are accepted); anything else is dropped so arbitrary strings can never create limiter buckets. A single header longer than 256 bytes is dropped in full (not parsed at all), and XFF chains longer than 16 entries keep only the first 16.
3. **XFF resolved from the right**: XFF is an append-only list, so the right-most entries are written by trusted proxies and the left-hand part may be forged. Trusted proxy addresses are skipped layer by layer (Cloudflare → Nginx) and the first untrusted valid IP wins.
4. **Visibility**: when proxy headers arrive from an untrusted peer, a throttled `检测到疑似伪造的代理头已忽略` warning is logged (at most once per IP per 5 minutes).

Deployment notes:

```nginx
# Nginx must *rewrite* XFF (append the upstream address it sees) or set X-Real-IP;
# otherwise a client-supplied XFF is forwarded untouched
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
```

- Same-host / same-private-network Nginx or Caddy: the default `["loopback", "private"]` in `trusted_proxies` is enough.
- Cloudflare (or Cloudflare → Nginx): add the `"cloudflare"` preset; it also honours `CF-Connecting-IP`, which Cloudflare overwrites.
- When the application port is **exposed directly to the internet** (including directly mapped Docker ports, where the peer may look like a gateway private address), narrow `trusted_proxies` to the concrete reverse-proxy IP (or only `["loopback"]`) — the `private` preset lets any host in those ranges forge proxy headers.
- Behind an internal load balancer whose address is a public IP, or when the proxy sits in a range other than the `private` preset: add the explicit IP/CIDR to `trusted_proxies`, otherwise proxy headers are ignored and every user shares one limit bucket (normal traffic starts getting throttled).
- At startup the effective policy is logged (`IP policy: ...` / `global IP rate limit: ...` / allow-list & block-list sizes) to the application log (`data/log/*.log`, falling back to stderr on serverless), so you can confirm the configuration.

> This project intentionally does **not** use Werkzeug's `ProxyFix`: it would let a forged XFF rewrite `request.remote_addr`, defeating the trusted-proxy check.

### Development & Testing

```bash
pip install -r requirements-dev.txt     # installs pytest (pulls in requirements.txt)
pytest tests/                           # run the whole end-to-end suite
pytest tests/test_org.py -q             # single module / keyword filter: pytest tests/ -q -k images
python tests/frontend_check.py          # front-end syntax check (Jinja2 + inline CSS/JSON; inline JS is checked only if Node is installed, otherwise skipped)
```

- Tests are organized with **pytest + logging**: `tests/conftest.py` pins `RUSIN_STORAGE=file`, switches to a temporary `RUSIN_DATA_DIR`, and clears every module-level runtime cache, so tests never touch your local data; rate limiting is disabled inside tests (to test the limiter itself see `tests/test_ip_limiter.py`), and the full conventions live in `tests/README.md`.
- All front-end assets are inlined in the Jinja2 templates (there is no `static/` directory), so run `python tests/frontend_check.py` after touching templates.
- CI (`.github/workflows/check.yml`) runs on push / PR to `dev` and is path-filtered: the `frontend` job runs the syntax check, the `test` job runs pytest and then starts the server for an HTTP health check.

### Configuration Options

- `max_note_size_kb`: Maximum note size (in **KB**), default `512` (0.5 MB — this is the value shipped in `config.json`; the code falls back to `5120` when the key is missing).
- `sitename`: Website name. Enter your site name.
- `rate_limit`: Rate limiting configuration.

    - `window_seconds`: Time window $t$, default `60`.
    - `max_requests`: Maximum number of requests $s$, default `30`.

    Maximum $s$ requests allowed within $t$ seconds.

- `get_rate_limit`: Independent rate limiting for GET requests.
    - `window_seconds`: Time window $t$, default `60`.
    - `max_requests`: Maximum number of requests $s$, default `45`.

    Maximum $s$ GET requests within $t$ seconds, applied only to routes that declare the decorator explicitly (world / note / user-list pages, etc.). The homepage, `/count` and static assets have no GET limit of their own and are only covered by `ip_rate_limit` below.

- `save_rate_limit`: Independent rate limiting for save-type POST requests (note saves / share write-backs).
    - `window_seconds`: Time window $t$, default `60`.
    - `max_requests`: Maximum number of requests $s$, default `120`.

    Maximum $s$ note saves within $t$ seconds, decoupled from the global POST limit (`rate_limit`) so frequent saves are not throttled.

- `register_rate_limit`: Per-IP registration rate limit, default one registration per 120 seconds.

- `ip_rate_limit`: Application-wide total request cap per IP, accumulated across every route and applied on top of the per-route limits.
    - `window_seconds`: Time window $t$, default `60`.
    - `max_requests`: Maximum number of requests $s$, default `300` (set to `0` to disable).
    - `enabled`: Switch, default `true`; set to `false` to disable this fallback limit as well.

- `trust_proxy_headers`: Whether to trust proxy client-IP headers. The repository configuration currently sets it to `true` for serverless/reverse-proxy deployments; set it to `false` when requests can reach the application directly.

    **Security note**: The built-in fallback is `false`. Only use `true` behind a trusted reverse proxy such as Nginx or Vercel; otherwise clients may forge proxy headers to bypass IP-based limits.

- `trusted_proxies`: **Trusted proxy networks** — the key defense against forged `X-Forwarded-For`. Proxy headers are honoured only when the direct TCP peer matches this list; for direct public traffic all proxy headers are ignored and the direct IP is used.

    Entries may be IPs/CIDRs, the presets `loopback` / `private` (RFC1918, CGNAT, link-local) / `cloudflare` (official Cloudflare ranges), or `"*"` to trust any peer (**forgeable**, for troubleshooting only). Default: `["loopback", "private"]`.

- `proxy_hops`: Number of proxy hops counted from the right of `X-Forwarded-For` in the legacy mode, default `1`. Legacy mode means `trusted_proxies` is set to `"*"` / `"any"` / `"all"` — an empty list is **not** legacy mode, it means "never trust proxy headers".

- `ip_allowlist`: IP/CIDR allowlist that is exempt from rate limiting (monitoring, internal health checks), default `[]`.

- `ip_blocklist`: IP/CIDR blocklist rejected with HTTP 403, default `[]`.

    All of the IP-related settings can also be supplied through environment variables (handy when the config file is read-only on serverless platforms): `RUSIN_TRUSTED_PROXIES`, `RUSIN_PROXY_HOPS`, `RUSIN_IP_ALLOWLIST`, `RUSIN_IP_BLOCKLIST` (comma separated; allow/block lists are merged with the config file).

- `secure_cookies`: Whether to add the `Secure` flag to the session cookie. The repository configuration currently sets it to `true`; disable it for plain HTTP local/VPS use.

    **Security note**: Only set to `true` when the site is served over HTTPS; otherwise browsers will refuse to send the cookie over HTTP.

- `id_generation`: Random URL generation configuration (values below are what `config.json` ships; when the key is missing the code falls back to length `6` with letters and digits all enabled).
    - `length`: URL length, default `4`.
    - `use_uppercase`: Use uppercase letters, default `false`.
    - `use_lowercase`: Use lowercase letters, default `true`.
    - `use_digits`: Use digits, default `false`.

- `share_token`: Share link token configuration.
    - `length`: Token length, default `64`.
    - `use_uppercase`: Use uppercase letters, default `true`.
    - `use_lowercase`: Use lowercase letters, default `true`.
    - `use_digits`: Use digits, default `true`.

- `session_timeout`: Session timeout configuration.
    - `enabled`: Enable session timeout, default `false`.
    - `minutes`: Timeout duration (in **minutes**), currently `1440` in `config.json`.

    Visitors will be logged out when the session exceeds the configured time.
- `note_expiration`: Note auto-cleanup (notes/clipboards are deleted after their save duration expires).
    - `enabled`: Enable auto-cleanup, default `false`.
    - `hours`: Save duration (in **hours**), default $24$.

    When enabled, notes (public + private) not modified within the configured hours are deleted by a background thread, which scans every 30 minutes.
- `global_cdn`: Base URL of the global CDN for front-end static assets.
    - Default `https://cdn.jsdmirror.cn`.

    Front-end assets are loaded by concatenating this base URL: FontAwesome icons, the marked editor script, DOMPurify, and KaTeX (all use `npm/`-style paths, so `https://cdn.jsdelivr.net` and other npm CDNs also work). You can replace the whole CDN in `config.json` to match your network environment without touching code.
- `latex_render`: LaTeX formula rendering.
    - `enabled`: Enable rendering, default `true`.
    - KaTeX static assets are loaded from the `global_cdn` base URL (default jsdmirror; jsdelivr, etc. also work).

    When enabled, Markdown read-only pages support `$...$` inline and `$$...$$` display math (KaTeX, client-side rendering, no server dependency).
- `code_highlight`: code highlighting (server-side Pygments + client-side highlight.js fallback).
    - `enabled`: Enable highlighting, default `true`.

    Code blocks are always tokenized and colored by Pygments on the server. This switch additionally controls client-side highlight.js: when enabled, every Markdown-rendered location (note read-only pages, editor live preview, benben feed, comments, disclaimer) gets a fallback pass for languages Pygments does not recognize, generates line numbers, and follows the site's light/dark theme. When disabled, line numbers and client-side highlighting are removed while server-side coloring remains.
- `cache`: page caching.
    - `enabled`: enable page caching, default `true`;
    - `backend`: configured backend, currently `redis`;
    - `default_timeout`: default timeout in seconds, currently `300`;
    - `redis_url`: Redis connection URL, overridden by `REDIS_URL`. An unreachable Redis automatically falls back to in-process SimpleCache.

      Note: rate-limit counters also read `REDIS_URL` (set it to share counters across instances; otherwise they live in process memory).
- `note_editor`: editor behavior.
    - `live_preview_default`: default state of live rendering, currently `false`; the browser stores the user's choice in local storage;
    - `markdown_manual_url`: Markdown guide URL shown in the editor.
- `home_page`: homepage workbench.
    - `recent_notes_limit`: number of recently edited notes shown on the homepage, default `5`;
    - `recent_shares_limit`: reserved limit for recent shares (the homepage does not render a share list yet), default `5`.
- `todos`: homepage workbench to-do list.
    - `max_items`: maximum number of to-dos per user, default `100`;
    - `max_length`: maximum characters per to-do item, default `200`.
- `note_refs`: quick `#` references.
    - `enabled`: default `true`;
    - `search_limit`: maximum autocomplete results, default `8`;
    - `scan_limit`: maximum recently modified notes scanned, default `100`.
- `max_note_tags`: maximum tags per note, default `10`.
- `max_tag_length`: maximum characters per tag, default `24`.
- `max_folder_name_length`: maximum characters per folder name, default `64`.
- `max_folder_depth`: maximum folder nesting depth (counted by `/` separators), default `8`.
- `max_note_id_length`: maximum note ID length, default `250` (compatibility cap for long links).
- `avatar`: user avatars (generated via a third-party service, shown next to the current user in the navbar, benben post authors, and the user notes list title).
    - `enabled`: enable avatars, default `true`; set `false` to hide avatars entirely.
    - `url_template`: avatar URL template, default `https://cn.cravatar.com/avatar/{hash}?d=identicon&f=y`. Supports two placeholders: `{hash}` (`md5(username)` lowercase hex) and `{username}` (URL-encoded username). Since this site's users have no email, `md5(username)` is used as the hash; `d=identicon` makes Gravatar-style services generate a deterministic geometric avatar per hash. You can also swap in other username-seeded services (e.g. DiceBear: `https://api.dicebear.com/9.x/identicon/svg?seed={username}`).
    - `size`: default size in the template (currently only a fallback value; templates use fixed sizes per location).
- `images`: note image hosting (`/image/<username>/<image_id>` is publicly readable).
    - `enabled`: enable image hosting, default `true`;
    - `max_size_kb`: maximum image size, default `2048` (2MB);
    - `max_total_kb`: per-user image quota, default `51200` (50MB);
    - PNG, JPEG, GIF, and WebP are accepted after file-signature validation; SVG is rejected.
- `attachments`: note attachments (attachment button in editor uploads files; `/attachment/<u>/<id>` requires login by default).
    - `enabled`: enable attachments, default `true`; set `false` to hide the attachment button in the editor and return 404 on the management page;
    - `max_size_kb`: max single file size (KB), default `50`;
    - `max_per_note_kb`: max total attachments referenced by one note (KB), default `500`;
    - `max_total_kb`: per-user total quota (KB), default `10240` (10MB);
    - `allow_anonymous_download`: allow **anonymous** attachment downloads, default `false` — anonymous requests to `/attachment/<u>/<id>` get 401 (the error page asks the visitor to log in); set `true` to restore the old "anyone with the link can download" behaviour;
    - `max_concurrent_downloads`: max **simultaneous downloads per user** (in-flight requests for one account), default `1` ([#191](https://github.com/rusin-dev/rusin-note/issues/191) "limit to 1 queue"); `0` disables the cap;
    - `max_concurrent_uploads`: max **simultaneous uploads per user** (in-flight requests for one account), default `1`; `0` disables the cap;
    - `download_rate_limit`: dedicated per-IP rate limit for the attachment download route, `window_seconds` (default `60`) and `max_requests` (default `120`);
    - These concurrency caps stop "open a thousand connections and trickle each at 1KB/s" or "100 threads downloading 100 files" abuse, where the request rate stays under the limiter but workers stay occupied and egress bandwidth is saturated: over the cap, downloads return 429 with `Retry-After` and uploads return a 429 JSON error the editor can display. Over-limit requests are **rejected, not queued** (queueing would occupy workers just the same). Counting is **per process** (`app/concurrency.py`), so with N gunicorn workers the effective cap is about `N × value`; strict cross-instance counting would need an atomic counter in external storage, which this project does not use;
    - Attachments are referenced as links by default; if one note embeds several attachment images (more concurrent requests than the cap), raise `max_concurrent_downloads` or set it to `0`;
    - `blocked_extensions`: list of blocked file extensions (blacklist mode), default includes `.exe`, `.bat`, `.sh`, `.zip` and other executables/archives. **The configured value carries no leading dot** (`config.json` lists `exe`, `zip`; the code adds the `.`), so do not write `.exe` — it would never match.
- `comments`: comment system (`/comments/<target_type>/<path:target_id>`, supports notes and share pages).
    - `enabled`: enable comments, default `true`; set `false` to return 404 on comment pages;
    - `max_length`: max length of a single comment (in **characters**), default `1024` (~1KB);
    - `max_comments`: max comments per target (note/share), default `200`;
    - `cooldown_seconds`: minimum interval between two comments by the same user (in **seconds**), default `3`;
    - `page_size`: comments loaded per batch, default `50`;
    - `max_height_px`: maximum display height of rendered comment content (in **px**), default `1000`, overflow scrolls within the content area.
- `password_policy`: password policy, defining the complexity requirements for guest passwords.  
   - `min_length`: minimum password length, default `8`;  
   - `max_length`: maximum password length, default `128` (hard cap `128`, preventing oversized passwords from entering the PBKDF2 slow hash and consuming CPU);  
   - `require_uppercase`: whether uppercase letters are required, default `true`;  
   - `require_lowercase`: whether lowercase letters are required, default `true`;  
   - `require_digits`: whether digits are required, default `true`;  
   - `require_special`: whether special characters (excluding `/ \ ( ) " '`) are required, default `true`;
- `RUSIN_DATA_DIR`: optional environment variable for the runtime data directory, defaulting to `data` (i.e. `data/` under the project). **Content data** (notes / images / attachments / collection JSON) is written here only by the local `sqlite` / `file` backends, but the `log/` and `plugins/` directories are always created under it regardless of backend (serverless logs fall back to stderr).

   Notes, images, attachments, and business-data JSON files are written under this directory; see the Zeabur layout above. On auto-deploy platforms, mount a persistent volume at `/data` and set `RUSIN_DATA_DIR=/data` to preserve data across deployments.
- `RUSIN_STORAGE`: optional env var to force the storage backend: `sqlite` (default, local/VPS), `file` (plain files — notes as `.txt` text), `memory` (in-memory), `upstash` (external KV for serverless), `postgres` (Neon/PostgreSQL). When unset: `KV_REST_API_URL`/`KV_REST_API_TOKEN` set → `upstash`; `DATABASE_URL` set → `postgres`; serverless platform env detected → `memory`; otherwise `sqlite`. See "Storage Backends" above.
- **Multi-language**: The interface supports Simplified Chinese and English. Language switch links (`/lang/zh` / `/lang/en`) are provided on the right side of the navbar; the preference is remembered via a cookie (`rusin-lang`); when unset, it falls back to the browser's `Accept-Language`, defaulting to Chinese. After switching, all site text (navbar, buttons, hints, error messages, benben previews, etc.) switches language instantly.
- `benben` (feed at `/benben`, logged-in users can post, anonymous read-only).
   - `max_length`: max length of a single feed post (in **characters**), default `1024` (~1KB);
   - `page_size`: posts loaded per batch, default `50`;
   - `cooldown_seconds`: minimum interval between two posts by the same user (in **seconds**), default `3`;
   - `max_height_px`: maximum display height of rendered feed content (in **px**), default `1000`, overflow scrolls within the content area;
   - `max_posts`: maximum number of posts persisted, default `200` (keeps external KV value size bounded; oldest posts are dropped);

   Content supports Markdown and LaTeX math (`$...$` / `$$...$$`, controlled by the `latex_render` switch); the form provides a sanitized marked.js live preview; server-rendered Markdown is sanitized with Bleach; loading and posting are rate-limited, and posting also has a per-user cooldown. Logged-in users can click Reply to replace the editor content with `|| @username: original content`.
- `plugins`: plugin installation and update settings.
    - `enabled`: default `true`, automatically disabled on serverless platforms;
    - `update_interval_hours`: update-check interval, default `6`;
    - `update_stale_days`: minimum age of `last_update` before fetching upstream, default `3`.
- `features` / `admin_users` feature flags (#90).
   - `features`: **default** states. The current `config.json` explicitly lists `world_notes`, `benben`, `share_links`, `open_register`, `note_tags`, `note_folders`, `note_pins`, `heading_anchors`, `markdown_alerts`, `note_images`, `note_attachments`, and `comments` (12 entries).

     **Precedence**: the 7 "legacy" features — `note_refs`, `latex_render`, `code_highlight`, `avatar`, `note_images`, `note_attachments`, `comments` — always take their defaults from their own dedicated sections (e.g. `images.enabled`, `attachments.enabled`, `comments.enabled`); same-named keys in this section have no effect for them. Every other feature (including `orgs`) defaults to enabled when omitted here.
   - `admin_users`: usernames allowed to manage feature flags; can also be set via the `RUSIN_ADMIN` environment variable (comma-separated; the two are merged).

   After logging in, an admin can toggle features at `/admin/features`; saving takes effect immediately (no restart needed): the runtime state is persisted in the storage backend (`feature_flags.json` under the data directory for the `sqlite`/`file` backends — the `feature_flags.json` in the repository root is a legacy leftover and is not used at runtime), and multi-instance deployments converge within a ~5s cache TTL. Disabled features return 404 and their navbar/home entry points are hidden automatically. All feature states are presented in the "Feature Status" section of the `/count` stats page (visible to everyone when no admin is configured, but nobody can change the switches then). Note: the serverless `memory` backend is not persistent — after a cold start, flags fall back to the `config.json` defaults.
- `logger`: logging.
    - `max_size`: byte cap per log file (RotatingFileHandler `maxBytes`), default `4294967296` (4 GiB);
    - `path_pattern`: log file path template, default `log/{timestamp}.log`, resolved relative to the data directory (i.e. `<RUSIN_DATA_DIR>/log/`);

    When the log file cannot be created (e.g. a read-only serverless filesystem), logging falls back to stderr and enters the platform log stream.
- `debug`: log verbosity switch, default `false`. It does **not** enable Flask's debug mode; the mapping is `false` → `INFO` (verbose) and `true` → `ERROR` (quiet). Keep it `false` in production.
