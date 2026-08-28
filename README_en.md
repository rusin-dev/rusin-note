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
        <a href="https://pypi.org/project/pandera/"><img src="https://img.shields.io/pypi/v/pandera.svg" alt="PyPI version shields.io"></a>
        <a href="https://www.repostatus.org/#active"><img src="https://img.shields.io/badge/repo%20status-Active-Green" alt="Project Status: Active – The project has reached a stable, usable state and is being actively developed."></a>
        <a href="https://pypi.python.org/pypi/pandera/"><img src="https://img.shields.io/pypi/pyversions/pandera.svg" alt="PyPI pyversions">
        </a>
    </p>
</div>

## Features

- **Cloud clipboard that works out of the box**: A lightweight Flask implementation for VPS or serverless (Vercel / AWS Lambda) deployment, letting you save and access text quickly from any browser.
- **Public and private notes**: Use random short paths for public notes, or keep private note lists under guest accounts for both temporary sharing and personal storage.
- **Secure share links**: Generate random-token share links for user notes, with optional write-back support for simple cross-device collaboration.
- **Markdown and LaTeX rendering**: Read-only pages, comments, and the benben feed support Bleach-sanitized Markdown, KaTeX math, and highlight.js syntax highlighting with line numbers. Editor live rendering can be toggled manually.
- **Document outline**: Read-only pages build an `h1`-`h6` outline with active-section tracking. Wide screens use a sidebar, narrow screens use a floating button and drawer, and the editor preview provides a live outline menu.
- **Markdown heading anchors**: Headings receive stable slug IDs for in-page links and deep links; the anchor control copies the section URL.
- **Quick note references (`#`)**: Typing `#` in a private-note editor opens GitHub-Issues-style autocomplete by note ID and first-line title. Rendered references link to the referenced note without affecting code blocks.
- **Note tags**: Add tags with autocomplete in the editor and filter the user note list by tag.
- **Note folders**: Assign each note to one folder and filter the user note list by folder.
- **Pinned notes**: Pin important notes from the note list so they remain at the top.
- **Note image hosting**: Paste or drag PNG, JPEG, GIF, or WebP images into the editor. Formats are validated by file signature, images are referenced through Markdown, and defaults are 2MB per image and 50MB per user.
- **Note attachments**: Upload arbitrary file types (executables blocked by default), configurable per-file size limit (default 10MB) and per-user quota (default 10MB), drag-drop upload on management page, referenced as links in notes.
- **Comment system**: Comment functionality for notes and share pages, supports anonymous comments, configurable max comments (default 200), cooldown time, paginated loading, similar posting wait mechanism to benben feed.
- **Benben feed**: A persistent lightweight feed where logged-in users can post and anonymous users can read, with live preview, pagination, post cooldowns, and a Reply action that fills `|| @username: original content`.
- **Feature flags**: Admins can toggle public notes, benben, share links, registration, references, tags, folders, pins, heading anchors, images, attachments, comments, LaTeX, highlighting, avatars, and organizations at `/admin/features`. Changes are persisted and take effect without restarting; disabled routes return 404 and their entry points are hidden.
- **Organizations and collaboration**: Create organizations with isolated notes and Owner / Admin / Member roles. Membership can use invitation codes, public joining, or approval requests; owners and admins can manage settings, members, invitations, and requests according to role.
- **Multi-language UI**: Simplified Chinese and English are built in, with manual switching and browser-language fallback.
- **Deployment-friendly configuration**: Common options live in `config.json`, including note expiration, session timeout, password policy, trusted proxy IP handling, and HTTPS cookies. For serverless deployment, data can go to external storage (Upstash Redis / Neon PostgreSQL), surviving cold starts.
- **Practical baseline protection**: Includes CSRF protection, request rate limits, save limits, registration limits, content sanitization, and a proxy-header trust switch for safer public deployments.

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
    python3 -m app
    ```

    Then open <http://localhost:8080>.

### Production Deployment

#### Option 1: Vercel (Serverless, Recommended)

The repository ships with Vercel configuration (`vercel.json` + `api/index.py`):

1. Import this repository on [Vercel](https://vercel.com) (the Python runtime is auto-detected).
2. Pick a storage backend:
   - **Neon (PostgreSQL)**: install [Neon](https://vercel.com/marketplace/neon) from the Vercel Storage / Marketplace — Vercel injects `DATABASE_URL` automatically (Vercel KV has been sunset; Neon is the recommended persistent option).
   - **Upstash Redis**: install Upstash Redis from the Vercel Marketplace and set `KV_REST_API_URL` / `KV_REST_API_TOKEN` manually. Upstash wins if both are set.
3. Add `RUSIN_SECRET_KEY` (a long random string used for session/CSRF signing). This is strongly recommended; a persistent backend can generate and retain one automatically, while the `memory` backend cannot preserve it across cold starts.
4. Deploy. Notes, media, users, sessions, shares, feeds, comments, and organization data use Neon/Upstash, are shared across instances, and survive cold starts.

Optional: set `REDIS_URL` so rate-limit counters are shared across instances (defaults to per-instance memory).

> Note: `config.json` defaults to `trust_proxy_headers: true` and `secure_cookies: true` for serverless platforms. Change them back for local/VPS use if needed.

#### Option 2: AWS Lambda (Serverless)

`lambda_handler.py` (Mangum WSGI adapter) is included:

1. Package the repository (including `templates/`, `config.json`, etc.);
2. Handler: `lambda_handler.handler`, with API Gateway proxy integration;
3. Env vars as on Vercel (`KV_REST_API_URL` / `KV_REST_API_TOKEN` / `RUSIN_SECRET_KEY`);
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
        }
    }
    ```

    > After setting up the Nginx reverse proxy, set `trust_proxy_headers` to `true` in
    > `config.json` so the server trusts the `X-Real-IP` header for rate limiting by the
    > real client IP (disabled by default to prevent header-forging bypasses).

    ```bash
    # Enable and reload
    sudo ln -s /etc/nginx/sites-available/rusin-note /etc/nginx/sites-enabled
    sudo nginx -t && sudo systemctl reload nginx
    sudo ufw allow 'Nginx Full'
    ```

