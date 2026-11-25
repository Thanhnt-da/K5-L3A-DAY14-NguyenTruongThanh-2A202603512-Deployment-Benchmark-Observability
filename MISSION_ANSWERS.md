# Day 14 Lab — Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found in `01-localhost-vs-production/develop/app.py`

1. **Hardcoded secrets in source code** (`develop/app.py` lines 17–18): `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` and `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`. If pushed to Git, credentials are leaked permanently in git history.
   - *Fixed in production:* `production/config.py` lines 27 & 32 read `OPENAI_API_KEY` and `AGENT_API_KEY` from environment variables via `os.getenv(...)`, with `validate()` (lines 37–46) failing fast if `AGENT_API_KEY` is missing in production.
2. **No environment-based config management** (`develop/app.py` lines 21–22): `DEBUG = True` and `MAX_TOKENS = 500` are hardcoded constants, making it impossible to switch behavior across dev/staging/production without editing code.
   - *Fixed in production:* Centralized `Settings` dataclass in `production/config.py` lines 14–50 reading all settings from env vars.
3. **Unstructured `print()` logging & secret leakage in logs** (`develop/app.py` lines 33–34, 38): Uses `print("[DEBUG] ...")` instead of structured logs and explicitly prints `OPENAI_API_KEY` to stdout.
   - *Fixed in production:* `production/app.py` lines 28–32 configure JSON-formatted `logging`, and lines 111–122 log only safe metadata (`event`, `question_length`, `client_ip`, `response_length`) without any secrets.
4. **No health check or readiness endpoints** (`develop/app.py` lines 42–43): Missing `/health` and `/ready`, so cloud platforms and load balancers cannot detect crashes or know when the app is ready to serve traffic.
   - *Fixed in production:* `production/app.py` implements `GET /health` (lines 135–149) and `GET /ready` (lines 152–161, returning `503` while not ready).
5. **Hardcoded `localhost`, fixed port `8000`, and `reload=True`** (`develop/app.py` lines 49–54): Binding to `localhost` makes the server unreachable outside a container, fixed port `8000` breaks cloud platforms that inject `PORT`, and `reload=True` wastes resources and causes instability in production.
   - *Fixed in production:* `production/app.py` lines 194–199 bind `host=settings.host` (`0.0.0.0`), `port=settings.port` (from `PORT` env var), and enable `reload` only when `DEBUG=true`.
6. **No graceful shutdown / lifecycle handling** (`develop/app.py`): No `lifespan` hook or `SIGTERM` handler; stopping the process abruptly cuts off in-flight requests.
   - *Fixed in production:* `production/app.py` uses `@asynccontextmanager async def lifespan(...)` (lines 39–67) to flip `is_ready = False` on shutdown and registers a `SIGTERM` signal handler (lines 180–189).
7. **No CORS configuration or input validation** (`develop/app.py` lines 30–39): Accepts `question` only as a raw query parameter with no CORS policy or structured JSON validation.
   - *Fixed in production:* `production/app.py` configures `CORSMiddleware` with `settings.allowed_origins` (lines 77–82) and validates the JSON body in `POST /ask` (lines 102–108), returning `422` when `question` is missing.

---

### Exercise 1.2: Running the develop version

Command:
```bash
curl -i -X POST "http://localhost:8000/ask?question=Hello"
```

