# Configuration Options

This document lists every `config.json` setting and environment variable, its meaning, default value, and security notes. For deployment steps see the [Deployment Overview](deployment/index-en.md), for backend selection see [Storage Backends](deployment/storage-backends-en.md), and for reverse-proxy/real-IP handling see [IP Rate Limiting and XFF Forgery Protection](deployment/ip-and-proxy-en.md).

> Defaults below reflect the shipped `config.json`; where a code fallback exists for a missing key it is noted inline.

## Basics and site

- `max_note_size_kb`: Maximum note size (in **KB**), default `512` (0.5 MB — this is the value shipped in `config.json`; the code falls back to `5120` when the key is missing).
- `sitename`: Website name. Enter your site name.
- `global_cdn`: Base URL of the global CDN for front-end static assets.
    - Default `https://cdn.jsdmirror.cn`.

    Front-end assets are loaded by concatenating this base URL: FontAwesome icons, the marked editor script, DOMPurify, and KaTeX (all use `npm/`-style paths, so `https://cdn.jsdelivr.net` and other npm CDNs also work). You can replace the whole CDN in `config.json` to match your network environment without touching code.

## Rate limiting

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

## IP and cookies (reverse proxy)

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

## ID and token generation

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

## Session and expiration

- `session_timeout`: Session timeout configuration.
    - `enabled`: Enable session timeout, default `false`.
    - `minutes`: Timeout duration (in **minutes**), currently `1440` in `config.json`.

    Visitors will be logged out when the session exceeds the configured time.
- `note_expiration`: Note auto-cleanup (notes/clipboards are deleted after their save duration expires).
    - `enabled`: Enable auto-cleanup, default `false`.
    - `hours`: Save duration (in **hours**), default $24$.

    When enabled, notes (public + private) not modified within the configured hours are deleted by a background thread, which scans every 30 minutes.

## Rendering

- `latex_render`: LaTeX formula rendering.
    - `enabled`: Enable rendering, default `true`.
    - KaTeX static assets are loaded from the `global_cdn` base URL (default jsdmirror; jsdelivr, etc. also work).

    When enabled, Markdown read-only pages support `$...$` inline and `$$...$$` display math (KaTeX, client-side rendering, no server dependency).
- `code_highlight`: code highlighting (server-side Pygments + client-side highlight.js fallback).
    - `enabled`: Enable highlighting, default `true`.

    Code blocks are always tokenized and colored by Pygments on the server. This switch additionally controls client-side highlight.js: when enabled, every Markdown-rendered location (note read-only pages, editor live preview, benben feed, comments, disclaimer) gets a fallback pass for languages Pygments does not recognize, generates line numbers, and follows the site's light/dark theme. When disabled, line numbers and client-side highlighting are removed while server-side coloring remains.

## Cache

- `cache`: page caching.
    - `enabled`: enable page caching, default `true`;
    - `backend`: configured backend, currently `redis`;
    - `default_timeout`: default timeout in seconds, currently `300`;
    - `redis_url`: Redis connection URL, overridden by `REDIS_URL`. An unreachable Redis automatically falls back to in-process SimpleCache.

      Note: rate-limit counters also read `REDIS_URL` (set it to share counters across instances; otherwise they live in process memory).

## Editor and homepage

- `note_editor`: editor behavior.
    - `live_preview_default`: default state of live rendering, currently `false`; the browser stores the user's choice in local storage;
    - `markdown_manual_url`: Markdown guide URL shown in the editor.
- `home_page`: homepage workbench.
    - `recent_notes_limit`: number of recently edited notes shown on the homepage, default `5`;
    - `recent_shares_limit`: reserved limit for recent shares (the homepage does not render a share list yet), default `5`.
- `todos`: homepage workbench to-do list.
    - `max_items`: maximum number of to-dos per user, default `100`;
    - `max_length`: maximum characters per to-do item, default `200`.

## Note organization

- `note_refs`: quick `#` references.
    - `enabled`: default `true`;
    - `search_limit`: maximum autocomplete results, default `8`;
    - `scan_limit`: maximum recently modified notes scanned, default `100`.