### Zeabur Auto Deployment

When deploying from GitHub on Zeabur, the application directory is rebuilt on each deployment. To prevent clipboards, users, share links, and benben posts from being cleared, store runtime data in a persistent volume:

1. Open the current service in your Zeabur project.
2. Go to `Storage` / `Volumes` and create a new Volume.
3. Set the Volume mount path to `/data`.
4. Go to `Environment Variables` and add `RUSIN_DATA_DIR=/data`.
5. Redeploy the service.

Do not mount the Volume to the project root, or it may hide the deployed application code. After setup, runtime data is stored under `/data`:

```plaintext
/data/notes/
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
/data/note_titles.json
/data/feature_flags.json
/data/orgs.json
/data/org_members.json
/data/org_invites.json
/data/org_join_requests.json
/data/log/
```

Benben posts are now persisted to the storage backend (up to `benben.max_posts`, default 200) instead of pure memory.

### Storage Backends (Key for Serverless)

The storage layer (`app/storage.py`) provides four backends, selected explicitly via the `RUSIN_STORAGE` env var or auto-detected:

| Backend | How to enable | Notes |
|---|---|---|
| `file` | default (local/VPS) | Data under `RUSIN_DATA_DIR` (default: current dir), layout as above |
| `upstash` | set `KV_REST_API_URL` + `KV_REST_API_TOKEN` (Upstash Redis REST API) | Data in external KV — shared across instances, survives cold starts; plain HTTPS requests, works on any Python serverless platform |
| `postgres` | set `DATABASE_URL` (Neon or any PostgreSQL; injected automatically when Neon is attached on Vercel) | Data in `storage_kv`, `storage_notes`, `storage_images`, and `storage_attachments`; cross-instance mutual exclusion via PG advisory locks |
| `memory` | `RUSIN_STORAGE=memory` (auto-enabled on serverless platforms without the above) | In-memory only, cleared on restart |

Auto-detect priority: explicit `RUSIN_STORAGE` > `KV_REST_API_URL`+`KV_REST_API_TOKEN` (upstash) > `DATABASE_URL` (postgres) > serverless platform (memory) > local (file).

- Serverless environments (detected via `VERCEL` / `NETLIFY` / `AWS_LAMBDA_FUNCTION_NAME`) do not start background threads — cleanup runs opportunistically inside requests; logs fall back to stderr (platform log streams).
- `RUSIN_SECRET_KEY` is strongly recommended on serverless platforms. If it is unset and the backend is persistent (file/upstash/postgres), a key is generated and stored automatically; otherwise a random per-instance key is used.
- `.env.example` shows `RUSIN_SECRET_KEY` and `RUSIN_ADMIN`; storage and cache environment variables are documented above.

## Plugin System

Plugins are distributed as zip archives. Place a `*.plugin.zip` package in `RUSIN_DATA_DIR`; at startup the application validates and extracts it into `plugins/<namespace>/`, registers its Flask blueprint, and removes the package. Plugins are disabled automatically on serverless platforms because their filesystems are read-only.

```plaintext
+ desc.json          metadata
+ icon.ico           optional icon named by desc.icon
+ src/
  + __init__.py      APP_ROUTER / OVERRIDE / ENV_VARIBLES declarations
  + app.py           contains a Flask Blueprint
  + templates/       namespaced Jinja2 templates
  + static/          blueprint static files
```

