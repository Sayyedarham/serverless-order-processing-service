# Engineering Design Document: Serverless Order Processing Service

## 1. Problem Statement
E-commerce order fulfillment backends face two opposing challenges:
1. Handling bursty, unpredictable order submission spikes without dropping requests or suffering cascading timeouts.
2. Maintaining absolute data consistency, preventing duplicate billing/fulfillments under network retries, and isolating flaky downstream dependencies.

This system provides an event-driven architecture that achieves high availability, strict idempotency, partial failure isolation, and comprehensive observability within the AWS Free Tier ($0 running cost).

## 2. Goals & Non-Goals

### Goals
- **Fault Tolerance**: Transient downstream errors trigger retries; poison-pill payloads route to a DLQ without blocking other orders in the batch.
- **Strict Idempotency**: Guarantee exactly-once processing side effects even when clients retry requests or SQS delivers duplicate messages.
- **Zero Idle Cost**: Built exclusively with AWS on-demand / serverless primitives (Lambda, SQS, DynamoDB, HTTP API, CloudWatch).
- **Observable by Default**: Structured JSON logs with distributed correlation IDs, custom business metrics (EMF), and proactive alarms.
- **Infrastructure as Code**: Reproducible Terraform definitions from `init` to `destroy`.

### Non-Goals
- Multi-region active-active replication (not required for single-region prototype).
- Synchronous legacy relational database locking (avoided to eliminate idle EC2/RDS costs).
- Complex saga orchestrations involving dozens of microservices.

## 3. Architecture & Key Tradeoffs

### Tradeoff 1: SQS Standard Queue vs FIFO Queue
- **Decision**: Standard SQS with application-level idempotency via DynamoDB.
- **Rationale**: Standard queues offer practically unlimited throughput and lower latency. In an order fulfillment domain, strict FIFO ordering across different customers is unnecessary; idempotency at the database row level provides the required correctness.

### Tradeoff 2: Partial Batch Failure vs Whole-Batch Failure
- **Decision**: Enable `ReportBatchItemFailures` on the SQS Lambda event source mapping.
- **Rationale**: If a batch contains 10 messages and 1 transiently fails, standard Lambda behavior throws an exception causing all 10 messages to be re-delivered. `ReportBatchItemFailures` returns only the failed `itemIdentifier`, ensuring 9 successful messages are deleted immediately.

### Tradeoff 3: DynamoDB Conditional Writes vs Distributed Mutex (Redis/Lock)
- **Decision**: Native DynamoDB conditional expressions (`attribute_not_exists(orderId)`).
- **Rationale**: Eliminates the operational overhead and cost of managing a Redis/ElastiCache cluster while ensuring atomicity at the storage engine level.

## 4. Failure Modes & Resilience Strategies

| Failure Mode | Impact | Mitigation Strategy |
| :--- | :--- | :--- |
| **Network Timeout on Ingest** | Client retries `POST /orders` | `Idempotency-Key` header mapped to deterministic UUID; conditional insert detects replay and returns existing order with HTTP 200 without re-queueing to SQS. |
| **Downstream Payment Gateway Flakiness** | Worker Lambda cannot fulfill order | Message returned in `batchItemFailures`; SQS retries up to 3 times before routing to DLQ; CloudWatch alarm notifies on-call engineer via SNS. |
| **Malformed Message Body** | Worker fails to parse JSON | Worker logs structured error and acknowledges/deletes poison pill without retrying or blocking batch. |
| **Traffic Spike / DoS Attempt** | Potential bill shock | API Gateway rate throttling (5 RPS, burst 10) + request size limit (10 KB) drops excess traffic with HTTP 429 / 413. |
| **Storage Growth Over Time** | Unbounded table growth | DynamoDB TTL (`expiresAt`) automatically purges orders after 7 days at zero compute cost. |

## 5. Security & Cost Guardrails
1. **GitHub OIDC**: GitHub Actions authenticates directly to AWS using short-lived tokens, eliminating long-lived IAM keys in repository secrets.
2. **Least-Privilege IAM Policies**: Lambda execution roles are strictly restricted to the specific table ARN, queue ARN, and CloudWatch log groups.
3. **AWS Budget**: $1.00 monthly spending limit with dual alerts (80% actual and 100% forecasted spend).
4. **Log Retention**: Every CloudWatch Log Group is capped at 7 days.
