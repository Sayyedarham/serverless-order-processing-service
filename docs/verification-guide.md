# Verification Guide

Deploy with a non-empty `api_shared_key`, retrieve `api_endpoint` with `terraform output`, and use that URL and token in the BYOK panel. The browser keeps the token only in current-page memory; use the future desktop client for OS-backed secret storage.

Start a run with a fixed subset of: `happy-path`, `duplicate-request`, `concurrent-duplicate`, `worker-failure`, `partial-batch-failure`, `dlq`, `redrive`, `downstream-failure`, `state-transition`, and `small-load`.

```bash
curl -X POST "$API/verification/runs" \
  -H "Content-Type: application/json" -H "X-Service-Key: $TOKEN" \
  -d '{"scenarios":["happy-path","duplicate-request"]}'
curl -H "X-Service-Key: $TOKEN" "$API/verification/runs/<run-id>"
curl -H "X-Service-Key: $TOKEN" "$API/verification/runs/<run-id>/results"
```

`COMPLETED` means the bounded runner finished and stored every requested scenario result; inspect each result status and evidence. It is not an overall pass. Some failure/DLQ scenarios can be deliberately `SKIPPED` until an isolated, bounded probe is available; this is intentional and honest rather than a synthetic pass.
