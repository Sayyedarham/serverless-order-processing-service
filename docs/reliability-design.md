# Reliability Design

This document defines the order pipeline's reliability contract. It distinguishes the current baseline from the target behavior so documentation does not imply guarantees the code does not yet provide.

## Current Baseline

The current code conditionally creates one DynamoDB order item per UUIDv5 idempotency key, sends a new order to SQS, and skips worker messages only when the order is already `COMPLETED`. SQS retries failed records and moves them to the DLQ after the configured receive count.

These mechanisms do **not** currently guarantee durable enqueue after an ingest failure, enforced state transitions, or an order status that reflects DLQ arrival. See [audit.md](audit.md) for the pre-change findings and configuration details. The invariants below are the target contract; they are not claims that the baseline already satisfies them.

## Phase 3: Simulated Fulfillment

The worker now calls a deterministic in-process fulfillment simulation. It uses the stable key `{orderId}:FULFILLMENT` and stores a successful result as a separate item in the existing DynamoDB table. Repeated successful calls return the stored result. The operation item uses the existing table TTL with a 30-day expiration, longer than the configured source-queue plus DLQ retention window.

The production simulation always returns a deterministic successful result. Tests inject transient and permanent failures by replacing the worker dependency in-process; public order fields cannot select failure behavior.

This models an idempotent **simulated result**, not an external payment or shipping side effect. A real downstream provider must enforce the same key at the side-effect boundary. SQS remains at-least-once, and this change alone does not make order state transitions conditional.

## Phase 4: Worker Retry Window

The worker test simulates a crash after the fulfillment result is persisted but before the order can be marked `COMPLETED`. The first delivery returns its SQS item as failed and leaves the order `PROCESSING`; the retry uses the same fulfillment key, reuses the saved result, and completes the order. The test verifies there is still exactly one fulfillment result item.

This proves retry safety for the in-process simulation and its DynamoDB result record. It does not prove exactly-once execution or protect a real external side effect unless that provider honors the same idempotency key.

## Phase 5: Bounded DLQ Recovery

On the final configured SQS receive attempt, a transient failure marks the correlated order `DLQ` before returning the record as failed so SQS can move it to the DLQ. The operator redrive script requires an explicit message cap (maximum 100) and operator identity, resets only `DLQ` orders to `RECEIVED`, republishes their unchanged message, and then deletes the DLQ copy. Each operation is logged with an invocation run ID. A crash between publish and delete may duplicate delivery; the worker's stable fulfillment key handles that case. The recovery test routes an order to `DLQ`, removes its injected failure, redrives one message, and verifies `COMPLETED`.

This is an operator-run application-level redrive, not SQS's unbounded `StartMessageMoveTask`. Status and queue updates span DynamoDB and SQS and are not atomic; a failed publish can leave an order `RECEIVED` while its message remains in the DLQ. `RECEIVED` is eligible on a rerun so the operator can repair that interruption.

## Phase 6: Bounded Verification

The manual GitHub Actions verification workflow accepts only the fixed `retry-window` and `dlq-recovery` scenarios. Each run executes one local Moto test, creates no AWS work, has a 10-minute job deadline, and retains its result artifact for seven days. Transient failure injection exists only in the test process; the public API cannot request it. This keeps verification asynchronous at the workflow level and bounds its scenarios, order/message count, execution time, and result retention.

## Target Invariants

### 1. Idempotent order acceptance

- An idempotency key identifies one logical order within the documented key scope.
- Concurrent requests with the same key create at most one order item.
- Replays return the existing order and never create a second logical fulfillment.
- Reuse of a key with a different normalized request is rejected as a conflict; it must not silently return an order for different content.
- An HTTP `202` response is returned only after both the order and its work are durably recoverable. If enqueue publication has an ambiguous outcome, retry may publish a duplicate message; the worker and fulfillment operation must safely absorb it.

### 2. No accepted work is silently lost

- Every accepted order has durable order state and durable work available to the worker, or has an explicit terminal outcome.
- Temporary failures remain retryable. Exhausted messages are observable in the DLQ, and the order record reflects that state.
- Malformed or uncorrelatable messages are not silently acknowledged. They must be recorded as an explicit rejected/poison-message outcome or sent to the DLQ for inspection.
- SQS is at-least-once: duplicate delivery is expected and handled. The system does not claim exactly-once message delivery.

### 3. Valid, conditional state transitions

Order lifecycle states:

```text
RECEIVED -> PROCESSING -> COMPLETED
                 |             (terminal)
                 +-----------> FAILED
                 |             (terminal until operator redrive)
                 +-----------> DLQ
                               (terminal until operator redrive)

FAILED -> RECEIVED       explicit redrive only
DLQ    -> RECEIVED       explicit redrive only
```

- `RECEIVED -> PROCESSING` begins an attempt.
- A transient failure keeps the order retryable; another delivery may enter/re-enter `PROCESSING`.
- `COMPLETED` is terminal. No later delivery may regress it or repeat the fulfillment effect.
- `FAILED` records a non-retryable business failure. Reprocessing requires an explicit operator action.
- `DLQ` records exhausted delivery. A redrive changes it to `RECEIVED` (or a separately represented retry state) before the message is made available again.
- Writes that change lifecycle state use DynamoDB conditions so stale or concurrent workers cannot perform invalid regressions. Attempt counters and timestamps are updated atomically with each transition.
- Queue publication state is tracked separately from business lifecycle state. This allows a retry of an ingest request to repair an incomplete enqueue without claiming that an unqueued order is being processed.

### 4. Retry-safe fulfillment

- Each order's simulated fulfillment uses a stable operation key, `orderId + operation`.
- The fulfillment operation stores its result durably and conditionally creates it once. Repeated calls with the same key return that result.
- A worker can crash after fulfillment succeeds and before it writes `COMPLETED`; the next delivery receives the stored fulfillment result and can finish the order without creating another logical operation.
- This is an idempotent-effect guarantee for the simulated operation, not exactly-once SQS delivery or exactly-once execution.

### 5. DLQ recovery

- Exhausted messages remain inspectable in the DLQ and correlate to an order and message.
- DLQ arrival is observable and represented in order state.
- Redrive is explicit, bounded, and auditable. It resets only eligible orders/messages and preserves the fulfillment operation key so a prior successful effect is not repeated.
- A redrive test must demonstrate successful completion after the injected failure is removed.

### 6. Bounded verification and failure injection

- Verification requests create bounded asynchronous work; the HTTP request does not wait for the suite.
- Every run has a fixed scenario allowlist, request/message ceiling, execution deadline, and retention period.
- Failure injection is disabled by default, scoped to one verification run/scenario, limited by affected message count, and expires automatically.
- Public callers cannot select arbitrary operations, unbounded request counts, or persistent failure rates.

## Correlation Fields

Logs and verification results should carry the identifiers that exist for that operation:

```text
verification_run_id (verification only)
scenario_id          (verification only)
order_id
idempotency_key
correlation_id
message_id           (worker/SQS)
```

Fields should be passed in SQS message attributes/body as appropriate and included in structured logs. Request bodies and secrets should not be logged.

## Guarantee Language

Use these terms precisely:

- **At-least-once delivery:** SQS may deliver a message more than once; the worker must tolerate that.
- **Idempotent fulfillment:** repeated operation calls with the same stable key return one durable logical result.
- **No silent loss:** accepted work remains recoverable or reaches a documented terminal state, subject to the stated AWS service and retention assumptions.
- Do not claim **exactly once**, **zero cost**, or **high availability**. The target design controls duplicate effects through idempotency and documents cost assumptions; it cannot guarantee those broader properties.
