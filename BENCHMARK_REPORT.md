# Benchmark & Observability Report — Day 14

> Copy file này thành `BENCHMARK_REPORT.md` trong repo của bạn và điền đầy đủ.
> Mọi con số phải lấy từ report JSON / CSV / screenshot thật, không ước lượng.

**Họ tên:** Nguyễn Trường Thành
**Ngày chạy:** 2026-11-25
**Môi trường:** Laptop with Intel Core i7-6600U (2 cores / 4 threads) and 8 GB RAM, Windows 10 Pro, Docker Desktop 29.9.3 (WSL2 backend, 4 CPU / 3.8 GB). The develop benchmarks (sections 2–3) ran inside a `python:3.11-slim` Linux container, with the agent (1 uvicorn process) and the load generator in the **same** container.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | A normal request takes ~190–220 ms (p50 ≈ 190 ms at low load), so 500 ms leaves about 2× headroom for queueing, while users still feel the agent is responsive. It is also the `load_test.py` default, so CI and this report use the same bar. |
| Error rate `/ask` | < 2 % | The mock upstream LLM fails ~1 % of calls (`MOCK_ERROR_RATE=0.01`), which we can't control. 2 % leaves a 1 % error budget for our own bugs and overload before users are noticeably affected. |
| Accuracy trên golden dataset | ≥ 85 % | The same threshold as the CI quality gate (`--min-accuracy 0.85`, Exercise 7.3). v2 is already above it (91.3 % before the fix), and a drop below it means a real regression, not noise (one question = 4.3 %). |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

Command: `python load_test.py --url http://localhost:8002 --requests 300 --concurrency <c> --out reports/load_v2_c<c>.json` (default `MOCK_SLOW_RATE=0.03`).

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.28 | 191.7 | 221.5 | 1701.9 | 1.67 % | ✅ PASS |
| 10 | 32.78 | 193.3 | 227.5 | 1704.6 | 1.67 % | ✅ PASS |
| 50 | 97.43 | 204.4 | 333.6 | 1748.6 | 2.00 % | ✅ PASS |
| 100 | 48.99 | 1058.3 | 4656.9 | 5312.7 | 1.33 % | ❌ FAIL (p95) |

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

Only at first. From 1 to 10, RPS rose 7.7× (4.28 → 32.78) while p50 stayed flat (~192 ms), so the agent was simply waiting on the (mock) LLM and could overlap requests. Little's law confirms it: at c=1, 1 / 0.2356 s avg ≈ 4.2 RPS, matching the measurement.

From 10 to 50, RPS rose only 3× (to 97.43) instead of 5×, and p95 grew from 227 to 334 ms, a sign that queueing had started. At 100, RPS **fell** to 48.99 and p50 jumped to 1058 ms (p95 4657 ms), so the system was past saturation. The likely bottleneck is CPU: one uvicorn process (one Python event loop) handles every request plus the metrics, and the load generator runs on the same 4 CPUs, so extra concurrent requests only wait in a queue. Throughput is limited by the slowest shared resource, not by how many requests we send. To go further we would need more workers or instances (section 5), not more concurrency.

### 2.2 Tail latency

Command: restart v2 with `MOCK_SLOW_RATE=<x>`, then `python load_test.py --url http://localhost:8002 --requests 300 --concurrency 20 --out reports/load_v2_slow_<x>.json`.

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 192.4 | 223.1 | 248.7 |
| 0.03 (mặc định) | 227.2 | 224.2 | 1696.3 |
| 0.1 | 398.6 | 1699.7 | 1717.0 |

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

The tail percentiles are the most sensitive. Going from 0 % to 3 % slow requests barely moved avg (+35 ms, +18 %) and p95 (+1 ms), but **p99 jumped ~7×** (249 → 1696 ms), because 3 % slow requests is more than the top 1 %. At 10 % the slow requests also exceed the top 5 %, so p95 jumped too (224 → 1700 ms) and the SLO failed, while avg "only" doubled to 399 ms.

The average hides the users who wait ~1.7 s: at 3 % it says 227 ms, "looks fine", even though 1 in 100 users waits 1.7 s. An SLO is a promise about user experience, so it should be set on p95/p99 (the experience of the slowest users), which shows exactly how many people get the bad experience. An average can also be skewed by a few huge outliers, or look fine while many users suffer.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3 % (1/23) | 91.3 % (21/23) | 100 % (23/23) |
| Avg tokens / câu | 56.9 | 109.0 | 116.3 |
| Tổng cost (USD) | 0.000402 | 0.000760 | 0.000814 |
| Cost / câu đúng (USD) | 0.00040155 | 0.00003619 | 0.00003537 |
| Quality gate | FAIL (exit 1) | PASS (exit 0) | PASS (exit 0, `--min-accuracy 1.0`, 0 regression) |

