import json
import uuid
from typing import Any

from common.config import SERVICE_KEY, VERIFICATION_QUEUE_URL, logger
from common.sqs import get_sqs_client
from verification.storage import create_run, get_run, get_scenario_results

ALLOWED_SCENARIOS = frozenset(
    {
        "happy-path",
        "duplicate-request",
        "concurrent-duplicate",
        "worker-failure",
        "partial-batch-failure",
        "dlq",
        "redrive",
        "downstream-failure",
        "state-transition",
        "small-load",
    }
)
MAX_SCENARIOS_PER_RUN = len(ALLOWED_SCENARIOS)


def _response(code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _authorized(event: dict[str, Any]) -> bool:
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}
    return bool(SERVICE_KEY) and headers.get("x-service-key") == SERVICE_KEY


@logger.inject_lambda_context
def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    if not _authorized(event):
        return _response(401, {"error": "Unauthorized"})
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("rawPath", "")
    if method == "POST" and path == "/verification/runs":
        try:
            body = json.loads(event.get("body") or "{}")
            scenarios = body.get("scenarios", [])
            if (
                not isinstance(scenarios, list)
                or not scenarios
                or len(scenarios) > MAX_SCENARIOS_PER_RUN
            ):
                raise ValueError("scenarios must be a non-empty bounded list")
            if len(set(scenarios)) != len(scenarios) or any(
                item not in ALLOWED_SCENARIOS for item in scenarios
            ):
                raise ValueError("one or more scenarios are not allowed")
            if set(body) - {"scenarios"}:
                raise ValueError("options are fixed and may not be supplied")
        except (json.JSONDecodeError, ValueError) as err:
            return _response(422, {"error": "Invalid verification request", "message": str(err)})
        if not VERIFICATION_QUEUE_URL:
            return _response(503, {"error": "Verification queue is not configured"})
        run_id = str(uuid.uuid4())
        create_run(run_id, scenarios)
        get_sqs_client().send_message(
            QueueUrl=VERIFICATION_QUEUE_URL, MessageBody=json.dumps({"runId": run_id})
        )
        return _response(202, {"runId": run_id, "status": "QUEUED"})
    run_id = event.get("pathParameters", {}).get("runId")
    run = get_run(run_id) if run_id else None
    if not run:
        return _response(404, {"error": "Verification run not found"})
    if method == "GET" and path.endswith("/results"):
        return _response(200, {"run": run, "results": get_scenario_results(run_id)})
    if method == "GET":
        return _response(200, run)
    return _response(405, {"error": "Method not allowed"})
