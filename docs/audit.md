# Existing System Audit

Audit date: 2026-10-07

This is a baseline audit before reliability-platform changes. It compares repository claims with the checked-in implementation and the AWS resources visible using the configured read-only inventory calls. No application, infrastructure, or deployment changes were made during this audit.

## Deployed Baseline

The repository contains Terraform state and live AWS resources matching its default `serverless-orders-prod` deployment in `us-east-1`. The live inventory confirms:

- API Gateway HTTP API `serverless-orders-api-prod` (`l67j9sjm76`)
- Three Python Lambda functions: ingest, worker, and status; plus a Lambda dependency layer and SQS event source mapping
- DynamoDB table `serverless-orders-prod`
- Main SQS queue and `serverless-orders-dlq-prod`
- CloudWatch log groups, five metric alarms, and a dashboard
- SNS alert topic, AWS Budget, IAM roles/policies, and GitHub Actions OIDC provider/role

No Terraform-managed EC2, ECS, RDS, NAT Gateway, or always-running application server appears in the checked-in state or tagged live-resource inventory. This confirms the current deployment only; it does not verify every account resource or establish future AWS pricing/free-tier eligibility. The GitHub Pages site is a static file in `docs/`.

## Implemented Behavior

- `POST /orders` validates a Pydantic request, enforces a 10 KiB decoded-body limit and required idempotency header, conditionally writes an order, then sends an SQS message.
- The order ID is UUIDv5 of the idempotency key. Conditional DynamoDB writes prevent two rows for the same derived key from being inserted concurrently.
- API Gateway has a default-stage throttle of 5 requests/second with burst 10. CORS allows `*`. `API_SHARED_KEY` defaults to empty, so the write API is public in the default deployment.
- DynamoDB is on-demand with a status/created-at GSI and TTL enabled; Lambda/API log groups declare seven-day retention. SQS is standard, with a 4-day source retention, 14-day DLQ retention, and `maxReceiveCount = 3`.
- The worker reports individual transient/unexpected failures using `ReportBatchItemFailures`; permanent simulated failures are marked `FAILED` and acknowledged. A completed order is skipped on redelivery.
- The downstream fulfillment is a local deterministic/random simulator. It does not persist an operation or accept/use a fulfillment idempotency key.
- The browser demo submits and polls real orders. It has no verification-run API or runner, and it does not expose AWS credentials.
- CI runs Ruff, mypy, and pytest. The deploy workflow runs Terraform plan for pull requests and apply on main pushes; it is not a manually triggered bounded verification workflow.

## Reliability Invariants Not Currently Met

1. **Accepted order may be stranded.** Ingest commits the order before calling SQS. If `SendMessage` fails, the handler errors after the row is written. A retry with the same key finds the row and takes the duplicate path, which does not send the message again. The order can remain `RECEIVED` indefinitely with no queued work.
2. **Fulfillment can repeat.** Worker checks only whether the order is already `COMPLETED`, then calls fulfillment and separately writes `COMPLETED`. A crash after fulfillment succeeds but before that write leaves the order eligible for a repeated fulfillment on SQS retry. The simulator currently makes no durable side effect, so tests do not reproduce this failure window.
3. **State transitions are not enforced.** `update_order_status` performs an unconditional DynamoDB update and can create a sparse item if the key is missing. There is no conditional transition graph. `PROCESSING` is set before fulfillment; transient failures leave the item at `PROCESSING`, including after it reaches the DLQ.
4. **DLQ is not an order terminal state.** SQS can move repeatedly failing messages to the DLQ, but the order item is not updated to a DLQ/terminal state. Redrive is an operator CLI procedure, not an automated or verified recovery flow.
5. **Some malformed records are silently acknowledged.** A valid JSON body without `orderId` is logged and returned as success, deleting the message. Malformed JSON instead raises into the retry path. These outcomes are inconsistent with a general no-silent-loss claim.
6. **Idempotency is key-only and global.** UUIDv5 is derived from the raw key alone, not customer/tenant or request content. Reusing a key with different content returns the existing order rather than detecting a payload mismatch. The implementation prevents duplicate order rows for a key, not duplicate downstream side effects.

## Documentation and Configuration Discrepancies

- README/design docs call the system “production-grade,” “highly available,” “strict”/“exactly-once,” and claim `$0` guaranteed. Those claims exceed the implementation and cannot be guaranteed by the budget alarm or current configuration.
- README says 10 KB requests are blocked by API Gateway. The 10 KiB check is in ingest Lambda; API Gateway stage configuration has throttling but no 10 KiB request-size rule.
- README/design docs describe idempotent fulfillment and automated DLQ redrive. Fulfillment has no idempotency storage, and redrive is a manual AWS CLI operation documented in the runbook.
- Architecture text describes all downstream errors retrying to DLQ. Permanent simulator errors are marked `FAILED` and acknowledged on the first attempt; only transient/unexpected errors are retried.
- Architecture/README describe worker status behavior as `PROCESSING -> COMPLETED/FAILED`; transient retry and DLQ paths leave status at `PROCESSING`.
- `docs/index.html` footer says 30-second visibility timeout, but Terraform configures 60 seconds. The UI’s lifecycle animation infers internal events from the HTTP response; it does not observe Lambda/SQS/DynamoDB directly.
- README benchmark table says 301 live requests, 5 requests/second, measured latency, 5/5 redriven messages, and `$0.00` idle cost. The checked-in artifacts are historical measurements, not a current run. `loadtest/k6_load_test.js` runs a fixed 5 RPS for 60 seconds (about 300 requests), and the chaos script submits five failing orders. Neither is exposed through the frontend; the load test is not capped at the requested 100 requests/30 seconds.
- Docs describe least-privilege GitHub deployment access, but Terraform attaches AWS `AdministratorAccess` to the GitHub Actions role. Its OIDC `sub` trust matches the repository wildcard across refs. The deploy workflow is triggered on pull requests as well as main pushes.
- Terraform declares a $1/month Budget with notifications. It is an alert, not a spending cap or automatic cleanup mechanism. CloudWatch alarms/dashboard, custom metrics, SNS, API traffic, and other usage may incur charges; a zero-cost result is not established by the repository.
- `downstream_failure_rate` is a string variable with no Terraform validation shown. The implementation uses it as a probability without range validation.

## Cost and Operational Risks

- Public API has throttling and an application payload check, but no daily quota or total verification-run budget. The current API is a public demo endpoint.
- The `sim-fail-transient` and `sim-fail-permanent` modes are selected by caller-controlled `customer_id`; these are not scoped to a verification run or bounded injection records. The stage throttle limits request rate but does not make failure injection operator-only.
- DynamoDB TTL deletion is asynchronous; seven-day TTL is not a precise retention deadline.
- CloudWatch dashboard, alarms, SNS, API access logs, and custom metrics are additional resources/usage beyond the compute path. Budget alerts can arrive after spend and do not stop traffic.
- Lambda logs use Powertools `log_event=True` on HTTP and SQS handlers, so request/message bodies may be written to CloudWatch logs. Retention is bounded in Terraform, but logged data is not minimized at source.
- Terraform state is local and ignored by Git. It exists in this checkout, but no remote state backend or state locking configuration is declared.

## Audit Scope Limits

Live resource names and existence were checked against AWS in `us-east-1`, alongside the local Terraform state. This was an inventory, not a full account-wide cost review, deployed configuration drift check, or billing-history analysis. The repository’s historical benchmark numbers were not re-run. No tests or load tests were run as part of this audit.
