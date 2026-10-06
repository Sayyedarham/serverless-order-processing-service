# ADR 0002: Multi-Layer Idempotency Strategy

## Status
Accepted

## Context
In distributed event-driven systems, duplicate requests occur frequently due to client retries on network drops and SQS at-least-once message delivery. We must prevent double-processing or conflicting state mutations.

## Decision
We implement a two-layer idempotency strategy:
1. **Ingest Layer (API Gateway / Ingest Lambda)**:
   - Requires client header `Idempotency-Key`.
   - Derives deterministic `orderId` via UUIDv5.
   - Executes DynamoDB conditional put with `attribute_not_exists(orderId)`.
   - If conditional check fails, checks if `idempotencyKey` matches; returns existing record (`200 OK`) and suppresses duplicate SQS publish.
2. **Worker Layer (SQS / Worker Lambda)**:
   - Reads existing order state from DynamoDB before calling downstream APIs.
   - If status is `COMPLETED`, acknowledges the SQS message and skips execution.

## Consequences
- **Pros**:
  - Guaranteed exactly-once business side effects.
  - Zero lock contention or distributed Redis cluster overhead.
  - Transparent replay behavior for client retries.
- **Cons**:
  - Requires one DynamoDB read on worker execution (amortized under on-demand free tier).
