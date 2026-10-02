# Plugin System

Plugins are distributed as zip archives. Place a `*.plugin.zip` package in `RUSIN_DATA_DIR`; at startup the application validates and extracts it into `plugins/<namespace>/`, registers its Flask blueprint, and removes the package. **Serverless deployments (read-only filesystem) do not support plugins.**

## Plugin package structure

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

## Installation, update and security

- **Phase 1 (install)**: at startup the app scans the runtime directory for `*.plugin.zip`, validates and extracts them into `plugins/<namespace>/`, writes `auth_token` and `last_update` back into `desc.json`, then deletes the package. Checks include: zip path traversal, oversized extraction, package root must contain only `desc.json` / icon / `src/`, `auth_token` verification, and namespace conflicts (a different source may not reuse an existing namespace unless it declares `OVERRIDE`; the same source may). The plugin must contain a Blueprint in `src/app.py`; a missing one logs an error and is skipped without breaking the site.
- **Phase 2 (update)**: a background thread (every `plugins.update_interval_hours`, default 6 hours) scans `plugins/*/desc.json`; when `last_update` is older than `update_stale_days` (default 3 days) it fetches `upstream_repo` (3 second timeout), saves the result as `<namespace>.plugin.zip` and reruns Phase 1. Already-loaded plugins only pick up the new files after a restart.
- `plugins` config in `config.json`: `enabled` (default `true`), `update_interval_hours` (default `6`), `update_stale_days` (default `3`). Full details in [Configuration Options](configuration-en.md).
- Plugin blueprints are registered before the root short-link catch-all, so plugin routes are not swallowed by `/<id>`; a plugin that fails to import only disables itself and is logged, the site keeps running.
- Plugin POST forms must include `{{ csrf_token() }}` because CSRF protection is global.
- Plugins execute Python inside the application process. Install only trusted packages; `auth_token` is recommended so unofficial packages are rejected (the check is skipped only with the explicit bypass above).