Files: `reports/eval_v1.json`, `reports/eval_v2.json` (`--baseline reports/eval_v1.json`), `reports/eval_v2_fixed.json` (`--min-accuracy 1.0 --baseline reports/eval_v2.json`).

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| security-02 ("JWT khác gì API key trong xác thực?") | `token`, `hết hạn`, `chữ ký` | No knowledge-base entry matched "JWT", so v2 fell back to a generic answer. I added a `KNOWLEDGE_BASE` entry triggered by `jwt` / `json web token`, explaining that a JWT is a signed token (chữ ký số) carrying user info and an expiry time (hết hạn), unlike a fixed API key. |
| scaling-03 ("Kubernetes HPA scale dựa trên những chỉ số nào?") | `cpu`, `memory`, `custom metrics` | No entry matched "HPA". I added an entry triggered by `hpa` / `horizontal pod autoscaler` / `autoscaler`, saying HPA scales pods on CPU, memory or custom metrics (RPS, queue length, p95). |

I kept the trigger keywords narrow (not `kubernetes` or `xác thực`) so no other question gets routed to the new documents. The re-run showed 2 improved, **0 regressions**. The same change was copied to `production/utils/mock_llm.py`. The golden dataset was not modified.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

v2 adds a retrieval step and puts the retrieved document into the prompt, so each question costs about **1.9× the tokens** (56.9 → 109.0) and **1.9× the total cost** (0.000402 → 0.000760 USD). It is also slightly slower (eval p95 196.3 → 214.8 ms, +18.5 ms).

In exchange, accuracy goes from 4.3 % to 91.3 %. So **cost per correct answer is ~11× lower** for v2 (0.00040155 → 0.00003619 USD): v1 is cheap per question but almost every answer is useless. After the knowledge-base fix, tokens rise a little more (116.3), but cost per correct answer drops again (0.00003537) because all 23 answers are now correct.

That's why "cost per correct answer" is the better metric for comparing versions: it measures what we actually pay for useful output.

**Quality gate / CI (Exercise 7.3):** running v1 against `--baseline reports/eval_v2.json` gives accuracy 4.3 %, **20 regressions**, `Quality gate ❌ FAIL` and **exit code 1**. The job in `.github/workflows/eval.yml` runs on every pull request:

1. Starts agent v2 with `MOCK_ERROR_RATE=0`, so random upstream errors can't fail CI.
2. Runs `run_eval.py --min-accuracy 0.85 --baseline reports/eval_v2_fixed.json`.

Because `run_eval.py` exits with 1 when accuracy is too low or any question regresses, the step fails, so the check fails. With branch protection making that check required, the PR cannot be merged.

---

## 4. Observability stack (production)

Stack started with `docker compose -p k5-day14-observability up -d --build --scale agent=1`; experiments ran with 2 agent instances.

**Fix needed to start the stack:** the given `production/Dockerfile` crashed with `ModuleNotFoundError: No module named 'uvicorn'`. The runtime user `agent` has home `/app`, so Python looked for user packages in `/app/.local`, but they were copied to `/home/agent/.local`. I added `ENV PYTHONUSERBASE=/home/agent/.local`. Alert rules unit test: `promtool test rules /p/alert_rules_test.yml` → `SUCCESS`.

### 4.0 Exercise 7.4 (default stack: v2, 2 instances, 10 Locust users, Prometheus 2-minute window)

1. **p95 vs avg:** p95 = 0.297 s, avg = 0.248 s, p99 = 1.871 s. p95 and avg are close because 97 % of requests take ~0.2–0.3 s. The big jump is between p95 and p99: the ~3 % "slow" mock LLM calls (+1.5 s) sit above the 95th percentile and show up only in p99. The gap between avg and the tail percentiles shows that a few users wait much longer than "average".
2. **Does Nginx balance evenly?** Yes. Requests/s per instance were 2.513 (`172.20.0.7`) and 2.446 (`172.20.0.8`), about 51 % / 49 %. That's what round-robin produces when both instances are healthy.
3. **Why input tokens/s > output tokens/s?** Input was 354.3 tokens/s and output 188.4 tokens/s. The input contains the system prompt, the retrieved document (v2 RAG context) and the question, while the output is only the short answer. RAG makes the prompt longer than the answer.
4. **`curl http://localhost:8080/metrics`** returns **404 Not Found** from Nginx. `nginx.conf` blocks `/metrics` from the outside: metrics expose internal details (versions, traffic, cost) and should only be scraped by Prometheus inside the Docker network, not published to the internet.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals) → `screenshots/grafana-dashboard.png` (during experiments A+B: error rate 23.62 %, p95 1.91 s, 2 instances)
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian) → `screenshots/jaeger-slow-trace.png`
- [x] Một trace lỗi trong Jaeger (có event `exception`) → `screenshots/jaeger-error-trace.png`
- [x] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing** → `screenshots/prometheus-alert-firing.png` (`AgentHighErrorRate` and `AgentHighLatencyP95` both FIRING)

