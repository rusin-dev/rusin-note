<div align="center">
    <a href="https://github.com/rusin-dev/rusin-note"><img width="10%" alt="logo" src="./image/logo.png" /></a>
    <h1><b>Rusin-Note</b></h1>
    <p><em>🖊︎ A lightweight cloud clipboard project that resembles note.ms can be deployed by VPS.</em></p>
    <p>
        <a href="https://github.com/rusin-dev/rusin-note/blob/main/README.md">简体中文</a> | English | <a href="https://note.rusin7.com">Demo</a>
    </p>
    <p align="center">
        <a href="https://github.com/rusin-dev/rusin-note/blob/main/LICENSE"><img src="https://img.shields.io/github/license/rusin-dev/rusin-note" alt="License" /></a>
        <a href="https://github.com/rusin-dev/rusin-note/releases"><img src="https://img.shields.io/github/release/rusin-dev/rusin-note" alt="latest version" /></a>
        <a href="https://github.com/rusin-dev/rusin-note/releases"><img src="https://img.shields.io/github/downloads/rusin-dev/rusin-note/total?color=%239F7AEA&logo=github" alt="Downloads" /></a>
        <a href="https://github.com/rusin-dev/rusin-note/stargazers"><img src="https://img.shields.io/github/stars/rusin-dev/rusin-note" alt="Stars" /></a>
        <a href="https://github.com/rusin-dev/rusin-note/network/members"><img src="https://img.shields.io/github/forks/rusin-dev/rusin-note" alt="Forks" /></a>
        <a href="https://github.com/rusin-dev/rusin-note/actions/workflows/ci-tests.yml?query=branch%3Amain">
        <img src="https://img.shields.io/github/actions/workflow/status/rusin-dev/rusin-note/check.yml?branch=main&label=tests" alt="CI Build"></a>
        <a href="https://pypi.org/project/pandera/"><img src="https://img.shields.io/pypi/v/pandera.svg" alt="PyPI version shields.io"></a>
        <a href="https://pypi.python.org/pypi/"><img src="https://img.shields.io/pypi/l/pandera.svg" alt="PyPI license"></a>
        <a href="https://www.repostatus.org/#active"><img src="https://img.shields.io/badge/repo%20status-Active-Green" alt="Project Status: Active – The project has reached a stable, usable state and is being actively developed."></a>
        <a href="https://pypi.python.org/pypi/pandera/"><img src="https://img.shields.io/pypi/pyversions/pandera.svg" alt="PyPI pyversions">
        </a>
    </p>
</div>

## Quick Start

### Requirements

Python version $\geq 3.10$.

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
    python3 main.py
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
    python3 main.py

    # Run in the background
    nohup python3 rusin-note.py > app.log 2>&1 &
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
            proxy_pass http://127.0.0.1:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }
    }
    ```

    ```bash
    # Enable and reload
    sudo ln -s /etc/nginx/sites-available/rusin-note /etc/nginx/sites-enabled
    sudo nginx -t && sudo systemctl reload nginx
    sudo ufw allow 'Nginx Full'
    ```

## Project Structure

```plaintext
rusin-note:.
│  README_en.md
│  config.json (configuration)
│  Disclaimer.md (disclaimer)
│  LICENSE
│  main.py (core code)
│  README.md
│  contribute.md (collaboration guide)
│  
├─image
│      logo.png
│      
├─.github
│  └─workflows
│          check.yml (test PR)
│          auto-merge.yml (auto-merge)
│          labeler.yml (auto-labeling)
│          
└─notes
```

### Configuration Options

- `max_note_size_mb`：Maximum note size (in **MB**), default `1`.
- `sitename`: Website name. Enter your site name.
- `rate_limit`：Rate limiting configuration.

    - `window_seconds`：Time window $t$, default `60`.
    - `max_requests`：Maximum number of requests $s$, default `30`.

    Maximum $s$ requests allowed within $t$ seconds.

- `id_generation`：Random URL generation configuration.
    - `length`：URL length, default `4`.
    - `use_uppercase`：Use uppercase letters, default `false`.
    - `use_lowercase`：Use lowercase letters, default `true`.
    - `use_digits`：Use digits, default `false`.

- `session_timeout`：Session timeout configuration.
    - `enabled`：Enable session timeout, default `false`.
    - `minutes`：Timeout duration (in **seconds**), default `1440`.

    Visitors will be logged out when the session exceeds the configured time.
- `password_policy`: password policy, defining the complexity requirements for guest passwords.  
   - `min_length`: minimum password length, default `8`;  
   - `require_uppercase`: whether uppercase letters are required, default `true`;  
   - `require_lowercase`: whether lowercase letters are required, default `true`;  
   - `require_digits`: whether digits are required, default `true`;  
   - `require_special`: whether special characters (excluding `/ \ ( ) " '`) are required, default `true`;