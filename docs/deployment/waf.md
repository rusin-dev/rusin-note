# 反向代理 WAF（ModSecurity + OWASP CRS）

> 可选的纵深防御层，适用于 VPS / 传统服务器 + Nginx 反代部署（见 [VPS 部署](vps.md)）。无服务器部署（Vercel / Lambda）自动跳过：只读文件系统，且平台本身自带 WAF。

Flask 进程内没有可用的开源 WAF 引擎，业界轻量做法是把 **nginx + ModSecurity + OWASP CoreRuleSet（CRS）** 放在应用前面：SQL 注入、XSS、命令注入、扫描器探测等在进 Flask 之前就被拦掉，与应用内的 Flask-Limiter（速率限制）构成两层防御。

## 供给配置

其中可自动化的部分由启动脚本完成——把 `config.json` 的 `waf.enabled` 改成 `true`（或临时设环境变量 `RUSIN_WAF=1`），然后照常启动：

```bash
python3 -m app                  # 自动下载 CRS 规则集 + 生成全部 WAF 配置
python3 -m app --waf-refresh    # 强制重新下载并重新校验规则集
python3 -m app.core.waf         # gunicorn / Lambda 等其它部署方式：手动供给一次
```

引擎本体是系统包，脚本**只探测并提示、绝不代为安装**（也不会擅自 reload nginx，除非显式设 `waf.auto_reload=true`）：

```bash
sudo apt-get install -y nginx libnginx-mod-http-modsecurity   # Debian / Ubuntu
sudo dnf install -y nginx nginx-mod-modsecurity               # RHEL / Fedora
sudo apk add nginx nginx-mod-http-modsecurity                 # Alpine
```

## 生成物

生成物都在 `<RUSIN_DATA_DIR>/waf/`（默认 `data/waf/`）：

| 路径 | 说明 | 会被覆盖 |
|---|---|---|
| `crs/rules/*.conf` | OWASP CRS 规则集（下载，版本 + SHA256 双锁定） | 换版本时 |
| `modsecurity.conf` | 引擎主配置：拦截模式、请求体上限、审计日志、Include 顺序 | 每次启动 |
| `crs-setup.conf` | CRS 调优：检测等级、异常分阈值 | 每次启动 |
| `exclusions.conf` | 内容型端点的误报排除（见下） | 每次启动 |
| `custom.conf` | **你的自定义规则**（id 用 1100-9999） | 只生成一次 |
| `nginx/nginx.conf` | 独立运行的完整配置，可 `nginx -c` 直接跑 | 每次启动 |
| `nginx/rusin-note.conf` | server 块片段，可 include 进现有 nginx 的 `conf.d/` | 每次启动 |
| `log/audit.log` | ModSecurity 审计日志（只记被拦截与 4xx/5xx） | nginx 写 |

## 启用反代

启用反代（二选一），启用前务必先校验：

```bash
sudo nginx -t -c /path/to/data/waf/nginx/nginx.conf          # 只校验
sudo nginx -c /path/to/data/waf/nginx/nginx.conf             # 方式一：独立跑一个反代实例
sudo ln -s /path/to/data/waf/nginx/rusin-note.conf /etc/nginx/conf.d/
sudo systemctl reload nginx                                  # 方式二：并进现有 nginx
```

**上线顺序**：先用 `waf.mode="detectiononly"`（只记日志不拦截）跑几天，确认 `waf/log/audit.log` 里没有误报，再改成 `"on"`。

## 关于误报

本站的核心用法就是把 SQL、JS、shell 片段当笔记存起来，直接开 CRS 会让「粘贴一段代码」被判成攻击而 403。因此 `exclusions.conf` 默认对**内容型端点**（笔记正文保存/导入、组织笔记、犇犇、评论、待办、图床与附件上传）按 tag 关闭注入类规则——这些正文渲染前都会经 bleach 清洗，不是可执行输入；协议强制（920）、方法强制（911）、扫描器识别（913）等仍全程生效。不需要这层排除时设 `waf.default_exclusions=false`。

## 常用配置项（`config.json` 的 `waf` 段）

- `crs_version` / `crs_url` / `crs_sha256`：锁定的规则集版本与校验和。**升级 CRS 必须三个一起改**——校验和对不上会直接拒绝安装（这是防供应链投毒的边界，不要为了省事把 `verify_checksum` 关掉）。
- `mode`：`on`（拦截）/ `detectiononly`（只记录）。
- `paranoia_level`：CRS 检测等级 1-4，越高越严也越容易误报，默认 1。
- `inbound_anomaly_threshold` / `outbound_anomaly_threshold`：异常分阈值，默认 5 / 4（单条 CRITICAL 记 5 分即触发）。
- `listen` / `server_name` / `upstream` / `upstream_port`：反代监听与回源；`upstream_port=0` 表示跟随 `PORT` 环境变量。
- `body_limit_kb`：请求体上限，`0` = 自动取笔记/导入/附件上限的较大值。**配小了会让上传先被 nginx 回 413**。
- `response_inspection`：出站响应体检测，默认关闭（渲染用户 Markdown/代码的站点误报多且耗 CPU）。
- `validate_config` / `auto_reload`：生成后是否跑 `nginx -t`（默认开，只读）、是否代为 reload nginx（默认关，需 root）。

## 注意

- 反代生效后应用看到的直连对端就是 nginx，必须保证 `trust_proxy_headers=true` 且 `trusted_proxies` 覆盖回源地址（同机默认 `["loopback","private"]` 已覆盖），否则应用只看到反代 IP，全站每 IP 限流会把所有用户算成同一个人并集体 429。供给脚本检测到这种情况会主动告警。详见 [真实客户端 IP 与防 XFF 伪造](ip-and-proxy.md)。
- 无服务器部署（Vercel / Lambda）自动跳过：只读文件系统，且平台本身自带 WAF。
- 引擎缺失、下载失败、`nginx -t` 不通过都**不会导致应用启动失败**，只在启动输出里给出原因和下一步命令；规则集会保留上一个可用版本。
