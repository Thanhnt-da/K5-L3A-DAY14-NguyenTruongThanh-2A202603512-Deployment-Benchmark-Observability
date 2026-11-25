# Deployment Information

## Public URL
https://agent-production-c93599a7.up.railway.app

## Platform
Railway: project `k5-day14-agent`, environment `production`.
- Service `agent`: built from `06-lab-complete/` using `railway.toml` (builder `DOCKERFILE`, `healthcheckPath = "/health"`).
- Service `Redis`: a Railway managed Redis database with a persistent volume.

Deployed with:
```bash
cd 06-lab-complete
railway init --name k5-day14-agent
railway add --database redis
railway add --service agent
railway variables --set 'REDIS_URL=${{Redis.REDIS_URL}}' ...   # see the variables list below
railway up --service agent
railway domain --service agent
```

## Test Commands

Set `BASE` to the public URL. `AGENT_API_KEY` is the key set on Railway; it is not stored in this repo.

```bash
BASE=https://agent-production-c93599a7.up.railway.app
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Observed results (2026-11-25):

| Check | HTTP code | Body |
|---|---|---|
| `GET /health` | 200 | `{"status":"ok","environment":"production","uptime_seconds":29.6}` |
| `GET /ready` | 200 | `{"ready":true,"redis":true}` |
| `POST /ask` without key | 401 | — |
| `POST /ask` with key | 200 | `{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","cost_usd":1.9e-05}` |

`python check_production_ready.py --public-url https://agent-production-c93599a7.up.railway.app` returned `Result: 12/12 tiêu chí đạt · 44/44 checks passed`, including `✅ Public URL: GET .../health → 200`.

## Environment Variables Set
Set on the Railway `agent` service, not in code:
- `AGENT_API_KEY`: secret, set by the owner in the Railway dashboard
- `REDIS_URL`: `${{Redis.REDIS_URL}}` (reference to the Railway Redis private URL `redis.railway.internal:6379`)
- `ENVIRONMENT`: `production`
- `RATE_LIMIT_PER_MINUTE`: `10`
- `DAILY_BUDGET_USD`: `1.0`
- `MONTHLY_BUDGET_USD`: `10.0`
- `PORT`: injected by Railway; the container listens on `${PORT:-8000}`
- `LOG_LEVEL`: not set, so it defaults to `INFO`

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
