# Order Processing Reliability & Verification Platform — Development Brief

Use this document as the starting prompt/context for the next development chat.

## Goal

Extend the existing `serverless-order-processing-service` into an **Order Processing Reliability & Verification Platform**. It must demonstrate that an event-driven order pipeline behaves correctly under normal operation and controlled failures.

Do not rewrite the existing order system. Extend it with the fewest moving parts necessary.

The project must be genuinely usable, not merely a collection of implementation exercises:

- deployable with Terraform;
- demonstrable through a browser and a desktop client;
- event-driven and serverless;
- bounded against accidental cost and abuse;
- able to run bounded verification against a deployed stack;
- clear about guarantees and limitations.

## Engineering style

Use pragmatic, minimal Python and Terraform. Prefer the standard library and existing dependencies. Do not add services, abstraction layers, or frameworks without a concrete requirement.

Favor deleting/avoiding code over designing for hypothetical future needs. A readable procedural function is preferred to a multi-file pattern.

## Non-negotiable constraints

### Cost

The architecture must be **designed to remain within applicable AWS Free Tier allowances under the documented demo workload**. It is not valid to claim that AWS costs are guaranteed to be zero.

Do not add EC2, ECS/Fargate, RDS, ElastiCache, OpenSearch, NAT Gateway, ALB, provisioned DynamoDB capacity, provisioned Lambda concurrency, Kubernetes, paid observability, paid databases/queues, commercial APIs, LLM APIs, or always-running servers.

Retain/enforce:

- API throttling and payload limits;
- DynamoDB TTL;
- seven-day CloudWatch log retention;
- AWS budget alert;
- bounded runner execution;
- bounded request/message counts;
- bounded failure injection;
- explicit cleanup/`terraform destroy` documentation.

### Security and product boundaries

Never put AWS credentials in a browser or desktop app.

**BYOK means Bring Your Own deployed stack**, not bring AWS credentials:

1. A user deploys this Terraform stack in their own AWS account.
2. They connect an app using that stack's API URL and an app-level token.
3. Their AWS credentials stay in their own local deployment workflow and never enter this project’s UI.

Keep the existing GitHub Actions deployment role access unchanged during development, as explicitly requested. Before public release, replace `AdministratorAccess` with a scoped deployment policy.

No public endpoint may create unlimited failure injections, execute arbitrary AWS actions, or run arbitrary/unbounded load tests.

## Product modes

### Hosted web showcase

GitHub Pages hosts a static showcase. It can show sample reports and, if retained, a very tightly throttled live order demo. It must not embed service tokens or AWS credentials.

A public endpoint cannot be made abuse-proof with throttle limits alone. Therefore the hosted site must not expose unrestricted verification execution.

### Desktop client: primary functional product

Create a lightweight desktop client only after the verification backend is functional. It connects to a user-owned deployed stack using API URL plus application token, and stores that configuration with OS secure storage where practical.

The desktop client provides the full workflow: submit/status orders, start bounded verification, inspect results, and view cost guardrails.

### Web BYOK: follow-up

The browser may accept a user-owned API URL/token for the current session. Explain that this is less secure than desktop secure storage. Do not persist secrets in source control or embed them in the hosted site.

## Existing system

Current repository components:

```text
API Gateway HTTP API
  -> ingest Lambda -> DynamoDB conditional order write -> SQS
  -> worker Lambda -> simulated fulfillment -> DynamoDB
  -> status Lambda -> order status

SQS source queue -> DLQ after three receives
DynamoDB on-demand table with TTL and StatusCreatedAtIndex
CloudWatch logs (7 days), alarms, dashboard, SNS budget/alerts
Terraform, pytest/Moto, GitHub Actions
```

Existing source areas:

- `src/ingest/handler.py`: validates input, idempotent order creation and SQS publication.
- `src/worker/handler.py`: partial batch failure worker.
- `src/worker/downstream.py`: deterministic simulated fulfillment.
- `src/common/dynamo.py`: DynamoDB operations.
- `src/common/failure_injection.py`: TTL-bound internal failure tokens.
- `src/verification/report.py`: measured-only text report renderer.
- `infra/`: Terraform.
- `docs/index.html`: GitHub Pages UI.

## Honest phase status

The original 16 phases remain the acceptance roadmap. Do not claim a phase complete merely because docs or unit tests exist.

| Phase | Status | Notes |
|---|---|---|
| 1 Audit | Mostly done | Audit/design documentation exists; keep reconciling code and docs. |
| 2 Invariants | Partial | Docs describe conditional transitions; current status updates are not conditional. |
| 3 Fulfillment | Done | Deterministic DynamoDB-backed fulfillment result is idempotent. |
| 4 Worker idempotency | Done | Retry-after-fulfillment test exists. |
| 5 Verification engine | Missing | No real engine yet. |
| 6 Required scenarios | Partial | Some behavior is unit-tested, but not run as structured live scenarios. |
| 7 Async verification | Missing | No API, run queue, runner, or run records. |
| 8 Frontend | Partial | Existing order UI; no verification UI. |
| 9 Failure injection | Partial | Internal primitive exists; a runner does not yet create/use it live. |
| 10 Observability | Partial | Order correlation flows ingest -> SQS -> worker; verification-run correlation is pending. |
| 11 Results | Partial | Renderer exists; no persisted/displayed reports. |
| 12 Cost safety | Partial | Infrastructure limits exist; required cost doc/UI are missing. |
| 13 Security | Partial | Validation/throttling exist; CORS/release IAM and app auth need work. |
| 14 Testing | Partial | Good unit coverage; missing verification API/runner/live scenario tests. |
| 15 CI/CD | Partial | CI works; manual verification only runs local Moto scenarios. |
| 16 Documentation | Partial | Required cost/failure/verification/benchmark docs are incomplete. |

