# ADR 0001: Asynchronous Event-Driven Architecture using SQS and Lambda

## Status
Accepted

## Context
The order processing service must handle variable burst loads without dropping requests or suffering client HTTP connection timeouts during long-running downstream fulfillments.

## Decision
We chose an **asynchronous event-driven architecture**:
1. API Gateway + Ingest Lambda accepts orders, performs schema validation and conditional DynamoDB insert, and immediately returns `202 Accepted` to the client.
2. Standard SQS Queue decouples ingestion from execution and acts as a buffer.
3. Worker Lambda processes orders asynchronously with partial batch failure reporting (`ReportBatchItemFailures`).

## Consequences
- **Pros**:
  - Predictable, low ingest latency (< 500ms p50).
  - High resilience: downstream outages buffer orders in SQS without losing transactions.
  - Zero idle cost within AWS Free Tier.
- **Cons**:
  - Clients must poll `GET /orders/{id}` or use webhooks to observe final completion.
  - Requires application-level idempotency to handle SQS at-least-once delivery.
