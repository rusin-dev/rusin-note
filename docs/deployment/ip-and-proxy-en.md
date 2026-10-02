# IP Rate Limiting and XFF Forgery Protection

> Reverse-proxy deployments (VPS / Vercel / Cloudflare) should read this page. Prerequisites live in the [Deployment Overview](index-en.md).

Rate limiting keys on the *real client IP*, while `X-Forwarded-For` (XFF), `X-Real-IP` and `CF-Connecting-IP` are request headers any client can forge — trusting them blindly lets an attacker rotate fake IPs and bypass every limit. The rules implemented in `app/core/ip_utils.py` are:

1. **Peer validation**: proxy headers are honoured only when the direct TCP peer (`remote_addr`) matches `trusted_proxies`; for direct public traffic all proxy headers are ignored.
2. **Strict parsing**: a header value must be a valid IP (`1.2.3.4:80`, `[2001:db8::1]:443`, `::ffff:1.2.3.4` are accepted); anything else is dropped so arbitrary strings can never create limiter buckets. A single header longer than 256 bytes is dropped in full (not parsed at all), and XFF chains longer than 16 entries keep only the first 16.
3. **XFF resolved from the right**: XFF is an append-only list, so the right-most entries are written by trusted proxies and the left-hand part may be forged. Trusted proxy addresses are skipped layer by layer (Cloudflare → Nginx) and the first untrusted valid IP wins.
4. **Visibility**: when proxy headers arrive from an untrusted peer, a throttled `检测到疑似伪造的代理头已忽略` warning is logged (at most once per IP per 5 minutes).

## Deployment notes

```nginx
# Nginx must *rewrite* XFF (append the upstream address it sees) or set X-Real-IP;
# otherwise a client-supplied XFF is forwarded untouched
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
```

- Same-host / same-private-network Nginx or Caddy: the default `["loopback", "private"]` in `trusted_proxies` is enough.
- Cloudflare (or Cloudflare → Nginx): add the `"cloudflare"` preset; it also honours `CF-Connecting-IP`, which Cloudflare overwrites.
- When the application port is **exposed directly to the internet** (including directly mapped Docker ports, where the peer may look like a gateway private address), narrow `trusted_proxies` to the concrete reverse-proxy IP (or only `["loopback"]`) — the `private` preset lets any host in those ranges forge proxy headers.
- Behind an internal load balancer whose address is a public IP, or when the proxy sits in a range other than the `private` preset: add the explicit IP/CIDR to `trusted_proxies`, otherwise proxy headers are ignored and every user shares one limit bucket (normal traffic starts getting throttled).
- At startup the effective policy is logged (`IP policy: ...` / `global IP rate limit: ...` / allow-list & block-list sizes) to the application log (`data/log/*.log`, falling back to stderr on serverless), so you can confirm the configuration.

> This project intentionally does **not** use Werkzeug's `ProxyFix`: it would let a forged XFF rewrite `request.remote_addr`, defeating the trusted-proxy check.

## Related configuration options

Full descriptions of `trust_proxy_headers`, `trusted_proxies`, `proxy_hops`, `ip_allowlist`, `ip_blocklist` and their environment variables (`RUSIN_TRUSTED_PROXIES`, `RUSIN_PROXY_HOPS`, `RUSIN_IP_ALLOWLIST`, `RUSIN_IP_BLOCKLIST`) are in [Configuration Options](../configuration-en.md).