### 4.2 Thí nghiệm "phá hệ thống"

**Setup and method:**
- Background load came from Locust headless with **10 users**, not the README's 30. At 30 users, the normal v2 traffic already cost $2.6–3.7/h, above the `LLMCostBurnRateHigh` threshold of $2/h, so that alert was firing before any change and experiment C could not be timed.
- Each change was applied with a `.env` override plus `docker compose -p k5-day14-observability up -d`. The time is measured from the moment that command finished, and a script polled `/api/v1/alerts` every 5 s.
- B was applied on top of A, so that both alerts fire together for the screenshot.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (error rate 17.8 % at firing) | **91 s** (pending at 30 s + `for: 1m`) | Golden Signals → **Error rate** (red, 23.62 % in screenshot); Requests/s by status (503 line) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (p95 1.90 s) | **146 s** (pending at 25 s + `for: 2m`) | **Latency p95** stat and the p50/p95/p99 graph: p95/p99 jump to ~1.9 s while p50 stays ~0.2 s |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (cost burn $6.82/h at firing, from $0.57/h) | **176 s** (pending at 55 s, once the 5-minute rate crossed $2/h, + `for: 2m`) | LLM row → **Cost burn rate (USD/giờ)** and LLM cost (1h); p95 also rose 0.30 → 0.69 s (latency ×2.5) |
| D | `docker pause` 1 instance (`k5-day14-observability-agent-1`) | `AgentInstanceDown` | **40 s** (pending at 10 s + `for: 30s`) | **Instances up** 2 → 1. Nginx logged **11 × 504** in that window, but the agent's error rate stayed ~0.5–1 %, because those requests never reached a healthy agent |
| E | `AGENT_VERSION=v1` | **None** (watched 240 s) | — | **Tokens/s** fell ~709 → ~345, the retrieval rate went from ~6/s to no data, and `agent_info{version="v1"}` changed. Error rate and p95 stayed green (p95 0.29 → 0.20 s) |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

v1 is *healthier* by infrastructure metrics: faster, cheaper, no errors. Only answer quality dropped (4.3 % vs 100 % in section 3), and metrics like latency, errors and saturation cannot see that. It has to be caught with quality signals:
1. **Before deploy:** run the eval quality gate (`run_eval.py` in CI, `.github/workflows/eval.yml`), which would have blocked v1 with 20 regressions and exit code 1.
2. **After deploy:**
   - Run the golden dataset periodically against production (a synthetic eval) and alert on accuracy.
   - Alert on quality proxies such as `agent_retrieval_total` dropping to 0 or the retrieval hit ratio falling, or an unexpected change in `agent_info{version}`.
   - Track user feedback (thumbs down), or sample answers with an LLM-as-judge.

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được (Jaeger, service `observable-agent`, recorded during the 1-instance scaling run, 100 users):

- `trace_id`: `92fc20b9fa058f745eff3d6be50aa8b1`
- Tổng thời gian: **5096.9 ms** (`POST /ask`, status 200)
- Span chiếm nhiều thời gian nhất: among the child spans, **`agent.run` (1880.6 ms, 36.9 %)**. Inside it, the LLM span `chat mock-llm-small` took **1689.3 ms (33.1 %)**, a "slow" mock LLM call, and `agent.retrieve_context` took 191.1 ms (3.7 %, normally ~20 ms).
- **Interpretation:** the remaining ~3216 ms (63 %) of `POST /ask` happened *before* `agent.run` started. The request was waiting in the queue of the single agent instance (limited to 0.5 CPU) while it served 100 users, which also explains why retrieval took 191 ms instead of ~20 ms. So this trace has two causes: a slow upstream LLM call plus CPU saturation on one instance. Scaling to 3 instances fixes the second (see section 5).
- Dòng log tương ứng (`docker compose -p k5-day14-observability logs agent | grep 92fc20b9fa058f745eff3d6be50aa8b1`):

