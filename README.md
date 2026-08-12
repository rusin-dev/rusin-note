> [!IMPORTANT]
>
> 注：如果你是 rusin-dev（本组织）的成员，想要贡献，请参见[协作指南](https://github.com/rusin-dev/rusin-note/blob/main/contribute.md)。

<div align="center">
    <a href="https://github.com/rusin-dev/rusin-note"><img width="15%" alt="logo" src="./image/logo.png" /></a>
    <h1><b>Rusin-Note</b></h1>
    <p><em>🖊︎ 一个受 note.ms 启发的轻量级云端剪贴板项目，专为 VPS 部署设计，开箱即用。</em></p>
    <p>
        简体中文 | <a href="https://github.com/rusin-dev/rusin-note/blob/main/README_en.md">English</a> | <a href="https://note.rusin7.com">Demo</a>
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

## 快速开始

### 要求

python 版本 $\geq 3.10$。

### 本地开发

1. 克隆代码

    ```bash
    git clone https://github.com/rusin-dev/rusin-note.git
    cd rusin-note
    ```

2. 安装依赖
   
   ```bash
   pip install -r requirements.txt
   ```

3. 启动服务

    ```bash
    python3 main.py
    ```

    然后打开 <https://localhost:8080> 查看效果。

### 线上部署

连接你的服务器，然后

1. 克隆代码

    ```bash
    git clone https://github.com/rusin-dev/rusin-note.git
    cd rusin-note
    ```

2. 安装依赖
   
   ```bash
   pip install -r requirements.txt
   ```

3. 启动服务

    ```bash
    python3 main.py

    # 后台运行
    nohup python3 rusin-note.py > app.log 2>&1 &
    ```

4. 配置 Nginx（可选）

    创建站点配置

    ```bash
    sudo nano /etc/nginx/sites-available/rusin-note
    ```

    复制以下内容：

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

    ```bash
    # 启用并重载
    sudo ln -s /etc/nginx/sites-available/rusin-note /etc/nginx/sites-enabled
    sudo nginx -t && sudo systemctl reload nginx
    sudo ufw allow 'Nginx Full'
    ```

## 项目结构

```plaintext
rusin-note:.
│  README_en.md
│  config.json（配置项）
│  Disclaimer.md（免责声明）
│  LICENSE
│  main.py（核心代码）
│  README.md
│  contribute.md（协作指南）
│  
├─image
│      logo.png
│      
├─.github
│  └─workflows
│          check.yml（测试 PR）
│          auto-merge.yml（自动合并）
│          labeler.yml（自动打标签）
│          
└─notes
```

### 配置项解析

- `max_note_size_mb`：笔记最大大小（单位：**MB**）默认 $1$。
- `sitename`：网页名称。填你的站点名。
- `rate_limit` 速率限制。
   
   - `window_seconds` ： 时间 $t$，默认 $60$；
   - `max_requests` ：请求数 $s$，默认 $30$;

   $t$ 秒内最大请求 $s$ 次。
- `id_generation` 随机 url 配置。
   - `length` ：长度，默认 $4$；
   - `use_uppercase` ：是否使用大写字母，默认 `false`；
   - `use_lowercase` ：是否使用小写字母，默认 `true`；
   - `use_digits` ：是否使用数字，默认 `false`；
- `session_timeout` 单次会话时间。
   - `enabled` ：是否开启，默认 `false`；
   - `minutes` ：设定时长，（单位：**秒**）默认 $1440$；

   当时间超过设定时，将登出访客账号。
- `password_policy`：密码策略，定义访客密码的复杂度要求。  
   - `min_length`：密码最小长度，默认 `8`；  
   - `require_uppercase`：是否必须包含大写字母，默认 `true`；  
   - `require_lowercase`：是否必须包含小写字母，默认 `true`；  
   - `require_digits`：是否必须包含数字，默认 `true`；  
   - `require_special`：是否必须包含特殊符号（不含 `/ \ ( ) " '`），默认 `true`； 