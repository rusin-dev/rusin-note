> [!IMPORTANT]
>
> Note: If you are a member of rusin-dev (this organization) and want to contribute, please see the [Collaboration Guide](https://github.com/rusin-dev/rusin-note?tab=contributing-ov-file). If you are not a member of this organization, you can join or open an Issue.

<div align="center">
    <a href="https://github.com/rusin-dev/rusin-note"><img width="15%" alt="logo" src="./image/logo.png" /></a>
    <h1><b>Rusin-Note</b></h1>
    <p><em>🖊︎ A lightweight cloud clipboard project inspired by note.ms, designed for VPS deployment, ready to use out of the box.</em></p>
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

- **Cloud clipboard that works out of the box**: A lightweight Flask implementation for VPS or personal-server deployment, letting you save and access text quickly from any browser.
- **Public and private notes**: Use random short paths for public notes, or keep private note lists under guest accounts for both temporary sharing and personal storage.
- **Secure share links**: Generate random-token share links for user notes, with optional write-back support for simple cross-device collaboration.
- **Markdown and LaTeX rendering**: Read-only pages and the benben feed support Markdown and KaTeX math, making the app useful for code snippets, notes, documentation, and formulas.
- **Benben feed**: A built-in lightweight feed where logged-in users can post and anonymous users can read, with live preview, paginated loading, and post cooldowns.
- **Multi-language UI**: Simplified Chinese and English are built in, with manual switching and browser-language fallback.
- **Deployment-friendly configuration**: Common options live in `config.json`, including note expiration, session timeout, password policy, trusted proxy IP handling, and HTTPS cookies.
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

    Then open <https://localhost:8080> to view the result.

### Production Deployment

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
/data/users.json
/data/sessions.json
/data/shares.json
/data/benben.json
/data/log/
```

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
│
├─app (core code)
│  │  __init__.py
│  │  __main__.py (entry: python3 -m app)
│  │  auth.py (password hashing & session auth)
│  │  background.py (background cleanup tasks)
│  │  config.py (configuration loading & global constants)
│  │  extensions.py (Flask extension instances)
│  │  i18n.py (multi-language support)
│  │  logger.py (logging)
│  │  middleware.py (request hooks and rate-limit helpers)
│  │  notes.py (note file operations & stats)
│  │  store.py (users/sessions/shares/benben data storage)
│  │  theme.py (theme and static resource helpers)
│  │  utils.py (shared utilities)
│  │  wsgi.py (WSGI entry)
│  │
│  └─views (blueprints and routes)
│          __init__.py (blueprint registration)
│          _helpers.py (view helpers)
│          auth.py (login and registration)
│          benben.py (benben feed)
│          home.py (home page)
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
│  ├─auth (auth pages)
│  ├─benben (benben pages)
│  ├─errors (error pages)
│  ├─notes (note pages)
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

- `max_note_size_kb`：Maximum note size (in **KB**), default `512` (0.5 MB).
- `sitename`: Website name. Enter your site name.
- `rate_limit`：Rate limiting configuration.

    - `window_seconds`：Time window $t$, default `60`.
    - `max_requests`：Maximum number of requests $s$, default `30`.

    Maximum $s$ requests allowed within $t$ seconds.

- `get_rate_limit`：Independent rate limiting for GET requests.
    - `window_seconds`：Time window $t$, default `60`.
    - `max_requests`：Maximum number of requests $s$, default `45`.

    Maximum $s$ GET requests (page loads, favicon, etc.) within $t$ seconds.

- `save_rate_limit`：Independent rate limiting for save-type POST requests (note saves / share write-backs).
    - `window_seconds`：Time window $t$, default `60`.
    - `max_requests`：Maximum number of requests $s$, default `120`.

    Maximum $s$ note saves within $t$ seconds, decoupled from the global POST limit (`rate_limit`) so frequent saves are not throttled.

- `trust_proxy_headers`：Whether to trust `X-Forwarded-For` / `X-Real-IP` headers set by a reverse proxy, default `false`.

    **Security note**: Disabled by default — rate limiting is always based on the direct TCP peer IP to prevent clients from forging headers to bypass limits. Only set to `true` when deployed behind a trusted reverse proxy (e.g. Nginx).

- `secure_cookies`：Whether to add the `Secure` flag to the session cookie, default `false`.

    **Security note**: Only set to `true` when the site is served over HTTPS; otherwise browsers will refuse to send the cookie over HTTP.

- `id_generation`：Random URL generation configuration.
    - `length`：URL length, default `4`.
    - `use_uppercase`：Use uppercase letters, default `false`.
    - `use_lowercase`：Use lowercase letters, default `true`.
    - `use_digits`：Use digits, default `false`.

- `share_token`：Share link token configuration.
    - `length`：Token length, default `64`.
    - `use_uppercase`：Use uppercase letters, default `true`.
    - `use_lowercase`：Use lowercase letters, default `true`.
    - `use_digits`：Use digits, default `true`.

- `session_timeout`：Session timeout configuration.
    - `enabled`：Enable session timeout, default `false`.
    - `minutes`：Timeout duration (in **minutes**), default $15$.

    Visitors will be logged out when the session exceeds the configured time.
- `note_expiration`：Note auto-cleanup (notes/clipboards are deleted after their save duration expires).
    - `enabled`：Enable auto-cleanup, default `false`.
    - `hours`：Save duration (in **hours**), default $24$.

    When enabled, notes (public + private) not modified within the configured hours are deleted by a background thread, which scans every 30 minutes.
- `latex_render`：LaTeX formula rendering.
    - `enabled`：Enable rendering, default `true`.
    - `cdn`：Base directory of KaTeX static files, default jsdelivr (e.g. BootCDN mirror for China: `https://cdn.bootcdn.net/ajax/libs/katex/0.16.11`).

    When enabled, Markdown read-only pages support `$...$` inline and `$$...$$` display math (KaTeX, client-side rendering, no server dependency).
- `password_policy`: password policy, defining the complexity requirements for guest passwords.  
   - `min_length`: minimum password length, default `8`;  
   - `max_length`: maximum password length, default `128` (hard cap `128`, preventing oversized passwords from entering the PBKDF2 slow hash and consuming CPU);  
   - `require_uppercase`: whether uppercase letters are required, default `true`;  
   - `require_lowercase`: whether lowercase letters are required, default `true`;  
   - `require_digits`: whether digits are required, default `true`;  
   - `require_special`: whether special characters (excluding `/ \ ( ) " '`) are required, default `true`;
- `RUSIN_DATA_DIR`: optional environment variable for the runtime data directory, defaulting to the current project directory.

   Notes, users, sessions, shares, benben posts, and logs are written under this directory as `notes/`, `users.json`, `sessions.json`, `shares.json`, `benben.json`, and `log/`. On auto-deploy platforms such as Zeabur, mount a persistent volume at `/data` and set `RUSIN_DATA_DIR=/data` to prevent clipboard data from being cleared on each deployment.
- **Multi-language**: The interface supports Simplified Chinese and English. Language switch links (`/lang/zh` / `/lang/en`) are provided on the right side of the navbar; the preference is remembered via a cookie (`rusin-lang`); when unset, it falls back to the browser's `Accept-Language`, defaulting to Chinese. After switching, all site text (navbar, buttons, hints, error messages, benben previews, etc.) switches language instantly.
- `benben` (feed at `/benben`, logged-in users can post, anonymous read-only).
   - `max_length`: max length of a single feed post (in **characters**), default `1024` (~1KB);
   - `page_size`: posts loaded per batch, default `50`;
   - `cooldown_seconds`: minimum interval between two posts by the same user (in **seconds**), default `3`;
   - `max_height_px`: maximum display height of rendered feed content (in **px**), default `1000`, overflow scrolls within the content area;

   Content supports Markdown and LaTeX math (`$...$` / `$$...$$`, controlled by the `latex_render` switch); the post form has a live preview (client-side marked.js rendering, which filters dangerous tags and links too); rendering is sanitized with bleach to prevent XSS; each page shows `page_size` posts, loaded in batches via "Load more"; loading and posting are both subject to request rate limits (GET/POST), and posting is also subject to a per-user cooldown (`cooldown_seconds`); each post's header shows the poster's IP (whether proxy headers are trusted follows `trust_proxy_headers`; not shown for old data without an IP field).