## Completed implementation details

### Fulfillment and retries

- Fulfillment uses stable key `{orderId}:FULFILLMENT` and a conditional DynamoDB item.
- A worker retry after fulfillment success returns the saved result rather than creating a second logical fulfillment.
- SQS is at-least-once. Do not claim exactly-once processing.

### Failure injection

`common.failure_injection` stores internal DynamoDB token items. It supports:

- `WORKER` failure;
- `FULFILLMENT_FAIL`;
- `FULFILLMENT_DELAY` (maximum three seconds).

Tokens require verification run/scenario IDs, expire in 1–900 seconds, and affect 1–3 requests. There is deliberately no public API endpoint for token creation. The future verification runner must call this module directly.

### Correlation

Ingest generates/persists a `correlationId`, adds it to the SQS body, and worker logs append available:

```text
verification_run_id
scenario_id
order_id
idempotency_key
correlation_id
message_id
```

## Immediate implementation milestone

Implement the missing verification backend before building desktop packaging or broad frontend work.

Target flow:

```text
POST /verification/runs
  -> validate fixed scenario allowlist and bounded options
  -> create DynamoDB run record (QUEUED)
  -> send one SQS verification job
  -> return 202 with run ID

Verification runner Lambda
  -> mark run RUNNING
  -> run fixed bounded live scenarios against the deployed order API
  -> create internal failure tokens when a scenario requires them
  -> persist each scenario's structured result/evidence
  -> write measured-only aggregate report
  -> mark run COMPLETED or FAILED

GET /verification/runs/{runId}
GET /verification/runs/{runId}/results
```

### DynamoDB single-table additions

Reuse the existing table. Suggested keys:

```text
orderId = VERIFICATION#<runId>                 # run summary/status
orderId = VERIFICATION#<runId>#SCENARIO#<id>   # scenario result
orderId = FAILURE_INJECTION#<run>#<scenario>#<action>
```

All verification items need `expiresAt` (seven days is sufficient). Do not add another database.

### Verification queue

Add a dedicated SQS verification queue and DLQ. The runner event source should use a batch size of one, a short hard Lambda timeout, and redrive protection. This isolates verification work from customer order processing.

### API and authorization

Add only these verification routes:

- `POST /verification/runs`
- `GET /verification/runs/{runId}`
- `GET /verification/runs/{runId}/results`

The POST endpoint must require an application token. The static hosted web showcase must not contain that token. A desktop client or BYOK user supplies the token for their own deployment.

Do not add a failure-injection endpoint. The runner is the privileged component.

### Live scenario allowlist and hard limits

Implement only fixed scenarios:

1. `happy-path`
2. `duplicate-request`
3. `concurrent-duplicate`
4. `worker-failure`
5. `partial-batch-failure`
6. `dlq`
7. `redrive`
8. `downstream-failure`
9. `state-transition`
10. `small-load`

Limits are constants, not caller-controlled:

```text
duplicate/concurrent requests: <= 20
small load requests: <= 100
small load duration: <= 30 seconds
failure injection affected requests: <= 3
verification job: bounded Lambda timeout
```

If a scenario cannot safely run against the deployed API yet, do not fake a pass. Persist it as skipped/failed with evidence.

## Correctness work required before claiming the platform is real-world ready

1. Make `update_order_status` conditional and enforce allowed transitions. Do not leave docs claiming conditional transitions while code performs unconditional updates.
2. Implement run persistence before relying on `verification.report`.
3. Ensure the runner records only measured metrics. Omit unavailable p50/p95/p99 values.
4. Ensure a runner failure marks its run `FAILED` with useful error evidence.
5. Do not let a verification run affect unrelated order messages. Use distinct correlation/run/scenario IDs.
6. Add tests for handler validation, run lifecycle, runner behavior, expiry/limits, result retrieval, and invalid state transitions.

## Subsequent milestones

### Frontend

Extend `docs/index.html` after the backend works:

- submit and poll an order;
- start an authorized verification run;
- poll and render run progress/results;
- show scenario evidence and measured metrics;
- show a clear “Demo Cost Guardrails” section;
- link to cost documentation.

Avoid dashboards made of decorative cards, gradients, and fake metrics.

### Documentation

Create/update:

```text
docs/cost-safety.md
docs/failure-model.md
docs/verification-guide.md
docs/benchmark-methodology.md
docs/runbook.md
docs/architecture.md
README.md
```

Document actual resource costs/risks, workload assumptions, cleanup, `terraform destroy`, real failure guarantees, and the distinction between hosted showcase vs user-owned BYOK stack.

### Desktop then web BYOK

After the backend and UI are end-to-end functional, package the existing web UI as a lightweight desktop client (prefer Tauri over a larger Electron stack unless a concrete need requires Electron). Use OS secure storage for the endpoint/token where practical.

Web BYOK follows afterward; do not claim it has the same secret-storage protection as desktop.

### Release hardening

Before public release:

- replace wildcard CORS with explicit configured origins;
- narrow GitHub OIDC deployment permissions;
- verify least-privilege Lambda policies;
- keep live verification manually triggered in GitHub Actions;
- add a deploy/verify/destroy workflow only if it remains bounded and free-tier-friendly;
- remove unsupported “production-grade,” “highly available,” “exactly once,” and “$0 guaranteed” claims.

## Required validation at each change

Run appropriate checks after every implementation slice:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m ruff format --check src tests
.\.venv\Scripts\python.exe -m mypy src tests
.\.venv\Scripts\python.exe -m pytest
terraform -chdir=infra validate
```

Preserve existing user changes. Do not reset/discard unrelated work. Implement one milestone at a time, test it, then report the actual state without inflating claims.