Observed output:
```http
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 08:33:35 GMT
server: uvicorn
content-length: 103
content-type: application/json

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

Server stdout (showing leaked secret in `print()`):
```text
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
```

---

### Exercise 1.3: Develop vs. Production Comparison

Production verification outputs:
- `GET /health` → `200 OK`: `{"status":"ok","uptime_seconds":2.1,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T08:34:03.236952+00:00"}`
- `GET /ready` → `200 OK`: `{"ready":true}`
- `POST /ask` (`{"question":"Hello"}`) → `200 OK`: `{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","model":"gpt-4o-mini"}`

| Feature | Develop (`develop/app.py`) | Production (`production/app.py` & `config.py`) | Why Important? |
|---------|-----------------------------|------------------------------------------------|----------------|
| **Config & Secrets** | Hardcoded constants (`OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG=True`) | Read from environment variables via `Settings` dataclass + `validate()` fail-fast | Prevents secret leaks in Git and allows deploying the exact same image to dev/staging/prod with different configs (12-Factor). |
| **Host & Port** | `host="localhost"`, `port=8000`, `reload=True` | `host="0.0.0.0"`, `port=int(os.getenv("PORT", "8000"))`, `reload=settings.debug` | Containers and cloud platforms (Railway/Render) require binding `0.0.0.0` and dynamically injected `PORT`; `reload=True` should never run in prod. |
| **Logging** | `print()` statements that also print `OPENAI_API_KEY` | Structured JSON `logging` with safe metadata only (`event`, `question_length`, `client_ip`) | Enables log aggregation/searching (Loki, Datadog) and avoids leaking credentials into logs. |
| **Health & Readiness** | None | `GET /health` (liveness) and `GET /ready` (readiness, returns `503` when not ready) | Allows orchestrators to restart crashed containers and prevents load balancers from routing traffic before startup completes or during shutdown. |
| **Shutdown** | Abrupt termination | FastAPI `lifespan` + `SIGTERM` handler (`is_ready = False`, drains in-flight requests) | Prevents dropped requests and partial writes during rolling deploys or restarts. |
| **API & CORS** | Query param `?question=...`, no CORS | JSON body `{"question": "..."}` with `422` validation + `CORSMiddleware` | Enforces clean API contracts and restricts browser origins for security. |
| **Observability** | None | `GET /metrics` endpoint exposing uptime, version, environment | Provides baseline operational visibility for monitoring/Prometheus scraping. |

---

## Part 2: Docker Containerization

### Exercise 2.1: Dockerfile questions (`02-docker/develop/Dockerfile`)

1. **Base image:** `python:3.11` (full Debian-based Python distribution, ~1 GB).
2. **Working directory:** `/app` (`WORKDIR /app`).
3. **Why `COPY requirements.txt` before `COPY app.py`?** Docker caches image layers sequentially. Dependencies change far less often than application code. Copying `requirements.txt` and running `pip install` first lets Docker reuse the cached dependency layer whenever only `app.py` changes, making rebuilds much faster.
4. **Difference between `CMD` and `ENTRYPOINT`:**
   - `ENTRYPOINT` sets the fixed executable that always runs when the container starts; arguments passed to `docker run <image> <args>` are appended to it.
   - `CMD` provides the default command or default arguments to `ENTRYPOINT`, and is completely overridden if you pass a command at `docker run`.

### Exercise 2.2: Build and run `my-agent:develop`

Built from repository root:
```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run -d --name k5-dev-test -p 8000:8000 my-agent:develop
curl -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker?"
```

Observed output:
```http
HTTP 200 OK
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

### Exercise 2.3: Multi-stage build (`02-docker/production/Dockerfile`) & Image Size Comparison

- **Stage 1 (`builder`):** Starts from `python:3.11-slim`, installs build tools (`gcc`, `libpq-dev`), and runs `pip install --no-cache-dir --user -r requirements.txt` into `/root/.local`.
- **Stage 2 (`runtime`):** Starts fresh from `python:3.11-slim`, creates a non-root user `appuser`, copies only the compiled packages (`/root/.local` → `/home/appuser/.local`) and application files, sets `USER appuser`, defines `HEALTHCHECK`, and starts `uvicorn` with 2 workers.
- **Why is the production image smaller?** It uses `python:3.11-slim` instead of full `python:3.11` and discards `gcc`, `libpq-dev`, apt caches, and build artifacts from Stage 1—only the runtime dependencies and source code enter the final image.

Measured with `docker images`:
- **Develop (`my-agent:develop`):** `1.67 GB` (~1,670 MB)
- **Production (`my-agent:advanced`):** `240 MB`
- **Difference:** **~85.6% smaller** (`1,430 MB` saved)

### Exercise 2.4: Docker Compose stack (`02-docker/production/docker-compose.yml`)

Architecture diagram:
```text
Client (HTTP :80 / HTTPS :443)
        │
        ▼
  ┌───────────┐
  │   nginx   │  (Reverse proxy & load balancer, exposes :80/:443)
  └─────┬─────┘
        │  internal bridge network
        ▼
  ┌───────────┐
  │   agent   │  (FastAPI on :8000, not exposed directly to host)
  └──┬─────┬──┘
     │     │
     ▼     ▼
┌───────┐ ┌────────┐
│ redis │ │ qdrant │  (persistent volumes: redis_data, qdrant_data)
│ :6379 │ │ :6333  │
└───────┘ └────────┘
```

- **Services started:** `nginx` (`nginx:alpine`), `agent` (built from `02-docker/production/Dockerfile` target `runtime`), `redis` (`redis:7-alpine`), and `qdrant` (`qdrant/qdrant:v1.9.0`).
- **Communication:** All 4 services share the isolated `internal` bridge network and address each other by service DNS name (`redis://redis:6379/0`, `http://qdrant:6333`, `agent:8000`). Only `nginx` publishes ports `80`/`443` to the host. `agent` waits for `redis` and `qdrant` healthchecks (`condition: service_healthy`).

Observed test results via Nginx (`docker compose -p k5-day14-docker up -d --build`):
- `GET http://localhost/health`:
  ```http
  HTTP/1.1 200 OK
  Server: nginx
  X-Frame-Options: DENY
  X-Content-Type-Options: nosniff
  X-XSS-Protection: 1; mode=block

  {"status":"ok","uptime_seconds":5.0,"version":"2.0.0","timestamp":"2026-11-25T08:51:29.465080"}
  ```
- `POST http://localhost/ask` (`{"question":"Explain microservices"}`):
  ```http
  HTTP 200 OK
  {"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
  ```

---

## Part 3: Cloud Deployment

### Exercise 3.1: Railway Deployment (`06-lab-complete/`)

- **Platform:** Railway (Docker build from `06-lab-complete/railway.toml` + `Dockerfile`, with managed Redis)
- **Public URL:** *(pending — will be filled in right after Railway deployment)*
- **Screenshots:** `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png` (see `DEPLOYMENT.md`)

### Comparison: `railway.toml` vs `render.yaml`

| Aspect | `railway.toml` (Railway) | `render.yaml` (Render Blueprint) |
|--------|--------------------------|----------------------------------|
| **Format & Scope** | TOML file configuring a **single service's** build and deploy behavior (`[build]`, `[deploy]`). | YAML Blueprint defining **multiple services, databases, and env vars** together as Infrastructure-as-Code. |
| **Build Config** | `[build] builder = "DOCKERFILE"`, `dockerfilePath = "Dockerfile"`. | `runtime: docker`, `dockerfilePath: ./Dockerfile` under `services:`. |
| **Health Check** | `healthcheckPath = "/health"` and `healthcheckTimeout = 100`. | `healthCheckPath: /health`. |
| **Secrets / Env Vars** | Configured via Railway Dashboard or `railway variables set` (kept out of `railway.toml`). | Declared in `envVars:` using `generateValue: true` (auto-generated secret) or `sync: false` (prompted in dashboard) without hardcoding values. |
| **Add-ons (Redis)** | Added on the Railway project canvas and linked via `${{Redis.REDIS_URL}}`. | Can be declared directly in `render.yaml` or attached via dashboard and passed as `REDIS_URL`. |

### Exercise 3.3: GCP Cloud Run CI/CD Pipeline (`cloudbuild.yaml` & `service.yaml`)

1. **Trigger & Test (`cloudbuild.yaml` Step 1):** Triggered on push to `main`, runs `pytest tests/ -v` inside `python:3.11-slim` so broken code fails before building.
2. **Build & Cache (Step 2):** Builds the Docker image tagged with `$COMMIT_SHA` and `latest`, using `--cache-from=gcr.io/$PROJECT_ID/ai-agent:latest` for faster builds.
3. **Push (Step 3):** Pushes both image tags to Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **Deploy to Cloud Run (Step 4 & `service.yaml`):** Deploys the immutable `$COMMIT_SHA` image to managed Cloud Run (`asia-southeast1`, public ingress, `512Mi` RAM / `1` vCPU, concurrency `80`, autoscaling `minScale: 1` to avoid cold starts up to `maxScale: 10`), injecting secrets (`OPENAI_API_KEY`, `AGENT_API_KEY`) from Secret Manager and configuring `livenessProbe` (`/health`) and `startupProbe` (`/ready`).

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/`)

Started with `AGENT_API_KEY=secret-key-123`.

- **Without API key (`401 Unauthorized`):**
  ```http
  HTTP/1.1 401 Unauthorized
  date: Wed, 25 Nov 2026 08:55:04 GMT
  server: uvicorn
  content-length: 67
  content-type: application/json

  {"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
  ```

- **With valid API key (`X-API-Key: <MASKED>`, `200 OK`):**
  ```http
  HTTP/1.1 200 OK
  date: Wed, 25 Nov 2026 08:55:04 GMT
  server: uvicorn
  content-length: 122
  content-type: application/json

  {"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
  ```

### Exercise 4.2 & 4.3: JWT Authentication & Rate Limiting (`04-api-gateway/production/`)

- **Rate limiter analysis (`rate_limiter.py`):**
  - **Algorithm:** Sliding Window Counter (stores a `deque` of request timestamps per `user_id` and evicts timestamps older than `now - window_seconds`).
  - **Limits:** Standard user (`rate_limiter_user`) = **10 requests / 60 seconds**; Admin (`rate_limiter_admin`) = **100 requests / 60 seconds**.
  - **Bypass / higher limit for admin:** The route checks the JWT user role (`role == "admin"`) and routes admin requests to `rate_limiter_admin` (100 req/min) or skips the strict user limiter instead of using `rate_limiter_user` (10 req/min).

- **Obtaining JWT token (`POST /auth/token` with `student` / `demo123`):**
  Returned `200 OK` with `token_type: bearer` (`Authorization: Bearer <REDACTED_JWT>`).

- **Authenticated request #1 (`200 OK`):**
  ```http
  HTTP/1.1 200 OK
  date: Wed, 25 Nov 2026 08:55:37 GMT
  server: uvicorn
  content-type: application/json
  x-content-type-options: nosniff
  x-frame-options: DENY
  x-xss-protection: 1; mode=block
  referrer-policy: strict-origin-when-cross-origin

  {"question":"ExplainJWT","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":9,"budget_remaining_usd":1.8e-05}}
  ```

- **Rate limit loop results (requests 2–11):**
  Requests 1–10 returned `HTTP 200`; starting from Request 11, the server returned `HTTP 429 Too Many Requests`:
  ```http
  HTTP/1.1 429 Too Many Requests
  date: Wed, 25 Nov 2026 08:55:39 GMT
  server: uvicorn
  x-ratelimit-limit: 10
  x-ratelimit-remaining: 0
  x-ratelimit-reset: 1795597000
  retry-after: 58
  content-type: application/json

  {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":58}}
  ```

### Exercise 4.4: Cost Guard Design & Why Both Rate Limit and Cost Guard Are Needed

- **How Cost Guard works:** Track each user's (and global) LLM spend in **Redis** keyed by period, e.g. `budget:{user_id}:{YYYY-MM}` (or `{YYYY-MM-DD}` for daily limits) with a TTL (`32 * 86400` seconds for monthly keys). Before calling the LLM, read the current spend (`float(r.get(key) or 0)`) and reject with **`402 Payment Required`** if `current + estimated_cost > budget_usd`. After the LLM responds, atomically increment the counter with `r.incrbyfloat(key, actual_cost)` and log a warning when usage crosses 80%.
- **Why both are needed:** **Rate limiting** protects **request velocity / availability** (preventing traffic spikes, DDoS, or tight loops from overwhelming CPU/upstream quotas), whereas **Cost Guard** protects **money / spend** (a single long-context prompt or steady low-rate usage well under 10 req/min can still rack up huge LLM token bills over hours or days).

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health Checks (`/health` vs `/ready`)

- **`GET /health` (Liveness Probe):** Answers *"Is the process alive?"* Cloud platforms (Railway, Render, Kubernetes) poll it periodically and **restart** the container if it fails or times out. It must return `200 OK` as long as the app process itself is alive—even if an external dependency like Redis is temporarily down (otherwise the orchestrator enters a crash-restart loop).
- **`GET /ready` (Readiness Probe):** Answers *"Is this instance ready to receive live traffic?"* Load balancers poll it to decide whether to route requests to the instance. It returns **`503 Service Unavailable`** during startup, during graceful shutdown (`_is_ready = False`), or when required dependencies (such as Redis) are unreachable.

### Exercise 5.2: Graceful Shutdown

When an orchestrator stops or replaces a container, it sends **`SIGTERM`** before forcing termination (`SIGKILL`). In `05-scaling-reliability/develop/app.py`:
1. FastAPI's `lifespan` shutdown block sets `_is_ready = False` so `/ready` returns `503` and the load balancer stops sending new requests.
2. Middleware tracks `_in_flight_requests`; shutdown waits (up to `timeout_graceful_shutdown=30s`) for in-flight requests to finish cleanly.
3. Open connections are closed and the process exits with code `0`, ensuring zero dropped requests during rolling deployments.

### Exercise 5.3: Why In-Memory State Fails When Scaling

When running multiple instances behind a load balancer, each container has its own isolated RAM. If conversation history, rate-limit counters, or budgets are stored in a Python `dict` in memory, request #1 hits `instance-1` while request #2 hits `instance-2`, which has no record of the session or previous quota usage. Moving shared state to an external store like **Redis** makes every agent container **stateless** and horizontally scalable.

### Exercise 5.4 & 5.5: Multi-Instance Stateless Test (`05-scaling-reliability/production/`)

Ran 3 agent replicas behind Nginx (port `8080`, endpoint `POST /chat`) + Redis:
```bash
docker compose -p k5-day14-scaling up -d --build --scale agent=3
python test_stateless.py
docker compose -p k5-day14-scaling down -v
```

Observed output from `test_stateless.py`:
```text
Session ID: 31f46b44-4807-40c4-a160-123cf9865936

Request 1: [instance-e0bbc4]  Q: What is Docker?
Request 2: [instance-e9a588]  Q: Why do we need containers?
Request 3: [instance-e0bbc4]  Q: What is Kubernetes?
Request 4: [instance-9d4899]  Q: How does load balancing work?
Request 5: [instance-e9a588]  Q: What is Redis used for?

Total requests: 5
Instances used: {'instance-e0bbc4', 'instance-9d4899', 'instance-e9a588'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

**Explanation:** Nginx round-robined the 5 requests across all 3 containers (`instance-e0bbc4`, `instance-e9a588`, `instance-9d4899`). Because every container reads and writes session history to the shared Redis instance under `session_id`, querying `/chat/{session_id}/history` returned all 10 messages (5 user + 5 assistant) without losing any context.

---

## Part 6: Final Project (`06-lab-complete/`) — `check_production_ready.py` Output

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

---

## AI Log

- **CP1 (Part 1):** Used AI assistant to inspect `01-localhost-vs-production/develop/app.py` and `production/app.py`, run both servers locally to capture live HTTP responses, and structure the comparison table in `MISSION_ANSWERS.md`. Verified all line numbers and HTTP outputs directly from local runs.
- **CP2 (Part 2):** Used AI assistant to analyze the develop/production Dockerfiles and Compose stack, build both images locally, measure real image sizes (`1.67 GB` vs `240 MB`), and test the Nginx-proxied Compose stack (`docker compose -p k5-day14-docker`). All numbers and responses were verified from local Docker runs.
- **CP3 (Part 4):** Used AI assistant to inspect `04-api-gateway/develop` and `production` (`rate_limiter.py`, `cost_guard.py`), execute the API key (`401`/`200`) and JWT + rate-limit loop (`200` → `429`) tests locally, and summarize the Cost Guard design. All HTTP outputs were captured from real local runs with tokens masked.
- **CP4 (Part 5):** Used AI assistant to summarize health/readiness probes, graceful shutdown, and stateless design, and to run the 3-replica Compose stack (`docker compose -p k5-day14-scaling up -d --build --scale agent=3`) with `test_stateless.py`. Verified multi-instance load balancing and 10/10 Redis history persistence from real output.
- **CP5 (Part 6):** Used AI assistant to implement all TODOs in `06-lab-complete/` (`app/config.py`, `auth.py`, `redis_client.py`, `rate_limiter.py`, `cost_guard.py`, `main.py`, multi-stage `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`). Verified locally with unmodified `check_production_ready.py` in a POSIX Linux environment with Docker (`PASS 12/12`, `43/43 checks passed`, `238 MB` image, `SIGTERM` exit code `0`).
- **CP5 review & hardening (Part 6):** Asked an AI assistant to review the Part 6 code against the grading contract and `RUBRIC.md`. Changes made after the review:
  - Removed the in-memory fallback from `rate_limiter.py` and `cost_guard.py`, so state lives only in Redis and Redis errors now return `503`.
  - Made the sliding-window check-and-add one atomic Redis Lua script, so concurrent workers can't exceed the limit.
  - Hashed the API key before using it in Redis key names.
  - Removed the hardcoded `AGENT_API_KEY` default from `docker-compose.yml` (it now comes from `.env`).
  - Added a fail-fast check in `config.py` when `ENVIRONMENT=production` and `AGENT_API_KEY` is empty.
  - Re-ran the unmodified `check_production_ready.py` inside a Linux (`os.name == 'posix'`) container with Docker access: `PASS 12/12`, `43/43 checks passed`, `238 MB` image, `docker stop` exit code `0` in `0.6s`.
  - Manually confirmed that `POST /ask` with Redis down returns `503`, and that the app refuses to start in production without a key.
