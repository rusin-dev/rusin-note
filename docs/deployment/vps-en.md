# VPS / Traditional Server

> Prerequisites (SECRET_KEY, env vars, proxy/cookie defaults) live in the [Deployment Overview](index-en.md). Local/VPS defaults to the `sqlite` backend — see [Storage Backends](storage-backends-en.md).

Connect to your server, then:

## 1. Clone the repository

```bash
git clone https://github.com/rusin-dev/rusin-note.git
cd rusin-note
```

## 2. Install dependencies

```bash
pip install -r requirements.txt
```

## 3. Start the server

```bash
python3 -m app

# Run in the background
nohup python3 -m app > app.log 2>&1 &

# Recommended in production (Linux, gunicorn — install it separately: pip install gunicorn)
# The listen port comes from PORT; replace 8080 yourself if PORT is unset (must match the reverse-proxy target below)
gunicorn 'app.wsgi:app' -b 0.0.0.0:${PORT:-8080} --workers 2 --threads 4
```

## 4. Configure Nginx (optional)

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
> is not trusted, all proxy headers are ignored and the direct IP is used. See
> [Real Client IP and XFF Forgery Protection](ip-and-proxy-en.md).

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