- `max_note_tags`: maximum tags per note, default `10`.
- `max_tag_length`: maximum characters per tag, default `24`.
- `max_folder_name_length`: maximum characters per folder name, default `64`.
- `max_folder_depth`: maximum folder nesting depth (counted by `/` separators), default `8`.
- `max_note_id_length`: maximum note ID length, default `250` (compatibility cap for long links).

## Avatars

- `avatar`: user avatars (generated via a third-party service, shown next to the current user in the navbar, benben post authors, and the user notes list title).
    - `enabled`: enable avatars, default `true`; set `false` to hide avatars entirely.
    - `url_template`: avatar URL template, default `https://cn.cravatar.com/avatar/{hash}?d=identicon&f=y`. Supports two placeholders: `{hash}` (`md5(username)` lowercase hex) and `{username}` (URL-encoded username). Since this site's users have no email, `md5(username)` is used as the hash; `d=identicon` makes Gravatar-style services generate a deterministic geometric avatar per hash. You can also swap in other username-seeded services (e.g. DiceBear: `https://api.dicebear.com/9.x/identicon/svg?seed={username}`).
    - `size`: default size in the template (currently only a fallback value; templates use fixed sizes per location).

## Images and attachments

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
    - These concurrency caps stop "open a thousand connections and trickle each at 1KB/s" or "100 threads downloading 100 files" abuse, where the request rate stays under the limiter but workers stay occupied and egress bandwidth is saturated: over the cap, downloads return 429 with `Retry-After` and uploads return a 429 JSON error the editor can display. Over-limit requests are **rejected, not queued** (queueing would occupy workers just the same). Counting is **per process** (`app/core/concurrency.py`), so with N gunicorn workers the effective cap is about `N × value`; strict cross-instance counting would need an atomic counter in external storage, which this project does not use;
    - Attachments are referenced as links by default; if one note embeds several attachment images (more concurrent requests than the cap), raise `max_concurrent_downloads` or set it to `0`;
    - `blocked_extensions`: list of blocked file extensions (blacklist mode), default includes `.exe`, `.bat`, `.sh`, `.zip` and other executables/archives. **The configured value carries no leading dot** (`config.json` lists `exe`, `zip`; the code adds the `.`), so do not write `.exe` — it would never match.

## Comments and feed

- `comments`: comment system (`/comments/<target_type>/<path:target_id>`, supports notes and share pages).
    - `enabled`: enable comments, default `true`; set `false` to return 404 on comment pages;
    - `max_length`: max length of a single comment (in **characters**), default `1024` (~1KB);
    - `max_comments`: max comments per target (note/share), default `200`;
    - `cooldown_seconds`: minimum interval between two comments by the same user (in **seconds**), default `3`;
    - `page_size`: comments loaded per batch, default `50`;
    - `max_height_px`: maximum display height of rendered comment content (in **px**), default `280`, overflow scrolls within the content area.
- `benben` (feed at `/benben`, logged-in users can post, anonymous read-only).
   - `max_length`: max length of a single feed post (in **characters**), default `1024` (~1KB);
   - `page_size`: posts loaded per batch, default `50`;
   - `cooldown_seconds`: minimum interval between two posts by the same user (in **seconds**), default `3`;
   - `max_height_px`: maximum display height of rendered feed content (in **px**), default `280`, overflow scrolls within the content area (keeps long posts from dominating the screen);
   - `max_posts`: maximum number of posts persisted, default `200` (keeps external KV value size bounded; oldest posts are dropped);

   Content supports Markdown and LaTeX math (`$...$` / `$$...$$`, controlled by the `latex_render` switch); the form provides a sanitized marked.js live preview; server-rendered Markdown is sanitized with Bleach; loading and posting are rate-limited, and posting also has a per-user cooldown. Logged-in users can click Reply to replace the editor content with `|| @username: original content`.

## Password policy

- `password_policy`: password policy, defining the complexity requirements for guest passwords.  
   - `min_length`: minimum password length, default `8`;  
   - `max_length`: maximum password length, default `128` (hard cap `128`, preventing oversized passwords from entering the PBKDF2 slow hash and consuming CPU);  
   - `require_uppercase`: whether uppercase letters are required, default `true`;  
   - `require_lowercase`: whether lowercase letters are required, default `true`;  
   - `require_digits`: whether digits are required, default `true`;  
   - `require_special`: whether special characters (excluding `/ \ ( ) " '`) are required, default `true`;

