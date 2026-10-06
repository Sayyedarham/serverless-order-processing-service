# Measured Benchmark & Chaos Test Results

All metrics documented below were measured directly on the live AWS deployment in `us-east-1`. Raw output artifacts are stored in `docs/results/`.

---

## 1. Load Testing Benchmark (k6)

- **Test Target**: `POST https://l67j9sjm76.execute-api.us-east-1.amazonaws.com/orders`
- **Executor**: `constant-arrival-rate` at 5.0 RPS (aligned with API Gateway safety throttling)
- **Duration**: 60 seconds
- **Raw Artifacts**: [`k6_baseline_raw.txt`](k6_baseline_raw.txt), [`k6_baseline_summary.json`](k6_baseline_summary.json)

| Metric | Measured Value | Target / Threshold | Status |
| :--- | :--- | :--- | :--- |
| **Total Ingest Requests** | **301** | > 300 | PASSED |
| **Throughput (req/s)** | **4.93 req/s** | ~ 5.0 req/s | PASSED |
| **HTTP Success Rate** | **100.00%** (301 / 301) | > 99.0% | PASSED |
| **HTTP Errors** | **0** | 0 | PASSED |
| **Ingest Latency (Min)** | **384.2 ms** | - | - |
| **Ingest Latency (p50 / Median)** | **419.84 ms** | < 500 ms | PASSED |
| **Ingest Latency (p90)** | **514.97 ms** | < 800 ms | PASSED |
| **Ingest Latency (p95)** | **1,350 ms** | < 1,500 ms | PASSED |
| **Ingest Latency (p99)** | **2,030 ms** | < 2,500 ms | PASSED |
| **Ingest Latency (Max)** | **4,910 ms** (Cold Start) | - | - |

---

## 2. Chaos Engineering & DLQ Redrive Test

- **Objective**: Validate partial batch failure isolation, SQS redrive policy after 3 retries, CloudWatch DLQ alarm triggering, and automated DLQ redrive.
- **Raw Artifact**: [`chaos_dlq_evidence.json`](chaos_dlq_evidence.json)

| Step | Action | Measured Result | Evidence |
| :--- | :--- | :--- | :--- |
| 1 | Ingest 5 flaky orders (`sim-fail-transient`) | 5 orders accepted with HTTP 202 | `orderId` generated |
| 2 | Worker Lambda execution | 3 retries attempted per message via `ReportBatchItemFailures` | SQS in-flight visibility |
| 3 | SQS Redrive Policy | 5 / 5 messages routed to `serverless-orders-dlq-prod` | `dlq_messages_routed = 5` |
| 4 | CloudWatch Metric Alarm | Alarm `serverless-orders-dlq-messages-visible-prod` evaluated | Alarm state tracked |
| 5 | DLQ Redrive Execution | `aws sqs start-message-move-task` executed | `5 / 5` messages redriven to main queue |

---

## 3. Test Suite & Code Quality Coverage

- **Test Framework**: `pytest` + `moto` + `pytest-cov`
- **Linters**: `ruff` + `mypy` (strict)
- **Coverage Summary**:

```
Name                       Stmts   Miss  Cover   Missing
--------------------------------------------------------
src\common\config.py          14      0   100%
src\common\dynamo.py          73      2    97%   91-94
src\common\models.py          38      1    97%   38
src\common\sqs.py             17      0   100%
src\ingest\handler.py         68      4    94%   29, 134-136
src\status\handler.py         31      1    97%   21
src\worker\downstream.py      24      4    83%   54-60
src\worker\handler.py         61      5    92%   114-120
--------------------------------------------------------
TOTAL                        326     17    95% (94.79%)
```