`desc.json` contains `name`, `version`, `namespace`, `upstream_repo`, optional `icon`, and `auth_token`. The namespace must match `^[a-zA-Z0-9_\-]+$`. Packages without `auth_token` are rejected unless startup uses `--skip-auth` or `RUSIN_PLUGIN_SKIP_AUTH=1`.

- Installation rejects zip path traversal, oversized extraction, invalid package roots, unauthorized packages, and namespace conflicts. A missing Blueprint disables only that plugin, not the main application.
- A background task checks plugins every `plugins.update_interval_hours` (default 6 hours). If `last_update` is older than `plugins.update_stale_days` (default 3 days), it fetches `upstream_repo` with a short timeout and reinstalls the package. Updated files of an already loaded plugin require an application restart.
- Plugin blueprints are registered before the root short-link catch-all. Plugin POST forms must include `{{ csrf_token() }}` because CSRF protection is global.
- Plugins execute Python inside the application process. Install only trusted packages.

## Project Structure

```plaintext
rusin-note:.
│  config.json (configuration)
│  contributing.md (collaboration guide)
│  Disclaimer-en.md (English disclaimer)
│  Disclaimer.md (disclaimer)
│  favicon.ico
│  README.md
│  README_en.md
│  requirements.txt (Python dependencies)
│  zbpack.json (packaging configuration)
│  vercel.json (Vercel serverless configuration)
│  lambda_handler.py (AWS Lambda entry)
│  .env.example (environment variable example)
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
│  │  config.py (configuration loading & global constants)
│  │  extensions.py (Flask extension instances)
│  │  feature_flags.py (feature registry and persisted runtime state)
│  │  folders.py (note folders)
│  │  i18n.py (multi-language support)
│  │  images.py (image validation, quotas, and storage API)
│  │  logger.py (logging)
│  │  middleware.py (request hooks and rate-limit helpers)
│  │  notes.py (note file operations & stats)
│  │  pins.py (pinned notes)
│  │  plugins.py (plugin installation, loading, and updates)
│  │  storage.py (file / memory / upstash / postgres backends)
│  │  store.py (users/sessions/shares/benben/comments/org data)
│  │  tags.py (note tags)
│  │  theme.py (theme and static resource helpers)
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
│          home.py (home page)
│          org.py (organizations and collaboration)
│          share.py (share pages)
│          static_routes.py (static and documentation pages)
│          user.py (user and user notes)
│          world.py (public notes)
│          world_short.py (short-link public notes)
│
├─templates (Jinja2 templates)
│  │  base.html (base layout)
│  │  count.html (statistics page)
│  │  disclaimer.html (disclaimer page)
│  │  home.html (home page)
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
├─image (image assets)
│      logo.png
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

### Configuration Options

- `max_note_size_kb`: Maximum note size (in **KB**), default `512` (0.5 MB).
- `sitename`: Website name. Enter your site name.
- `rate_limit`: Rate limiting configuration.

    - `window_seconds`: Time window $t$, default `60`.
    - `max_requests`: Maximum number of requests $s$, default `30`.

    Maximum $s$ requests allowed within $t$ seconds.

- `get_rate_limit`: Independent rate limiting for GET requests.
    - `window_seconds`: Time window $t$, default `60`.
    - `max_requests`: Maximum number of requests $s$, default `45`.

    Maximum $s$ GET requests (page loads, favicon, etc.) within $t$ seconds.

- `save_rate_limit`: Independent rate limiting for save-type POST requests (note saves / share write-backs).
    - `window_seconds`: Time window $t$, default `60`.
    - `max_requests`: Maximum number of requests $s$, default `120`.

    Maximum $s$ note saves within $t$ seconds, decoupled from the global POST limit (`rate_limit`) so frequent saves are not throttled.

- `register_rate_limit`: Per-IP registration rate limit, default one registration per 120 seconds.

- `trust_proxy_headers`: Whether to trust proxy client-IP headers. The repository configuration currently sets it to `true` for serverless/reverse-proxy deployments; set it to `false` when requests can reach the application directly.

    **Security note**: The built-in fallback is `false`. Only use `true` behind a trusted reverse proxy such as Nginx or Vercel; otherwise clients may forge proxy headers to bypass IP-based limits.

- `secure_cookies`: Whether to add the `Secure` flag to the session cookie. The repository configuration currently sets it to `true`; disable it for plain HTTP local/VPS use.

    **Security note**: Only set to `true` when the site is served over HTTPS; otherwise browsers will refuse to send the cookie over HTTP.

- `id_generation`: Random URL generation configuration.
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
- `code_highlight`: code highlighting (highlight.js, client-side rendering).
    - `enabled`: Enable highlighting, default `true`.

    When enabled, code blocks in all Markdown-rendered locations (note read-only pages, editor live preview, benben feed, disclaimer) get automatic syntax highlighting with line numbers, following the site's light/dark theme with no server dependency.
- `cache`: page caching.
    - `enabled`: enable page caching, default `true`;
    - `backend`: configured backend, currently `redis`;
    - `default_timeout`: default timeout in seconds, currently `300`;
    - `redis_url`: Redis connection URL, overridden by `REDIS_URL`. An unreachable Redis automatically falls back to in-process SimpleCache.
- `note_editor`: editor behavior.
    - `live_preview_default`: default state of live rendering, currently `false`; the browser stores the user's choice in local storage;
    - `markdown_manual_url`: Markdown guide URL shown in the editor.
- `note_refs`: quick `#` references.
    - `enabled`: default `true`;
    - `search_limit`: maximum autocomplete results, default `8`;
    - `scan_limit`: maximum recently modified notes scanned, default `100`.
