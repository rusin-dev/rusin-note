# AWS Lambda (Serverless)

> A credit card is required, so this option is not recommended. Prerequisites live in the [Deployment Overview](index-en.md).

`lambda_handler.py` (Mangum WSGI adapter) is included:

1. Package the repository (including `templates/`, `config.json`, etc.);
2. Handler: `lambda_handler.handler`, with API Gateway proxy integration;
3. Env vars as on Vercel (`RUSIN_SECRET_KEY` plus storage: `DATABASE_URL` or `KV_REST_API_URL` / `KV_REST_API_TOKEN`);
4. Memory ≥ 512MB recommended (Markdown rendering).

> Serverless environments skip background threads and local WAF provisioning, and without a persistent backend the data falls back to the volatile `memory` backend. See [Storage Backends](storage-backends-en.md).
