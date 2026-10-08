# Failure Model and Guarantees

SQS standard queues provide at-least-once delivery. A message can be delivered more than once, including around a failed acknowledgement or redrive. The worker therefore uses a stable fulfillment key and persists the simulated fulfillment outcome before recording order completion.

Order status changes are conditional: `RECEIVED → PROCESSING → COMPLETED|FAILED|DLQ`; `PROCESSING → PROCESSING` supports retry; an explicit operator redrive resets `DLQ → RECEIVED`. A rejected transition is evidence of an invalid state change, not a successful verification result.

Failure injection is internal only. The verification runner creates TTL-bound DynamoDB tokens for a run and scenario; no HTTP endpoint creates tokens. Tokens are tagged by run and scenario, limiting their effect to the matching verification order. A runner does not claim success for an unavailable observation: it records `SKIPPED` or `FAILED` with evidence.