- `max_note_tags`: maximum tags per note, default `10`.
- `max_tag_length`: maximum characters per tag, default `24`.
- `max_folder_name_length`: maximum characters per folder name, default `32`.
- `avatar`: user avatars (generated via a third-party service, shown next to the current user in the navbar, benben post authors, and the user notes list title).
    - `enabled`: enable avatars, default `true`; set `false` to hide avatars entirely.
    - `url_template`: avatar URL template, default `https://cn.cravatar.com/avatar/{hash}?d=identicon&f=y`. Supports two placeholders: `{hash}` (`md5(username)` lowercase hex) and `{username}` (URL-encoded username). Since this site's users have no email, `md5(username)` is used as the hash; `d=identicon` makes Gravatar-style services generate a deterministic geometric avatar per hash. You can also swap in other username-seeded services (e.g. DiceBear: `https://api.dicebear.com/9.x/identicon/svg?seed={username}`).
    - `size`: default size in the template (currently only a fallback value; templates use fixed sizes per location).
- `images`: note image hosting (`/image/<username>/<image_id>` is publicly readable).
    - `enabled`: enable image hosting, default `true`;
    - `max_size_kb`: maximum image size, default `2048` (2MB);
    - `max_total_kb`: per-user image quota, default `51200` (50MB);
    - PNG, JPEG, GIF, and WebP are accepted after file-signature validation; SVG is rejected.
- `attachments`: note attachments (attachment button in editor uploads files, `/attachment/<u>/<id>` for public download).
    - `enabled`: enable attachments, default `true`; set `false` to hide the attachment button in the editor and return 404 on the management page;
    - `max_size_kb`: max single file size (KB), default `10240` (10MB);
    - `max_total_kb`: per-user total quota (KB), default `10240` (10MB);
    - `blocked_extensions`: list of blocked file extensions (blacklist mode), default includes `.exe`, `.bat`, `.sh`, `.zip` and other executables/archives.
- `comments`: comment system (`/comments/<target_type>/<target_id>`, supports notes and share pages).
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
- `RUSIN_DATA_DIR`: optional environment variable for the runtime data directory, defaulting to the current project directory (`file` backend only).

   Notes, images, attachments, and business-data JSON files are written under this directory; see the Zeabur layout above. On auto-deploy platforms, mount a persistent volume at `/data` and set `RUSIN_DATA_DIR=/data` to preserve data across deployments.
- `RUSIN_STORAGE`: optional env var to force the storage backend: `file` (default, local/VPS), `memory` (in-memory), `upstash` (external KV for serverless), `postgres` (Neon/PostgreSQL). When unset: `KV_REST_API_URL`/`KV_REST_API_TOKEN` set → `upstash`; `DATABASE_URL` set → `postgres`; serverless platform env detected → `memory`; otherwise `file`. See "Storage Backends" above.
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
   - `features`: **default** states. The current `config.json` explicitly enables `world_notes`, `benben`, `share_links`, `open_register`, `note_tags`, `note_folders`, `note_pins`, `heading_anchors`, `note_images`, `note_attachments`, and `comments`. `orgs` defaults to enabled when omitted. Legacy defaults for `note_refs`, `latex_render`, `code_highlight`, `avatar`, `note_images`, `note_attachments`, and `comments` come from their dedicated sections;
   - `admin_users`: usernames allowed to manage feature flags; can also be set via the `RUSIN_ADMIN` environment variable (comma-separated; the two are merged).

   After logging in, an admin can toggle features at `/admin/features`; saving takes effect immediately (no restart needed): the runtime state is persisted in the storage backend (`feature_flags.json` under the data directory for the `file` backend), and multi-instance deployments converge within a ~5s cache TTL. Disabled features return 404 and their navbar/home entry points are hidden automatically. All feature states are presented in the "Feature Status" section of the `/count` stats page (visible to everyone when no admin is configured, but nobody can change the switches then). Note: the serverless `memory` backend is not persistent — after a cold start, flags fall back to the `config.json` defaults.