```json
{"ts": "2026-11-25T15:03:11.022689+00:00", "level": "INFO", "service": "observable-agent", "instance": "d2c98b1b7da4", "event": "llm_call", "trace_id": "92fc20b9fa058f745eff3d6be50aa8b1", "span_id": "56d5f2b1b6fe609b", "request_id": "6b28efbd8ac9", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 83, "output_tokens": 44, "cost_usd": 3.9e-05, "llm_ms": 1647.5}
{"ts": "2026-11-25T15:03:11.028543+00:00", "level": "INFO", "service": "observable-agent", "instance": "d2c98b1b7da4", "event": "http_request", "trace_id": "92fc20b9fa058f745eff3d6be50aa8b1", "span_id": "56d5f2b1b6fe609b", "request_id": "6b28efbd8ac9", "method": "POST", "route": "/ask", "status": 200, "ms": 5094.9}
```

Error trace (`screenshots/jaeger-error-trace.png`): `trace_id` `290d30fe59de15057352cf196f3ab08a`, 97.0 ms, status 503.
- The span `chat mock-llm-small` (72.1 ms) has `error.type=upstream_unavailable` and an `exception` event: `utils.mock_llm.LLMError: Upstream LLM error: 503 Service Unavailable (mock)`.
- Matching log line:

```json
{"ts": "2026-11-25T15:07:24.721682+00:00", "level": "INFO", "service": "observable-agent", "instance": "fd361d2393c4", "event": "llm_error", "trace_id": "290d30fe59de15057352cf196f3ab08a", "span_id": "e0cac4682dcda162", "request_id": "f16ec99e5782", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Commands: see CP8 in `CHECKPOINTS.md` (`--headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_N`). Numbers are from the `POST /ask` row of `benchmark-results/scale_1_stats.csv` and `scale_3_stats.csv`.

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 46.74 | 260 | 2200 | 4200 | 60 / 5466 (1.10 %) |
| 3 | 58.58 | 200 | 600 | 1700 | 55 / 6923 (0.79 %) |

(Aggregated rows, including `/health`: 1 instance 51.59 req/s, p95 2100 ms; 3 instances 64.47 req/s, p95 560 ms.)

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

Yes, a lot. p95 fell from 2200 to 600 ms (−73 %), p99 from 4200 to 1700 ms, and average latency from 623 to 276 ms. RPS rose 25 % (46.74 → 58.58).

With 1 instance, the bottleneck was the agent container itself. It is limited to `cpus: "0.5"` and runs one uvicorn process, so 100 users queued in front of it: the slow trace in 4.3 spent 63 % of its time waiting before `agent.run` started. Three instances split the queue, so most requests go straight to the LLM call again (p50 200 ms ≈ the bare mock-LLM latency).

RPS did not triple because Locust users wait 0.5–2 s between requests. With 100 users the offered load is only ~60–65 req/s, so with 3 instances throughput is limited by the users, not by the agents. The remaining p99 of 1700 ms is now the **upstream LLM** itself: 3 % of calls are slow by design (`MOCK_SLOW_RATE`, +1.5 s). Adding instances cannot fix that; only a faster or more reliable LLM, timeouts with retries, or caching would.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Percentiles, not averages.** 3 % slow requests barely moved avg or p95, but raised p99 about 7× (section 2.2), and the tail is what users complain about. SLOs and alerts should use p95/p99, and an alert needs a `for:` duration (30 s–2 min here) to avoid false alarms from short spikes.
  2. **Metrics, traces and logs answer different questions, and the `trace_id` connects them.** The dashboard showed *that* p95 was high, the Jaeger trace showed *where* (63 % queueing plus a slow LLM span), and the JSON log line with the same `trace_id` gave the exact request details.
  3. **Infrastructure health ≠ product quality.** Switching to v1 made every infrastructure panel greener while accuracy dropped from 91–100 % to 4 %. Errors at the load balancer (11 × 504 in experiment D) were also invisible to the agent's own metrics. Production needs eval quality gates and synthetic checks from outside, not only internal metrics.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?
  - **Quality:** a scheduled golden-dataset eval against production that exports `agent_eval_accuracy` (alert if < 85 %), the retrieval hit ratio (alert if it drops sharply), and a user-feedback "thumbs down" rate.
  - **Load-balancer side:** Nginx 5xx/504 rate and upstream response time (e.g. an nginx exporter), plus an external synthetic `/ask` check, so failures the agent never sees are still caught.
  - **Cost:** a per-day budget burn alert (multi-window: fast 5 m and slow 1 h), cost per correct answer, and tokens per request by model, to catch prompt bloat.
  - **Saturation:** in-flight requests per instance and CPU throttling (`container_cpu_cfs_throttled_seconds_total`), to scale out before p95 degrades. Also an alert on `agent_info` version changes.
