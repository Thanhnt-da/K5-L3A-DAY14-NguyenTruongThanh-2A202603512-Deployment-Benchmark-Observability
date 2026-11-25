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

### 4.1 Screenshot

- [ ] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals)
- [ ] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian)
- [ ] Một trace lỗi trong Jaeger (có event `exception`)
- [ ] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing**

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | | | |
| B | `MOCK_SLOW_RATE=0.3` | | | |
| C | `LLM_MODEL=mock-llm-large` | | | |
| D | `docker pause` 1 instance | | | |
| E | `AGENT_VERSION=v1` | | | |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

...

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: ...
- Tổng thời gian: ... ms
- Span chiếm nhiều thời gian nhất: ... (... ms, ...%)
- Dòng log tương ứng (grep theo `trace_id`):

```json

```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | | | | | |
| 3 | | | | | |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

...

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. ...
  2. ...
  3. ...
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

...