## Data directory and storage backend (environment variables)

- `RUSIN_DATA_DIR`: optional environment variable for the runtime data directory, defaulting to `data` (i.e. `data/` under the project). **Content data** (notes / images / attachments / collection JSON) is written here only by the local `sqlite` / `file` backends, but the `log/` and `plugins/` directories are always created under it regardless of backend (serverless logs fall back to stderr).

   Notes, images, attachments, and business-data JSON files are written under this directory; see the [Zeabur layout](deployment/zeabur-en.md). On auto-deploy platforms, mount a persistent volume at `/data` and set `RUSIN_DATA_DIR=/data` to preserve data across deployments.
- `RUSIN_STORAGE`: optional env var to force the storage backend: `sqlite` (default, local/VPS), `file` (plain files — notes as `.txt` text), `memory` (in-memory), `upstash` (external KV for serverless), `postgres` (Neon/PostgreSQL). When unset: `KV_REST_API_URL`/`KV_REST_API_TOKEN` set → `upstash`; `DATABASE_URL` set → `postgres`; serverless platform env detected → `memory`; otherwise `sqlite`. See [Storage Backends](deployment/storage-backends-en.md).

## Multi-language

- **Multi-language**: The interface supports Simplified Chinese and English. Language switch links (`/lang/zh` / `/lang/en`) are provided on the right side of the navbar; the preference is remembered via a cookie (`rusin-lang`); when unset, it falls back to the browser's `Accept-Language`, defaulting to Chinese. After switching, all site text (navbar, buttons, hints, error messages, benben previews, etc.) switches language instantly.

## Plugins

- `plugins`: plugin installation and update settings (see [Plugin System](plugins-en.md)).
    - `enabled`: default `true`, automatically disabled on serverless platforms;
    - `update_interval_hours`: update-check interval, default `6`;
    - `update_stale_days`: minimum age of `last_update` before fetching upstream, default `3`.

## Feature flags

- `features` / `admin_users` feature flags (#90).
   - `features`: **default** states. The current `config.json` explicitly lists `world_notes`, `benben`, `share_links`, `open_register`, `note_tags`, `note_folders`, `note_pins`, `heading_anchors`, `markdown_alerts`, `note_images`, `note_attachments`, and `comments` (12 entries).

     **Precedence**: the 7 "legacy" features — `note_refs`, `latex_render`, `code_highlight`, `avatar`, `note_images`, `note_attachments`, `comments` — always take their defaults from their own dedicated sections (e.g. `images.enabled`, `attachments.enabled`, `comments.enabled`); same-named keys in this section have no effect for them. Every other feature (including `orgs`) defaults to enabled when omitted here.
   - `admin_users`: usernames allowed to manage feature flags; can also be set via the `RUSIN_ADMIN` environment variable (comma-separated; the two are merged).

   After logging in, an admin can toggle features at `/admin/features`; saving takes effect immediately (no restart needed): the runtime state is persisted in the storage backend (`feature_flags.json` under the data directory for the `sqlite`/`file` backends), and multi-instance deployments converge within a ~5s cache TTL. Disabled features return 404 and their navbar/home entry points are hidden automatically. All feature states are presented in the "Feature Status" section of the `/count` stats page (visible to everyone when no admin is configured, but nobody can change the switches then). Note: the serverless `memory` backend is not persistent — after a cold start, flags fall back to the `config.json` defaults.

## Logging and debug

- `logger`: logging.
    - `max_size`: byte cap per log file (RotatingFileHandler `maxBytes`), default `4294967296` (4 GiB);
    - `path_pattern`: log file path template, default `log/{timestamp}.log`, resolved relative to the data directory (i.e. `<RUSIN_DATA_DIR>/log/`);

    When the log file cannot be created (e.g. a read-only serverless filesystem), logging falls back to stderr and enters the platform log stream.
- `debug`: log verbosity switch, default `false`. It does **not** enable Flask's debug mode; the mapping is `false` → `INFO` (verbose) and `true` → `ERROR` (quiet). Keep it `false` in production.
