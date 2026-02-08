# CIRISNode Production Deployment

This guide covers deploying CIRISNode behind a reverse proxy with proper CORS, TLS, and security header configuration.

## Architecture

```
Browser (ethicsengine.org)
    |
    |  HTTPS (port 443)
    v
Caddy / Nginx (reverse proxy + TLS)
    |
    |  HTTP (port 8000, localhost only)
    v
CIRISNode (FastAPI + Uvicorn)
    |
    +---> PostgreSQL (port 5432)
    +---> Redis (port 6379)
```

## CORS Configuration

CIRISNode handles CORS via FastAPI's `CORSMiddleware` in `cirisnode/main.py`. The allowed origins, methods, and headers are defined there.

**The reverse proxy must NOT set its own CORS headers.** If both the proxy and the application set `Access-Control-*` headers, the browser receives conflicting or restrictive values and blocks requests.

### Symptoms of proxy CORS override

If the reverse proxy is overriding CORS, you will see responses like:

```
access-control-allow-origin: https://ciris.ai        # only one origin
access-control-allow-headers: Content-Type            # missing Authorization
access-control-allow-methods: GET, OPTIONS            # missing POST, PATCH, DELETE
```

When it should be (for a request from ethicsengine.org):

```
access-control-allow-origin: https://ethicsengine.org
access-control-allow-headers: Authorization, Content-Type, Accept, X-API-Key, stripe-signature
access-control-allow-methods: GET, POST, PATCH, DELETE, OPTIONS
access-control-allow-credentials: true
```

### Verify with curl

```bash
curl -sI -X OPTIONS \
  -H "Origin: https://ethicsengine.org" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: Content-Type,Authorization" \
  https://your-domain.example.com/api/v1/health
```

Check that `access-control-allow-origin` matches the `Origin` you sent, and that `Authorization` appears in `allow-headers`.

## Caddy Configuration

### Recommended: Let FastAPI handle CORS

The simplest and most maintainable approach is to let CIRISNode handle all CORS logic. The Caddyfile should be a plain reverse proxy with no `Access-Control-*` header directives:

```caddyfile
your-domain.example.com {
    reverse_proxy localhost:8000
}
```

Caddy will automatically provision TLS via Let's Encrypt. CIRISNode's `CORSMiddleware` will set the correct CORS headers based on the request origin.

**Do not add `header` directives for `Access-Control-*` in the Caddyfile.** If Caddy sets these headers, they will override or conflict with the ones set by FastAPI, breaking cross-origin requests from the frontend.

### If you must handle CORS in Caddy

If your deployment requires Caddy to handle CORS (e.g., multiple backends behind one domain), remove `CORSMiddleware` from `cirisnode/main.py` and configure Caddy instead:

```caddyfile
your-domain.example.com {
    @cors_preflight method OPTIONS
    handle @cors_preflight {
        header Access-Control-Allow-Origin "{header.Origin}"
        header Access-Control-Allow-Methods "GET, POST, PATCH, DELETE, OPTIONS"
        header Access-Control-Allow-Headers "Authorization, Content-Type, Accept, X-API-Key, stripe-signature"
        header Access-Control-Allow-Credentials "true"
        header Access-Control-Max-Age "600"
        respond "" 204
    }

    header Access-Control-Allow-Origin "{header.Origin}"
    header Access-Control-Allow-Credentials "true"
    header Vary "Origin"

    reverse_proxy localhost:8000
}
```

**Important:** Do not use both Caddy CORS headers and FastAPI `CORSMiddleware` at the same time. Pick one.

## Nginx Configuration

If using Nginx instead of Caddy, the same principle applies: either let FastAPI handle CORS (recommended) or handle it entirely in Nginx.

### Recommended: Plain reverse proxy

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.example.com;

    ssl_certificate     /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Do not add `add_header Access-Control-*` directives. Let FastAPI handle it.

## Security Headers

CIRISNode sets security headers via `SecurityHeadersMiddleware` in `cirisnode/main.py`:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- `Strict-Transport-Security: max-age=63072000; includeSubDomains` (HTTPS only)

If your reverse proxy also sets these headers, the values may conflict. Either let the application handle them or configure them only in the proxy — not both.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | (required) | PostgreSQL connection string |
| `REDIS_URL` | (required) | Redis connection string |
| `JWT_SECRET` | (required) | Secret key for JWT signing (shared with frontend's `AUTH_SECRET`) |
| `ENVIRONMENT` | `production` | `production`, `development`, or `test` |
| `FRONTEND_ORIGIN` | `https://node0.ciris.ai` | Additional allowed CORS origin |
| `NODE_ENV` | `production` | Set to `development` to allow `localhost:3000` as CORS origin |

## Docker Compose (Production)

```bash
docker compose up -d
```

The `docker-compose.yml` starts CIRISNode on port 8000, PostgreSQL on 5432, and Redis on 6379. Point your reverse proxy at `localhost:8000`.

## Allowed CORS Origins

The following origins are allowed by default (defined in `cirisnode/main.py`):

- `https://ciris.ai`
- `https://www.ciris.ai`
- `https://ethicsengine.org`
- `https://www.ethicsengine.org`
- `https://admin.ethicsengine.org`
- Value of `FRONTEND_ORIGIN` env var (default: `https://node0.ciris.ai`)
- `http://localhost:3000` (only when `NODE_ENV=development`)

To add more origins, update the `_allowed_origins` list in `cirisnode/main.py`.

## Troubleshooting

### "Failed to fetch" on all API calls from the frontend

1. Check CORS with the curl command above
2. If `access-control-allow-origin` doesn't match the frontend origin, the reverse proxy is likely overriding headers
3. Remove all `Access-Control-*` header directives from your proxy config
4. Reload the proxy (`caddy reload` or `nginx -s reload`)
5. Verify again with curl

### Preflight (OPTIONS) returns 405

FastAPI's CORSMiddleware handles OPTIONS automatically. If you get 405, the request may not be reaching FastAPI — check that your proxy forwards OPTIONS requests.

### CORS works for GET but not POST

Check that the preflight response includes the method in `access-control-allow-methods`. If your proxy overrides this header with only `GET, OPTIONS`, POST requests will be blocked.
