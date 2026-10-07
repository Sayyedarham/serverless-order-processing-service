# System Architecture

## Overview
The **Serverless Event-Driven Order Processing Service** is an enterprise-grade, zero-cost portfolio project demonstrating high throughput asynchronous processing, strict idempotency guarantees, fault tolerance, and comprehensive observability.

```mermaid
flowchart TD
    Client["Client / Load Generator"]
    
    subgraph Edge["API Gateway (HTTP API v2)"]
        Throttle["Stage Throttle: 5 RPS / Burst 10"]
        PostRoute["POST /orders"]
        GetRoute["GET /orders/{id}"]
        HealthRoute["GET /health"]
    end

    subgraph Compute["AWS Lambda (Python 3.12 + Powertools)"]
        IngestLambda["Ingest Lambda\n(Validate, Idempotency, Enqueue)"]
        WorkerLambda["Worker Lambda\n(Batch Processor, Flaky Retries)"]
        StatusLambda["Status Lambda\n(Read DynamoDB)"]
    end

    subgraph Messaging["Asynchronous Queueing"]
        MainSQS["Standard SQS Queue\n(Visibility Timeout: 60s)"]
        DLQ["Dead Letter Queue\n(maxReceiveCount = 3)"]
    end

    subgraph Storage["Persistence & Observability"]
        Dynamo["DynamoDB (On-Demand)\nPK: orderId\nGSI: StatusCreatedAtIndex\nTTL: expiresAt (7 days)"]
        CWLogs["CloudWatch Logs\n(7-Day Retention)"]
        CWAlarms["CloudWatch Alarms\n(DLQ depth, 5xx, p99 Latency)"]
        SNS["SNS Topic -> Email Alerts"]
        Dashboard["CloudWatch Dashboard"]
    end

    Client --> Throttle
    Throttle --> PostRoute
    Throttle --> GetRoute
    Throttle --> HealthRoute

    PostRoute --> IngestLambda
    GetRoute --> StatusLambda
    HealthRoute --> StatusLambda

    IngestLambda -- Conditional Put (attribute_not_exists) --> Dynamo
    IngestLambda -- Publish Message --> MainSQS
    
    MainSQS -- Batch Event (ReportBatchItemFailures) --> WorkerLambda
    WorkerLambda -- Read/Update Status (PROCESSING -> COMPLETED/FAILED) --> Dynamo
    WorkerLambda -- 3 Consecutive Failures --> DLQ
    
    DLQ -- ApproximateNumberOfMessagesVisible > 0 --> CWAlarms
    CWAlarms --> SNS
    StatusLambda -- GetItem --> Dynamo

    IngestLambda -. Logs & EMF Metrics .-> CWLogs
    WorkerLambda -. Logs & EMF Metrics .-> CWLogs
    StatusLambda -. Logs & EMF Metrics .-> CWLogs
    CWLogs -. Metrics Aggregation .-> Dashboard
```

## Architectural Components

### 1. Ingestion Layer
- **Amazon API Gateway (HTTP API v2)**: Provides low-latency HTTP endpoints with stage-level rate limiting (5 RPS, burst 10) to eliminate runaway costs.
- **Ingest Lambda**:
  - Validates schema using **Pydantic v2**.
  - Enforces mandatory `Idempotency-Key` header and payload size constraints (< 10 KB).
  - Performs conditional write into DynamoDB (`attribute_not_exists(orderId)`).
  - Returns `202 Accepted` on new orders or `200 OK` on duplicate replays.

### 2. Messaging & Decoupling
- **Amazon SQS Standard Queue**: Decouples ingest from background processing, absorbing traffic spikes.
- **Dead Letter Queue (DLQ)**: Configured with `maxReceiveCount = 3` and 14-day retention.
- **Partial Batch Item Failures**: Uses `ReportBatchItemFailures` so only failed individual messages in a batch are returned to SQS for retry.

### 3. Processing Layer
- **Worker Lambda**:
  - Consumes SQS batches (up to 10 records per batch, 5s batching window).
  - Idempotent state check before executing downstream actions.
  - Runs the deterministic fulfillment simulation; failure injection is confined to tests.

### 4. Persistence & Lifecycle
- **Amazon DynamoDB (Pay-Per-Request)**:
  - Primary Key: `orderId` (String UUID).
  - Global Secondary Index: `StatusCreatedAtIndex` (`status` Partition Key, `createdAt` Sort Key).
  - Time-to-Live (TTL): Automatically cleans up orders after 7 days via `expiresAt`.

### 5. Observability & Alerting
- **AWS Lambda Powertools**: Structured JSON logging with correlation IDs (`order_id`, `idempotency_key`, `request_id`).
- **CloudWatch Alarms & SNS**: Immediate email notifications for DLQ message arrival, Lambda errors, API 5xx spikes, and elevated p99 latency.
- **AWS Budgets**: $1.00 monthly spending safety ceiling with email alerts at 80% actual and 100% forecasted spend.
