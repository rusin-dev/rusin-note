# rusin-note-desktop

<div align="center">
  <p><i>Put rusin-note on your desktop: a native WebView shell — all note data stays on the web app</i></p>
</div>

<p align="center">
  <a href="https://www.python.org/">
    <img src="https://img.shields.io/badge/Python-3.12%2B-3776AB?style=for-the-badge&amp;logo=python&amp;logoColor=white" alt="Python 3.12+">
  </a>
</p>

<p align="center">
  <a href="../README.md">中文</a> | <b>English</b>
</p>

## What is this

A desktop client for the rusin-note web app. A standalone window loads your site directly — no browser, no hunting for tabs.

**Notes are never stored locally.** Notes, attachments and sync all live in the web app. The local data directory holds only client configuration (site URL, window geometry), logs, and WebView session data (cookies / localStorage) so you stay signed in. Install the client on another machine, sign in with the same account, and you see the same notes.

Features:

- Native window on your site, sign-in state persists across launches
- First-run setup asks for the site URL; switch instances any time from the menu
- Remembers window size / position / maximized state; single instance only
- External links and OAuth go to the system browser; attachments download normally
- "Check for updates" compares against the site's `/downloads/manifest.json` and points you at the new build
- Portable: unzip and run, no registry writes

> This is a monorepo subdirectory of [rusin-note](../../README.md). It shares the repository with the web app but has no dependency on it. Installers are self-hosted and served from the web app's `/downloads` page.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
uv sync                    # install dependencies
uv run python main.py      # run the desktop client
```

On first launch a "connect to site" page appears. Enter your rusin-note URL (e.g. `https://note.example.com`), connect, then sign in inside the window.

Runtime requirements: Windows needs [WebView2](https://developer.microsoft.com/microsoft-edge/webview2/) (usually preinstalled on Win10/11); Linux needs GTK3 and WebKit2GTK 4.1.

## Tests

```bash
uv run pytest tests/ -q -m "not network"   # unit tests (skip network cases)
uv run pytest tests/ -q                    # includes network cases (need a live site)
```

## Building installers

```bash
uv run python release/build.py                        # build for the current platform
uv run python release/build.py --merge dist/downloads # merge per-platform manifests
```

Artifacts land in `dist/downloads/` (installer + `manifest.json`). Drop that whole directory into the web app's data directory under `downloads/` to publish. See the [desktop client docs](../../docs/desktop.md).

## Layout

```plaintext
desktop/
├─ main.py                  entry point
├─ data/metadata.json       bundled version info (written at build time)
├─ src/
│  ├─ app.py                data dir → single-instance lock → config → window
│  ├─ core/                 window / setup / site / data / logger
│  └─ modules/              storage (config only) / updater / ai_copilot
├─ release/                 build.py + PyInstaller spec
└─ tests/                   pytest
```

## Conventions

- **uv only**: use `uv sync`, `uv run ...`, `uv pip install ...` for every install/run. Do not use pip directly or create a separate virtualenv.
- `uv.lock` must be committed for reproducible builds; `build/` and `dist/` are build output and stay out of Git.
- Config keys are two-segment `module.key` (e.g. `site.url`, `window.width`); see `src/modules/storage/config.py`.

## License

See [LICENSE](../LICENSE).