> [!IMPORTANT]
>
> Note: If you are a member of rusin-dev (this organization) and want to contribute, please see the [Collaboration Guide](https://github.com/rusin-dev/rusin-note?tab=contributing-ov-file). If you are not a member of this organization, you can join or open an Issue.

<div align="center">
    <a href="https://github.com/rusin-dev/rusin-note"><img width="15%" alt="logo" src="./app/static/image/logo.png" /></a>
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

![Screenshot](https://github.com/rusin-dev/rusin-note/blob/main/app/static/image/screenshots1.png)

## Features

- **Cloud clipboard and notes**: A lightweight Flask implementation for VPS or serverless deployment. Random short-path public notes for quick sharing, plus a private note list for signed-in users, and random-token share links with optional write-back for cross-device collaboration.
- **Rich Markdown rendering**: Bleach-sanitized Markdown with KaTeX math and syntax highlighting (server-side Pygments + client-side highlight.js fallback, following the light/dark theme). Read-only pages add a live `h1`-`h6` outline, heading anchors / deep links, and GitHub-style alert cards (`> [!NOTE]`, `> [!WARNING]`, … collapsible). Editor live preview can be toggled.
- **Note organization**: Tags (with autocomplete + list filtering), folders, pinned notes, and quick `#` references that turn a note ID into a hover-linked reference.
- **Image hosting and attachments**: Paste/drag image uploads (PNG/JPEG/GIF/WebP, validated by file signature), and attachments of arbitrary type (extension blacklist + quotas). Attachments require login to download by default, with a per-user in-flight concurrency gate that keeps slow/parallel connections from occupying workers.
- **Comments and benben feed**: Comments on note / share pages (anonymous allowed, cooldown, pagination) and a persistent lightweight benben feed (post when signed in, read anonymously).
- **Organizations and collaboration**: Owner / Admin / Member roles, invitation-code / public / approval join modes, and organization notes stored in an isolated namespace, fully separated from personal notes. Organization descriptions render as Markdown with LaTeX (`$...$` / `$$...$$`).
- **Homepage workbench**: When signed in, the homepage shows recently edited notes and a to-do list, with a notice banner that reads the first non-empty line of `NOTICE.txt`.
- **Multi-language and personalization**: Built-in Simplified Chinese / English (manual switch or browser-language fallback); per-user settings for simple mode, change password, and change username (all data migrated automatically).
- **Feature flags**: Admins toggle public notes, benben, share links, registration, images/attachments, comments, LaTeX, highlighting, and more at `/admin/features`; changes persist and take effect without restarting, and disabled routes return 404 with their entry points hidden.
- **Plugin system**: Drop a `*.plugin.zip` into the runtime directory to auto-extract, install, and load its Flask blueprint, with upstream auto-update (unsupported on read-only serverless). See [Plugin System](docs/plugins-en.md).
- **Deployment-friendly with baseline protection**: Configuration lives in `config.json`, with pluggable data backends (sqlite / file / upstash / postgres / memory); built-in CSRF protection, multi-tier IP rate limiting, `X-Forwarded-For` forgery protection, content sanitization, and an optional nginx + ModSecurity reverse-proxy WAF.

> Per-feature toggles, quotas and limits are documented in [Configuration Options](docs/configuration-en.md).

## Quick Start

### Requirements

Python version $\geq$ 3.10.

### Local Development

```bash
git clone https://github.com/rusin-dev/rusin-note.git
cd rusin-note
pip install -r requirements.txt
python3 -m app          # on Windows: python -m app; port controlled by the PORT env var, default 8080
```

Open <http://localhost:8080>. Local/VPS defaults to the `sqlite` backend, persisted under `RUSIN_DATA_DIR` (default `data/`).

### Development & Testing

```bash
pip install -r requirements-dev.txt     # installs pytest (pulls in requirements.txt)
pytest tests/                           # whole end-to-end suite (isolated temp data dir, never touches local data)
pytest tests/test_org.py -q             # single module / keyword filter: pytest tests/ -q -k images
python tests/frontend_check.py          # front-end syntax check (Jinja2 + inline CSS/JSON; inline JS only when Node is installed)
```

- Tests use **pytest + logging**: `tests/conftest.py` pins `RUSIN_STORAGE=file`, switches to a temporary `RUSIN_DATA_DIR`, and clears runtime caches, so tests never touch your local data; full conventions live in `tests/README.md`.
- All front-end assets are inlined in the Jinja2 templates (no separate JS/CSS), so run `python tests/frontend_check.py` after touching templates.
- CI (`.github/workflows/check.yml`) runs on push / PR to `dev` and is path-filtered: the `frontend` job runs the syntax check, the `test` job runs pytest plus an HTTP health check.

## Deployment

Full per-platform steps are split into `docs/deployment/`. Start with the [Deployment Overview](docs/deployment/index-en.md) (SECRET_KEY, common env vars, proxy/cookie defaults), then pick a method:

| Method | Best for | Guide |
|---|---|---|
| **Vercel** | Serverless, recommended; attach Neon for persistence | [docs/deployment/vercel-en.md](docs/deployment/vercel-en.md) |
| **AWS Lambda** | Serverless, needs a credit card, not recommended | [docs/deployment/aws-lambda-en.md](docs/deployment/aws-lambda-en.md) |
| **VPS / traditional server** | Self-hosted, gunicorn + Nginx reverse proxy | [docs/deployment/vps-en.md](docs/deployment/vps-en.md) |
| **Zeabur** | GitHub auto-deploy, needs a persistent volume (optional Redis) | [docs/deployment/zeabur-en.md](docs/deployment/zeabur-en.md) |

Advanced deployment topics:

- How the storage backends (sqlite / file / upstash / postgres / memory) are enabled and auto-detected → [Storage Backends](docs/deployment/storage-backends-en.md)
- Real client IP resolution, XFF forgery protection, and IP allow/block lists → [IP Rate Limiting and XFF Forgery Protection](docs/deployment/ip-and-proxy-en.md)
- Optional nginx + ModSecurity + OWASP CRS reverse-proxy WAF (documented in the Chinese docs for now) → [waf.md (中文)](docs/deployment/waf.md)

## Documentation

| Doc | Contents |
|---|---|
| [Deployment Overview](docs/deployment/index-en.md) | Per-platform entry, SECRET_KEY, env vars, proxy defaults |
| [Storage Backends](docs/deployment/storage-backends-en.md) | Five backends and their auto-detect priority |
| [Configuration Options](docs/configuration-en.md) | Every `config.json` setting, defaults, security notes, `RUSIN_*` env vars |
| [IP Rate Limiting and XFF Forgery Protection](docs/deployment/ip-and-proxy-en.md) | Trusted-proxy check, right-to-left XFF, IP lists |
| [Plugin System](docs/plugins-en.md) | Package structure, install/update flow, security |
| [Collaboration Guide](docs/CONTRIBUTING.md) | Contributing flow |
| [Disclaimer](docs/Disclaimer-en.md) | Terms of use |

## Project Structure

```plaintext
rusin-note/
├─ config.json          configuration (see docs/configuration-en.md)
├─ NOTICE.txt           homepage notice banner content (first non-empty line)
├─ README.md / README_en.md
├─ requirements.txt / requirements-dev.txt / pytest.ini
├─ vercel.json          Vercel serverless configuration
├─ lambda_handler.py    AWS Lambda entry (Mangum)
├─ .env.example         environment variable example
│
├─ api/                 serverless entry (Vercel Python entry)
├─ app/                 application
│  ├─ __init__.py       Flask app factory create_app
│  ├─ __main__.py       dev entry: python3 -m app
│  ├─ wsgi.py           WSGI entry (gunicorn)
│  ├─ core/             shared kernel: storage / store / auth / middleware / ip_utils /
│  │                    concurrency / feature_flags / plugins / totp / notes / tags /
│  │                    folders / pins / prefs / cleanup / i18n …
│  ├─ apps/             feature Apps (each owns views.py, business logic in service.py)
│  │  └─ registry.py    registers every App blueprint in order (incl. plugins + catch-all)
│  └─ static/           bundled static assets (logo / images)
│
├─ templates/           Jinja2 templates (all front-end CSS/JS inlined, bilingual)
├─ tests/               pytest end-to-end tests + frontend_check.py syntax check
├─ docs/                documentation (deployment/ guides, configuration, plugins, …)
└─ .github/             ISSUE_TEMPLATE and workflows (check / codeql / release / sync …)
```

Architecture: a shared kernel `app/core/` (infrastructure + cross-feature domain services) plus feature Apps `app/apps/<feature>/` (each with its own `views.py` blueprint and optional `service.py`); all modules access data only through the unified `app/core/storage.py` interface with pluggable backends. For detailed module responsibilities and the route table, see the Skill: `.opencode/skills/rusin-note-codebase/SKILL.md`.
