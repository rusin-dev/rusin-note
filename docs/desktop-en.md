# Desktop client (rusin-note-desktop)

The desktop app is a **native WebView shell** around the rusin-note web app: a standalone window loads your site directly — no browser, no hunting for tabs.

**All note data lives in the web app.** The desktop client stores no notes, attachments or sync state locally. Its data directory holds only three things: client configuration (site URL, window geometry), logs, and WebView session data (cookies / localStorage) so you stay signed in. Install it on another machine, sign in with the same account, and you see the same notes.

The code lives in the [`desktop/`](../desktop/) subdirectory of this repository — a standalone uv project (its own `pyproject.toml` and `uv.lock`) that shares the repo with the web app but has no dependency on it.

## User guide

### Install

1. Open your site's `/downloads` page and grab the build for your OS (Windows `.zip` / macOS `.zip` containing an `.app` / Linux `.tar.gz`).
2. Extract anywhere and run `rusin-note-desktop` (`rusin-note-desktop.exe` on Windows). Portable — no installer, no registry writes.
3. On first launch a "connect to site" page appears. Enter your rusin-note URL (e.g. `https://note.example.com`) and connect.
4. Sign in inside the window as usual. The session is persisted, so the next launch goes straight to your site.

Windows needs the [WebView2 runtime](https://developer.microsoft.com/microsoft-edge/webview2/) (usually preinstalled with Edge on Win10/11); Linux needs GTK3 and WebKit2GTK 4.1.

### Menu

| Menu | Action |
|---|---|
| File → Change site… | Reopen the connect page and switch to another rusin-note instance |
| File → Check for updates… | Read the site's `/downloads/manifest.json` and offer to open the download page when a newer build exists |
| File → Quit | Close the window |
| View → Reload | Reload the current page (falls back to the connect page when the site is unreachable) |
| View → Fullscreen | Toggle fullscreen |

Window size, position and maximized state are remembered on close and restored on the next launch. Only one instance may run at a time (a second launch exits immediately), so two processes never write the same config concurrently.

External links inside the site (including OAuth redirects) open in the system browser; attachment downloads save to your normal download folder.

### Local data directory

| OS | Path |
|---|---|
| Windows | `%APPDATA%\rusin-note-desktop\` |
| macOS | `~/Library/Application Support/rusin-note-desktop/` |
| Linux | `$XDG_DATA_HOME/rusin-note-desktop/` (default `~/.local/share/rusin-note-desktop/`) |

Inside: `config.json` (client config), `logs/desktop.log` (rotating, 4 MB × 3), `webview/` (session data), `instance.lock` (single-instance lock).

Environment variables:

- `RUSIN_DESKTOP_DATA_DIR`: override the data directory, for portable runs and tests;
- `RUSIN_DESKTOP_DEBUG`: set to `1` to enable WebView debug logging (off by default).

> `webview/` contains your sign-in cookies — treat it like a browser profile and keep it out of shared backups or public folders. Deleting it signs you out.

### Updates

The client does not auto-update. "Check for updates…" compares the bundled `data/metadata.json` (version + channel) against the site manifest: the channel must match (`stable` only accepts `stable`), and when the site version is newer you are offered the `/downloads` page. Extract the new build over the old one — config and sign-in state are unaffected.

## Admins: publishing installers

Installers are **self-hosted on your site**, not on GitHub Releases, and never committed to Git.

### 1. Build

From `desktop/` (requires [uv](https://docs.astral.sh/uv/)):

```bash
uv sync                              # install deps (incl. PyInstaller from the dev group)
uv run python release/build.py       # build for the current platform
```

Artifacts land in `desktop/dist/downloads/`:

```plaintext
dist/downloads/
├─ rusin-note-desktop-0.1.0-windows-x64.zip      installer
└─ manifest-windows-x64.json                     per-platform manifest (with sha256)
```

Useful flags: `--version` (defaults to `pyproject.toml`), `--channel stable|beta`, `--notes "release notes"`, `--released-at YYYY-MM-DD`.

After building on all three platforms, put the partial manifests and installers in one directory and merge:

```bash
uv run python release/build.py --merge dist/downloads
```

Merging verifies that version/channel agree across platforms and writes `manifest.json` ordered Windows → macOS → Linux.

### 2. Publish

Copy the directory's contents into the web app's data directory under `downloads/` (the `downloads.dir` setting, default `<RUSIN_DATA_DIR>/downloads/`):

```plaintext
<RUSIN_DATA_DIR>/downloads/
├─ manifest.json
├─ rusin-note-desktop-0.1.0-windows-x64.zip
├─ rusin-note-desktop-0.1.0-macos-arm64.zip
└─ rusin-note-desktop-0.1.0-linux-x64.tar.gz
```

Publishing takes effect immediately (the service layer does not cache the manifest; the landing page's display delay is just the view cache TTL). With no manifest, `/downloads` shows "no installers yet" instead of erroring.

Multi-instance deployments (Vercel / Lambda) need shared or object storage for the installers — `downloads/` is a local directory and serverless read-only filesystems are a poor fit. For those deployments, point `/downloads` at a self-hosted VPS site or turn off the `downloads` feature flag.

### 3. CI builds

[`.github/workflows/desktop-build.yml`](../.github/workflows/desktop-build.yml):

- Pushing a `desktop-v*` tag or a manual workflow_dispatch (version / channel / release notes inputs) triggers a three-platform matrix build; each platform runs its own test suite first;
- Tags with a prerelease suffix (e.g. `desktop-v1.0.0-rc.1`) are automatically assigned to the `beta` channel;
- The `merge` job combines the manifests and uploads a `downloads` artifact — download it and drop it onto your server;
- Pushes / PRs touching `desktop/**` only run the desktop unit tests, no build.

### 4. Validation and security

The manifest is external input, so the service layer validates every field: artifact ids allow only lowercase alphanumerics plus `_-`, filenames must match the suffix whitelist, sha256 must be 64 lowercase hex characters, artifact paths are realpath-checked against traversal, and entries above `downloads.max_file_mb` are dropped. Download responses carry `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff`, support Range requests for resumable downloads, and are throttled by `downloads.download_rate_limit`.

The landing page shows each installer's full SHA256 so users can verify it themselves:

```bash
sha256sum rusin-note-desktop-0.1.0-windows-x64.zip
```

Related settings: [Configuration Options](configuration-en.md#desktop-client-downloads).

## Developers

```plaintext
desktop/
├─ main.py                  entry point (uv run python main.py)
├─ pyproject.toml / uv.lock  standalone uv project, Python >= 3.12
├─ data/metadata.json       bundled version info (written at build time)
├─ src/
│  ├─ app.py                data dir → single-instance lock → config → window
│  ├─ core/
│  │  ├─ window.py          WebView shell, menu, window geometry, update check
│  │  ├─ setup.py           first-run "connect to site" page (self-contained HTML)
│  │  ├─ site.py            site URL normalization and validation
│  │  ├─ data.py            DataService (client config only)
│  │  └─ logger.py          rotating file log
│  └─ modules/
│     ├─ storage/config.py  JSON config store (atomic writes)
│     ├─ updater.py         site manifest fetch and version comparison
│     └─ ai_copilot/        AI provider adapters (kept module, not wired into the shell yet)
├─ release/
│  ├─ build.py              build + archive + manifest generation/merge
│  └─ rusin-note-desktop.spec  PyInstaller onedir config
└─ tests/                   pytest (cases marked `network` need a live site)
```

```bash
uv sync                                   # install deps
uv run python main.py                     # run the client
uv run pytest tests/ -q -m "not network"  # unit tests (skip network cases)
uv run pytest tests/ -q                   # including network cases
uv run python release/build.py            # build the current platform's installer
```

The desktop project is **uv-only** (`uv run` / `uv sync` / `uv pip install`) — do not install with pip directly or create a separate virtualenv.

Implementation notes:

- WebView comes from [pywebview](https://pywebview.flowrl.com/): EdgeChromium/WebView2 via pythonnet on Windows, Cocoa/WebKit on macOS, GTK/WebKit2GTK on Linux;
- `webview.start(private_mode=False, storage_path=<data dir>/webview)` keeps cookies and localStorage — this is what makes it more convenient than a browser, since the session survives restarts;
- `OPEN_EXTERNAL_LINKS_IN_BROWSER=True` sends external links and OAuth to the system browser; `ALLOW_DOWNLOADS=True` permits attachment downloads;
- Window geometry is saved in the `closing` event (size is skipped while maximized so the restored size stays correct);
- PyInstaller runs in onedir mode; pywebview's bundled hook collects the WebView2 DLLs and JS assets, so the spec only adds platform-specific hiddenimports and `data/metadata.json`.