# Benchmark Methodology

The historical artifacts in `docs/results/` are point-in-time observations, not capacity promises. Record API URL (redacted as necessary), AWS region, timestamp, request count, rate, payload, response counts, raw latency output, and any failures for every run.

Do not derive percentiles when raw timings are absent. The verification report aggregates only metrics directly persisted by scenarios; unavailable p50/p95/p99 values are omitted. Keep load runs bounded to the documented demo limits and run them manually against a user-owned stack.
