# Resume Summary & Technical Interview Preparation

## 1. Project Title & Stack
**Serverless Event-Driven Order Processing Service** | *Python 3.12, AWS Lambda, Amazon SQS, DynamoDB, API Gateway, CloudWatch, Terraform, Pydantic, Moto, k6*

---

## 2. Resume Experience Bullets (Grounded in Measured Metrics)

- **Architected and deployed** an asynchronous, event-driven order processing engine on AWS (Lambda, SQS, DynamoDB, API Gateway) achieving **4.93 req/s sustained ingestion throughput** at **$0.00 idle running cost**.
- **Implemented multi-layer idempotency** using client `Idempotency-Key` headers, deterministic UUIDv5 mapping, and native DynamoDB conditional writes (`attribute_not_exists`), achieving **100% duplicate suppression** across network retries without external distributed locks.
- **Engineered resilient batch ingestion** with SQS `ReportBatchItemFailures` and exponential backoff, isolating transient downstream API failures and automating Dead Letter Queue (DLQ) message recovery with **100% successful message redrive (5/5 recovered)**.
- **Achieved 94.8% test coverage across 28 unit and integration test suites** using `pytest`, `moto`, and strict `mypy` typing, validating cold start handling, poison-pill drops, and schema validation.
- **Built end-to-end GitOps CI/CD pipelines** using GitHub Actions with keyless AWS OIDC authentication and Terraform IaC, enforcing log retention limits (7 days) and $1.00 budget alerts.

---

## 3. High-Yield Amazon SDE Technical Interview Questions & Code-Grounded Answers

### Q1: How do you guarantee idempotency in your order processing pipeline if a client sends duplicate requests?
**Answer**:
"We implement a two-tier idempotency model. At the API Gateway / Ingest layer (`src/ingest/handler.py`), every incoming request requires an `Idempotency-Key` header. We derive a deterministic UUIDv5 from this key and attempt a conditional put to DynamoDB with `attribute_not_exists(orderId)`. If a client replays the same request, DynamoDB throws a `ConditionalCheckFailedException`. We catch this, verify that the existing record's `idempotencyKey` matches, and immediately return HTTP `200 OK` with the existing order details while skipping enqueuing to SQS. At the worker layer (`src/worker/handler.py`), the Lambda inspects the order status before making any downstream API calls; if the order is already `COMPLETED`, it acknowledges the SQS message and skips execution."

---

### Q2: Why did you choose SQS Standard Queue over SQS FIFO or Kinesis Streams?
**Answer**:
"Standard SQS offers virtually unlimited throughput, sub-10ms enqueue latency, and is fully covered under the AWS Free Tier. In our order processing domain, strict global ordering across different customers is unnecessary as each customer's order is independent. By delegating ordering and deduplication to row-level conditional writes in DynamoDB, we eliminated the partition key bottlenecks and concurrency limits inherent to FIFO queues, while avoiding the continuous shard costs of Kinesis."

---

### Q3: How does your worker handle partial batch failures in SQS, and why is that important?
**Answer**:
"By default, if an AWS Lambda function fails while processing an SQS batch of 10 messages, the runtime fails the entire batch and SQS makes all 10 messages visible again, causing duplicate executions for the 9 messages that succeeded. We enabled `ReportBatchItemFailures` in Terraform (`infra/lambda.tf`) and implemented partial batch failure reporting in Python (`src/worker/handler.py`). When a transient downstream exception occurs, we catch it and populate the specific message ID into `batchItemFailures: [{"itemIdentifier": message_id}]`. SQS only retries the failing message, while deleting the successful ones immediately."

---

### Q4: How does the system handle poison-pill messages, and how do you recover messages from the Dead Letter Queue?
**Answer**:
"We configure a Dead Letter Queue (`serverless-orders-dlq-prod`) with `maxReceiveCount = 3` and a 60-second visibility timeout. If an order fails 3 consecutive execution attempts (e.g., due to an extended downstream service outage), SQS routes the message to the DLQ. A CloudWatch alarm (`ApproximateNumberOfMessagesVisible > 0`) immediately triggers an SNS email notification to the on-call engineer. Once the downstream dependency recovers, we invoke an SQS Redrive task using `aws sqs start-message-move-task` (`loadtest/run_benchmarks.py`), which programmatically moves messages back to the main queue for seamless reprocessing without manual database intervention."

---

### Q5: How did you ensure zero idle cost ($0/month) and prevent runaway bills during load testing?
**Answer**:
"We enforced three architectural guardrails:
1. **Serverless on-demand primitives**: DynamoDB `PAY_PER_REQUEST`, HTTP API Gateway v2, and Lambda compute with 0 provisioned instances.
2. **Safety throttling**: Configured HTTP API stage rate limiting (`throttling_rate_limit = 5` RPS, `throttling_burst_limit = 10`) and a strict 10 KB payload size limit.
3. **Storage lifecycle & Cost Alerting**: Configured a 7-day TTL on DynamoDB records, 7-day retention on all CloudWatch log groups, and an AWS Budget resource configured in Terraform with automated email alerts at 80% and 100% of a $1.00 monthly threshold."

---

### Q6: How do you achieve distributed tracing and structured observability across asynchronous components?
**Answer**:
"We use AWS Lambda Powertools for Python (`src/common/config.py`). On ingestion, we attach correlation IDs (`order_id`, `idempotency_key`, `request_id`) to the logger context and inject them into SQS message attributes. When the worker consumes the message, it unpacks the attributes and binds the same correlation IDs. All application logs are emitted as structured JSON, enabling CloudWatch Logs Insights queries to trace an individual order across the entire lifecycle. Furthermore, we emit custom business metrics (`OrdersReceived`, `OrdersCompleted`, `OrdersFailed`, `ProcessingLatency`) using CloudWatch Embedded Metric Format (EMF) without incurring additional API call latency."
